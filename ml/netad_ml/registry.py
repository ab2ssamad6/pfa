"""Model registry CLI (MLflow). Run inside the trainer container via scripts/promote.sh / scripts/mlops.sh.

  python -m netad_ml.registry list
  python -m netad_ml.registry promote latest|candidate|production|<version> [--dest artifacts/models]
  python -m netad_ml.registry import-bundle artifacts/models/<ver> [--report ml/reports/experiments.json]

`promote` downloads the registered bundle, verifies it with ModelBundle.load (sha256 + classes), replaces the
bundle in --dest (the backend serves the single bundle found there) and moves the `production` alias.
Versioning the exported directory with DVC is done by scripts/promote.sh.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import tempfile
from pathlib import Path

from .runtime import BundleError, ModelBundle
from .tracking import REGISTERED_MODEL, log_bundle_run

log = logging.getLogger(__name__)
PRODUCTION = "production"


def resolve_version(client, ref: str):
    if ref == "latest":
        versions = client.search_model_versions(f"name='{REGISTERED_MODEL}'")
        if not versions:
            raise SystemExit(f"no versions registered under {REGISTERED_MODEL}")
        return max(versions, key=lambda v: int(v.version))
    if ref.isdigit():
        return client.get_model_version(REGISTERED_MODEL, ref)
    return client.get_model_version_by_alias(REGISTERED_MODEL, ref)


def promote(ref: str, dest: Path) -> Path:
    import mlflow
    from mlflow import MlflowClient

    client = MlflowClient()
    mv = resolve_version(client, ref)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(mlflow.artifacts.download_artifacts(artifact_uri=mv.source, dst_path=tmp))
        bundle = ModelBundle.load(local)  # verifies sha256 and classes before anything is replaced
        expected = (mv.tags or {}).get("sha256")
        if expected and expected != bundle.metadata["sha256"]:
            raise BundleError(f"registry sha256 {expected} != bundle sha256 {bundle.metadata['sha256']}")
        dest.mkdir(parents=True, exist_ok=True)
        for old in dest.iterdir():
            if old.is_dir() and (old / "metadata.json").is_file():
                shutil.rmtree(old)
        target = dest / bundle.version
        shutil.copytree(local, target)
    client.set_registered_model_alias(REGISTERED_MODEL, PRODUCTION, mv.version)
    log.info("promoted %s v%s (%s) -> %s", REGISTERED_MODEL, mv.version, bundle.version, target)
    return target


def list_versions() -> None:
    from mlflow import MlflowClient

    client = MlflowClient()
    try:
        aliases = client.get_registered_model(REGISTERED_MODEL).aliases or {}
    except Exception:
        print(f"no registered model {REGISTERED_MODEL} yet")
        return
    by_version: dict[str, list[str]] = {}
    for a, v in aliases.items():
        by_version.setdefault(str(v), []).append(a)
    print(f"{'version':>7}  {'bundle':<36} {'test recall':>11} {'test fpr':>9}  aliases")
    for mv in sorted(client.search_model_versions(f"name='{REGISTERED_MODEL}'"), key=lambda v: int(v.version)):
        m = client.get_run(mv.run_id).data.metrics if mv.run_id else {}
        print(f"{mv.version:>7}  {(mv.tags or {}).get('bundle_version', '?'):<36} "
              f"{m.get('test_binary_recall', float('nan')):>11.4f} {m.get('test_binary_fpr', float('nan')):>9.4f}  "
              f"{','.join(by_version.get(str(mv.version), []))}")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    pr = sub.add_parser("promote")
    pr.add_argument("ref", nargs="?", default="latest", help="latest | alias | version number")
    pr.add_argument("--dest", type=Path, default=Path("artifacts/models"))
    im = sub.add_parser("import-bundle", help="register an existing bundle (one-time migration)")
    im.add_argument("bundle", type=Path)
    im.add_argument("--report", type=Path, default=Path("ml/reports/experiments.json"))
    im.add_argument("--alias", default=PRODUCTION)
    a = p.parse_args(argv)

    if a.cmd == "list":
        list_versions()
    elif a.cmd == "promote":
        promote(a.ref, a.dest)
    else:
        ModelBundle.load(a.bundle)
        meta = json.loads((a.bundle / "metadata.json").read_text())
        if a.report.is_file():
            exp = json.loads(a.report.read_text())
        else:  # fall back to the metrics stored in the bundle itself
            exp = {"selected": meta["algorithm"], "validation": {meta["algorithm"]: meta["metrics"]["validation"]},
                   "test": {meta["algorithm"]: meta["metrics"]["test"]}}
        params = {f"train_{k}": v for k, v in meta.get("training", {}).items() if not isinstance(v, (dict, list))}
        version = log_bundle_run(a.bundle, exp, params=params, extra_artifacts=[a.report], alias=a.alias)
        print(f"registered {meta['version']} as {REGISTERED_MODEL} v{version} (alias {a.alias})")


if __name__ == "__main__":
    main()
