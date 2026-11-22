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

# Start MinIO (DVC remote + MLflow artifact store) and MLflow (tracking + registry); idempotent.
mlops_up() {
  ensure_env
  info "starting MLOps services (MinIO, MLflow)"
  compose --profile mlops up -d --build mlflow >/dev/null
  local port; port="$(port_of MLFLOW_PORT)"; port="${port:-5050}"
  wait_healthy "http://localhost:${port}/health" 180 "mlflow minio minio-init"
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
    info "artifacts are versioned with DVC — pulling them from the MinIO remote"
    mlops_up
    [[ -f artifacts/models.dvc ]] && ml dvc pull artifacts/models.dvc
    [[ -f dvc.lock ]] && ml dvc pull replay_pool
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
