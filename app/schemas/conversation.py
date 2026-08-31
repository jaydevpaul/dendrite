
from datetime import datetime
from typing import Annotated
from uuid import UUID

from app.models._shared import NonSpanStrategy, DEFAULT_STRATEGY

from pydantic import BaseModel,ConfigDict, StringConstraints

Title = Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=200)]

class ConversationCreate(BaseModel):
    title : Title | None =None
    default_strategy: NonSpanStrategy = DEFAULT_STRATEGY

class ConversationUpdate(BaseModel):
    # PATCH: absent fields are left alone.
    title : Title | None =None
    default_strategy: NonSpanStrategy | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:UUID
    title:str
    default_strategy: NonSpanStrategy
    root_message_id:UUID | None
    created_at: datetime
    updated_at: datetime

    