"""MLflow tracking + registry round trip against a local file store (no server needed)."""
import json

import pytest

mlflow = pytest.importorskip("mlflow")

from netad_ml import registry, tracking, train
from netad_ml.prepare import main as prepare_main
from netad_ml.runtime import ModelBundle


@pytest.fixture
def tracked(tmp_path, monkeypatch):
    from conftest import synthetic_frame
    uri = (tmp_path / "mlruns").as_uri()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    pq = tmp_path / "pq"; pq.mkdir()
    for i in range(2):
        synthetic_frame(3000, seed=20 + i).to_parquet(pq / f"Dataset0{i}.parquet")
    prepare_main(["--src", str(pq), "--dst", str(tmp_path / "sp")])
    train.main(["--splits", str(tmp_path / "sp"), "--out", str(tmp_path / "cand"), "--report", str(tmp_path / "rep"),
                "--cap", "400", "--cal-rows", "300", "--checkpoints", str(tmp_path / "ck"),
                "--candidates", "logreg", "--skip-ablation"])
    yield tmp_path
    mlflow.set_tracking_uri(None)


def test_training_registers_candidate_and_promote_exports(tracked):
    client = mlflow.MlflowClient()
    mv = client.get_model_version_by_alias(tracking.REGISTERED_MODEL, "candidate")
    run = client.get_run(mv.run_id)
    assert "test_binary_recall" in run.data.metrics
    assert run.data.params["cap"] == "400"
    metrics = json.loads((tracked / "rep" / "metrics.json").read_text())
    assert metrics["selected"] == "logreg"

    dest = tracked / "serve"
    (dest / "stale-bundle").mkdir(parents=True)
    (dest / "stale-bundle" / "metadata.json").write_text("{}")
    target = registry.promote("candidate", dest)
    assert [p.name for p in dest.iterdir()] == [target.name]  # old bundle replaced: backend serves exactly one
    b = ModelBundle.load(target)
    assert b.metadata["sha256"] == mv.tags["sha256"]
    assert client.get_model_version_by_alias(tracking.REGISTERED_MODEL, "production").version == mv.version


def test_import_bundle_registers_new_version(tracked):
    bundle = next((tracked / "cand").iterdir())
    registry.main(["import-bundle", str(bundle), "--report", str(tracked / "rep" / "experiments.json")])
    client = mlflow.MlflowClient()
    prod = client.get_model_version_by_alias(tracking.REGISTERED_MODEL, "production")
    assert int(prod.version) == 2
