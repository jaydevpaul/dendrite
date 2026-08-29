
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import DUMMY_HASH, verify_password, hash_password
from app.models.user import User

class EmailAlreadyRegistered(Exception):
    """Signup targeted an email that already has an account."""

def normalize_email(email:str):
    return email.strip().lower()

async def get_user_by_email(session:AsyncSession,email:str):
    result = await session.execute(
        select(User).where(User.email==normalize_email(email))
    )

    return result.scalar_one_or_none()

async def signup_user(session: AsyncSession, email:str, password:str):

    if await get_user_by_email(session,email) is not None:
        raise EmailAlreadyRegistered(email)

    user=User(email=normalize_email(email),password_hash=hash_password(password))
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as exc:
         # Two concurrent signups can both pass the check above. The unique
        # constraint is the real guarantee; this turns its error into ours.
        await session.rollback()
        raise EmailAlreadyRegistered(email) from exc


    await session.refresh(user)
    return user



async def authenticate_user(session:AsyncSession, email:str, password:str):
     user =await get_user_by_email(session,email)
     if user is None:
        # Burn comparable time so response latency does not reveal whether
        # the email exists.
        verify_password(password,DUMMY_HASH)
        return None

     if not verify_password(password,user.password_hash):
         return None

     return user