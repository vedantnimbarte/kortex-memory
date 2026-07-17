import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useScope } from "../lib/scope";
import type { ContextBundle } from "../lib/types";
import {
  Banner,
  Button,
  Card,
  DecayMeter,
  Eyebrow,
  Input,
  MonoId,
  SensitivityChip,
  Spinner,
  TierChip,
} from "../components/ui";

export default function RecallPage() {
  const { active } = useScope();
  const [query, setQuery] = useState("");
  const [synthesize, setSynthesize] = useState(false);
  const [bundle, setBundle] = useState<ContextBundle | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { query, synthesize };
      if (active) body.scopes = [{ scope_type: active.scope_type, scope_id: active.scope_id }];
      setBundle(await api<ContextBundle>("/v1/search/recall", { method: "POST", body: JSON.stringify(body) }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "recall failed");
      setBundle(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <header className="fade-up">
        <Eyebrow>Agentic recall</Eyebrow>
        <h1 className="mt-2 font-mono text-3xl font-semibold tracking-tight text-ink">
          Ask the memory.
        </h1>
        <p className="mt-2 max-w-lg text-sm text-muted">
          A planner runs multi-hop hybrid lookups — vector, keyword, and recency — over{" "}
          {active ? <span className="text-copper">{active.label}</span> : "everything you can see"}, then
          returns the passages it leaned on.
        </p>
      </header>

      <form onSubmit={run} className="fade-up space-y-3">
        <div className="flex gap-2">
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What did we decide about rate limiting?"
            className="flex-1 text-base"
          />
          <Button type="submit" disabled={busy || !query.trim()}>
            {busy ? <Spinner /> : "Recall"}
          </Button>
        </div>
        <label className="flex w-fit cursor-pointer items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={synthesize}
            onChange={(e) => setSynthesize(e.target.checked)}
            className="accent-copper"
          />
          Synthesize an answer (uses the planner LLM)
        </label>
      </form>

      {error && <Banner>{error}</Banner>}

      {bundle && (
        <div className="space-y-6">
          {bundle.answer && (
            <Card className="fade-up p-5">
              <Eyebrow>Synthesized answer</Eyebrow>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-ink">{bundle.answer}</p>
            </Card>
          )}

          {/* Plan trace — the machine showing its work. */}
          <div className="grid gap-6 lg:grid-cols-[1fr_260px]">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Eyebrow>{bundle.candidates.length} passages</Eyebrow>
                <span className="font-mono text-[11px] text-faint">
                  {bundle.hops} hops · {bundle.used_tokens} tok
                </span>
              </div>
              {bundle.candidates.length === 0 && (
                <p className="text-sm text-muted">No memories matched. Try a broader query.</p>
              )}
              {bundle.candidates.map((c) => (
                <Link key={c.public_id} to={`/app/memories/${c.public_id}`} className="block">
                  <Card className="panel panel-hover p-4">
                    <div className="flex items-center gap-2">
                      <TierChip tier={c.tier} />
                      <SensitivityChip level={c.sensitivity} />
                      <span className="ml-auto font-mono text-[11px] tabular-nums text-copper">
                        {c.final_score.toFixed(3)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-medium text-ink">{c.title || "Untitled"}</p>
                    <p className="mt-1 line-clamp-3 text-sm text-muted">{c.body}</p>
                    <div className="mt-2">
                      <MonoId id={c.public_id} />
                    </div>
                  </Card>
                </Link>
              ))}
            </div>

            <aside className="space-y-3">
              <Card className="p-4">
                <Eyebrow>Plan trace</Eyebrow>
                <ol className="mt-3 space-y-2">
                  {bundle.plan_trace.length === 0 && (
                    <li className="text-xs text-faint">Direct lookup — no planning needed.</li>
                  )}
                  {bundle.plan_trace.map((step, i) => (
                    <li key={i} className="flex gap-2 font-mono text-[11px] text-muted">
                      <span className="text-copper">{String(i + 1).padStart(2, "0")}</span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
                {bundle.plan_rationale && (
                  <p className="mt-3 border-t border-line pt-3 text-xs italic text-faint">
                    {bundle.plan_rationale}
                  </p>
                )}
                <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-faint">
                  stopped: {bundle.stopped_reason}
                </p>
              </Card>
              {bundle.citations.length > 0 && (
                <Card className="p-4">
                  <Eyebrow>Citations</Eyebrow>
                  <ul className="mt-3 space-y-2">
                    {bundle.citations.map((cit) => (
                      <li key={cit.public_id} className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-xs text-ink">{cit.title || "Untitled"}</span>
                        <DecayMeter value={cit.score} label={false} />
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </aside>
          </div>
        </div>
      )}
    </div>
  );
}
