"""Add missing fields to job and schedules

Revision ID: 4d9908c6590d
Revises: bf3d203e53ac
Create Date: 2025-10-28 05:11:19.348926

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '4d9908c6590d'
down_revision: Union[str, None] = 'bf3d203e53ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Add missing fields to publish_jobs table
    op.add_column('publish_jobs', sa.Column('enqueued_at', sa.DateTime(), nullable=True))
    
    # Add attempt column as nullable first
    op.add_column('publish_jobs', sa.Column('attempt', sa.Integer(), nullable=True))
    # Set default value for existing rows
    op.execute("UPDATE publish_jobs SET attempt = 0 WHERE attempt IS NULL")
    # Now make it NOT NULL
    op.alter_column('publish_jobs', 'attempt', nullable=False)
    
    # Update status for existing rows
    op.execute("UPDATE publish_jobs SET status = 'planned' WHERE status = 'pending'")
    
    # Add last_run_at to schedules table
    op.add_column('schedules', sa.Column('last_run_at', sa.DateTime(), nullable=True))
    
    # Add unique constraint on (schedule_id, planned_at) for idempotency
    # Note: This will fail if there are duplicate (schedule_id, planned_at) pairs in existing data
    op.create_unique_constraint('unique_schedule_planned_at', 'publish_jobs', ['schedule_id', 'planned_at'])


def downgrade() -> None:
    # Drop the unique constraint
    op.drop_constraint('unique_schedule_planned_at', 'publish_jobs', type_='unique')
    
    # Revert status for existing rows
    op.execute("UPDATE publish_jobs SET status = 'pending' WHERE status = 'planned'")
    
    # Drop last_run_at from schedules
    op.drop_column('schedules', 'last_run_at')
    
    # Drop columns from publish_jobs
    op.drop_column('publish_jobs', 'attempt')
    op.drop_column('publish_jobs', 'enqueued_at')

