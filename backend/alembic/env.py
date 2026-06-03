"""Alembic migrations environment."""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import inspect, pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
ALEMBIC_VERSION_MIN_LENGTH = 255


def _load_project_env() -> None:
    if os.getenv("NICKELFRONT_DISABLE_ENV_OVERRIDE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(env_file, override=True)


_load_project_env()

for _path in (PROJECT_ROOT, BACKEND_DIR):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from app.db.base import Base
import app.db.models
from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def _ensure_version_table_capacity(connection: Connection) -> None:
    """Make Alembic's version table compatible with long project revision IDs.

    Alembic defaults to VARCHAR(32). Several Nickelfront revisions use readable
    IDs longer than 32 characters, so direct Alembic runs and apply_migrations.py
    must widen this column before version updates happen.
    """
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        if connection.dialect.name == "postgresql":
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version "
                    f"(version_num VARCHAR({ALEMBIC_VERSION_MIN_LENGTH}) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
        return

    if connection.dialect.name == "postgresql":
        connection.execute(
            text(
                "ALTER TABLE alembic_version "
                f"ALTER COLUMN version_num TYPE VARCHAR({ALEMBIC_VERSION_MIN_LENGTH})"
            )
        )


def run_migrations_offline() -> None:
    """Запуск миграций в оффлайн режиме."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:





    _ensure_version_table_capacity(connection)
    try:
        connection.commit()
    except Exception:


        pass

    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Запуск миграций в асинхронном режиме."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Запуск миграций в онлайн режиме."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
