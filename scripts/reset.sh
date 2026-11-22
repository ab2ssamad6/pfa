#!/usr/bin/env bash
# Stop the stack and DELETE the database volume (all telemetry, predictions and incidents).
# ML artifacts, datasets, MLflow runs and the MinIO (DVC) store are not touched.
source "$(dirname "$0")/_common.sh"
require_docker
if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "This deletes all stored telemetry and incidents. Continue? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { info "aborted"; exit 0; }
fi
compose --profile mlops down
docker volume rm netad_pgdata >/dev/null   # compose project name is "netad"
info "database volume removed — ./scripts/start.sh starts from a clean state"
