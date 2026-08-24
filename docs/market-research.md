# Kortex Memory — Market Research & Product Strategy

**Date:** 2026-08-24 · **Author:** research pass over the live market + a code-level audit of this repo
**Assumptions locked with the requester:** all three ICPs researched and ranked · full competitor sweep (memory natives, platform-native memory, adjacent vector/RAG infra) · business model = **open-source core + managed cloud**

---

## 0. Method & sources

This is not a vibes report. Three evidence streams:

1. **Code audit of this repo** — every claim about what Kortex does or doesn't do below was verified by reading the source, not the README. File references are clickable.
2. **Competitor issue mining via the GitHub API** — open issues sorted by comment count and reactions across `mem0ai/mem0`, `getzep/graphiti`, `letta-ai/letta`, `topoteretes/cognee`, `supermemoryai/supermemory`. Issue threads are the highest-signal customer-review surface in dev tools: people only file when they're blocked, and reaction counts are a free vote.
3. **Primary discussion threads + vendor pricing pages** — Hacker News comment threads (fetched, not summarized from SEO blogspam), and the vendors' own pricing pages.

**Caveat on source quality, stated up front:** general web search for "Mem0 complaints reddit" returns almost entirely AI-generated comparison spam — dozens of near-identical "Mem0 vs Zep vs Letta 2026" listicles with recycled numbers. I discarded that layer and leaned on GitHub issues, HN threads, and vendor pricing pages, which are verifiable. Where a number comes only from secondary sources it is marked *(secondary)*.

---

## 1. What Kortex actually is today (verified against source)

| Capability | Status | Where |
|---|---|---|
| MCP server, stdio + HTTP/SSE, 16 tools | Shipped | [tools/](../packages/kortex-mcp/src/kortex_mcp/tools) |
| Hybrid retrieval: pgvector HNSW + BM25 + RRF + decay weighting | Shipped | [hybrid.py](../packages/kortex-core/src/kortex_core/retrieval/hybrid.py) |
| Agentic retrieval (LLM plans multi-hop), falls back to plain hybrid | Shipped | [agentic_retriever.py](../packages/kortex-core/src/kortex_core/services/agentic_retriever.py) |
| Short/mid/long tiers, decay, HDBSCAN consolidation | Shipped | [decay_policy.py](../packages/kortex-core/src/kortex_core/skills/decay_policy.py), [consolidator.py](../packages/kortex-core/src/kortex_core/skills/consolidator.py) |
| Org → Workspace → Project → Session tenancy, RBAC, sensitivity tiers | Shipped | [access_control.py](../packages/kortex-core/src/kortex_core/services/access_control.py) |
| Audit log model | Shipped | [audit.py](../packages/kortex-core/src/kortex_core/models/audit.py) |
| REST API w/ Idempotency-Key, ETag/If-Match, rate limit, body-size caps | Shipped | [middleware/](../packages/kortex-api/src/kortex_api/middleware) |
| Web console (recall, browse, ingest, keys, billing) | Shipped | `packages/kortex-web` |
| Stripe billing, plan caps | Shipped | [billing_service.py](../packages/kortex-core/src/kortex_core/services/billing_service.py), [plan_limits.py](../packages/kortex-core/src/kortex_core/security/plan_limits.py) |
| Helm chart, kustomize overlays, 6 Grafana dashboards, OTel | Shipped | `deploy/` |
| Export/import by scope (tar) | Shipped | [export_service.py](../packages/kortex-core/src/kortex_core/services/export_service.py) |

**Distribution reality check:** the GitHub repo is public with **2 stars** and **no `LICENSE` file** — `pyproject.toml` declares Apache-2.0 but GitHub reports `licenseInfo: null`. For an open-source-core strategy that is a blocking defect, not a nit (§7, P0-0).

For scale: Mem0 is at ~48K stars and claims 100K+ developers *(secondary)*. The product gap between Kortex and the leaders is **much smaller** than the distribution gap. Read the whole roadmap in §7 with that in mind — several of the highest-ROI items are distribution items, not features.

---

## 2. The category in 2026

The memory layer is the least standardized layer of the agent stack, and the three leaders don't agree on what the layer *is*:

- **Mem0** — background extraction pipeline; facts extracted from chat, promoted across scopes. Widest adoption, weakest at temporal correctness.
- **Zep / Graphiti** — temporal knowledge graph; entities are nodes, facts are edges with validity intervals, so facts *expire* rather than vanish. Best accuracy positioning, heaviest ops (Neo4j/FalkorDB).
- **Letta (MemGPT)** — agent runtime where the agent edits its own memory tiers. Self-host-first, but you adopt their whole runtime.
- **Cognee, Supermemory, Memobase** — fast followers; Cognee is aggressively courting the coding-agent harness market, Supermemory is winning the "easiest free tier" position.

**Funding / gravity:** Mem0 raised $24M (seed + Series A led by Basis Set), Letta raised a $10M seed at ~$70M post led by Felicis, backed by Jeff Dean and Clem Delangue *(secondary)*. This is a funded, crowded category. You will not out-spend it; you have to out-position it.

