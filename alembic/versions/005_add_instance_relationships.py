"""Add instance relationships to all tables

Revision ID: 005_add_instance_relationships
Revises: 004_add_tag_sync
Create Date: 2026-01-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_add_instance_relationships'
down_revision = '004_add_tag_sync'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar user_id a woocommerce_instances
    op.add_column('woocommerce_instances', 
        sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_woocommerce_instances_user_id'), 
        'woocommerce_instances', ['user_id'], unique=False)
    op.create_foreign_key('fk_woocommerce_instances_user_id', 
        'woocommerce_instances', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    
    # Agregar instance_id a category_sync
    op.add_column('category_sync', 
        sa.Column('instance_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_category_sync_instance_id'), 
        'category_sync', ['instance_id'], unique=False)
    op.create_foreign_key('fk_category_sync_instance_id', 
        'category_sync', 'woocommerce_instances', ['instance_id'], ['id'], ondelete='CASCADE')
    
    # Agregar instance_id a tag_sync
    op.add_column('tag_sync', 
        sa.Column('instance_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_tag_sync_instance_id'), 
        'tag_sync', ['instance_id'], unique=False)
    op.create_foreign_key('fk_tag_sync_instance_id', 
        'tag_sync', 'woocommerce_instances', ['instance_id'], ['id'], ondelete='CASCADE')
    
    # Agregar instance_id a product_sync
    op.add_column('product_sync', 
        sa.Column('instance_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_product_sync_instance_id'), 
        'product_sync', ['instance_id'], unique=False)
    op.create_foreign_key('fk_product_sync_instance_id', 
        'product_sync', 'woocommerce_instances', ['instance_id'], ['id'], ondelete='CASCADE')
    
    # Agregar instance_id a webhook_logs
    op.add_column('webhook_logs', 
        sa.Column('instance_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_webhook_logs_instance_id'), 
        'webhook_logs', ['instance_id'], unique=False)
    op.create_foreign_key('fk_webhook_logs_instance_id', 
        'webhook_logs', 'woocommerce_instances', ['instance_id'], ['id'], ondelete='CASCADE')
    
    # Agregar instance_id a celery_task_logs
    op.add_column('celery_task_logs', 
        sa.Column('instance_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_celery_task_logs_instance_id'), 
        'celery_task_logs', ['instance_id'], unique=False)
    op.create_foreign_key('fk_celery_task_logs_instance_id', 
        'celery_task_logs', 'woocommerce_instances', ['instance_id'], ['id'], ondelete='CASCADE')


def downgrade():
    # Eliminar foreign keys e índices en orden inverso
    op.drop_constraint('fk_celery_task_logs_instance_id', 'celery_task_logs', type_='foreignkey')
    op.drop_index(op.f('ix_celery_task_logs_instance_id'), table_name='celery_task_logs')
    op.drop_column('celery_task_logs', 'instance_id')
    
    op.drop_constraint('fk_webhook_logs_instance_id', 'webhook_logs', type_='foreignkey')
    op.drop_index(op.f('ix_webhook_logs_instance_id'), table_name='webhook_logs')
    op.drop_column('webhook_logs', 'instance_id')
    
    op.drop_constraint('fk_product_sync_instance_id', 'product_sync', type_='foreignkey')
    op.drop_index(op.f('ix_product_sync_instance_id'), table_name='product_sync')
    op.drop_column('product_sync', 'instance_id')
    
    op.drop_constraint('fk_tag_sync_instance_id', 'tag_sync', type_='foreignkey')
    op.drop_index(op.f('ix_tag_sync_instance_id'), table_name='tag_sync')
    op.drop_column('tag_sync', 'instance_id')
    
    op.drop_constraint('fk_category_sync_instance_id', 'category_sync', type_='foreignkey')
    op.drop_index(op.f('ix_category_sync_instance_id'), table_name='category_sync')
    op.drop_column('category_sync', 'instance_id')
    
    op.drop_constraint('fk_woocommerce_instances_user_id', 'woocommerce_instances', type_='foreignkey')
    op.drop_index(op.f('ix_woocommerce_instances_user_id'), table_name='woocommerce_instances')
    op.drop_column('woocommerce_instances', 'user_id')
