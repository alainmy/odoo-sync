"""Add parent_task_id and instance_id to celery_task_logs

Revision ID: 007
Revises: 14400774b44c
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '14400774b44c'
branch_labels = None
depends_on = None


def upgrade():
    # Add parent_task_id column
    op.add_column('celery_task_logs', 
        sa.Column('parent_task_id', sa.String(255), nullable=True)
    )
    op.create_index(
        op.f('ix_celery_task_logs_parent_task_id'), 
        'celery_task_logs', 
        ['parent_task_id'], 
        unique=False
    )


def downgrade():
    # Drop parent_task_id column
    op.drop_index(op.f('ix_celery_task_logs_parent_task_id'), table_name='celery_task_logs')
    op.drop_column('celery_task_logs', 'parent_task_id')
