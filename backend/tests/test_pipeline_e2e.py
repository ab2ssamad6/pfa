"""End-to-end: mock Zabbix -> adapter -> ingestion -> real RF model -> incidents -> REST API.

No external Zabbix, no fabricated predictions: the trained bundle in artifacts/models scores
windows replayed from the held-out test split.
"""
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.main import create_app
from app.db.models import FeatureWindow, Host, Incident, Prediction
from app.worker import Worker


@pytest.fixture
async def worked(sessions, source, settings, clock):
    w = Worker(settings, sessions, source, clock=clock.dt)
    await w.start()
    run = await w.cycle()
    return w, run


async def _api(settings, sessions):
    app = create_app(settings)
    app.state.sessions = sessions
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def test_first_cycle_ingests_scores_and_correlates(worked, sessions):
    w, run = worked
    assert run.error is None
    assert run.windows_ingested == 3 * 1801            # 1 h backfill, 2 s windows, 3 hosts
    assert run.predictions == run.windows_ingested     # every window scored
    async with sessions() as s:
        rows = (await s.execute(select(Host.name, Incident.category, Incident.status, Incident.anomaly_count)
                                .join(Host).order_by(Incident.opened_at))).all()
    by_host = {}
    for name, cat, status, n in rows:
        by_host.setdefault(name, []).append((cat, status.value, n))
    # scenario loop 1 (fully in the past): recon on lan-a, DDoS on pfSense
    assert any(c == "Recon" and n >= 20 for c, _, n in by_host["lan-a-core"]), by_host
    assert any(c in ("DDoS", "DoS") and n >= 50 for c, _, n in by_host["pfsense-edge"]), by_host
    # loop 1 ended 180 s before "now": every loop-1 incident must already be auto-resolved
    assert all(st == "resolved" for h in ("pfsense-edge", "lan-b-core") for _, st, _ in by_host.get(h, []))


async def test_benign_backfill_has_few_false_incidents(worked, sessions, mock_app):
    """Before the scenario starts the replay is 100% benign: incidents there are false positives."""
    sc = mock_app.state.scenario
    from datetime import datetime, timezone
    start = datetime.fromtimestamp(sc.start, tz=timezone.utc)
    async with sessions() as s:
        windows = await s.scalar(select(func.count()).select_from(Prediction).where(Prediction.ts < start))
        fp = await s.scalar(select(func.count()).select_from(Prediction).where(Prediction.ts < start, Prediction.is_anomaly))
        false_inc = await s.scalar(select(func.count()).select_from(Incident).where(Incident.opened_at < start))
    assert fp / windows < 0.03          # model FPR ~1% at the chosen threshold
    assert false_inc <= 1               # 3-of-5 debounce suppresses isolated false positives


async def test_incremental_cycle_and_outage(worked, sessions, clock, mock_app):
    w, _ = worked
    clock.t += 6
    run = await w.cycle()
    assert run.windows_ingested == 3 * 3 and run.predictions == 9
    TestClient(mock_app).post("/_scenario/outage", params={"seconds": 100})
    for _ in range(3):
        clock.t += 2
        run = await w.cycle()
        assert run.error and "503" in run.error
    assert w.next_delay() > w.s.poll_interval_seconds   # exponential backoff
    async with sessions() as s:
        from app.db.models import SourceHealth
        h = await s.get(SourceHealth, "zabbix")
        assert h.state == "down" and h.consecutive_failures == 3
    clock.t += 100
    run = await w.cycle()
    assert run.error is None and run.windows_ingested == 3 * 53   # gap backfilled from watermark
    async with sessions() as s:
        assert (await s.get(SourceHealth, "zabbix", populate_existing=True)).state == "up"


async def test_rest_api_over_pipeline_results(worked, settings, sessions):
    async with await _api(settings, sessions) as c:
        hosts = (await c.get("/api/hosts")).json()
        assert len(hosts) == 3 and all(h["last_p_attack"] is not None for h in hosts)
        edge = next(h for h in hosts if h["name"] == "pfsense-edge")
        scores = (await c.get(f"/api/hosts/{edge['id']}/scores", params={"minutes": 60})).json()
        assert 0 < len(scores) <= 1500                    # downsampled
        metrics = (await c.get(f"/api/hosts/{edge['id']}/metrics", params={"minutes": 30})).json()
        assert {m["key"] for m in metrics} >= {"pfsense.state.table.current"} and metrics[0]["points"]

        page = (await c.get("/api/incidents")).json()
        assert page["total"] >= 2
        inc_id = next(i["id"] for i in page["items"] if i["host_name"] == "pfSense Edge Firewall")
        detail = (await c.get(f"/api/incidents/{inc_id}")).json()
        assert detail["anomalies"] and detail["timeline"]
        assert any("pfSense" in e["name"] for e in detail["events"])   # Zabbix problems linked

        open_ = (await c.get("/api/incidents", params={"status": "open"})).json()["items"]
        if open_:
            r = await c.post(f"/api/incidents/{open_[0]['id']}/acknowledge", json={"note": "checking"})
            assert r.status_code == 200 and r.json()["status"] == "acknowledged"
            assert (await c.post(f"/api/incidents/{open_[0]['id']}/acknowledge", json={})).status_code == 409
            r = await c.post(f"/api/incidents/{open_[0]['id']}/resolve", json={"note": "done"})
            assert r.json()["status"] == "resolved" and r.json()["resolution"] == "manual"
        assert (await c.get("/api/incidents/99999")).status_code == 404

        anomalies = (await c.get("/api/anomalies", params={"limit": 10})).json()
        assert anomalies["total"] > 0 and len(anomalies["items"]) == 10
        assert (await c.get("/api/events")).json()
        model = (await c.get("/api/model")).json()
        assert model["algorithm"] == "random_forest" and model["test"]["binary"]["recall"] > 0.9
        ov = (await c.get("/api/overview")).json()
        assert ov["hosts"] == 3 and ov["windows_last_15m"] > 0
        health = (await c.get("/api/health")).json()
        assert health["database"] and health["source"]["state"] == "up" and health["model"]
        assert (await c.get("/api/demo/live-accuracy")).status_code == 404   # disabled by default


async def test_invalid_window_is_flagged_not_dropped(worked, sessions):
    w, _ = worked
    async with sessions() as s:
        some = (await s.scalars(select(FeatureWindow).limit(1))).first()
        bad = FeatureWindow(host_id=some.host_id, item_id=some.item_id, ts=some.ts, ns=some.ns + 1,
                            features={"Rate": 1.0})
        s.add(bad)
        await s.commit()
        bad_id = bad.id
    run = await w.cycle()
    async with sessions() as s:
        bad = await s.get(FeatureWindow, bad_id)
        assert bad.invalid_reason and "missing features" in bad.invalid_reason
        assert await s.get(Prediction, bad_id) is None
