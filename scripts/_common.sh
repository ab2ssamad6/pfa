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

sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

artifacts_present() { ls artifacts/models/*/metadata.json >/dev/null 2>&1 && [[ -f artifacts/replay/replay_pool.parquet ]]; }

# Download the release tarball recorded in artifacts/release.lock, verify its sha256, extract it into artifacts/.
fetch_release_artifacts() {
  [[ -f artifacts/release.lock ]] || return 1
  local url sha tmp
  url="$(grep -E '^ARTIFACTS_URL=' artifacts/release.lock | cut -d= -f2-)"
  sha="$(grep -E '^ARTIFACTS_SHA256=' artifacts/release.lock | cut -d= -f2-)"
  [[ -n "$url" && -n "$sha" ]] || return 1
  command -v curl >/dev/null 2>&1 || fail "curl is required to download the ML artifacts"
  tmp="$(mktemp)"
  info "downloading the model and replay pool from $url"
  if ! curl -fL --retry 3 -o "$tmp" "$url"; then rm -f "$tmp"; warn "download failed"; return 1; fi
  if [[ "$(sha256_of "$tmp")" != "$sha" ]]; then rm -f "$tmp"; fail "artifact tarball sha256 mismatch (expected $sha)"; fi
  # only accept members under artifacts/models/ or artifacts/replay/
  if tar -tzf "$tmp" | grep -vqE '^artifacts/(models|replay)(/|$)' || tar -tzf "$tmp" | grep -q '\.\.'; then
    rm -f "$tmp"; fail "artifact tarball contains unexpected paths"
  fi
  tar -xzf "$tmp"
  rm -f "$tmp"
}

# Model bundle + replay pool, in order of preference: already on disk; DVC pull (owner, with credentials in
# .dvc/config.local); the public GitHub Release in artifacts/release.lock (anyone, no account); else train.
check_artifacts() {
  artifacts_present && return 0
  warn "ML artifacts (model bundle, replay pool) are missing in artifacts/"
  if [[ -f .dvc/config.local && -f artifacts/models.dvc ]]; then
    info "pulling them with DVC (credentials found in .dvc/config.local)"
    ml dvc pull artifacts/models.dvc || true
    [[ -f dvc.lock ]] && { ml dvc pull replay_pool || true; }
    artifacts_present && return 0
    warn "DVC pull did not restore the artifacts"
  fi
  fetch_release_artifacts || true
  artifacts_present && return 0
  fail "ML artifacts missing: no release download available (artifacts/release.lock) — run ./scripts/train.sh"
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
