from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOCK_", env_file=".env", extra="ignore")

    scenario_file: Path = Path("scenarios/defense_demo.yaml")
    replay_pool: Path = Path("../artifacts/replay/replay_pool.parquet")
    api_token: str = "mock-zabbix-token"
    # Scenario starts this many seconds BEFORE service start (0 = starts now).
    start_offset_seconds: int = 0
    max_history_rows: int = 10000   # hard cap per history.get, like Zabbix's search limit
    api_version: str = "7.0.0"
