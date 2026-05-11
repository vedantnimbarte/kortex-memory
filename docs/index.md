# Kortex Memory

A production-grade, multi-tenant memory layer for LLM apps and AI coding agents
(Claude Code, Codex, OpenCode). Memories are stored in Postgres + S3, retrieved
via hybrid vector + BM25 + recency search, optionally planned by an LLM, and
served over REST, MCP (stdio + SSE), or the `kortex` CLI.

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
