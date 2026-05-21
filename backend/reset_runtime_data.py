from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import engine

# Tables that are project structure / identity, not runtime data.
# users is preserved by default so the local admin account keeps working after cleanup.
ALWAYS_PRESERVE_TABLES = {"alembic_version"}
DEFAULT_PRESERVE_TABLES = ALWAYS_PRESERVE_TABLES | {"users"}

# Runtime files/dirs that should be reset to make the project look like a fresh start.
RUNTIME_DIRS_TO_CLEAR = (
    "logs",
    "backend/logs",
    "qwen_service/logs",
    "parser_alpha/logs",
    "rag/logs",
    "data",
    "parser_alpha/data",
    "storage/papers_pdf",
    "archives",
    "chroma_db",
    "backend/chroma_db",
    "rag/data/uploads",
    "rag/data/db",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp_wheels",
)

RUNTIME_FILES_TO_DELETE = (
    "parser_alpha/source_health.json",
    "celerybeat-schedule",
    "celerybeat-schedule.db",
    "celerybeat.pid",
)

REDIS_RUNTIME_PATTERNS = (
    "*.rdb",
    "*.aof",
    "*.tmp",
    "temp-*.rdb",
    "redis*.log",
)


@dataclass
class CleanupStats:
    deleted_dirs: int = 0
    deleted_files: int = 0
    redis_keys_deleted: int = 0
    skipped_locked: int = 0
    db_tables_cleaned: list[str] = field(default_factory=list)
    db_rows_before: dict[str, int] = field(default_factory=dict)
    db_rows_after: dict[str, int] = field(default_factory=dict)
    db_tables_preserved: dict[str, int] = field(default_factory=dict)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _safe_clear_dir_contents(target: Path, stats: CleanupStats, keep_names: set[str] | None = None) -> None:
    if not target.exists() or not target.is_dir():
        return

    keep_names = keep_names or set()
    for child in target.iterdir():
        if child.name in keep_names:
            continue
        if child.is_dir():
            try:
                shutil.rmtree(child, ignore_errors=False)
                stats.deleted_dirs += 1
            except Exception:
                stats.skipped_locked += 1
        elif child.exists():
            try:
                child.unlink(missing_ok=True)
                stats.deleted_files += 1
            except Exception:
                stats.skipped_locked += 1


def _delete_file_if_exists(path: Path, stats: CleanupStats) -> None:
    if path.exists() and path.is_file():
        try:
            path.unlink(missing_ok=True)
            stats.deleted_files += 1
        except Exception:
            stats.skipped_locked += 1


def _delete_dir_if_exists(path: Path, stats: CleanupStats) -> None:
    if path.exists() and path.is_dir():
        try:
            shutil.rmtree(path, ignore_errors=False)
            stats.deleted_dirs += 1
        except Exception:
            stats.skipped_locked += 1


def _clear_python_caches(project_root: Path, stats: CleanupStats) -> None:
    for cache_dir in project_root.rglob("__pycache__"):
        if cache_dir.is_dir():
            _delete_dir_if_exists(cache_dir, stats)
    for pyc_file in project_root.rglob("*.pyc"):
        _delete_file_if_exists(pyc_file, stats)


def _clear_alloy_analysis_results(project_root: Path, stats: CleanupStats) -> None:
    target = project_root / "storage" / "alloy_analysis"
    prompt_path = target / "prompt.txt"
    if not target.exists() or not target.is_dir():
        return

    for child in target.iterdir():
        # Keep editable prompt template, remove only generated artifacts.
        if child == prompt_path:
            continue
        if child.is_dir():
            _delete_dir_if_exists(child, stats)
        else:
            _delete_file_if_exists(child, stats)


