"""Benchmark suite loaders, normalised onto one shape.

Every suite reduces to the same thing: a *haystack* of documents to remember,
and questions whose answers live in known documents. That shared shape is what
lets one runner measure LongMemEval, LoCoMo and a synthetic smoke suite
without special-casing any of them downstream.

The third-party loaders validate the schema they expect and fail loudly naming
the keys they wanted. These datasets are versioned by their authors and do
drift; a loud failure is a one-line fix, while silently reading `.get(...)` into
empty strings produces a benchmark that runs to completion and reports numbers
that mean nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SUITES = ("longmemeval", "locomo", "synthetic")


@dataclass(frozen=True, slots=True)
class Document:
    """One unit of the haystack. Becomes exactly one Kortex memory."""

    doc_id: str
    title: str
    body: str
    timestamp: str | None = None


@dataclass(frozen=True, slots=True)
class Question:
    question_id: str
    question: str
    answer: str
    gold_doc_ids: tuple[str, ...]
    """Documents that actually contain the answer — the retrieval ground truth."""
    category: str = ""


@dataclass(frozen=True, slots=True)
class EvalInstance:
    """A haystack plus the questions asked over it.

    One instance is one isolated Kortex scope, so instances never contaminate
    each other's retrieval.
    """

    instance_id: str
    documents: tuple[Document, ...]
    questions: tuple[Question, ...]

    @property
    def total_chars(self) -> int:
        return sum(len(d.body) for d in self.documents)


class DatasetError(Exception):
    """Raised when a dataset file is missing or does not match the expected schema."""


def _require(obj: dict, keys: tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise DatasetError(
            f"{where}: missing key(s) {missing}. "
            f"Present keys: {sorted(obj)[:12]}. "
            "The loader targets the upstream schema documented in scripts/eval/README.md; "
            "if the dataset has changed, adjust the loader rather than making it tolerant."
        )


def _render_turns(turns: list[dict]) -> str:
    """Flatten a chat session into the text a memory will hold."""
    lines = []
    for turn in turns:
        role = turn.get("role") or turn.get("speaker") or "unknown"
        content = turn.get("content") or turn.get("text") or ""
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


# --- LongMemEval ------------------------------------------------------------


def load_longmemeval(path: Path) -> Iterator[EvalInstance]:
    """LongMemEval / LongMemEval-V2.

    One question per item, each over its own haystack of chat sessions, so one
    item becomes one instance. See scripts/eval/README.md for where to get the
    file and which variant to use.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise DatasetError(f"{path}: expected a JSON list of questions, got {type(raw).__name__}")

    for index, item in enumerate(raw):
        where = f"{path.name}[{index}]"
        _require(item, ("question_id", "question", "answer", "haystack_sessions"), where)

        sessions = item["haystack_sessions"]
        session_ids = item.get("haystack_session_ids") or [
            f"{item['question_id']}-s{i}" for i in range(len(sessions))
        ]
        dates = item.get("haystack_dates") or [None] * len(sessions)
        if len(session_ids) != len(sessions):
            raise DatasetError(
                f"{where}: {len(sessions)} sessions but {len(session_ids)} session ids"
            )

        documents = tuple(
            Document(
                doc_id=str(sid),
                title=f"session {sid}",
                body=_render_turns(turns),
                timestamp=str(date) if date else None,
            )
            for sid, turns, date in zip(session_ids, sessions, dates, strict=True)
        )
        gold = tuple(str(s) for s in (item.get("answer_session_ids") or ()))
        yield EvalInstance(
            instance_id=str(item["question_id"]),
            documents=documents,
            questions=(
                Question(
                    question_id=str(item["question_id"]),
                    question=str(item["question"]),
                    answer=str(item["answer"]),
                    gold_doc_ids=gold,
                    category=str(item.get("question_type", "")),
                ),
            ),
        )


# --- LoCoMo -----------------------------------------------------------------


