from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

REQUIRED_TABLES = (
    "papers",
    "users",
    "refresh_tokens",
    "patent_tasks",
    "paper_content_parts",
    "paper_content_part_translations",
    "analysis_results",
    "system_settings",
)
LEGACY_REVISION_ALIASES = {
    "012_add_content_part_extraction_metadata": "012_content_extract_meta",
}


def load_project_env(project_root: Path) -> None:
    if os.getenv("NICKELFRONT_DISABLE_ENV_OVERRIDE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    env_file = project_root / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(env_file, override=True)


def redact_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip().strip('"').strip("'"))
        netloc = parts.netloc
        if "@" in netloc:
            credentials, host = netloc.rsplit("@", 1)
            username = credentials.split(":", 1)[0] if credentials else "***"
            netloc = f"{username}:***@{host}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "***"


def sync_database_url(async_url: str) -> str:
    return async_url.strip().strip('"').strip("'").replace("+asyncpg", "+psycopg2")


def is_ancestor_revision(script, ancestor_revision: str, descendant_revision: str) -> bool:
    current = script.get_revision(descendant_revision)
    seen: set[str] = set()
    while current is not None and current.revision not in seen:
        seen.add(current.revision)
        raw_down_revisions = current.down_revision
        if raw_down_revisions is None:
            down_revisions: list[str] = []
        elif isinstance(raw_down_revisions, tuple):
            down_revisions = [rev for rev in raw_down_revisions if rev]
        else:
            down_revisions = [raw_down_revisions]
        if ancestor_revision in down_revisions:
            return True
        next_revision_id = down_revisions[0] if len(down_revisions) == 1 else None
        current = script.get_revision(next_revision_id) if next_revision_id else None
    return False


def create_sync_engine():
    from sqlalchemy import create_engine

    from app.core.config import settings

    return create_engine(sync_database_url(settings.DATABASE_URL), pool_pre_ping=True)


def normalize_legacy_revision_ids() -> None:
    from sqlalchemy import inspect, text

    engine = create_sync_engine()
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            if not inspector.has_table("alembic_version"):
                return
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            versions = {row[0] for row in rows if row and row[0]}
            for legacy_revision, current_revision in LEGACY_REVISION_ALIASES.items():
                if legacy_revision in versions and current_revision not in versions:
                    conn.execute(
                        text("UPDATE alembic_version SET version_num = :current WHERE version_num = :legacy"),
                        {"current": current_revision, "legacy": legacy_revision},
                    )
                    print(f"Normalized Alembic revision: {legacy_revision} -> {current_revision}")
    finally:
        engine.dispose()


def prune_overlapping_alembic_versions(alembic_cfg) -> None:
    from alembic.script import ScriptDirectory
    from sqlalchemy import bindparam, inspect, text

    script = ScriptDirectory.from_config(alembic_cfg)
    engine = create_sync_engine()
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            if not inspector.has_table("alembic_version"):
                print("Alembic version table not found; fresh database, skipping revision cleanup.")
                return
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            versions = [row[0] for row in rows if row and row[0]]
            if len(versions) < 2:
                return
            resolved = {}
            for version in versions:
                try:
                    resolved[version] = script.get_revision(version)
                except Exception:
                    resolved[version] = None
            unknown_versions = [version for version, revision in resolved.items() if revision is None]
            if unknown_versions:
                raise RuntimeError(
                    "Unknown Alembic revision(s) in alembic_version: "
                    + ", ".join(sorted(unknown_versions))
                    + ". Refusing automatic cleanup."
                )
            stale_versions: set[str] = set()
            for version, revision in resolved.items():
                for other_version, other_revision in resolved.items():
                    if version == other_version:
                        continue
                    if is_ancestor_revision(script, revision.revision, other_revision.revision):
                        stale_versions.add(version)
                        break
            if not stale_versions:
                return
            delete_stmt = text("DELETE FROM alembic_version WHERE version_num IN :versions").bindparams(bindparam("versions", expanding=True))
            conn.execute(delete_stmt, {"versions": sorted(stale_versions)})
            print(f"Removed stale Alembic ancestor revisions: {', '.join(sorted(stale_versions))}")
    finally:
        engine.dispose()


def verify_required_tables() -> None:
    from sqlalchemy import inspect, text

    from app.core.config import settings

    engine = create_sync_engine()
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            missing = [table for table in REQUIRED_TABLES if not inspector.has_table(table)]
            if not inspector.has_table("alembic_version"):
                missing.insert(0, "alembic_version")
            if missing:
                raise RuntimeError(
                    "Migrations finished, but required table(s) are missing in "
                    f"DATABASE_URL={redact_url(settings.DATABASE_URL)}: "
                    + ", ".join(missing)
                    + ". This usually means migrations were applied to another database/schema or .env was not loaded consistently."
                )
            try:
                rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
                versions = ", ".join(str(row[0]) for row in rows if row and row[0])
            except Exception:
                versions = "unknown"
            print(f"Database schema check OK. Alembic version(s): {versions or 'empty'}")
    finally:
        engine.dispose()
