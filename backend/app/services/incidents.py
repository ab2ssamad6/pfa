"""Incident correlation: anomalies -> incidents with an open/acknowledged/resolved lifecycle.

Rules (configurable):
  * debounce   - an incident opens only when >= K of the last N windows of a host are anomalous
  * grouping   - one active incident per host; an anomaly within GAP seconds of the incident's
                 last anomaly joins it. The suspected category is the dominant one among its
                 anomalies (category-keyed grouping would fragment one attack, because the model
                 confuses e.g. DoS/DDoS window-by-window).
  * resolution - auto-resolved after RESOLVE seconds without anomalies (measured in telemetry time,
                 so a source outage never "resolves" an attack); a recurrence opens a NEW incident.
  * linking    - Zabbix problems on the same host overlapping [opened-GAP, last_seen+GAP] are linked.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    ExternalEvent, Host, Incident, IncidentExternalLink, IncidentStatus, Prediction, Severity,
)

log = logging.getLogger(__name__)
ACTIVE = (IncidentStatus.open, IncidentStatus.acknowledged)
_LEVELS = [Severity.low, Severity.medium, Severity.high, Severity.critical]


@dataclass(frozen=True)
class IncidentRules:
    k: int = 3
    n: int = 5
    gap: timedelta = timedelta(seconds=60)
    resolve_after: timedelta = timedelta(seconds=120)


@dataclass
class CorrelationStats:
    processed: int = 0
    opened: int = 0
    attached: int = 0
    resolved: int = 0


def compute_severity(max_score: float, anomaly_count: int, criticality: str) -> Severity:
    lvl = 0 if max_score < 0.9 else 1 if max_score < 0.97 else 2
    if anomaly_count >= 30:
        lvl += 1
    if criticality == "critical":
        lvl += 1
    elif criticality == "low":
        lvl -= 1
    return _LEVELS[max(0, min(lvl, 3))]


def _attach(inc: Incident, p: Prediction, criticality: str) -> None:
    p.incident_id = inc.id
    inc.anomaly_count += 1
    inc.max_score = max(inc.max_score, p.p_attack)
    inc.sum_score += p.p_attack
    inc.last_seen_at = max(inc.last_seen_at, p.ts)
    counts = Counter(inc.category_counts or {})
    counts[p.category] += 1
    inc.category_counts = dict(counts)
    inc.category = counts.most_common(1)[0][0]
    inc.severity = compute_severity(inc.max_score, inc.anomaly_count, criticality)


async def correlate(session: AsyncSession, rules: IncidentRules, batch: int = 5000) -> CorrelationStats:
    """Drain all uncorrelated predictions (in batches), then auto-resolve and link Zabbix events."""
    st = CorrelationStats()
    while True:
        n = await _correlate_batch(session, rules, batch, st)
        if n < batch:
            break
    await _auto_resolve(session, rules, st)
    await _link_external(session, rules)
    await session.commit()
    return st


async def _correlate_batch(session: AsyncSession, rules: IncidentRules, batch: int, st: CorrelationStats) -> int:
    preds = (await session.scalars(select(Prediction).where(Prediction.correlated.is_(False))
                                   .order_by(Prediction.ts, Prediction.window_id).limit(batch))).all()
    if not preds:
        return 0
    crit = dict((await session.execute(select(Host.id, Host.criticality))).all())
    active: dict[int, Incident] = {
        i.host_id: i for i in (await session.scalars(select(Incident).where(Incident.status.in_(ACTIVE)))).all()}

    for p in preds:
        p.correlated = True
        st.processed += 1
        if not p.is_anomaly:
            continue
        inc = active.get(p.host_id)
        if inc is not None and p.ts - inc.last_seen_at <= rules.gap:
            _attach(inc, p, crit.get(p.host_id, "medium"))
            st.attached += 1
            continue
        if inc is not None:     # quiet for longer than GAP: close it (never later than this anomaly)
            _resolve(inc, min(inc.last_seen_at + rules.resolve_after, p.ts), "auto")
            st.resolved += 1
            active.pop(p.host_id)
        recent = (await session.scalars(select(Prediction).where(
            Prediction.host_id == p.host_id, Prediction.ts <= p.ts).order_by(Prediction.ts.desc())
            .limit(rules.n))).all()
        if sum(r.is_anomaly for r in recent) < rules.k:
            continue
        inc = Incident(host_id=p.host_id, status=IncidentStatus.open, severity=Severity.low, category=p.category,
                       category_counts={}, opened_at=min(r.ts for r in recent if r.is_anomaly), last_seen_at=p.ts,
                       anomaly_count=0, max_score=0.0, sum_score=0.0, model_version_id=p.model_version_id)
        session.add(inc)
        await session.flush()
        for r in sorted((r for r in recent if r.is_anomaly and r.incident_id is None), key=lambda r: r.ts):
            _attach(inc, r, crit.get(p.host_id, "medium"))
        active[p.host_id] = inc
        st.opened += 1
        log.info("incident %s opened on host %s (%s)", inc.id, p.host_id, inc.category)

    await session.commit()
    return len(preds)


def _resolve(inc: Incident, when: datetime, how: str) -> None:
    inc.status = IncidentStatus.resolved
    inc.resolved_at = when
    inc.resolution = how


async def _auto_resolve(session: AsyncSession, rules: IncidentRules, st: CorrelationStats) -> None:
    # "now" per host = newest scored window for that host (telemetry time, not wall-clock)
    newest = dict((await session.execute(select(Prediction.host_id, func.max(Prediction.ts))
                                         .where(Prediction.correlated).group_by(Prediction.host_id))).all())
    for inc in (await session.scalars(select(Incident).where(Incident.status.in_(ACTIVE)))).all():
        host_now = newest.get(inc.host_id)
        if host_now is not None and host_now - inc.last_seen_at > rules.resolve_after:
            _resolve(inc, inc.last_seen_at + rules.resolve_after, "auto")
            st.resolved += 1
            log.info("incident %s auto-resolved", inc.id)


async def _link_external(session: AsyncSession, rules: IncidentRules) -> None:
    incs = (await session.scalars(select(Incident).where(or_(
        Incident.status.in_(ACTIVE), Incident.updated_at >= func.now() - timedelta(minutes=10))))).all()
    for inc in incs:
        lo = inc.opened_at - rules.gap
        hi = (inc.resolved_at or inc.last_seen_at) + rules.gap
        ev_ids = (await session.scalars(select(ExternalEvent.id).where(
            ExternalEvent.host_id == inc.host_id, ExternalEvent.clock <= hi,
            or_(ExternalEvent.recovered_at.is_(None), ExternalEvent.recovered_at >= lo)))).all()
        for eid in ev_ids:
            await session.execute(insert(IncidentExternalLink).values(incident_id=inc.id, external_event_id=eid)
                                  .on_conflict_do_nothing())


async def acknowledge(session: AsyncSession, incident_id: int, note: str | None, now: datetime) -> Incident:
    inc = await session.get(Incident, incident_id)
    if inc is None:
        raise LookupError(incident_id)
    if inc.status != IncidentStatus.open:
        raise ValueError(f"cannot acknowledge an incident in status '{inc.status.value}'")
    inc.status, inc.acknowledged_at = IncidentStatus.acknowledged, now
    if note:
        inc.note = note
    await session.commit()
    return inc


async def resolve_manually(session: AsyncSession, incident_id: int, note: str | None, now: datetime) -> Incident:
    inc = await session.get(Incident, incident_id)
    if inc is None:
        raise LookupError(incident_id)
    if inc.status == IncidentStatus.resolved:
        raise ValueError("incident already resolved")
    _resolve(inc, now, "manual")
    if note:
        inc.note = note
    await session.commit()
    return inc
