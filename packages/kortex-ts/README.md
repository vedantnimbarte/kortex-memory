# @kortex/client

TypeScript client for [Kortex Memory](https://github.com/vedantnimbarte/kortex-memory) — a
multi-tenant memory layer for LLMs and AI agents.

```bash
npm install @kortex/client
```

**Zero runtime dependencies.** It uses global `fetch`, which Node has had since
18, so it also runs in Bun, Deno, edge runtimes and the browser.

## Thirty seconds

```ts
import { Kortex } from "@kortex/client";

const kx = new Kortex({ scope: { type: "project", id: 7 } });
// with no apiKey/baseUrl it reads KORTEX_API_KEY and KORTEX_API_URL

await kx.remember("We chose Postgres over DynamoDB for the ledger: we need joins.");

const { hits } = await kx.search("which database for the ledger");
for (const hit of hits) console.log(hit.score.toFixed(3), hit.title);
```

Pass them explicitly if you would rather not use the environment:

```ts
const kx = new Kortex({
  apiKey: "kx_live_...",
  baseUrl: "https://kortex.example.com",
  scope: { type: "project", id: 7 },
});
```

## search vs recall

Both retrieve. They cost different things.

| | `search` | `recall` |
|---|---|---|
| How | vectors + keywords, fused, decay-weighted | the server plans, searches, re-ranks, optionally synthesises |
| Costs | one embedding | LLM tokens |
| Returns | ranked hits | a context bundle with citations and a `usage` breakdown |
| Use for | "find me things about X" | "answer this, and show your working" |

Reach for `search` first. `recall` earns its cost when the question needs more
than one lookup to answer.

```ts
import { asPrompt } from "@kortex/client";

const bundle = await kx.recall("why did we move off DynamoDB", {
  maxTokens: 2000,
  tokenBudget: 4000,
});

asPrompt(bundle);              // the candidates as one block, ready for a prompt
bundle.citations;              // what it drew on
bundle.usage.costUsd;          // null means unpriced, not free
bundle.usage.budgetExhausted;
```

Budgets are ceilings, not targets. One too small to plan within degrades to
plain hybrid retrieval rather than overshooting it.

## Things worth knowing

**Writes deduplicate.** Storing the same text twice folds into the existing
memory instead of creating a rival copy that competes with it in every future
recall. `memory.deduped` tells you which happened; `{ force: true }` insists.

**Writes may be held.** A project can gate writes for human review, and
suspicious low-trust content is held regardless of that setting.
`memory.pendingReview` means stored but invisible to retrieval until someone
approves it.

**Embedding is asynchronous.** `memory.embeddingState` is `pending` until the
worker catches up; keyword search finds it in the meantime.
`{ embedInline: true }` waits for the vector instead.

**Search degrades rather than fails.** `result.usedVector === false` means the
embedder was unavailable and this was keyword-only. The hits are real, just
ranked without semantics — worth a log line.

**Hits can carry conflicts.** `hit.conflicts` is non-empty when something in
the corpus contradicts that hit. Show it before a user acts on the memory.

## Errors

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

429s and 5xx are retried automatically, honouring the `Retry-After` the server
sent before falling back to jittered exponential backoff. You see the error only
once the retries are spent. Any other 4xx is never retried — a rejected request
stays rejected.

Everything inherits from `KortexError`.

## The long tail

Only the calls integrators actually make are wrapped. The rest of the API —
billing, admin, tenancy, attachments, review queue — is reachable without
waiting for this package to catch up:

```ts
await kx.request("GET", "/v1/analytics/summary");
await kx.request("POST", `/v1/review/${memoryId}/approve`);
```

Same auth, same retries, same error mapping; just untyped.

## Reference

| | |
|---|---|
| `remember(body, options?)` | store |
| `search(query, options?)` | hybrid retrieval |
| `recall(query, options?)` | agentic retrieval |
| `get(id)` / `listMemories(options?)` | read |
| `update(id, options)` / `forget(id)` | edit, soft-delete |
| `pin(id)` / `unpin(id)` / `bulk(action, ids)` | curate |
| `register(...)` / `login(...)` / `whoami()` | auth |
| `request(method, path, init?)` | anything else |

Every method takes `scope` to override the client default; `search` and
`recall` take `scopes` to span several.

Licensed Apache-2.0.
