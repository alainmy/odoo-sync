"""Enhance product and category sync tables

Revision ID: 002_enhance_sync
Revises: 001_celery_integration
Create Date: 2026-01-17 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '002_enhance_sync'
down_revision = '001_celery_integration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enhance product_sync table
    op.add_column('product_sync', sa.Column('published', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('product_sync', sa.Column('needs_sync', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('product_sync', sa.Column('wc_date_created', sa.DateTime(timezone=True), nullable=True))
    op.add_column('product_sync', sa.Column('wc_date_updated', sa.DateTime(timezone=True), nullable=True))
    op.add_column('product_sync', sa.Column('odoo_write_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('product_sync', sa.Column('sync_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('product_sync', sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('product_sync', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.add_column('product_sync', sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True))
    
    # Modify message and error_details columns to have explicit length
    op.alter_column('product_sync', 'message',
                    existing_type=sa.String(),
                    type_=sa.String(500),
                    existing_nullable=True)
    op.alter_column('product_sync', 'error_details',
                    existing_type=sa.String(),
                    type_=sa.String(500),
                    existing_nullable=True)
    
    # Enhance category_sync table
    op.add_column('category_sync', sa.Column('needs_sync', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('category_sync', sa.Column('wc_date_created', sa.DateTime(timezone=True), nullable=True))
    op.add_column('category_sync', sa.Column('wc_date_updated', sa.DateTime(timezone=True), nullable=True))
    op.add_column('category_sync', sa.Column('odoo_write_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('category_sync', sa.Column('sync_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('category_sync', sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('category_sync', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    op.add_column('category_sync', sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True))
    
    # Modify message and error_details columns to have explicit length
    op.alter_column('category_sync', 'message',
                    existing_type=sa.String(),
                    type_=sa.String(500),
                    existing_nullable=True)
    op.alter_column('category_sync', 'error_details',
                    existing_type=sa.String(),
                    type_=sa.String(500),
                    existing_nullable=True)


def downgrade() -> None:
    # Remove columns from product_sync
    op.drop_column('product_sync', 'updated_at')
    op.drop_column('product_sync', 'created_at')
    op.drop_column('product_sync', 'last_synced_at')
    op.drop_column('product_sync', 'sync_date')
    op.drop_column('product_sync', 'odoo_write_date')
    op.drop_column('product_sync', 'wc_date_updated')
    op.drop_column('product_sync', 'wc_date_created')
    op.drop_column('product_sync', 'needs_sync')
    op.drop_column('product_sync', 'published')
    
    # Revert message and error_details
    op.alter_column('product_sync', 'message',
                    existing_type=sa.String(500),
                    type_=sa.String(),
                    existing_nullable=True)
    op.alter_column('product_sync', 'error_details',
                    existing_type=sa.String(500),
                    type_=sa.String(),
                    existing_nullable=True)
    
    # Remove columns from category_sync
    op.drop_column('category_sync', 'updated_at')
    op.drop_column('category_sync', 'created_at')
    op.drop_column('category_sync', 'last_synced_at')
    op.drop_column('category_sync', 'sync_date')
    op.drop_column('category_sync', 'odoo_write_date')
    op.drop_column('category_sync', 'wc_date_updated')
    op.drop_column('category_sync', 'wc_date_created')
    op.drop_column('category_sync', 'needs_sync')
    
    # Revert message and error_details
    op.alter_column('category_sync', 'message',
                    existing_type=sa.String(500),
                    type_=sa.String(),
                    existing_nullable=True)
    op.alter_column('category_sync', 'error_details',
                    existing_type=sa.String(500),
                    type_=sa.String(),
                    existing_nullable=True)
