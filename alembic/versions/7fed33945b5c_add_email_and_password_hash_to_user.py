"""add email and password_hash to user

Revision ID: 7fed33945b5c
Revises: 4624be06dde7
Create Date: 2026-08-21 14:34:44.853313

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7fed33945b5c'
down_revision: Union[str, Sequence[str], None] = '4624be06dde7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    # Both columns are NOT NULL with no server default, which is only safe
    # because "user" has zero rows. With existing rows this would need the
    # add-nullable -> backfill -> SET NOT NULL sequence instead.
    op.add_column('user', sa.Column('email', sa.Text(), nullable=False))
    op.add_column('user', sa.Column('password_hash', sa.Text(), nullable=False))
    # Named explicitly: autogenerate emits None here, which works on the way
    # up (Postgres picks a name) but makes downgrade() undroppable.
    op.create_unique_constraint('uq_user_email', 'user', ['email'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_user_email', 'user', type_='unique')
    op.drop_column('user', 'password_hash')
    op.drop_column('user', 'email')
