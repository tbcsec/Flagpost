"""submissions

Revision ID: a1b2c3d4e5f6
Revises: e127a3ac9202
Create Date: 2026-07-20 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e127a3ac9202'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'submissions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('challenge_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=True),
        sa.Column('value', sa.String(), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=False),
        sa.Column('is_duplicate', sa.Boolean(), nullable=False),
        sa.Column('points_awarded', sa.Integer(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['challenge_id'], ['challenges.id'],
            name=op.f('fk_submissions_challenge_id_challenges'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_submissions_user_id_users'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['team_id'], ['teams.id'],
            name=op.f('fk_submissions_team_id_teams'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_submissions_competition_id_competitions'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_submissions')),
    )
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_submissions_challenge_id'), ['challenge_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_submissions_user_id'), ['user_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_submissions_team_id'), ['team_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_submissions_competition_id'),
            ['competition_id'], unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('submissions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_submissions_competition_id'))
        batch_op.drop_index(batch_op.f('ix_submissions_team_id'))
        batch_op.drop_index(batch_op.f('ix_submissions_user_id'))
        batch_op.drop_index(batch_op.f('ix_submissions_challenge_id'))

    op.drop_table('submissions')
