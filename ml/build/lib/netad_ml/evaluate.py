"""Metric helpers. Pure functions over numpy arrays — unit-tested."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix, f1_score,
    precision_recall_fscore_support, roc_auc_score,
)


def threshold_for_fpr(benign_scores: np.ndarray, max_fpr: float) -> float:
    """Smallest threshold t such that FPR = P(score >= t | benign) <= max_fpr."""
    if len(benign_scores) == 0:
        raise ValueError("no benign samples to set threshold")
    s = np.sort(benign_scores)
    k = int(np.floor(max_fpr * len(s)))  # number of benign allowed at/above t
    if k == 0:
        return float(np.nextafter(s[-1], np.inf))
    # t must exceed the (n-k-1)-th value so at most k benign are >= t
    t = float(np.nextafter(s[len(s) - k - 1], np.inf))
    return t


def binary_metrics(y_attack: np.ndarray, p_attack: np.ndarray, threshold: float,
                   realistic_attack_prevalence: float = 0.10) -> dict:
    y = y_attack.astype(bool)
    pred = p_attack >= threshold
    tp = int((pred & y).sum()); fp = int((pred & ~y).sum())
    fn = int((~pred & y).sum()); tn = int((~pred & ~y).sum())
    tpr = tp / max(tp + fn, 1); fpr = fp / max(fp + tn, 1)
    prec = tp / max(tp + fp, 1)
    pi = realistic_attack_prevalence
    prec_real = (tpr * pi) / max(tpr * pi + fpr * (1 - pi), 1e-12)
    out = {
        "threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": prec, "recall": tpr, "fpr": fpr,
        "f1": 2 * prec * tpr / max(prec + tpr, 1e-12),
        f"precision_at_{int(pi * 100)}pct_attack_prevalence": prec_real,
        "brier": float(brier_score_loss(y, p_attack)),
    }
    if y.any() and (~y).any():
        out["roc_auc"] = float(roc_auc_score(y, p_attack))
        out["pr_auc_attack"] = float(average_precision_score(y, p_attack))
        # PR-AUC for the *benign* class is informative because benign is the minority here
        out["pr_auc_benign"] = float(average_precision_score(~y, 1 - p_attack))
    return out


def multiclass_metrics(y_true: np.ndarray, y_pred: np.ndarray, labels: list[str]) -> dict:
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    return {
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0)),
        "accuracy": float((y_true == y_pred).mean()),
        "per_class": {lab: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(s[i])}
                      for i, lab in enumerate(labels)},
        "confusion_matrix": {"labels": labels,
                             "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist()},
    }
