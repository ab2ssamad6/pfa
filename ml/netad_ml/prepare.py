"""Step 2: global de-duplication and leakage-safe train/val/test split.

Design
------
* The data has no timestamps/flow ids and every shard has the same label mix,
  so chronological or grouped splitting is impossible. We split at random.
* The split bucket is derived from a hash of the *feature values only*:
  identical feature vectors always land in the same split, so duplicates and
  label-conflicting copies can never leak between train and test.
* Exact duplicates (features + label) are removed globally, keeping the first.
* Rows whose identical feature vector appears with >1 different label are
  counted and reported (irreducible label noise), but kept.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import LABEL_COL, RAW_FEATURES

log = logging.getLogger(__name__)

SPLITS = {"train": (0, 700), "val": (700, 850), "test": (850, 1000)}  # per-mille buckets


def feature_hash(df: pd.DataFrame) -> np.ndarray:
    return pd.util.hash_pandas_object(df[list(RAW_FEATURES)], index=False).to_numpy()


def row_hash(df: pd.DataFrame, fhash: np.ndarray) -> np.ndarray:
    lab = pd.util.hash_pandas_object(df[LABEL_COL].astype(str), index=False).to_numpy()
    return fhash ^ (lab * np.uint64(0x9E3779B97F4A7C15))


def assign_split(fhash: np.ndarray) -> np.ndarray:
    bucket = fhash % np.uint64(1000)
    out = np.empty(len(fhash), dtype=object)
    for name, (lo, hi) in SPLITS.items():
        out[(bucket >= lo) & (bucket < hi)] = name
    return out


def first_occurrence_mask(hashes: np.ndarray) -> np.ndarray:
    _, idx = np.unique(hashes, return_index=True)
    mask = np.zeros(len(hashes), dtype=bool)
    mask[idx] = True
    return mask


def count_label_conflicts(fh_dedup: np.ndarray) -> int:
    """Distinct feature vectors seen with more than one label.

    After exact de-duplication, a repeated feature hash can only mean the same
    feature vector carries different labels.
    """
    _, counts = np.unique(fh_dedup, return_counts=True)
    return int((counts > 1).sum())


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=Path("ml/work/parquet"))
    p.add_argument("--dst", type=Path, default=Path("ml/work/splits"))
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    files = sorted(a.src.glob("Dataset*.parquet"))
    if not files:
        raise SystemExit(f"no parquet files in {a.src}; run netad_ml.convert first")

    # Pass 1: hashes + redundancy statistics
    fhs, rhs, sizes = [], [], []
    red = {"rows": 0, "AVG==Tot size": 0, "IPv==LLC": 0}
    for f in files:
        df = pd.read_parquet(f)
        fh = feature_hash(df)
        fhs.append(fh); rhs.append(row_hash(df, fh)); sizes.append(len(df))
        red["rows"] += len(df)
        red["AVG==Tot size"] += int((df["AVG"] == df["Tot size"]).sum())
        red["IPv==LLC"] += int((df["IPv"] == df["LLC"]).sum())
        log.info("hashed %s (%d rows)", f.name, len(df))
    fh_all, rh_all = np.concatenate(fhs), np.concatenate(rhs)
    keep_all = first_occurrence_mask(rh_all)
    conflicts = count_label_conflicts(fh_all[keep_all])
    log.info("rows=%d unique=%d conflicts=%d", len(rh_all), int(keep_all.sum()), conflicts)

    # Pass 2: write de-duplicated split parts
    for name in SPLITS:
        (a.dst / name).mkdir(parents=True, exist_ok=True)
    split_counts: dict[str, dict[str, int]] = {s: {} for s in SPLITS}
    off = 0
    for f, n in zip(files, sizes):
        keep = keep_all[off:off + n]; fh = fh_all[off:off + n]; off += n
        df = pd.read_parquet(f)[keep].reset_index(drop=True)
        split = assign_split(fh[keep])
        for name in SPLITS:
            part = df[split == name]
            part.to_parquet(a.dst / name / f.name, index=False)
            for lab, c in part[LABEL_COL].value_counts().items():
                split_counts[name][lab] = split_counts[name].get(lab, 0) + int(c)

    report = {
        "rows_after_cleaning": int(len(rh_all)),
        "exact_duplicates_removed": int(len(rh_all) - keep_all.sum()),
        "unique_rows": int(keep_all.sum()),
        "feature_vectors_with_conflicting_labels": conflicts,
        "redundancy_row_equality": red,
        "split_rule": "bucket = hash(features) % 1000; train<700<=val<850<=test",
        "split_label_counts": split_counts,
        "split_totals": {s: sum(c.values()) for s, c in split_counts.items()},
    }
    (a.dst / "prepare_report.json").write_text(json.dumps(report, indent=2))
    log.info("report: %s", {k: v for k, v in report.items() if k != "split_label_counts"})


if __name__ == "__main__":
    main()
