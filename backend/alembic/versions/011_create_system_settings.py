"""create system settings

Revision ID: 011
Revises: 010
Create Date: 2026-05-23 17:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=80), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("value_type", sa.String(length=30), nullable=False, server_default="json"),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requires_restart", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section", "key", name="uq_system_settings_section_key"),
    )
    op.create_index(op.f("ix_system_settings_id"), "system_settings", ["id"], unique=False)
    op.create_index(op.f("ix_system_settings_section"), "system_settings", ["section"], unique=False)
    op.create_index(op.f("ix_system_settings_key"), "system_settings", ["key"], unique=False)

    op.alter_column("system_settings", "value_type", server_default=None)
    op.alter_column("system_settings", "title", server_default=None)
    op.alter_column("system_settings", "is_public", server_default=None)
    op.alter_column("system_settings", "requires_restart", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_system_settings_key"), table_name="system_settings")
    op.drop_index(op.f("ix_system_settings_section"), table_name="system_settings")
    op.drop_index(op.f("ix_system_settings_id"), table_name="system_settings")
    op.drop_table("system_settings")
