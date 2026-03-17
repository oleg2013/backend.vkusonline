"""flow3: order_type, status migration, plain_password

Revision ID: b5c7d9e1f3a2
Revises: a3f8b2c1d4e5
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa
from packages.core.security import generate_public_order_token

revision = "b5c7d9e1f3a2"
down_revision = "a3f8b2c1d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add order_type to orders
    op.add_column("orders", sa.Column("order_type", sa.String(10), nullable=False, server_default="prepaid"))
    op.create_index("ix_orders_order_type", "orders", ["order_type"])

    # 2. Backfill order_type based on payment_method
    op.execute("UPDATE orders SET order_type = 'codflow' WHERE payment_method = 'cod'")

    # 3. Map old statuses to new ones
    op.execute("UPDATE orders SET status = 'confirmed' WHERE status = 'processing'")
    op.execute("UPDATE orders SET status = 'shipped' WHERE status = 'in_transit'")

    # 4. Backfill guest_order_token for orders that don't have one
    # Use md5 + random() to generate unique tokens (no pgcrypto needed)
    op.execute("""
        UPDATE orders
        SET guest_order_token = md5(random()::text || id || now()::text)
        WHERE guest_order_token IS NULL
    """)

    # 5. Add plain_password to users
    op.add_column("users", sa.Column("plain_password", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "plain_password")
    op.drop_index("ix_orders_order_type", table_name="orders")
    op.drop_column("orders", "order_type")
    # Note: status migration is not reversible (processing/in_transit data lost)
