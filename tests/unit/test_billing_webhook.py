"""Unit tests for billing webhook reconciliation — no DB, fake repo/session."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kortex_core.services.billing_service import (
    PLANS,
    BillingService,
    superuser_principal,
)


@dataclass
class FakeOrg:
    id: int = 1
    plan: str = "free"
    slug: str = "acme"
    name: str = "Acme"
    settings: dict[str, Any] = field(default_factory=dict)


class FakeOrgRepo:
    def __init__(self, org: FakeOrg):
        self.org = org

    async def get_by_id(self, org_id: int) -> FakeOrg | None:
        return self.org if org_id == self.org.id else None

    async def get_by_stripe_customer(self, customer_id: str) -> FakeOrg | None:
        stored = (self.org.settings.get("billing") or {}).get("stripe_customer_id")
        return self.org if stored == customer_id else None


class FakeSession:
    async def commit(self) -> None:
        return None


def _service(org: FakeOrg) -> BillingService:
    svc = BillingService(FakeSession(), superuser_principal())  # type: ignore[arg-type]
    svc._orgs = FakeOrgRepo(org)  # type: ignore[assignment]
    return svc


def test_plans_catalog() -> None:
    ids = [p.id for p in PLANS]
    assert ids == ["free", "pro", "team"]
    assert BillingService.plans() is PLANS


async def test_checkout_completed_activates_plan() -> None:
    org = FakeOrg(plan="free")
    svc = _service(org)
    event = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"org_id": "1", "plan": "pro"}, "subscription": "sub_1"}},
    }
    await svc.apply_webhook_event(event)
    assert org.plan == "pro"
    assert org.settings["billing"]["status"] == "active"
    assert org.settings["billing"]["stripe_subscription_id"] == "sub_1"


async def test_webhook_is_idempotent() -> None:
    org = FakeOrg(plan="free")
    svc = _service(org)
    event = {
        "id": "evt_dup",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"org_id": "1", "plan": "team"}}},
    }
    await svc.apply_webhook_event(event)
    assert org.plan == "team"
    # A retry of the same event id must not re-apply.
    org.plan = "SENTINEL"
    await svc.apply_webhook_event(event)
    assert org.plan == "SENTINEL"


async def test_payment_failed_sets_past_due_via_customer_lookup() -> None:
    org = FakeOrg(plan="pro", settings={"billing": {"stripe_customer_id": "cus_9"}})
    svc = _service(org)
    event = {
        "id": "evt_pf",
        "type": "invoice.payment_failed",
        "data": {"object": {"customer": "cus_9"}},
    }
    await svc.apply_webhook_event(event)
    assert org.settings["billing"]["status"] == "past_due"
    assert org.plan == "pro"  # grace: plan kept until Stripe cancels


async def test_subscription_deleted_downgrades() -> None:
    org = FakeOrg(plan="team", settings={"billing": {"stripe_customer_id": "cus_x"}})
    svc = _service(org)
    event = {
        "id": "evt_del",
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_x"}},
    }
    await svc.apply_webhook_event(event)
    assert org.plan == "free"
    assert org.settings["billing"]["status"] == "canceled"


async def test_unknown_org_is_noop() -> None:
    org = FakeOrg(id=1)
    svc = _service(org)
    event = {
        "id": "evt_unknown",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"org_id": "999", "plan": "pro"}}},
    }
    await svc.apply_webhook_event(event)  # org 999 doesn't resolve
    assert org.plan == "free"
