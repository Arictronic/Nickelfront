"""Скрипт для применения миграций Alembic."""


def run_migrations():
    """Применить все миграции."""
    from alembic.config import Config
    from alembic import command
    
    alembic_cfg = Config("alembic.ini")
    
    print("Применение миграций...")
    command.upgrade(alembic_cfg, "head")
    print("Миграции успешно применены!")


if __name__ == "__main__":
    run_migrations()
