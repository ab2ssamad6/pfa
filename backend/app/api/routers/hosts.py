from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import FeatureWindow, Host, Incident, Item, ItemKind, MetricSample, Prediction
from ...services.incidents import ACTIVE
from ..deps import get_session
from ..schemas import HostOut, HostStatus, MetricPoint, MetricSeries, ScorePoint

router = APIRouter(prefix="/api/hosts", tags=["hosts"])
MAX_POINTS = 1500


async def _host(s: AsyncSession, host_id: int) -> Host:
    h = await s.get(Host, host_id)
    if h is None:
        raise HTTPException(404, f"host {host_id} not found")
    return h


async def _ref_time(s: AsyncSession, host_id: int):
    return await s.scalar(select(func.max(FeatureWindow.ts)).where(FeatureWindow.host_id == host_id))


@router.get("", response_model=list[HostStatus])
async def list_hosts(s: AsyncSession = Depends(get_session)):
    out = []
    for h in (await s.scalars(select(Host).order_by(Host.id))).all():
        last = (await s.execute(select(Prediction.ts, Prediction.p_attack).where(Prediction.host_id == h.id)
                                .order_by(Prediction.ts.desc()).limit(1))).first()
        active = await s.scalar(select(func.count()).select_from(Incident).where(
            Incident.host_id == h.id, Incident.status.in_(ACTIVE)))
        anomalies = 0
        if last:
            anomalies = await s.scalar(select(func.count()).select_from(Prediction).where(
                Prediction.host_id == h.id, Prediction.is_anomaly, Prediction.ts >= last[0] - timedelta(minutes=15)))
        out.append(HostStatus(**HostOut.model_validate(h).model_dump(), last_window_at=last[0] if last else None,
                              last_p_attack=last[1] if last else None, active_incidents=active or 0,
                              anomalies_last_15m=anomalies or 0))
    return out


@router.get("/{host_id}", response_model=HostOut)
async def get_host(host_id: int, s: AsyncSession = Depends(get_session)):
    return await _host(s, host_id)


@router.get("/{host_id}/scores", response_model=list[ScorePoint])
async def host_scores(host_id: int, minutes: int = Query(30, ge=1, le=24 * 60), s: AsyncSession = Depends(get_session)):
    await _host(s, host_id)
    ref = await _ref_time(s, host_id)
    if ref is None:
        return []
    return await score_timeline(s, host_id, ref - timedelta(minutes=minutes), ref)


async def score_timeline(s: AsyncSession, host_id: int, start, end) -> list[ScorePoint]:
    span = max((end - start).total_seconds(), 1)
    bucket = max(int(span // MAX_POINTS) + 1, 1)
    if bucket <= 2:
        rows = (await s.execute(select(Prediction.ts, Prediction.p_attack, Prediction.is_anomaly, Prediction.category)
                                .where(Prediction.host_id == host_id, Prediction.ts >= start, Prediction.ts <= end)
                                .order_by(Prediction.ts))).all()
        return [ScorePoint(ts=r[0], p_attack=r[1], is_anomaly=r[2], category=r[3]) for r in rows]
    # downsample: max score per bucket keeps attack peaks visible
    rows = (await s.execute(text(
        "SELECT date_bin(make_interval(secs => :b), ts, TIMESTAMPTZ '2000-01-01') AS t, max(p_attack), bool_or(is_anomaly) "
        "FROM predictions WHERE host_id = :h AND ts BETWEEN :a AND :e GROUP BY t ORDER BY t"),
        {"b": bucket, "h": host_id, "a": start, "e": end})).all()
    return [ScorePoint(ts=r[0], p_attack=r[1], is_anomaly=r[2]) for r in rows]


@router.get("/{host_id}/metrics", response_model=list[MetricSeries])
async def host_metrics(host_id: int, minutes: int = Query(30, ge=1, le=24 * 60), s: AsyncSession = Depends(get_session)):
    await _host(s, host_id)
    items = (await s.scalars(select(Item).where(Item.host_id == host_id, Item.kind == ItemKind.metric)
                             .order_by(Item.key))).all()
    out = []
    for it in items:
        ref = await s.scalar(select(func.max(MetricSample.ts)).where(MetricSample.item_id == it.id))
        pts = []
        if ref is not None:
            rows = (await s.execute(select(MetricSample.ts, MetricSample.value).where(
                MetricSample.item_id == it.id, MetricSample.ts >= ref - timedelta(minutes=minutes))
                .order_by(MetricSample.ts))).all()
            step = max(len(rows) // MAX_POINTS, 1)
            pts = [MetricPoint(ts=r[0], value=r[1]) for r in rows[::step]]
        out.append(MetricSeries(item_id=it.id, key=it.key, name=it.name, units=it.units, points=pts))
    return out
