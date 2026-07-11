import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Plan } from "../lib/types";
import { Card, DecayMeter, Eyebrow, Spinner, TierChip } from "../components/ui";

const TIERS = [
  { tier: "short", title: "Short-term", body: "Fresh context from the current session. Volatile — it fades unless it proves useful." },
  { tier: "mid", title: "Mid-term", body: "Recurring facts and decisions promote here as they're recalled again and again." },
  { tier: "long", title: "Long-term", body: "Settled knowledge, woven into core. Durable across every agent and tool." },
];

const FEATURES = [
  ["Agentic recall", "A planner runs multi-hop hybrid lookups — vector, keyword, recency — and shows its work."],
  ["Scoped by design", "Org → workspace → project → session. Memory stays exactly where it belongs."],
  ["Sensitivity × RBAC", "Four sensitivity tiers meet role-based access. Secrets never leak across a scope."],
  ["MCP-native", "16 canonical tools over stdio or HTTP. Plug in Claude Code, Codex, or OpenCode."],
];

function TopNav() {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-bg/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <span className="font-mono text-sm font-semibold tracking-[0.3em] text-ink">KORTEX</span>
        <nav className="flex items-center gap-6 text-sm">
          <a href="#pricing" className="text-muted transition-colors hover:text-ink">
            Pricing
          </a>
          <Link to="/login" className="text-muted transition-colors hover:text-ink">
            Sign in
          </Link>
          <Link
            to="/signup"
            className="rounded-md bg-copper px-3.5 py-2 text-sm font-medium text-[#1a0e02] transition-colors hover:bg-copper-bright"
          >
            Get started
          </Link>
        </nav>
      </div>
    </header>
  );
}

export default function LandingPage() {
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api<Plan[]>("/v1/billing/plans") });
  return (
    <div className="min-h-screen">
      <TopNav />

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-line">
        <div className="core-lattice absolute inset-0" />
        <div className="relative mx-auto grid max-w-6xl gap-12 px-6 py-20 lg:grid-cols-[1fr_460px] lg:py-28">
          <div className="fade-up">
            <Eyebrow>Memory layer for AI agents</Eyebrow>
            <h1 className="mt-4 font-mono text-4xl font-semibold leading-[1.1] tracking-tight text-ink sm:text-5xl">
              Your agents forget.
              <br />
              <span className="text-copper">Kortex remembers.</span>
            </h1>
            <p className="mt-5 max-w-md text-base leading-relaxed text-muted">
              A durable, scoped, access-controlled memory that survives across sessions and tools. Plug it in
              over MCP and every agent shares one recall.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                to="/signup"
                className="rounded-md bg-copper px-5 py-2.5 text-sm font-medium text-[#1a0e02] transition-colors hover:bg-copper-bright"
              >
                Start free
              </Link>
              <a
                href="#how"
                className="rounded-md border border-line-bright px-5 py-2.5 text-sm text-ink transition-colors hover:border-copper hover:text-copper"
              >
                How it works
              </a>
            </div>
          </div>

          {/* Signature: a live recall panel, built from the product's own data language. */}
          <div className="fade-up">
            <Card className="p-4 shadow-2xl shadow-black/40">
              <div className="flex items-center gap-2 border-b border-line pb-3">
                <span className="font-mono text-[11px] uppercase tracking-wider text-copper">recall</span>
                <span className="font-mono text-xs text-muted">"how do we handle rate limiting?"</span>
              </div>
              <div className="mt-3 space-y-2.5">
                {[
                  { tier: "long", title: "Decision: token-bucket per API key", decay: 0.94, score: "0.912" },
                  { tier: "mid", title: "Redis sliding-window fallback", decay: 0.71, score: "0.804" },
                  { tier: "short", title: "429s spiked after the v2 rollout", decay: 0.38, score: "0.657" },
                ].map((m) => (
                  <div key={m.title} className="rounded-lg border border-line bg-bg p-3">
                    <div className="flex items-center gap-2">
                      <TierChip tier={m.tier} />
                      <span className="ml-auto font-mono text-[11px] text-copper">{m.score}</span>
                    </div>
                    <p className="mt-2 text-sm text-ink">{m.title}</p>
                    <div className="mt-2 w-28">
                      <DecayMeter value={m.decay} />
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-3 font-mono text-[10px] text-faint">2 hops · vector + bm25 + recency · 214 tok</p>
            </Card>
          </div>
        </div>
      </section>

      {/* How it works — a genuine lifecycle, so the numbering earns its place. */}
      <section id="how" className="mx-auto max-w-6xl px-6 py-20">
        <Eyebrow>The memory lifecycle</Eyebrow>
        <h2 className="mt-3 max-w-lg text-2xl font-semibold text-ink">
          Memories settle into core as they prove their worth.
        </h2>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {TIERS.map((t, i) => (
            <div key={t.tier} className="border-t border-line-bright pt-5">
              <div className="flex items-center gap-3">
                <span className="font-mono text-sm text-copper">{String(i + 1).padStart(2, "0")}</span>
                <TierChip tier={t.tier} />
              </div>
              <h3 className="mt-4 text-lg font-medium text-ink">{t.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{t.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="border-y border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-px overflow-hidden bg-line md:grid-cols-2">
          {FEATURES.map(([title, body]) => (
            <div key={title} className="bg-surface p-8">
              <h3 className="font-mono text-sm uppercase tracking-wider text-copper">{title}</h3>
              <p className="mt-3 text-base leading-relaxed text-muted">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="mx-auto max-w-6xl px-6 py-20">
        <Eyebrow>Pricing</Eyebrow>
        <h2 className="mt-3 text-2xl font-semibold text-ink">Start free. Grow into core.</h2>
        {plans.isLoading ? (
          <div className="mt-10"><Spinner /></div>
        ) : (
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {plans.data?.map((plan, i) => (
              <Card key={plan.id} className={`flex flex-col p-6 ${i === 1 ? "border-copper" : ""}`}>
                <span className="text-lg font-semibold text-ink">{plan.name}</span>
                <p className="mt-2 font-mono text-3xl text-ink">
                  ${plan.price_usd}
                  <span className="text-sm text-faint">/mo</span>
                </p>
                <ul className="mt-5 flex-1 space-y-2">
                  {plan.features.map((f) => (
                    <li key={f} className="flex gap-2 text-sm text-muted">
                      <span className="text-copper">›</span>
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  to="/signup"
                  className={`mt-6 rounded-md px-4 py-2.5 text-center text-sm font-medium transition-colors ${
                    i === 1
                      ? "bg-copper text-[#1a0e02] hover:bg-copper-bright"
                      : "border border-line-bright text-ink hover:border-copper hover:text-copper"
                  }`}
                >
                  {plan.price_usd === 0 ? "Start free" : `Choose ${plan.name}`}
                </Link>
              </Card>
            ))}
          </div>
        )}
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8">
          <span className="font-mono text-xs tracking-[0.2em] text-faint">KORTEX</span>
          <p className="text-xs text-faint">Production-grade memory for LLMs and coding agents.</p>
        </div>
      </footer>
    </div>
  );
}
