"""rename woocommerce instance columns

Revision ID: 006
Revises: 005
Create Date: 2026-01-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005_add_instance_relationships'
branch_labels = None
depends_on = None


def upgrade():
    # Renombrar columnas de WooCommerce - MySQL requiere especificar el tipo
    op.alter_column('woocommerce_instances', 'url', 
                    new_column_name='woocommerce_url',
                    existing_type=sa.String(500))
    op.alter_column('woocommerce_instances', 'consumer_key', 
                    new_column_name='woocommerce_consumer_key',
                    existing_type=sa.String(255))
    op.alter_column('woocommerce_instances', 'consumer_secret', 
                    new_column_name='woocommerce_consumer_secret',
                    existing_type=sa.String(255))


def downgrade():
    # Revertir renombrado
    op.alter_column('woocommerce_instances', 'woocommerce_url', 
                    new_column_name='url',
                    existing_type=sa.String(500))
    op.alter_column('woocommerce_instances', 'woocommerce_consumer_key', 
                    new_column_name='consumer_key',
                    existing_type=sa.String(255))
    op.alter_column('woocommerce_instances', 'woocommerce_consumer_secret', 
                    new_column_name='consumer_secret',
                    existing_type=sa.String(255))
