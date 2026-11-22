"""MLflow experiment tracking and model registry for NetAD bundles.

Tracking is optional: it is active only when MLFLOW_TRACKING_URI is set (the Docker trainer sets it to the
`mlflow` service). The bundle directory (model.joblib + metadata.json with sha256) is the model format;
it is logged as the run artifact `bundle/` and registered as a version of REGISTERED_MODEL.

Registry aliases:
  candidate   the newest trained version (set automatically by training)
  production  the version exported to artifacts/models/ and served by the backend (set by `promote`)
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

REGISTERED_MODEL = os.environ.get("NETAD_REGISTERED_MODEL", "netad-anomaly-detector")
EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT_NAME", "netad-anomaly-detection")
BUNDLE_ARTIFACT = "bundle"


def enabled() -> bool:
    return bool(os.environ.get("MLFLOW_TRACKING_URI"))


def _scalar_metrics(prefix: str, res: Mapping[str, Any]) -> dict[str, float]:
    """Flatten numeric binary/multiclass metrics of one evaluate() result into MLflow metric names."""
    out: dict[str, float] = {}
    for group in ("binary", "multiclass"):
        for k, v in (res.get(group) or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{prefix}_{group}_{k}"] = float(v)
    for k in ("inference_us_per_row", "fit_seconds", "model_bytes", "n"):
        if isinstance(res.get(k), (int, float)):
            out[f"{prefix}_{k}"] = float(res[k])
    return out


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
                              timeout=5).stdout.strip() or None
    except Exception:
        return None


def _data_version(repo_root: Path = Path(".")) -> str | None:
    """md5 recorded by DVC for data/ (data.dvc), i.e. the dataset version the model was trained on."""
    f = repo_root / "data.dvc"
    if not f.is_file():
        return None
    for line in f.read_text().splitlines():
        line = line.strip().lstrip("- ")
        if line.startswith("md5:"):
            return line.split(":", 1)[1].strip()
    return None


def log_bundle_run(bundle_dir: Path, experiments: Mapping[str, Any], params: Mapping[str, Any] | None = None,
                   extra_artifacts: list[Path] | None = None, alias: str = "candidate") -> str:
    """Log one training run (a nested child run per candidate), upload the bundle and register it.

    `experiments` has the shape of ml/reports/experiments.json: {selected, version, validation, test}.
    Returns the registered model version number.
    """
    import mlflow
    from mlflow import MlflowClient

    meta = json.loads((bundle_dir / "metadata.json").read_text())
    best = experiments["selected"]
    mlflow.set_experiment(EXPERIMENT)
    tags = {"bundle_version": meta["version"], "algorithm": meta["algorithm"], "sha256": meta["sha256"],
            "git_commit": _git_commit() or "unknown", "data_md5": _data_version() or "untracked"}
    with mlflow.start_run(run_name=meta["version"], tags=tags) as run:
        mlflow.log_params({**(params or {}), "selected": best, "n_features": len(meta["features"]),
                           "threshold": meta["threshold"], "dropped_features": ",".join(meta.get("dropped_features", []))})
        for name, val in experiments["validation"].items():
            with mlflow.start_run(run_name=name, nested=True, tags={"candidate": name}):
                mlflow.log_metrics({**_scalar_metrics("val", val),
                                    **_scalar_metrics("test", experiments["test"].get(name, {}))})
        mlflow.log_metrics({**_scalar_metrics("val", experiments["validation"][best]),
                            **_scalar_metrics("test", experiments["test"][best])})
        mlflow.log_artifacts(str(bundle_dir), BUNDLE_ARTIFACT)
        for f in extra_artifacts or []:
            if f.is_file():
                mlflow.log_artifact(str(f), "reports")
        source = f"{run.info.artifact_uri}/{BUNDLE_ARTIFACT}"
        run_id = run.info.run_id

    client = MlflowClient()
    try:
        client.get_registered_model(REGISTERED_MODEL)
    except Exception:
        client.create_registered_model(REGISTERED_MODEL, description="NetAD calibrated anomaly classifier bundle")
    mv = client.create_model_version(REGISTERED_MODEL, source=source, run_id=run_id,
                                     tags={"bundle_version": meta["version"], "sha256": meta["sha256"]})
    if alias:
        client.set_registered_model_alias(REGISTERED_MODEL, alias, mv.version)
    return str(mv.version)
