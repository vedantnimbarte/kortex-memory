# Python SDK

```bash
pip install kortex
```

`httpx` is the only dependency. The package never imports `kortex_core`, so
installing it does not pull a database driver and an embedding stack into an
application that only sends JSON over HTTP.

```python
from kortex import Kortex

kx = Kortex(scope=("project", 7))   # reads KORTEX_API_KEY and KORTEX_API_URL

kx.remember("We chose Postgres over DynamoDB for the ledger: we need joins.")

for hit in kx.search("which database for the ledger"):
    print(f"{hit.score:.3f}  {hit.title}")
```

Async is the same surface, awaited:

```python
from kortex import AsyncKortex

async with AsyncKortex(scope=("project", 7)) as kx:
    bundle = await kx.recall("what did we decide about the ledger")
    prompt = bundle.as_prompt()
```

## Choosing between `search` and `recall`

Both retrieve; they cost different things.

| | `search` | `recall` |
|---|---|---|
| How | vectors + keywords, fused, decay-weighted | the server plans, searches, re-ranks, optionally synthesises |
| Costs | one embedding | LLM tokens |
| Returns | ranked hits | a context bundle with citations and a `usage` breakdown |

Reach for `search` first. `recall` earns its cost when the question needs more
than one lookup. Its budgets (`token_budget`, `latency_budget_ms`) are ceilings:
a budget too small to plan within degrades to plain hybrid retrieval rather
than overshooting.

## What the server tells you that is easy to miss

| Field | Means |
|---|---|
| `memory.deduped` | The write folded into an existing identical memory instead of creating a rival copy. Pass `force=True` to insist on a second row. |
| `memory.pending_review` | Stored, but held for a human and invisible to retrieval until approved. |
| `memory.embedding_state` | `pending`/`failed` — not in vector search yet. Keyword search still finds it. `embed_inline=True` waits instead. |
| `result.used_vector` | `False` means the embedder was unavailable and this degraded to keyword-only. Real results, ranked without semantics. |
| `hit.conflicts` | Something in the corpus contradicts this hit. Worth surfacing before a user acts on it. |
| `usage.cost_usd` | `None` means the model has no configured price, **not** that it was free. |

## Errors and retries

429 and 5xx are retried automatically, honouring the server's `Retry-After`
before falling back to jittered exponential backoff. Any other 4xx is never
retried — a rejected request stays rejected, and retrying it only delays the
error the caller needs to see.

```python
from kortex import PlanLimitError, RateLimitError

try:
    kx.remember("...")
except PlanLimitError as e:
    print(e)               # "memory limit reached for the free plan (25,000 memories)."
except RateLimitError as e:
    print(e.retry_after)   # the server's own advice, in seconds, when it gave any
```

Everything inherits from `KortexError`.

## The endpoints this client does not wrap

Only the calls integrators actually make are typed. Billing, admin, tenancy,
attachments and the review queue stay reachable without waiting for a release:

```python
kx.request("GET", "/v1/analytics/summary")
```

Same auth, same retries, same error mapping — just untyped.

Full reference:
[`packages/kortex-sdk/README.md`](https://github.com/vedantnimbarte/kortex-memory/blob/main/packages/kortex-sdk/README.md).
