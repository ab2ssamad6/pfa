from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zabbix_mock.config import Settings
from zabbix_mock.jsonrpc import build_app

ROOT = Path(__file__).resolve().parents[2]
T0 = 1_763_218_800  # fixed "now" (matches the time range used in ZABBIX_doc examples)


class Clock:
    def __init__(self, t: int):
        self.t = t

    def __call__(self) -> int:
        return self.t


@pytest.fixture
def clock():
    return Clock(T0)


@pytest.fixture
def settings():
    return Settings(scenario_file=ROOT / "mock_zabbix/scenarios/defense_demo.yaml",
                    replay_pool=ROOT / "artifacts/replay/replay_pool.parquet",
                    api_token="t", start_offset_seconds=0)


@pytest.fixture
def app(settings, clock):
    # Scenario starts 15 minutes before "now" -> one full loop (11 min) is in the past.
    return build_app(settings.model_copy(update={"start_offset_seconds": 900}), now=clock)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def rpc(client):
    def call(method, params=None, token="t"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = client.post("/api_jsonrpc.php", json={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1},
                        headers=headers)
        assert r.status_code == 200, r.text
        return r.json()
    return call
