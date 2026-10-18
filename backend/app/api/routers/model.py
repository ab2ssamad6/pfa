from __future__ import annotations

from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import FeatureWindow, Host, ModelVersion, Prediction
from ..deps import get_session
from ..schemas import LiveAccuracy, ModelOut

router = APIRouter(prefix="/api", tags=["model"])


@router.get("/model", response_model=ModelOut)
async def active_model(s: AsyncSession = Depends(get_session)):
    mv = (await s.scalars(select(ModelVersion).where(ModelVersion.is_active))).first()
    if mv is None:
        raise HTTPException(404, "no active model — is the worker running?")
    md = mv.metadata_json
    return ModelOut(version=mv.version, algorithm=mv.algorithm, threshold=mv.threshold,
                    threshold_rule=md.get("threshold_rule"), features=mv.features, categories=mv.categories,
                    loaded_at=mv.loaded_at, training=md.get("training", {}),
                    validation=md.get("metrics", {}).get("validation", {}), test=md.get("metrics", {}).get("test", {}),
                    calibration=md.get("calibration"))


@router.get("/demo/live-accuracy", response_model=LiveAccuracy)
async def live_accuracy(request: Request, minutes: int = Query(15, ge=1, le=360), s: AsyncSession = Depends(get_session)):
    """Compare live predictions with the mock scenario's ground truth. Demo-only (needs DEMO_TRUTH_URL)."""
    url = request.app.state.settings.demo_truth_url
    if not url:
        raise HTTPException(404, "live accuracy disabled (DEMO_TRUTH_URL not set)")
    tp = fp = fn = tn = 0
    for h in (await s.scalars(select(Host).where(Host.active))).all():
        ref = await s.scalar(select(func.max(Prediction.ts)).where(Prediction.host_id == h.id))
        if ref is None:
            continue
        start = ref - timedelta(minutes=minutes)
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(url, params={"host": h.name, "time_from": int(start.timestamp()),
                                             "time_till": int(ref.timestamp())})
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"ground-truth service unavailable: {e}") from None
        truth = {(w["clock"], w["ns"]): w["label"] != "BENIGN" for w in r.json()}
        rows = (await s.execute(select(FeatureWindow.ts, FeatureWindow.ns, Prediction.is_anomaly)
                                .join(Prediction, Prediction.window_id == FeatureWindow.id)
                                .where(FeatureWindow.host_id == h.id, FeatureWindow.ts >= start))).all()
        for ts, ns, pred in rows:
            actual = truth.get((int(ts.timestamp()), ns))
            if actual is None:
                continue
            tp += pred and actual
            fp += pred and not actual
            fn += (not pred) and actual
            tn += (not pred) and (not actual)
    n = tp + fp + fn + tn
    return LiveAccuracy(window_minutes=minutes, evaluated=n, tp=tp, fp=fp, fn=fn, tn=tn,
                        precision=tp / (tp + fp) if tp + fp else None, recall=tp / (tp + fn) if tp + fn else None,
                        fpr=fp / (fp + tn) if fp + tn else None,
                        note="Per-window agreement with the replay scenario's labels (demo data, not a benchmark).")
