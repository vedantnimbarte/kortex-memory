import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useScope } from "../lib/scope";
import type { SearchOut } from "../lib/types";
import {
  Banner,
  Button,
  Card,
  Eyebrow,
  Input,
  MonoId,
  SensitivityChip,
  Spinner,
  TierChip,
} from "../components/ui";

export default function SearchPage() {
  const { active } = useScope();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { query, limit: 30 };
      if (active) body.scopes = [{ scope_type: active.scope_type, scope_id: active.scope_id }];
      setResult(await api<SearchOut>("/v1/search", { method: "POST", body: JSON.stringify(body) }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "search failed");
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <Eyebrow>Search</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Hybrid search</h1>
        <p className="mt-2 text-sm text-muted">
          Direct vector + keyword ranking — no planning. For multi-hop reasoning, use{" "}
          <Link to="/app/recall" className="text-copper hover:text-copper-bright">
            Recall
          </Link>
          .
        </p>
      </header>

      <form onSubmit={run} className="flex gap-2">
        <Input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="rate limiting"
          className="flex-1"
        />
        <Button type="submit" disabled={busy || !query.trim()}>
          {busy ? <Spinner /> : "Search"}
        </Button>
      </form>

      {error && <Banner>{error}</Banner>}

      {result && (
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <Eyebrow>{result.hits.length} hits</Eyebrow>
            <span className="font-mono text-[11px] text-faint">
              {result.used_vector ? "vector + keyword" : "keyword only"}
            </span>
          </div>
          {result.hits.length === 0 && <p className="text-sm text-muted">Nothing matched.</p>}
          {result.hits.map((h) => (
            <Link key={h.public_id} to={`/app/memories/${h.public_id}`} className="block">
              <Card className="p-4 transition-colors hover:border-line-bright">
                <div className="flex items-center gap-2">
                  <TierChip tier={h.tier} />
                  <SensitivityChip level={h.sensitivity} />
                  <span className="ml-auto font-mono text-[11px] tabular-nums text-copper">
                    {h.score.toFixed(3)}
                  </span>
                </div>
                <p className="mt-2 text-sm font-medium text-ink">{h.title || "Untitled"}</p>
                <p className="mt-1 line-clamp-2 text-sm text-muted">{h.body}</p>
                <div className="mt-2">
                  <MonoId id={h.public_id} />
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
