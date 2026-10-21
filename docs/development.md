# Development & testing

## Test suites (78 tests)

| Suite | Path | Tests | What it covers |
|---|---|---|---|
| ML | `ml/tests` | 19 | taxonomy, CSV validation (inf/NaN/truncated lines), hash split determinism and no train/test overlap, dedup, label conflicts, threshold/FPR maths, metric maths, full train→bundle pipeline on synthetic data, bundle sha256 tamper detection, feature validation |
| Mock Zabbix | `mock_zabbix/tests` | 17 | **contract vs `ZABBIX_doc/*.json`**, auth/JSON-RPC errors, determinism, paging/limits, no future values, scenario ground truth, metric spikes, events/recoveries, `problem.get`, outage |
| Backend | `backend/tests` | 31 | migrations match models (autogenerate diff empty) + downgrade/upgrade, adapter contract and failure modes, idempotent ingestion and watermarks, incident rules (debounce, gap, auto-resolve, recurrence, lifecycle, linking, severity, backlog draining), **end-to-end pipeline with the real RF model**, REST API, invalid window handling, outage → health → recovery |
| Frontend | `frontend/src/test` | 11 | API client errors, Overview, error/empty states, health banner, incident filter, acknowledge workflow (POST body, refresh), 409 handling, Model page |
| Smoke | `scripts/smoke.sh` | — | Running stack via the web proxy: SPA, health, hosts, waits for an incident, acknowledge, 404 |

The backend tests run against **real PostgreSQL 16** (the `pgserver` wheel bundles the binaries). It needs
`LANG=C.UTF-8` and a non-root user.

```bash
./scripts/test.sh            # everything in Docker
./scripts/test.sh --local    # local toolchains (below)
```

## Local setup without Docker
```bash
python3.11 -m venv ml/.venv
ml/.venv/bin/pip install -e "ml[train,dev]" -r backend/requirements.txt -r backend/requirements-dev.txt -r mock_zabbix/requirements.txt
(cd frontend && npm ci)
export LANG=C.UTF-8 LC_ALL=C.UTF-8
```
Run the services (each in its own terminal; `DATABASE_URL` must point to a migrated Postgres):
```bash
cd mock_zabbix && MOCK_REPLAY_POOL=../artifacts/replay/replay_pool.parquet ../ml/.venv/bin/uvicorn zabbix_mock.main:app --port 8081
cd backend && DATABASE_URL=... ../ml/.venv/bin/alembic upgrade head
cd backend && DATABASE_URL=... MODEL_DIR=../artifacts/models ../ml/.venv/bin/uvicorn app.api.main:app --port 8000
cd backend && DATABASE_URL=... MODEL_DIR=../artifacts/models ../ml/.venv/bin/python -m app.worker
cd frontend && npm run dev     # http://localhost:5173, proxies /api to :8000
```

## Database migrations
- Models: `backend/app/db/models.py`. Migrations: `backend/alembic/versions/`.
- New migration: `cd backend && DATABASE_URL=... alembic revision --autogenerate -m "..."`, then review it.
  Autogenerate does not drop enum types in `downgrade()`.
- `test_migration_matches_models` fails if the models and migrations diverge.
- In Docker, the api container applies `alembic upgrade head` on start (with retries).

## Conventions
- Configuration only through environment variables (`backend/app/core/config.py`, `.env.example`).
- Feature order and taxonomy have a single source: `ml/netad_ml/schema.py`. The model bundle records the
  exact feature list, and the backend uses it through `netad_ml.runtime.ModelBundle`.
- Dependencies are pinned (`ml/pyproject.toml`, `ml/requirements.lock`, `backend/requirements*.txt`,
  `mock_zabbix/requirements.txt`, `frontend/package-lock.json`). scikit-learn **must stay 1.5.2** for the
  committed RF bundle to load.
