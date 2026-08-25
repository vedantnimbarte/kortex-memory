"""Benchmark scoring.

These numbers are the ones that would go in a README, so the arithmetic has to
be right and the distinction between "not measured" and "zero" has to hold.
Reporting an unjudged run as 0% accuracy, or counting an errored query as a
retrieval miss, both understate the system in ways nobody would catch by
eyeballing a table.
"""

from __future__ import annotations

import pytest

from scripts.eval.datasets import DatasetError, load, load_synthetic
from scripts.eval.metrics import (
    QueryOutcome,
    accuracy,
    latency_percentiles,
    mrr,
    recall_at_k,
    render_markdown,
    summarise,
)


def _outcome(
    qid: str = "q",
    retrieved: tuple[str, ...] = (),
    gold: tuple[str, ...] = ("gold",),
    latency: float = 0.1,
    judged: bool | None = None,
    error: str | None = None,
    tokens: int = 0,
) -> QueryOutcome:
    return QueryOutcome(
        question_id=qid,
        category="",
        latency_s=latency,
        retrieved_doc_ids=retrieved,
        gold_doc_ids=gold,
        judged_correct=judged,
        used_tokens=tokens,
        error=error,
    )


# --- rank ---


@pytest.mark.parametrize(
    ("retrieved", "expected"),
    [
        (("gold", "a", "b"), 1),
        (("a", "gold", "b"), 2),
        (("a", "b", "c"), None),
        ((), None),
    ],
)
def test_first_gold_rank_is_one_based(retrieved: tuple[str, ...], expected: int | None) -> None:
    assert _outcome(retrieved=retrieved).first_gold_rank == expected


def test_rank_finds_any_gold_document() -> None:
    outcome = _outcome(retrieved=("a", "g2"), gold=("g1", "g2"))
    assert outcome.first_gold_rank == 2


# --- recall@k ---


def test_recall_at_k_counts_hits_within_k() -> None:
    outcomes = [
        _outcome("a", retrieved=("gold",)),  # rank 1
        _outcome("b", retrieved=("x", "y", "gold")),  # rank 3
        _outcome("c", retrieved=("x", "y", "z")),  # miss
    ]
    assert recall_at_k(outcomes, 1) == pytest.approx(1 / 3)
    assert recall_at_k(outcomes, 3) == pytest.approx(2 / 3)
    assert recall_at_k(outcomes, 10) == pytest.approx(2 / 3)


def test_errored_queries_are_excluded_not_counted_as_misses() -> None:
    """An unreachable API is not the same as bad retrieval."""
    outcomes = [_outcome("a", retrieved=("gold",)), _outcome("b", error="connection refused")]
    assert recall_at_k(outcomes, 5) == 1.0


def test_questions_without_ground_truth_are_excluded() -> None:
    outcomes = [_outcome("a", retrieved=("gold",)), _outcome("b", retrieved=("x",), gold=())]
    assert recall_at_k(outcomes, 5) == 1.0


def test_recall_is_none_when_nothing_is_scoreable() -> None:
    """None means "not measured" — a caller must not render it as 0.0."""
    assert recall_at_k([_outcome(gold=())], 5) is None
    assert recall_at_k([], 5) is None


# --- MRR ---


def test_mrr_averages_reciprocal_ranks() -> None:
    outcomes = [
        _outcome("a", retrieved=("gold",)),  # 1/1
        _outcome("b", retrieved=("x", "gold")),  # 1/2
        _outcome("c", retrieved=("x",)),  # 0
    ]
    assert mrr(outcomes) == pytest.approx((1.0 + 0.5 + 0.0) / 3)


def test_mrr_is_none_without_ground_truth() -> None:
    assert mrr([_outcome(gold=())]) is None


# --- accuracy ---


def test_accuracy_counts_only_judged_answers() -> None:
    outcomes = [
        _outcome("a", judged=True),
        _outcome("b", judged=False),
        _outcome("c", judged=None),  # unjudged: must not drag accuracy down
    ]
    assert accuracy(outcomes) == pytest.approx(0.5)


def test_unjudged_run_reports_none_not_zero() -> None:
    assert accuracy([_outcome("a"), _outcome("b")]) is None


# --- latency ---


def test_percentiles_use_observed_samples() -> None:
    outcomes = [_outcome(str(i), latency=float(i)) for i in range(1, 101)]
    p = latency_percentiles(outcomes)
    assert p["p50"] == 50.0
    assert p["p95"] == 95.0
    assert p["p99"] == 99.0
    assert p["max"] == 100.0


def test_percentiles_never_invent_a_value_between_samples() -> None:
    """Nearest-rank: with two samples p99 must be one of them."""
    p = latency_percentiles([_outcome("a", latency=1.0), _outcome("b", latency=9.0)])
    assert p["p99"] in (1.0, 9.0)


