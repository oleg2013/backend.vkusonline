"""product_fields_and_nullable_family

Revision ID: a3f8b2c1d4e5
Revises: 72de5976e4a1
Create Date: 2026-03-10 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3f8b2c1d4e5'
down_revision: Union[str, None] = '72de5976e4a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make family_id nullable (products can exist without a family)
    op.alter_column('products', 'family_id', existing_type=sa.String(36), nullable=True)

    # Change default vat_rate from 22 to 20 (food products in Russia)
    op.alter_column('products', 'vat_rate', existing_type=sa.Integer(),
                    server_default=sa.text('20'))

    # Add new product fields from frontend catalog
    op.add_column('products', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('products', sa.Column('composition', sa.Text(), nullable=True))
    op.add_column('products', sa.Column('product_type', sa.String(length=50), nullable=True))
    op.add_column('products', sa.Column('sub_type', sa.String(length=50), nullable=True))
    op.add_column('products', sa.Column('product_format', sa.String(length=50), nullable=True))
    op.add_column('products', sa.Column('taste', postgresql.JSONB(), nullable=True))
    op.add_column('products', sa.Column('images', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'images')
    op.drop_column('products', 'taste')
    op.drop_column('products', 'product_format')
    op.drop_column('products', 'sub_type')
    op.drop_column('products', 'product_type')
    op.drop_column('products', 'composition')
    op.drop_column('products', 'description')

    op.alter_column('products', 'vat_rate', existing_type=sa.Integer(),
                    server_default=sa.text('22'))
    op.alter_column('products', 'family_id', existing_type=sa.String(36), nullable=False)
