# MCP

## Transports

| Mode | Use | Auth |
|---|---|---|
| `kortex-mcp stdio` | Local agents (Claude Code, Codex) — launched as subprocess | `KORTEX_API_KEY` env |
| `kortex-mcp serve` | Remote agents over HTTP+SSE | `Authorization: Bearer kx_*` per connection |

## Tool surface

16 tools, all going through the same kortex-core repo + service stack as REST:

| Tool | Notes |
|---|---|
| `remember` | Create a memory; pass `embed_inline=true` to embed at write time. |
| `recall` | Agentic retrieval; falls back to plain hybrid when no planner LLM is configured. |
| `search_memory` | Plain hybrid retrieval (vector + BM25 + RRF + decay). |
| `get_context_bundle` | Like `recall` but always synthesises a cited answer. |
| `get_memory`, `list_memories`, `update_memory`, `delete_memory` | Memory CRUD. |
| `link_memories`, `pin_memory` | Graph + pin ops. |
| `start_session`, `end_session`, `list_sessions` | Session lifecycle. |
| `attach_file`, `finalize_attachment`, `get_attachment` | Two-step presign + finalize upload flow. |

## Conflicts on retrieval results

Every hit returned by `search_memory`, `recall`, and `get_context_bundle` carries a
`conflicts` array — the memories that supersede or contradict it:

```json
{
  "public_id": "…", "title": "Job queue", "body": "The job queue runs on Postgres.",
  "conflicts": [
    {
      "public_id": "…",
      "title": "Queue migration",
      "relation": "superseded_by",
      "created_at": "2026-08-25T10:14:00+00:00"
    }
  ]
}
```

`relation` is stated from the annotated memory's point of view:

| Value | Meaning |
|---|---|
| `superseded_by` | **This memory is stale.** Prefer the one named in the note. |
| `supersedes` | This memory replaced the one named in the note. |
| `contradicts` | The two cannot both be true; neither is clearly newer. |

A memory superseded by another memory *in the same result page* is sorted last, so the current
state of the world reads first. Nothing is ever filtered out — deciding which side of a
contradiction holds needs conversation context that only the agent has. `created_at` is included
so that decision can be made without another round trip.

## Duplicate writes

`remember` folds a repeat into the memory that already holds it. Writing the
same normalised title+body to the same scope returns the existing memory with
`deduped: true` rather than storing a second copy — so an agent that
re-remembers a fact across sessions does not pay context tokens to read the
same sentence twice in later recalls.

The repeat counts as an access, which feeds the decay score and keeps a
re-confirmed memory from fading. Metadata is merged into the survivor.

Matching is exact on normalised content: whitespace is collapsed and Unicode is
folded to NFKC, but **case is preserved** and **paraphrases are not matched** —
"We use Redis for the queue" and "the queue runs on Redis" are two memories.
Catching those needs a vector comparison, which needs an embedding, which does
not exist yet at write time.

Pass `force: true` for a deliberate second copy. Turn the whole thing off with
`KORTEX_DEDUP_ON_WRITE=false`.

## Budgets and cost on recall

`recall` and `get_context_bundle` accept two optional caps:

| Field | Meaning |
|---|---|
| `latency_budget_ms` | Wall-clock ceiling for the whole call. 0 = unlimited. |
| `token_budget` | Ceiling on LLM tokens spent planning and synthesising. 0 = unlimited. |

Agentic recall plans with an LLM before retrieving, which buys multi-hop
reasoning and costs a model round trip. Below roughly 1500ms
(`KORTEX_RETRIEVAL_PLANNER_MIN_BUDGET_MS`) that round trip cannot fit, so the
call **degrades to plain hybrid retrieval** — the same path taken when no
planner is configured — rather than overshooting a budget the caller set
deliberately. `plan_rationale` always says which happened, so a fast hybrid
answer is distinguishable from a broken planner.

Every response carries `usage`:

```json
{
  "usage": {
    "mode": "agentic",
    "tokens_in": 1180, "tokens_out": 240, "total_tokens": 1420,
    "llm_calls": 2, "plan_steps": 3, "hops": 2,
    "latency_ms": 2317.4,
    "cost_usd": 0.00214,
    "budget_exhausted": false
  }
}
```

`cost_usd` is **null** unless the operator has configured prices via
`KORTEX_LLM_PRICES` (model id → `[input, output]` USD per million tokens).
Null means unpriced, not free — model pricing varies by contract and is zero
for self-hosted models, so Kortex reports tokens and lets the operator
multiply rather than shipping a table that goes stale.

`budget_exhausted` is true when a cap cut the work short, which lets a caller
tell a fast answer from a truncated one.

## Tool schemas

The MCP `list_tools` response advertises full JSON schemas. The client can
validate calls before sending them; the server treats unknown fields as an
input error (`InputValidationError`).

## Resources & prompts

(Planned for a follow-up minor release.)

- `kortex://memory/{id}` — read-only resource view of a memory.
- `kortex://session/{id}/summary` — resource view of a conversation summary.
- `kortex.recall` prompt — pre-shaped recall workflow.
