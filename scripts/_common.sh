#!/usr/bin/env bash
# Shared helpers for the scripts in this folder. Sourced, not executed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

info()  { printf '\033[1;34m[netad]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[netad]\033[0m %s\n' "$*" >&2; }
fail()  { printf '\033[1;31m[netad] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

require_docker() {
  command -v docker >/dev/null 2>&1 || fail "Docker is not installed. Install Docker Desktop / Docker Engine first."
  docker info >/dev/null 2>&1 || fail "Docker daemon is not running (docker info failed). Start Docker and retry."
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required ('docker compose ...')."
}

compose() { docker compose "$@"; }

# The trainer container runs as the host user (files it writes into the repo stay yours)
HOST_UID="$(id -u)"; HOST_GID="$(id -g)"; export HOST_UID HOST_GID

# Run a command in the ML/MLOps container (repo mounted at /srv/project; has python, dvc, git, mlflow client)
ml() { compose --profile train run --rm trainer "$@"; }

# MLflow tracking server: MLFLOW_TRACKING_URI from .env, or the local `mlflow` service when unset.
mlflow_remote() { local u; u="$(port_of MLFLOW_TRACKING_URI)"; [[ -n "$u" && "$u" != http://mlflow:* ]]; }
mlflow_ui() {
  if mlflow_remote; then port_of MLFLOW_TRACKING_URI
  else local p; p="$(port_of MLFLOW_PORT)"; echo "http://localhost:${p:-5050}"; fi
}

# Start the S3 store (SeaweedFS: local DVC remote + MLflow artifact store) and MLflow (tracking + registry);
# idempotent. Skipped when MLflow is hosted (MLFLOW_TRACKING_URI): DVC then uses its default remote (DagsHub).
mlops_up() {
  ensure_env
  if mlflow_remote; then
    info "using hosted MLflow at $(mlflow_ui)"
    return 0
  fi
  info "starting MLOps services (S3 store, MLflow)"
  compose --profile mlops up -d --build mlflow >/dev/null
  local port; port="$(port_of MLFLOW_PORT)"; port="${port:-5050}"
  wait_healthy "http://localhost:${port}/health" 180 "mlflow s3 s3-init"
}

ensure_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    info "created .env from .env.example"
  fi
}

# Model bundle + replay pool are produced by scripts/train.sh (offline ML pipeline).
check_artifacts() {
  local ok=1
  if ! ls artifacts/models/*/metadata.json >/dev/null 2>&1; then
    warn "no trained model bundle in artifacts/models/"
    ok=0
  fi
  if [[ ! -f artifacts/replay/replay_pool.parquet ]]; then
    warn "no replay pool at artifacts/replay/replay_pool.parquet"
    ok=0
  fi
  if [[ $ok -eq 0 && ( -f artifacts/models.dvc || -f dvc.lock ) ]]; then
    # The default remote (DagsHub) is public: no credentials and no local MLOps services needed.
    info "artifacts are versioned with DVC — pulling the model and replay pool from the DagsHub remote"
    [[ -f artifacts/models.dvc ]] && ml dvc pull artifacts/models.dvc
    [[ -f dvc.lock ]] && ml dvc pull replay_pool
    ls artifacts/models/*/metadata.json >/dev/null 2>&1 && [[ -f artifacts/replay/replay_pool.parquet ]] \
      || fail "DVC pull did not restore the artifacts (check network access to dagshub.com)."
    return 0
  fi
  if [[ $ok -eq 0 ]]; then
    fail "ML artifacts missing — run ./scripts/train.sh first (needs the CSV datasets in data/)."
  fi
}

port_of() { grep -E "^$1=" .env 2>/dev/null | cut -d= -f2 || true; }

wait_healthy() {
  local url="$1" timeout="${2:-180}" services="${3:-api worker}" waited=0
  info "waiting for $url (timeout ${timeout}s)"
  until curl -fsS "$url" >/dev/null 2>&1; do
    sleep 3
    waited=$((waited + 3))
    if [[ $waited -ge $timeout ]]; then
      warn "service did not become healthy in ${timeout}s; recent logs:"
      compose --profile mlops logs --tail=40 $services || true
      fail "startup timed out — see logs above (./scripts/logs.sh)"
    fi
  done
}
