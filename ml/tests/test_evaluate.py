import numpy as np
import pytest

from netad_ml.evaluate import binary_metrics, multiclass_metrics, threshold_for_fpr


@pytest.mark.parametrize("max_fpr", [0.0, 0.01, 0.05, 0.2])
def test_threshold_respects_fpr_budget(max_fpr):
    s = np.random.default_rng(0).random(10_000)
    t = threshold_for_fpr(s, max_fpr)
    assert (s >= t).mean() <= max_fpr
    # and it is tight: lowering slightly would exceed the budget (unless budget is 0)
    if max_fpr > 0:
        assert (s >= np.nextafter(t, -np.inf) - 1e-9).mean() >= max_fpr - 1e-3


def test_threshold_with_ties():
    s = np.array([0.5] * 100)
    t = threshold_for_fpr(s, 0.01)
    assert (s >= t).mean() == 0.0


def test_binary_metrics_counts_and_prevalence_adjustment():
    y = np.array([1, 1, 1, 0, 0, 0, 0, 0])
    p = np.array([.9, .8, .2, .7, .1, .1, .1, .1])
    m = binary_metrics(y, p, 0.5, realistic_attack_prevalence=0.5)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 4)
    assert m["recall"] == pytest.approx(2 / 3) and m["fpr"] == pytest.approx(1 / 5)
    assert m["precision_at_50pct_attack_prevalence"] == pytest.approx((2 / 3) / (2 / 3 + 1 / 5))


def test_multiclass_metrics_shape():
    m = multiclass_metrics(np.array(["a", "b", "b"]), np.array(["a", "b", "a"]), ["a", "b"])
    assert m["confusion_matrix"]["matrix"] == [[1, 0], [1, 1]]
    assert m["accuracy"] == pytest.approx(2 / 3)
