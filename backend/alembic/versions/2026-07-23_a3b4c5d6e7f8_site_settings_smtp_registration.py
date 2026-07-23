"""site settings: smtp + registration_open

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-23 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('registration_open', sa.Boolean(), nullable=False, server_default='1')
        )
        batch_op.add_column(sa.Column('smtp_host', sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column('smtp_port', sa.Integer(), nullable=False, server_default='587')
        )
        batch_op.add_column(sa.Column('smtp_username', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('smtp_password', sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column('smtp_from', sa.String(), nullable=False, server_default='flagpost@localhost')
        )
        batch_op.add_column(
            sa.Column('smtp_starttls', sa.Boolean(), nullable=False, server_default='1')
        )


def downgrade() -> None:
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('smtp_starttls')
        batch_op.drop_column('smtp_from')
        batch_op.drop_column('smtp_password')
        batch_op.drop_column('smtp_username')
        batch_op.drop_column('smtp_port')
        batch_op.drop_column('smtp_host')
        batch_op.drop_column('registration_open')
