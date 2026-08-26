"""The accuracy-vs-latency frontier, and the verdict it produces.

WU-2.6 turns on one decision — *if agentic recall still loses to plain hybrid,
say so publicly and demote it to opt-in* — and the temptation at the moment of
reading a disappointing table is to find a reason it does not count. So the
verdict is computed, and the computation is tested, before anyone has seen a
number they might not like.

The cases that matter are the awkward ones: no ground truth, no judge, a
mixed result where agentic wins only above some budget, and a sample too small
to conclude anything from.
"""

from __future__ import annotations

from scripts.eval.metrics import Frontier, RunReport, frontier, render_frontier

QUESTIONS = 100


def report(
    mode: str,
    *,
    accuracy: float | None = None,
    recall5: float | None = None,
    p95: float = 1.0,
    budget_ms: int = 0,
    questions: int = QUESTIONS,
) -> RunReport:
    return RunReport(
        suite="longmemeval",
        mode=mode,
        instances=10,
        questions=questions,
        corpus_fingerprint="abc123",
        recall={"recall@5": recall5} if recall5 is not None else {},
        accuracy=accuracy,
        latency={"p95": p95},
        budget_ms=budget_ms,
    )


# --- the finding WU-2.6 is written to accept ---------------------------------


def test_agentic_losing_everywhere_says_demote() -> None:
    front = frontier(
        [
            report("hybrid", accuracy=0.70, p95=0.4),
            report("agentic@500ms", accuracy=0.61, p95=1.9, budget_ms=500),
            report("agentic@2000ms", accuracy=0.68, p95=3.4, budget_ms=2000),
        ]
    )
    assert front is not None
    assert front.demote is True
    assert "did not beat plain hybrid at any budget" in front.verdict
    assert "KORTEX_AGENTIC_RETRIEVAL=false" in front.verdict
    assert "0.680" in front.verdict  # the peak it did reach, not just the failure


def test_agentic_winning_everywhere_says_keep_it() -> None:
    front = frontier(
        [
            report("hybrid", accuracy=0.60, p95=0.4),
            report("agentic@500ms", accuracy=0.71, p95=1.2, budget_ms=500),
        ]
    )
    assert front is not None
    assert front.demote is False
    assert "at every budget measured" in front.verdict
    assert "3.0x the p95" in front.verdict


def test_a_mixed_result_names_the_budget_where_it_starts_winning() -> None:
    """The most likely real outcome, and the one a single unbudgeted run cannot
    distinguish from "agentic is bad"."""
    front = frontier(
        [
            report("hybrid", accuracy=0.70, p95=0.4),
            report("agentic@250ms", accuracy=0.66, p95=0.5, budget_ms=250),
            report("agentic@1000ms", accuracy=0.73, p95=1.6, budget_ms=1000),
            report("agentic@4000ms", accuracy=0.79, p95=4.2, budget_ms=4000),
        ]
    )
    assert front is not None
    assert front.demote is False
    assert "only at budgets from 1000 ms" in front.verdict


def test_the_cheapest_win_is_the_one_reported_not_the_best() -> None:
    """What a user needs is the lowest budget that pays, not the highest score
    at any price."""
    front = frontier(
        [
            report("hybrid", accuracy=0.50, p95=1.0),
            report("agentic@4000ms", accuracy=0.90, p95=5.0, budget_ms=4000),
            report("agentic@1000ms", accuracy=0.55, p95=1.5, budget_ms=1000),
        ]
    )
    assert front is not None
    # Both budgets beat hybrid, so the phrasing is "every budget" — but the
    # numbers quoted are the cheap win, not the expensive one.
    assert "0.550" in front.verdict
    assert "1.5x" in front.verdict
    assert "0.900" not in front.verdict


# --- refusing to conclude ----------------------------------------------------


def test_a_small_sample_is_flagged_rather_than_trusted() -> None:
    front = frontier(
        [
            report("hybrid", accuracy=0.70, questions=8),
            report("agentic", accuracy=0.40, questions=8),
        ]
    )
    assert front is not None
    assert "indicative, not conclusive" in front.verdict


def test_no_ground_truth_means_no_verdict() -> None:
    """A suite with no gold documents and no judge measures latency only.
    Ranking two modes on that would be ranking them on nothing."""
    front = frontier([report("hybrid"), report("agentic")])
    assert front is not None
    assert front.demote is False
    assert "Not decidable" in front.verdict


def test_a_frontier_needs_both_sides() -> None:
    assert frontier([report("hybrid", accuracy=0.7)]) is None
    assert frontier([report("agentic", accuracy=0.7)]) is None
    assert frontier([]) is None


# --- comparing like with like ------------------------------------------------


def test_accuracy_wins_over_recall_when_a_judge_ran() -> None:
    front = frontier(
        [
            report("hybrid", accuracy=0.70, recall5=0.95),
            report("agentic", accuracy=0.80, recall5=0.90),
        ]
    )
    assert front is not None
    assert front.metric == "accuracy"
    assert front.baseline == 0.70


def test_recall_is_used_when_no_judge_ran() -> None:
    front = frontier([report("hybrid", recall5=0.80), report("agentic", recall5=0.85)])
    assert front is not None
    assert front.metric == "recall@5"


def test_modes_are_never_compared_on_different_metrics() -> None:
    """Scoring agentic on accuracy against hybrid on recall is the arithmetic
    version of a vendor-favourable chart. When one side lacks the chosen
    metric, the verdict refuses rather than substituting."""
    front = frontier(
        [
            report("hybrid", recall5=0.95),  # no judge on this side
            report("agentic", accuracy=0.80),
        ]
    )
    assert front is not None
    assert front.metric == "accuracy"
    assert front.baseline is None
    assert "Not decidable" in front.verdict


# --- rendering ---------------------------------------------------------------


def test_the_table_shows_the_delta_against_hybrid() -> None:
    front = frontier(
        [
            report("hybrid", accuracy=0.70, p95=0.4),
            report("agentic@1000ms", accuracy=0.66, p95=1.6, budget_ms=1000),
        ]
    )
    rendered = render_frontier(front)
    assert "| — (hybrid) | 0.700 | 0.40 | baseline |" in rendered
    assert "| 1000 | 0.660 | 1.60 | -0.040 |" in rendered


def test_an_unbudgeted_agentic_run_renders_as_unbounded() -> None:
    front = frontier([report("hybrid", accuracy=0.7), report("agentic", accuracy=0.6)])
    assert "| unbounded |" in render_frontier(front)


def test_a_missing_frontier_says_what_is_missing() -> None:
    assert "not measured" in render_frontier(None)


def test_the_frontier_survives_a_json_round_trip() -> None:
    """It goes into the results file, which is the artefact anyone comparing
    two runs actually reads."""
    import json

    front = frontier([report("hybrid", accuracy=0.7), report("agentic", accuracy=0.6)])
    assert isinstance(front, Frontier)
    assert json.loads(json.dumps(front.as_dict(), default=str))["demote"] is True
