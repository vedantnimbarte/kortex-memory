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

## Tool schemas

The MCP `list_tools` response advertises full JSON schemas. The client can
validate calls before sending them; the server treats unknown fields as an
input error (`InputValidationError`).

## Resources & prompts

(Planned for a follow-up minor release.)

- `kortex://memory/{id}` — read-only resource view of a memory.
- `kortex://session/{id}/summary` — resource view of a conversation summary.
- `kortex.recall` prompt — pre-shaped recall workflow.
