from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from passlib.context import CryptContext

from app.core.config import settings

ALGORITHM ="HS256"



pwd_context = CryptContext(schemes=["argon2"],deprecated="auto")

# Verified against when no user matches the submitted email, so that the
# "user not found" branch of login burns the same time as a real check.
# See docs/auth_design.md section 4.2 (timing side channel).
DUMMY_HASH = pwd_context.hash(secret="dendrite-dummy-password-never-a-real-account")

def hash_password(password:str)->str:
    """hash a plaintext password with argon2id. Salt is generated per call"""
    return pwd_context.hash(password)

def verify_password(password:str, password_hash:str):
    """Check a plaintext password against a stored hash."""
    return pwd_context.verify(password,password_hash)

def create_access_token(user_id:UUID)->str:
    """Mint a signed session token carrying the user's id."""
    now=datetime.now(timezone.utc)
    payload={
        "sub":str(user_id),
        "iat":now,
        "exp":now+settings.access_token_ttl
    }
    return jwt.encode(payload,settings.secret_key,algorithm=ALGORITHM)

def decode_access_token(token:str)->UUID | None:
    """Return the user id from a valid token, or None if it is not usable.

    Covers every failure the same way on purpose: bad signature, expired,
    malformed, missing or unparseable subject. The caller only needs to know
    'this token does not identify anyone'.
    """    

    try:
        payload=jwt.decode(token,settings.secret_key, [ALGORITHM])
    except jwt.InvalidTokenError:
        return None

    subject = payload.get("sub")
    if not isinstance(subject,str):
        return None

    try:
        return UUID(subject)
    except ValueError:
        return None 
    

