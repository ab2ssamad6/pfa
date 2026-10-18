"""Online inference: score every new feature window with the active model bundle."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from netad_ml.runtime import FeatureValidationError, ModelBundle
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import FeatureWindow, ModelVersion, Prediction

log = logging.getLogger(__name__)


def resolve_bundle_dir(model_dir: Path) -> Path:
    """MODEL_DIR may be a bundle itself or a parent of versioned bundles (newest wins)."""
    if (model_dir / "metadata.json").is_file():
        return model_dir
    candidates = sorted(p for p in model_dir.glob("*") if (p / "metadata.json").is_file())
    if not candidates:
        raise FileNotFoundError(f"no model bundle found in {model_dir} — run scripts/train.sh")
    return max(candidates, key=lambda p: p.stat().st_mtime)


@dataclass
class ActiveModel:
    bundle: ModelBundle
    version_id: int


async def register_model(session: AsyncSession, model_dir: Path) -> ActiveModel:
    bdir = resolve_bundle_dir(model_dir)
    bundle = ModelBundle.load(bdir)
    md = bundle.metadata
    await session.execute(insert(ModelVersion).values(
        version=bundle.version, algorithm=md["algorithm"], path=str(bdir), sha256=md["sha256"],
        threshold=bundle.threshold, features=bundle.features, categories=bundle.categories, metadata_json=md,
        is_active=True, loaded_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(index_elements=[ModelVersion.version], set_={
        "is_active": True, "loaded_at": datetime.now(timezone.utc), "path": str(bdir)}))
    await session.execute(update(ModelVersion).where(ModelVersion.version != bundle.version).values(is_active=False))
    vid = await session.scalar(select(ModelVersion.id).where(ModelVersion.version == bundle.version))
    await session.commit()
    log.info("active model: %s (threshold %.4f)", bundle.version, bundle.threshold)
    return ActiveModel(bundle, vid)


@dataclass
class InferenceStats:
    predictions: int = 0
    anomalies: int = 0
    invalid: int = 0


async def run_inference(session: AsyncSession, model: ActiveModel, batch_size: int) -> InferenceStats:
    stats = InferenceStats()
    while True:
        windows = (await session.scalars(
            select(FeatureWindow)
            .outerjoin(Prediction, Prediction.window_id == FeatureWindow.id)
            .where(Prediction.window_id.is_(None), FeatureWindow.invalid_reason.is_(None))
            .order_by(FeatureWindow.ts).limit(batch_size))).all()
        if not windows:
            return stats
        valid, preds = [], []
        try:
            preds = model.bundle.predict([w.features for w in windows])
            valid = list(windows)
        except FeatureValidationError:
            for w in windows:  # isolate the bad rows instead of failing the batch
                try:
                    preds.extend(model.bundle.predict([w.features]))
                    valid.append(w)
                except FeatureValidationError as e:
                    w.invalid_reason = str(e)
                    stats.invalid += 1
                    log.warning("window %s rejected by model: %s", w.id, e)
        if valid:
            await session.execute(insert(Prediction).values([{
                "window_id": w.id, "host_id": w.host_id, "ts": w.ts, "model_version_id": model.version_id,
                "p_attack": p.p_attack, "category": p.category, "category_proba": p.category_proba,
                "is_anomaly": p.is_anomaly} for w, p in zip(valid, preds)]).on_conflict_do_nothing())
        stats.predictions += len(valid)
        stats.anomalies += sum(p.is_anomaly for p in preds)
        await session.commit()
        if len(windows) < batch_size:
            return stats
