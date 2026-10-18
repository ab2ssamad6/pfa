"""Zabbix JSON-RPC adapter (Zabbix 6.0/7.0). Works unchanged against the mock and a real server.

Pagination: Zabbix has no cursor. We page by time — sort ASC, `limit`, then
restart from the last clock (inclusive; duplicates are removed by the DB
unique constraint).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone

import httpx

from .base import (
    ExternalEventRecord, FeatureWindowRecord, FetchResult, HostInfo, ItemInfo, MetricRecord, RejectedRecord,
    SourceProtocolError, SourceUnavailable,
)

log = logging.getLogger(__name__)

NUMERIC_TYPES = (0, 3)
MAX_PAGES = 50


def _ts(clock: str | int) -> datetime:
    return datetime.fromtimestamp(int(clock), tz=timezone.utc)


def _clock(dt: datetime) -> int:
    return int(dt.timestamp())


class ZabbixJsonRpcAdapter:
    name = "zabbix"

    def __init__(self, url: str, token: str, *, feature_item_key: str, metric_item_keys: list[str],
                 timeout: float = 10.0, page_size: int = 2000, transport: httpx.AsyncBaseTransport | None = None):
        self.url = url
        self.feature_item_key = feature_item_key
        self.metric_item_keys = set(metric_item_keys)
        self.page_size = page_size
        self._client = httpx.AsyncClient(
            timeout=timeout, transport=transport,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json-rpc"})
        self._id = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call(self, method: str, params: dict | None = None):
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": self._id}
        try:
            r = await self._client.post(self.url, json=body)
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"{method}: {type(e).__name__}: {e}") from e
        if r.status_code >= 500:
            raise SourceUnavailable(f"{method}: HTTP {r.status_code}")
        if r.status_code != 200:
            raise SourceProtocolError(f"{method}: HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError as e:
            raise SourceProtocolError(f"{method}: non-JSON response") from e
        if "error" in data:
            err = data["error"]
            raise SourceProtocolError(f"{method}: {err.get('message')} {err.get('data')}")
        if "result" not in data:
            raise SourceProtocolError(f"{method}: response without result")
        return data["result"]

    # ------------------------------------------------------------ inventory
    async def health(self) -> str:
        return str(await self.call("apiinfo.version"))

    async def list_hosts(self) -> list[HostInfo]:
        rows = await self.call("host.get", {"output": ["hostid", "host", "name", "status"], "selectTags": "extend",
                                            "filter": {"status": "0"}})
        out = []
        for r in rows:
            tags = {t["tag"]: t.get("value", "") for t in r.get("tags", [])}
            out.append(HostInfo(r["hostid"], r["host"], r.get("name") or r["host"],
                                tags.get("criticality", "medium"), tags))
        return out

    async def list_items(self, host_refs: list[str]) -> list[ItemInfo]:
        if not host_refs:
            return []
        rows = await self.call("item.get", {"output": ["itemid", "hostid", "name", "key_", "value_type", "units"],
                                            "hostids": host_refs})
        out = []
        for r in rows:
            if r["key_"] == self.feature_item_key:
                kind = "feature"
            elif r["key_"] in self.metric_item_keys and int(r["value_type"]) in NUMERIC_TYPES:
                kind = "metric"
            else:
                continue
            out.append(ItemInfo(r["itemid"], r["hostid"], r["key_"], r["name"], kind, int(r["value_type"]),
                                r.get("units", "")))
        return out

    # ------------------------------------------------------------ history
    async def _history_pages(self, history: int, item_refs: list[str], since: datetime):
        t_from = _clock(since)
        for _ in range(MAX_PAGES):
            rows = await self.call("history.get", {"output": "extend", "history": history, "itemids": item_refs,
                                                   "time_from": t_from, "sortfield": "clock", "sortorder": "ASC",
                                                   "limit": self.page_size})
            yield rows
            if len(rows) < self.page_size:
                return
            last = int(rows[-1]["clock"])
            t_from = last if last > t_from else t_from + 1
        log.warning("history.get pagination stopped after %d pages (backlog continues next cycle)", MAX_PAGES)

    async def fetch_feature_windows(self, item_refs: list[str], since: datetime) -> FetchResult:
        res = FetchResult(records=[])
        if not item_refs:
            return res
        async for rows in self._history_pages(4, item_refs, since):
            for r in rows:
                ts = _ts(r["clock"])
                try:
                    feats = json.loads(r["value"])
                    if not isinstance(feats, dict) or not feats:
                        raise ValueError("value is not a JSON object")
                    clean = {}
                    for k, v in feats.items():
                        x = float(v)
                        if not math.isfinite(x):
                            raise ValueError(f"non-finite value for {k}")
                        clean[str(k)] = x
                except (ValueError, TypeError) as e:
                    res.rejected.append(RejectedRecord(r.get("itemid", "?"), ts, f"invalid feature payload: {e}"))
                    continue
                res.records.append(FeatureWindowRecord(r["itemid"], ts, int(r.get("ns", 0)), clean))
                res.last_ts = ts if res.last_ts is None or ts > res.last_ts else res.last_ts
        return res

    async def fetch_metrics(self, items: list[ItemInfo], since: datetime) -> FetchResult:
        res = FetchResult(records=[])
        by_type: dict[int, list[str]] = {}
        for it in items:
            by_type.setdefault(it.value_type, []).append(it.source_ref)
        for vt, refs in by_type.items():
            async for rows in self._history_pages(vt, refs, since):
                for r in rows:
                    ts = _ts(r["clock"])
                    try:
                        v = float(r["value"])
                        if not math.isfinite(v):
                            raise ValueError("non-finite")
                    except (ValueError, TypeError) as e:
                        res.rejected.append(RejectedRecord(r["itemid"], ts, f"invalid metric value: {e}"))
                        continue
                    res.records.append(MetricRecord(r["itemid"], ts, v))
                    res.last_ts = ts if res.last_ts is None or ts > res.last_ts else res.last_ts
        return res

    # ------------------------------------------------------------ events
    async def fetch_events(self, since: datetime) -> list[ExternalEventRecord]:
        rows = await self.call("event.get", {"output": "extend", "source": 0, "object": 0,
                                             "time_from": _clock(since), "selectHosts": ["hostid"],
                                             "selectTags": "extend", "sortfield": ["clock", "eventid"],
                                             "sortorder": "ASC"})
        recovery = {r["eventid"]: _ts(r["clock"]) for r in rows if r.get("value") == "0"}
        out = []
        for r in rows:
            if r.get("value", "1") != "1":
                continue
            hosts = r.get("hosts") or []
            r_id = r.get("r_eventid", "0")
            out.append(ExternalEventRecord(
                source_ref=r["eventid"], host_ref=hosts[0]["hostid"] if hosts else None, name=r["name"],
                severity=int(r.get("severity", 0)), clock=_ts(r["clock"]),
                recovered_at=recovery.get(r_id) if r_id != "0" else None,
                tags={t["tag"]: t.get("value", "") for t in r.get("tags", [])}))
        return out


def build_source(settings) -> ZabbixJsonRpcAdapter:
    return ZabbixJsonRpcAdapter(settings.zabbix_url, settings.zabbix_token,
                                feature_item_key=settings.zabbix_feature_item_key,
                                metric_item_keys=settings.zabbix_metric_item_keys,
                                timeout=settings.zabbix_timeout_seconds, page_size=settings.ingest_page_size)