def _clear_redis_local_runtime(project_root: Path, stats: CleanupStats) -> None:
    """Remove Redis persistence/runtime files but keep redis-server.exe/redis-cli.exe/configs/DLLs."""
    redis_dir = project_root / "redis"
    if not redis_dir.exists() or not redis_dir.is_dir():
        return

    for pattern in REDIS_RUNTIME_PATTERNS:
        for path in redis_dir.glob(pattern):
            if path.is_dir():
                _delete_dir_if_exists(path, stats)
            else:
                _delete_file_if_exists(path, stats)

    _delete_dir_if_exists(redis_dir / "appendonlydir", stats)


def _clear_runtime_files(project_root: Path, stats: CleanupStats) -> None:
    for rel in RUNTIME_DIRS_TO_CLEAR:
        _safe_clear_dir_contents(project_root / rel, stats, keep_names={".gitkeep"})

    for rel in RUNTIME_FILES_TO_DELETE:
        _delete_file_if_exists(project_root / rel, stats)

    _clear_alloy_analysis_results(project_root, stats)
    _clear_redis_local_runtime(project_root, stats)
    _clear_python_caches(project_root, stats)


def _clear_papers_count_cache() -> None:
    try:
        from app.api.v1.endpoints.parse import _papers_count_cache

        _papers_count_cache.clear()
    except Exception:
        # Cleanup must not fail because of an optional in-memory cache.
        pass


def _flush_redis_runtime(stats: CleanupStats) -> None:
    try:
        import redis
    except Exception:
        print("ПРЕДУПРЕЖДЕНИЕ: Python-пакет `redis` не установлен, очистка Redis DB пропущена.")
        return

    urls = [
        settings.REDIS_URL,
        settings.CELERY_BROKER_URL,
        settings.CELERY_RESULT_BACKEND,
    ]
    seen: set[str] = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            client = redis.Redis.from_url(url)
            count = int(client.dbsize() or 0)
            client.flushdb()
            stats.redis_keys_deleted += count
            print(f"Redis FLUSHDB выполнен: {url} удалено_ключей={count}")
        except Exception as exc:
            print(f"ПРЕДУПРЕЖДЕНИЕ: очистка Redis пропущена для {url}: {exc}")


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_sql(table_name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f'public.{_quote_ident(table_name)}'
    return _quote_ident(table_name)


async def _list_tables(conn, dialect_name: str) -> list[str]:
    if dialect_name == "postgresql":
        result = await conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        )
        return [str(row[0]) for row in result.fetchall()]

    if dialect_name == "sqlite":
        result = await conn.execute(
            text(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        )
        return [str(row[0]) for row in result.fetchall()]

    # Generic fallback for tests/alternate DBs.
    result = await conn.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
    )
    return [str(row[0]) for row in result.fetchall()]


async def _count_table(conn, table_name: str, dialect_name: str) -> int:
    result = await conn.execute(text(f"SELECT COUNT(*) FROM {_table_sql(table_name, dialect_name)}"))
    return int(result.scalar() or 0)


async def _reset_database_runtime(stats: CleanupStats, preserve_tables: set[str]) -> None:
    dialect_name = engine.dialect.name

    async with engine.begin() as conn:
        tables = await _list_tables(conn, dialect_name)
        cleanup_tables = [table for table in tables if table not in preserve_tables]
        preserved_existing = [table for table in tables if table in preserve_tables]

        for table in preserved_existing:
            try:
                stats.db_tables_preserved[table] = await _count_table(conn, table, dialect_name)
            except Exception:
                stats.db_tables_preserved[table] = -1

        for table in cleanup_tables:
            try:
                stats.db_rows_before[table] = await _count_table(conn, table, dialect_name)
            except Exception:
                stats.db_rows_before[table] = -1

        if not cleanup_tables:
            return

        if dialect_name == "postgresql":
            table_list = ", ".join(_table_sql(table, dialect_name) for table in cleanup_tables)
            await conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
        elif dialect_name == "sqlite":
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            for table in cleanup_tables:
                await conn.execute(text(f"DELETE FROM {_table_sql(table, dialect_name)}"))
                await conn.execute(text("DELETE FROM sqlite_sequence WHERE name = :table_name"), {"table_name": table})
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        else:
            for table in cleanup_tables:
                await conn.execute(text(f"DELETE FROM {_table_sql(table, dialect_name)}"))

        stats.db_tables_cleaned = cleanup_tables

        for table in cleanup_tables:
            try:
                stats.db_rows_after[table] = await _count_table(conn, table, dialect_name)
            except Exception:
                stats.db_rows_after[table] = -1


