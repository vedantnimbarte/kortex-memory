"""Billing schemas."""

from __future__ import annotations

from pydantic import Field

from kortex_api.schemas.common import APIModel


class PlanOut(APIModel):
    id: str
    name: str
    price_usd: int
    features: list[str]


class UsageOut(APIModel):
    memories: int
    max_memories: int
    workspaces: int
    max_workspaces: int


class SubscriptionOut(APIModel):
    plan: str
    status: str
    current_period_end: int | None = None
    billing_enabled: bool
    usage: UsageOut | None = None


class CheckoutIn(APIModel):
    plan: str = Field(min_length=1, max_length=32)


class RedirectOut(APIModel):
    url: str
