#!/usr/bin/env bash
# One-time setup: check prerequisites, create .env, verify ML artifacts, build images.
source "$(dirname "$0")/_common.sh"

require_docker
ensure_env
check_artifacts
info "building images (first run downloads base images; can take a few minutes)"
compose build
info "setup complete — run ./scripts/start.sh"
