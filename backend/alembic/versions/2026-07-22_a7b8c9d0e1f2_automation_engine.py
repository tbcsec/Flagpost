"""automation engine

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-22 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'automation_rules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('trigger_type', sa.String(), nullable=False),
        sa.Column('conditions', sa.JSON(), nullable=False),
        sa.Column('actions', sa.JSON(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=True),
        sa.Column('owner_user_id', sa.String(), nullable=True),
        sa.Column('trigger_count', sa.Integer(), nullable=False),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_automation_rules_competition_id_competitions'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['owner_user_id'], ['users.id'],
            name=op.f('fk_automation_rules_owner_user_id_users'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_automation_rules')),
    )
    with op.batch_alter_table('automation_rules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_automation_rules_trigger_type'), ['trigger_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_rules_competition_id'), ['competition_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_automation_rules_owner_user_id'), ['owner_user_id'], unique=False)

    op.create_table(
        'achievements',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('team_id', sa.String(), nullable=True),
        sa.Column('rule_id', sa.String(), nullable=True),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_achievements_user_id_users'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['team_id'], ['teams.id'],
            name=op.f('fk_achievements_team_id_teams'), ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['rule_id'], ['automation_rules.id'],
            name=op.f('fk_achievements_rule_id_automation_rules'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_achievements_competition_id_competitions'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_achievements')),
    )
    with op.batch_alter_table('achievements', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_achievements_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_achievements_team_id'), ['team_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_achievements_competition_id'), ['competition_id'], unique=False)

    op.create_table(
        'score_adjustments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('team_id', sa.String(), nullable=True),
        sa.Column('rule_id', sa.String(), nullable=True),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_score_adjustments_user_id_users'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['team_id'], ['teams.id'],
            name=op.f('fk_score_adjustments_team_id_teams'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['rule_id'], ['automation_rules.id'],
            name=op.f('fk_score_adjustments_rule_id_automation_rules'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_score_adjustments_competition_id_competitions'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_score_adjustments')),
    )
    with op.batch_alter_table('score_adjustments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_score_adjustments_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_score_adjustments_team_id'), ['team_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_score_adjustments_competition_id'), ['competition_id'], unique=False)

    op.create_table(
        'competition_modules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('module_id', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_competition_modules_competition_id_competitions'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_competition_modules')),
        sa.UniqueConstraint(
            'competition_id', 'module_id', name='uq_competition_module'
        ),
    )
    with op.batch_alter_table('competition_modules', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_competition_modules_module_id'), ['module_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_competition_modules_competition_id'), ['competition_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('competition_modules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_competition_modules_competition_id'))
        batch_op.drop_index(batch_op.f('ix_competition_modules_module_id'))
    op.drop_table('competition_modules')

    with op.batch_alter_table('score_adjustments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_score_adjustments_competition_id'))
        batch_op.drop_index(batch_op.f('ix_score_adjustments_team_id'))
        batch_op.drop_index(batch_op.f('ix_score_adjustments_user_id'))
    op.drop_table('score_adjustments')

    with op.batch_alter_table('achievements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_achievements_competition_id'))
        batch_op.drop_index(batch_op.f('ix_achievements_team_id'))
        batch_op.drop_index(batch_op.f('ix_achievements_user_id'))
    op.drop_table('achievements')

    with op.batch_alter_table('automation_rules', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_automation_rules_owner_user_id'))
        batch_op.drop_index(batch_op.f('ix_automation_rules_competition_id'))
        batch_op.drop_index(batch_op.f('ix_automation_rules_trigger_type'))
    op.drop_table('automation_rules')
