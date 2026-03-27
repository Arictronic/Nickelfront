"""Add embedding column to papers table."""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "003_add_embedding"
down_revision = "002_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем колонку embedding типа JSON для хранения вектора
    op.add_column("papers", sa.Column("embedding", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Удаляем колонку embedding
    op.drop_column("papers", "embedding")
