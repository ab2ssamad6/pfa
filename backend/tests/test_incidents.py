"""Incident grouping rules on hand-crafted prediction sequences."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import (
    ExternalEvent, FeatureWindow, Host, Incident, IncidentExternalLink, IncidentStatus, Item, ItemKind, ModelVersion,
    Prediction, Severity,
)
from app.services.incidents import IncidentRules, acknowledge, compute_severity, correlate, resolve_manually

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
RULES = IncidentRules(k=3, n=5, gap=timedelta(seconds=60), resolve_after=timedelta(seconds=120))


@pytest.fixture
async def env(sessions):
    async with sessions() as s:
        h = Host(source_ref="1", name="h", display_name="H", criticality="medium", tags={})
        s.add(h)
        await s.flush()
        it = Item(host_id=h.id, source_ref="11", key="netad.flow.features", name="f", kind=ItemKind.feature,
                  value_type=4, units="")
        mv = ModelVersion(version="v", algorithm="a", path="/", sha256="x", threshold=0.5, features=[], categories=[],
                          metadata_json={}, is_active=True)
        s.add_all([it, mv])
        await s.commit()
        return {"host": h.id, "item": it.id, "mv": mv.id}


async def feed(sessions, env, pattern: str, start: datetime, step: int = 2, category: str = "DDoS"):
    """pattern: 'x' anomaly, '.' normal; one window per `step` seconds."""
    async with sessions() as s:
        for i, ch in enumerate(pattern):
            ts = start + timedelta(seconds=i * step)
            w = FeatureWindow(host_id=env["host"], item_id=env["item"], ts=ts, ns=0, features={})
            s.add(w)
            await s.flush()
            s.add(Prediction(window_id=w.id, host_id=env["host"], ts=ts, model_version_id=env["mv"],
                             p_attack=0.99 if ch == "x" else 0.05, category=category, category_proba={},
                             is_anomaly=ch == "x"))
        await s.commit()
        return await correlate(s, RULES)


async def incidents(sessions):
    async with sessions() as s:
        return (await s.scalars(select(Incident).order_by(Incident.id))).all()


async def test_isolated_anomalies_do_not_open_incident(sessions, env):
    st = await feed(sessions, env, "..x...x....x..x.....", T)
    assert st.opened == 0 and await incidents(sessions) == []


async def test_debounce_opens_and_backfills_recent_anomalies(sessions, env):
    st = await feed(sessions, env, "....x.xx", T)
    [inc] = await incidents(sessions)
    assert st.opened == 1 and inc.anomaly_count == 3
    assert inc.opened_at == T + timedelta(seconds=8)   # first anomaly of the debounce window
    assert inc.status == IncidentStatus.open


async def test_gap_grouping_and_auto_resolve(sessions, env):
    # burst, a 40 s pause (within GAP), burst, then 130 s of normal traffic (> RESOLVE)
    await feed(sessions, env, "xxxxx" + "." * 20 + "xxxx" + "." * 65, T)
    [inc] = await incidents(sessions)
    assert inc.anomaly_count == 9
    assert inc.status == IncidentStatus.resolved and inc.resolution == "auto"
    assert inc.resolved_at == inc.last_seen_at + RULES.resolve_after


async def test_recurrence_after_long_gap_is_new_incident(sessions, env):
    await feed(sessions, env, "xxxx" + "." * 40 + "xxxx", T)   # 80 s pause > GAP
    a, b = await incidents(sessions)
    assert a.status == IncidentStatus.resolved and b.status == IncidentStatus.open
    assert a.resolved_at <= b.opened_at


async def test_large_backlog_is_fully_drained(sessions, env):
    from app.services import incidents as svc
    async with sessions() as s:
        for i, ch in enumerate("xxxx" + "." * 80):
            ts = T + timedelta(seconds=i * 2)
            w = FeatureWindow(host_id=env["host"], item_id=env["item"], ts=ts, ns=0, features={})
            s.add(w)
            await s.flush()
            s.add(Prediction(window_id=w.id, host_id=env["host"], ts=ts, model_version_id=env["mv"],
                             p_attack=0.99 if ch == "x" else 0.05, category="DDoS", category_proba={},
                             is_anomaly=ch == "x"))
        await s.commit()
        st = await svc.correlate(s, RULES, batch=7)      # many small batches
    assert st.processed == 84
    [inc] = await incidents(sessions)
    assert inc.status == IncidentStatus.resolved


async def test_dominant_category(sessions, env):
    await feed(sessions, env, "xxx", T, category="DoS")
    await feed(sessions, env, "xxxxx", T + timedelta(seconds=6), category="DDoS")
    [inc] = await incidents(sessions)
    assert inc.category == "DDoS" and inc.category_counts == {"DoS": 3, "DDoS": 5}


async def test_lifecycle_transitions(sessions, env):
    await feed(sessions, env, "xxx", T)
    [inc] = await incidents(sessions)
    async with sessions() as s:
        inc = await acknowledge(s, inc.id, "looking", T)
        assert inc.status == IncidentStatus.acknowledged and inc.note == "looking"
        with pytest.raises(ValueError):
            await acknowledge(s, inc.id, None, T)
        inc = await resolve_manually(s, inc.id, "false positive", T)
        assert inc.status == IncidentStatus.resolved and inc.resolution == "manual"
        with pytest.raises(ValueError):
            await resolve_manually(s, inc.id, None, T)
        with pytest.raises(LookupError):
            await acknowledge(s, 9999, None, T)


async def test_acknowledged_incident_keeps_growing(sessions, env):
    await feed(sessions, env, "xxx", T)
    [inc] = await incidents(sessions)
    async with sessions() as s:
        await acknowledge(s, inc.id, None, T)
    await feed(sessions, env, "xx", T + timedelta(seconds=6))
    [inc] = await incidents(sessions)
    assert inc.status == IncidentStatus.acknowledged and inc.anomaly_count == 5


async def test_external_events_linked_by_host_and_time(sessions, env):
    async with sessions() as s:
        s.add_all([
            ExternalEvent(source_ref="e1", host_id=env["host"], name="overlap", severity=4, clock=T + timedelta(seconds=5),
                          recovered_at=None, tags={}),
            ExternalEvent(source_ref="e2", host_id=env["host"], name="old", severity=3, clock=T - timedelta(hours=2),
                          recovered_at=T - timedelta(hours=1), tags={}),
        ])
        await s.commit()
    await feed(sessions, env, "xxxx", T)
    async with sessions() as s:
        names = (await s.scalars(select(ExternalEvent.name).join(IncidentExternalLink))).all()
    assert names == ["overlap"]


@pytest.mark.parametrize("score,count,crit,expected", [
    (0.85, 3, "medium", Severity.low), (0.95, 3, "medium", Severity.medium), (0.99, 3, "medium", Severity.high),
    (0.99, 40, "medium", Severity.critical), (0.85, 3, "critical", Severity.medium), (0.99, 40, "critical", Severity.critical),
    (0.85, 3, "low", Severity.low),
])
def test_severity(score, count, crit, expected):
    assert compute_severity(score, count, crit) == expected
