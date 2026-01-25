"""Create pricelist_sync table

Revision ID: 011
Revises: 010
Create Date: 2026-01-24

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    """Create pricelist_sync table for tracking Odoo pricelist to WooCommerce sync."""
    op.create_table(
        'pricelist_sync',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('odoo_pricelist_id', sa.Integer(), nullable=False, comment='Odoo pricelist ID'),
        sa.Column('odoo_pricelist_name', sa.String(255), nullable=True, comment='Odoo pricelist name'),
        sa.Column('instance_id', sa.Integer(), nullable=False, comment='WooCommerce instance ID'),
        sa.Column('active', sa.Boolean(), default=True, nullable=False, comment='Is this pricelist active for sync'),
        sa.Column('price_type', sa.String(50), default='regular', nullable=False, comment='Type: regular, sale, meta'),
        sa.Column('meta_key', sa.String(100), nullable=True, comment='Meta key for custom price fields'),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True, comment='Last sync timestamp'),
        sa.Column('created_at', sa.DateTime(), default=datetime.utcnow, nullable=False),
        sa.Column('updated_at', sa.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False),
        sa.Column('message', sa.Text(), nullable=True, comment='Last sync message or errors'),
        
        # Unique constraint: one pricelist per instance
        sa.UniqueConstraint('odoo_pricelist_id', 'instance_id', name='uq_pricelist_sync_instance'),
        
        # Indexes for faster queries
        sa.Index('idx_pricelist_sync_instance', 'instance_id'),
        sa.Index('idx_pricelist_sync_active', 'active'),
    )


def downgrade():
    """Drop pricelist_sync table."""
    op.drop_table('pricelist_sync')
