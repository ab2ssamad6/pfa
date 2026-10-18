"""Retention and source-health bookkeeping."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import FeatureWindow, IncidentStatus, Incident, MetricSample, PipelineRun, SourceHealth


async def apply_retention(session: AsyncSession, now: datetime, days: int) -> dict[str, int]:
    """Delete raw telemetry older than `days`. Windows still referenced by an incident are kept."""
    cutoff = now - timedelta(days=days)
    from ..db.models import Prediction
    keep = select(Prediction.window_id).where(Prediction.incident_id.is_not(None))
    w = await session.execute(delete(FeatureWindow).where(FeatureWindow.ts < cutoff, FeatureWindow.id.not_in(keep)))
    m = await session.execute(delete(MetricSample).where(MetricSample.ts < cutoff))
    r = await session.execute(delete(PipelineRun).where(PipelineRun.started_at < cutoff))
    i = await session.execute(delete(Incident).where(Incident.status == IncidentStatus.resolved,
                                                     Incident.resolved_at < now - timedelta(days=days * 4)))
    await session.commit()
    return {"windows": w.rowcount, "metrics": m.rowcount, "runs": r.rowcount, "incidents": i.rowcount}


async def record_health(session: AsyncSession, source: str, ok: bool, now: datetime, error: str | None = None,
                        down_after: int = 3) -> SourceHealth:
    cur = await session.get(SourceHealth, source)
    failures = 0 if ok else (cur.consecutive_failures + 1 if cur else 1)
    state = "up" if ok else ("down" if failures >= down_after else "degraded")
    values = {"state": state, "consecutive_failures": failures, "last_error": None if ok else error}
    if ok:
        values["last_ok_at"] = now
    await session.execute(insert(SourceHealth).values(source=source, **values)
                          .on_conflict_do_update(index_elements=[SourceHealth.source], set_=values))
    await session.commit()
    return await session.get(SourceHealth, source, populate_existing=True)
