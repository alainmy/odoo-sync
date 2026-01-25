"""Add unique constraint on woocommerce_id in category_sync

Revision ID: 010
Revises: 009
Create Date: 2026-01-24

This migration adds a unique constraint to prevent duplicate WooCommerce category IDs
in the category_sync table, which was causing race conditions where multiple
Odoo categories would sync to the same WooCommerce category ID.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    # Add unique constraint to prevent duplicate WooCommerce category IDs per instance
    # This ensures one WooCommerce category can only be mapped to one Odoo category
    op.create_unique_constraint(
        'uq_category_sync_wc_instance',
        'category_sync',
        ['woocommerce_id', 'instance_id']
    )


def downgrade():
    # Remove the unique constraint
    op.drop_constraint(
        'uq_category_sync_wc_instance',
        'category_sync',
        type_='unique'
    )
