#!/usr/bin/env bash
# Follow logs: ./scripts/logs.sh            (all services)
#              ./scripts/logs.sh worker api (selected services)
source "$(dirname "$0")/_common.sh"
require_docker
compose logs -f --tail=100 "$@"
