"""Backend test fixtures.

* A real PostgreSQL server (pgserver: bundled binaries) is started once per session and migrated with
  Alembic — tests exercise the same schema as production, not SQLite.
* The mock Zabbix server runs in-process behind httpx.ASGITransport with a frozen clock.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("LANG", "C.UTF-8")
os.environ.setdefault("LC_ALL", "C.UTF-8")

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db.session import make_sessionmaker
from app.sources.zabbix import ZabbixJsonRpcAdapter

ROOT = Path(__file__).resolve().parents[2]
T0 = 1_763_218_800
MODELS = ROOT / "artifacts" / "models"


@pytest.fixture(scope="session")
def pg_url():
    import pgserver
    srv = pgserver.get_server(tempfile.mkdtemp(prefix="netad-pg-"), cleanup_mode="stop")
    srv.psql("CREATE DATABASE netad_test;")
    host = srv.get_uri().split("host=")[1]
    url = f"postgresql+asyncpg://postgres@/netad_test?host={host}"
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    cfg.attributes.update(url=url, skip_logging=True)
    command.upgrade(cfg, "head")
    yield url


@pytest.fixture(scope="session")
def alembic_cfg(pg_url):
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    cfg.attributes.update(url=pg_url, skip_logging=True)
    return cfg


@pytest.fixture
async def engine(pg_url):
    eng = create_async_engine(pg_url)
    async with eng.begin() as c:
        tables = (await c.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"))).scalars().all()
        await c.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


@pytest.fixture
def sessions(engine):
    return make_sessionmaker(engine)


class Clock:
    def __init__(self, t: int):
        self.t = t

    def __call__(self) -> int:
        return self.t

    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.t, tz=timezone.utc)


@pytest.fixture
def clock():
    return Clock(T0)


@pytest.fixture
def mock_app(clock):
    from zabbix_mock.config import Settings as MockSettings
    from zabbix_mock.jsonrpc import build_app
    ms = MockSettings(scenario_file=ROOT / "mock_zabbix/scenarios/defense_demo.yaml",
                      replay_pool=ROOT / "artifacts/replay/replay_pool.parquet", api_token="t",
                      start_offset_seconds=900)
    return build_app(ms, now=clock)


@pytest.fixture
def settings(pg_url):
    return Settings(database_url=pg_url, zabbix_url="http://mock/api_jsonrpc.php", zabbix_token="t",
                    model_dir=MODELS, retention_days=0, demo_truth_url="")


@pytest.fixture
async def source(mock_app, settings):
    src = ZabbixJsonRpcAdapter(settings.zabbix_url, settings.zabbix_token,
                               feature_item_key=settings.zabbix_feature_item_key,
                               metric_item_keys=settings.zabbix_metric_item_keys,
                               transport=httpx.ASGITransport(app=mock_app))
    yield src
    await src.aclose()
