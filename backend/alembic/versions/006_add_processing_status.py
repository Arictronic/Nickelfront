"""Add processing_status column to papers table.

Revision ID: 006
Revises: 005
Create Date: 2026-03-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить колонку processing_status."""

    # Проверяем, существует ли уже колонка
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('papers')]

    if 'processing_status' not in columns:
        # Добавляем колонку со значением по умолчанию
        op.add_column(
            'papers',
            sa.Column('processing_status', sa.String(length=50), nullable=False, server_default='pending')
        )
        # Создаём индекс для колонки
        op.create_index('ix_papers_processing_status', 'papers', ['processing_status'], unique=False)
    else:
        # Если колонка существует, но имеет NULL значения, обновляем их
        op.execute("UPDATE papers SET processing_status = 'pending' WHERE processing_status IS NULL")


def downgrade() -> None:
    """Удалить колонку processing_status."""
    op.drop_index('ix_papers_processing_status')
    op.drop_column('papers', 'processing_status')
