"""Step 3: train, calibrate, select threshold, evaluate and package the model.

Protocol (all randomness seeded):
  train split  -> class-capped sample (per raw label) -> fit candidates
  val split    -> half A: probability calibration (isotonic, natural distribution)
               -> half B: threshold selection (benign FPR <= --max-fpr) + model selection
  test split   -> final, untouched evaluation of every candidate
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from threadpoolctl import threadpool_limits
import joblib

from .evaluate import binary_metrics, multiclass_metrics, threshold_for_fpr
from .runtime import save_bundle
from .schema import BENIGN, CATEGORIES, LABEL_COL, LABEL_TO_CATEGORY, RAW_FEATURES

log = logging.getLogger(__name__)

# Decided from prepare_report.json (row-level equality = 100%): exact duplicates of other columns.
DEFAULT_DROP: tuple[str, ...] = ("Tot size", "LLC")


def signed_log1p(x):
    return np.sign(x) * np.log1p(np.abs(x))


def make_candidates(seed: int) -> dict[str, Callable[[], object]]:
    return {
        "logreg": lambda: Pipeline([
            ("log", FunctionTransformer(signed_log1p, feature_names_out="one-to-one")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed)),
        ]),
        "random_forest": lambda: RandomForestClassifier(
            n_estimators=100, max_depth=20, min_samples_leaf=5, max_samples=0.3,
            class_weight="balanced_subsample", n_jobs=-1, random_state=seed),
        "hist_gb": lambda: HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.1, max_leaf_nodes=63, early_stopping=True,
            validation_fraction=0.1, n_iter_no_change=15, class_weight="balanced",
            random_state=seed),
    }


# ---------------------------------------------------------------- data loading
def to_xy(df: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    y = df[LABEL_COL].astype(str).map(LABEL_TO_CATEGORY).to_numpy()
    return df[features], y


def label_counts(split_dir: Path) -> pd.Series:
    parts = [pd.read_parquet(f, columns=[LABEL_COL])[LABEL_COL].astype(str) for f in sorted(split_dir.glob("*.parquet"))]
    return pd.concat(parts).value_counts()


def load_capped(split_dir: Path, cap: int, rng: np.random.Generator) -> pd.DataFrame:
    """Bernoulli-sample each raw attack label to ~cap rows; rare labels and all BENIGN rows are kept."""
    frac = (cap / label_counts(split_dir)).clip(upper=1.0)
    frac["BENIGN"] = 1.0  # keep every benign row: it drives the false-positive rate
    out = []
    for f in sorted(split_dir.glob("*.parquet")):
        df = pd.read_parquet(f)
        keep = rng.random(len(df)) < df[LABEL_COL].astype(str).map(frac).to_numpy()
        out.append(df[keep])
    return pd.concat(out, ignore_index=True)


def load_all(split_dir: Path) -> pd.DataFrame:
    return pd.concat([pd.read_parquet(f) for f in sorted(split_dir.glob("*.parquet"))], ignore_index=True)


# ---------------------------------------------------------------- evaluation
def predict_proba_chunked(model, X: pd.DataFrame, chunk: int = 500_000) -> np.ndarray:
    return np.vstack([model.predict_proba(X.iloc[i:i + chunk]) for i in range(0, len(X), chunk)])


def evaluate(model, X, y, threshold: float, classes: list[str]) -> dict:
    t0 = time.perf_counter()
    proba = predict_proba_chunked(model, X)
    elapsed = time.perf_counter() - t0
    bi = classes.index(BENIGN)
    p_attack = 1.0 - proba[:, bi]
    y_attack = y != BENIGN
    y_pred = np.asarray(classes)[proba.argmax(axis=1)]
    return {
        "n": int(len(y)),
        "binary": binary_metrics(y_attack, p_attack, threshold),
        "multiclass": multiclass_metrics(y, y_pred, list(classes)),
        "inference_us_per_row": 1e6 * elapsed / max(len(y), 1),
    }


def fit_and_calibrate(factory, X_tr, y_tr, X_cal, y_cal):
    t0 = time.perf_counter()
    base = factory().fit(X_tr, y_tr)
    fit_s = time.perf_counter() - t0
    cal = CalibratedClassifierCV(base, method="isotonic", cv="prefit").fit(X_cal, y_cal)
    return cal, fit_s


def run_cached(ckpt: Path, name: str, *args, **kw) -> dict:
    """Run an experiment once; persist model + validation result so reruns resume and RAM is freed."""
    mpath, rpath = ckpt / f"{name}.joblib", ckpt / f"{name}.json"
    if mpath.is_file() and rpath.is_file():
        log.info("[%s] using checkpoint", name)
        return json.loads(rpath.read_text())
    model, res = run_experiment(name, *args, **kw)
    joblib.dump(model, mpath)
    rpath.write_text(json.dumps(res, default=str))
    del model
    gc.collect()
    return res


def run_experiment(name, factory, features, data, max_fpr, binary=False) -> tuple[object, dict]:
    (X_tr, y_tr), (X_a, y_a), (X_b, y_b) = [(d[0][features], d[1]) for d in data]
    if binary:
        enc = lambda y: np.where(y == BENIGN, BENIGN, "Attack")
        y_tr, y_a, y_b = enc(y_tr), enc(y_a), enc(y_b)
    log.info("[%s] fitting on %d rows, %d features", name, len(X_tr), len(features))
    model, fit_s = fit_and_calibrate(factory, X_tr, y_tr, X_a, y_a)
    classes = list(model.classes_)
    p_b = 1.0 - predict_proba_chunked(model, X_b)[:, classes.index(BENIGN)]
    thr = threshold_for_fpr(p_b[y_b == BENIGN], max_fpr)
    res = evaluate(model, X_b, y_b, thr, classes)
    res.update(fit_seconds=fit_s, features=features, classes=classes)
    log.info("[%s] val: recall=%.4f fpr=%.4f macroF1=%.4f thr=%.4f fit=%.0fs",
             name, res["binary"]["recall"], res["binary"]["fpr"], res["multiclass"]["macro_f1"], thr, fit_s)
    return model, res


# ---------------------------------------------------------------- plots
def save_plots(out: Path, test_res: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cm = np.asarray(test_res["multiclass"]["confusion_matrix"]["matrix"], dtype=float)
    labels = test_res["multiclass"]["confusion_matrix"]["labels"]
    norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{norm[i, j]:.2f}", ha="center", va="center",
                    color="white" if norm[i, j] > 0.5 else "black", fontsize=8)
    ax.set_xlabel("Predicted"); ax.set_ylabel("True"); ax.set_title("Test confusion matrix (row-normalised)")
    fig.colorbar(im); fig.tight_layout(); fig.savefig(out / "confusion_matrix.png", dpi=120); plt.close(fig)


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--splits", type=Path, default=Path("ml/work/splits"))
    p.add_argument("--out", type=Path, default=Path("artifacts/models"))
    p.add_argument("--report", type=Path, default=Path("ml/reports"))
    p.add_argument("--cap", type=int, default=100_000, help="max train rows per raw label")
    p.add_argument("--cal-rows", type=int, default=1_500_000)
    p.add_argument("--max-fpr", type=float, default=0.01)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--candidates", nargs="*", default=None)
    p.add_argument("--skip-ablation", action="store_true")
    p.add_argument("--checkpoints", type=Path, default=Path("ml/work/checkpoints"))
    p.add_argument("--fresh", action="store_true", help="ignore existing checkpoints")
    p.add_argument("--threads", type=int, default=None, help="cap OpenMP/BLAS threads (default: all)")
    a = p.parse_args(argv)
    if a.threads:
        with threadpool_limits(limits=a.threads):
            return _main(a)
    return _main(a)


def _main(a: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rng = np.random.default_rng(a.seed)
    a.report.mkdir(parents=True, exist_ok=True)
    a.checkpoints.mkdir(parents=True, exist_ok=True)
    if a.fresh:
        for f in a.checkpoints.glob("*"):
            f.unlink()

    features = [f for f in RAW_FEATURES if f not in DEFAULT_DROP]
    train = load_capped(a.splits / "train", a.cap, rng)
    val = load_all(a.splits / "val")
    perm = rng.permutation(len(val))
    val_a, val_b = val.iloc[perm[:a.cal_rows]], val.iloc[perm[a.cal_rows:]]
    del val
    data = [to_xy(train, list(RAW_FEATURES)), to_xy(val_a, list(RAW_FEATURES)), to_xy(val_b, list(RAW_FEATURES))]
    n_train = int(len(train))
    log.info("train=%d valA=%d valB=%d", n_train, len(val_a), len(val_b))
    log.info("train category counts: %s", pd.Series(data[0][1]).value_counts().to_dict())

    cands = make_candidates(a.seed)
    names = a.candidates or list(cands)
    val_results = {}
    for n in names:
        val_results[n] = run_cached(a.checkpoints, n, cands[n], features, data, a.max_fpr)

    if not a.skip_ablation:
        hgb = cands["hist_gb"]
        for tag, drop in {"hist_gb_no_iat": ["IAT"], "hist_gb_no_iat_ttl": ["IAT", "Time_To_Live"]}.items():
            val_results[tag] = run_cached(a.checkpoints, tag, hgb, [f for f in features if f not in drop], data, a.max_fpr)
        val_results["hist_gb_binary"] = run_cached(a.checkpoints, "hist_gb_binary", hgb, features, data, a.max_fpr, binary=True)
    del data, train, val_a, val_b
    gc.collect()

    # Selection on validation B: recall at the fixed FPR budget, then macro-F1.
    best = max(names, key=lambda n: (round(val_results[n]["binary"]["recall"], 4), val_results[n]["multiclass"]["macro_f1"]))
    log.info("selected: %s", best)

    test = load_all(a.splits / "test")
    X_te, y_te = to_xy(test, list(RAW_FEATURES)); del test
    test_results = {}
    for n in val_results:
        model = joblib.load(a.checkpoints / f"{n}.joblib")
        y_eval = y_te if n != "hist_gb_binary" else np.where(y_te == BENIGN, BENIGN, "Attack")
        test_results[n] = evaluate(model, X_te[val_results[n]["features"]], y_eval,
                                   val_results[n]["binary"]["threshold"], list(model.classes_))
        test_results[n]["model_bytes"] = (a.checkpoints / f"{n}.joblib").stat().st_size
        del model; gc.collect()
        log.info("[%s] test: recall=%.4f fpr=%.4f macroF1=%.4f", n, test_results[n]["binary"]["recall"],
                 test_results[n]["binary"]["fpr"], test_results[n]["multiclass"]["macro_f1"])

    # Package selected model
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    version = f"{best}-{stamp}"
    bdir = a.out / version
    best_model = joblib.load(a.checkpoints / f"{best}.joblib")
    prep_report = json.loads((a.splits / "prepare_report.json").read_text())
    metadata = {
        "version": version, "algorithm": best, "created_at": stamp,
        "features": features, "dropped_features": list(DEFAULT_DROP),
        "categories": list(best_model.classes_), "benign_label": BENIGN,
        "threshold": val_results[best]["binary"]["threshold"], "threshold_rule": f"benign FPR <= {a.max_fpr} on validation B",
        "calibration": "isotonic, validation A (natural class distribution)",
        "training": {"cap_per_raw_label": a.cap, "rows": n_train, "seed": a.seed,
                     "split_rule": prep_report["split_rule"]},
        "metrics": {"validation": val_results[best], "test": test_results[best]},
        "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                        "numpy": np.__version__, "pandas": pd.__version__},
    }
    save_bundle(best_model, metadata, bdir)
    save_plots(bdir, test_results[best])
    (a.report / "experiments.json").write_text(json.dumps(
        {"selected": best, "version": version, "validation": val_results, "test": test_results}, indent=2, default=str))
    log.info("bundle written: %s", bdir)


if __name__ == "__main__":
    main()
