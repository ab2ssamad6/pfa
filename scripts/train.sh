#!/usr/bin/env bash
# Reproducible ML pipeline in Docker: `dvc repro` inside the trainer container.
#   convert (CSV -> Parquet) -> prepare (dedup + hash split) -> train (log to MLflow, register "candidate")
#   -> replay_pool. Only stages whose code, data or params.yaml changed are re-run.
#
#   ./scripts/train.sh              run what changed
#   ./scripts/train.sh --force      re-run every stage
#   ./scripts/train.sh train        run one stage (and what it depends on)
# Needs roughly 8 GB RAM for Docker. Afterwards compare runs in MLflow and ./scripts/promote.sh to deploy.
source "$(dirname "$0")/_common.sh"
require_docker

mlops_up
if ! ls data/*.csv >/dev/null 2>&1; then
  [[ -f data.dvc ]] || fail "no CSV datasets in data/ and no data.dvc to pull them from"
  info "data/ is empty — pulling the dataset version recorded in data.dvc"
  ml dvc pull data.dvc
fi
mkdir -p ml/work ml/reports artifacts

info "running the pipeline (dvc repro $*)"
ml dvc repro "$@"
info "pushing versioned outputs (data, replay pool) to the DVC remote"
ml dvc push
ml dvc metrics show
info "done — new model registered as 'candidate': $(mlflow_ui)"
info "deploy it with ./scripts/promote.sh   (then commit dvc.lock and artifacts/models.dvc)"
