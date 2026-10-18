"""Ingestion: source -> normalised records -> PostgreSQL (idempotent, watermark-driven)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ExternalEvent, FeatureWindow, Host, IngestWatermark, Item, ItemKind, MetricSample
from ..sources.base import ItemInfo, TelemetrySource

log = logging.getLogger(__name__)
CHUNK = 1000


@dataclass
class IngestStats:
    windows: int = 0
    rejected: int = 0
    metrics: int = 0
    events: int = 0


async def sync_inventory(session: AsyncSession, source: TelemetrySource) -> None:
    hosts = await source.list_hosts()
    for h in hosts:
        await session.execute(insert(Host).values(
            source_ref=h.source_ref, name=h.name, display_name=h.display_name, criticality=h.criticality,
            tags=h.tags, active=True,
        ).on_conflict_do_update(index_elements=[Host.source_ref], set_={
            "name": h.name, "display_name": h.display_name, "criticality": h.criticality, "tags": h.tags,
            "active": True}))
    seen = {h.source_ref for h in hosts}
    for host in (await session.scalars(select(Host))).all():
        if host.source_ref not in seen:
            host.active = False
    host_ids = dict((await session.execute(select(Host.source_ref, Host.id))).all())
    for it in await source.list_items(list(seen)):
        if it.host_ref not in host_ids:
            continue
        await session.execute(insert(Item).values(
            host_id=host_ids[it.host_ref], source_ref=it.source_ref, key=it.key, name=it.name,
            kind=ItemKind(it.kind), value_type=it.value_type, units=it.units,
        ).on_conflict_do_update(index_elements=[Item.source_ref], set_={
            "name": it.name, "key": it.key, "kind": ItemKind(it.kind), "value_type": it.value_type,
            "units": it.units}))
    await session.commit()


async def _watermarks(session: AsyncSession, items: list[Item], default: datetime) -> dict[int, datetime]:
    rows = dict((await session.execute(select(IngestWatermark.item_id, IngestWatermark.last_ts)
                                       .where(IngestWatermark.item_id.in_([i.id for i in items])))).all())
    return {i.id: rows.get(i.id, default) for i in items}


async def _set_watermark(session: AsyncSession, item_id: int, ts: datetime) -> None:
    await session.execute(insert(IngestWatermark).values(item_id=item_id, last_ts=ts).on_conflict_do_update(
        index_elements=[IngestWatermark.item_id], set_={"last_ts": ts}))


async def ingest(session: AsyncSession, source: TelemetrySource, now: datetime, backfill_seconds: int,
                 event_lookback_seconds: int) -> IngestStats:
    stats = IngestStats()
    default_since = now - timedelta(seconds=backfill_seconds)
    items = (await session.scalars(select(Item).join(Host).where(Host.active))).all()
    feature_items = [i for i in items if i.kind == ItemKind.feature]
    metric_items = [i for i in items if i.kind == ItemKind.metric]
    by_ref = {i.source_ref: i for i in items}

    # ---- feature windows (one call per item keeps watermarks exact)
    wms = await _watermarks(session, feature_items, default_since)
    for it in feature_items:
        res = await source.fetch_feature_windows([it.source_ref], wms[it.id])
        for r in res.rejected:
            log.warning("rejected window item=%s ts=%s: %s", r.item_ref, r.ts, r.reason)
        stats.rejected += len(res.rejected)
        rows = [{"host_id": it.host_id, "item_id": it.id, "ts": w.ts, "ns": w.ns, "features": w.features}
                for w in res.records]
        for i in range(0, len(rows), CHUNK):
            out = await session.execute(insert(FeatureWindow).values(rows[i:i + CHUNK])
                                        .on_conflict_do_nothing(constraint="uq_feature_windows_item_ts_ns")
                                        .returning(FeatureWindow.id))
            stats.windows += len(out.all())
        if res.last_ts:
            await _set_watermark(session, it.id, res.last_ts)
        await session.commit()

    # ---- numeric metrics (batched by value type inside the adapter)
    if metric_items:
        wms = await _watermarks(session, metric_items, default_since)
        since = min(wms.values())
        infos = [ItemInfo(i.source_ref, "", i.key, i.name, "metric", i.value_type, i.units) for i in metric_items]
        res = await source.fetch_metrics(infos, since)
        stats.rejected += len(res.rejected)
        rows = [{"item_id": by_ref[m.item_ref].id, "ts": m.ts, "value": m.value} for m in res.records
                if m.item_ref in by_ref and m.ts >= wms[by_ref[m.item_ref].id]]
        for i in range(0, len(rows), CHUNK):
            out = await session.execute(insert(MetricSample).values(rows[i:i + CHUNK]).on_conflict_do_nothing()
                                        .returning(MetricSample.item_id))
            stats.metrics += len(out.all())
        newest: dict[int, datetime] = {}
        for m in res.records:
            iid = by_ref[m.item_ref].id
            newest[iid] = max(newest.get(iid, m.ts), m.ts)
        for iid, ts in newest.items():
            await _set_watermark(session, iid, ts)
        await session.commit()

    # ---- Zabbix problem events (re-read a lookback window: recoveries update earlier rows)
    host_ids = dict((await session.execute(select(Host.source_ref, Host.id))).all())
    for e in await source.fetch_events(now - timedelta(seconds=event_lookback_seconds)):
        await session.execute(insert(ExternalEvent).values(
            source_ref=e.source_ref, host_id=host_ids.get(e.host_ref), name=e.name, severity=e.severity,
            clock=e.clock, recovered_at=e.recovered_at, tags=e.tags,
        ).on_conflict_do_update(index_elements=[ExternalEvent.source_ref], set_={
            "recovered_at": e.recovered_at, "name": e.name, "severity": e.severity, "tags": e.tags}))
        stats.events += 1
    await session.commit()
    return stats
