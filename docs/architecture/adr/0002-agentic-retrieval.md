# ADR 0002: Agentic retrieval over single-shot retrieval

- **Status:** Accepted
- **Date:** 2026-05-09

## Context

For AI coding agents, recall queries are often vague ("what did we decide
about caching?") and span scopes. A single hybrid call returns relevant rows
but misses cross-references; an LLM-only solution costs too much and can't
enforce tenancy.

## Decision

Adopt a **two-LLM, server-driven agent loop**: a planner LLM emits a
`QueryPlan` (Pydantic), a server-side executor runs each step through the
same tenant chokepoint, a cross-encoder reranks, and (optionally) a
summariser LLM writes a `ContextBundle` with citations.

Crucially, the planner does not execute — it returns structured steps the
server validates and runs. This keeps tenancy enforcement deterministic and
keeps token spend bounded.

## Consequences

- Recall p99 is dominated by planner latency; we cap hops (3) and candidates (200) to bound it.
- A clean fallback path: if the planner LLM is down or `KORTEX_AGENTIC_RETRIEVAL=false`, we run plain hybrid + rerank.
- Adapter Protocol (`LLM`) lets us swap providers per-tenant later (Anthropic, OpenAI, OpenRouter, Ollama).
