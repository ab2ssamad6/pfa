"""Zabbix-compatible JSON-RPC 2.0 endpoint (subset used by the platform).

Mirrors the structures documented in tests/fixtures/zabbix_doc/: every value is a string,
timestamps are unix seconds ('clock') + nanoseconds ('ns').
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .scenario import FEATURE_ITEM_KEY, Scenario, ZEvent, window_json

log = logging.getLogger("mock_zabbix")


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: str):
        self.code, self.message, self.data = code, message, data


def invalid(data: str) -> RpcError:
    return RpcError(-32602, "Invalid params.", data)


# ------------------------------------------------------------------ helpers
def _ids(params: dict, key: str) -> set[str] | None:
    v = params.get(key)
    if v is None:
        return None
    return {str(x) for x in (v if isinstance(v, list) else [v])}


def _int(params: dict, key: str, default: int | None = None) -> int | None:
    v = params.get(key, default)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise invalid(f'Invalid parameter "/{key}": an integer is expected.') from None


def _select(row: dict, output: Any) -> dict:
    if output in (None, "extend"):
        return row
    if isinstance(output, list):
        return {k: v for k, v in row.items() if k in output}
    raise invalid('Invalid parameter "/output".')


def _sort_limit(rows: list[dict], params: dict, default_field: str) -> list[dict]:
    fields = params.get("sortfield", default_field)
    fields = fields if isinstance(fields, list) else [fields]
    desc = str(params.get("sortorder", "ASC")).upper() == "DESC"
    def key(r):
        return tuple(int(r[f]) if str(r.get(f, "")).lstrip("-").isdigit() else r.get(f, "") for f in fields)
    rows = sorted(rows, key=key, reverse=desc)
    limit = _int(params, "limit")
    return rows[:limit] if limit else rows


def _tags(d: dict[str, str]) -> list[dict]:
    return [{"tag": k, "value": v} for k, v in d.items()]


def _tag_match(tags: dict[str, str], filters: list[dict] | None) -> bool:
    for f in filters or []:
        val, op = tags.get(f["tag"]), int(f.get("operator", 0))
        if op == 1 and val != f.get("value"):     # equals
            return False
        if op == 0 and (val is None or f.get("value", "") not in val):  # contains
            return False
    return True


# ------------------------------------------------------------------ methods
class Methods:
    def __init__(self, sc: Scenario, settings: Settings, now: Callable[[], int]):
        self.sc, self.settings, self.now = sc, settings, now

    def apiinfo_version(self, p: dict) -> str:
        return self.settings.api_version

    def host_get(self, p: dict) -> list[dict]:
        ids, filt = _ids(p, "hostids"), p.get("filter") or {}
        out = []
        for h in self.sc.hosts:
            if ids is not None and h.hostid not in ids:
                continue
            if "host" in filt and h.host not in (filt["host"] if isinstance(filt["host"], list) else [filt["host"]]):
                continue
            if "ip" in filt and h.ip not in (filt["ip"] if isinstance(filt["ip"], list) else [filt["ip"]]):
                continue
            row: dict[str, Any] = {"hostid": h.hostid, "host": h.host, "name": h.name, "status": "0",
                                   "description": h.description}
            row = _select(row, p.get("output"))
            if "selectInterfaces" in p:
                row["interfaces"] = [{"interfaceid": str(int(h.hostid) * 10 + 1), "ip": h.ip, "dns": "",
                                      "port": "10050", "type": "1", "main": "1"}]
            groups = [{"groupid": "22" if "Firewall" in h.group else "23", "name": h.group}]
            if "selectHostGroups" in p:
                row["hostgroups"] = groups
            if "selectGroups" in p:          # Zabbix 6.0 spelling
                row["groups"] = groups
            if "selectTags" in p:
                row["tags"] = _tags({"criticality": h.criticality, "role": h.role})
            if "selectParentTemplates" in p:
                tpl = [{"templateid": "10500", "name": "pfSense by SNMP"}] if h.role == "perimeter-firewall" \
                    else [{"templateid": "10001", "name": "Linux by Zabbix agent"}]
                row["parentTemplates"] = tpl + [{"templateid": "10100", "name": "Zabbix agent"}]
            if "selectInventory" in p:
                row["inventory"] = {"type": h.role, "location": "Lab", "os": h.os, "hardware": "", "contact": "",
                                    "notes": ""}
            out.append(row)
        return out

    def item_get(self, p: dict) -> list[dict]:
        hids, iids = _ids(p, "hostids"), _ids(p, "itemids")
        search = (p.get("search") or {}).get("key_")
        now = self.now()
        out = []
        for it in self.sc.items:
            if hids is not None and it.hostid not in hids:
                continue
            if iids is not None and it.itemid not in iids:
                continue
            if search and search not in it.key:
                continue
            last = self._last_value(it, now)
            out.append(_select({"itemid": it.itemid, "hostid": it.hostid, "name": it.name, "key_": it.key,
                                "value_type": str(it.value_type), "units": it.units, "lastvalue": last,
                                "delay": f"{self.sc.window_seconds if it.metric is None else self.sc.metric_interval}s"},
                               p.get("output")))
        return _sort_limit(out, p, "name") if "sortfield" in p else out

    def _last_value(self, it, now: int) -> str:
        if it.metric is None:
            ws = self.sc.windows(self.sc.hosts_by_id[it.hostid].host, now - self.sc.window_seconds, now)
            return window_json(ws[-1]) if ws else ""
        s = self.sc.metric_series(it, now - self.sc.metric_interval, now)
        return self._fmt(it, s[-1][1]) if s else "0"

    @staticmethod
    def _fmt(it, v: float) -> str:
        return f"{v:.4f}" if it.value_type == 0 else str(int(v))

    def history_get(self, p: dict) -> list[dict]:
        htype = _int(p, "history", 3)
        if htype not in (0, 1, 2, 3, 4):
            raise invalid('Invalid parameter "/history": value must be one of 0, 1, 2, 3, 4.')
        now = self.now()
        t_from = _int(p, "time_from", self.sc.earliest())
        t_till = min(_int(p, "time_till", now), now)
        iids = _ids(p, "itemids")
        hids = _ids(p, "hostids")
        rows: list[dict] = []
        for it in self.sc.items:
            if it.value_type != htype:
                continue
            if iids is not None and it.itemid not in iids:
                continue
            if hids is not None and it.hostid not in hids:
                continue
            if it.metric is None:
                host = self.sc.hosts_by_id[it.hostid].host
                for w in self.sc.windows(host, t_from, t_till):
                    rows.append({"itemid": it.itemid, "clock": str(w.clock), "value": window_json(w), "ns": str(w.ns)})
            else:
                for t, v in self.sc.metric_series(it, t_from, t_till):
                    rows.append({"itemid": it.itemid, "clock": str(t), "value": self._fmt(it, v), "ns": "0"})
            if len(rows) > self.settings.max_history_rows * 4:
                break
        rows = _sort_limit(rows, p, "clock")
        rows = rows[: self.settings.max_history_rows]
        return [_select(r, p.get("output")) for r in rows]

    def trend_get(self, p: dict) -> list[dict] | str:
        now = self.now()
        t_from = _int(p, "time_from", self.sc.earliest())
        t_till = min(_int(p, "time_till", now), now)
        iids = _ids(p, "itemids")
        rows = []
        for it in self.sc.items:
            if it.metric is None or (iids is not None and it.itemid not in iids):
                continue
            hour = (max(t_from, self.sc.earliest()) // 3600) * 3600
            while hour <= t_till:
                vals = [v for _, v in self.sc.metric_series(it, hour, min(hour + 3599, now))]
                if vals:
                    rows.append({"itemid": it.itemid, "clock": str(hour), "num": str(len(vals)),
                                 "value_min": self._fmt(it, min(vals)),
                                 "value_avg": self._fmt(it, sum(vals) / len(vals)),
                                 "value_max": self._fmt(it, max(vals))})
                hour += 3600
        if p.get("countOutput"):
            return str(len(rows))
        rows = _sort_limit(rows, p, "clock")
        return [_select(r, p.get("output")) for r in rows]

    def _event_row(self, e: ZEvent, p: dict, with_hosts: bool) -> dict:
        h = self.sc.hosts_by_name[e.host]
        row = {"eventid": e.eventid, "source": "0", "object": "0", "objectid": e.objectid, "clock": str(e.clock),
               "ns": "0", "value": str(e.value), "name": e.name, "severity": str(e.severity),
               "acknowledged": "0", "r_eventid": e.r_eventid, "suppressed": "0"}
        row = _select(row, p.get("output"))
        if with_hosts and "selectHosts" in p:
            row["hosts"] = [_select({"hostid": h.hostid, "host": h.host, "name": h.name},
                                    p["selectHosts"] if isinstance(p["selectHosts"], list) else "extend")]
        if "selectTags" in p:
            row["tags"] = _tags(e.tags)
        if "selectAcknowledges" in p:
            row["acknowledges"] = []
        if "selectSuppressionData" in p:
            row["suppression_data"] = []
        return row

    def _filter_events(self, evs: list[ZEvent], p: dict) -> list[ZEvent]:
        hids, eids = _ids(p, "hostids"), _ids(p, "eventids")
        sev = {int(s) for s in p["severities"]} if p.get("severities") else None
        value = _ids(p, "value")
        out = []
        for e in evs:
            if hids is not None and self.sc.hosts_by_name[e.host].hostid not in hids:
                continue
            if eids is not None and e.eventid not in eids:
                continue
            if sev is not None and e.value == 1 and e.severity not in sev:
                continue
            if value is not None and str(e.value) not in value:
                continue
            if not _tag_match(e.tags, p.get("tags")):
                continue
            out.append(e)
        return out

    def event_get(self, p: dict) -> list[dict]:
        now = self.now()
        t_from = _int(p, "time_from", self.sc.earliest())
        t_till = _int(p, "time_till", now)
        evs = self._filter_events(self.sc.events(t_from, t_till, now), p)
        rows = [self._event_row(e, p, True) for e in evs]
        return _sort_limit(rows, p, "clock")

    def problem_get(self, p: dict) -> list[dict]:
        evs = self._filter_events(self.sc.open_problems(self.now()), p)
        rows = [self._event_row(e, {**p, "output": p.get("output") or "extend"}, False) for e in evs]
        for r in rows:  # problem.get has no value/r_eventid/source fields beyond what is selected
            for k in ("value", "r_eventid", "source", "object", "ns"):
                if p.get("output") in (None, "extend"):
                    r.pop(k, None)
        return _sort_limit(rows, p, "eventid")


METHODS_NO_AUTH = {"apiinfo.version"}


def build_app(settings: Settings | None = None, now: Callable[[], int] | None = None) -> FastAPI:
    settings = settings or Settings()
    clock = now or (lambda: int(time.time()))
    state: dict[str, Any] = {"outage_until": 0}
    sc = Scenario.load(settings.scenario_file, settings.replay_pool, clock() - settings.start_offset_seconds)
    methods = Methods(sc, settings, clock)
    app = FastAPI(title="Mock Zabbix API", version=settings.api_version)
    app.state.scenario, app.state.methods = sc, methods

    @app.post("/api_jsonrpc.php")
    async def rpc(request: Request):
        if clock() < state["outage_until"]:
            return JSONResponse({"detail": "simulated outage"}, status_code=503)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error.",
                                                             "data": "Invalid JSON."}, "id": None})
        rid = body.get("id") if isinstance(body, dict) else None
        try:
            if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or "method" not in body:
                raise RpcError(-32600, "Invalid request.", "Invalid JSON-RPC request.")
            method = body["method"]
            if method not in METHODS_NO_AUTH:
                auth = request.headers.get("authorization", "")
                if auth != f"Bearer {settings.api_token}":
                    raise RpcError(-32602, "Invalid params.", "Not authorised.")
            fn = getattr(methods, method.replace(".", "_"), None)
            if fn is None or method.startswith("_"):
                raise RpcError(-32601, "Method not found.", f'Incorrect API "{method.split(".")[0]}".')
            params = body.get("params") or {}
            if not isinstance(params, dict):
                raise invalid("Params must be an object.")
            return {"jsonrpc": "2.0", "result": fn(params), "id": rid}
        except RpcError as e:
            return {"jsonrpc": "2.0", "error": {"code": e.code, "message": e.message, "data": e.data}, "id": rid}

    # ---------------- demo-only control plane (NOT part of the Zabbix API)
    @app.get("/_scenario/status")
    def status():
        t = clock()
        ph, li = sc.phase_at(t)
        return {"now": t, "start": sc.start, "period": sc.period, "loop_index": li,
                "phase": ph.name if ph else None, "outage": t < state["outage_until"],
                "phases": [{"name": p.name, "start": p.start, "duration": p.duration,
                            "attacked_hosts": list(p.attacks)} for p in sc.phases]}

    @app.get("/_scenario/truth")
    def truth(host: str, time_from: int, time_till: int):
        """Ground-truth labels of replayed windows — for evaluating the demo, never for detection."""
        if host not in sc.hosts_by_name:
            return JSONResponse({"detail": f"unknown host {host}"}, status_code=404)
        if time_till - time_from > 6 * 3600:
            return JSONResponse({"detail": "range too large (max 6h)"}, status_code=400)
        return [{"clock": w.clock, "ns": w.ns, "phase": w.phase, "label": w.label}
                for w in sc.windows(host, time_from, min(time_till, clock()))]

    @app.post("/_scenario/restart")
    def restart():
        sc.start = clock()
        return {"start": sc.start}

    @app.post("/_scenario/outage")
    def outage(seconds: int = 30):
        state["outage_until"] = clock() + max(0, min(seconds, 3600))
        return {"outage_until": state["outage_until"]}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
