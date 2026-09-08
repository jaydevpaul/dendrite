import uuid
from typing import Annotated

from fastapi import APIRouter,Depends,HTTPException,status

from app.api.deps import SessionDep,CurrentUser
from app.models.conversation import Conversation
from app.schemas.conversation import ConversationCreate,ConversationOut,ConversationUpdate

from app.services.conversation import (
    ConversationNotFound,
    create_conversation,
    delete_conversation,
    list_conversation,
    update_conversation,
    get_owned_conversation,
)

router = APIRouter(prefix="/conversations", tags=["conversation"])

# 404 rather than 403: a 403 would confirm the id exists, which is exactly the
# fact an IDOR probe is fishing for.
NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Conversation not found"
)

async def _owned_conversation(
        conversation_id: uuid.UUID,
        user: CurrentUser,
        session: SessionDep
):
    try:
        return await get_owned_conversation(session,user,conversation_id)
    except ConversationNotFound as exc:
        raise NOT_FOUND from exc

OwnedConversation =Annotated[Conversation,Depends(_owned_conversation)]

@router.post("",response_model= ConversationOut,status_code=status.HTTP_201_CREATED)
async def create(body: ConversationCreate, user: CurrentUser, session:SessionDep):
    return await create_conversation(
        session,user,body.title,body.default_strategy
    )

@router.get("",response_model=list[ConversationOut])
async def list_all(user:CurrentUser, session:SessionDep):
    return await list_conversation(session,user)

@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_one(conversation: OwnedConversation):
    return conversation


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update(
    body: ConversationUpdate, conversation:OwnedConversation, session:SessionDep
):
    return await update_conversation(
        session, conversation,body.model_dump(exclude_unset=True)
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(conversation: OwnedConversation, session:SessionDep):
    # OwnedConversation is what makes this safe: someone else's id 404s in the
    # dependency, before this body runs.
    await delete_conversation(session, conversation)

