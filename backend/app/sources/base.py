"""Source-agnostic telemetry contract.

Everything downstream of the adapter (ingestion, ML, incidents, API) only sees
these normalised types — never raw Zabbix structures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol


class SourceError(Exception):
    """Base class for telemetry-source failures."""


class SourceUnavailable(SourceError):
    """Transport-level failure: connection refused, timeout, HTTP 5xx."""


class SourceProtocolError(SourceError):
    """The source answered, but with an error or an unexpected structure."""


@dataclass(frozen=True)
class HostInfo:
    source_ref: str
    name: str
    display_name: str
    criticality: str
    tags: dict[str, str]


@dataclass(frozen=True)
class ItemInfo:
    source_ref: str
    host_ref: str
    key: str
    name: str
    kind: Literal["feature", "metric"]
    value_type: int
    units: str


@dataclass(frozen=True)
class FeatureWindowRecord:
    item_ref: str
    ts: datetime
    ns: int
    features: dict[str, float]


@dataclass(frozen=True)
class MetricRecord:
    item_ref: str
    ts: datetime
    value: float


@dataclass(frozen=True)
class RejectedRecord:
    item_ref: str
    ts: datetime | None
    reason: str


@dataclass(frozen=True)
class ExternalEventRecord:
    source_ref: str
    host_ref: str | None
    name: str
    severity: int
    clock: datetime
    recovered_at: datetime | None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class FetchResult:
    records: list
    rejected: list[RejectedRecord] = field(default_factory=list)
    last_ts: datetime | None = None   # newest timestamp seen (for the watermark)


class TelemetrySource(Protocol):
    name: str

    async def health(self) -> str: ...
    async def list_hosts(self) -> list[HostInfo]: ...
    async def list_items(self, host_refs: list[str]) -> list[ItemInfo]: ...
    async def fetch_feature_windows(self, item_refs: list[str], since: datetime) -> FetchResult: ...
    async def fetch_metrics(self, items: list[ItemInfo], since: datetime) -> FetchResult: ...
    async def fetch_events(self, since: datetime) -> list[ExternalEventRecord]: ...
    async def aclose(self) -> None: ...
