"""Apply Alembic migrations from the project root or backend directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent


def _sync_database_url(async_url: str) -> str:
    return async_url.replace("+asyncpg", "+psycopg2")


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


def _prune_overlapping_alembic_versions(alembic_cfg) -> None:
    """Drop stale ancestor revisions from alembic_version.

    This heals local databases where both an ancestor revision and its
    descendant were left in alembic_version after an interrupted upgrade.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text

    from app.core.config import settings

    script = ScriptDirectory.from_config(alembic_cfg)
    engine = create_engine(_sync_database_url(settings.DATABASE_URL))

    with engine.begin() as conn:
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

        stale_versions: set[str] = set()
        for version, revision in resolved.items():
            if revision is None:
                continue
            for other_version, other_revision in resolved.items():
                if version == other_version or other_revision is None:
                    continue
                if _is_ancestor_revision(script, revision.revision, other_revision.revision):
                    stale_versions.add(version)
                    break

        if not stale_versions:
            return

        conn.execute(
            text("DELETE FROM alembic_version WHERE version_num = ANY(:versions)"),
            {"versions": sorted(stale_versions)},
        )
        print(f"Removed stale Alembic ancestor revisions: {', '.join(sorted(stale_versions))}")


def run_migrations() -> None:
    """Apply all Alembic migrations."""
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
        print("Applying migrations...")
        _prune_overlapping_alembic_versions(alembic_cfg)
        command.upgrade(alembic_cfg, "head")
        print("Migrations applied successfully!")
    finally:
        os.chdir(previous_cwd)


if __name__ == "__main__":
    run_migrations()
