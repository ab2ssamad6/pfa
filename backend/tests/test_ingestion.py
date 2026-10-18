from datetime import timedelta

from sqlalchemy import func, select

from app.db.models import ExternalEvent, FeatureWindow, Host, IngestWatermark, Item, MetricSample
from app.services.ingestion import ingest, sync_inventory


async def _count(s, model):
    return await s.scalar(select(func.count()).select_from(model))


async def test_ingest_is_idempotent_and_watermarked(sessions, source, clock):
    async with sessions() as s:
        await sync_inventory(s, source)
        assert await _count(s, Host) == 3 and await _count(s, Item) == 13
        st1 = await ingest(s, source, clock.dt(), backfill_seconds=600, event_lookback_seconds=3600)
        assert st1.windows == 3 * 301 and st1.rejected == 0 and st1.metrics > 0 and st1.events > 0
        st2 = await ingest(s, source, clock.dt(), backfill_seconds=600, event_lookback_seconds=3600)
        assert st2.windows == 0 and st2.metrics == 0       # nothing new, nothing duplicated
        assert await _count(s, FeatureWindow) == 903
        wm = await s.scalar(select(func.max(IngestWatermark.last_ts)))
        assert wm == clock.dt()
    clock.t += 10
    async with sessions() as s:
        st3 = await ingest(s, source, clock.dt(), backfill_seconds=600, event_lookback_seconds=3600)
        assert st3.windows == 3 * 5                         # only the 5 new windows per host
        events = await _count(s, ExternalEvent)
        assert events == len({e.source_ref for e in (await s.scalars(select(ExternalEvent))).all()})


async def test_host_deactivated_when_missing(sessions, source):
    async with sessions() as s:
        await sync_inventory(s, source)
        s.add(Host(source_ref="999", name="ghost", display_name="Ghost", criticality="low", tags={}))
        await s.commit()
        await sync_inventory(s, source)
        ghost = await s.scalar(select(Host).where(Host.source_ref == "999"))
        assert ghost.active is False
