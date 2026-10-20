#!/usr/bin/env bash
# Stop the stack and DELETE the database volume (all telemetry, predictions and incidents).
# ML artifacts in artifacts/ and the datasets in data/ are not touched.
source "$(dirname "$0")/_common.sh"
require_docker
if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "This deletes all stored telemetry and incidents. Continue? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { info "aborted"; exit 0; }
fi
compose down -v
info "database volume removed — ./scripts/start.sh starts from a clean state"
