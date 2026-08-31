import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.conversation import Conversation

class ConversationNotFound(Exception):
    """No conversation with that id is visible to this user.

    Deliberately does not distinguish "does not exist" from "belongs to
    someone else" - the route turns both into the same 404.
    """

async def create_conversation(
        session:AsyncSession,
        user: User,
        title: str|None,
        default_strategy: str
):
    conversation = Conversation(
        user_id=user.id,
        default_strategy=default_strategy
        )

    if title is not None:
        conversation.title=title

    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation

async def list_conversation(session:AsyncSession, user: User):
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id==user.id)
        .order_by(Conversation.updated_at.desc(),Conversation.id.desc())
    )
    return list(result.scalars().all())


async def get_owned_conversation(
        session:AsyncSession,
        user: User,
        conversation_id: uuid.UUID
):
    result = await session.execute(
        select(Conversation).where(
            Conversation.id==conversation_id,
            Conversation.user_id==user.id
        )
    )

    conversation =result.scalar_one_or_none()

    if conversation is None:
        raise ConversationNotFound(conversation_id)

    return conversation


async def update_conversation(
        session:AsyncSession,
        conversation: Conversation,
        changes: dict
):
    for field,value in changes.items():
        if value is not None:
            setattr(conversation,field,value)

    await session.commit()
    await session.refresh(conversation)
    return conversation