async def reset_runtime_data(include_users: bool = False) -> CleanupStats:
    preserve_tables = set(ALWAYS_PRESERVE_TABLES if include_users else DEFAULT_PRESERVE_TABLES)
    stats = CleanupStats()

    await _reset_database_runtime(stats, preserve_tables=preserve_tables)

    project_root = _project_root()
    _clear_runtime_files(project_root, stats)
    _flush_redis_runtime(stats)
    _clear_papers_count_cache()

    return stats


def _print_stats(stats: CleanupStats, include_users: bool) -> None:
    print("\nОчистка завершена:")
    print("- режим:", "полный сброс БД, включая пользователей" if include_users else "сброс runtime-данных, пользователи сохранены")

    print("\nБаза данных:")
    if stats.db_tables_cleaned:
        print("- очищенные таблицы:")
        for table in stats.db_tables_cleaned:
            before = stats.db_rows_before.get(table, "?")
            after = stats.db_rows_after.get(table, "?")
            print(f"  - {table}: до={before}, после={after}")
    else:
        print("- очищенные таблицы: нет")

    if stats.db_tables_preserved:
        print("- сохранённые таблицы:")
        for table, count in stats.db_tables_preserved.items():
            print(f"  - {table}: строк={count}")

    bad_tables = [table for table, count in stats.db_rows_after.items() if count not in (0, -1)]
    if bad_tables:
        print("\nПРЕДУПРЕЖДЕНИЕ: некоторые очищенные таблицы не пустые после очистки:")
        for table in bad_tables:
            print(f"  - {table}: строк={stats.db_rows_after.get(table)}")
    else:
        print("- проверка: все очищенные таблицы БД пустые")

    print("\nФайлы/Redis:")
    print(f"- удалено папок: {stats.deleted_dirs}")
    print(f"- удалено файлов: {stats.deleted_files}")
    print(f"- удалено ключей Redis: {stats.redis_keys_deleted}")
    print(f"- пропущено занятых файлов/папок: {stats.skipped_locked}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Сброс runtime-состояния Nickelfront почти до первого запуска: runtime-таблицы БД, "
            "статьи, задачи, истории, Chroma/RAG-файлы, PDF, логи, кэши и Redis-очереди."
        )
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Запустить без интерактивного подтверждения.",
    )
    parser.add_argument(
        "--include-users",
        action="store_true",
        help=(
            "Также очистить таблицу users. По умолчанию пользователи сохраняются, "
            "чтобы локальный admin-логин продолжал работать. Таблица миграций Alembic всегда сохраняется."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.yes:
        print("Будут УДАЛЕНЫ runtime-данные:")
        print("1. по умолчанию все таблицы БД, кроме `users` и `alembic_version`")
        print("2. refresh-токены/сессии, истории задач, статьи, patent_tasks, статистика парсеров")
        print("3. Chroma/vector/RAG-хранилища, загруженные RAG-файлы, PDF, результаты анализа")
        print("4. логи, очереди Celery/Redis, runtime-данные парсеров и временные кэши")
        print("\nПользователи по умолчанию сохраняются. Используй --include-users только если точно хочешь удалить и их.")
        confirm = input("Введите YES для продолжения: ").strip()
        if confirm != "YES":
            print("Отменено.")
            return 1

    try:
        stats = asyncio.run(reset_runtime_data(include_users=bool(args.include_users)))
    except SQLAlchemyError as exc:
        print(f"Ошибка очистки БД: {exc}")
        return 2

    _print_stats(stats, include_users=bool(args.include_users))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
