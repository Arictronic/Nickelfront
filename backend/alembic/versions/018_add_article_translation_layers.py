"""Add article translation layers for content parts.

Revision ID: 018_article_translation_layers
Revises: 017_add_paper_language
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "018_article_translation_layers"
down_revision = "017_add_paper_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("available_language_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("papers", sa.Column("translation_status", sa.String(length=50), nullable=True))
    op.add_column("papers", sa.Column("translation_task_id", sa.String(length=100), nullable=True))
    op.add_column("papers", sa.Column("translation_error", sa.Text(), nullable=True))
    op.create_index("ix_papers_translation_status", "papers", ["translation_status"])
    op.create_index("ix_papers_translation_task_id", "papers", ["translation_task_id"])

    op.create_table(
        "paper_content_part_translations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("language_code", sa.String(length=20), nullable=False),
        sa.Column("language_name", sa.String(length=100), nullable=True),
        sa.Column("source_language_code", sa.String(length=20), nullable=True),
        sa.Column("translated_markdown_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("qwen_model", sa.String(length=100), nullable=True),
        sa.Column("qwen_prompt_version", sa.String(length=50), nullable=True),
        sa.Column("source_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("translated_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["part_id"], ["paper_content_parts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("part_id", "language_code", name="uq_part_translation_language"),
    )
    op.create_index("ix_paper_content_part_translations_id", "paper_content_part_translations", ["id"])
    op.create_index("ix_paper_content_part_translations_paper_id", "paper_content_part_translations", ["paper_id"])
    op.create_index("ix_paper_content_part_translations_part_id", "paper_content_part_translations", ["part_id"])
    op.create_index("ix_paper_content_part_translations_language_code", "paper_content_part_translations", ["language_code"])
    op.create_index("ix_paper_content_part_translations_status", "paper_content_part_translations", ["status"])
    op.create_index("ix_part_translations_paper_language", "paper_content_part_translations", ["paper_id", "language_code"])
    op.create_index("ix_part_translations_status", "paper_content_part_translations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_part_translations_status", table_name="paper_content_part_translations")
    op.drop_index("ix_part_translations_paper_language", table_name="paper_content_part_translations")
    op.drop_index("ix_paper_content_part_translations_status", table_name="paper_content_part_translations")
    op.drop_index("ix_paper_content_part_translations_language_code", table_name="paper_content_part_translations")
    op.drop_index("ix_paper_content_part_translations_part_id", table_name="paper_content_part_translations")
    op.drop_index("ix_paper_content_part_translations_paper_id", table_name="paper_content_part_translations")
    op.drop_index("ix_paper_content_part_translations_id", table_name="paper_content_part_translations")
    op.drop_table("paper_content_part_translations")

    op.drop_index("ix_papers_translation_task_id", table_name="papers")
    op.drop_index("ix_papers_translation_status", table_name="papers")
    op.drop_column("papers", "translation_error")
    op.drop_column("papers", "translation_task_id")
    op.drop_column("papers", "translation_status")
    op.drop_column("papers", "available_language_codes")
