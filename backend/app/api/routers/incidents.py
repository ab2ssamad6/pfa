from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import ExternalEvent, Host, Incident, IncidentExternalLink, IncidentStatus, Prediction
from ...services import incidents as svc
from ..deps import get_session
from ..schemas import (
    AnomalyOut, AnomalyPage, ExternalEventOut, IncidentAction, IncidentDetail, IncidentOut, IncidentPage,
)
from .hosts import score_timeline

router = APIRouter(prefix="/api", tags=["incidents"])


def _inc_out(inc: Incident, host_name: str, linked: int = 0) -> IncidentOut:
    o = IncidentOut.model_validate(inc)
    o.status, o.severity = inc.status.value, inc.severity.value
    o.host_name = host_name
    o.mean_score = inc.sum_score / inc.anomaly_count if inc.anomaly_count else 0.0
    o.linked_events = linked
    return o


@router.get("/incidents", response_model=IncidentPage)
async def list_incidents(status: IncidentStatus | None = None, host_id: int | None = None,
                         limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                         s: AsyncSession = Depends(get_session)):
    q = select(Incident, Host.display_name).join(Host)
    cq = select(func.count()).select_from(Incident)
    if status:
        q, cq = q.where(Incident.status == status), cq.where(Incident.status == status)
    if host_id:
        q, cq = q.where(Incident.host_id == host_id), cq.where(Incident.host_id == host_id)
    rows = (await s.execute(q.order_by(Incident.opened_at.desc()).limit(limit).offset(offset))).all()
    links = dict((await s.execute(select(IncidentExternalLink.incident_id, func.count())
                                  .where(IncidentExternalLink.incident_id.in_([r[0].id for r in rows]))
                                  .group_by(IncidentExternalLink.incident_id))).all()) if rows else {}
    return IncidentPage(total=await s.scalar(cq) or 0,
                        items=[_inc_out(i, name, links.get(i.id, 0)) for i, name in rows])


def _anom(p: Prediction, host_name: str) -> AnomalyOut:
    return AnomalyOut(window_id=p.window_id, host_id=p.host_id, host_name=host_name, ts=p.ts, p_attack=p.p_attack,
                      category=p.category, category_proba=p.category_proba, incident_id=p.incident_id)


def _event_out(e: ExternalEvent, host_name: str | None) -> ExternalEventOut:
    o = ExternalEventOut.model_validate(e)
    o.host_name = host_name
    return o


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident(incident_id: int, s: AsyncSession = Depends(get_session)):
    row = (await s.execute(select(Incident, Host.display_name).join(Host).where(Incident.id == incident_id))).first()
    if row is None:
        raise HTTPException(404, f"incident {incident_id} not found")
    inc, host_name = row
    anomalies = (await s.scalars(select(Prediction).where(Prediction.incident_id == inc.id)
                                 .order_by(Prediction.ts).limit(1000))).all()
    events = (await s.scalars(select(ExternalEvent).join(IncidentExternalLink, IncidentExternalLink.external_event_id == ExternalEvent.id)
                              .where(IncidentExternalLink.incident_id == inc.id).order_by(ExternalEvent.clock))).all()
    end = inc.resolved_at or inc.last_seen_at
    margin = timedelta(seconds=120)
    timeline = await score_timeline(s, inc.host_id, inc.opened_at - margin, end + margin)
    base = _inc_out(inc, host_name, len(events))
    return IncidentDetail(**base.model_dump(), anomalies=[_anom(p, host_name) for p in anomalies],
                          events=[_event_out(e, host_name) for e in events], timeline=timeline)


async def _action(fn, incident_id: int, body: IncidentAction, s: AsyncSession):
    try:
        inc = await fn(s, incident_id, body.note, datetime.now(timezone.utc))
    except LookupError:
        raise HTTPException(404, f"incident {incident_id} not found") from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    host = await s.get(Host, inc.host_id)
    return _inc_out(inc, host.display_name if host else "")


@router.post("/incidents/{incident_id}/acknowledge", response_model=IncidentOut)
async def acknowledge(incident_id: int, body: IncidentAction, s: AsyncSession = Depends(get_session)):
    return await _action(svc.acknowledge, incident_id, body, s)


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
async def resolve(incident_id: int, body: IncidentAction, s: AsyncSession = Depends(get_session)):
    return await _action(svc.resolve_manually, incident_id, body, s)


@router.get("/anomalies", response_model=AnomalyPage)
async def list_anomalies(host_id: int | None = None, limit: int = Query(100, ge=1, le=1000),
                         offset: int = Query(0, ge=0), s: AsyncSession = Depends(get_session)):
    q = select(Prediction, Host.display_name).join(Host, Host.id == Prediction.host_id).where(Prediction.is_anomaly)
    cq = select(func.count()).select_from(Prediction).where(Prediction.is_anomaly)
    if host_id:
        q, cq = q.where(Prediction.host_id == host_id), cq.where(Prediction.host_id == host_id)
    rows = (await s.execute(q.order_by(Prediction.ts.desc()).limit(limit).offset(offset))).all()
    return AnomalyPage(total=await s.scalar(cq) or 0, items=[_anom(p, n) for p, n in rows])


@router.get("/events", response_model=list[ExternalEventOut])
async def list_events(active_only: bool = False, limit: int = Query(100, ge=1, le=1000),
                      s: AsyncSession = Depends(get_session)):
    q = select(ExternalEvent, Host.display_name).outerjoin(Host, Host.id == ExternalEvent.host_id)
    if active_only:
        q = q.where(ExternalEvent.recovered_at.is_(None))
    rows = (await s.execute(q.order_by(ExternalEvent.clock.desc()).limit(limit))).all()
    return [_event_out(e, n) for e, n in rows]
