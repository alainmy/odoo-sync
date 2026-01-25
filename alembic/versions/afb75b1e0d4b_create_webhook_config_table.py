"""
create_webhook_config_table

Revision ID: afb75b1e0d4b
Revises: '2669504b3299'
Create Date: 2026-01-25 03:21:03.937474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'afb75b1e0d4b'
down_revision: Union[str, None] = '2669504b3299'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'webhook_config',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('instance_id', sa.Integer(), nullable=False),
        sa.Column('topic', sa.String(100), nullable=False, comment='e.g., product.created, order.updated'),
        sa.Column('delivery_url', sa.String(500), nullable=False, comment='URL where webhook payload is sent'),
        sa.Column('secret', sa.String(200), nullable=True, comment='Secret for webhook signature verification'),
        sa.Column('wc_webhook_id', sa.Integer(), nullable=True, comment='WooCommerce webhook ID'),
        sa.Column('status', sa.String(20), nullable=False, default='active', comment='active, paused, disabled'),
        sa.Column('active', sa.Boolean(), nullable=False, default=True),
        sa.Column('api_version', sa.String(10), nullable=False, default='wp_api_v3'),
        sa.Column('name', sa.String(200), nullable=True, comment='Friendly name for webhook'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('last_delivery_at', sa.DateTime(), nullable=True),
        sa.Column('delivery_count', sa.Integer(), nullable=False, default=0),
        sa.ForeignKeyConstraint(['instance_id'], ['woocommerce_instances.id'], ondelete='CASCADE'),
    )
    
    # Create indexes
    op.create_index('idx_webhook_instance', 'webhook_config', ['instance_id'])
    op.create_index('idx_webhook_topic', 'webhook_config', ['topic'])
    op.create_index('idx_webhook_wc_id', 'webhook_config', ['wc_webhook_id'])
    
    # Unique constraint: one webhook per topic per instance per delivery URL
    op.create_unique_constraint(
        'uq_webhook_instance_topic_url',
        'webhook_config',
        ['instance_id', 'topic', 'delivery_url']
    )


def downgrade() -> None:
    op.drop_index('idx_webhook_wc_id', 'webhook_config')
    op.drop_index('idx_webhook_topic', 'webhook_config')
    op.drop_index('idx_webhook_instance', 'webhook_config')
    op.drop_table('webhook_config')
