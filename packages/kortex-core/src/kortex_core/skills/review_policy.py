"""Whether a write goes straight into recall, or waits for a human.

Two things put a memory in the queue, and they are not the same worry:

* **Suspicion** — low-trust content that reads as instructions to a model
  (see :mod:`kortex_core.skills.trust_policy`). A security decision.
* **Low confidence** — the writer itself said it was unsure, or the project
  gates every write. A quality decision.

They share one queue anyway, because from the memory's point of view the
outcome is identical: it is stored, it is invisible to recall, and a person has
to look at it. Two mechanisms that both mean "held" would mean two exclusion
filters to keep in step and two inboxes to remember to check — and a governance
control nobody checks is worse than none, because it looks like coverage.

Gating is **off by default**. A memory layer whose whole promise is that agents
stop re-explaining themselves does not, out of the box, make every fact wait on
a human. Projects that want the discipline turn it on.
"""

from __future__ import annotations

from dataclasses import dataclass

from kortex_core.db.types import ReviewMode, ReviewStatus


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    status: ReviewStatus
    reason: str = ""
    """Shown to the reviewer. Empty when the memory went straight through."""

    @property
    def held(self) -> bool:
        return self.status is ReviewStatus.PENDING


def decide_review(
    *,
    mode: ReviewMode,
    confidence: float | None,
    threshold: float,
    suspicious_reason: str = "",
) -> ReviewDecision:
    """Decide whether this write is visible to recall immediately.

    Suspicion is checked first and ignores the mode: a project that has turned
    review off is saying "I trust my writers", not "store prompt injections
    from fetched pages where my agents will read them". Turning off a quality
    control must not turn off a security one.
    """
    if suspicious_reason:
        return ReviewDecision(ReviewStatus.PENDING, suspicious_reason)
    if mode is ReviewMode.ALL:
        return ReviewDecision(ReviewStatus.PENDING, "project reviews every write")
    if mode is ReviewMode.LOW_CONFIDENCE and confidence is not None and confidence < threshold:
        return ReviewDecision(
            ReviewStatus.PENDING,
            f"confidence {confidence:.2f} below the {threshold:.2f} threshold",
        )
    return ReviewDecision(ReviewStatus.APPROVED)
