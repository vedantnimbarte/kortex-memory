"""Billing: Stripe Checkout + Customer Portal + webhook reconciliation.

The org's tier lives in ``orgs.plan``; Stripe bookkeeping (customer/subscription
ids, status) lives in ``orgs.settings['billing']`` — a JSONB blob, so no schema
migration. When Stripe isn't configured the catalog still lists, but any call
that would talk to Stripe raises :class:`BillingUnavailable`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import ActorKind, ScopeType
from kortex_core.models.org import Org
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.repositories.workspace_repo import WorkspaceRepository
from kortex_core.security.plan_limits import limits_for
from kortex_core.security.principal import Principal, ScopeRef
from kortex_core.services.access_control import AccessControl, AccessDeniedError
from kortex_core.settings import get_settings


class BillingUnavailableError(Exception):
    """Raised when billing is called but Stripe isn't configured."""


class BillingError(Exception):
    """Raised on a bad billing request (unknown plan, no price id, etc.)."""


@dataclass(frozen=True, slots=True)
class Plan:
    id: str
    name: str
    price_usd: int  # per month; 0 = free
    features: list[str]


# The catalog. Free is implicit (no Stripe price); paid plans map to a settings
# price id resolved at checkout time.
PLANS: list[Plan] = [
    Plan("free", "Free", 0, ["1 workspace", "1k memories", "Community support"]),
    Plan(
        "pro",
        "Pro",
        20,
        ["Unlimited workspaces", "100k memories", "Agentic recall", "Email support"],
    ),
    Plan(
        "team",
        "Team",
        99,
        ["Everything in Pro", "SSO & RBAC", "1M memories", "Priority support"],
    ),
]
_PLAN_IDS = {p.id for p in PLANS}


