#!/usr/bin/env bash
# Stop all containers. Database, MLflow and S3 data are kept (use reset.sh to wipe it).
source "$(dirname "$0")/_common.sh"
require_docker
compose --profile mlops down
info "stopped (database volume kept)"
