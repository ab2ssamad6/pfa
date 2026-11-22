import os

# Keep OpenMP (HistGradientBoosting) from oversubscribing shared CPUs during tests.
os.environ.setdefault("OMP_NUM_THREADS", "2")
# Tests never talk to the real MLflow server (the trainer container sets this); test_tracking uses a file store.
os.environ.pop("MLFLOW_TRACKING_URI", None)

import numpy as np
import pandas as pd
import pytest

from netad_ml.schema import LABEL_COL, RAW_FEATURES, RAW_LABELS


def synthetic_frame(n: int, seed: int = 0, labels=None) -> pd.DataFrame:
    """Separable synthetic rows: each label shifts a different feature."""
    rng = np.random.default_rng(seed)
    labels = list(labels or RAW_LABELS)
    y = rng.choice(labels, size=n)
    X = rng.normal(0, 1, size=(n, len(RAW_FEATURES))).astype(np.float32)
    for i, lab in enumerate(labels):
        X[y == lab, i % len(RAW_FEATURES)] += 6.0
    df = pd.DataFrame(X, columns=list(RAW_FEATURES))
    df[LABEL_COL] = pd.Categorical(y, categories=RAW_LABELS)
    return df


@pytest.fixture
def synth():
    return synthetic_frame
