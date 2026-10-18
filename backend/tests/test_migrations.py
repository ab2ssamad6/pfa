from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base


async def test_migration_matches_models(pg_url):
    eng = create_async_engine(pg_url)
    async with eng.connect() as conn:
        diff = await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    await eng.dispose()
    assert diff == [], f"models and migrations diverge: {diff}"


def test_downgrade_and_upgrade_roundtrip(alembic_cfg):
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
