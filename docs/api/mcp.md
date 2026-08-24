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

## Tool schemas

The MCP `list_tools` response advertises full JSON schemas. The client can
validate calls before sending them; the server treats unknown fields as an
input error (`InputValidationError`).

## Resources & prompts

(Planned for a follow-up minor release.)

- `kortex://memory/{id}` — read-only resource view of a memory.
- `kortex://session/{id}/summary` — resource view of a conversation summary.
- `kortex.recall` prompt — pre-shaped recall workflow.
