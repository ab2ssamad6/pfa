#!/usr/bin/env bash
# Stop all containers. Database data is kept (use reset.sh to wipe it).
source "$(dirname "$0")/_common.sh"
require_docker
compose down
info "stopped (database volume kept)"
