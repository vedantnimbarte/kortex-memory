# Kortex Memory

**The memory layer you can actually run yourself — one Postgres,
tenant-isolated by construction, shared across every coding agent your team
uses.**

Memories are stored in Postgres (+ optional S3), retrieved via hybrid vector +
BM25 + recency search, optionally planned by an LLM, and served over REST, MCP
(stdio + SSE), or the `kortex` CLI. Scoping is Org → Workspace → Project →
Session, with `org_id` on every scoped row and a tenancy chokepoint enforced by
a CI lint — so one memory can be shared across Claude Code, Cursor, Codex and
OpenCode without leaking across tenants.

## What's here

| Surface | Use it for |
|---|---|
| **REST** (`kortex-api`) | Web apps, custom integrations, dashboards |
| **MCP stdio** | Local agents (Claude Code, Codex, OpenCode) |
| **MCP SSE** | Remote agents over HTTP with per-key auth |
| **CLI** (`kortex`) | Admin + day-to-day ops |

## Why agentic retrieval?

A single hybrid query gets you 80% of the way; the last 20% requires the
planner to decide whether to fan out across scopes, walk memory_links, or
expand attachment chunks. Kortex's planner emits a structured `QueryPlan` and
the agent loop executes it through the same tenant-safe repository chokepoint,
so the planner can't escape org boundaries.

See [Architecture → Overview](architecture/overview.md) for the full design.

## Quickstart

```sh
pip install kortex-cli
kortex auth login
# wire Claude Code to:
kortex-mcp stdio
```

Full setup in [Quickstart](quickstart.md).
