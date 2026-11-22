# Machine-learning methodology

Every number in this document was produced by the code in `ml/netad_ml/` on the data in `data/`. The raw
outputs are in `ml/work/parquet/conversion_report.json`, `ml/work/splits/prepare_report.json`,
`ml/reports/experiments.json` and `artifacts/models/<version>/metadata.json`.

## 1. Dataset assessment

| Property | Finding |
|---|---|
| Origin | CICIoT2023 (Canadian Institute for Cybersecurity), a variant with 39 features plus `Label` |
| Files / rows | 63 CSV shards, 45,019,243 rows (65,724 – 920,543 per file) |
| Schema | The header is identical in all 63 files |
| Unit of observation | One **packet-window** summary (`Number` ≈ 100 packets): flag ratios, protocol shares, header/size statistics, `Rate`, `IAT` |
| Time information | **None.** No timestamp, flow id, IP or ordering column |
| Shard structure | Every file contains all 34 labels and the benign share is 2.24–2.40% in each, so the shards are random partitions of one shuffled dataset, not separate environments |
| Truncated files | Datasets 42, 44, 46–52 end mid-row (one partial line each) |
| Invalid values | 670 rows with NaN `Std`/`Variance`; 321 further rows with `Rate = inf`; 2 rows with negative `IAT` |
| Exact duplicates | **24,317,191 rows (54%)** duplicate another row, most of them *across* files |
| Label noise | 598,054 distinct feature vectors carry more than one label |
| Redundant columns | `AVG ≡ Tot size` and `IPv ≡ LLC` in 100% of rows (row-level check), so both were dropped |
| Class balance (unique rows) | DDoS 58.6%, DoS 19.5%, Mirai 11.4%, **Benign 5.1%**, Recon 3.2%, Spoofing 2.1%, Web 0.11%, BruteForce 0.06% |

**Consequences**
1. A chronological split is impossible, and grouping by file is meaningless, so the split is random.
2. Because 54% of rows are duplicated across files, a file-based split (as in `training.ipynb`) leaks heavily.
3. Attacks are the majority class. Real networks are benign-majority, so precision is also reported at a
   re-weighted 10% attack prevalence.

## 2. Review of the original notebook (`training.ipynb`, kept unchanged)

| Issue | Effect |
|---|---|
| Column names don't match the data (`label` vs `Label`; `flow_duration`, `Srate`, `Magnitue`… do not exist) | Crashes with `KeyError` |
| Label dictionaries use mixed case, the data is upper-case | `KeyError` in the 8- and 2-class sections |
| `scaler.fit()` called once per file | Only the last training file determines the scaling |
| `model.fit()` called once per file | The final model has only seen the last training file |
| `f1_score(y_pred, y_test)` | Arguments reversed: precision and recall swapped |
| No handling of `inf`/NaN, no dedup, no seed, no artifact | Not reproducible; LR raises on `inf` |
| File-based 80/20 split | Leaks because of cross-file duplicates |

Kept from the notebook: the three label granularities and the idea of a linear baseline.

## 3. Pipeline

1. **convert.** Validates the header, parses every value explicitly, rejects (and counts) bad labels, NaN and inf,
   and stores float32 Parquet. Result: 45,018,243 valid rows.
2. **prepare.**
   - `split = hash(feature values) mod 1000` → train < 700 ≤ validation < 850 ≤ test. Identical feature vectors
     always land in the same split, including label-conflicting copies, which prevents leakage *by construction*.
   - Then a global exact deduplication: 20,701,052 unique rows (train 14.49M / val 3.11M / test 3.10M).
3. **train.**
   - Each attack label is capped at about 100k training rows and **all benign rows are kept**, giving 2,950,245
     rows (seed 42).
   - Class-balanced weights are used.
   - Validation is split into half A (1.5M rows, isotonic calibration on the natural distribution) and half B
     (1.6M rows, threshold selection and model selection).
   - The test split is used once, for the final evaluation.
4. **Target.** One 8-class model. The binary alert score is `p_attack = 1 − P(Benign)`, and the category hint is
   the most likely attack class.
5. **Threshold.** The smallest `t` with benign FPR ≤ 1% on validation B (`threshold_for_fpr`, unit-tested).
6. **Artifact.** `model.joblib` (calibrated estimator) plus `metadata.json` (feature order, categories, threshold,
   metrics, seed, library versions, sha256). `ModelBundle.load` verifies the hash and the class order, and
   `predict` rejects missing or non-finite features.
7. **Replay pool.** 44,352 rows (up to 1,500 per label) sampled from the **test split only**, used by the mock.

## 4. Candidates and results

Hyper-parameters: LR = signed-log + standard scaling, `class_weight=balanced`. RF = 100 trees, `max_depth` 20,
`min_samples_leaf` 5, `max_samples` 0.3. HGB = 300 iterations, early stopping, 63 leaves.

### Validation B (model selection; threshold fixed at FPR ≤ 1%)

