from uuid import UUID
from datetime import datetime
from typing import Literal,Annotated,List

from pydantic import StringConstraints,Field, BaseModel, model_validator, ConfigDict
from app.models._shared import AnyStrategy

Role = Literal["user","assistant"]

# The column allows empty strings for server-side streaming inserts.
# Requests aren't streaming, so they must carry real text.
Content = Annotated[str,StringConstraints(strip_whitespace=True,min_length=1)]

AnchorOffset = Annotated[int,Field(ge=0)]
AnchoredText = Annotated[str,StringConstraints(min_length=1)]

class MessageCreate(BaseModel):
    role: Role
    content: Content

    # None means "this is the conversation's first message".
    parent_message_id: UUID | None = None

    # All three present = a branch. All three absent = a continuation.
    anchor_start: AnchorOffset | None = None
    anchor_end: AnchorOffset | None = None
    anchored_text: AnchoredText | None = None

    strategy_override: AnyStrategy | None = None

    @model_validator(mode="after")
    def check_the_anchor(self):
        anchor = (self.anchor_start,self.anchor_end,self.anchored_text)
        given = sum(value is not None for value in anchor)

        # Mirrors ck_edge_anchor_all_or_nothing. Better for the client: a 422 naming
        # the bad fields, not an opaque 500 from the DB's IntegrityError.
        if given not in (0,3):
            raise ValueError(
                "anchor_start, anchor_end and anchored_text must all be given, "
                "or all be omitted"
            )

        if(given == 3):
            if self.parent_message_id is None:
                raise ValueError("an anchor needs a parent_message_id to point into")
            if self.anchor_end <= self.anchor_start:
                raise ValueError("anchor_end must be greater than anchor_start")
            
        if self.strategy_override == "SpanOnly" and given == 0:
            raise ValueError("SpanOnly needs an anchor to compose from")

        return self


class MessageOut(BaseModel):
    model_config= ConfigDict(from_attributes=True)

    id:UUID
    conversation_id:UUID
    role:Role
    content: str
    created_at: datetime
    updated_at: datetime

class EdgeOut(BaseModel):
    model_config= ConfigDict(from_attributes=True)

    id: UUID
    parent_message_id: UUID
    child_message_id: UUID
    anchor_start: int | None
    anchor_end: int | None
    anchored_text: str | None
    strategy_override: AnyStrategy | None
    created_at: datetime

class MessageCreated(BaseModel):
    """POST response: the new message, and the edge that attached it.

    `edge` is None for the root message, which has nothing to attach to.
    """
    message: MessageOut
    edge: EdgeOut | None


class ConversationGraph(BaseModel):
    """GET response: every node, and every link, as two flat lists."""
    messages: List[MessageOut]
    edges: List[EdgeOut]    
