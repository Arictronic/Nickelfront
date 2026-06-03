from __future__ import annotations

import os
import sys
from pathlib import Path

from db_migration_support import (
    load_project_env,
    normalize_legacy_revision_ids,
    prune_overlapping_alembic_versions,
    redact_url,
    verify_required_tables,
)

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent


def _prepare_paths() -> None:
    for path in (PROJECT_ROOT, BACKEND_DIR):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)


def _build_alembic_config():
    from alembic.config import Config

    alembic_ini = BACKEND_DIR / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    alembic_cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    return alembic_cfg


def run_migrations() -> None:
    load_project_env(PROJECT_ROOT)
    _prepare_paths()

    from alembic import command
    from app.core.config import settings

    alembic_cfg = _build_alembic_config()
    previous_cwd = Path.cwd()
    try:
        os.chdir(BACKEND_DIR)
        print("Applying migrations...")
        print(f"Migration DATABASE_URL: {redact_url(settings.DATABASE_URL)}")
        normalize_legacy_revision_ids()
        prune_overlapping_alembic_versions(alembic_cfg)
        command.upgrade(alembic_cfg, "head")
        verify_required_tables()
        print("Migrations applied successfully!")
    finally:
        os.chdir(previous_cwd)


if __name__ == "__main__":
    run_migrations()
