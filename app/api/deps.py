from typing import Annotated

from fastapi import Cookie,HTTPException,Depends,status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.config import settings
from app.core.security import decode_access_token
from app.models.user import User

SessionDep=Annotated[AsyncSession,Depends(get_session)]

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


    

