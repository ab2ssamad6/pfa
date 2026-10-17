import numpy as np
import pandas as pd
import pytest

from netad_ml.convert import SchemaError, clean_frame, convert_file, validate_header
from netad_ml.schema import CATEGORIES, LABEL_COL, LABEL_TO_CATEGORY, RAW_COLUMNS, RAW_FEATURES


def test_taxonomy_complete():
    assert len(LABEL_TO_CATEGORY) == 34
    assert set(LABEL_TO_CATEGORY.values()) == set(CATEGORIES)
    assert all(k == k.upper() for k in LABEL_TO_CATEGORY)


def test_header_validation():
    validate_header(list(RAW_COLUMNS))
    with pytest.raises(SchemaError):
        validate_header(list(RAW_COLUMNS[:-1]) + ["label"])


def _raw(rows):
    return pd.DataFrame(rows, columns=list(RAW_COLUMNS)).astype(str)


def test_clean_frame_rejects_invalid_rows():
    good = ["1"] * len(RAW_FEATURES) + ["BENIGN"]
    inf = ["inf"] + ["1"] * (len(RAW_FEATURES) - 1) + ["BENIGN"]
    nan = ["1"] * (len(RAW_FEATURES) - 1) + [""] + ["BENIGN"]
    badlab = ["1"] * len(RAW_FEATURES) + ["NOT_A_LABEL"]
    raw = _raw([good, inf, nan, badlab, good])
    raw.loc[2, "Variance"] = np.nan
    out, rep = clean_frame(raw)
    assert rep == {**rep, "rows_in": 5, "rows_out": 2, "rejected_inf": 1, "rejected_nan": 1, "rejected_bad_label": 1}
    assert out.dtypes[RAW_FEATURES[0]] == np.float32
    assert list(out[LABEL_COL]) == ["BENIGN", "BENIGN"]


def test_convert_file_drops_truncated_last_line(tmp_path):
    line = ",".join(["1"] * len(RAW_FEATURES) + ["DDOS-SYN_FLOOD"])
    src = tmp_path / "Dataset99.csv"
    src.write_text(",".join(RAW_COLUMNS) + "\n" + line + "\n" + line[:25])  # truncated, no newline
    rep = convert_file(src, tmp_path)
    assert rep["rows_in"] == 2 and rep["rows_out"] == 1 and rep["rejected_bad_label"] == 1
    assert len(pd.read_parquet(tmp_path / "Dataset99.parquet")) == 1
