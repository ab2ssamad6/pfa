# API reference

Interactive OpenAPI docs: `http://localhost:8000/docs` (generated from the Pydantic schemas in
`backend/app/api/schemas.py`). Timestamps are ISO-8601 UTC. All ports are bound to
127.0.0.1.

| Method & path | Description |
|---|---|
| `GET /api/health` | `status` ok/degraded/down; database, telemetry-source health, active model, worker freshness (stale after 30 s without a finished cycle) |
| `GET /api/overview` | KPI counts (incidents by status, windows and anomalies in the last 15 min of telemetry, pipeline lag) + health |
| `GET /api/pipeline/runs?limit=` | Latest worker cycles with counts and errors |
| `GET /api/hosts` | Hosts with latest score, active incidents, recent anomaly count |
| `GET /api/hosts/{id}` | One host |
| `GET /api/hosts/{id}/scores?minutes=30` | Attack-score timeline (≤1,500 points; longer ranges are bucketed with the max score per bucket) |
| `GET /api/hosts/{id}/metrics?minutes=30` | Zabbix numeric items (context only) |
| `GET /api/incidents?status=&host_id=&limit=&offset=` | Paginated incidents (`total`, `items`) |
| `GET /api/incidents/{id}` | Incident + anomalous windows + linked Zabbix problems + score timeline (±2 min) |
| `POST /api/incidents/{id}/acknowledge` `{"note": "…"}` | open → acknowledged. `409` otherwise |
| `POST /api/incidents/{id}/resolve` `{"note": "…"}` | open/acknowledged → resolved (manual). `409` if already resolved |
| `GET /api/anomalies?host_id=&limit=&offset=` | Anomalous windows, newest first, with their incident (or isolated) |
| `GET /api/events?active_only=` | Zabbix problem events (rule-based, from `event.get`) |
| `GET /api/model` | Active model: version, threshold rule, features, validation/test metrics, confusion matrix |
| `GET /api/demo/live-accuracy?minutes=15` | **Demo only.** Per-window agreement with the mock's ground truth. `404` when `DEMO_TRUTH_URL` is empty |

Errors use FastAPI's format: `{"detail": "incident 9 not found"}` with status 404/409/422/502.

## Mock Zabbix (port 8081)

`POST /api_jsonrpc.php` implements JSON-RPC 2.0 with the header `Authorization: Bearer <token>`
(`apiinfo.version` needs no auth). Methods: `apiinfo.version`, `host.get`, `item.get`, `history.get`, `trend.get`,
`event.get`, `problem.get`. Supported parameters: `output`, `hostids`/`itemids`/`eventids`, `filter.host|ip`,
`search.key_`, `history`, `time_from`/`time_till`, `sortfield`/`sortorder`, `limit`, `severities`, `value`,
`tags`, `countOutput`, `selectHosts|Tags|Interfaces|HostGroups|Groups|Inventory|ParentTemplates|Acknowledges|SuppressionData`.
Error codes: -32700 parse error, -32600 invalid request, -32601 method not found, -32602 invalid params / not authorised.

Demo control plane (not part of the Zabbix API): `GET /_scenario/status`, `GET /_scenario/truth?host=&time_from=&time_till=`,
`POST /_scenario/restart`, `POST /_scenario/outage?seconds=N` (HTTP 503 for N seconds), `GET /healthz`.
