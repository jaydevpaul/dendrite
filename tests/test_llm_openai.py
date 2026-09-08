"""The real client's wire handling, driven by a stub instead of the network.

Everything above this layer is already tested against the fake, so the only
new risk here is the wire format: which frames carry text, which frame carries
usage, and what the request has to say for usage to arrive at all. The stub
speaks in the SDK's own chunk models, so a field that gets renamed upstream
fails here rather than on the first real call.
"""

import pytest
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta
from openai.types.create_embedding_response import CreateEmbeddingResponse
from openai.types.embedding import Embedding

from app.llm.base import EMBEDDING_DIMENSIONS, Completed, PromptMessage, TextDelta
from app.llm.openai_client import OpenAIClient

MODEL = "test-generation-model"


def text_chunk(content, model=MODEL):
    """A frame carrying model output."""
    return ChatCompletionChunk(
        id="chunk",
        object="chat.completion.chunk",
        created=0,
        model=model,
        choices=[Choice(index=0, delta=ChoiceDelta(content=content))],
    )


def usage_chunk(prompt_tokens, completion_tokens, model=MODEL):
    """The final frame include_usage asks for. Its `choices` is empty - the
    real API sends no choice at all on this one."""
    return ChatCompletionChunk(
        id="chunk",
        object="chat.completion.chunk",
        created=0,
        model=model,
        choices=[],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


class StubCompletions:
    def __init__(self, chunks):
        self._chunks = chunks
        self.request = None

    async def create(self, **kwargs):
        self.request = kwargs

        async def stream():
            for chunk in self._chunks:
                yield chunk

        return stream()


class StubEmbeddings:
    def __init__(self, vector):
        self._vector = vector
        self.request = None

    async def create(self, **kwargs):
        self.request = kwargs
        return CreateEmbeddingResponse(
            object="list",
            model=kwargs["model"],
            data=[Embedding(object="embedding", index=0, embedding=self._vector)],
            usage={"prompt_tokens": 1, "total_tokens": 1},
        )


class StubOpenAI:
    """Shaped like AsyncOpenAI as far as this client reaches into it."""

    def __init__(self, chunks=(), vector=None):
        self.completions = StubCompletions(list(chunks))
        self.embeddings = StubEmbeddings(
            [0.0] * EMBEDDING_DIMENSIONS if vector is None else vector
        )

    @property
    def chat(self):
        return self


def build(chunks=(), vector=None, **kwargs):
    stub = StubOpenAI(chunks=chunks, vector=vector)
    return stub, OpenAIClient(client=stub, model=MODEL, **kwargs)


async def drain(client, system="system", messages=None):
    if messages is None:
        messages = [PromptMessage(role="user", content="hello")]
    return [event async for event in client.generate(system, messages)]


# --- the stream ---------------------------------------------------------


async def test_text_frames_become_deltas_then_one_completed():
    _, client = build([text_chunk("Hel"), text_chunk("lo"), usage_chunk(11, 2)])

    events = await drain(client)

    assert events == [
        TextDelta(text="Hel"),
        TextDelta(text="lo"),
        Completed(text="Hello", input_tokens=11, output_tokens=2, model=MODEL),
    ]


async def test_usage_frame_carries_no_choice_and_must_not_be_indexed():
    """The usage frame ends a perfectly good stream, so reaching for
    choices[0] on it would turn every successful generation into an
    IndexError."""
    _, client = build([text_chunk("fine"), usage_chunk(5, 1)])

    events = await drain(client)

    assert isinstance(events[-1], Completed)
    assert (events[-1].input_tokens, events[-1].output_tokens) == (5, 1)


async def test_frames_with_no_content_are_skipped():
    """The opening role-only frame, thinking frames and a refusal all arrive
    with content None, and none of them is text to show the reader."""
    _, client = build([text_chunk(None), text_chunk("real"), text_chunk(""), usage_chunk(1, 1)])

    events = await drain(client)

    assert events[:-1] == [TextDelta(text="real")]
    assert events[-1].text == "real"


async def test_missing_usage_leaves_both_counts_null():
    """A stream can die before usage is reported, and that is written as a
    row with null counts rather than a guessed number."""
    _, client = build([text_chunk("no usage frame")])

    completed = (await drain(client))[-1]

    assert (completed.input_tokens, completed.output_tokens) == (None, None)


async def test_completed_reports_the_model_the_provider_names():
    """The provider answers with a dated id, which is what the Generation row
    should record - not the alias that was requested."""
    dated = "test-generation-model-2026-09-01"
    _, client = build([text_chunk("hi", model=dated), usage_chunk(1, 1, model=dated)])

    assert (await drain(client))[-1].model == dated


async def test_empty_stream_still_finishes_with_completed():
    """A model may return nothing; the route still has a row to write."""
    _, client = build([])

    assert await drain(client) == [
        Completed(text="", input_tokens=None, output_tokens=None, model=MODEL)
    ]


# --- the request --------------------------------------------------------


async def test_request_asks_for_usage_and_streams():
    stub, client = build([usage_chunk(1, 1)], effort="high")

    await drain(client)

    assert stub.completions.request["stream"] is True
    # Without this no usage arrives at all and every row lands with null counts.
    assert stub.completions.request["stream_options"] == {"include_usage": True}
    assert stub.completions.request["model"] == MODEL
    assert stub.completions.request["reasoning_effort"] == "high"


async def test_system_goes_first_and_turns_keep_their_order():
    stub, client = build([usage_chunk(1, 1)])

    await drain(
        client,
        system="you are dendrite",
        messages=[
            PromptMessage(role="user", content="first"),
            PromptMessage(role="assistant", content="second"),
            PromptMessage(role="user", content="third"),
        ],
    )

    assert stub.completions.request["messages"] == [
        {"role": "system", "content": "you are dendrite"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]


# --- embeddings ---------------------------------------------------------


async def test_embed_returns_the_vector_and_names_the_model():
    stub, client = build(vector=[0.5] * EMBEDDING_DIMENSIONS, embedding_model="test-embed")

    vector = await client.embed("some text")

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert stub.embeddings.request == {"model": "test-embed", "input": "some text"}


async def test_embed_rejects_a_wrong_width():
    """A wrong embedding model returns a different width, and without this the
    failure surfaces far away as a pgvector insert error."""
    _, client = build(vector=[0.5] * 3072)

    with pytest.raises(ValueError, match="3072"):
        await client.embed("some text")
