"""cascade deletes so one DELETE removes a whole conversation

Revision ID: b1c4d9e77a30
Revises: 70ccde22e86d
Create Date: 2026-09-08 00:00:00.000000

Hand-written: Alembic's autogenerate does not compare a foreign key's ON
DELETE action at all, so it reports "no changes" for this whole migration.

Deleting a conversation has to take its messages with it, and each message its
edges, generations, summaries and embeddings. Doing that as six ordered
DELETEs in Python is six chances to leave orphans behind; the database can do
it in one statement, and a new child table inherits the behaviour by declaring
its own foreign key rather than by someone remembering to extend a list.

conversation.root_message_id is the one exception - SET NULL, not CASCADE.
That column points *down* into the conversation's own first message, so
cascading from it would mean deleting one message could take the conversation
and every other message with it.

Every constraint is dropped and recreated by name, because an unnamed one
leaves downgrade() unrunnable.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b1c4d9e77a30'
down_revision: Union[str, Sequence[str], None] = '70ccde22e86d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (constraint name, table, column, target table, target column)
CASCADES = [
    ("message_conversation_id_fkey", "message", "conversation_id", "conversation"),
    ("edge_parent_message_id_fkey", "edge", "parent_message_id", "message"),
    ("edge_child_message_id_fkey", "edge", "child_message_id", "message"),
    ("generation_user_message_id_fkey", "generation", "user_message_id", "message"),
    (
        "generation_assistant_message_id_fkey",
        "generation",
        "assistant_message_id",
        "message",
    ),
    ("message_summary_message_id_fkey", "message_summary", "message_id", "message"),
    (
        "message_embedding_message_id_fkey",
        "message_embedding",
        "message_id",
        "message",
    ),
]

ROOT_FK = "fk_conversation_root_message_id"


def _recreate(name, table, column, target, ondelete):
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, target, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    """Upgrade schema."""
    for name, table, column, target in CASCADES:
        _recreate(name, table, column, target, "CASCADE")

    _recreate(ROOT_FK, "conversation", "root_message_id", "message", "SET NULL")


def downgrade() -> None:
    """Downgrade schema."""
    for name, table, column, target in CASCADES:
        _recreate(name, table, column, target, None)

    _recreate(ROOT_FK, "conversation", "root_message_id", "message", None)