| Experiment | Attack recall | FPR | 8-class macro-F1 | Threshold | Fit time |
|---|---|---|---|---|---|
| Logistic Regression | 0.9552 | 0.98% | 0.498 | 0.733 | 552 s |
| Random Forest | **0.9737** | 1.00% | 0.698 | 0.864 | 152 s |
| HistGradientBoosting | 0.9723 | 1.00% | 0.711 | 0.841 | 224 s |
| HGB without `IAT` | 0.9722 | 1.00% | 0.713 | 0.846 | 156 s |
| HGB without `IAT`, `Time_To_Live` | 0.9726 | 1.00% | 0.709 | 0.827 | 149 s |
| HGB binary-only | 0.9754 | 0.88% | (binary) | 0.877 | 85 s |

### Test split (3,104,653 unique windows, 157,455 benign)

| Model | Recall | FPR | Precision | Precision @10% prevalence | ROC-AUC | PR-AUC (benign) | Brier | macro-F1 | µs/row | Size on disk |
|---|---|---|---|---|---|---|---|---|---|---|
| Logistic Regression | 0.9549 | 0.91% | — | 0.921 | 0.9893 | 0.780 | 0.020 | 0.499 | 1.5 | <0.1 MB |
| **Random Forest (deployed)** | **0.9734** | **1.02%** | **0.9994** | 0.914 | 0.9959 | 0.911 | 0.011 | 0.702 | 4.9 | 275 MB (86 MB compressed) |
| HistGradientBoosting | 0.9721 | 1.02% | — | 0.914 | 0.9958 | 0.909 | 0.012 | 0.714 | 11.6 | 3.9 MB |
| HGB binary-only | 0.9752 | 0.89% | — | 0.924 | 0.9964 | 0.919 | 0.010 | — | 4.3 | 2.2 MB |

Random Forest confusion counts at the threshold: TP 2,868,947 · FP 1,611 · FN 78,251 · TN 155,844.

### Per-category recall on test

| Category | LR | **RF** | HGB |
|---|---|---|---|
| Benign | 0.919 | 0.877 | 0.894 |
| DDoS | 0.973 | 0.944 | 0.939 |
| DoS | 0.113 | 0.468 | 0.480 |
| Mirai | 0.993 | 0.996 | 0.997 |
| Recon | 0.461 | 0.750 | 0.736 |
| Spoofing | 0.298 | 0.846 | 0.847 |
| Web | 0.000 | 0.190 | 0.236 |
| BruteForce | 0.158 | 0.296 | 0.331 |

(Per-category values use the arg-max class; the binary alert uses the calibrated threshold.)

### Interpretation
- **Binary detection is strong.** About 97% of attack windows are flagged at a 1% false-positive budget.
- **The category is a hint.** DoS and DDoS look alike at the window level, because the difference is the number of
  sources, which these features don't capture. Web and BruteForce have too few examples. The UI therefore shows
  a distribution and the wording "suspected".
- **Leakage check.** Removing `IAT`/`TTL` changes recall by less than 0.05 percentage points, so these
  features do not act as capture-session fingerprints in this variant. They are kept.
- **Binary versus 8-class.** A dedicated binary model gains only about 0.2 percentage points of recall, which
  doesn't justify losing the category hint.
- **Model choice.** The rule "highest validation recall, then macro-F1" selected Random Forest (by 0.14 percentage
  points), and it is the deployed model. HGB has near-identical metrics, a 20× smaller artifact and slightly higher
  macro-F1, so it remains a drop-in alternative (retrain with it selected, then `promote.sh`).

### False positives versus false negatives
At FPR 1% and about 0.5 windows/s per host, a purely benign host produces about 18 anomalous windows per hour.
The 3-of-5 debounce makes an incident from benign noise very unlikely (independent-error approximation:
C(5,3)·0.01³ ≈ 1e-5 per window). Missed windows (FN ≈ 2.7%) rarely prevent detection, because an attack lasts
many windows. A higher threshold would trade attack coverage, mostly Recon and Web, for fewer alerts.

## 5. Live demo check (scenario ground truth)
Over a 10-minute window: 903 windows, precision 0.915, recall 0.701, FPR 0.61%.
Recall is lower than offline because the scenario over-represents the hard classes (Recon, Web).
These are **demo** numbers, not a benchmark.

## 6. Limitations and future work
- **Domain shift.** CICIoT2023 is lab IoT traffic. The pfSense network in the target deployment differs, so
  thresholds and models must be re-validated on local labelled data.
- **Feature exporter.** A real deployment needs an exporter that produces the same window features from pfSense
  traffic (softflowd / CICFlowMeter-style aggregation pushed with `zabbix_sender`). That exporter isn't part of
  this project.
- **No temporal modelling.** Windows are scored independently. Temporal context only enters through incident
  grouping.
- **Label noise.** 598k conflicting vectors cap the achievable accuracy.
- **Possible improvements.** Unsupervised baselines on Zabbix numeric items , drift
  monitoring, and periodic retraining with analyst feedback (acknowledged/false-positive incidents as labels).

## 7. Reproduce
```bash
./scripts/train.sh            # Docker: dvc repro + MLflow tracking (docs/mlops.md); or locally:
python -m netad_ml.convert && python -m netad_ml.prepare && python -m netad_ml.train && python -m netad_ml.replay_pool
```
Memory: training checkpoints each model to `ml/work/checkpoints/` and frees it, so a full run fits in a 7 GB
container. Reruns resume from checkpoints. If memory is short, lower `--cap`.
