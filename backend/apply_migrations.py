"""Apply Alembic migrations from the project root or backend directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ALEMBIC_VERSION_MIN_LENGTH = 255
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


def _load_project_env() -> None:
    """Make migrations use the project .env instead of stale shell variables."""
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


def _redact_url(value: str | None) -> str:
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


def _sync_database_url(async_url: str) -> str:
    normalized_url = async_url.strip().strip('"').strip("'")
    return normalized_url.replace("+asyncpg", "+psycopg2")


def _is_ancestor_revision(script, ancestor_revision: str, descendant_revision: str) -> bool:
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


def _ensure_alembic_version_capacity(alembic_cfg) -> None:
    """Ensure Alembic can store long revision IDs used by this project.

    Alembic creates ``alembic_version.version_num`` as VARCHAR(32) by default.
    Nickelfront has descriptive revision IDs such as
    ``012_add_content_part_extraction_metadata`` and
    ``014_include_full_text_in_search_vector``. These are longer than 32
    characters, so a clean PostgreSQL database fails while Alembic tries to
    update its own version table. Widening the column before ``upgrade head``
    makes migrations idempotent for fresh and partially migrated databases.
    """
    from sqlalchemy import create_engine, inspect, text

    from app.core.config import settings

    # Do NOT call alembic.command.ensure_version() here. In this project env.py
    # also prepares the version table, and doing manual DDL inside Alembic's
    # migration connection before context.begin_transaction() can leave the whole
    # upgrade in an implicit transaction that is rolled back on connection close.
    # Use a separate sync engine and commit this preparation before Alembic runs.
    engine = create_engine(_sync_database_url(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            dialect_name = conn.dialect.name

            if dialect_name == "postgresql":
                if not inspector.has_table("alembic_version"):
                    conn.execute(
                        text(
                            "CREATE TABLE IF NOT EXISTS alembic_version "
                            f"(version_num VARCHAR({ALEMBIC_VERSION_MIN_LENGTH}) NOT NULL, "
                            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE alembic_version "
                            f"ALTER COLUMN version_num TYPE VARCHAR({ALEMBIC_VERSION_MIN_LENGTH})"
                        )
                    )
                print(
                    "Alembic version table is ready: "
                    f"version_num VARCHAR({ALEMBIC_VERSION_MIN_LENGTH})."
                )
            else:
                if not inspector.has_table("alembic_version"):
                    conn.execute(
                        text(
                            "CREATE TABLE alembic_version "
                            "(version_num VARCHAR(255) NOT NULL PRIMARY KEY)"
                        )
                    )
                print(
                    "Alembic version table exists; skipping PostgreSQL-only "
                    f"VARCHAR({ALEMBIC_VERSION_MIN_LENGTH}) widening for dialect {dialect_name}."
                )
    finally:
        engine.dispose()


def _prune_overlapping_alembic_versions(alembic_cfg) -> None:
    """Drop stale ancestor revisions from alembic_version.

    The cleanup is intentionally conservative:
    * on a fresh database Alembic may not have created alembic_version yet, so
      cleanup must be skipped and regular ``upgrade head`` should create it;
    * if the table contains unknown revisions, setup must stop with a clear error
      instead of deleting data blindly;
    * only revisions that are proven ancestors of another stored revision are
      removed.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import bindparam, create_engine, inspect, text

    from app.core.config import settings

    script = ScriptDirectory.from_config(alembic_cfg)
    engine = create_engine(_sync_database_url(settings.DATABASE_URL), pool_pre_ping=True)

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

            unknown_versions = [
                version for version, revision in resolved.items() if revision is None
            ]
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
                    if _is_ancestor_revision(script, revision.revision, other_revision.revision):
                        stale_versions.add(version)
                        break

            if not stale_versions:
                return

            delete_stmt = text(
                "DELETE FROM alembic_version WHERE version_num IN :versions"
            ).bindparams(bindparam("versions", expanding=True))
            conn.execute(delete_stmt, {"versions": sorted(stale_versions)})
            print(f"Removed stale Alembic ancestor revisions: {', '.join(sorted(stale_versions))}")
    finally:
        engine.dispose()


