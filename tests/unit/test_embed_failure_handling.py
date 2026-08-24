"""Write-path integrity: no memory is silently left out of vector search.

The behaviour under test is the one that destroys trust in a memory product —
`remember` returns 201, the embedding quietly fails, and the memory is absent
from every future recall with nothing to say so. These tests pin the three
guarantees that prevent it: a failed batch does not take good memories down
with it, every failure is counted and backed off, and an exhausted memory is
parked visibly rather than retried forever.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pytest
from kortex_core.embeddings.protocol import EmbeddingError
from kortex_core.embeddings.retry import MAX_BACKOFF_SECONDS, decide_retry
from kortex_worker.tasks.embedding import _embed_one_by_one, _text_of

MAX_ATTEMPTS = 5
RETRY_BASE = 60


@dataclass
class FakeMemory:
    id: int
    org_id: int = 1
    title: str = ""
    body: str = "b"
    embed_attempts: int = 0
    embed_error: str | None = None
    embed_failed_at: dt.datetime | None = None
    embed_next_attempt_at: dt.datetime | None = None
    embedding: list[float] | None = None
    embedding_model: str | None = None

    @property
    def embedding_state(self) -> str:
        if self.embedding is not None:
            return "ok"
        return "failed" if self.embed_failed_at is not None else "pending"


@dataclass
class FakeRepo:
    """Stands in for MemoryRepository, mirroring `record_embed_failure`'s rules."""

    memories: dict[int, FakeMemory] = field(default_factory=dict)
    embedded: list[int] = field(default_factory=list)

    async def set_embedding(self, memory_id: int, vector: list[float], model_id: str) -> None:
        memory = self.memories[memory_id]
        memory.embedding = vector
        memory.embedding_model = model_id
        memory.embed_attempts = 0
        memory.embed_error = None
        memory.embed_failed_at = None
        memory.embed_next_attempt_at = None
        self.embedded.append(memory_id)

    async def record_embed_failure(
        self,
        memory_ids: list[int],
        *,
        error: str,
        max_attempts: int,
        retry_base_seconds: int,
    ) -> int:
        """Mirrors MemoryRepository.record_embed_failure, delegating the actual
        rule to the same ``decide_retry`` the repository uses."""
        now = dt.datetime.now(tz=dt.UTC)
        failed = 0
        for mid in memory_ids:
            memory = self.memories[mid]
            decision = decide_retry(
                memory.embed_attempts,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
                now=now,
            )
            memory.embed_attempts = decision.attempts
            memory.embed_error = error[:2000]
            memory.embed_next_attempt_at = decision.next_attempt_at
            if decision.parked:
                memory.embed_failed_at = now
                failed += 1
        return failed


class FakeEmbedder:
    """Fails for any text containing ``poison``; succeeds otherwise."""

    model_id = "test-model"
    dim = 3

    def __init__(self, poison: str | None = "poison"):
        self._poison = poison
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self._poison and any(self._poison in t for t in texts):
            raise EmbeddingError("provider rejected input")
        return [[0.1, 0.2, 0.3] for _ in texts]


def _repo(*memories: FakeMemory) -> FakeRepo:
    return FakeRepo(memories={m.id: m for m in memories})


# --- batch isolation ---------------------------------------------------------


async def test_one_bad_input_does_not_lose_the_rest_of_the_batch() -> None:
    """The mem0 #5245 failure mode: a partial batch failure dropping everything."""
    good_a, bad, good_b = FakeMemory(1, body="fine"), FakeMemory(2, body="poison"), FakeMemory(3)
    repo = _repo(good_a, bad, good_b)

    embedded, retrying, parked = await _embed_one_by_one(
        repo, FakeEmbedder(), [good_a, bad, good_b]
    )

    assert (embedded, retrying, parked) == (2, 1, 0)
    assert repo.embedded == [1, 3]
    assert good_a.embedding_state == "ok"
    assert good_b.embedding_state == "ok"
    # The bad one is *retrying*, not lost and not silently dropped.
    assert bad.embedding_state == "pending"
    assert bad.embed_attempts == 1
    assert bad.embed_error == "provider rejected input"


async def test_every_failure_is_recorded_with_its_reason() -> None:
    memory = FakeMemory(1, body="poison")
    repo = _repo(memory)
    await _embed_one_by_one(repo, FakeEmbedder(), [memory])
    assert memory.embed_error  # never fails without saying why
    assert memory.embed_next_attempt_at is not None


