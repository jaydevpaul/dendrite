"""The one concrete client, behind the same seam as the fake.

Chat completions rather than the responses API: the seam hands over a system
string and a flat list of turns, which is exactly the chat shape, and usage
arrives on the stream either way.
"""

from collections.abc import Sequence

from openai import AsyncOpenAI

from app.core.config import settings
from app.llm.base import EMBEDDING_DIMENSIONS,Completed, PromptMessage, TextDelta

__all__=["OpenAIClient"]

class OpenAIClient:
    """Satisfies LLMClient against the real API."""

    def __init__(
            self,
            client: AsyncOpenAI | None = None,
            model: str | None =  None,
            effort: str | None = None,
            embedding_model: str | None = None
    ):
        self._client = client or AsyncOpenAI(
            api_key = settings.llm_api_key,
            base_url=settings.llm_base_url
        )

        self._model = model or settings.generation_model
        self._effort=effort or settings.generation_effort
        self._embedding_model = embedding_model or settings.embedding_model

    async def generate(self, system: str, messages: Sequence[PromptMessage]):
        stream = await self._client.chat.completions.create(
            model = self._model,
            reasoning_effort=self._effort,
            messages=[
                {"role":"system", "content":system},
                *({"role" : m.role, "content":m.content}for m in messages)
            ],
            stream=True,
            stream_options={"include_usage":True}
        )

        text = ""
        usage = None
        model = self._model

        async for chunk in stream:
            if chunk.usage is not None:
                usage=chunk.usage
            if chunk.model:
                model=chunk.model
            if not chunk.choices:
                continue

            piece = chunk.choices[0].delta.content
            if not piece:
                continue

            text += piece
            yield TextDelta(text = piece)

        yield Completed(
           text=text,
            # Both nullable because a stream can die before usage is reported.
            input_tokens=usage.prompt_tokens if usage is not None else None,
            output_tokens=usage.completion_tokens if usage is not None else None,
            model=model, 
        )

    async def embed(self, text:str):
        response =  await self._client.embeddings.create(
            model=self._embedding_model,
            input=text
        )
        vector =  response.data[0].embedding

        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"{self._embedding_model} returned {len(vector)} dimensions, "
                f"expected {EMBEDDING_DIMENSIONS}"
            )

        return vector
    





