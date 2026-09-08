from typing import Annotated

from functools import lru_cache
from app.llm.openai_client import OpenAIClient

from fastapi import Cookie,HTTPException,Depends,status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


from app.core.db import get_session,async_session_factory
from app.core.config import settings
from app.core.security import decode_access_token
from app.models.user import User

from app.llm.base import LLMClient
from app.llm.fake import FakeLLMClient

SessionDep=Annotated[AsyncSession,Depends(get_session)]

def get_session_factory():
    """Sessions for work that outlives the request."""

    return async_session_factory

SessionFactoryDep = Annotated[
    async_sessionmaker[AsyncSession],Depends(get_session_factory)
]

def get_llm():
    """The model client for this request."""

    if settings.llm_client =="fake":
        return FakeLLMClient()

    return _openai_client()

LLMDep= Annotated[LLMClient, Depends(get_llm)]


# Request rejection Msg common for every type of rejection
CREDENTIALS_ERROR =HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not Authenticated",
)

async def get_current_user(
        session:SessionDep,
        session_cookie:Annotated[str|None, Cookie(alias=settings.cookie_name)] =None,
):
    if session_cookie  is None:
        raise CREDENTIALS_ERROR

    user_id =  decode_access_token(session_cookie)

    if user_id is None:
        raise CREDENTIALS_ERROR

    user = await session.get(User,user_id)

    if user is None:
        raise CREDENTIALS_ERROR

    return user

CurrentUser = Annotated[User,Depends(get_current_user)]


@lru_cache
def _openai_client():
    return OpenAIClient()


    

