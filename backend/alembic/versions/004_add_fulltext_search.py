"""add fulltext search indexes

Revision ID: 004
Revises: 003_add_embedding
Create Date: 2026-03-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003_add_embedding'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить колонки и индексы для полнотекстового поиска."""

    # Включаем расширение для trigram индексов
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Добавляем колонку tsvector для полнотекстового поиска
    op.add_column('papers', sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True))

    # Заполняем существующие записи
    op.execute("""
        UPDATE papers SET search_vector =
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(abstract, '')), 'B') ||
            setweight(to_tsvector('english', coalesce((SELECT string_agg(elem, ' ') FROM jsonb_array_elements_text(keywords::jsonb) AS elem), '')), 'C')
    """)

    # Добавляем индекс GIN для полнотекстового поиска
    op.create_index(
        'ix_papers_search_vector',
        'papers',
        ['search_vector'],
        unique=False,
        postgresql_using='gin'
    )

    # Добавляем индекс для ранжирования по релевантности
    op.create_index(
        'ix_papers_title_trgm',
        'papers',
        ['title'],
        unique=False,
        postgresql_using='gin',
        postgresql_ops={'title': 'gin_trgm_ops'}
    )

    # Добавляем триггер для автоматического обновления search_vector
    op.execute("""
        CREATE OR REPLACE FUNCTION papers_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.abstract, '')), 'B') ||
                setweight(to_tsvector('english', coalesce((SELECT string_agg(elem, ' ') FROM jsonb_array_elements_text(NEW.keywords::jsonb) AS elem), '')), 'C');
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER papers_search_vector_trigger
        BEFORE INSERT OR UPDATE ON papers
        FOR EACH ROW
        EXECUTE FUNCTION papers_search_vector_update();
    """)


def downgrade() -> None:
    """Удалить колонки и индексы для полнотекстового поиска."""

    # Удаляем триггер
    op.execute("DROP TRIGGER IF EXISTS papers_search_vector_trigger ON papers")
    op.execute("DROP FUNCTION IF EXISTS papers_search_vector_update()")

    # Удаляем индексы
    op.drop_index('ix_papers_search_vector')
    op.drop_index('ix_papers_title_trgm')

    # Удаляем колонку
    op.drop_column('papers', 'search_vector')