def test_errored_queries_do_not_pollute_latency() -> None:
    outcomes = [_outcome("a", latency=1.0), _outcome("b", latency=99.0, error="boom")]
    assert latency_percentiles(outcomes)["max"] == 1.0


def test_latency_is_empty_without_samples() -> None:
    assert latency_percentiles([]) == {}


# --- report ---


def _summary(**kw: object) -> object:
    defaults = {
        "suite": "synthetic",
        "mode": "hybrid",
        "instances": 1,
        "corpus_fingerprint": "abc123",
        "outcomes": [_outcome("a", retrieved=("gold",))],
    }
    return summarise(**(defaults | kw))  # type: ignore[arg-type]


def test_summary_warns_when_accuracy_was_not_measured() -> None:
    report = _summary()
    assert report.accuracy is None  # type: ignore[attr-defined]
    assert any("not measured" in n for n in report.notes)  # type: ignore[attr-defined]


def test_summary_warns_when_tokens_are_unavailable_in_agentic_mode() -> None:
    report = _summary(mode="agentic")
    assert any("usage" in n for n in report.notes)  # type: ignore[attr-defined]


def test_summary_counts_and_flags_errors() -> None:
    report = _summary(outcomes=[_outcome("a", retrieved=("gold",)), _outcome("b", error="boom")])
    assert report.errors == 1  # type: ignore[attr-defined]
    assert any("errored" in n for n in report.notes)  # type: ignore[attr-defined]


def test_summary_flags_a_suite_with_no_ground_truth() -> None:
    report = _summary(outcomes=[_outcome("a", gold=())])
    assert any("No gold documents" in n for n in report.notes)  # type: ignore[attr-defined]


def test_markdown_renders_unmeasured_as_a_dash_not_a_zero() -> None:
    table = render_markdown([_summary()], command="python -m scripts.eval.run")  # type: ignore[list-item]
    assert "| —" in table or " — " in table
    assert "python -m scripts.eval.run" in table
    assert "Caveats" in table


def test_markdown_lists_every_mode_it_was_given() -> None:
    table = render_markdown(
        [_summary(), _summary(mode="agentic")],  # type: ignore[list-item]
        command="cmd",
    )
    assert "| hybrid |" in table
    assert "| agentic |" in table


# --- datasets ---


def test_synthetic_suite_is_deterministic() -> None:
    """A regression gate has to compare like with like across runs."""
    first = list(load_synthetic(count=5))
    second = list(load_synthetic(count=5))
    assert [i.instance_id for i in first] == [i.instance_id for i in second]
    assert [d.body for d in first[0].documents] == [d.body for d in second[0].documents]


def test_synthetic_instance_has_exactly_one_gold_document_among_distractors() -> None:
    instance = next(iter(load_synthetic(count=1, haystack_size=10)))
    assert len(instance.documents) == 12  # gold + near-distractor + 10 far
    assert instance.questions[0].gold_doc_ids == (instance.documents[0].doc_id,)


def test_synthetic_question_shares_its_verb_and_topic_with_the_gold_document() -> None:
    """`plainto_tsquery` ANDs terms, so a paraphrased answer matches nothing.

    This is the failure that produced recall@k of exactly 0.0: the question
    asked what we "decided" while the gold document said we "settled".
    """
    instance = next(iter(load_synthetic(count=1, haystack_size=3)))
    question, gold = instance.questions[0].question.lower(), instance.documents[0].body.lower()
    assert "decide" in question and "decided" in gold
    topic = question.removeprefix("what did we decide about the ").rstrip("?")
    assert topic in gold


def test_near_distractor_shares_the_topic_so_ranking_is_exercised() -> None:
    instance = next(iter(load_synthetic(count=1, haystack_size=3)))
    gold, near = instance.documents[0], instance.documents[1]
    topic = (
        instance.questions[0]
        .question.lower()
        .removeprefix("what did we decide about the ")
        .rstrip("?")
    )
    assert topic in near.body.lower()
    assert "decided" in near.body.lower()
    # Only the gold carries the answer, so a correct ranker prefers it.
    assert instance.questions[0].answer in gold.body
    assert instance.questions[0].answer not in near.body


def test_unknown_suite_is_rejected() -> None:
    with pytest.raises(DatasetError, match="unknown suite"):
        load("nope", None)


def test_missing_data_file_is_reported_clearly() -> None:
    from pathlib import Path

    with pytest.raises(DatasetError, match="README"):
        load("longmemeval", Path("does-not-exist.json"))


def test_real_suite_without_data_says_what_to_pass() -> None:
    with pytest.raises(DatasetError, match="--data"):
        load("locomo", None)
