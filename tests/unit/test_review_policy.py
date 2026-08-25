"""The gating decision: does this write go straight into recall, or wait.

Getting this wrong in either direction is bad in a different way. Gate too
much and a memory layer whose whole promise is that agents stop re-explaining
themselves makes every fact wait on a human. Gate too little and the review
queue is decoration.

The load-bearing case is the last one: turning off a *quality* control must not
turn off a *security* one.
"""

from __future__ import annotations

import pytest
from kortex_core.db.types import ReviewMode, ReviewStatus
from kortex_core.skills.review_policy import decide_review

THRESHOLD = 0.5


def decide(**over: object):  # type: ignore[no-untyped-def]
    kw: dict = {
        "mode": ReviewMode.OFF,
        "confidence": None,
        "threshold": THRESHOLD,
        "suspicious_reason": "",
    }
    return decide_review(**(kw | over))  # type: ignore[arg-type]


# --- off is the default and means off ---------------------------------------


def test_gating_off_lets_everything_through() -> None:
    assert decide().status is ReviewStatus.APPROVED
    assert decide(confidence=0.01).status is ReviewStatus.APPROVED


def test_an_approved_write_carries_no_reason() -> None:
    """The reason is shown to a reviewer; an approved memory has none."""
    decision = decide()
    assert decision.reason == ""
    assert decision.held is False


# --- confidence gating ------------------------------------------------------


def test_low_confidence_is_held_when_the_project_asks() -> None:
    decision = decide(mode=ReviewMode.LOW_CONFIDENCE, confidence=0.2)
    assert decision.held
    assert "0.20" in decision.reason
    assert "0.50" in decision.reason  # the reviewer sees the bar it missed


def test_confident_writes_pass_the_same_gate() -> None:
    assert not decide(mode=ReviewMode.LOW_CONFIDENCE, confidence=0.9).held


def test_confidence_exactly_at_the_threshold_passes() -> None:
    """Below, not at: a threshold nobody can sit exactly on is a footgun."""
    assert not decide(mode=ReviewMode.LOW_CONFIDENCE, confidence=THRESHOLD).held


def test_an_unstated_confidence_is_treated_as_certain() -> None:
    """Most writers never report confidence. Holding all of them would make
    `low_confidence` mode behave as `all`."""
    assert not decide(mode=ReviewMode.LOW_CONFIDENCE, confidence=None).held


# --- gate everything --------------------------------------------------------


def test_all_mode_holds_regardless_of_confidence() -> None:
    for confidence in (None, 0.0, 1.0):
        decision = decide(mode=ReviewMode.ALL, confidence=confidence)
        assert decision.held, f"confidence={confidence} slipped through"
        assert "every write" in decision.reason


# --- suspicion outranks the mode -------------------------------------------


def test_suspicion_holds_even_with_gating_off() -> None:
    """A project turning review off is saying "I trust my writers", not "store
    prompt injections from fetched pages where my agents will read them"."""
    decision = decide(mode=ReviewMode.OFF, suspicious_reason="override_instructions")
    assert decision.held
    assert decision.reason == "override_instructions"


def test_suspicion_reason_survives_a_confident_write() -> None:
    decision = decide(
        mode=ReviewMode.LOW_CONFIDENCE,
        confidence=1.0,
        suspicious_reason="exfiltration",
    )
    assert decision.held
    assert decision.reason == "exfiltration"


@pytest.mark.parametrize("mode", list(ReviewMode))
def test_no_mode_can_release_suspicious_content(mode: ReviewMode) -> None:
    assert decide(mode=mode, suspicious_reason="concealment").held


# --- statuses ---------------------------------------------------------------


def test_only_approved_is_retrievable_by_definition() -> None:
    """Pinned so a future status cannot quietly become visible to recall."""
    assert {s.value for s in ReviewStatus} == {"approved", "pending", "rejected"}
    assert ReviewStatus.APPROVED.value == "approved"
