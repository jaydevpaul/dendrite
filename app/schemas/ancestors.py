from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models._shared import AnyStrategy, StrategySource
from app.schemas.message import EdgeOut, MessageOut


class AncestorStepOut(BaseModel):
    """One level of the chain, as the client sees it."""

    model_config = ConfigDict(from_attributes=True)

    depth: int
    message: MessageOut
    edge: EdgeOut

class StrategyResolutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    strategy: AnyStrategy
    source: StrategySource
    edge_id: UUID | None


class AncestorChain(BaseModel):
    """GET .../ancestors: what is above this message, and how it will compose.

    Both in one response because the graph navigator needs both together -
    "here is the chain, and here is why this message resolves to this
    strategy" - and because it is two cheap queries either way.
    """

    steps: list[AncestorStepOut]
    truncated: bool
    strategy: StrategyResolutionOut