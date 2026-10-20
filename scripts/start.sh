#!/usr/bin/env bash
# Build (if needed) and start the whole stack, then wait until it is healthy.
source "$(dirname "$0")/_common.sh"

require_docker
ensure_env
check_artifacts
compose up -d --build
API_PORT="$(port_of API_PORT)"; API_PORT="${API_PORT:-8000}"
WEB_PORT="$(port_of WEB_PORT)"; WEB_PORT="${WEB_PORT:-8080}"
MOCK_PORT="$(port_of MOCK_PORT)"; MOCK_PORT="${MOCK_PORT:-8081}"
wait_healthy "http://localhost:${API_PORT}/api/health" 240
info "stack is up:"
info "  dashboard   http://localhost:${WEB_PORT}"
info "  API docs    http://localhost:${API_PORT}/docs"
info "  mock Zabbix http://localhost:${MOCK_PORT}/api_jsonrpc.php  (scenario: http://localhost:${MOCK_PORT}/_scenario/status)"
info "the demo scenario starts now: recon at +3 min, DDoS at +5 min, web attack at +10 min (loops every 12 min)"
