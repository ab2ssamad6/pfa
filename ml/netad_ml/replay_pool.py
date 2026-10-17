"""Build the demo replay pool from the held-out TEST split only.

The mock Zabbix server replays these rows as flow-window telemetry, so the
demo never shows the model rows it was trained or calibrated on.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import LABEL_COL

log = logging.getLogger(__name__)


def build_pool(test_dir: Path, per_label: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.concat([pd.read_parquet(f) for f in sorted(test_dir.glob("*.parquet"))], ignore_index=True)
    parts = []
    for label, grp in df.groupby(LABEL_COL, observed=True):
        n = min(per_label, len(grp))
        parts.append(grp.iloc[rng.choice(len(grp), size=n, replace=False)])
    pool = pd.concat(parts, ignore_index=True)
    pool[LABEL_COL] = pool[LABEL_COL].astype(str)
    return pool


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--test-split", type=Path, default=Path("ml/work/splits/test"))
    p.add_argument("--out", type=Path, default=Path("artifacts/replay/replay_pool.parquet"))
    p.add_argument("--per-label", type=int, default=1500)
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pool = build_pool(a.test_split, a.per_label, a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    pool.to_parquet(a.out, index=False)
    meta = {"source": "test split", "per_label": a.per_label, "seed": a.seed, "rows": len(pool),
            "label_counts": pool[LABEL_COL].value_counts().to_dict()}
    a.out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    log.info("replay pool: %d rows -> %s", len(pool), a.out)


if __name__ == "__main__":
    main()
