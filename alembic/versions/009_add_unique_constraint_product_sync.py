"""Add unique constraint on woocommerce_id in product_sync

Revision ID: 009
Revises: 008
Create Date: 2026-01-24

This migration adds a unique constraint to prevent duplicate WooCommerce IDs
in the product_sync table, which was causing race conditions where multiple
Odoo products would sync to the same WooCommerce product ID.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    # Add unique constraint to prevent duplicate WooCommerce IDs per instance
    # This ensures one WooCommerce product can only be mapped to one Odoo product
    op.create_unique_constraint(
        'uq_product_sync_wc_instance',
        'product_sync',
        ['woocommerce_id', 'instance_id']
    )


def downgrade():
    # Remove the unique constraint
    op.drop_constraint(
        'uq_product_sync_wc_instance',
        'product_sync',
        type_='unique'
    )
