import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
TABLAS_ESPERADAS = {"ciudadanos", "casos", "interacciones", "auditorias"}


def _alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["sqlalchemy.url"] = settings.test_database_url
    return config


async def test_migraciones_crean_tablas_correctamente():
    config = _alembic_config()
    # command.upgrade/downgrade son síncronos y manejan su propio loop async
    # internamente; to_thread evita el conflicto con el loop de pytest-asyncio.
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(settings.test_database_url)
    try:
        async with engine.connect() as conn:
            tablas = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    finally:
        await engine.dispose()

    assert TABLAS_ESPERADAS.issubset(tablas)

    await asyncio.to_thread(command.downgrade, config, "base")
