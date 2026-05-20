"""Скрипт для применения миграций Alembic из корня проекта или из backend/."""

from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent


def run_migrations() -> None:
    """Применить все миграции."""
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
        print("Применение миграций...")
        command.upgrade(alembic_cfg, "head")
        print("Миграции успешно применены!")
    finally:
        os.chdir(previous_cwd)


if __name__ == "__main__":
    run_migrations()
