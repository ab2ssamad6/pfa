"""Application configuration — all environment-specific values come from env vars."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=("settings_",))

    database_url: str = "postgresql+asyncpg://netad:netad@localhost:5432/netad"

    # Telemetry source (mock or real Zabbix — same adapter)
    zabbix_url: str = "http://localhost:8081/api_jsonrpc.php"
    zabbix_token: str = "mock-zabbix-token"
    zabbix_timeout_seconds: float = 10.0
    zabbix_feature_item_key: str = "netad.flow.features"
    zabbix_metric_item_keys: list[str] = Field(default_factory=lambda: [
        "net.if.in[igb0]", "net.if.out[igb0]", "system.cpu.util", "pfsense.state.table.current"])

    # Worker
    poll_interval_seconds: float = 2.0
    ingest_backfill_seconds: int = 3600
    ingest_page_size: int = 2000
    event_lookback_seconds: int = 3600
    inventory_refresh_seconds: int = 60
    inference_batch_size: int = 2000
    max_backoff_seconds: float = 30.0

    # Model
    model_dir: Path = Path("../artifacts/models")  # a bundle dir, or a parent holding bundle dirs

    # Incidents
    incident_debounce_k: int = 3
    incident_debounce_n: int = 5
    incident_gap_seconds: int = 60
    incident_resolve_seconds: int = 120

    # Retention
    retention_days: int = 7
    retention_interval_seconds: int = 3600

    # Demo only: ground-truth endpoint of the mock (empty = feature disabled)
    demo_truth_url: str = ""

    # API
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
