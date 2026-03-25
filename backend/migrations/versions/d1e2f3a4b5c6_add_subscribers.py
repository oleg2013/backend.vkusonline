"""Add subscribers table

Revision ID: d1e2f3a4b5c6
Revises: c6d8e0f2a4b6
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c6d8e0f2a4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscribers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "unsubscribe_token",
            sa.String(64),
            unique=True,
            nullable=False,
            index=True,
        ),
        sa.Column("source", sa.String(50), nullable=False, server_default="footer"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("subscribers")
