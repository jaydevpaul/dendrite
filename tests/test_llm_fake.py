"""C1 - the LLMClient seam and its fake.

No database, no network. These tests are about the fake itself, and they matter
more than they look: FakeLLMClient is the assertion surface for every
composition test in C2-C6. If `calls` does not faithfully record what a strategy
handed the model, those later tests assert on nothing.
"""

import asyncio

import pytest

from app.llm.base import Completed, PromptMessage, TextDelta
from app.llm.fake import EMBEDDING_DIMENSIONS, FakeLLMClient, FakeLLMError, fake_vector

SYSTEM = "You are answering inside a branching conversation."
MESSAGES = [
    PromptMessage(role="user", content="Postgres or a vector DB?"),
    PromptMessage(role="assistant", content="pgvector is enough for your scale."),
    PromptMessage(role="user", content="What does that cost me?"),
]


async def drain(client, system=SYSTEM, messages=None):
    """Run one generation to completion, returning every event in order."""
    return [event async for event in client.generate(system, messages or MESSAGES)]


# --- the assertion surface ------------------------------------------------


async def test_records_exactly_what_it_was_handed():
    client = FakeLLMClient()

    await drain(client)

    assert len(client.calls) == 1
    assert client.calls[0].system == SYSTEM
    assert client.calls[0].messages == MESSAGES


async def test_records_each_call_separately():
    client = FakeLLMClient()

    await drain(client)
    await drain(client, system="another preamble")

    assert [call.system for call in client.calls] == [SYSTEM, "another preamble"]


async def test_recorded_messages_are_a_copy():
    """A caller mutating its list afterwards must not rewrite history.

    Without list() in generate(), a composer that builds one list and reuses it
    would leave every recorded call pointing at the same final state - and a
    per-strategy test would then pass no matter what the strategy did.
    """
    messages = list(MESSAGES)
    client = FakeLLMClient()

    await drain(client, messages=messages)
    messages.append(PromptMessage(role="user", content="injected later"))

    assert client.calls[0].messages == MESSAGES


# --- the event sequence ---------------------------------------------------


async def test_yields_a_delta_per_chunk_then_one_completed():
    client = FakeLLMClient(chunks=["Recall is", " the fraction", " of neighbours"])

    events = await drain(client)

    assert [type(event) for event in events] == [
        TextDelta,
        TextDelta,
        TextDelta,
        Completed,
    ]
    assert [event.text for event in events[:-1]] == [
        "Recall is",
        " the fraction",
        " of neighbours",
    ]


async def test_completed_carries_the_whole_buffered_reply():
    """8.14 writes `content` once, from Completed.text - not by accumulating
    deltas in the route. So the fake has to supply the join itself."""
    client = FakeLLMClient(chunks=["Recall is", " the fraction"])

    events = await drain(client)

    assert events[-1].text == "Recall is the fraction"


async def test_completed_reports_the_model_and_token_counts():
    client = FakeLLMClient(chunks=["four words in here"], model="fake-luna")

    completed = (await drain(client))[-1]

    assert completed.model == "fake-luna"
    assert completed.output_tokens == 4
    # System plus all three messages, so input must exceed any one of them.
    assert completed.input_tokens > completed.output_tokens


async def test_token_counts_are_deterministic():
    first = (await drain(FakeLLMClient()))[-1]
    second = (await drain(FakeLLMClient()))[-1]

    assert (first.input_tokens, first.output_tokens) == (
        second.input_tokens,
        second.output_tokens,
    )


async def test_an_empty_script_still_completes():
    """A model can legally return nothing. The route must still get a Completed
    to write, rather than an empty stream it has to special-case."""
    client = FakeLLMClient(chunks=[])

    events = await drain(client)

    assert [type(event) for event in events] == [Completed]
    assert events[0].text == ""
    assert events[0].output_tokens == 0


# --- failure, for D9's failure path ---------------------------------------


async def test_fail_after_chunk_raises_and_yields_no_completed():
    client = FakeLLMClient(chunks=["a", "b", "c", "d"], fail_after_chunk=2)

    seen = []
    with pytest.raises(FakeLLMError):
        async for event in client.generate(SYSTEM, MESSAGES):
            seen.append(event)

    assert [event.text for event in seen] == ["a", "b"]
    assert not any(isinstance(event, Completed) for event in seen)


