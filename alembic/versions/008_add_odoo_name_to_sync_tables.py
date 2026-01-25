"""Add odoo_name to sync tables

Revision ID: 008
Revises: 28e4f56d186e
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008'
down_revision = '28e4f56d186e'
branch_labels = None
depends_on = None


def upgrade():
    # Add odoo_name to category_sync
    op.add_column('category_sync',
        sa.Column('odoo_name', sa.String(255), nullable=True)
    )
    op.create_index(
        op.f('ix_category_sync_odoo_name'),
        'category_sync',
        ['odoo_name'],
        unique=False
    )
    
    # Add odoo_name to tag_sync
    op.add_column('tag_sync',
        sa.Column('odoo_name', sa.String(255), nullable=True)
    )
    op.create_index(
        op.f('ix_tag_sync_odoo_name'),
        'tag_sync',
        ['odoo_name'],
        unique=False
    )
    
    # Add odoo_name to attribute_syncs
    op.add_column('attribute_syncs',
        sa.Column('odoo_name', sa.String(255), nullable=True)
    )
    op.create_index(
        op.f('ix_attribute_syncs_odoo_name'),
        'attribute_syncs',
        ['odoo_name'],
        unique=False
    )
    
    # Add odoo_name to attribute_value_syncs
    op.add_column('attribute_value_syncs',
        sa.Column('odoo_name', sa.String(255), nullable=True)
    )
    op.create_index(
        op.f('ix_attribute_value_syncs_odoo_name'),
        'attribute_value_syncs',
        ['odoo_name'],
        unique=False
    )


def downgrade():
    # Drop odoo_name from attribute_value_syncs
    op.drop_index(op.f('ix_attribute_value_syncs_odoo_name'), table_name='attribute_value_syncs')
    op.drop_column('attribute_value_syncs', 'odoo_name')
    
    # Drop odoo_name from attribute_syncs
    op.drop_index(op.f('ix_attribute_syncs_odoo_name'), table_name='attribute_syncs')
    op.drop_column('attribute_syncs', 'odoo_name')
    
    # Drop odoo_name from tag_sync
    op.drop_index(op.f('ix_tag_sync_odoo_name'), table_name='tag_sync')
    op.drop_column('tag_sync', 'odoo_name')
    
    # Drop odoo_name from category_sync
    op.drop_index(op.f('ix_category_sync_odoo_name'), table_name='category_sync')
    op.drop_column('category_sync', 'odoo_name')
