"""dashboard_layouts

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-22 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dashboard_layouts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('dashboard_key', sa.String(), nullable=False),
        sa.Column('layout_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_dashboard_layouts_user_id_users'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dashboard_layouts')),
        sa.UniqueConstraint(
            'user_id', 'dashboard_key', name='uq_dashboard_layout_user_key'
        ),
    )
    with op.batch_alter_table('dashboard_layouts', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_dashboard_layouts_user_id'), ['user_id'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('dashboard_layouts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_dashboard_layouts_user_id'))
    op.drop_table('dashboard_layouts')
