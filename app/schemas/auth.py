from uuid import UUID

from pydantic import BaseModel,ConfigDict,EmailStr,Field


class SignupRequest(BaseModel):
    email:EmailStr
    password:str=Field(min_length=8,max_length=1024)

class LoginRequest(BaseModel):
    email:EmailStr
    password:str

class UserOut(BaseModel):
    """Everything we are willing to say about a user over the wire."""

    model_config=ConfigDict(from_attributes=True)
    id:UUID
    email: EmailStr

