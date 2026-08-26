# kortex

Python client for [Kortex Memory](https://github.com/vedantnimbarte/kortex-memory) — a
multi-tenant memory layer for LLMs and AI agents.

```bash
pip install kortex
```

`httpx` is the only dependency. This package never imports `kortex_core`, so it
does not drag a database driver and an embedding model into your app to send
JSON over HTTP.

## Thirty seconds

```python
from kortex import Kortex

kx = Kortex(scope=("project", 7))   # reads KORTEX_API_KEY and KORTEX_API_URL

kx.remember("We chose Postgres over DynamoDB for the ledger: we need joins.")

for hit in kx.search("which database for the ledger"):
    print(f"{hit.score:.3f}  {hit.title or hit.body[:60]}")
```

`Kortex()` with no arguments reads `KORTEX_API_KEY` and `KORTEX_API_URL` from
the environment. Pass them explicitly if you would rather not:

```python
kx = Kortex("kx_live_...", base_url="https://kortex.example.com", scope=("project", 7))
```

## Async

Same surface, awaited.

```python
from kortex import AsyncKortex

async with AsyncKortex(scope=("project", 7)) as kx:
    bundle = await kx.recall("what did we decide about the ledger")
    prompt = bundle.as_prompt()
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

```python
bundle = kx.recall("why did we move off DynamoDB", max_tokens=2000, token_budget=4000)

bundle.as_prompt()          # the candidates as one block, ready for a prompt
bundle.citations            # what it drew on
bundle.usage.cost_usd       # None means unpriced, not free
bundle.usage.budget_exhausted
```

Budgets are ceilings, not targets. A budget too small to plan within degrades
to plain hybrid retrieval rather than overshooting it.

## Things worth knowing

**Writes deduplicate.** Storing the same text twice folds into the existing
memory instead of creating a rival copy that competes with it in every future
recall. `memory.deduped` tells you which happened; `force=True` insists.

**Writes may be held.** A project can gate writes for human review, and
suspicious low-trust content is held regardless of that setting. Check
`memory.pending_review` — a held memory is stored but invisible to retrieval
until someone approves it.

**Embedding is asynchronous.** `memory.embedding_state` is `pending` until the
worker catches up; keyword search finds it in the meantime. Pass
`embed_inline=True` to wait for the vector instead.

**Search degrades rather than fails.** `result.used_vector == False` means the
embedder was unavailable and this was keyword-only. The hits are real, just
ranked without semantics — worth a log line.

**Hits can carry conflicts.** `hit.conflicts` is non-empty when something in
the corpus contradicts that hit. Show it before a user acts on the memory.

## Errors

```python
from kortex import Kortex, RateLimitError, PlanLimitError, NotFoundError

try:
    kx.remember("...")
except PlanLimitError as e:
    print(e)          # "memory limit reached for the free plan (25,000 memories)."
except RateLimitError as e:
    print(e.retry_after)
```

429s and 5xx are retried automatically, honouring the server's `Retry-After`
before falling back to jittered exponential backoff. You see the exception only
once the retries are spent. 4xx other than 429 is never retried — a rejected
request stays rejected.

Everything inherits from `KortexError`.

## The long tail

Only the calls integrators actually make are wrapped. The rest of the API —
billing, admin, tenancy, attachments, review queue — is reachable without
waiting for this package to catch up:

```python
kx.request("GET", "/v1/analytics/summary")
kx.request("POST", "/v1/review/{id}/approve".format(id=memory_id))
```

Same auth, same retries, same error mapping; just untyped.

## Reference

| | |
|---|---|
| `remember(body, *, title, kind, sensitivity, importance, pinned, metadata, confidence, expires_at, embed_inline, force)` | store |
| `search(query, *, scopes, limit, embed_query)` | hybrid retrieval |
| `recall(query, *, scopes, synthesize, max_tokens, per_item_max, latency_budget_ms, token_budget)` | agentic retrieval |
| `get(memory_id)` / `list_memories(...)` | read |
| `update(memory_id, ...)` / `forget(memory_id)` | edit, soft-delete |
| `pin(memory_id)` / `unpin(memory_id)` / `bulk(action, ids)` | curate |
| `register(email, password, org_name)` / `login(email, password)` / `whoami()` | auth |
| `request(method, path, *, json, params)` | anything else |

Every method takes `scope=("project", 7)` to override the client default;
`search` and `recall` take `scopes=[...]` to span several.

Licensed Apache-2.0.