async def test_fail_after_chunk_zero_fails_before_any_text():
    client = FakeLLMClient(fail_after_chunk=0)

    with pytest.raises(FakeLLMError):
        await drain(client)


async def test_a_failed_call_is_still_recorded():
    """D9 writes composed_context even for a failed generation, so the fake has
    to have recorded the prompt before it fails."""
    client = FakeLLMClient(fail_after_chunk=0)

    with pytest.raises(FakeLLMError):
        await drain(client)

    assert client.calls[0].messages == MESSAGES


# --- the gate, for D1's `pending` -----------------------------------------


async def test_the_gate_holds_the_stream_until_it_is_set():
    """D9 commits the blank row before streaming, so a test that freezes the
    stream here can assert what a second session sees mid-generation."""
    gate = asyncio.Event()
    client = FakeLLMClient(chunks=["held"], gate=gate)

    events = []

    async def run():
        async for event in client.generate(SYSTEM, MESSAGES):
            events.append(event)

    task = asyncio.create_task(run())
    await asyncio.sleep(0)

    assert events == []          # nothing has streamed
    assert client.calls          # but the call was recorded, so compose ran

    gate.set()
    await task

    assert [type(event) for event in events] == [TextDelta, Completed]


async def test_an_already_set_gate_does_not_block():
    gate = asyncio.Event()
    gate.set()

    events = await drain(FakeLLMClient(gate=gate))

    assert isinstance(events[-1], Completed)


# --- embeddings -----------------------------------------------------------


async def test_embed_returns_a_locked_length_vector():
    vector = await FakeLLMClient().embed("HNSW trades recall for speed")

    assert len(vector) == EMBEDDING_DIMENSIONS == 1536
    assert all(isinstance(value, float) for value in vector)


async def test_embed_is_deterministic():
    text = "HNSW trades recall for speed"

    assert await FakeLLMClient().embed(text) == await FakeLLMClient().embed(text)


async def test_embed_vectors_are_normalised():
    vector = await FakeLLMClient().embed("recall and speed")

    assert sum(value * value for value in vector) == pytest.approx(1.0)


async def test_embed_records_what_it_was_asked_for():
    client = FakeLLMClient()

    await client.embed("first")
    await client.embed("second")

    assert client.embed_calls == ["first", "second"]


async def test_fail_on_embed_raises():
    """8.6's 'embedding service down' fallback needs a way to be triggered, and
    D6's test that retrieval degrades to plain decay depends on this."""
    client = FakeLLMClient(fail_on_embed=True)

    with pytest.raises(FakeLLMError):
        await client.embed("anything")


async def test_fail_on_embed_does_not_affect_generate():
    """The two services fail independently (8.6), so a broken embedder must
    still let generation run - that is the whole shape of the fallback."""
    client = FakeLLMClient(fail_on_embed=True)

    assert isinstance((await drain(client))[-1], Completed)


# --- the property D6's retrieval tests rest on ----------------------------


def cosine_distance(a, b):
    return 1.0 - sum(x * y for x, y in zip(a, b))


def test_similar_text_is_nearer_than_unrelated_text():
    """The fake's embeddings must preserve *some* similarity structure.

    A plain hash of the whole string would scatter near-identical sentences to
    unrelated points, and every D6 retrieval test would then be asserting on
    noise while looking like it worked. Word bucketing is the cheapest thing
    that makes 'the relevant ancestor is retrieved' a real claim.
    """
    query = fake_vector("how does ef_search affect recall")
    relevant = fake_vector("ef_search trades recall for latency at query time")
    unrelated = fake_vector("deployment uses a single container on Fly.io")

    assert cosine_distance(query, relevant) < cosine_distance(query, unrelated)


def test_identical_text_has_zero_distance():
    text = "ef_search trades recall for latency"

    assert cosine_distance(fake_vector(text), fake_vector(text)) == pytest.approx(0.0)


def test_empty_text_embeds_without_dividing_by_zero():
    vector = fake_vector("")

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert not any(vector)


async def test_embed_returns_exactly_what_fake_vector_builds():
    """Tests build corpus embeddings with fake_vector() and let the client embed
    the query. If those two ever diverge, retrieval tests would be comparing
    vectors from two different spaces - 8.2's model_used failure mode, in
    miniature, and passing tests would prove nothing."""
    text = "ef_search trades recall for latency"

    assert await FakeLLMClient().embed(text) == fake_vector(text)