class BillingService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal
        self._orgs = OrgRepository(session, principal=principal)
        self._ac = AccessControl()

    # --- read ---

    @staticmethod
    def plans() -> list[Plan]:
        return PLANS

    async def subscription(self) -> dict:
        org = await self._require_org()
        billing = (org.settings or {}).get("billing", {})
        limits = limits_for(org.plan)
        memories = MemoryRepository(self._session, principal=self._principal)
        workspaces = WorkspaceRepository(self._session, principal=self._principal)
        mem_used = await memories.count_for_org(org.id)
        ws_used = await workspaces.count_for_org(org.id)
        return {
            "plan": org.plan,
            "status": billing.get("status", "active" if org.plan == "free" else "unknown"),
            "current_period_end": billing.get("current_period_end"),
            "billing_enabled": get_settings().billing_enabled,
            "usage": {
                "memories": mem_used,
                "max_memories": limits.max_memories,
                "workspaces": ws_used,
                "max_workspaces": limits.max_workspaces,
            },
        }

    # --- write (require org admin) ---

    async def create_checkout(self, *, plan: str) -> str:
        org = await self._require_org(admin=True)
        if plan not in _PLAN_IDS or plan == "free":
            raise BillingError(f"cannot checkout plan {plan!r}")
        s = get_settings()
        price_id = {"pro": s.stripe_price_pro, "team": s.stripe_price_team}.get(plan)
        if not price_id:
            raise BillingError(f"no Stripe price configured for plan {plan!r}")
        stripe = _stripe()
        customer_id = await self._ensure_customer(org, stripe)
        checkout = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=s.billing_success_url,
            cancel_url=s.billing_cancel_url,
            metadata={"org_id": str(org.id), "plan": plan},
            subscription_data={"metadata": {"org_id": str(org.id), "plan": plan}},
        )
        return checkout.url

    async def create_portal(self) -> str:
        org = await self._require_org(admin=True)
        customer_id = (org.settings or {}).get("billing", {}).get("stripe_customer_id")
        if not customer_id:
            raise BillingError("no billing account yet — subscribe to a plan first")
        stripe = _stripe()
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=get_settings().billing_success_url,
        )
        return portal.url

    # --- webhook reconciliation (runs unauthenticated, superuser-scoped) ---

    async def apply_webhook_event(self, event: dict) -> None:
        etype = event.get("type", "")
        event_id = event.get("id")
        obj = event.get("data", {}).get("object", {})
        org = await self._resolve_org(obj)
        if org is None:
            return  # not one of ours

        # Idempotency: Stripe retries webhooks, so skip events we've applied.
        # A small per-org ring buffer of recent event ids is enough — events are
        # low-volume per tenant and we only need to dedupe near-term retries.
        seen = (org.settings or {}).get("billing", {}).get("seen_events", [])
        if event_id and event_id in seen:
            return

        if etype in ("checkout.session.completed", "customer.subscription.updated"):
            plan = (obj.get("metadata") or {}).get("plan", org.plan)
            self._set_billing(
                org,
                plan=plan,
                status="active",
                stripe_subscription_id=obj.get("subscription") or obj.get("id"),
                current_period_end=obj.get("current_period_end"),
            )
        elif etype == "invoice.payment_failed":
            # Grace: flag past_due but keep the plan until Stripe cancels it.
            self._set_billing(org, plan=org.plan, status="past_due")
        elif etype == "customer.subscription.deleted":
            self._set_billing(org, plan="free", status="canceled")
        else:
            # ponytail: unhandled event type — still record it as seen below so a
            # retry storm of it is a no-op. Add a branch when a flow needs it.
            pass

        if event_id:
            merged = {**(org.settings or {}).get("billing", {})}
            merged["seen_events"] = [*seen, event_id][-50:]
            org.settings = {**(org.settings or {}), "billing": merged}
        await self._session.commit()

    async def _resolve_org(self, obj: dict) -> Org | None:
        """Link a Stripe object back to an org: prefer our metadata, fall back
        to the customer id (payment_failed/invoice events carry no metadata)."""
        org_id = (obj.get("metadata") or {}).get("org_id")
        if org_id:
            return await self._orgs.get_by_id(int(org_id))
        customer = obj.get("customer")
        if isinstance(customer, str):
            return await self._orgs.get_by_stripe_customer(customer)
        return None

    # --- helpers ---

    async def _ensure_customer(self, org: Org, stripe) -> str:
        billing = (org.settings or {}).get("billing", {})
        if billing.get("stripe_customer_id"):
            return billing["stripe_customer_id"]
        customer = stripe.Customer.create(
            name=org.name, metadata={"org_id": str(org.id), "slug": org.slug}
        )
        merged = {**billing, "stripe_customer_id": customer.id}
        org.settings = {**(org.settings or {}), "billing": merged}
        await self._session.commit()
        return customer.id

    def _set_billing(self, org: Org, *, plan: str, status: str, **extra) -> None:
        billing = {**(org.settings or {}).get("billing", {}), "status": status}
        billing.update({k: v for k, v in extra.items() if v is not None})
        org.plan = plan
        org.settings = {**(org.settings or {}), "billing": billing}

    async def _require_org(self, *, admin: bool = False) -> Org:
        org = await self._orgs.get_by_id(self._principal.org_id)
        if org is None:
            raise BillingError("no organization bound to this account")
        if admin:
            scope = ScopeRef(type=ScopeType.ORG, id=org.id)
            if not self._ac.can_admin(self._principal, scope):
                raise AccessDeniedError("org admin required to manage billing")
        return org


def _stripe():
    s = get_settings()
    if not s.billing_enabled or s.stripe_secret_key is None:
        raise BillingUnavailableError("billing is not configured on this server")
    try:
        import stripe
    except ModuleNotFoundError as e:  # pragma: no cover
        raise BillingUnavailableError("stripe library not installed") from e
    stripe.api_key = s.stripe_secret_key.get_secret_value()
    return stripe


def superuser_principal() -> Principal:
    return Principal(actor_id=0, actor_kind=ActorKind.SYSTEM, org_id=0, is_superuser=True)
