"""competition invite code

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-21 15:00:00.000000
"""
from typing import Sequence, Union
from secrets import token_urlsafe

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable first, backfill each existing row with a unique code, then
    # enforce NOT NULL + UNIQUE (a single ALTER can't invent unique values).
    with op.batch_alter_table('competitions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('invite_code', sa.String(), nullable=True))

    competitions = sa.table('competitions', sa.column('id', sa.String()),
                            sa.column('invite_code', sa.String()))
    conn = op.get_bind()
    rows = conn.execute(sa.select(competitions.c.id)).fetchall()
    for (comp_id,) in rows:
        conn.execute(
            competitions.update()
            .where(competitions.c.id == comp_id)
            .values(invite_code=token_urlsafe(8))
        )

    with op.batch_alter_table('competitions', schema=None) as batch_op:
        batch_op.alter_column('invite_code', existing_type=sa.String(), nullable=False)
        batch_op.create_unique_constraint(
            batch_op.f('uq_competitions_invite_code'), ['invite_code']
        )


def downgrade() -> None:
    with op.batch_alter_table('competitions', schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f('uq_competitions_invite_code'), type_='unique'
        )
        batch_op.drop_column('invite_code')
