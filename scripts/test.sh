#!/usr/bin/env bash
# Run all test suites.
#   ./scripts/test.sh          in Docker (only Docker needed)
#   ./scripts/test.sh --local  with local toolchains (ml/.venv with all deps + npm)
source "$(dirname "$0")/_common.sh"

status=0
step() { info "── $1"; shift; if "$@"; then info "   passed"; else warn "   FAILED"; status=1; fi; }

if [[ "${1:-}" == "--local" ]]; then
  PY="$ROOT/ml/.venv/bin/python"
  [[ -x "$PY" ]] || fail "ml/.venv not found — see docs/development.md for the local setup"
  export LANG=C.UTF-8 LC_ALL=C.UTF-8
  step "ML pipeline"     bash -c "cd ml && '$PY' -m pytest -q"
  step "mock Zabbix"     bash -c "cd mock_zabbix && '$PY' -m pytest -q"
  step "backend"         bash -c "cd backend && '$PY' -m pytest -q"
  step "frontend"        bash -c "cd frontend && npx vitest run"
  step "frontend types"  bash -c "cd frontend && npx tsc -b --noEmit"
else
  require_docker
  step "ML pipeline"  compose --profile train run --rm -w /srv/project/ml trainer python -m pytest -q -p no:cacheprovider
  step "mock Zabbix + backend (real PostgreSQL via pgserver)" compose --profile test run --rm backend-tests
  step "mock Zabbix (unit + contract)" compose --profile test run --rm -w /srv/project/mock_zabbix backend-tests \
       python -m pytest -q -p no:cacheprovider
  step "frontend"     docker run --rm -v "$ROOT/frontend:/app:ro" -w /tmp node:20.18.1-alpine \
       sh -c "cp -r /app /tmp/fe && cd /tmp/fe && rm -rf node_modules && npm ci --no-audit --no-fund >/dev/null && npx vitest run && npx tsc -b --noEmit"
fi
[[ $status -eq 0 ]] && info "all suites passed" || fail "some suites failed"
