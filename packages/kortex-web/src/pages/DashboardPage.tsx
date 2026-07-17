import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useScope } from "../lib/scope";
import { fromApi } from "../lib/analytics";
import type { Analytics, Subscription } from "../lib/types";
import {
  BarList,
  Banner,
  Card,
  DecayMeter,
  Eyebrow,
  EmptyState,
  MonoId,
  SegmentBar,
  Sparkline,
  Spinner,
  Stat,
  formatNumber,
} from "../components/ui";

export default function DashboardPage() {
  const { active } = useScope();
  const scopeKey = active ? `${active.scope_type}:${active.scope_id}` : "all";

  const analyticsQ = useQuery({
    queryKey: ["dashboard-analytics", scopeKey],
    queryFn: () => {
      const params = new URLSearchParams();
      if (active) {
        params.set("scope_type", active.scope_type);
        params.set("scope_id", String(active.scope_id));
      }
      const qs = params.toString();
      return api<Analytics>(`/v1/analytics/summary${qs ? `?${qs}` : ""}`);
    },
  });

  const subQ = useQuery({
    queryKey: ["subscription"],
    queryFn: () => api<Subscription>("/v1/billing/subscription"),
    retry: false,
  });

  const summary = analyticsQ.data ? fromApi(analyticsQ.data) : null;
  const usage = subQ.data?.usage ?? null;
  const trueTotal = usage?.memories ?? summary?.count ?? 0;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow>Overview</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold text-ink">
            {active ? active.label : "Everything you can see"}
          </h1>
        </div>
        <Link to="/app/recall" className="text-sm text-copper transition-colors hover:text-copper-bright">
          Ask the memory →
        </Link>
      </header>

      {analyticsQ.isLoading && <Spinner />}
      {analyticsQ.error && <Banner>{(analyticsQ.error as ApiError).message}</Banner>}

      {summary && summary.count === 0 && (
        <EmptyState
          title="Nothing stored here yet."
          hint="Memories accumulate as your agents work. Once there are some, this becomes a live view of what the machine is holding."
          action={
            <Link to="/app/memories" className="text-sm text-copper hover:text-copper-bright">
              Write the first memory →
            </Link>
          }
        />
      )}

      {summary && summary.count > 0 && (
        <div className="stagger space-y-6">
          {/* Signature hero: the core, glowing. */}
          <Card className="core-glow panel relative overflow-hidden p-6" style={{ ["--i" as string]: 0 }}>
            <div className="core-lattice pointer-events-none absolute inset-0" aria-hidden />
            <div className="relative grid gap-6 md:grid-cols-[auto_1fr] md:items-center">
              <div>
                <span className="font-mono text-6xl font-semibold tracking-tight text-core">
                  {formatNumber(trueTotal)}
                </span>
                <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.2em] text-faint">
                  memories in core
                </p>
              </div>
              <div className="md:justify-self-end md:text-right">
                <p className="font-mono text-[11px] uppercase tracking-wider text-faint">
                  last 14 days
                </p>
                <div className="mt-2 max-w-xs md:ml-auto">
                  <Sparkline data={summary.timeline} />
                </div>
              </div>
            </div>
          </Card>

          {/* Vital signs. */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" style={{ ["--i" as string]: 1 }}>
            <Card className="panel p-5">
              <Stat value={formatNumber(summary.pinned)} label="Pinned" sub="held against decay" />
            </Card>
            <Card className="panel p-5">
              <Stat value={summary.avgDecay.toFixed(2)} label="Avg retention" accent />
              <div className="mt-3">
                <DecayMeter value={summary.avgDecay} label={false} />
              </div>
            </Card>
            <Card className="panel p-5">
              <Stat value={formatNumber(summary.totalAccess)} label="Total recalls" sub="all time" />
            </Card>
            <Card className="panel p-5">
              {usage ? (
                <>
                  <Stat
                    value={`${formatNumber(usage.memories)} / ${formatNumber(usage.max_memories)}`}
                    label="Plan usage"
                  />
                  <div className="mt-3">
                    <DecayMeter value={usage.memories / Math.max(1, usage.max_memories)} label={false} />
                  </div>
                </>
              ) : (
                <Stat value={formatNumber(summary.count)} label="Memories" />
              )}
            </Card>
          </div>

          <div className="grid gap-5 lg:grid-cols-2" style={{ ["--i" as string]: 2 }}>
            <Card className="panel p-5">
              <Eyebrow>Tiers</Eyebrow>
              <p className="mt-1 mb-4 text-xs text-muted">Short-term volatility settling into long-term core.</p>
              <SegmentBar segments={summary.byTier} />
            </Card>

            <Card className="panel p-5">
              <Eyebrow>Retention health</Eyebrow>
              <p className="mt-1 mb-4 text-xs text-muted">How strongly memories are still held.</p>
              <SegmentBar
                segments={[
                  { label: "healthy", value: summary.decayHealth.healthy, color: "var(--color-ok)" },
                  { label: "aging", value: summary.decayHealth.aging, color: "var(--color-tier-mid)" },
                  { label: "faded", value: summary.decayHealth.faded, color: "var(--color-danger)" },
                ]}
              />
            </Card>

            <Card className="panel p-5">
              <Eyebrow>By kind</Eyebrow>
              <div className="mt-4">
                <BarList items={summary.byKind} />
              </div>
            </Card>

            <Card className="panel p-5">
              <div className="flex items-center justify-between">
                <Eyebrow>Most recalled</Eyebrow>
                <Link to="/app/memories" className="text-xs text-muted hover:text-copper">
                  All memories →
                </Link>
              </div>
              <ul className="mt-4 space-y-3">
                {summary.topAccessed.map((m) => (
                  <li key={m.public_id}>
                    <Link
                      to={`/app/memories/${m.public_id}`}
                      className="group flex items-center gap-3"
                    >
                      <span className="min-w-0 flex-1 truncate text-sm text-ink group-hover:text-copper">
                        {m.title || "Untitled"}
                      </span>
                      <span className="shrink-0 font-mono text-[11px] tabular-nums text-copper">
                        {formatNumber(m.access_count)}×
                      </span>
                      <MonoId id={m.public_id} />
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