### Pricing landscape (from vendor pricing pages)

| Vendor | Free | Entry paid | Mid | Enterprise |
|---|---|---|---|---|
| **Mem0** | 10K add + 1K retrieval /mo, 1 project | **$19/mo** — 50K add / 5K retrieval | **$249/mo** Pro — 500K add / 50K retrieval, graph memory, consolidation | Custom: on-prem, SSO, audit logs, SLA |
| **Zep** | 10K credits/mo, 2 projects, 1 MCP seat | **$104/mo** (billed annually, $1,250/yr) — 50K credits, 5 projects | **$312/mo** — 200K credits, webhooks, analytics | Custom: BYOK, BYOC, SOC 2 Type II, HIPAA BAA, audit logs |
| **Letta** | 3 agents | ~$20/mo Pro | ~$200/mo *(secondary)* | Self-host free |
| **Supermemory** | Generous (1M tokens) *(secondary)* | — | Scale ~$399/mo with SOC 2 + HIPAA BAA *(secondary)* | — |
| **Kortex (today)** | 1K memories, 1 workspace | Pro: 100K memories | Team: 1M memories | — |

**Two exploitable holes in this table:**

1. **The $19 → $249 canyon.** Mem0 has nothing between hobbyist and $249. Zep's cheapest real plan is $104/mo *and demands an annual commitment*. A team that outgrows free has no $30–$100 option anywhere in the market.
2. **Everyone gates self-host/on-prem behind "Enterprise: call us."** Mem0 puts on-prem in Enterprise. Zep puts BYOC in Enterprise. Kortex ships a Helm chart and kustomize overlays in the open repo today. That is a genuine, defensible wedge — and it's currently unmarketed.

Kortex's free tier at **1,000 memories** is 10× stingier than Mem0's free tier. It will not convert; it will not even get tried. Reprice (§8).

### Benchmarks are now table stakes

Buyers in this category ask for numbers, and the evaluation bar moved in 2026:

- **LongMemEval-V2** scores *accuracy against latency* via a **LAFS Gain** metric — "average reachable accuracy over log-scaled latency budgets" from 1–200s. Baselines: RAG 51.0% @ 0.2s, AgentRunbook-R 58.6% @ 26.9s, Codex 69.9% @ 177.2s, AgentRunbook-C 74.9% @ 108.3s. The public leaderboard has **no external submissions yet**.
- Mem0 reports 94.4 on LongMemEval v1 at ~6.9K tokens/query *(secondary, vendor-published)*.

Kortex has **zero published retrieval-quality numbers**. [`scripts/bench_retrieval.py`](../scripts/bench_retrieval.py) is a *load* test (p99 < 1.2s @ 50 RPS), not a *quality* eval — a grep for `recall@`, `ndcg`, `mrr`, `precision@` across the repo returns nothing. Meanwhile the empty V2 leaderboard is a land-grab opportunity (§7, P0-4).

---

## 3. What users actually complain about — the evidence

Themes ranked by how often they recur *across independent competitors*. Cross-vendor recurrence is the strongest signal available: if Mem0, Cognee, and Supermemory users all file the same complaint, it's a category-level unmet need, not a vendor bug.

### T1 — Memories go stale and contradict each other (appears in 4 of 5 competitors)

