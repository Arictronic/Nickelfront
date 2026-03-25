"""Initial migration - create papers table."""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаём таблицу papers
    op.create_table(
        "papers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=True),
        sa.Column("publication_date", sa.DateTime(), nullable=True),
        sa.Column("journal", sa.String(length=500), nullable=True),
        sa.Column("doi", sa.String(length=200), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doi"),
    )

    # Индексы
    op.create_index(op.f("ix_papers_id"), "papers", ["id"], unique=False)
    op.create_index(op.f("ix_papers_title"), "papers", ["title"], unique=False)
    op.create_index(
        op.f("ix_papers_publication_date"),
        "papers",
        ["publication_date"],
        unique=False,
    )
    op.create_index(op.f("ix_papers_doi"), "papers", ["doi"], unique=False)
    op.create_index(op.f("ix_papers_source"), "papers", ["source"], unique=False)
    op.create_index(
        op.f("ix_papers_source_id"), "papers", ["source_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_papers_source_id"), table_name="papers")
    op.drop_index(op.f("ix_papers_source"), table_name="papers")
    op.drop_index(op.f("ix_papers_doi"), table_name="papers")
    op.drop_index(op.f("ix_papers_publication_date"), table_name="papers")
    op.drop_index(op.f("ix_papers_title"), table_name="papers")
    op.drop_index(op.f("ix_papers_id"), table_name="papers")
    op.drop_table("papers")
