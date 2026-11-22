# Project status and limitations

NetAD is complete as a final-year project. Every component below is implemented, tested and runs with
`./scripts/start.sh`.

| Area | State |
|---|---|
| ML pipeline | convert → prepare → train → bundle, reproducible with DVC; runs tracked in MLflow; Random Forest deployed |
| Mock Zabbix | Zabbix 7.0 JSON-RPC server with a 60 s scripted scenario; contract-tested against the Zabbix API examples in `mock_zabbix/tests/fixtures/zabbix_doc/` |
| Backend | FastAPI API + worker (ingestion, inference, incident correlation, retention), PostgreSQL 16 with Alembic |
| Frontend | React dashboard: overview, hosts, incidents (acknowledge/resolve), model page |
| Packaging | Docker Compose stack; model and replay pool distributed with DVC (DagsHub) and a GitHub Release fallback |
| Tests | ML 21, mock 17, backend 31, frontend 11, plus `scripts/smoke.sh` end to end |

## Design choices
1. **HistGradientBoosting instead of LightGBM**, so the whole ML stack stays within scikit-learn.
2. **Incidents are grouped by host**, not by (host, category): the model alternates DoS/DDoS per window, so a
   category key would fragment one attack. The dominant category and the distribution are stored instead.
3. **Python 3.11** in every image.
4. **A plain asyncio loop** in the worker instead of a scheduler library.
5. **Benign rows are never capped** in training, so the false-positive rate is measured on the real class balance.
6. **Random Forest is deployed.** HGB has near-equal metrics and a much smaller artifact and can replace it via
   `train.sh` + `promote.sh`.

## Known limitations
- **Domain shift.** CICIoT2023 is lab IoT traffic; thresholds must be re-validated on local labelled data.
- **No pfSense feature exporter.** A real deployment needs one to push window features to Zabbix
  ([real_zabbix.md](real_zabbix.md)).
- **No authentication.** All ports are bound to 127.0.0.1; this is an academic prototype.
- **Acknowledgements stay local.** They are not written back to Zabbix (`event.acknowledge`).
- **Problem recoveries** older than the 1 h event lookback are not applied.
- **No browser E2E suite.** UI workflows are covered by Vitest + Testing Library and by the HTTP smoke test.
- **Recharts 2.x** is pinned; v3 is the upstream successor.

See [ml_methodology.md §6](ml_methodology.md) for the ML limitations and future work.
