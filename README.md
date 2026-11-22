# NetAD — AI-assisted network anomaly detection for a pfSense / Zabbix monitoring stack

University final-year project. NetAD extends a pfSense + Zabbix monitoring concept with a machine-learning
pipeline. It pulls flow-window telemetry from Zabbix's API (a faithful mock is bundled), scores every window with
a model trained on CICIoT2023-derived data, groups anomalous windows into incidents with a lifecycle, and shows
everything on a React dashboard.

> Scores are **model predictions**, not confirmed attacks. The dashboard always says "suspected" and shows the score.

```text
mock Zabbix (JSON-RPC) ──► worker: ingest ─► infer (Random Forest) ─► correlate ──► PostgreSQL ◄── FastAPI ◄── React
```

## Quick start (Docker only)

Prerequisites: Docker Engine / Desktop with Compose v2, about 4 GB free RAM, ports 8080/8000/8081/5432 free on localhost.

```bash
git clone <repo-url> && cd pfa
./scripts/start.sh          # downloads the trained model + replay pool (~85 MB, sha256-verified) on first run,
                            # builds images, starts db + mock-zabbix + api + worker + web, waits for health
open http://localhost:8080  # dashboard (API docs: http://localhost:8000/docs)
./scripts/smoke.sh          # optional end-to-end check through the web proxy
```

The demo scenario starts when the mock starts: **recon at +3 min, DDoS at +5 min, web attack at +10 min**, and then
it loops every 12 minutes. See [docs/demo.md](docs/demo.md) for the defence walkthrough.

| Script | Purpose |
|---|---|
| `scripts/setup.sh` | Checks prerequisites, creates `.env`, verifies ML artifacts, builds images |
| `scripts/start.sh` / `stop.sh` / `restart.sh [svc]` | Lifecycle (the database volume persists) |
| `scripts/logs.sh [svc…]` | Follow logs |
| `scripts/reset.sh` | Stops the stack and **deletes** the database volume |
| `scripts/test.sh [--local]` | Runs all test suites (in Docker, or with local toolchains) |
| `scripts/smoke.sh [url]` | End-to-end smoke test against a running stack |
| `scripts/demo.sh status\|restart\|outage N` | Scenario controls for live demos |
| `scripts/train.sh [--force\|stage]` | Reproducible ML pipeline (`dvc repro` in Docker), logged to MLflow |
| `scripts/promote.sh [ref]` | Deploy a registered model version to `artifacts/models` (versioned by DVC) |
| `scripts/mlops.sh up\|down\|status\|models\|bootstrap` | S3 store (SeaweedFS) + MLflow services, registry listing, one-time migration |
| `scripts/package_artifacts.sh [tag] [owner/repo]` | Package the model + replay pool for a GitHub Release (writes `artifacts/release.lock`) |
| `scripts/dvc.sh <cmd>` | Any DVC command in Docker (`pull`, `status`, `metrics diff`, …) |

The model (`artifacts/models/…`) and replay pool (`artifacts/replay/…`) are versioned with DVC in an S3 store (SeaweedFS).
`start.sh` pulls them when they are missing. See [docs/mlops.md](docs/mlops.md) for the train → track → promote
workflow.

## Repository layout

```text
ZABBIX_doc/  data/  training.ipynb  todo.md   original project resources (unchanged)
ml/            netad_ml package: convert → prepare → train → runtime bundle, MLflow tracking/registry (+ tests, Dockerfile)
mlops/         MLflow server image;  dvc.yaml + params.yaml at the root define the pipeline
artifacts/     models/<version>/{model.joblib,metadata.json,confusion_matrix.png}, replay/replay_pool.parquet
mock_zabbix/   Zabbix 7.0-compatible JSON-RPC mock + scripted scenario (+ contract tests vs ZABBIX_doc)
backend/       FastAPI API + worker (ingestion, inference, incidents), SQLAlchemy models, Alembic migrations
frontend/      React 18 + Vite + TypeScript + TanStack Query + Recharts + Tailwind dashboard
scripts/       operational shell scripts
docs/          architecture, ML methodology, API, demo, real-Zabbix integration, development, status
```

## Key results (held-out test split: 3.10M unique windows)

| Model | Attack recall | FPR | ROC-AUC | 8-class macro-F1 |
|---|---|---|---|---|
| Logistic Regression (baseline) | 0.955 | 0.91% | 0.989 | 0.499 |
| **Random Forest (deployed)** | **0.973** | **1.02%** | **0.996** | **0.702** |
| HistGradientBoosting | 0.972 | 1.02% | 0.996 | 0.714 |

The threshold was chosen on validation data for benign FPR ≤ 1%. Full methodology, dataset audit and limitations are in
[docs/ml_methodology.md](docs/ml_methodology.md).

## Documentation

- [Architecture](docs/architecture.md): components, data flows, ERD, adapter abstraction, incident lifecycle
- [ML methodology](docs/ml_methodology.md): dataset assessment, preprocessing, model selection, evaluation, limitations
- [API reference](docs/api.md)
- [Demo guide](docs/demo.md)
- [Connecting a real Zabbix](docs/real_zabbix.md)
- [Development & testing](docs/development.md)
- [Implementation status & known limitations](docs/status.md)
