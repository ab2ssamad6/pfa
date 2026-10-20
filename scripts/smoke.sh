#!/usr/bin/env bash
# End-to-end smoke test against a RUNNING stack, through the web server's /api proxy
# (the same path the browser uses). Waits for the demo scenario to produce incidents.
#   ./scripts/smoke.sh                      # http://localhost:8080
#   ./scripts/smoke.sh http://localhost:4173
set -euo pipefail
BASE="${1:-http://localhost:8080}"
TIMEOUT="${SMOKE_TIMEOUT:-600}"
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✘ %s\033[0m\n' "$*" >&2; exit 1; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"; }

echo "smoke test against $BASE"
curl -fsS "$BASE/" | grep -q '<div id="root">' || die "dashboard HTML not served"
ok "dashboard served"
curl -fsS -o /dev/null "$BASE/incidents/1" || die "SPA fallback route failed"
ok "SPA routes fall back to index.html"

h=$(curl -fsS "$BASE/api/health") || die "API not reachable through proxy"
[[ $(json 'd["database"]' <<<"$h") == True ]] || die "database not healthy"
[[ $(json 'd["model"]["algorithm"]' <<<"$h") != "" ]] || die "no active model"
ok "API healthy, model $(json 'd["model"]["version"]' <<<"$h"), source $(json 'd["source"]["state"]' <<<"$h")"

n=$(curl -fsS "$BASE/api/hosts" | json 'len(d)')
[[ "$n" -ge 1 ]] || die "no hosts ingested"
ok "$n hosts discovered from (mock) Zabbix"

echo "  waiting up to ${TIMEOUT}s for the scenario to raise an incident…"
waited=0
until [[ $(curl -fsS "$BASE/api/incidents" | json 'd["total"]') -gt 0 ]]; do
  sleep 5; waited=$((waited + 5))
  [[ $waited -lt $TIMEOUT ]] || die "no incident after ${TIMEOUT}s"
done
inc=$(curl -fsS "$BASE/api/incidents" | json 'd["items"][-1]["id"]')
detail=$(curl -fsS "$BASE/api/incidents/$inc")
ok "incident #$inc: suspected $(json 'd["category"]' <<<"$detail") on $(json 'd["host_name"]' <<<"$detail"), $(json 'd["anomaly_count"]' <<<"$detail") anomalous windows, $(json 'len(d["events"])' <<<"$detail") linked Zabbix problem(s)"

st=$(json 'd["status"]' <<<"$detail")
if [[ "$st" == "open" ]]; then
  r=$(curl -fsS -X POST -H 'Content-Type: application/json' -d '{"note":"smoke test"}' "$BASE/api/incidents/$inc/acknowledge")
  [[ $(json 'd["status"]' <<<"$r") == acknowledged ]] || die "acknowledge failed"
  ok "incident acknowledged via API"
fi
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' "$BASE/api/incidents/999999/resolve")
[[ "$code" == 404 ]] || die "expected 404 for unknown incident, got $code"
ok "error handling (404) correct"
echo "smoke test passed"
