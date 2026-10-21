# Implementation status (2026-10-20)

| Phase | Status | Evidence |
|---|---|---|
| 0 Discovery | done | dataset audit of all 45M rows; notebook and Zabbix JSON review |
| 1 Design | done, approved | single adapter + fake Zabbix server; RF/HGB/LR candidates; 8-class model; 3-of-5 / 60 s / 120 s |
| 2 ML | done | `ml/reports/experiments.json`, bundle `artifacts/models/random_forest-20261017112951` |
| 3 Backend + mock | done | 31 backend + 17 mock tests passing |
| 4 Frontend | done | 11 tests, `tsc` clean, production build OK |
| 5 Integration | done **natively**; Docker files written but **not executed** (see below) | live run of all services + `scripts/smoke.sh` passed |
| 6 Documentation | done | `README.md`, `docs/*` |

## Test results (last run, all executed)
- `ml/tests`: 19 passed
- `mock_zabbix/tests`: 17 passed
- `backend/tests`: 31 passed (real PostgreSQL 16 via pgserver)
- `frontend`: 11 passed; `tsc --noEmit` clean; `vite build` OK
- `scripts/smoke.sh` against the live local stack: passed

## Not verified in the development environment
- **Docker / Compose.** Docker wasn't available in the build environment, so the `Dockerfile`s,
  `docker-compose.yml` and the Docker paths of `scripts/*.sh` were written but **never built or run**. The
  same commands, versions and environment variables were exercised natively (uvicorn, worker, Alembic, Postgres,
  vite preview with the `/api` proxy). The first `./scripts/start.sh` on a Docker machine is the outstanding
  check. Run `./scripts/smoke.sh` afterwards.
- **Browser E2E (Playwright).** Chromium couldn't be installed (missing system libraries, no root). It is
  replaced by component/workflow tests (Vitest + Testing Library) and the HTTP smoke test through the web proxy.

## Deviations from the approved design (with reasons)
1. **LightGBM → HistGradientBoosting.** The owner asked for scikit-learn (or TensorFlow) only.
2. **Incident grouping key is the host**, not (host, category): the model alternates DoS/DDoS per window, so a
   category key would fragment one attack. The dominant category and the distribution are stored instead.
3. **Python 3.11** (not 3.12) in images, matching the environment where everything was tested.
4. **No APScheduler.** A plain asyncio loop in the worker is enough.
5. **Benign rows are never capped in training.** The first run capped them by mistake; it was fixed and retrained.

## Open decisions for the project owner
- **RF vs HGB for deployment.** Deferred by the owner; RF is deployed. HGB has near-equal metrics, higher macro-F1
  and a 3.9 MB artifact instead of 86 MB (compressed). Switching = copy the HGB checkpoint into a bundle
  (`ml/work/checkpoints/hist_gb.joblib`), or retrain and select it.
- **Committing artifacts.** `artifacts/models/…/model.joblib` is 86 MB, too large for plain git (GitHub rejects
  files > 100 MB and warns > 50 MB). Options: Git LFS, a release asset, or switching to HGB.
- **Recharts 2.x** is pinned and works, but upstream marks it deprecated. Upgrade to v3 later.

## Known limitations
See `docs/ml_methodology.md §6`. The main ones: lab-dataset domain shift, no pfSense feature exporter, no
authentication (by requirement), acknowledgements not written back to Zabbix (by requirement), and problem
recoveries older than the 1 h lookback are not applied.
