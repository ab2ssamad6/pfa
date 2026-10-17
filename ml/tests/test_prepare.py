import numpy as np
import pandas as pd

from netad_ml import prepare
from netad_ml.schema import LABEL_COL


def test_identical_features_same_split_regardless_of_label(synth):
    df = synth(200)
    dup = df.copy()
    dup[LABEL_COL] = "BENIGN"
    s1 = prepare.assign_split(prepare.feature_hash(df))
    s2 = prepare.assign_split(prepare.feature_hash(dup))
    assert (s1 == s2).all()


def test_split_proportions_and_determinism(synth):
    df = synth(20000, seed=3)
    s = prepare.assign_split(prepare.feature_hash(df))
    frac = pd.Series(s).value_counts(normalize=True)
    assert abs(frac["train"] - 0.70) < 0.02 and abs(frac["test"] - 0.15) < 0.02
    assert (s == prepare.assign_split(prepare.feature_hash(df))).all()


def test_dedup_and_conflicts(synth):
    df = synth(50, seed=1)
    conflict = df.iloc[[0]].copy()
    conflict[LABEL_COL] = "BENIGN" if df[LABEL_COL].iloc[0] != "BENIGN" else "XSS"
    full = pd.concat([df, df.iloc[[1, 2]], conflict], ignore_index=True)
    fh = prepare.feature_hash(full)
    rh = prepare.row_hash(full, fh)
    keep = prepare.first_occurrence_mask(rh)
    assert keep.sum() == 51  # 2 exact duplicates removed, conflicting row kept
    assert prepare.count_label_conflicts(fh[keep]) == 1


def test_prepare_main_end_to_end(tmp_path, synth):
    src = tmp_path / "pq"; src.mkdir()
    a, b = synth(500, seed=1), synth(500, seed=2)
    a.to_parquet(src / "Dataset01.parquet"); pd.concat([b, a.iloc[:50]]).to_parquet(src / "Dataset02.parquet")
    prepare.main(["--src", str(src), "--dst", str(tmp_path / "sp")])
    import json
    rep = json.loads((tmp_path / "sp" / "prepare_report.json").read_text())
    assert rep["exact_duplicates_removed"] == 50
    assert sum(rep["split_totals"].values()) == 1000
    hashes = {s: set(prepare.feature_hash(pd.read_parquet(tmp_path / "sp" / s / "Dataset02.parquet")))
              for s in prepare.SPLITS}
    assert not (hashes["train"] & hashes["test"])
