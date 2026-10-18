"""Scenario model and deterministic telemetry generation."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

FEATURE_ITEM_KEY = "netad.flow.features"
FEATURE_ITEM_OFFSET = 1
BENIGN_LABEL = "BENIGN"


@dataclass(frozen=True)
class Host:
    hostid: str
    host: str
    name: str
    ip: str
    item_base: int
    group: str
    criticality: str
    role: str
    os: str
    description: str


@dataclass(frozen=True)
class Item:
    itemid: str
    hostid: str
    key: str
    name: str
    value_type: int      # 0 float, 3 unsigned, 4 text
    units: str
    metric: str | None   # None for the feature item
    base: float = 0.0


@dataclass(frozen=True)
class ProblemDef:
    host: str
    triggerid: str
    name: str
    severity: int
    delay: int
    recovery_delay: int
    tags: dict[str, str]


@dataclass(frozen=True)
class Phase:
    name: str
    start: int           # offset within one loop (seconds)
    duration: int
    attacks: dict[str, dict]
    problems: tuple[ProblemDef, ...]


@dataclass(frozen=True)
class Window:
    clock: int
    ns: int
    host: str
    phase: str
    label: str
    features: dict[str, float]


@dataclass(frozen=True)
class ZEvent:
    eventid: str
    objectid: str
    clock: int
    name: str
    severity: int
    value: int           # 1 problem, 0 recovery
    r_eventid: str
    host: str
    tags: dict[str, str]


def _rng(*parts) -> np.random.Generator:
    digest = hashlib.blake2b(":".join(map(str, parts)).encode(), digest_size=16).digest()
    return np.random.default_rng(int.from_bytes(digest, "little"))


@dataclass
class Scenario:
    seed: int
    window_seconds: int
    metric_interval: int
    backfill: int
    loop: bool
    hosts: list[Host]
    items: list[Item]
    phases: list[Phase]
    pool: dict[str, list[dict[str, float]]]
    start: int                       # unix seconds when phase 0 begins
    period: int = field(init=False)

    def __post_init__(self) -> None:
        self.period = sum(p.duration for p in self.phases)
        self.hosts_by_name = {h.host: h for h in self.hosts}
        self.hosts_by_id = {h.hostid: h for h in self.hosts}
        self.items_by_id = {i.itemid: i for i in self.items}
        missing = {lab for p in self.phases for a in p.attacks.values() for lab in a["labels"]} - set(self.pool)
        if missing or BENIGN_LABEL not in self.pool:
            raise ValueError(f"replay pool lacks labels: {sorted(missing | ({BENIGN_LABEL} - set(self.pool)))}")

    # ------------------------------------------------------------- loading
    @classmethod
    def load(cls, scenario_file: Path, pool_file: Path, start: int) -> "Scenario":
        spec = yaml.safe_load(scenario_file.read_text())
        hosts = [Host(**h) for h in spec["hosts"]]
        items: list[Item] = []
        for h in hosts:
            items.append(Item(str(h.item_base + FEATURE_ITEM_OFFSET), h.hostid, FEATURE_ITEM_KEY,
                              "Flow-window features (JSON)", 4, "", None))
            for mname, m in spec["metrics"].items():
                if "hosts" in m and h.host not in m["hosts"]:
                    continue
                items.append(Item(str(h.item_base + m["offset"]), h.hostid, m["key"], m["name"],
                                  m["value_type"], m["units"], mname, float(m["base"])))
        phases, off = [], 0
        for p in spec["phases"]:
            probs = tuple(ProblemDef(**{"tags": {}, **pr}) for pr in p.get("problems", []))
            phases.append(Phase(p["name"], off, p["duration"], p.get("attacks", {}), probs))
            off += p["duration"]
        df = pd.read_parquet(pool_file)
        feats = [c for c in df.columns if c != "Label"]
        pool = {lab: [{f: float(f"{v:.7g}") for f, v in zip(feats, row)} for row in grp[feats].to_numpy()]
                for lab, grp in df.groupby("Label")}
        return cls(spec["seed"], spec["window_seconds"], spec["metric_interval_seconds"],
                   spec["backfill_seconds"], spec["loop"], hosts, items, phases, pool, start)

    # ------------------------------------------------------------- timeline
    def phase_at(self, t: int) -> tuple[Phase | None, int]:
        """(phase, loop_index). Before start -> (None, -1); after end without loop -> (None, 0)."""
        e = t - self.start
        if e < 0:
            return None, -1
        loop_idx, within = divmod(e, self.period)
        if loop_idx > 0 and not self.loop:
            return None, 0
        for p in self.phases:
            if p.start <= within < p.start + p.duration:
                return p, loop_idx
        return None, loop_idx

    def earliest(self) -> int:
        return self.start - self.backfill

    def _grid(self, step: int, t_from: int, t_till: int) -> range:
        lo = max(t_from, self.earliest())
        first = -(-lo // step) * step
        return range(first, t_till + 1, step)

    # ------------------------------------------------------------- telemetry
    def window(self, host: str, t: int) -> Window:
        phase, _ = self.phase_at(t)
        rng = _rng(self.seed, host, t)
        attack = phase.attacks.get(host) if phase else None
        label = BENIGN_LABEL
        if attack and rng.random() < attack.get("intensity", 1.0):
            label = attack["labels"][int(rng.integers(len(attack["labels"])))]
        rows = self.pool[label]
        feats = rows[int(rng.integers(len(rows)))]
        return Window(t, int(rng.integers(1_000_000_000)), host, phase.name if phase else "backfill", label, feats)

    def windows(self, host: str, t_from: int, t_till: int) -> list[Window]:
        return [self.window(host, t) for t in self._grid(self.window_seconds, t_from, t_till)]

    def metric_value(self, item: Item, t: int) -> float:
        host = self.hosts_by_id[item.hostid].host
        phase, _ = self.phase_at(t)
        mult = 1.0
        if phase and host in phase.attacks:
            mult = float(phase.attacks[host].get("metrics", {}).get(item.metric, 1.0))
        rng = _rng(self.seed, item.itemid, t)
        diurnal = 1.0 + 0.15 * math.sin(2 * math.pi * (t % 86400) / 86400)
        v = item.base * diurnal * mult * float(rng.lognormal(0.0, 0.06))
        if item.metric == "cpu":
            v = min(v, 100.0)
        return round(v, 4) if item.value_type == 0 else float(int(v))

    def metric_series(self, item: Item, t_from: int, t_till: int) -> list[tuple[int, float]]:
        return [(t, self.metric_value(item, t)) for t in self._grid(self.metric_interval, t_from, t_till)]

    # ------------------------------------------------------------- events
    def events(self, t_from: int, t_till: int, now: int) -> list[ZEvent]:
        """Problem + recovery events whose clock is in [t_from, min(t_till, now)]."""
        t_till = min(t_till, now)
        out: list[ZEvent] = []
        if t_till < self.start:
            return out
        first_loop = max(0, (t_from - self.start) // self.period - 1)
        last_loop = (t_till - self.start) // self.period
        if not self.loop:
            last_loop = min(last_loop, 0)
        for li in range(first_loop, last_loop + 1):
            base = self.start + li * self.period
            for pi, ph in enumerate(self.phases):
                for j, pr in enumerate(ph.problems):
                    pid = 900000 + li * 1000 + pi * 20 + j * 2
                    p_clock = base + ph.start + pr.delay
                    r_clock = base + ph.start + ph.duration + pr.recovery_delay
                    recovered = r_clock <= now
                    hostname = pr.host
                    if t_from <= p_clock <= t_till:
                        out.append(ZEvent(str(pid), pr.triggerid, p_clock, pr.name, pr.severity, 1,
                                          str(pid + 1) if recovered else "0", hostname, pr.tags))
                    if recovered and t_from <= r_clock <= t_till:
                        out.append(ZEvent(str(pid + 1), pr.triggerid, r_clock, pr.name, 0, 0, "0", hostname, pr.tags))
        return out

    def open_problems(self, now: int) -> list[ZEvent]:
        lookback = now - 2 * self.period
        return [e for e in self.events(lookback, now, now) if e.value == 1 and e.r_eventid == "0"]


def window_json(w: Window) -> str:
    return json.dumps(w.features, separators=(",", ":"))