- Mem0 [#5867](https://github.com/mem0ai/mem0/issues/5867) "ADD-only memory extraction can create conflicting memories"
- Mem0 [#4956](https://github.com/mem0ai/mem0/issues/4956) "ADD-only extraction in v3 may surface stale/contradictory facts for time-sensitive attributes"
- Cognee: "[hackathon] Memory task: RECONCILE / supersede (contradiction resolution)" (12 comments)
- Zep's entire moat is bitemporal edge validity — and third-party projects are filing research issues to copy the pattern
- HN, on a memory DB that does detect contradictions: *"contradictions are surfaced, not resolved... the agent has conversation context, the DB doesn't"* — with a critic noting *"You simply cannot tell [if something is contradictory] without understanding the broader context"* and *"Alice and Bob can both be CEO"*

**The nuance that matters:** users don't want the DB to *auto-resolve*. They want contradictions **surfaced at recall time** so the agent decides. That's a much cheaper build than a temporal knowledge graph.

**Kortex status:** `SUPERSEDES` and `CONTRADICTS` exist in [`db/types.py:67-68`](../packages/kortex-core/src/kortex_core/db/types.py) and the query planner can traverse them ([`query_plan.py:33`](../packages/kortex-core/src/kortex_core/retrieval/query_plan.py)) — **but nothing in the codebase ever writes them.** A grep for those constants returns only the enum definition and the planner's type literal. The rails are laid and no train runs on them. This is the single highest-leverage gap in the product.

### T2 — Silent write-path failure (Mem0 + Supermemory, high comment counts)

- Mem0 [#5245](https://github.com/mem0ai/mem0/issues/5245) "Silent memory loss when batch embedding partially fails in V3 add pipeline" — **20 comments, the most-discussed open issue in the repo**
- Mem0 [#5509](https://github.com/mem0ai/mem0/issues/5509) — the TypeScript counterpart of the same bug
- Supermemory: "Document ingest queue stuck at 'queued' — embeddings never process", "ingestion and search silently broken", "orphaning docs into a permanent retry-cron loop"

Users discover months later that memories they believed were stored never were. Trust in a memory product is binary — one silent loss and it's uninstalled.

**Kortex status:** at structural risk of the same failure class. Embedding happens in Celery workers; there is no ingest-status endpoint, no dead-letter queue, and no `doctor` command to prove the write path is healthy. Turning this into a *feature* ("every write is verifiable") is a marketing asset, not just a bugfix.

### T3 — Setup friction / one-command harness install (Mem0 + Cognee, explicitly requested)

- Mem0 [#5413](https://github.com/mem0ai/mem0/issues/5413) "Provide one-click hooks + MCP setup for Claude Code / Codex with self-hosted Mem0"
- Cognee: "One-command harness setup — `cognee install claude-code/cursor/opencode`" (11 comments)
- Cognee: "Hackathon [Feature]: Add Aider CLI memory integration" (17 comments)
- HN sentiment: *"Wow another day, another memory system for AI agents! How many are we up to now? Has to be hundreds of them."*

In a category with hundreds of options and severe reviewer fatigue, **time-to-first-recall is the product**. Two independent competitors have this as an open, unshipped request. Whoever ships it first owns the coding-agent segment.

**Kortex status:** the CLI ([`cmds/`](../packages/kortex-cli/src/kortex_cli/cmds)) has `auth`, `memory`, `key`, `ingest`, `export`, `attachment`, `admin` — no `init`, no harness integration, no hook installer. Onboarding today is: clone, `cp .env.example`, `uv sync`, `docker compose up` (7 services), run migrations, seed, create a key, hand-edit MCP JSON.

### T4 — English-only pipelines (Mem0 + Supermemory, with reaction votes)

- Mem0 [#4884](https://github.com/mem0ai/mem0/issues/4884) "BM25 keyword search and entity extraction are hardcoded to English"
- Supermemory: "make the local embedding model configurable (hard-coded `bge-base-en-v1.5` breaks non-English recall)" — **4 reactions**, one of the few reacted issues in that repo

**Kortex status: identically broken.** `to_tsvector('english', ...)` is hardcoded in the model definitions and migrations ([`models/memory.py:117`](../packages/kortex-core/src/kortex_core/models/memory.py), [`models/attachment.py:129`](../packages/kortex-core/src/kortex_core/models/attachment.py)) and in every query (`plainto_tsquery('english', :q)` in [`memory_repo.py:435-438`](../packages/kortex-core/src/kortex_core/repositories/memory_repo.py)). The default embedder is `BAAI/bge-large-**en**-v1.5`. Non-English users get degraded BM25 silently — the worst kind of failure, because search still returns *something*.

### T5 — Governance, PII, and memory poisoning (Supermemory FR + HN privacy pushback)

- Supermemory: "[Feature Request] Memory governance layer — PII redaction, context poisoning defense, and audit trail for memory retrieval"
- HN, to Mem0's founders: *"Over time, I can imagine there's going to be a lot of sensitive information being stored. How are you handling privacy?"* — Mem0 answered with LLM-based exclusion prompts, and got: *"Do you just rely on the LLM to follow instructions perfectly?"*
- Same thread: GDPR non-compliance flagged as an adoption blocker for European teams

Memory is a **prompt-injection persistence layer**. Poison a memory once and it's re-injected into every future session. Nobody in this category has shipped a credible answer.

**Kortex status:** sensitivity tiers × RBAC are real and genuinely ahead of the field. But a grep for `redact|pii|sanitiz|injection` across `packages/` hits only unrelated code. No write-time PII detection, no provenance-based trust scoring, no injection heuristics. Sensitivity tiers control *who reads what*; they don't control *what gets written*.

### T6 — Context pollution: too many memories make the agent worse (HN, repeatedly)

- *"you might want to have 5 or 10 [projects] in memory, each one made sense to have at the time... you pay for it by filling up your llm context"*
- *"All the 'memory' is manually curated in PROJECT, no messy consolidation, no Russian roulette."*
- *"It's either an agents.md with a high level summary, which is fairly useless for specific details... or something detailed... which seems to get ignored."*
- On atomic-fact extraction: *"facts are an incredibly dull and far too rigid tool"* — *"the extracted facts database was a complete mess of largely incomplete, invalid... sentences"*
- Contrast: *"temporal decay with configurable half-life lets unimportant memories fade like human memory does"* and *"duplicates per query (top-10): 0.9 → 0.0"* were the *praised* features in a competing Show HN.

The market has learned that **more memory is not better memory**. Decay, dedup, and write-gating are now selling points, not internals.

**Kortex status:** decay and consolidation are shipped and on the right side of this trend — and completely unmarketed. Dedup on write does not exist (grep for `dedup` in core hits only a billing comment). Write-gating does not exist: `remember` writes unconditionally.

### T7 — Agentic/LLM-driven retrieval is expensive and slow (HN)

- *"LLM-driven query [approaches are] incredibly expensive and slow"* compared to direct HNSW vector lookup
- Even Mem0's own framing concedes the tradeoff: 7–10s synchronous write mode *"which no production deployment should use"* *(secondary)*
- LongMemEval-V2's whole design — accuracy *per latency budget* — codifies that the market now prices latency, not just accuracy

**Kortex status:** agentic recall is the headline feature and the default path when an LLM key is configured. Correct fallback exists when the planner is unavailable, but there's no *budget-aware* mode: no "answer in <300ms or don't plan," no per-call cost reporting. Compare Mem0 [#2820](https://github.com/mem0ai/mem0/issues/2820) (8 reactions): "Include OpenAI Token Usage in All Relevant Method Responses." Users want to see what each recall cost.

### T8 — Self-hosting is broken or heavy everywhere (Supermemory + Graphiti + Mem0)

- Supermemory self-host: encrypted snapshot OOMs past ~150MB, snapshot re-serializes the whole DB every 10s (~60% sustained CPU), Linux binary missing a WASM module so ingestion is dead, env vars ignored, segfaults under concurrent load. **Nine separate self-host issues open.**
- Graphiti: Neo4j is a hard operational commitment; open issues on Ollama, Bedrock ([25 reactions](https://github.com/getzep/graphiti/issues) — the highest-reacted issue found anywhere in this sweep), FalkorDB quickstart failures
- Mem0: production Dockerfile hardening (missing `libpq5`, runs as root, `--reload` in prod), stale DockerHub images

**This is the biggest strategic opening in the entire report.** Every competitor's self-host story is either broken (Supermemory), heavy (Graphiti/Neo4j), or paywalled (Mem0 on-prem = Enterprise). Kortex is Postgres + Redis + S3 with a real Helm chart and Grafana dashboards, and does it *better than the funded incumbents* — while saying nothing about it.

Caveat: the current compose stack is 7 services (postgres, redis, minio, minio-init, api, mcp, worker, beat, web). "Better than Supermemory" isn't the bar; "`docker run` one container" is (§7, P1-8).

### T9 — Portability and lock-in

- Letta: "Conversation Import API for Agent Migration" (8 comments)
- Mem0 [#5863](https://github.com/mem0ai/mem0/issues/5863): "Difference in API surface between Platform mode and Standalone/OSS mode" — OSS users feeling second-class
- HN, on Mem0: *"Will you support the open source version as a first class citizen for the long term?"*
- A "Universal Memory Protocol — a shared format for agent memory" thread reached HN front page

**Kortex status:** export/import by scope already exists ([`export_service.py`](../packages/kortex-core/src/kortex_core/services/export_service.py)) — again shipped, again unmarketed, and with no *importers from competitors*.

### T10 — Scope/tenant leakage bugs (Mem0, many)

Mem0 [#6796](https://github.com/mem0ai/mem0/issues/6796) `add()` mutating the caller's filters and leaking scope into the next call and bypassing the required-scope check; MongoDB and Cassandra stores applying filters *after* the vector `top_k` so scoped users get too few or zero results; Weaviate silently dropping custom metadata filters; cross-scope entity linking in the TS SDK.

**Kortex status:** this is where Kortex is structurally strongest. `org_id` on every scoped row, a tenancy chokepoint enforced by a custom CI lint ([`tools/ruff_plugins`](../tools/ruff_plugins)). *Nobody knows.* "The memory layer that can't leak between tenants — enforced in CI" is a headline you have already paid for.

---

## 4. Segment ranking

### #1 — Solo devs / AI-coding-agent users → **adoption engine**

**Why first:** it's the only segment where Kortex's architecture is *structurally* differentiated rather than merely competitive. Every competitor scopes memory to a user or an agent; Kortex scopes it to Org → Workspace → Project → Session, which means **one memory shared across Claude Code, Codex, Cursor, and OpenCode on the same project** — the actual thing developers on HN say they want and can't find: *"I've been looking for a memory system that works the same for a while, so that I can switch away from Claude.ai to something else... but I just haven't found any."*

**Why it can't be the revenue engine:** these users won't pay much, and the free-tool competition is brutal (hundreds of MCP memory servers, plus Anthropic's native memory tool). They are the top of the funnel, and the OSS repo is the funnel.

**What they need that's missing:** `kortex init claude-code` (T3), write-gating (T6), sub-300ms recall (T7), one-container self-host (T8).

### #2 — Enterprise platform teams → **revenue engine**

**Why second in sequence but first in dollars:** multi-tenancy, RBAC, sensitivity tiers, audit log, idempotency/ETag, Helm, OTel, Prometheus, Grafana — Kortex has enterprise plumbing that Mem0 and Zep put behind "contact sales," and that Supermemory demonstrably does not have. Add PII governance (T5) and SSO and this is a sellable product to a bank's AI platform team *this year*.

**What blocks the sale today:** no SSO/OIDC/SAML (grep across `packages/` finds nothing), no SCIM, no SOC 2, no data-residency story, no BYOK, no PII redaction, no published benchmark. Procurement will ask for all seven.

### #3 — AI app builders (startups) → **defer**

**Why last:** most crowded, and Kortex is weakest here. These teams buy on SDK ergonomics and time-to-integration; Mem0 has Python + TypeScript SDKs, an AWS Agent SDK partnership, and 48K stars of Stack-Overflow-able surface area. **Kortex ships no client SDK at all** — `packages/` contains api, cli, core, mcp, web, worker and nothing else. A startup integrating today writes raw HTTP.

Serving them well means shipping and maintaining two SDKs plus framework adapters (LangChain, LlamaIndex, Vercel AI SDK) — a large ongoing surface for a segment where you'd be the 8th option. Enter later, on the back of enterprise credibility.

**Recommendation: build for #1, monetize #2, defer #3.** That maps exactly onto OSS-core + managed cloud: devs adopt free and self-hosted, platform teams pay for governance and SSO.

---

## 5. Positioning: where Kortex wins, ties, and loses

| Dimension | Kortex | Best competitor | Verdict |
|---|---|---|---|
| Multi-tenancy + RBAC + sensitivity tiers | Org/WS/Project/Session, CI-enforced chokepoint | Mem0 (scope filters, leaking — [#6796](https://github.com/mem0ai/mem0/issues/6796)) | **Win — big, unmarketed** |
| Self-host quality | Compose + Helm + kustomize + 6 dashboards | Graphiti (needs Neo4j), Supermemory (broken) | **Win — big, unmarketed** |
| Ops maturity (OTel, idempotency, ETag, ratelimit) | Shipped day one | Mem0 (Dockerfile still runs as root) | **Win** |
| Single-datastore simplicity (Postgres) | pgvector + tsvector, one DB | Zep needs a graph DB | **Win** |
| Coding-agent-native, cross-tool shared memory | MCP-first, project-scoped | Cognee (chasing it, unshipped) | **Win — narrow window** |
| Temporal correctness / contradiction handling | Enum exists, never written | Zep (bitemporal edges) | **Lose — biggest gap** |
| Published quality benchmarks | None | Mem0, Zep, and now an open V2 leaderboard | **Lose** |
| Client SDKs (Python/TS) | None | Mem0, Zep, Letta, Supermemory all have both | **Lose** |
| Time-to-first-recall | ~20 min, 7 services | Supermemory/Mem0 free tier: minutes | **Lose** |
| Free-tier generosity | 1K memories | Mem0 10K adds, Supermemory 1M tokens | **Lose** |
| Multilingual | Hardcoded English | Everyone (same bug) | **Tie — at parity, and it's an open flank** |
| PII / injection governance | None | Nobody | **Tie — open category** |
| Community gravity | 2 stars, no LICENSE file | Mem0 ~48K | **Lose — decisively** |

**Honest read:** Kortex is a better-engineered product than most of the field and an unknown one. The strategy must weight distribution above features.

### The platform threat, sized

Anthropic's memory tool (`memory_20250818`) plus context editing gives Claude a file-based memory directory in *your* infrastructure, with reported 84% token reduction over a 100-turn eval, available on the Claude Developer Platform, Bedrock, and Vertex. That eats the low end: single-user, single-tool, single-machine memory. Free and built-in beats good and installed, every time.

**It does not eat:** shared memory across *different* agent vendors, multi-tenant RBAC, sensitivity tiers, audit trails, server-side retrieval quality, or team/org-scoped memory. Position deliberately **above** the native tool, never against it: *"Claude's memory tool is per-agent files. Kortex is your org's memory — shared across Claude Code, Codex, and Cursor, access-controlled, auditable."* Better still, **support it**: expose Kortex as a memory-tool backend so the native path writes into Kortex.

---

## 6. The one-sentence positioning

> **Kortex is the memory layer you can actually run yourself — one Postgres, tenant-isolated by construction, shared across every coding agent your team uses.**

Three proof points, all already true or one sprint away: (1) the CI-enforced tenancy chokepoint, (2) `docker run` self-host that outperforms funded competitors', (3) one memory shared across Claude Code + Codex + Cursor.

---

## 7. Roadmap — add / enhance / replace

Ordered by **evidence strength × leverage ÷ effort**. Effort is engineer-weeks for one competent engineer.

### P0 — Do these first (weeks 0–6)

**P0-0 · Add a `LICENSE` file. — 5 minutes.**
`pyproject.toml` says Apache-2.0; GitHub reports no license, which legally reads as all-rights-reserved. No company will adopt, and no OSS-core strategy exists, until this file lands. *This is the highest ROI line in the document.*

**P0-1 · `kortex init <harness>` — one command to first recall. — 1.5 weeks.**
`kortex init claude-code|codex|cursor|opencode` writes the MCP server config, installs session hooks, creates a scoped key, and runs a verification recall. Ship `docker run kortex/kortex:local` (embedded SQLite/pgvector-lite or single-container Postgres) so the zero-config path needs no compose file.
*Evidence:* Mem0 [#5413](https://github.com/mem0ai/mem0/issues/5413), Cognee's one-command harness issue (11c) and Aider integration (17c) — **two competitors have this open and unshipped**. T3.

**P0-2 · Contradiction surfacing at recall. — 2.5 weeks.**
On write, embed and check the top-k nearest memories in the same scope; when an LLM (or a cheap NLI classifier) judges the new memory to conflict, write a `CONTRADICTS` edge and, when it's a clean replacement, `SUPERSEDES`. At recall, return conflicting memories **together, flagged, newest first, with timestamps** — surface, don't resolve. The enum, the relation table, and the planner's traversal already exist; only the writer is missing.
*Evidence:* T1 — four independent competitors, and HN's explicit guidance that surfacing beats auto-resolution. This is also the cheapest available answer to Zep's temporal moat: bitemporal correctness for 90% of cases without adopting a graph database.

**P0-3 · Write-path integrity: dead-letter queue, ingest status, `kortex doctor`. — 1.5 weeks.**
Per-item ingest status endpoint, DLQ for failed embeddings with retry/inspect, partial-batch failures surfaced instead of swallowed, and `kortex doctor` proving the round trip end to end. Market it: *"every write is verifiable."*
*Evidence:* T2 — Mem0's single most-discussed open issue (20 comments) plus its TS twin, plus five Supermemory issues in the same failure class.

**P0-4 · Publish a real benchmark. — 2 weeks.**
Run LongMemEval-V2 and LoCoMo; publish accuracy **and** p50/p95 latency; commit the harness under `scripts/eval/` so anyone can reproduce it. Submit to the V2 leaderboard while it is still empty of external entries. Report *both* modes: hybrid-only and agentic.
*Evidence:* HN — *"Did you check if this leads to any actual benefits? If so, how did you benchmark it?"*; the LAFS metric; the empty leaderboard. Without numbers Kortex cannot be compared, and uncomparable means unbought.

**P0-5 · Reprice the free tier. — 1 day.**
1K memories → 25K memories + 10K recalls/mo. Today's cap is 10× below Mem0's free tier; it guarantees no evaluation ever completes. ([`plan_limits.py`](../packages/kortex-core/src/kortex_core/security/plan_limits.py))

**P0-6 · Say the true things out loud. — 3 days (docs/site work).**
Three claims already earned and never made: CI-enforced tenant isolation; self-host that beats the funded competition; decay + consolidation as *anti-pollution* features. Plus a comparison page against Mem0/Zep/Letta with the self-host and on-prem-pricing columns filled in honestly.

### P1 — Next (weeks 6–16)

**P1-7 · Multilingual: per-project text search config + multilingual embedder. — 1.5 weeks.**
Make `to_tsvector('english', …)` a per-project setting (`regconfig` column, generated column rebuilt on change) and add `BAAI/bge-m3` to the embedder registry. Kortex has exactly the bug two competitors are being yelled at for; being the only one *without* it is cheap differentiation. T4.

**P1-8 · Shrink the default self-host footprint. — 1.5 weeks.**
Make attachments/S3 optional with a local-filesystem driver (drops MinIO + minio-init), fold beat into the worker, and ship a `compose.minimal.yaml`: postgres + redis + one app container. Keep the full stack for production. T8.

**P1-9 · Budget-aware recall + cost reporting. — 2 weeks.**
`recall(latency_budget_ms=300)` skips the planner and serves hybrid-only; the planner engages only when the budget allows or the query is genuinely multi-hop. Return `usage: {tokens_in, tokens_out, cost_usd, plan_steps, latency_ms}` on every recall — the LLM adapters already capture token counts ([`llm/anthropic.py:87`](../packages/kortex-core/src/kortex_core/llm/anthropic.py)), they're just not surfaced.
*Evidence:* T7, plus Mem0 [#2820](https://github.com/mem0ai/mem0/issues/2820) (8 reactions).

**P1-10 · Write-gating + memory review queue in the console. — 2.5 weeks.**
`remember(confidence=…)` routes low-confidence writes to a pending queue; the console gets approve/reject/merge/forget with a diff view, and the audit log records who approved what. Kortex is one of the few products in this category with a real web console — turn it into the governance surface nobody else has.
*Evidence:* T6 — *"expose what 'memories' have been stored... so that humans can review and verify it over time"*, *"no messy consolidation, no Russian roulette"*, and the write-gated-memory Show HN.

**P1-11 · Dedup on write. — 1 week.**
Cosine-similarity near-duplicate check before insert; merge or increment `access_count` instead of inserting. *Evidence:* T6 (*"duplicates per query (top-10): 0.9 → 0.0"* was the headline praised result for a competitor), Letta's archival dedup FR.

**P1-12 · PII redaction + memory-poisoning defense. — 3 weeks.**
Pluggable write-time detector (Presidio or regex+NER) that redacts or auto-escalates sensitivity; provenance-based trust (memories originating from tool output or fetched web content marked lower-trust and excluded from high-sensitivity recalls); injection heuristics on ingested content. Ship as a `Skill` alongside the existing `access_policy`/`importance_scorer` protocols — the plugin architecture is already there.
*Evidence:* T5 — Supermemory's governance FR, HN's unanswered privacy pushback at Mem0, GDPR as a stated blocker. **No competitor has shipped this.** It is simultaneously the enterprise wedge and a category-defining claim.

**P1-13 · Embedder/LLM breadth: Bedrock, Voyage, Ollama-embeddings. — 1 week.**
Bedrock support is the highest-reacted issue found anywhere in this sweep (25 reactions on Graphiti). The registry pattern in [`embeddings/registry.py`](../packages/kortex-core/src/kortex_core/embeddings/registry.py) makes each adapter small. Also unblocks air-gapped enterprise.

### P2 — Then (months 4–6)

**P2-14 · Enterprise gate-openers: SSO/OIDC + SCIM, audit-log export (SIEM), BYOK, data residency, SOC 2 kickoff. — 6–8 weeks.**
The audit model exists; export, retention, and immutability do not. All seven procurement questions from §4 answered together, or the enterprise motion doesn't start.

**P2-15 · Python + TypeScript client SDKs. — 3 weeks.**
Generate from the OpenAPI schema, then hand-polish ergonomics. Deliberately *after* P0/P1: SDKs serve ICP #3, and a generated SDK over a shifting API is churn.

**P2-16 · Competitor importers + a portability promise. — 1.5 weeks.**
`kortex import --from mem0|zep|letta|json`. Pair with a public commitment: full export, no proprietary format, OSS is first-class. Turns competitors' lock-in anxiety (T9, Mem0 [#5863](https://github.com/mem0ai/mem0/issues/5863)) into your acquisition channel.

**P2-17 · Be a backend for Anthropic's memory tool. — 2 weeks.**
Implement the `memory_20250818` file-tool interface over Kortex scopes so Claude's native memory writes land in Kortex — governed, shared, auditable. Converts the biggest platform threat into a distribution channel.

### Replace / cut / don't build

| Don't | Why |
|---|---|
| **A Neo4j-style knowledge graph** | Zep's differentiator is also Zep's ops tax and Graphiti's top complaint source. The relation table + pgvector delivers most of the value; contradiction edges (P0-2) close the gap that actually matters. Keep "one Postgres" as the pitch. |
| **Agentic recall as the unconditional default** | HN: *"incredibly expensive and slow."* Demote to a budgeted mode (P1-9). Keep it as the premium/complex-query path — it's genuinely good, just wrongly defaulted. |
| **HDBSCAN consolidation, unmeasured** | Real compute cost, unproven retrieval benefit. Gate it behind P0-4: if the eval doesn't show consolidation improving recall, cut or simplify to periodic summary. |
| **Attachments + S3 as a headline capability** | It's the single biggest source of self-host friction (MinIO + init job) and it isn't why anyone buys a memory layer. Keep it, demote it, make it optional (P1-8). |
| **Framework adapters (LangChain, LlamaIndex, …) now** | ICP #3 surface. Maintenance-heavy, low differentiation, and premature before the SDKs exist. |
| **Chasing Mem0 on benchmark headline numbers** | You will not out-market a funded incumbent's blog. Compete on the *latency-accuracy frontier* (LAFS) and on governance, where the leaderboard is empty and the field is absent. |

---

## 8. Packaging for OSS-core + managed cloud

**License split.** Apache-2.0 for everything currently in the repo (and *actually add the file*). Put P2-14 enterprise features — SSO/SCIM, SIEM audit export, BYOK, data-residency controls — in an `ee/` directory under a source-available enterprise license. That is the standard, well-tolerated split (GitLab, Sentry-style). Do **not** retro-license shipped code; the OSS-first promise is the whole acquisition strategy, and Mem0 [#5863](https://github.com/mem0ai/mem0/issues/5863) shows how fast OSS users notice being treated as second-class.

**Cloud ladder** — built to occupy the $19→$249 canyon and to make self-host a funnel rather than a leak:

| Tier | Price | Contents |
|---|---|---|
| **Self-host** | Free forever, Apache-2.0 | Everything except `ee/`. No memory caps, no phone-home. This is marketing spend, not lost revenue. |
| **Cloud Free** | $0 | 25K memories, 10K recalls/mo, 1 project. Beats Mem0's free tier — the cheapest competitive move available (P0-5). |
| **Cloud Dev** | $29/mo | 250K memories, 100K recalls, unlimited projects, agentic recall. *Nothing exists at this price point anywhere in the market.* |
| **Cloud Team** | $199/mo | 3 seats (+$29/seat), 2M memories, review queue + governance console, PII redaction, 30-day audit retention. |
| **Enterprise** | Custom | Self-host license or BYOC, SSO/SCIM, SIEM export, BYOK, data residency, SLA, SOC 2. Anchor against Zep's Enterprise, which starts effectively at $1,250/yr for Flex. |

**Meter memories + recalls, not "credits."** Zep's credit system draws complaints for being unpredictable; Mem0's add/retrieval split is legible. Copy the legible one.

---

## 9. Risks

1. **Distribution, not product, is the binding constraint.** 2 stars vs ~48K. If the plan is all engineering and no launch, none of it matters. P0-1 + P0-4 + P0-6 exist to produce a *launchable artifact*: a one-command install with published numbers and a claim nobody else can make. Budget real time for Show HN, the MCP directories, and the coding-agent communities.
2. **Reviewer fatigue is severe.** *"Another day, another memory system... has to be hundreds of them."* A generic "memory for agents" launch will be ignored. Lead with the specific, verifiable, unusual claim (tenant isolation enforced in CI; benchmark numbers; one-container self-host), never with the category.
3. **Anthropic/OpenAI keep eating the low end.** Mitigate by owning what platforms structurally can't: cross-vendor, multi-tenant, governed, auditable memory (§5), and by integrating rather than competing (P2-17).
4. **Solo maintainer, wide surface.** Six packages, Helm, kustomize, 6 dashboards, a Stripe integration, and 22 test files. The cut list in §7 exists to buy back capacity — the fastest way to fund P0 is to stop widening.
5. **Agentic recall could become a liability.** If the benchmark shows it losing on the LAFS frontier to plain hybrid, say so publicly and demote it. Publishing an unflattering-but-honest number buys more credibility in this fatigued market than another vendor-favorable chart.

---

## 10. Open questions for you

1. **Is there any real usage yet** — your own daily use, design partners, private pilots? Zero-user product decisions are guesses; ten users' complaints outrank this entire document.
2. **Enterprise motion: do you have a design partner?** P2-14 is 6–8 weeks of unpleasant work. Do it against a named prospect, or not yet.
3. **Hosted infra appetite.** Cloud Free at 25K memories means eating embedding compute for non-payers. Local BGE keeps that near-zero on CPU-bound workers, but it's a real cost line to plan.
4. **How much of the agentic-retrieval investment is emotional?** It is the most novel thing here and, on current market evidence, likely the wrong default. P0-4 settles it with data — commit in advance to following the number.
5. **Time budget.** P0 is ~7 engineer-weeks. If it's nights-and-weekends, cut to P0-0, P0-1, P0-5, P0-6 (about 2.5 weeks) — a licensed repo, a one-command install, a usable free tier, and honest marketing of what's already built. That alone changes the trajectory more than any feature in P1.

---

## Sources

**Competitor issue trackers (GitHub API, fetched 2026-08-24):** [mem0ai/mem0](https://github.com/mem0ai/mem0/issues) · [getzep/graphiti](https://github.com/getzep/graphiti/issues) · [letta-ai/letta](https://github.com/letta-ai/letta/issues) · [topoteretes/cognee](https://github.com/topoteretes/cognee/issues) · [supermemoryai/supermemory](https://github.com/supermemoryai/supermemory/issues)

**Hacker News threads (comments fetched):** [Open source memory layer so any AI agent can do what Claude.ai and ChatGPT do](https://news.ycombinator.com/item?id=47897790) · [Everyone's trying vectors and graphs for AI memory. We went back to SQL](https://news.ycombinator.com/item?id=45329322) · [Show HN: Mem0 — open-source Memory Layer for AI apps](https://news.ycombinator.com/item?id=41447317) · [Show HN: A memory database that forgets, consolidates, and detects contradiction](https://news.ycombinator.com/item?id=47767119) · [Show HN: Total Recall — write-gated memory for Claude Code](https://news.ycombinator.com/item?id=46907183) · [Universal Memory Protocol — a shared format for agent memory](https://news.ycombinator.com/item?id=48428796)

**Vendor pricing (fetched):** [Mem0 pricing](https://mem0.ai/pricing) · [Zep pricing](https://www.getzep.com/pricing)

**Benchmarks:** [LongMemEval-V2](https://xiaowu0162.github.io/longmemeval-v2/) · [LongMemEval (ICLR 2025)](https://github.com/xiaowu0162/longmemeval)

**Platform:** [Managing context on the Claude Developer Platform](https://www.anthropic.com/news/context-management) · [Memory tool docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)

**Secondary (AI-generated comparison content, used only for figures marked *(secondary)*):** [Mem0 Series A](https://mem0.ai/series-a) · [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026) · [Developers Digest vendor comparison](https://www.developersdigest.tech/blog/best-ai-agent-memory-providers-2026) · [Vectorize: Mem0 vs Zep](https://vectorize.io/articles/mem0-vs-zep)
