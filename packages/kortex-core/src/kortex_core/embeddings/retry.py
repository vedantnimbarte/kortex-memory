"""When to retry a failed embedding, and when to stop.

Pure and database-free on purpose: this is the rule that decides whether a
memory gets another chance or is parked as unsearchable, so it should be
testable without standing up Postgres — and there should be exactly one copy of
it for the repository and its tests to share.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MAX_BACKOFF_SECONDS = 3600
"""An hour. Without a ceiling, attempt 20 schedules a retry decades out."""


@dataclass(frozen=True, slots=True)
class RetryDecision:
    attempts: int
    """The attempt count *after* recording this failure."""
    next_attempt_at: dt.datetime | None
    """When to try again. ``None`` when parked — parked means stop, not wait."""
    parked: bool
    """True once the retry budget is spent: no longer searchable, no longer retried."""


def decide_retry(
    attempts_before: int,
    *,
    max_attempts: int,
    retry_base_seconds: int,
    now: dt.datetime,
) -> RetryDecision:
    """Record one failed attempt and say what happens next.

    Backoff is exponential (``base * 2^(n-1)``) and capped, so a provider
    outage does not burn the entire retry budget inside the first two minutes —
    the failure mode that turns a transient blip into permanently lost recall.
    """
    attempts = attempts_before + 1
    if attempts >= max_attempts:
        return RetryDecision(attempts=attempts, next_attempt_at=None, parked=True)
    delay = min(retry_base_seconds * (2 ** (attempts - 1)), MAX_BACKOFF_SECONDS)
    return RetryDecision(
        attempts=attempts,
        next_attempt_at=now + dt.timedelta(seconds=delay),
        parked=False,
    )
