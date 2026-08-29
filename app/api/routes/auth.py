from fastapi import APIRouter,Response,HTTPException,status

from app.models.user import User

from app.core.config import settings
from app.core.security import create_access_token
from app.api.deps import SessionDep,CurrentUser

from app.services.auth import signup_user,EmailAlreadyRegistered, authenticate_user

from app.schemas.auth import UserOut,SignupRequest,LoginRequest

router = APIRouter(prefix="/auth",tags=["auth"])

def _set_session_cookie(response: Response, user: User):
    response.set_cookie(
        key=settings.cookie_name,
        value=create_access_token(user.id),
        max_age=int(settings.access_token_ttl.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,   
        path="/"
    )

@router.post(path="/signup",response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(body:SignupRequest, response:Response, session:SessionDep):

    try:
        user= await signup_user(session,body.email,body.password)
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email Already Registered"
        )from exc

    _set_session_cookie(response,user)
    return user

@router.post(path="/login", response_model=UserOut)
async def login(body: LoginRequest, response: Response ,session: SessionDep, ):
    user = await authenticate_user(session,body.email,body.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong Credentials"
        )

    _set_session_cookie(response,user)
    return user


@router.post("/logout",status_code=status.HTTP_204_NO_CONTENT)
async def logout(response:Response):
    response.delete_cookie(
        key=settings.cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/"
    )

@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user