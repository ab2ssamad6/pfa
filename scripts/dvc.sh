#!/usr/bin/env bash
# Run any DVC command in Docker against the default remote (DagsHub; add -r s3 for local SeaweedFS), e.g.
#   ./scripts/dvc.sh pull        fetch data + model + replay pool for the current git commit
#   ./scripts/dvc.sh status      what changed since the last pipeline run
#   ./scripts/dvc.sh metrics diff main    compare metrics with another git revision
#   ./scripts/dvc.sh dag | params diff | exp show
source "$(dirname "$0")/_common.sh"
require_docker
[[ $# -gt 0 ]] || fail "usage: ./scripts/dvc.sh <dvc command> [args]"
# SeaweedFS is only needed when targeting the local s3 remote
[[ " $* " == *" -r s3 "* || " $* " == *" --remote s3 "* ]] && mlops_up
ml dvc "$@"
