# MLOps workflow: DVC + MLflow + S3 (SeaweedFS)

Git holds code and small pointer files. Large binaries (the 8.7 GB dataset, model bundles, the replay pool)
live in an S3 object store, and every step runs in Docker.

| Tool | Role | Where |
|---|---|---|
| **DVC** | Versions `data/`, `artifacts/models/` and `artifacts/replay/`. Defines the reproducible pipeline (`dvc.yaml`, `params.yaml`, `dvc.lock`) | `trainer` container |
| **MLflow** | Experiment tracking (params, metrics, plots, the bundle for every run) and the **model registry** (`candidate` / `production` aliases) | `mlflow` service, UI at http://localhost:5050 |
| **SeaweedFS** | S3-compatible store (MinIO stopped publishing public images): bucket `netad-dvc` (DVC remote) and `mlflow` (MLflow artifacts). To move to AWS S3, change the endpoint and keys | `s3` service, S3 API :8333, file browser at http://localhost:8888/buckets/ |
| PostgreSQL | MLflow run and registry metadata | `mlflow-db` service |

```mermaid
flowchart LR
  D[data/ CSV<br/>data.dvc] --> C[convert] --> P[prepare] --> T[train] --> R[(MLflow registry<br/>alias candidate)]
  P --> RP[replay_pool<br/>artifacts/replay]
  R -- promote.sh --> M[artifacts/models<br/>artifacts/models.dvc] --> API[api / worker]
  RP --> MOCK[mock-zabbix]
```

## Daily workflow

```bash
./scripts/mlops.sh up            # S3 store + MLflow (other scripts start them automatically)
# edit params.yaml or ml/netad_ml/*.py
./scripts/train.sh               # dvc repro: re-runs only the stages that changed, logs the run to MLflow,
                                 # registers the new version as "candidate", then dvc push
# compare runs in the MLflow UI, or: ./scripts/dvc.sh metrics diff HEAD
./scripts/promote.sh             # registry "candidate" -> artifacts/models (sha256 verified) -> alias "production"
git add dvc.lock artifacts/models.dvc params.yaml && git commit -m "model: promote <version>"
./scripts/restart.sh api worker
```

- Roll back: `./scripts/promote.sh <registry version>` (see `./scripts/mlops.sh models`).
- Fresh clone or another machine: when the model or replay pool is missing, `./scripts/start.sh` runs
  `dvc pull` if DVC credentials are in `.dvc/config.local`. Otherwise it downloads the GitHub Release tarball
  named in `artifacts/release.lock` and checks its sha256. No account is needed. DagsHub requires a login
  even for public repos, so it can't serve anonymous users.
- Publish a release after promoting a model: `./scripts/package_artifacts.sh v1.1 <owner>/<repo>`, commit
  `artifacts/release.lock`, push, then `gh release create v1.1 dist/netad-artifacts-v1.1.tar.gz`.
- Retraining from a fresh clone (`train.sh`) pulls `data/` (9.3 GB) from DagsHub, which needs a free DagsHub
  account and a token in `.dvc/config.local`.
- Pushing to DagsHub needs a token in `.dvc/config.local` (see the comments in `.dvc/config`). The local SeaweedFS
  remote is still available as `-r s3`.
- Code is hosted on GitHub. `.github/workflows/mirror-dagshub.yml` mirrors every push to DagsHub (secret
  `DAGSHUB_TOKEN`), so the DagsHub repository shows the DVC-tracked dataset and models next to the code.
- Any DVC command: `./scripts/dvc.sh status | dag | params diff | metrics show`.

## Design decisions

- **The bundle format stays the model format.** MLflow stores the existing `model.joblib` + `metadata.json`
  (sha256) as the run artifact `bundle/` and registers that path. It does not use an MLflow sklearn flavour.
  The backend still loads only through `netad_ml.runtime.ModelBundle` and **does not depend on MLflow at
  runtime**. If the MLflow server is down, serving is unaffected.
- **Promotion is explicit.** Training never changes what is served. `promote.sh` verifies the sha256, replaces
  the single bundle in `artifacts/models/` (the backend serves the newest bundle it finds there) and commits it
  to DVC, so each git commit pins the exact model the stack serves.
- **Intermediate outputs are not cached** (`ml/work/*`, `cache: false`). They are derived from versioned data
  and code, and caching them would double the disk use.
- The train stage always runs with `--fresh`, so a parameter change can never reuse stale checkpoints.
- Traceability: each MLflow run is tagged with `git_commit`, `data_md5` (from `data.dvc`), `bundle_version`
  and `sha256`.
- Artifacts are proxied through MLflow (`--serve-artifacts`), so only the MLflow server holds S3 credentials
  for its bucket.
- The `trainer` container runs as the host user, so files it writes into the repo are not owned by root.

## One-time migration (repositories that predate DVC)

```bash
./scripts/mlops.sh bootstrap
```
1. `dvc add data` copies the files into `.dvc/cache` (cache type `copy`, so `data/` is never modified).
2. `dvc commit` records the existing `ml/work` and replay outputs in `dvc.lock` without recomputing them.
3. It registers the existing bundle in MLflow as `production`.
4. It runs `dvc add artifacts/models`, then `dvc push`.

Then commit `data.dvc dvc.lock artifacts/models.dvc`.
The first `train.sh` after this runs the `train` stage, because it has never run under DVC.

Disk: `.dvc/cache` (~10 GB) plus the `s3-data` volume (~10 GB). `reset.sh` deletes only the application
database. `s3-data` and `mlflow-pg` hold the versioned history, so only remove them on purpose.

The model bundle committed before the migration remains in git history. Model versions are no longer stored in git.

## Hosted MLflow (DagsHub)

Tracking and the model registry can use DagsHub's free hosted MLflow instead of the local `mlflow` service.
Set these in `.env` (never commit it):

```bash
MLFLOW_TRACKING_URI=https://dagshub.com/ab2ssamad6/pfa.mlflow
MLFLOW_TRACKING_USERNAME=ab2ssamad6
MLFLOW_TRACKING_PASSWORD=<dagshub token>
```

The trainer container then logs runs and registers versions there. `train.sh`, `promote.sh`, `dvc.sh` and
`mlops.sh models` skip starting SeaweedFS and the local MLflow. Runs and models are visible at
https://dagshub.com/ab2ssamad6/pfa/experiments and `/models`. Leave `MLFLOW_TRACKING_URI` empty to go back to
the local stack.
