"""Step 1: convert raw CSV shards to typed Parquet, with a per-file validation report.

Rows are rejected (and counted, never silently) when:
  - the label is missing or unknown (e.g. truncated last line of a file),
  - any feature is NaN / unparseable,
  - any feature is +/-inf.
"""
from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import LABEL_COL, RAW_COLUMNS, RAW_FEATURES, RAW_LABELS

log = logging.getLogger(__name__)


class SchemaError(ValueError):
    pass


def validate_header(columns: list[str]) -> None:
    if tuple(columns) != RAW_COLUMNS:
        missing = set(RAW_COLUMNS) - set(columns)
        extra = set(columns) - set(RAW_COLUMNS)
        raise SchemaError(f"header mismatch: missing={sorted(missing)} extra={sorted(extra)}")


def clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Coerce types and drop invalid rows. Returns cleaned frame and rejection counts."""
    report: dict[str, int] = {"rows_in": len(df)}
    feats = df[list(RAW_FEATURES)].apply(pd.to_numeric, errors="coerce").astype(np.float64)
    labels = df[LABEL_COL].astype("string")

    bad_label = ~labels.isin(RAW_LABELS)
    arr = feats.to_numpy()
    has_nan = np.isnan(arr).any(axis=1)
    has_inf = np.isinf(arr).any(axis=1)
    report["rejected_bad_label"] = int(bad_label.sum())
    report["rejected_nan"] = int((has_nan & ~bad_label.to_numpy()).sum())
    report["rejected_inf"] = int((has_inf & ~has_nan & ~bad_label.to_numpy()).sum())
    keep = ~(bad_label.to_numpy() | has_nan | has_inf)

    out = feats.loc[keep].astype(np.float32)
    out[LABEL_COL] = pd.Categorical(labels[keep], categories=RAW_LABELS)
    out = out.reset_index(drop=True)
    report["rows_out"] = len(out)
    report["negative_iat_rows"] = int((out["IAT"] < 0).sum())
    return out, report


def convert_file(src: Path, dst_dir: Path) -> dict:
    with src.open() as fh:
        validate_header(fh.readline().strip().split(","))
    # dtype=str: parse ourselves so malformed values are counted, not guessed.
    raw = pd.read_csv(src, dtype=str, keep_default_na=False, na_values=[""])
    df, report = clean_frame(raw)
    dst = dst_dir / (src.stem + ".parquet")
    df.to_parquet(dst, index=False)
    report["file"] = src.name
    return report


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=Path("data"))
    p.add_argument("--dst", type=Path, default=Path("ml/work/parquet"))
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    files = sorted(a.src.glob("*.csv"))
    if not files:
        raise SystemExit(f"no CSV files in {a.src}")
    a.dst.mkdir(parents=True, exist_ok=True)
    reports = []
    with ProcessPoolExecutor(a.workers) as ex:
        for r in ex.map(convert_file, files, [a.dst] * len(files)):
            log.info("%s in=%d out=%d", r["file"], r["rows_in"], r["rows_out"])
            reports.append(r)
    totals = {k: sum(r[k] for r in reports) for k in reports[0] if k != "file"}
    (a.dst / "conversion_report.json").write_text(json.dumps({"totals": totals, "files": reports}, indent=2))
    log.info("totals: %s", totals)


if __name__ == "__main__":
    main()
