"""API response/request contracts."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SourceHealthOut(ORM):
    source: str
    state: str
    last_ok_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    updated_at: datetime | None


class ModelSummary(BaseModel):
    version: str
    algorithm: str
    threshold: float
    loaded_at: datetime | None


class LastCycle(ORM):
    started_at: datetime
    finished_at: datetime | None
    windows_ingested: int
    predictions: int
    anomalies: int
    error: str | None


class HealthOut(BaseModel):
    status: str                      # ok | degraded | down
    database: bool
    source: SourceHealthOut | None
    model: ModelSummary | None
    worker_last_cycle: datetime | None
    worker_stale: bool


class HostOut(ORM):
    id: int
    source_ref: str
    name: str
    display_name: str
    criticality: str
    tags: dict
    active: bool


class HostStatus(HostOut):
    last_window_at: datetime | None = None
    last_p_attack: float | None = None
    active_incidents: int = 0
    anomalies_last_15m: int = 0


class ScorePoint(BaseModel):
    ts: datetime
    p_attack: float
    is_anomaly: bool
    category: str | None = None


class MetricPoint(BaseModel):
    ts: datetime
    value: float


class MetricSeries(BaseModel):
    item_id: int
    key: str
    name: str
    units: str
    points: list[MetricPoint]


class AnomalyOut(BaseModel):
    window_id: int
    host_id: int
    host_name: str
    ts: datetime
    p_attack: float
    category: str
    category_proba: dict[str, float]
    incident_id: int | None


class IncidentOut(ORM):
    id: int
    host_id: int
    host_name: str = ""
    status: str
    severity: str
    category: str
    category_counts: dict
    opened_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    resolution: str | None
    acknowledged_at: datetime | None
    anomaly_count: int
    max_score: float
    mean_score: float = 0.0
    note: str | None
    linked_events: int = 0


class ExternalEventOut(ORM):
    id: int
    source_ref: str
    host_id: int | None
    host_name: str | None = None
    name: str
    severity: int
    clock: datetime
    recovered_at: datetime | None
    tags: dict


class IncidentDetail(IncidentOut):
    anomalies: list[AnomalyOut]
    events: list[ExternalEventOut]
    timeline: list[ScorePoint]


class Page(BaseModel):
    total: int
    items: list


class IncidentPage(Page):
    items: list[IncidentOut]


class AnomalyPage(Page):
    items: list[AnomalyOut]


class IncidentAction(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class Overview(BaseModel):
    hosts: int
    incidents_open: int
    incidents_acknowledged: int
    incidents_resolved_24h: int
    windows_last_15m: int
    anomalies_last_15m: int
    latest_window_at: datetime | None
    pipeline_lag_seconds: float | None
    health: HealthOut


class ModelOut(BaseModel):
    version: str
    algorithm: str
    threshold: float
    threshold_rule: str | None
    features: list[str]
    categories: list[str]
    loaded_at: datetime | None
    training: dict
    validation: dict
    test: dict
    calibration: str | None


class LiveAccuracy(BaseModel):
    window_minutes: int
    evaluated: int
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float | None
    recall: float | None
    fpr: float | None
    note: str
