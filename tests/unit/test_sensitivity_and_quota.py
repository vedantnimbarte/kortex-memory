"""Unit tests for the read-sensitivity cap and per-org daily quota short-circuit."""

from __future__ import annotations

import pytest
from kortex_core.db.types import Sensitivity
from kortex_core.repositories.memory_repo import _sensitivities_up_to
from kortex_core.security.quota import check_daily_quota

pytestmark = pytest.mark.unit


def test_sensitivities_up_to_caps_reads() -> None:
    # A CONFIDENTIAL cap (VIEWER/MEMBER) must never include SECRET — this is the
    # filter that stops the list endpoint from leaking SECRET rows.
    allowed = set(_sensitivities_up_to(Sensitivity.CONFIDENTIAL))
    assert Sensitivity.SECRET.value not in allowed
    assert Sensitivity.CONFIDENTIAL.value in allowed
    assert Sensitivity.PUBLIC.value in allowed

    assert set(_sensitivities_up_to(Sensitivity.SECRET)) == {s.value for s in Sensitivity}
    assert _sensitivities_up_to(Sensitivity.PUBLIC) == [Sensitivity.PUBLIC.value]


async def test_daily_quota_disabled_when_limit_non_positive() -> None:
    # limit <= 0 disables the cap without touching Redis.
    assert await check_daily_quota(bucket="recall", org_id=1, limit=0) is True
    assert await check_daily_quota(bucket="recall", org_id=1, limit=-5) is True
