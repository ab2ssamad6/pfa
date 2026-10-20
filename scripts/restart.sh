#!/usr/bin/env bash
# Restart one service (e.g. ./scripts/restart.sh worker) or the whole stack.
source "$(dirname "$0")/_common.sh"
require_docker
if [[ $# -gt 0 ]]; then
  compose restart "$@"
else
  "$ROOT/scripts/stop.sh"
  "$ROOT/scripts/start.sh"
fi
