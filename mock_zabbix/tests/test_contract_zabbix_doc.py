"""Contract tests: the mock answers the documented requests with the documented shapes."""
import json

import pytest

from conftest import ROOT

DOC = ROOT / "ZABBIX_doc"


def _doc(name):
    return json.loads((DOC / f"{name}.get.json").read_text())


def _keys(rows):
    return set().union(*(r.keys() for r in rows))


def _all_strings(obj):
    if isinstance(obj, dict):
        return all(_all_strings(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_all_strings(v) for v in obj)
    return isinstance(obj, str)


@pytest.mark.parametrize("name,req_key,resp_key", [
    ("host", "request_example", "response_example"),
    ("event", "request_example", "response_example"),
    ("problem", "request_example", "response_example"),
    ("trend", "request_example", "response_example"),
    ("history", "request_numeric_example", "response_numeric_example"),
])
def test_documented_request_returns_documented_shape(rpc, app, clock, name, req_key, resp_key):
    d = _doc(name)
    if name == "problem":  # problem.get only returns OPEN problems: query during the DDoS phase
        sc = app.state.scenario
        ddos = next(p for p in sc.phases if p.name == "ddos")
        clock.t = sc.start + sc.period + ddos.start + 90
    req = d[req_key]
    resp = rpc(req["method"], req["params"])
    assert "error" not in resp, resp
    result = resp["result"]
    assert result, f"{name}: empty result for documented request"
    expected = _keys(d[resp_key]["result"])
    assert expected <= _keys(result), f"{name}: missing {expected - _keys(result)}"
    assert _all_strings(result), f"{name}: Zabbix returns every scalar as a string"
    # nested structures keep the documented sub-keys
    for sub in ("hosts", "tags", "interfaces", "hostgroups", "inventory"):
        doc_rows = [r[sub] for r in d[resp_key]["result"] if sub in r]
        if doc_rows:
            ours = [r[sub] for r in result if sub in r]
            assert ours, f"{name}.{sub} missing"
            first_doc = doc_rows[0][0] if isinstance(doc_rows[0], list) and doc_rows[0] else doc_rows[0]
            first_ours = ours[0][0] if isinstance(ours[0], list) and ours[0] else ours[0]
            if isinstance(first_doc, dict):
                assert set(first_doc) <= set(first_ours), f"{name}.{sub}: {set(first_doc) - set(first_ours)}"


def test_documented_item_ids_exist(rpc):
    """The documented firewall-states item (44721) and host (10542) are reproduced."""
    items = rpc("item.get", {"hostids": ["10542"], "search": {"key_": "pfsense"}, "output": "extend"})["result"]
    assert any(i["itemid"] == "44721" for i in items)


def test_count_output(rpc):
    req = _doc("trend")["request_count_only_example"]
    res = rpc(req["method"], req["params"])["result"]
    assert isinstance(res, str) and int(res) > 0


def test_event_by_tag(rpc):
    res = rpc("event.get", {"tags": [{"tag": "scope", "value": "security", "operator": 1}], "selectTags": "extend",
                            "time_from": 0})["result"]
    assert res and all({"tag": "scope", "value": "security"} in e["tags"] for e in res)
