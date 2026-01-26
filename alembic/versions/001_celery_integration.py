"""Add webhook and task tracking tables

Revision ID: 001_celery_integration
Revises: 
Create Date: 2026-01-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = '001_celery_integration'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create product_sync table
    op.create_table(
        'product_sync',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('odoo_id', sa.Integer(), nullable=True),
        sa.Column('woocommerce_id', sa.Integer(), nullable=True),
        sa.Column('created', sa.Boolean(), nullable=True),
        sa.Column('updated', sa.Boolean(), nullable=True),
        sa.Column('skipped', sa.Boolean(), nullable=True),
        sa.Column('error', sa.Boolean(), nullable=True),
        sa.Column('message', sa.String(500), nullable=True),
        sa.Column('error_details', sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_product_sync_odoo_id'), 'product_sync', ['odoo_id'], unique=False)
    op.create_index(op.f('ix_product_sync_woocommerce_id'), 'product_sync', ['woocommerce_id'], unique=False)
    op.create_index(op.f('ix_product_sync_message'), 'product_sync', ['message'], unique=False)
    op.create_index(op.f('ix_product_sync_error_details'), 'product_sync', ['error_details'], unique=False)

    # Create category_sync table
    op.create_table(
        'category_sync',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('odoo_id', sa.Integer(), nullable=True),
        sa.Column('woocommerce_id', sa.Integer(), nullable=True),
        sa.Column('created', sa.Boolean(), nullable=True),
        sa.Column('updated', sa.Boolean(), nullable=True),
        sa.Column('skipped', sa.Boolean(), nullable=True),
        sa.Column('error', sa.Boolean(), nullable=True),
        sa.Column('message', sa.String(500), nullable=True),
        sa.Column('error_details', sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_category_sync_odoo_id'), 'category_sync', ['odoo_id'], unique=False)
    op.create_index(op.f('ix_category_sync_woocommerce_id'), 'category_sync', ['woocommerce_id'], unique=False)
    op.create_index(op.f('ix_category_sync_message'), 'category_sync', ['message'], unique=False)
    op.create_index(op.f('ix_category_sync_error_details'), 'category_sync', ['error_details'], unique=False)

    # Create webhook_logs table
    op.create_table(
        'webhook_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(255), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=True),
        sa.Column('payload_hash', sa.String(64), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_webhook_logs_created_at'), 'webhook_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_webhook_logs_event_id'), 'webhook_logs', ['event_id'], unique=True)
    op.create_index(op.f('ix_webhook_logs_event_type'), 'webhook_logs', ['event_type'], unique=False)
    op.create_index(op.f('ix_webhook_logs_payload_hash'), 'webhook_logs', ['payload_hash'], unique=False)

    # Create celery_task_logs table
    op.create_table(
        'celery_task_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.String(255), nullable=True),
        sa.Column('task_name', sa.String(255), nullable=True),
        sa.Column('task_args', sa.JSON(), nullable=True),
        sa.Column('task_kwargs', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_celery_task_logs_created_at'), 'celery_task_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_celery_task_logs_task_id'), 'celery_task_logs', ['task_id'], unique=True)
    op.create_index(op.f('ix_celery_task_logs_task_name'), 'celery_task_logs', ['task_name'], unique=False)

    # Create woocommerce_instances table
    op.create_table(
        'woocommerce_instances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('url', sa.String(500), nullable=True),
        sa.Column('consumer_key', sa.String(255), nullable=True),
        sa.Column('consumer_secret', sa.String(255), nullable=True),
        sa.Column('webhook_secret', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('odoo_url', sa.String(500), nullable=True),
        sa.Column('odoo_db', sa.String(255), nullable=True),
        sa.Column('odoo_username', sa.String(255), nullable=True),
        sa.Column('odoo_password', sa.String(255), nullable=True),
        sa.Column('auto_sync_products', sa.Boolean(), nullable=True),
        sa.Column('auto_sync_orders', sa.Boolean(), nullable=True),
        sa.Column('auto_sync_customers', sa.Boolean(), nullable=True),
        sa.Column('sync_interval_minutes', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_woocommerce_instances_name'), 'woocommerce_instances', ['name'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_woocommerce_instances_name'), table_name='woocommerce_instances')
    op.drop_table('woocommerce_instances')
    
    op.drop_index(op.f('ix_celery_task_logs_task_name'), table_name='celery_task_logs')
    op.drop_index(op.f('ix_celery_task_logs_task_id'), table_name='celery_task_logs')
    op.drop_index(op.f('ix_celery_task_logs_created_at'), table_name='celery_task_logs')
    op.drop_table('celery_task_logs')
    
    op.drop_index(op.f('ix_webhook_logs_payload_hash'), table_name='webhook_logs')
    op.drop_index(op.f('ix_webhook_logs_event_type'), table_name='webhook_logs')
    op.drop_index(op.f('ix_webhook_logs_event_id'), table_name='webhook_logs')
    op.drop_index(op.f('ix_webhook_logs_created_at'), table_name='webhook_logs')
    op.drop_table('webhook_logs')
    
    op.drop_index(op.f('ix_category_sync_error_details'), table_name='category_sync')
    op.drop_index(op.f('ix_category_sync_message'), table_name='category_sync')
    op.drop_index(op.f('ix_category_sync_woocommerce_id'), table_name='category_sync')
    op.drop_index(op.f('ix_category_sync_odoo_id'), table_name='category_sync')
    op.drop_table('category_sync')
    
    op.drop_index(op.f('ix_product_sync_error_details'), table_name='product_sync')
    op.drop_index(op.f('ix_product_sync_message'), table_name='product_sync')
    op.drop_index(op.f('ix_product_sync_woocommerce_id'), table_name='product_sync')
    op.drop_index(op.f('ix_product_sync_odoo_id'), table_name='product_sync')
    op.drop_table('product_sync')
