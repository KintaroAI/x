"""rename_metadata_to_extra_data

Revision ID: a3b0d580191d
Revises: 001
Create Date: 2025-10-26 20:18:33.421588

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b0d580191d'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Rename 'metadata' column to 'extra_data'
    op.alter_column('audit_log', 'metadata', new_column_name='extra_data')


def downgrade() -> None:
    # Rename 'extra_data' column back to 'metadata'
    op.alter_column('audit_log', 'extra_data', new_column_name='metadata')

