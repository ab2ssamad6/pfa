"""Background worker: ingest -> infer -> correlate, every POLL_INTERVAL seconds.

Runs independently of the API and of any frontend request.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core.config import Settings, get_settings
from .core.logging import setup_logging
from .db.models import PipelineRun
from .db.session import make_engine, make_sessionmaker
from .services.inference import ActiveModel, register_model, run_inference
from .services.incidents import IncidentRules, correlate
from .services.ingestion import ingest, sync_inventory
from .services.maintenance import apply_retention, record_health
from .sources.base import SourceError, TelemetrySource
from .sources.zabbix import build_source

log = logging.getLogger("worker")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Worker:
    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession], source: TelemetrySource,
                 clock: Callable[[], datetime] = utcnow):
        self.s, self.sessions, self.source, self.clock = settings, sessions, source, clock
        self.rules = IncidentRules(settings.incident_debounce_k, settings.incident_debounce_n,
                                   _td(settings.incident_gap_seconds), _td(settings.incident_resolve_seconds))
        self.model: ActiveModel | None = None
        self._inventory_at = 0.0
        self._retention_at = 0.0
        self.failures = 0

    async def start(self) -> None:
        async with self.sessions() as s:
            self.model = await register_model(s, self.s.model_dir)

    async def cycle(self) -> PipelineRun:
        assert self.model is not None, "call start() first"
        run = PipelineRun(started_at=self.clock())
        now = self.clock()
        source_ok = True
        try:
            async with self.sessions() as s:
                if time.monotonic() - self._inventory_at > self.s.inventory_refresh_seconds:
                    await sync_inventory(s, self.source)
                    self._inventory_at = time.monotonic()
                st = await ingest(s, self.source, now, self.s.ingest_backfill_seconds, self.s.event_lookback_seconds)
                run.windows_ingested, run.windows_rejected = st.windows, st.rejected
                run.metrics_ingested, run.events_upserted = st.metrics, st.events
            async with self.sessions() as s:
                await record_health(s, self.source.name, True, now)
            self.failures = 0
        except SourceError as e:
            source_ok = False
            self.failures += 1
            run.error = f"source: {e}"
            log.warning("source error (%d in a row): %s", self.failures, e)
            async with self.sessions() as s:
                await record_health(s, self.source.name, False, now, str(e))
        # Inference and correlation run even when the source is down (they drain what is stored).
        async with self.sessions() as s:
            inf = await run_inference(s, self.model, self.s.inference_batch_size)
            run.predictions, run.anomalies = inf.predictions, inf.anomalies
        async with self.sessions() as s:
            cs = await correlate(s, self.rules)
            run.incidents_opened, run.incidents_resolved = cs.opened, cs.resolved
        if self.s.retention_days > 0 and time.monotonic() - self._retention_at > self.s.retention_interval_seconds:
            async with self.sessions() as s:
                log.info("retention: %s", await apply_retention(s, self.clock(), self.s.retention_days))
            self._retention_at = time.monotonic()
        run.finished_at = self.clock()
        async with self.sessions() as s:
            s.add(run)
            await s.commit()
        if run.windows_ingested or run.incidents_opened or not source_ok:
            log.info("cycle: windows=%d preds=%d anomalies=%d opened=%d resolved=%d%s", run.windows_ingested,
                     run.predictions, run.anomalies, run.incidents_opened, run.incidents_resolved,
                     f" error={run.error}" if run.error else "")
        return run

    def next_delay(self) -> float:
        if self.failures == 0:
            return self.s.poll_interval_seconds
        return min(self.s.poll_interval_seconds * 2 ** self.failures, self.s.max_backoff_seconds)


def _td(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=seconds)


async def wait_for_db(sessions: async_sessionmaker[AsyncSession], attempts: int = 30) -> None:
    for i in range(attempts):
        try:
            async with sessions() as s:
                await s.execute(text("SELECT 1 FROM model_versions LIMIT 1"))
            return
        except Exception as e:  # noqa: BLE001 — report and retry any startup failure
            log.warning("database not ready (%d/%d): %s", i + 1, attempts, str(e).splitlines()[0])
            await asyncio.sleep(2)
    raise SystemExit("database unavailable or not migrated — check DATABASE_URL and run `alembic upgrade head`")


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    await wait_for_db(sessions)
    source = build_source(settings)
    worker = Worker(settings, sessions, source)
    await worker.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker started: source=%s poll=%.1fs", settings.zabbix_url, settings.poll_interval_seconds)
    while not stop.is_set():
        try:
            await worker.cycle()
        except Exception:  # noqa: BLE001 — keep the loop alive, but never silently
            log.exception("cycle failed")
            worker.failures += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=worker.next_delay())
        except asyncio.TimeoutError:
            pass
    await source.aclose()
    await engine.dispose()
    log.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
