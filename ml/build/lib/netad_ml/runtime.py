"""Runtime model bundle: the ONLY interface online inference uses.

A bundle directory contains:
  model.joblib   calibrated sklearn estimator (predict_proba over CATEGORIES order)
  metadata.json  version, feature list, categories, threshold, metrics, sha256 of model.joblib
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd

from .schema import BENIGN


class BundleError(RuntimeError):
    pass


class FeatureValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Prediction:
    p_attack: float
    category: str           # most likely attack category (never "Benign")
    category_proba: dict[str, float]
    is_anomaly: bool


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save_bundle(model: Any, metadata: dict, directory: str | Path) -> Path:
    """Write model.joblib + metadata.json (sha256 filled in). Returns the directory."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, d / "model.joblib", compress=3)
    meta = {**metadata, "sha256": sha256_file(d / "model.joblib")}
    (d / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    return d


class ModelBundle:
    def __init__(self, model: Any, metadata: dict):
        self.model = model
        self.metadata = metadata
        self.features: list[str] = metadata["features"]
        self.categories: list[str] = metadata["categories"]
        self.threshold: float = float(metadata["threshold"])
        self.version: str = metadata["version"]
        if BENIGN not in self.categories:
            raise BundleError("bundle categories must include Benign")
        self._benign_idx = self.categories.index(BENIGN)

    @classmethod
    def load(cls, directory: str | Path) -> "ModelBundle":
        d = Path(directory)
        meta_path, model_path = d / "metadata.json", d / "model.joblib"
        if not meta_path.is_file() or not model_path.is_file():
            raise BundleError(f"incomplete model bundle at {d}")
        metadata = json.loads(meta_path.read_text())
        digest = sha256_file(model_path)
        if digest != metadata.get("sha256"):
            raise BundleError(f"sha256 mismatch for {model_path}: {digest} != {metadata.get('sha256')}")
        model = joblib.load(model_path)
        if list(model.classes_) != metadata["categories"]:
            raise BundleError("model classes do not match metadata categories")
        return cls(model, metadata)

    def to_frame(self, rows: Sequence[Mapping[str, float]]) -> pd.DataFrame:
        """Validate and order raw feature dicts. Raises on missing/non-finite values."""
        out = np.empty((len(rows), len(self.features)), dtype=np.float32)
        for i, row in enumerate(rows):
            missing = [f for f in self.features if f not in row]
            if missing:
                raise FeatureValidationError(f"row {i}: missing features {missing}")
            for j, f in enumerate(self.features):
                v = row[f]
                try:
                    x = float(v)
                except (TypeError, ValueError):
                    raise FeatureValidationError(f"row {i}: feature {f!r} not numeric: {v!r}") from None
                if not math.isfinite(x):
                    raise FeatureValidationError(f"row {i}: feature {f!r} not finite: {v!r}")
                out[i, j] = x
        return pd.DataFrame(out, columns=self.features)

    def predict(self, rows: Sequence[Mapping[str, float]]) -> list[Prediction]:
        if not rows:
            return []
        proba = self.model.predict_proba(self.to_frame(rows))
        preds = []
        for pr in proba:
            p_attack = float(1.0 - pr[self._benign_idx])
            attack_only = {c: float(p) for c, p in zip(self.categories, pr) if c != BENIGN}
            preds.append(Prediction(
                p_attack=p_attack,
                category=max(attack_only, key=attack_only.get),
                category_proba={c: float(p) for c, p in zip(self.categories, pr)},
                is_anomaly=p_attack >= self.threshold,
            ))
        return preds
