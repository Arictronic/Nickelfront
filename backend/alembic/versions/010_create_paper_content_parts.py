"""create paper content parts

Revision ID: 010
Revises: 009
Create Date: 2026-05-23 05:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_content_parts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("part_index", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("markdown_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="raw_extracted"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="pdf"),
        sa.Column("qwen_model", sa.String(length=100), nullable=True),
        sa.Column("qwen_prompt_version", sa.String(length=50), nullable=True),
        sa.Column("regeneration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_text_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("markdown_text_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paper_id", "part_index", name="uq_paper_content_parts_paper_part_index"),
    )
    op.create_index(op.f("ix_paper_content_parts_id"), "paper_content_parts", ["id"], unique=False)
    op.create_index(op.f("ix_paper_content_parts_paper_id"), "paper_content_parts", ["paper_id"], unique=False)
    op.create_index(op.f("ix_paper_content_parts_status"), "paper_content_parts", ["status"], unique=False)
    op.create_index("ix_paper_content_parts_paper_pages", "paper_content_parts", ["paper_id", "page_start", "page_end"], unique=False)


    op.alter_column("paper_content_parts", "status", server_default=None)
    op.alter_column("paper_content_parts", "source", server_default=None)
    op.alter_column("paper_content_parts", "regeneration_count", server_default=None)
    op.alter_column("paper_content_parts", "raw_text_chars", server_default=None)
    op.alter_column("paper_content_parts", "markdown_text_chars", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_paper_content_parts_paper_pages", table_name="paper_content_parts")
    op.drop_index(op.f("ix_paper_content_parts_status"), table_name="paper_content_parts")
    op.drop_index(op.f("ix_paper_content_parts_paper_id"), table_name="paper_content_parts")
    op.drop_index(op.f("ix_paper_content_parts_id"), table_name="paper_content_parts")
    op.drop_table("paper_content_parts")
