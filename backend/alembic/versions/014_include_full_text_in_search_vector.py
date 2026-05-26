"""Include extracted full_text in PostgreSQL FTS vector.

Revision ID: 014_fulltext_search_vector
Revises: 013_add_content_part_types
Create Date: 2026-05-26
"""

from alembic import op


revision = "014_fulltext_search_vector"
down_revision = "013_add_content_part_types"
branch_labels = None
depends_on = None


_KEYWORDS_TEXT_SQL = """
COALESCE((
    SELECT string_agg(elem, ' ')
    FROM jsonb_array_elements_text(
        CASE
            WHEN jsonb_typeof(keywords::jsonb) = 'array' THEN keywords::jsonb
            ELSE '[]'::jsonb
        END
    ) AS elem
), '')
"""

_NEW_KEYWORDS_TEXT_SQL = """
COALESCE((
    SELECT string_agg(elem, ' ')
    FROM jsonb_array_elements_text(
        CASE
            WHEN jsonb_typeof(NEW.keywords::jsonb) = 'array' THEN NEW.keywords::jsonb
            ELSE '[]'::jsonb
        END
    ) AS elem
), '')
"""


def _search_vector_expression(*, use_new: bool, include_full_text: bool) -> str:
    prefix = "NEW." if use_new else ""
    keywords_sql = _NEW_KEYWORDS_TEXT_SQL if use_new else _KEYWORDS_TEXT_SQL
    parts = [
        f"setweight(to_tsvector('english', coalesce({prefix}title, '')), 'A')",
        f"setweight(to_tsvector('english', coalesce({prefix}abstract, '')), 'B')",
        f"setweight(to_tsvector('english', {keywords_sql}), 'C')",
    ]
    if include_full_text:
        parts.append(f"setweight(to_tsvector('english', coalesce({prefix}full_text, '')), 'D')")
    return " ||\n                ".join(parts)


def _create_trigger_function(*, include_full_text: bool) -> None:
    expression = _search_vector_expression(use_new=True, include_full_text=include_full_text)
    op.execute(f"""
        CREATE OR REPLACE FUNCTION papers_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                {expression};
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)


def _rebuild_existing_vectors(*, include_full_text: bool) -> None:
    expression = _search_vector_expression(use_new=False, include_full_text=include_full_text)
    op.execute(f"""
        UPDATE papers
        SET search_vector =
            {expression}
    """)


def upgrade() -> None:
    """Добавить extracted full_text в FTS-индекс и пересобрать существующие строки."""
    _create_trigger_function(include_full_text=True)
    _rebuild_existing_vectors(include_full_text=True)


def downgrade() -> None:
    """Вернуть прежний индекс: title + abstract + keywords без full_text."""
    _create_trigger_function(include_full_text=False)
    _rebuild_existing_vectors(include_full_text=False)
