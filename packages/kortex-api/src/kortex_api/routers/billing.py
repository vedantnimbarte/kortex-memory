"""Billing router: plans, subscription, Stripe checkout/portal, webhook."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from kortex_core.services.billing_service import (
    BillingError,
    BillingService,
    BillingUnavailableError,
    superuser_principal,
)
from kortex_core.settings import get_settings

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import bad_request, service_unavailable
from kortex_api.schemas.billing import (
    CheckoutIn,
    PlanOut,
    RedirectOut,
    SubscriptionOut,
)

router = APIRouter(prefix="/v1/billing", tags=["billing"])


@router.get("/plans", response_model=list[PlanOut])
async def list_plans() -> list[PlanOut]:
    return [PlanOut.model_validate(p, from_attributes=True) for p in BillingService.plans()]


@router.get("/subscription", response_model=SubscriptionOut)
async def get_subscription(principal: PrincipalDep, session: SessionDep) -> SubscriptionOut:
    svc = BillingService(session, principal)
    return SubscriptionOut(**await svc.subscription())


@router.post("/checkout", response_model=RedirectOut)
async def create_checkout(
    payload: CheckoutIn, principal: PrincipalDep, session: SessionDep
) -> RedirectOut:
    svc = BillingService(session, principal)
    try:
        url = await svc.create_checkout(plan=payload.plan)
    except BillingUnavailableError as e:
        raise service_unavailable(str(e)) from e
    except BillingError as e:
        raise bad_request(str(e)) from e
    return RedirectOut(url=url)


@router.post("/portal", response_model=RedirectOut)
async def create_portal(principal: PrincipalDep, session: SessionDep) -> RedirectOut:
    svc = BillingService(session, principal)
    try:
        url = await svc.create_portal()
    except BillingUnavailableError as e:
        raise service_unavailable(str(e)) from e
    except BillingError as e:
        raise bad_request(str(e)) from e
    return RedirectOut(url=url)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, session: SessionDep) -> Response:
    s = get_settings()
    if not s.billing_enabled or s.stripe_webhook_secret is None:
        raise service_unavailable("billing is not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        import stripe

        event = stripe.Webhook.construct_event(
            payload, sig, s.stripe_webhook_secret.get_secret_value()
        )
    except Exception as e:
        raise bad_request(f"invalid webhook: {e}") from e
    await BillingService(session, superuser_principal()).apply_webhook_event(dict(event))
    return Response(status_code=200)
