import json

from conftest import T0


def test_auth_and_errors(rpc, client):
    assert rpc("apiinfo.version", token=None)["result"] == "7.0.0"
    assert rpc("host.get", token="wrong")["error"]["data"] == "Not authorised."
    assert rpc("nope.get")["error"]["code"] == -32601
    assert rpc("history.get", {"history": 9})["error"]["code"] == -32602
    r = client.post("/api_jsonrpc.php", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.json()["error"]["code"] == -32700


def _feature_item(rpc, host):
    hid = rpc("host.get", {"filter": {"host": [host]}})["result"][0]["hostid"]
    return [i for i in rpc("item.get", {"hostids": [hid]})["result"] if i["key_"] == "netad.flow.features"][0]


def test_feature_history_deterministic_and_typed(rpc):
    it = _feature_item(rpc, "lan-a-core")
    assert it["value_type"] == "4"
    p = {"history": 4, "itemids": [it["itemid"]], "time_from": T0 - 120, "time_till": T0, "sortorder": "ASC"}
    a, b = rpc("history.get", p)["result"], rpc("history.get", p)["result"]
    assert a == b and len(a) == 61  # 2-second windows, inclusive bounds
    feats = json.loads(a[0]["value"])
    assert len(feats) == 39 and "Rate" in feats
    assert [int(r["clock"]) for r in a] == sorted(int(r["clock"]) for r in a)
    # numeric history type does not return text items
    assert rpc("history.get", {**p, "history": 3})["result"] == [] or \
        all(r["itemid"] != it["itemid"] for r in rpc("history.get", {**p, "history": 3})["result"])


def test_no_future_values(rpc):
    it = _feature_item(rpc, "pfsense-edge")
    res = rpc("history.get", {"history": 4, "itemids": [it["itemid"]], "time_from": T0 - 10, "time_till": T0 + 600})
    assert max(int(r["clock"]) for r in res["result"]) <= T0


def test_limit_and_desc(rpc):
    it = _feature_item(rpc, "pfsense-edge")
    res = rpc("history.get", {"history": 4, "itemids": [it["itemid"]], "time_from": T0 - 600,
                              "sortorder": "DESC", "limit": 5})["result"]
    clocks = [int(r["clock"]) for r in res]
    assert len(clocks) == 5 and clocks == sorted(clocks, reverse=True) and clocks[0] == T0


def test_scenario_ground_truth_follows_phases(client, app):
    sc = app.state.scenario
    recon = next(p for p in sc.phases if p.name == "recon")
    t0, t1 = sc.start + recon.start, sc.start + recon.start + recon.duration - 1
    lan_a = client.get("/_scenario/truth", params={"host": "lan-a-core", "time_from": t0, "time_till": t1}).json()
    edge = client.get("/_scenario/truth", params={"host": "pfsense-edge", "time_from": t0, "time_till": t1}).json()
    attack_share = sum(w["label"] != "BENIGN" for w in lan_a) / len(lan_a)
    assert 0.7 < attack_share < 0.97
    assert all(w["label"] == "BENIGN" for w in edge)
    assert all(w["phase"] == "recon" for w in lan_a)


def test_ddos_metrics_spike(rpc, app):
    sc = app.state.scenario
    ddos = next(p for p in sc.phases if p.name == "ddos")
    t = sc.start + ddos.start
    p = {"history": 3, "itemids": ["44721"]}
    normal = [int(r["value"]) for r in rpc("history.get", {**p, "time_from": sc.start, "time_till": sc.start + sc.phases[0].duration - 1})["result"]]
    attack = [int(r["value"]) for r in rpc("history.get", {**p, "time_from": t, "time_till": t + ddos.duration - 1})["result"]]
    assert sum(attack) / len(attack) > 4 * sum(normal) / len(normal)


def test_events_problem_and_recovery(rpc, app):
    sc = app.state.scenario
    evs = rpc("event.get", {"time_from": sc.start, "selectHosts": ["host"], "output": "extend"})["result"]
    problems = [e for e in evs if e["value"] == "1"]
    recoveries = {e["eventid"] for e in evs if e["value"] == "0"}
    assert {e["hosts"][0]["host"] for e in problems} == {"lan-a-core", "pfsense-edge"}
    for e in problems:
        assert e["r_eventid"] in recoveries  # whole loop is in the past -> all resolved
    assert rpc("event.get", {"time_from": sc.start, "value": 1})["result"] and \
        all(e["value"] == "1" for e in rpc("event.get", {"time_from": sc.start, "value": 1})["result"])


def test_problem_get_open_only(rpc, app, clock):
    sc = app.state.scenario
    ddos = next(p for p in sc.phases if p.name == "ddos")
    clock.t = sc.start + sc.period + ddos.start + ddos.duration - 2   # second loop, late DDoS
    open_ = rpc("problem.get", {"selectTags": "extend"})["result"]
    assert {p["name"] for p in open_} >= {"pfSense: High rate of blocked connections from single IP"}
    assert all("r_eventid" not in p for p in open_)


def test_outage(client, rpc, clock):
    client.post("/_scenario/outage", params={"seconds": 30})
    r = client.post("/api_jsonrpc.php", json={"jsonrpc": "2.0", "method": "apiinfo.version", "id": 1})
    assert r.status_code == 503
    clock.t += 31
    assert rpc("apiinfo.version", token=None)["result"] == "7.0.0"
