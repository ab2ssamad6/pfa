from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import FeatureWindow, Host, Incident, IncidentStatus, ModelVersion, PipelineRun, Prediction, SourceHealth
from ..deps import get_session
from ..schemas import HealthOut, LastCycle, ModelSummary, Overview, SourceHealthOut

router = APIRouter(prefix="/api", tags=["system"])
WORKER_STALE_AFTER = timedelta(seconds=30)


async def build_health(s: AsyncSession) -> HealthOut:
    try:
        await s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return HealthOut(status="down", database=False, source=None, model=None, worker_last_cycle=None,
                         worker_stale=True)
    src = (await s.scalars(select(SourceHealth).order_by(SourceHealth.updated_at.desc()))).first()
    mv = (await s.scalars(select(ModelVersion).where(ModelVersion.is_active))).first()
    last = await s.scalar(select(func.max(PipelineRun.finished_at)))
    stale = last is None or datetime.now(timezone.utc) - last > WORKER_STALE_AFTER
    status = "ok"
    if stale or mv is None or src is None or src.state == "down":
        status = "down" if (stale or mv is None) else "degraded"
    elif src.state == "degraded":
        status = "degraded"
    return HealthOut(
        status=status, database=True, source=SourceHealthOut.model_validate(src) if src else None,
        model=ModelSummary(version=mv.version, algorithm=mv.algorithm, threshold=mv.threshold,
                           loaded_at=mv.loaded_at) if mv else None,
        worker_last_cycle=last, worker_stale=stale)


@router.get("/health", response_model=HealthOut)
async def health(s: AsyncSession = Depends(get_session)):
    return await build_health(s)


@router.get("/pipeline/runs", response_model=list[LastCycle])
async def pipeline_runs(limit: int = 20, s: AsyncSession = Depends(get_session)):
    rows = (await s.scalars(select(PipelineRun).order_by(PipelineRun.id.desc()).limit(min(limit, 200)))).all()
    return [LastCycle.model_validate(r) for r in rows]


@router.get("/overview", response_model=Overview)
async def overview(s: AsyncSession = Depends(get_session)):
    latest = await s.scalar(select(func.max(FeatureWindow.ts)))
    # "last 15 minutes" is relative to the newest telemetry, so replayed/backfilled data reads sensibly
    ref = latest or datetime.now(timezone.utc)
    since = ref - timedelta(minutes=15)
    counts = dict((await s.execute(select(Incident.status, func.count()).group_by(Incident.status))).all())
    resolved_24h = await s.scalar(select(func.count()).select_from(Incident).where(
        Incident.status == IncidentStatus.resolved, Incident.resolved_at >= ref - timedelta(hours=24)))
    newest_pred = await s.scalar(select(func.max(Prediction.ts)))
    lag = (datetime.now(timezone.utc) - newest_pred).total_seconds() if newest_pred else None
    return Overview(
        hosts=await s.scalar(select(func.count()).select_from(Host).where(Host.active)) or 0,
        incidents_open=counts.get(IncidentStatus.open, 0),
        incidents_acknowledged=counts.get(IncidentStatus.acknowledged, 0),
        incidents_resolved_24h=resolved_24h or 0,
        windows_last_15m=await s.scalar(select(func.count()).select_from(FeatureWindow).where(FeatureWindow.ts >= since)) or 0,
        anomalies_last_15m=await s.scalar(select(func.count()).select_from(Prediction).where(
            Prediction.is_anomaly, Prediction.ts >= since)) or 0,
        latest_window_at=latest, pipeline_lag_seconds=lag, health=await build_health(s))