def load_locomo(path: Path) -> Iterator[EvalInstance]:
    """LoCoMo: long multi-session conversations with many QA pairs each.

    Sessions live under ``conversation`` as ``session_N`` keys, so one
    conversation becomes one instance carrying all of its questions.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise DatasetError(f"{path}: expected a JSON list of samples, got {type(raw).__name__}")

    for index, sample in enumerate(raw):
        where = f"{path.name}[{index}]"
        _require(sample, ("conversation", "qa"), where)
        conversation = sample["conversation"]
        sample_id = str(sample.get("sample_id", index))

        documents = []
        for key in sorted(k for k in conversation if k.startswith("session_")):
            if key.endswith("_date_time"):
                continue
            turns = conversation[key]
            if not isinstance(turns, list):
                continue
            documents.append(
                Document(
                    doc_id=f"{sample_id}:{key}",
                    title=f"{sample_id} {key}",
                    body=_render_turns(turns),
                    timestamp=conversation.get(f"{key}_date_time"),
                )
            )
        if not documents:
            raise DatasetError(f"{where}: no session_N lists found under `conversation`")

        questions = []
        for q_index, qa in enumerate(sample["qa"]):
            _require(qa, ("question",), f"{where}.qa[{q_index}]")
            # LoCoMo evidence points at turns; we score at session granularity,
            # which is the unit actually stored as a memory.
            evidence = qa.get("evidence") or []
            gold = tuple(
                d.doc_id
                for d in documents
                if any(str(e).split(":")[0] in d.doc_id for e in evidence)
            )
            questions.append(
                Question(
                    question_id=f"{sample_id}:q{q_index}",
                    question=str(qa["question"]),
                    answer=str(qa.get("answer", "")),
                    gold_doc_ids=gold,
                    category=str(qa.get("category", "")),
                )
            )
        yield EvalInstance(
            instance_id=sample_id,
            documents=tuple(documents),
            questions=tuple(questions),
        )


# --- Synthetic --------------------------------------------------------------

_TOPICS = (
    ("job queue", "Celery with Redis as the broker"),
    ("primary datastore", "Postgres 16 with pgvector"),
    ("deployment target", "Kubernetes via the Helm chart"),
    ("cache eviction", "an LRU with a five minute TTL"),
    ("auth mechanism", "scoped API keys hashed with argon2id"),
    ("log format", "structured JSON shipped to the collector"),
    ("test database", "testcontainers spinning up a real Postgres"),
    ("embedding model", "BAAI bge-large-en at 1024 dimensions"),
    ("rate limit strategy", "a Redis token bucket per org"),
    ("blob storage", "S3 in production and the filesystem locally"),
)

_DISTRACTOR = (
    "The team debated {topic} at length during the offsite and agreed to "
    "revisit it next quarter. No decision was recorded at the time, and the "
    "notes from that session were never circulated."
)


def load_synthetic(count: int = 50, haystack_size: int = 40) -> Iterator[EvalInstance]:
    """A deterministic suite that needs no download.

    This measures the *plumbing* — ingest, embed, retrieve, rank — not real
    long-context memory quality. Its job is to be a regression gate that runs
    anywhere, so a change that breaks retrieval fails fast without waiting on a
    115M-token corpus. Never publish these numbers as a benchmark result.
    """
    for i in range(count):
        topic, answer = _TOPICS[i % len(_TOPICS)]
        gold_id = f"syn-{i}-gold"
        documents = [
            Document(
                doc_id=gold_id,
                title=f"decision {i}: {topic}",
                body=(
                    f"After the migration review we settled the question of {topic}. "
                    f"We use {answer}. This is the current state and supersedes the "
                    f"earlier discussion."
                ),
            )
        ]
        for j in range(haystack_size):
            other, _ = _TOPICS[(i + j + 1) % len(_TOPICS)]
            documents.append(
                Document(
                    doc_id=f"syn-{i}-noise-{j}",
                    title=f"note {i}.{j}",
                    body=_DISTRACTOR.format(topic=other),
                )
            )
        yield EvalInstance(
            instance_id=f"syn-{i}",
            documents=tuple(documents),
            questions=(
                Question(
                    question_id=f"syn-{i}-q",
                    question=f"What did we decide about the {topic}?",
                    answer=answer,
                    gold_doc_ids=(gold_id,),
                    category="synthetic-single-hop",
                ),
            ),
        )


# --- dispatch ---------------------------------------------------------------


def load(suite: str, path: Path | None, *, count: int = 50) -> list[EvalInstance]:
    # Validate the suite name before anything else: a typo used to be reported
    # as "needs --data", sending people to find a file for a suite that does
    # not exist.
    if suite not in SUITES:
        raise DatasetError(f"unknown suite {suite!r}; expected one of {SUITES}")
    if suite == "synthetic":
        return list(load_synthetic(count=count))
    if path is None:
        raise DatasetError(f"suite {suite!r} needs --data pointing at the downloaded file")
    if not path.exists():
        raise DatasetError(f"{path} does not exist — see scripts/eval/README.md for downloads")
    if suite == "longmemeval":
        return list(load_longmemeval(path))
    return list(load_locomo(path))


def fingerprint(instances: list[EvalInstance]) -> str:
    """Stable id for the exact corpus scored, so results state what they measured."""
    digest = hashlib.sha256()
    for instance in instances:
        digest.update(instance.instance_id.encode())
        for q in instance.questions:
            digest.update(q.question_id.encode())
    return digest.hexdigest()[:12]
