import json
import math

import numpy as np
import pandas as pd
import pytest

from netad_ml import train
from netad_ml.prepare import main as prepare_main
from netad_ml.runtime import BundleError, FeatureValidationError, ModelBundle
from netad_ml.schema import CATEGORIES, LABEL_COL, LABEL_TO_CATEGORY, RAW_FEATURES


@pytest.fixture(scope="module")
def trained(tmp_path_factory, request):
    from conftest import synthetic_frame
    root = tmp_path_factory.mktemp("pipe")
    pq = root / "pq"; pq.mkdir()
    for i in range(3):
        synthetic_frame(4000, seed=10 + i).to_parquet(pq / f"Dataset0{i}.parquet")
    prepare_main(["--src", str(pq), "--dst", str(root / "sp")])
    train.main(["--splits", str(root / "sp"), "--out", str(root / "models"), "--report", str(root / "rep"),
                "--cap", "500", "--cal-rows", "400", "--checkpoints", str(root / "ck"), "--candidates", "logreg", "hist_gb", "--skip-ablation"])
    bundle_dir = next((root / "models").iterdir())
    return root, bundle_dir


def test_bundle_roundtrip_and_metadata(trained):
    root, bdir = trained
    b = ModelBundle.load(bdir)
    meta = json.loads((bdir / "metadata.json").read_text())
    assert b.features == [f for f in RAW_FEATURES if f not in train.DEFAULT_DROP]
    assert set(b.categories) == set(CATEGORIES)
    assert 0.0 <= meta["threshold"] <= 1.0 + 1e-9
    # threshold rule is guaranteed on the data it was chosen on (validation B, 1% budget)
    assert meta["metrics"]["validation"]["binary"]["fpr"] <= 0.01
    # synthetic data is separable; test benign count is small (~50), so only a loose FPR bound
    assert meta["metrics"]["test"]["binary"]["recall"] > 0.9
    assert meta["metrics"]["test"]["binary"]["fpr"] < 0.25
    assert (bdir / "confusion_matrix.png").is_file()
    exp = json.loads((root / "rep" / "experiments.json").read_text())
    assert exp["selected"] in {"logreg", "hist_gb"}


def test_predictions_consistent(trained, synth):
    _, bdir = trained
    b = ModelBundle.load(bdir)
    df = synth(200, seed=99)
    rows = df[list(RAW_FEATURES)].to_dict("records")
    preds = b.predict(rows)
    assert len(preds) == 200
    for p in preds:
        assert math.isclose(sum(p.category_proba.values()), 1.0, abs_tol=1e-6)
        assert p.category != "Benign"
        assert p.is_anomaly == (p.p_attack >= b.threshold)
    truth = df[LABEL_COL].astype(str).map(LABEL_TO_CATEGORY).ne("Benign").to_numpy()
    acc = np.mean([p.is_anomaly for p in preds] == truth)
    assert acc > 0.9


def test_feature_validation(trained):
    b = ModelBundle.load(trained[1])
    row = {f: 1.0 for f in b.features}
    with pytest.raises(FeatureValidationError, match="missing"):
        b.predict([{k: v for k, v in row.items() if k != "Rate"}])
    with pytest.raises(FeatureValidationError, match="finite"):
        b.predict([{**row, "Rate": float("inf")}])
    with pytest.raises(FeatureValidationError, match="numeric"):
        b.predict([{**row, "Rate": "abc"}])
    assert b.predict([]) == []


def test_tampered_model_rejected(trained, tmp_path):
    import shutil
    d = tmp_path / "copy"; shutil.copytree(trained[1], d)
    with (d / "model.joblib").open("ab") as f:
        f.write(b"x")
    with pytest.raises(BundleError, match="sha256"):
        ModelBundle.load(d)
