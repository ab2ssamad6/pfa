"""Source-adapter contract: the Zabbix adapter against the mock server, plus failure modes."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.sources.base import SourceProtocolError, SourceUnavailable
from app.sources.zabbix import ZabbixJsonRpcAdapter
from conftest import T0

SINCE = datetime.fromtimestamp(T0 - 600, tz=timezone.utc)


async def test_inventory(source):
    hosts = await source.list_hosts()
    assert {h.name for h in hosts} == {"pfsense-edge", "lan-a-core", "lan-b-core"}
    assert {h.name: h.criticality for h in hosts}["pfsense-edge"] == "critical"
    items = await source.list_items([h.source_ref for h in hosts])
    feats = [i for i in items if i.kind == "feature"]
    assert len(feats) == 3 and all(i.value_type == 4 for i in feats)
    assert any(i.source_ref == "44721" and i.kind == "metric" for i in items)


async def test_feature_windows_normalised_and_paginated(source, mock_app):
    item = next(i for i in await source.list_items(["10543"]) if i.kind == "feature")
    full = await source.fetch_feature_windows([item.source_ref], SINCE)
    assert len(full.records) == 301 and not full.rejected
    w = full.records[0]
    assert w.ts.tzinfo is not None and isinstance(w.features["Rate"], float) and len(w.features) == 39
    assert full.last_ts == datetime.fromtimestamp(T0, tz=timezone.utc)
    small = ZabbixJsonRpcAdapter("http://mock/api_jsonrpc.php", "t", feature_item_key="netad.flow.features",
                                 metric_item_keys=[], page_size=37, transport=httpx.ASGITransport(app=mock_app))
    paged = await small.fetch_feature_windows([item.source_ref], SINCE)
    await small.aclose()
    assert {(r.ts, r.ns) for r in paged.records} == {(r.ts, r.ns) for r in full.records}


async def test_metrics_and_events(source):
    items = [i for i in await source.list_items(["10542"]) if i.kind == "metric"]
    res = await source.fetch_metrics(items, SINCE)
    assert {r.item_ref for r in res.records} == {i.source_ref for i in items}
    evs = await source.fetch_events(datetime.fromtimestamp(T0 - 3600, tz=timezone.utc))
    assert evs and all(e.host_ref for e in evs)
    assert any(e.recovered_at is not None and e.recovered_at > e.clock for e in evs)


async def test_auth_error_is_protocol_error(mock_app):
    bad = ZabbixJsonRpcAdapter("http://mock/api_jsonrpc.php", "wrong", feature_item_key="x", metric_item_keys=[],
                               transport=httpx.ASGITransport(app=mock_app))
    with pytest.raises(SourceProtocolError, match="Not authorised"):
        await bad.list_hosts()
    await bad.aclose()


async def test_outage_and_connection_errors(source, mock_app):
    from fastapi.testclient import TestClient
    TestClient(mock_app).post("/_scenario/outage", params={"seconds": 60})
    with pytest.raises(SourceUnavailable, match="503"):
        await source.list_hosts()

    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)
    down = ZabbixJsonRpcAdapter("http://nowhere/api_jsonrpc.php", "t", feature_item_key="x", metric_item_keys=[],
                                transport=httpx.MockTransport(refuse))
    with pytest.raises(SourceUnavailable, match="ConnectError"):
        await down.health()
    await down.aclose()


async def test_invalid_payloads_are_rejected_not_dropped():
    def handler(request):
        rows = [{"itemid": "1", "clock": str(T0), "ns": "0", "value": "not json"},
                {"itemid": "1", "clock": str(T0 + 2), "ns": "0", "value": json.dumps({"Rate": "Infinity"})},
                {"itemid": "1", "clock": str(T0 + 4), "ns": "0", "value": json.dumps({"Rate": 1.5})}]
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": rows, "id": 1})
    src = ZabbixJsonRpcAdapter("http://x/api_jsonrpc.php", "t", feature_item_key="x", metric_item_keys=[],
                               transport=httpx.MockTransport(handler))
    res = await src.fetch_feature_windows(["1"], SINCE)
    await src.aclose()
    assert len(res.records) == 1 and len(res.rejected) == 2
    assert all("invalid feature payload" in r.reason for r in res.rejected)
