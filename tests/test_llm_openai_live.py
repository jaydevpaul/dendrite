"""The one test that costs money. Skipped unless you ask for it.

Gated on its own env var rather than on the key being present, so that adding
the key to .env does not quietly make every pytest run bill you:

    DENDRITE_LIVE_LLM=1 .venv/Scripts/python.exe -m pytest tests/test_llm_openai_live.py -q

Two calls, both deliberately tiny - a one-word reply and a three-word
embedding. Everything else about this client is covered offline against a
stub; what only the real API can tell us is whether the wire format is what we
think it is, and whether the model ids in config exist on this account.
"""

import os

import pytest

from app.core.config import settings
from app.llm.base import EMBEDDING_DIMENSIONS, Completed, TextDelta
from app.llm.base import PromptMessage
from app.llm.openai_client import OpenAIClient

pytestmark = pytest.mark.skipif(
    os.environ.get("DENDRITE_LIVE_LLM") != "1",
    reason="live API test - set DENDRITE_LIVE_LLM=1 to spend real money on it",
)


@pytest.fixture(scope="module")
def live_client():
    if not settings.llm_api_key:
        pytest.fail("DENDRITE_LLM_API_KEY is not set")
    return OpenAIClient()


async def test_generate_streams_and_reports_provider_usage(live_client):
    events = [
        event
        async for event in live_client.generate(
            "Answer in one word. No punctuation.",
            [PromptMessage(role="user", content="Which planet do we live on?")],
        )
    ]

    completed = events[-1]
    assert isinstance(completed, Completed)
    assert all(isinstance(event, TextDelta) for event in events[:-1])

    # Exactly one terminal event, whatever the provider did in between.
    assert sum(isinstance(event, Completed) for event in events) == 1

    assert completed.text.strip(), "the model returned nothing"

    # The whole point of stream_options: without it these are both None and
    # every Generation row lands with null counts.
    assert completed.input_tokens is not None
    assert completed.output_tokens is not None
    assert completed.model

    print(
        f"\nmodel={completed.model} in={completed.input_tokens} "
        f"out={completed.output_tokens} text={completed.text.strip()!r}"
    )


async def test_embed_returns_the_locked_width(live_client):
    vector = await live_client.embed("dendrite branches from a span")

    assert len(vector) == EMBEDDING_DIMENSIONS
    assert any(vector), "an all-zero vector means the response was not read"
