"""feedback surveys

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-22 21:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'surveys',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_open', sa.Boolean(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_surveys_competition_id_competitions'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_surveys')),
    )
    with op.batch_alter_table('surveys', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_surveys_competition_id'), ['competition_id'], unique=False)

    op.create_table(
        'survey_questions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('survey_id', sa.String(), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('options', sa.JSON(), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['survey_id'], ['surveys.id'],
            name=op.f('fk_survey_questions_survey_id_surveys'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_survey_questions_competition_id_competitions'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_survey_questions')),
    )
    with op.batch_alter_table('survey_questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_survey_questions_survey_id'), ['survey_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_survey_questions_competition_id'), ['competition_id'], unique=False)

    op.create_table(
        'survey_responses',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('survey_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['survey_id'], ['surveys.id'],
            name=op.f('fk_survey_responses_survey_id_surveys'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_survey_responses_user_id_users'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_survey_responses_competition_id_competitions'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_survey_responses')),
        sa.UniqueConstraint('survey_id', 'user_id', name='uq_survey_response_user'),
    )
    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_survey_responses_survey_id'), ['survey_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_survey_responses_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_survey_responses_competition_id'), ['competition_id'], unique=False)

    op.create_table(
        'survey_answers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('response_id', sa.String(), nullable=False),
        sa.Column('question_id', sa.String(), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['response_id'], ['survey_responses.id'],
            name=op.f('fk_survey_answers_response_id_survey_responses'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['question_id'], ['survey_questions.id'],
            name=op.f('fk_survey_answers_question_id_survey_questions'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_survey_answers_competition_id_competitions'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_survey_answers')),
    )
    with op.batch_alter_table('survey_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_survey_answers_response_id'), ['response_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_survey_answers_question_id'), ['question_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_survey_answers_competition_id'), ['competition_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('survey_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_survey_answers_competition_id'))
        batch_op.drop_index(batch_op.f('ix_survey_answers_question_id'))
        batch_op.drop_index(batch_op.f('ix_survey_answers_response_id'))
    op.drop_table('survey_answers')

    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_survey_responses_competition_id'))
        batch_op.drop_index(batch_op.f('ix_survey_responses_user_id'))
        batch_op.drop_index(batch_op.f('ix_survey_responses_survey_id'))
    op.drop_table('survey_responses')

    with op.batch_alter_table('survey_questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_survey_questions_competition_id'))
        batch_op.drop_index(batch_op.f('ix_survey_questions_survey_id'))
    op.drop_table('survey_questions')

    with op.batch_alter_table('surveys', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_surveys_competition_id'))
    op.drop_table('surveys')
