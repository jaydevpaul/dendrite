"""The fake behind the seam - no network, no key, no spend.

This is the assertion surface for every composition test in C2-C6: `calls` is
the only proof that a strategy composed what it claims to have composed. If it
records the wrong thing, those tests assert on nothing while passing.
"""

import asyncio
import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass,field


from app.llm.base import EMBEDDING_DIMENSIONS, Completed, PromptMessage, TextDelta



__all__ = [
    "EMBEDDING_DIMENSIONS",
    "FakeLLMClient",
    "FakeLLMError",
    "RecordedCall",
    "fake_vector",
]

_WORD = re.compile(r"[a-z0-9_]+")

DEFAULT_CHUNKS = ["A fake reply", " in two parts."]
DEFAULT_MODEL = "fake-model"

class FakeLLMError(Exception):
    """A scripted provider failure - 8.6's 'embedding service down' and the
    mid-stream failure D9's failure path has to write a Generation row for."""


@dataclass(frozen=True)
class RecordedCall:
    system: str
    messages: list[PromptMessage]


def _count_tokens(text: str) -> int:
    """Words, not real tokens. Deterministic is the only property tests need;
    the real client reports the provider's billed `usage` (8.15 D12)."""
    return len(text.split())


def fake_vector(text: str) -> list[float]:
    """A deterministic embedding that keeps *some* similarity structure.

    Each word is bucketed into one dimension and the vector is L2-normalised,
    so shared vocabulary really does mean smaller cosine distance. A hash of
    the whole string would scatter near-identical sentences to unrelated
    points, and every D6 retrieval test would then be asserting on noise while
    looking like it worked.

    blake2b rather than the builtin hash(): str hashing is salted per process
    (PYTHONHASHSEED), so builtin hash() would not survive a second pytest run.
    """
    vector = [0.0] * EMBEDDING_DIMENSIONS

    for word in _WORD.findall(text.lower()):
        digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
        vector[int.from_bytes(digest, "big") % EMBEDDING_DIMENSIONS] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:                      # empty or wordless text - all zeros
        return vector

    return [value / norm for value in vector]


@dataclass
class FakeLLMClient:
    """Satisfies LLMClient. Scripts a stream exactly, including failing partway
    through, and records everything it was handed."""

    chunks: Sequence[str] | None = None
    model: str = DEFAULT_MODEL
    gate: asyncio.Event | None = None
    fail_after_chunk: int | None = None
    fail_on_embed: bool = False

    calls: list[RecordedCall] = field(default_factory=list)
    embed_calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # `is None`, not `or`: chunks=[] is a legal script - a model may return
        # nothing, and the route must still get a Completed to write.
        if self.chunks is None:
            self.chunks = list(DEFAULT_CHUNKS)

    def _fail_if_due(self, chunks_sent: int) -> None:
        if self.fail_after_chunk is not None and chunks_sent >= self.fail_after_chunk:
            raise FakeLLMError(f"scripted failure after {chunks_sent} chunk(s)")

    async def generate(self, system: str, messages: Sequence[PromptMessage]):
        # Recorded first, before the gate and before any failure: D9 writes
        # composed_context even for a failed generation, so the prompt must
        # already be on record when the failure lands.
        #
        # list() is load-bearing. A composer that builds one list and reuses it
        # would otherwise leave every recorded call pointing at the same final
        # state, and per-strategy tests would pass no matter what ran.
        self.calls.append(RecordedCall(system=system, messages=list(messages)))

        if self.gate is not None:
            await self.gate.wait()

        text = ""
        for index, chunk in enumerate(self.chunks):
            self._fail_if_due(index)
            text += chunk
            yield TextDelta(text=chunk)
            await asyncio.sleep(0)     # let other tasks observe the pending row
        self._fail_if_due(len(self.chunks))

        prompt_text = " ".join([system, *(message.content for message in messages)])
        yield Completed(
            text=text,
            input_tokens=_count_tokens(prompt_text),
            output_tokens=_count_tokens(text),
            model=self.model,
        )



    async def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)

        # Independent of generate() on purpose: 8.6 falls back to plain decay
        # when embeddings are down, which only means anything if generation
        # still runs.
        if self.fail_on_embed:
            raise FakeLLMError("scripted embedding failure")

        return fake_vector(text)