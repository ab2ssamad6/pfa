#!/usr/bin/env bash
# Demo controls for the mock Zabbix scenario.
#   ./scripts/demo.sh status        current phase of the scenario
#   ./scripts/demo.sh restart       restart the scenario timeline from "normal" now
#   ./scripts/demo.sh outage [30]   make the mock API return HTTP 503 for N seconds
source "$(dirname "$0")/_common.sh"
ensure_env
MOCK_PORT="$(port_of MOCK_PORT)"; MOCK_PORT="${MOCK_PORT:-8081}"
BASE="http://localhost:${MOCK_PORT}/_scenario"
case "${1:-status}" in
  status)  curl -fsS "$BASE/status"; echo ;;
  restart) curl -fsS -X POST "$BASE/restart"; echo; info "scenario restarted: recon in 3 min, DDoS in 5 min" ;;
  outage)  curl -fsS -X POST "$BASE/outage?seconds=${2:-30}"; echo; info "source outage injected — watch the dashboard banner" ;;
  *) fail "usage: $0 status|restart|outage [seconds]" ;;
esac
