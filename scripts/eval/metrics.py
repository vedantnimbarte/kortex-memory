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
    cost_usd: float | None = None
    """None means unpriced (no KORTEX_LLM_PRICES), never free."""
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
    total_cost_usd: float | None = None
    budget_ms: int = 0
    """The latency ceiling this run was given; 0 means unbounded."""
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
    budget_ms: int = 0,
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
            "Agentic mode reported 0 tokens. Recall does report `usage`, so this "
            "means the planner never ran — check whether an LLM is configured, or "
            "whether a latency/token budget forced the hybrid path."
        )
    priced = [o.cost_usd for o in outcomes if o.cost_usd is not None]
    if mode.startswith("agentic") and not priced:
        notes.append(
            "Cost was not measured: the configured model has no price in KORTEX_LLM_PRICES. "
            "Null means unpriced, not free — an agentic run always spends tokens."
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
        total_cost_usd=sum(priced) if priced else None,
        budget_ms=budget_ms,
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


# --- the frontier ------------------------------------------------------------

SMALL_SAMPLE = 30
"""Below this many scoreable questions, a frontier verdict is a coin flip
dressed as a finding."""


@dataclass(frozen=True, slots=True)
class Frontier:
    """Whether agentic recall is worth what it costs, at each budget measured.

    WU-2.6 turns on a specific decision — *if agentic still loses to plain
    hybrid, say so publicly and demote it to an opt-in mode* — and that
    decision needs a curve, not two dots. One agentic run at one latency says
    nothing about whether the mode is bad or merely under-budgeted.

    Computed rather than eyeballed, because the temptation at the moment of
    reading a disappointing table is to find a reason it does not count.
    """

    metric: str
    baseline: float | None
    baseline_p95: float
    points: tuple[tuple[int, float | None, float], ...]
    """(budget_ms, score, p95) per agentic run, ascending by budget."""
    verdict: str
    demote: bool
    """True when the evidence says agentic should not be the default."""

    def as_dict(self) -> dict:
        return asdict(self)


def _comparable_metric(reports: list[RunReport]) -> str:
    """Accuracy when a judge ran, otherwise the largest recall@k available.

    Never mixes the two across modes: comparing agentic's accuracy against
    hybrid's recall is the arithmetic version of a vendor-favourable chart.
    """
    if any(r.accuracy is not None for r in reports):
        return "accuracy"
    ks = sorted({int(key.split("@")[1]) for r in reports for key in r.recall})
    return f"recall@{ks[-1]}" if ks else "accuracy"


def _score(report: RunReport, metric: str) -> float | None:
    return report.accuracy if metric == "accuracy" else report.recall.get(metric)


def frontier(reports: list[RunReport]) -> Frontier | None:
    """Compare every agentic run against the hybrid baseline. None if either side
    is missing — a frontier needs both, and inventing one is worse than saying
    it was not measured."""
    hybrid = next((r for r in reports if r.mode == "hybrid"), None)
    agentic = sorted(
        (r for r in reports if r.mode.startswith("agentic")), key=lambda r: r.budget_ms
    )
    if hybrid is None or not agentic:
        return None

    metric = _comparable_metric(reports)
    baseline = _score(hybrid, metric)
    baseline_p95 = hybrid.latency.get("p95", 0.0)
    points = tuple((r.budget_ms, _score(r, metric), r.latency.get("p95", 0.0)) for r in agentic)

    if baseline is None:
        return Frontier(
            metric=metric,
            baseline=None,
            baseline_p95=baseline_p95,
            points=points,
            verdict=(
                f"Not decidable: hybrid has no {metric} to compare against. "
                "This suite carries no ground truth, so only latency was measured."
            ),
            demote=False,
        )

    wins = [(b, s, p) for b, s, p in points if s is not None and s > baseline]
    scored = [(b, s, p) for b, s, p in points if s is not None]
    if not scored:
        return Frontier(
            metric=metric,
            baseline=baseline,
            baseline_p95=baseline_p95,
            points=points,
            verdict=f"Not decidable: no agentic run produced a {metric}.",
            demote=False,
        )

    caveat = ""
    if hybrid.questions < SMALL_SAMPLE:
        caveat = (
            f" On {hybrid.questions} questions this is indicative, not conclusive — "
            f"re-run with at least {SMALL_SAMPLE} before acting on it."
        )

    if not wins:
        best_budget, best_score, _ = max(scored, key=lambda point: point[1] or 0.0)
        return Frontier(
            metric=metric,
            baseline=baseline,
            baseline_p95=baseline_p95,
            points=points,
            verdict=(
                f"**Agentic recall did not beat plain hybrid at any budget measured.** "
                f"Hybrid {metric}={baseline:.3f}; agentic peaked at {best_score:.3f} "
                f"({best_budget or 'unbounded'} ms). Per WU-2.6 the finding is published "
                f"as it stands and agentic is demoted to opt-in: "
                f"`KORTEX_AGENTIC_RETRIEVAL=false`.{caveat}"
            ),
            demote=True,
        )

    cheapest_win = min(wins, key=lambda point: point[0] or 10**9)
    budget, score, p95 = cheapest_win
    cost = f"{p95 / baseline_p95:.1f}x" if baseline_p95 else "an unmeasured multiple of"
    if len(wins) == len(scored):
        where = "at every budget measured"
    else:
        where = f"only at budgets from {budget or 'unbounded'} ms"
    return Frontier(
        metric=metric,
        baseline=baseline,
        baseline_p95=baseline_p95,
        points=points,
        verdict=(
            f"Agentic recall beat plain hybrid {where}: {metric} {baseline:.3f} → "
            f"{score:.3f}, for {cost} the p95 latency. Keeping it as the default is "
            f"defensible on this evidence.{caveat}"
        ),
        demote=False,
    )


def render_frontier(front: Frontier | None) -> str:
    """The frontier as a table plus the verdict sentence."""
    if front is None:
        return (
            "\n**Frontier:** not measured — needs a `hybrid` run and at least one "
            "`agentic` run over the same corpus.\n"
        )
    lines = [
        "",
        "**Accuracy-vs-latency frontier**",
        "",
        f"| budget (ms) | {front.metric} | p95 (s) | vs hybrid |",
        "|---|---|---|---|",
    ]
    base = front.baseline
    lines.append(f"| — (hybrid) | {_fmt(base)} | {_fmt(front.baseline_p95, '.2f')} | baseline |")
    for budget, score, p95 in front.points:
        delta = "—" if score is None or base is None else f"{score - base:+.3f}"
        lines.append(f"| {budget or 'unbounded'} | {_fmt(score)} | {_fmt(p95, '.2f')} | {delta} |")
    lines += ["", front.verdict, ""]
    return "\n".join(lines)
