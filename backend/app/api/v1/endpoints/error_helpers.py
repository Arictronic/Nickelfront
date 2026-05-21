"""Shared API error helpers for endpoint-level diagnostics."""

_SCHEMA_HINT_COLUMNS = (
    "parse_confidence",
    "provenance",
    "quality_flags",
    "schema_version",
)


def format_paper_db_error(exc: Exception) -> str:
    """Return a user-actionable DB error, especially for missed Alembic migrations."""
    raw = str(exc)
    lower = raw.lower()
    if any(column in lower for column in _SCHEMA_HINT_COLUMNS) and (
        "does not exist" in lower
        or "undefinedcolumn" in lower
        or "column" in lower
    ):
        return (
            "Похоже, база данных не обновлена после патча: в таблице papers нет новых "
            "колонок parser metadata. Запусти из корня проекта: run_migrations.bat "
            "или python backend\\apply_migrations.py, затем перезапусти backend."
        )
    return raw
