"""Scoring and report rendering.

Two families of number, kept apart on purpose:

* **Retrieval** — recall@k and MRR over the gold documents. Needs no LLM, so it
  runs anywhere and is what the regression gate uses.
* **Answer accuracy** — whether a synthesised answer is right. Needs a judge
  model, and is the number comparable with published LongMemEval results.

Reporting them separately matters because they are not interchangeable. A
system can retrieve the right document and still answer badly, and a report
that blurs the two invites exactly the vendor-favourable summary this benchmark
exists to avoid.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field

DEFAULT_KS = (1, 3, 5, 10)


@dataclass(frozen=True, slots=True)
class QueryOutcome:
    """What one question produced."""

    question_id: str
    category: str
    latency_s: float
    retrieved_doc_ids: tuple[str, ...]
    """Ordered best-first. Empty when retrieval returned nothing."""
    gold_doc_ids: tuple[str, ...]
    answer: str | None = None
    judged_correct: bool | None = None
    """None when no judge ran — never conflate "unjudged" with "wrong"."""
    used_tokens: int = 0
    error: str | None = None

    @property
    def first_gold_rank(self) -> int | None:
        """1-based rank of the first gold document, or None if absent."""
        gold = set(self.gold_doc_ids)
        for rank, doc_id in enumerate(self.retrieved_doc_ids, start=1):
            if doc_id in gold:
                return rank
        return None

    @property
    def scoreable(self) -> bool:
        """Retrieval metrics need ground truth; not every suite supplies it."""
        return bool(self.gold_doc_ids) and self.error is None


def recall_at_k(outcomes: list[QueryOutcome], k: int) -> float | None:
    """Fraction of scoreable questions with a gold document in the top k."""
    scoreable = [o for o in outcomes if o.scoreable]
    if not scoreable:
        return None
    hits = sum(1 for o in scoreable if (r := o.first_gold_rank) is not None and r <= k)
    return hits / len(scoreable)


def mrr(outcomes: list[QueryOutcome]) -> float | None:
    scoreable = [o for o in outcomes if o.scoreable]
    if not scoreable:
        return None
    total = sum(1.0 / r for o in scoreable if (r := o.first_gold_rank) is not None)
    return total / len(scoreable)


def accuracy(outcomes: list[QueryOutcome]) -> float | None:
    """Judged accuracy, or None when no judge ran."""
    judged = [o for o in outcomes if o.judged_correct is not None]
    if not judged:
        return None
    return sum(1 for o in judged if o.judged_correct) / len(judged)


def latency_percentiles(outcomes: list[QueryOutcome]) -> dict[str, float]:
    samples = sorted(o.latency_s for o in outcomes if o.error is None)
    if not samples:
        return {}

    def pct(p: float) -> float:
        # Nearest-rank; with a handful of samples an interpolated p99 invents
        # a number no query actually took.
        index = min(len(samples) - 1, max(0, round(p / 100 * len(samples)) - 1))
        return samples[index]

    return {
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "mean": statistics.fmean(samples),
        "max": samples[-1],
    }


@dataclass(frozen=True, slots=True)
class RunReport:
    suite: str
    mode: str
    instances: int
    questions: int
    corpus_fingerprint: str
    recall: dict[str, float | None] = field(default_factory=dict)
    mrr: float | None = None
    accuracy: float | None = None
    judge: str = "none"
    latency: dict[str, float] = field(default_factory=dict)
    total_tokens: int = 0
    errors: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def summarise(
    *,
    suite: str,
    mode: str,
    instances: int,
    corpus_fingerprint: str,
    outcomes: list[QueryOutcome],
    judge: str = "none",
    ks: tuple[int, ...] = DEFAULT_KS,
) -> RunReport:
    notes: list[str] = []
    if not any(o.scoreable for o in outcomes):
        notes.append(
            "No gold documents in this suite — retrieval metrics are unavailable, "
            "only latency was measured."
        )
    if judge == "none":
        notes.append(
            "No judge configured: accuracy was not measured. Retrieval metrics say "
            "whether the right memory came back, not whether the answer was right."
        )
    total_tokens = sum(o.used_tokens for o in outcomes)
    if total_tokens == 0 and mode == "agentic":
        notes.append(
            "Token usage reported as 0: recall responses do not carry a `usage` "
            "field yet (see issue #12). Cost per query cannot be derived from this run."
        )
    errors = sum(1 for o in outcomes if o.error)
    if errors:
        notes.append(f"{errors} question(s) errored and are excluded from every metric.")

    return RunReport(
        suite=suite,
        mode=mode,
        instances=instances,
        questions=len(outcomes),
        corpus_fingerprint=corpus_fingerprint,
        recall={f"recall@{k}": recall_at_k(outcomes, k) for k in ks},
        mrr=mrr(outcomes),
        accuracy=accuracy(outcomes),
        judge=judge,
        latency=latency_percentiles(outcomes),
        total_tokens=total_tokens,
        errors=errors,
        notes=notes,
    )


def _fmt(value: float | None, spec: str = ".3f") -> str:
    return "—" if value is None else format(value, spec)


def render_markdown(reports: list[RunReport], *, command: str) -> str:
    """A table that states what was measured and what was not."""
    if not reports:
        return "_No results._\n"

    ks = sorted({int(key.split("@")[1]) for r in reports for key in r.recall})
    header = (
        ["mode", "questions"]
        + [f"recall@{k}" for k in ks]
        + ["MRR", "accuracy", "p50 (s)", "p95 (s)", "p99 (s)"]
    )
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in reports:
        row = (
            [r.mode, str(r.questions)]
            + [_fmt(r.recall.get(f"recall@{k}")) for k in ks]
            + [
                _fmt(r.mrr),
                _fmt(r.accuracy),
                _fmt(r.latency.get("p50")),
                _fmt(r.latency.get("p95")),
                _fmt(r.latency.get("p99")),
            ]
        )
        lines.append("| " + " | ".join(row) + " |")

    first = reports[0]
    lines += [
        "",
        f"Suite `{first.suite}` · {first.instances} instance(s) · "
        f"corpus `{first.corpus_fingerprint}` · judge `{first.judge}`",
        "",
        "Reproduce:",
        "",
        "```bash",
        command,
        "```",
    ]

    seen: list[str] = []
    for r in reports:
        for note in r.notes:
            if note not in seen:
                seen.append(note)
    if seen:
        lines += ["", "**Caveats**", ""]
        lines += [f"- {n}" for n in seen]
    return "\n".join(lines) + "\n"
