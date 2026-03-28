"""Add price exchange tables

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- price_types ---
    op.create_table(
        "price_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("label", sa.String(255), nullable=False),
    )

    # Seed default price types
    price_types_table = sa.table(
        "price_types",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("label", sa.String),
    )
    op.bulk_insert(price_types_table, [
        {"id": "pt-trade-0001", "code": "trade", "label": "Торговая цена"},
        {"id": "pt-base-0002", "code": "base", "label": "Базовая цена"},
        {"id": "pt-sale-0003", "code": "sale", "label": "Цена со скидкой"},
        {"id": "pt-cost-0004", "code": "cost", "label": "Себестоимость"},
    ])

    # --- product_prices ---
    op.create_table(
        "product_prices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False, index=True),
        sa.Column("price_type_id", sa.String(36), sa.ForeignKey("price_types.id"), nullable=False, index=True),
        sa.Column("price", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="643"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("product_id", "price_type_id", name="uq_product_price"),
    )

    # --- price_import_sessions ---
    op.create_table(
        "price_import_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("total_goods", sa.Integer, nullable=False, server_default="0"),
        sa.Column("matched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created", sa.Integer, nullable=False, server_default="0"),
        sa.Column("deleted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    # --- price_import_logs ---
    op.create_table(
        "price_import_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("price_import_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sku", sa.String(50), nullable=False),
        sa.Column("product_id", sa.String(36), nullable=True),
        sa.Column("price_type", sa.String(50), nullable=False),
        sa.Column("old_price", sa.BigInteger, nullable=True),
        sa.Column("new_price", sa.BigInteger, nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("price_import_logs")
    op.drop_table("price_import_sessions")
    op.drop_table("product_prices")
    op.drop_table("price_types")
