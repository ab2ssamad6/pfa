"""ORM models. Every timestamp is timezone-aware UTC (timestamptz)."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ItemKind(str, enum.Enum):
    feature = "feature"
    metric = "metric"


class IncidentStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


TS = DateTime(timezone=True)


class Host(Base):
    __tablename__ = "hosts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_ref: Mapped[str] = mapped_column(String(64), unique=True)   # Zabbix hostid
    name: Mapped[str] = mapped_column(String(255))                      # technical name ("host")
    display_name: Mapped[str] = mapped_column(String(255))
    criticality: Mapped[str] = mapped_column(String(32), default="medium")
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())
    items: Mapped[list["Item"]] = relationship(back_populates="host")


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), index=True)
    source_ref: Mapped[str] = mapped_column(String(64), unique=True)   # Zabbix itemid
    key: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[ItemKind] = mapped_column(_enum(ItemKind, "item_kind"))
    value_type: Mapped[int] = mapped_column(Integer)
    units: Mapped[str] = mapped_column(String(32), default="")
    host: Mapped[Host] = relationship(back_populates="items")


class IngestWatermark(Base):
    __tablename__ = "ingest_watermarks"
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    last_ts: Mapped[datetime] = mapped_column(TS)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class MetricSample(Base):
    """Numeric Zabbix items — displayed on the dashboard, not used by the model."""
    __tablename__ = "metric_samples"
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class FeatureWindow(Base):
    """One normalised flow-feature vector (the model input) for a host at a point in time."""
    __tablename__ = "feature_windows"
    __table_args__ = (
        UniqueConstraint("item_id", "ts", "ns", name="uq_feature_windows_item_ts_ns"),
        Index("ix_feature_windows_host_ts", "host_id", "ts"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TS)
    ns: Mapped[int] = mapped_column(BigInteger, default=0)
    features: Mapped[dict] = mapped_column(JSONB)
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # set when inference rejects it
    ingested_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(128), unique=True)
    algorithm: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    threshold: Mapped[float] = mapped_column(Float)
    features: Mapped[list] = mapped_column(JSONB)
    categories: Mapped[list] = mapped_column(JSONB)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    loaded_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)


class Prediction(Base):
    """Model output for every window. Anomaly = prediction with is_anomaly (score >= threshold)."""
    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_predictions_host_ts", "host_id", "ts"),
        Index("ix_predictions_uncorrelated", "ts", postgresql_where="NOT correlated"),
        Index("ix_predictions_anomalies", "host_id", "ts", postgresql_where="is_anomaly"),
    )
    window_id: Mapped[int] = mapped_column(ForeignKey("feature_windows.id", ondelete="CASCADE"), primary_key=True)
    # host_id/ts are copied from the window so timelines need no join (small, immutable values)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TS)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    p_attack: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(32))
    category_proba: Mapped[dict] = mapped_column(JSONB)
    is_anomaly: Mapped[bool] = mapped_column(Boolean)
    correlated: Mapped[bool] = mapped_column(Boolean, default=False)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True,
                                                    index=True)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_host_status", "host_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"))
    status: Mapped[IncidentStatus] = mapped_column(_enum(IncidentStatus, "incident_status"), default=IncidentStatus.open)
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "incident_severity"))
    category: Mapped[str] = mapped_column(String(32))          # dominant suspected category
    category_counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    opened_at: Mapped[datetime] = mapped_column(TS, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(TS)
    resolved_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)   # auto | manual
    acknowledged_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    sum_score: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())
    host: Mapped[Host] = relationship()


class ExternalEvent(Base):
    """Zabbix-originated problem events. Linked to incidents, never merged with them."""
    __tablename__ = "external_events"
    __table_args__ = (Index("ix_external_events_host_clock", "host_id", "clock"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_ref: Mapped[str] = mapped_column(String(64), unique=True)   # Zabbix eventid
    host_id: Mapped[int | None] = mapped_column(ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(Text)
    severity: Mapped[int] = mapped_column(Integer)
    clock: Mapped[datetime] = mapped_column(TS)
    recovered_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class IncidentExternalLink(Base):
    __tablename__ = "incident_external_links"
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True)
    external_event_id: Mapped[int] = mapped_column(ForeignKey("external_events.id", ondelete="CASCADE"),
                                                   primary_key=True)


class SourceHealth(Base):
    __tablename__ = "source_health"
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))      # up | degraded | down
    last_ok_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class PipelineRun(Base):
    """One worker cycle — execution metadata for observability and latency."""
    __tablename__ = "pipeline_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(TS, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(TS, nullable=True)
    windows_ingested: Mapped[int] = mapped_column(Integer, default=0)
    windows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    metrics_ingested: Mapped[int] = mapped_column(Integer, default=0)
    events_upserted: Mapped[int] = mapped_column(Integer, default=0)
    predictions: Mapped[int] = mapped_column(Integer, default=0)
    anomalies: Mapped[int] = mapped_column(Integer, default=0)
    incidents_opened: Mapped[int] = mapped_column(Integer, default=0)
    incidents_resolved: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
