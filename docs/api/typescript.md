# TypeScript SDK

```bash
npm install @kortex/client
```

**Zero runtime dependencies** — it uses global `fetch`, which Node has had since
18, so it also runs in Bun, Deno, edge runtimes and the browser.

```ts
import { Kortex } from "@kortex/client";

const kx = new Kortex({ scope: { type: "project", id: 7 } });
// with no apiKey/baseUrl it reads KORTEX_API_KEY and KORTEX_API_URL

await kx.remember("We chose Postgres over DynamoDB for the ledger: we need joins.");

const { hits } = await kx.search("which database for the ledger");
for (const hit of hits) console.log(hit.score, hit.title);
```

## Choosing between `search` and `recall`

Both retrieve; they cost different things.

| | `search` | `recall` |
|---|---|---|
| How | vectors + keywords, fused, decay-weighted | the server plans, searches, re-ranks, optionally synthesises |
| Costs | one embedding | LLM tokens |
| Returns | ranked hits | a context bundle with citations and a `usage` breakdown |

Reach for `search` first. `recall` earns its cost when the question needs more
than one lookup. Its budgets (`tokenBudget`, `latencyBudgetMs`) are ceilings: one
too small to plan within degrades to plain hybrid retrieval rather than
overshooting.

```ts
import { asPrompt } from "@kortex/client";

const bundle = await kx.recall("why did we move off DynamoDB", { maxTokens: 2000 });
const prompt = asPrompt(bundle);
```

## What the server tells you that is easy to miss

| Field | Means |
|---|---|
| `memory.deduped` | The write folded into an existing identical memory. `{ force: true }` insists on a second row. |
| `memory.pendingReview` | Stored, but held for a human and invisible to retrieval until approved. |
| `memory.embeddingState` | `pending`/`failed` — not in vector search yet. Keyword search still finds it. `{ embedInline: true }` waits instead. |
| `result.usedVector` | `false` means the embedder was unavailable and this degraded to keyword-only. |
| `hit.conflicts` | Something in the corpus contradicts this hit. Worth surfacing before a user acts on it. |
| `usage.costUsd` | `null` means the model has no configured price, **not** that it was free. |

## Errors and retries

429 and 5xx are retried automatically, honouring the `Retry-After` the server
sent before falling back to jittered exponential backoff. Any other 4xx is never
retried — a rejected request stays rejected, and retrying it only delays the
error the caller needs to see.

```ts
import { PlanLimitError, RateLimitError } from "@kortex/client";

try {
  await kx.remember("...");
} catch (error) {
  if (error instanceof PlanLimitError) console.log(error.message);
  else if (error instanceof RateLimitError) console.log(error.retryAfter);
  else throw error;
}
```

Everything inherits from `KortexError`.

## The endpoints this client does not wrap

Only the calls integrators actually make are typed. Billing, admin, tenancy,
attachments and the review queue stay reachable without waiting for a release:

```ts
await kx.request("GET", "/v1/analytics/summary");
```

Same auth, same retries, same error mapping — just untyped.

Full reference:
[`packages/kortex-ts/README.md`](https://github.com/vedantnimbarte/kortex-memory/blob/main/packages/kortex-ts/README.md).