def _verify_required_tables() -> None:
    """Verify that the same database now contains core Nickelfront tables."""
    from sqlalchemy import create_engine, inspect, text

    from app.core.config import settings

    engine = create_engine(_sync_database_url(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            missing = [table for table in REQUIRED_TABLES if not inspector.has_table(table)]
            if not inspector.has_table("alembic_version"):
                missing.insert(0, "alembic_version")

            if missing:
                raise RuntimeError(
                    "Migrations finished, but required table(s) are missing in "
                    f"DATABASE_URL={_redact_url(settings.DATABASE_URL)}: "
                    + ", ".join(missing)
                    + ". This usually means migrations were applied to another database/schema "
                    "or .env was not loaded consistently."
                )

            try:
                rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
                versions = ", ".join(str(row[0]) for row in rows if row and row[0])
            except Exception:
                versions = "unknown"
            print(f"Database schema check OK. Alembic version(s): {versions or 'empty'}")
    finally:
        engine.dispose()


def _repair_known_schema_gaps() -> None:
    """Repair tables inserted into the Alembic chain after a local DB reached head."""
    from sqlalchemy import create_engine, inspect, text

    from app.core.config import settings

    engine = create_engine(_sync_database_url(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            if not inspector.has_table("analysis_results"):
                if conn.dialect.name == "postgresql":
                    id_column = "id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
                    json_type = "JSONB"
                    created_at_column = "created_at TIMESTAMP WITH TIME ZONE DEFAULT now()"
                    updated_at_column = "updated_at TIMESTAMP WITH TIME ZONE NULL"
                    completed_at_column = "completed_at TIMESTAMP WITH TIME ZONE NULL"
                else:
                    id_column = "id INTEGER PRIMARY KEY"
                    json_type = "JSON"
                    created_at_column = "created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                    updated_at_column = "updated_at DATETIME NULL"
                    completed_at_column = "completed_at DATETIME NULL"
                conn.execute(
                    text(
                        f"""
                        CREATE TABLE analysis_results (
                            {id_column},
                            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                            user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
                            status VARCHAR(20) NOT NULL DEFAULT 'pending',
                            prompt_version VARCHAR(50) NOT NULL DEFAULT '1.0',
                            context_preview TEXT NULL,
                            raw_response TEXT NULL,
                            structured_result {json_type} NULL,
                            error_message TEXT NULL,
                            {created_at_column},
                            {updated_at_column},
                            {completed_at_column}
                        )
                        """
                    )
                )
                print("Repaired missing table: analysis_results")

            inspector = inspect(conn)
            if inspector.has_table("analysis_results"):
                existing_indexes = {idx["name"] for idx in inspector.get_indexes("analysis_results")}
                indexes = (
                    ("ix_analysis_results_id", ["id"]),
                    ("ix_analysis_results_paper_id", ["paper_id"]),
                    ("ix_analysis_results_user_id", ["user_id"]),
                    ("ix_analysis_results_status", ["status"]),
                    ("ix_analysis_results_paper_user", ["paper_id", "user_id"]),
                )
                for index_name, columns in indexes:
                    if index_name not in existing_indexes:
                        column_list = ", ".join(f'"{column}"' for column in columns)
                        conn.execute(text(f'CREATE INDEX "{index_name}" ON "analysis_results" ({column_list})'))
                        print(f"Repaired missing index: {index_name}")
    finally:
        engine.dispose()


def run_migrations() -> None:
    """Apply all Alembic migrations."""
    _load_project_env()

    from alembic import command
    from alembic.config import Config

    for path in (PROJECT_ROOT, BACKEND_DIR):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    alembic_ini = BACKEND_DIR / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    alembic_cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))

    previous_cwd = Path.cwd()
    try:
        os.chdir(BACKEND_DIR)
        from app.core.config import settings
        print("Applying migrations...")
        print(f"Migration DATABASE_URL: {_redact_url(settings.DATABASE_URL)}")
        _ensure_alembic_version_capacity(alembic_cfg)
        _prune_overlapping_alembic_versions(alembic_cfg)
        command.upgrade(alembic_cfg, "head")
        _repair_known_schema_gaps()
        _verify_required_tables()
        print("Migrations applied successfully!")
    finally:
        os.chdir(previous_cwd)


if __name__ == "__main__":
    run_migrations()
