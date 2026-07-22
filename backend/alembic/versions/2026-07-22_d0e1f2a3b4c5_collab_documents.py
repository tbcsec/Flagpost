"""collab_documents

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-22 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'collab_documents',
        sa.Column('doc_key', sa.String(), nullable=False),
        sa.Column('competition_id', sa.String(), nullable=False),
        sa.Column('state', sa.LargeBinary(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['competition_id'], ['competitions.id'],
            name=op.f('fk_collab_documents_competition_id_competitions'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('doc_key', name=op.f('pk_collab_documents')),
    )
    with op.batch_alter_table('collab_documents', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_collab_documents_competition_id'),
            ['competition_id'], unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('collab_documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collab_documents_competition_id'))
    op.drop_table('collab_documents')