# --- retry budget and backoff ------------------------------------------------


async def test_attempts_are_parked_once_exhausted() -> None:
    memory = FakeMemory(1, body="poison")
    repo = _repo(memory)
    embedder = FakeEmbedder()

    for attempt in range(1, MAX_ATTEMPTS):
        await _embed_one_by_one(repo, embedder, [memory])
        assert memory.embedding_state == "pending", f"parked too early at attempt {attempt}"

    _, _, parked = await _embed_one_by_one(repo, embedder, [memory])
    assert parked == 1
    assert memory.embedding_state == "failed"
    assert memory.embed_failed_at is not None
    # Parked means *stop*, not "retry with a longer wait".
    assert memory.embed_next_attempt_at is None


@pytest.mark.parametrize(
    ("attempts_before", "expected_delay"),
    [(0, 60), (1, 120), (2, 240), (3, 480)],
)
async def test_backoff_doubles_each_attempt(attempts_before: int, expected_delay: int) -> None:
    memory = FakeMemory(1, body="poison", embed_attempts=attempts_before)
    repo = _repo(memory)
    before = dt.datetime.now(tz=dt.UTC)
    await _embed_one_by_one(repo, FakeEmbedder(), [memory])
    assert memory.embed_next_attempt_at is not None
    delay = (memory.embed_next_attempt_at - before).total_seconds()
    assert expected_delay - 5 <= delay <= expected_delay + 5


def test_backoff_is_capped_at_an_hour() -> None:
    """Without a cap, attempt 20 would schedule a retry decades out."""
    now = dt.datetime.now(tz=dt.UTC)
    decision = decide_retry(19, max_attempts=100, retry_base_seconds=RETRY_BASE, now=now)
    assert decision.next_attempt_at is not None
    assert (decision.next_attempt_at - now).total_seconds() == MAX_BACKOFF_SECONDS


def test_parked_decision_carries_no_next_attempt() -> None:
    """Parked means stop. A next_attempt_at here would resurrect it forever."""
    decision = decide_retry(
        MAX_ATTEMPTS - 1,
        max_attempts=MAX_ATTEMPTS,
        retry_base_seconds=RETRY_BASE,
        now=dt.datetime.now(tz=dt.UTC),
    )
    assert decision.parked
    assert decision.next_attempt_at is None
    assert decision.attempts == MAX_ATTEMPTS


# --- recovery ----------------------------------------------------------------


async def test_success_clears_prior_failure_state() -> None:
    """A memory that recovers must not stay flagged, or the alert never clears."""
    memory = FakeMemory(
        1,
        body="fine",
        embed_attempts=3,
        embed_error="old failure",
        embed_next_attempt_at=dt.datetime.now(tz=dt.UTC),
    )
    repo = _repo(memory)
    await _embed_one_by_one(repo, FakeEmbedder(), [memory])
    assert memory.embedding_state == "ok"
    assert memory.embed_attempts == 0
    assert memory.embed_error is None
    assert memory.embed_next_attempt_at is None


async def test_all_good_batch_embeds_everything() -> None:
    memories = [FakeMemory(i, body=f"body {i}") for i in range(1, 4)]
    repo = _repo(*memories)
    embedded, retrying, parked = await _embed_one_by_one(repo, FakeEmbedder(), memories)
    assert (embedded, retrying, parked) == (3, 0, 0)
    assert all(m.embedding_state == "ok" for m in memories)


# --- state derivation --------------------------------------------------------


def test_embedding_state_answers_is_this_searchable() -> None:
    assert FakeMemory(1).embedding_state == "pending"
    assert FakeMemory(2, embedding=[0.1]).embedding_state == "ok"
    assert FakeMemory(3, embed_failed_at=dt.datetime.now(tz=dt.UTC)).embedding_state == "failed"
    # A parked memory that later succeeds reads as ok, not failed.
    recovered = FakeMemory(4, embedding=[0.1], embed_failed_at=dt.datetime.now(tz=dt.UTC))
    assert recovered.embedding_state == "ok"


def test_text_of_prefers_title_and_body_together() -> None:
    assert _text_of(FakeMemory(1, title="T", body="B")) == "T\nB"  # type: ignore[arg-type]
    assert _text_of(FakeMemory(2, title="", body="B")) == "B"  # type: ignore[arg-type]
