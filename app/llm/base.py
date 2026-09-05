from collections.abc import AsyncIterator, Sequence
from typing import Literal,Protocol
from dataclasses import dataclass

# text-embedding-3-small -> vector(1536).
EMBEDDING_DIMENSIONS = 1536

PromptRole = Literal["user","assistant"]

@dataclass(frozen=True)
class PromptMessage:
    """One turn of  the composed prompt"""

    role: PromptRole
    content:str


@dataclass(frozen=True)
class TextDelta:
    """One streamed fragment. Maps 1:1 onto D10's `chunk` SSE event."""

    text: str

@dataclass(frozen=True)
class Completed:
    """The terminal event of a successful generation"""

    text: str
    input_tokens: int | None
    output_tokens: int | None
    model: str


# A generation stream is zero or more TextDelta followed by exactly one Completed. 
GenerationEvent = TextDelta | Completed

class LLMClient(Protocol):
        """Generation and embeddings. Deliberately not a provider registry"""

        def generate(
                  self,
                  system:str,
                  messages: Sequence[PromptMessage  ]
        ) -> AsyncIterator[GenerationEvent]:
             """Stream one reply. An async generator function, so it is declared as
        a plain method returning an AsyncIterator, not as `async def`."""
             ...

        async def embed(self, text: str) -> list[float]:
            """One vector of EMBEDDING_DIMENSIONS floats."""
            ...





















































































