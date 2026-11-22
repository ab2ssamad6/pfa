#!/usr/bin/env bash
# Manage the MLOps services: SeaweedFS (S3 object store: DVC remote + MLflow artifacts) and MLflow (tracking + registry).
#   ./scripts/mlops.sh up | down | status | models
#   ./scripts/mlops.sh bootstrap    one-time: version the existing data, pipeline outputs and model
source "$(dirname "$0")/_common.sh"
require_docker
ensure_env

urls() {
  local c; c="$(port_of S3_CONSOLE_PORT)"
  info "  MLflow UI      $(mlflow_ui)"
  info "  S3 browser     http://localhost:${c:-8888}/buckets/   (S3 API on :8333, keys S3_ACCESS_KEY / S3_SECRET_KEY in .env)"
}

bootstrap() {
  mlops_up
  if [[ ! -f data.dvc ]]; then
    ls data/*.csv >/dev/null 2>&1 || fail "no CSV datasets in data/"
    info "1/4 versioning data/ (copies ~9 GB into .dvc/cache; files in data/ are not changed)"
    ml dvc add data
  fi
  if [[ ! -f dvc.lock ]] && [[ -d ml/work/splits && -f artifacts/replay/replay_pool.parquet ]]; then
    info "2/4 recording the existing pipeline outputs in dvc.lock (no recomputation)"
    ml dvc commit -f convert prepare replay_pool
  fi
  if ! ml python -m netad_ml.registry list 2>/dev/null | grep -q production; then
    local bundle; bundle="$(ls -d artifacts/models/*/ 2>/dev/null | head -1)"
    [[ -n "$bundle" ]] || fail "no model bundle in artifacts/models/ to register"
    info "3/4 registering ${bundle%/} in MLflow as production"
    ml python -m netad_ml.registry import-bundle "${bundle%/}"
  fi
  info "4/4 versioning artifacts/models and pushing everything to the DVC remote"
  ml dvc add artifacts/models
  ml dvc push
  info "bootstrap done. Commit the pointers:"
  info "  git add data.dvc dvc.lock artifacts/models.dvc artifacts/.gitignore .gitignore && git commit -m 'mlops: version data, pipeline and model'"
  urls
}

case "${1:-status}" in
  up)        mlops_up; urls ;;
  down)      compose --profile mlops stop s3 s3-init mlflow-db mlflow; info "MLOps services stopped (volumes kept)" ;;
  status)    compose --profile mlops ps s3 mlflow-db mlflow; urls ;;
  models)    mlops_up; ml python -m netad_ml.registry list ;;
  bootstrap) bootstrap ;;
  *)         fail "usage: ./scripts/mlops.sh up|down|status|models|bootstrap" ;;
esac
