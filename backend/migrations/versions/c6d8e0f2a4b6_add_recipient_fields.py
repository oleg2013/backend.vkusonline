"""add recipient_name and recipient_phone to orders

Revision ID: c6d8e0f2a4b6
Revises: b5c7d9e1f3a2
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa

revision = "c6d8e0f2a4b6"
down_revision = "b5c7d9e1f3a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("recipient_name", sa.String(255), nullable=True))
    op.add_column("orders", sa.Column("recipient_phone", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "recipient_phone")
    op.drop_column("orders", "recipient_name")
