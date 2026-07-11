import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { Plan, Subscription } from "../lib/types";
import { Banner, Button, Card, Eyebrow, Spinner } from "../components/ui";

function UsageBar({ label, used, max }: { label: string; used: number; max: number }) {
  const unlimited = max < 0;
  const pct = unlimited ? 0 : Math.min(100, (used / Math.max(1, max)) * 100);
  const near = pct >= 90;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-sm text-ink">{label}</span>
        <span className="font-mono text-xs text-faint">
          {used.toLocaleString()} {unlimited ? "· unlimited" : `/ ${max.toLocaleString()}`}
        </span>
      </div>
      {!unlimited && (
        <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${pct}%`,
              background: near
                ? "var(--color-danger)"
                : "linear-gradient(90deg, var(--color-copper-dim), var(--color-copper-bright))",
            }}
          />
        </div>
      )}
    </div>
  );
}

export default function BillingPage() {
  const [params] = useSearchParams();
  const checkout = params.get("checkout");

  const sub = useQuery({ queryKey: ["subscription"], queryFn: () => api<Subscription>("/v1/billing/subscription") });
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api<Plan[]>("/v1/billing/plans") });

  const startCheckout = useMutation({
    mutationFn: (plan: string) =>
      api<{ url: string }>("/v1/billing/checkout", { method: "POST", body: JSON.stringify({ plan }) }),
    onSuccess: ({ url }) => {
      window.location.href = url;
    },
  });

  const openPortal = useMutation({
    mutationFn: () => api<{ url: string }>("/v1/billing/portal", { method: "POST" }),
    onSuccess: ({ url }) => {
      window.location.href = url;
    },
  });

  const currentPlan = sub.data?.plan ?? "free";
  const billingEnabled = sub.data?.billing_enabled ?? false;

  return (
    <div className="space-y-6">
      <header>
        <Eyebrow>Billing</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Plan & billing</h1>
      </header>

      {checkout === "success" && <Banner tone="ok">Subscription updated. Welcome aboard.</Banner>}
      {checkout === "cancel" && <Banner>Checkout canceled — no changes made.</Banner>}
      {(startCheckout.error || openPortal.error) && (
        <Banner>{((startCheckout.error || openPortal.error) as ApiError).message}</Banner>
      )}

      {sub.isLoading || plans.isLoading ? (
        <Spinner />
      ) : (
        <>
          <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
            <div>
              <p className="font-mono text-[11px] uppercase tracking-wider text-faint">Current plan</p>
              <p className="mt-1 text-xl font-semibold capitalize text-ink">
                {currentPlan}{" "}
                <span className="font-mono text-xs text-muted">· {sub.data?.status}</span>
              </p>
            </div>
            {currentPlan !== "free" && billingEnabled && (
              <Button variant="outline" onClick={() => openPortal.mutate()} disabled={openPortal.isPending}>
                {openPortal.isPending ? <Spinner /> : "Manage billing"}
              </Button>
            )}
          </Card>

          {sub.data?.usage && (
            <Card className="p-5">
              <Eyebrow>Usage</Eyebrow>
              <div className="mt-4 space-y-4">
                <UsageBar label="Memories" used={sub.data.usage.memories} max={sub.data.usage.max_memories} />
                <UsageBar label="Workspaces" used={sub.data.usage.workspaces} max={sub.data.usage.max_workspaces} />
              </div>
            </Card>
          )}

          {!billingEnabled && (
            <Banner tone="ok">
              Billing runs in preview — Stripe isn't configured on this server, so checkout is disabled. Set{" "}
              <code className="font-mono">KORTEX_STRIPE_SECRET_KEY</code> to go live.
            </Banner>
          )}

          <div className="grid gap-4 md:grid-cols-3">
            {plans.data?.map((plan) => {
              const isCurrent = plan.id === currentPlan;
              const isPaid = plan.price_usd > 0;
              return (
                <Card
                  key={plan.id}
                  className={`flex flex-col p-5 ${isCurrent ? "border-copper" : ""}`}
                >
                  <div className="flex items-baseline justify-between">
                    <span className="text-lg font-semibold text-ink">{plan.name}</span>
                    {isCurrent && <Eyebrow>Current</Eyebrow>}
                  </div>
                  <p className="mt-2 font-mono text-2xl text-ink">
                    ${plan.price_usd}
                    <span className="text-sm text-faint">/mo</span>
                  </p>
                  <ul className="mt-4 flex-1 space-y-1.5">
                    {plan.features.map((f) => (
                      <li key={f} className="flex gap-2 text-sm text-muted">
                        <span className="text-copper">›</span>
                        {f}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-5">
                    {isCurrent ? (
                      <Button variant="ghost" disabled className="w-full">
                        Active
                      </Button>
                    ) : isPaid ? (
                      <Button
                        className="w-full"
                        onClick={() => startCheckout.mutate(plan.id)}
                        disabled={!billingEnabled || startCheckout.isPending}
                      >
                        {startCheckout.isPending ? <Spinner /> : `Upgrade to ${plan.name}`}
                      </Button>
                    ) : (
                      <Button variant="outline" disabled className="w-full">
                        Free tier
                      </Button>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
