"""Add TagSync table

Revision ID: 004_add_tag_sync
Revises: 003_create_users
Create Date: 2026-01-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_add_tag_sync'
down_revision = '003_create_users'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create tag_sync table
    op.create_table('tag_sync',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('odoo_id', sa.Integer(), nullable=True),
    sa.Column('woocommerce_id', sa.Integer(), nullable=True),
    sa.Column('created', sa.Boolean(), nullable=True),
    sa.Column('updated', sa.Boolean(), nullable=True),
    sa.Column('skipped', sa.Boolean(), nullable=True),
    sa.Column('error', sa.Boolean(), nullable=True),
    sa.Column('needs_sync', sa.Boolean(), nullable=True),
    sa.Column('message', sa.String(length=500), nullable=True),
    sa.Column('error_details', sa.String(length=500), nullable=True),
    sa.Column('wc_date_created', sa.DateTime(timezone=True), nullable=True),
    sa.Column('wc_date_updated', sa.DateTime(timezone=True), nullable=True),
    sa.Column('odoo_write_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sync_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tag_sync_error_details'), 'tag_sync', ['error_details'], unique=False)
    op.create_index(op.f('ix_tag_sync_id'), 'tag_sync', ['id'], unique=False)
    op.create_index(op.f('ix_tag_sync_message'), 'tag_sync', ['message'], unique=False)
    op.create_index(op.f('ix_tag_sync_odoo_id'), 'tag_sync', ['odoo_id'], unique=False)
    op.create_index(op.f('ix_tag_sync_woocommerce_id'), 'tag_sync', ['woocommerce_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tag_sync_woocommerce_id'), table_name='tag_sync')
    op.drop_index(op.f('ix_tag_sync_odoo_id'), table_name='tag_sync')
    op.drop_index(op.f('ix_tag_sync_message'), table_name='tag_sync')
    op.drop_index(op.f('ix_tag_sync_id'), table_name='tag_sync')
    op.drop_index(op.f('ix_tag_sync_error_details'), table_name='tag_sync')
    op.drop_table('tag_sync')
