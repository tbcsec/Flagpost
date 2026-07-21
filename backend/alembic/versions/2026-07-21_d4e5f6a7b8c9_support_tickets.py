"""support tickets

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-21 17:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tickets',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('subject', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('challenge_id', sa.String(), nullable=True),
        sa.Column('opener_user_id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=True),
        sa.Column('assignee_user_id', sa.String(), nullable=True),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['challenge_id'], ['challenges.id'],
            name=op.f('fk_tickets_challenge_id_challenges'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['opener_user_id'], ['users.id'],
            name=op.f('fk_tickets_opener_user_id_users'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['team_id'], ['teams.id'],
            name=op.f('fk_tickets_team_id_teams'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['assignee_user_id'], ['users.id'],
            name=op.f('fk_tickets_assignee_user_id_users'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_tickets_competition_id_competitions'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tickets')),
    )
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tickets_challenge_id'), ['challenge_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tickets_opener_user_id'), ['opener_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tickets_team_id'), ['team_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tickets_competition_id'), ['competition_id'], unique=False)

    op.create_table(
        'ticket_messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('ticket_id', sa.String(), nullable=False),
        sa.Column('author_user_id', sa.String(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['ticket_id'], ['tickets.id'],
            name=op.f('fk_ticket_messages_ticket_id_tickets'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['author_user_id'], ['users.id'],
            name=op.f('fk_ticket_messages_author_user_id_users'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_ticket_messages_competition_id_competitions'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ticket_messages')),
    )
    with op.batch_alter_table('ticket_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ticket_messages_ticket_id'), ['ticket_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ticket_messages_competition_id'), ['competition_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('ticket_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ticket_messages_competition_id'))
        batch_op.drop_index(batch_op.f('ix_ticket_messages_ticket_id'))
    op.drop_table('ticket_messages')

    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tickets_competition_id'))
        batch_op.drop_index(batch_op.f('ix_tickets_team_id'))
        batch_op.drop_index(batch_op.f('ix_tickets_opener_user_id'))
        batch_op.drop_index(batch_op.f('ix_tickets_challenge_id'))
    op.drop_table('tickets')
