# Scaling

## API

Two scaling signals are wired through the HPA:

- CPU utilization (default 70%)
- Custom Prometheus metric `kortex_api_requests_per_second` (default target 150 RPS/pod)

For traffic over 1k RPS, raise `api.replicas` and `api.hpa.maxReplicas`; sit the
deployment behind a CDN that respects `Cache-Control: private, no-cache`.

## Worker

The worker scales on Redis queue depth (`redis_queue_depth{queue="embed"}` by
default). Bump `worker.hpa.queueDepthTarget` higher to absorb spiky ingestion
without thrashing pods.

## DB

`pgvector` HNSW indexes have non-trivial build cost. When loading >1M memories
in bulk, drop the index, ingest, then `CREATE INDEX` once. The migration
already configures HNSW with `m=16, ef_construction=64`; tune `ef_search` at
query time via `SET hnsw.ef_search = 100`.

## MCP

Stateless. Scale on CPU. For very high concurrent agent count, consider
running multiple MCP deployments behind a hash-based load balancer (per
`Authorization` header) so a single agent's traffic stays on one pod for the
duration of its SSE connection.

## Choosing an embedder

`KORTEX_EMBEDDER` selects the adapter. All of them must produce
**1024-dimensional** vectors, because that is the width of every vector column
in the schema — see below.

| Value | Model default | Needs | Use when |
|---|---|---|---|
| `local_bge` | `BAAI/bge-large-en-v1.5` | `kortex-core[embeddings-local]` (~2 GB) | Default. No egress, no per-token cost, but the model has to load. |
| `openai` | `text-embedding-3-large` | `kortex-core[embeddings-openai]`, `KORTEX_OPENAI_API_KEY` | You already send data to OpenAI. Truncated to 1024 via Matryoshka. |
| `voyage` | `voyage-3` | `KORTEX_VOYAGE_API_KEY` | Retrieval-tuned embeddings; natively 1024. |
| `ollama` | `mxbai-embed-large` | a reachable `ollama serve` | Air-gapped or cost-sensitive self-host. No key, no egress. |
| `bedrock` | `amazon.titan-embed-text-v2:0` | `kortex-core[storage-s3]`, AWS credentials, `KORTEX_AWS_REGION` | The data must stay in an existing AWS account under an existing agreement. |

Voyage and Ollama need no extra package — both are plain HTTP. Bedrock reuses
the `aiobotocore` client stack that the S3 storage backend already installs.

### The 1024 constraint

`memories.embedding`, `attachment_chunks.embedding` and
`conversations.summary_embedding` are all `VECTOR(1024)`. Postgres rejects a
vector of any other length, so an embedder of the wrong width does not degrade
quality — it stops writes entirely.

Adapters therefore refuse to construct at the wrong width and say what to do
about it. Ollama gets a second check on the first response, because it serves
whatever model was pulled and only the response proves the width
(`nomic-embed-text` is 768 and will not fit; `mxbai-embed-large` is 1024).

Changing the width is a migration of all three columns plus a full re-embed:

```bash
kortex admin reindex-embeddings   # clears every vector; embed_pending refills
kortex admin ingest-status        # watch the queue drain
```

### Switching embedder

Vectors from different models are not comparable, so a switch invalidates the
whole corpus. `embed_pending` already re-embeds anything whose
`embedding_model` differs from the configured one, so the transition is
gradual — but recall quality is mixed until it finishes. Watch
`kortex_embed_pending` and expect degraded results in the meantime.

### Choosing an LLM provider

`KORTEX_LLM_PROVIDER` selects the planner and summariser backend:
`anthropic`, `openai`, `openrouter`, `ollama`, `bedrock`.

Bedrock uses the Converse API, so token usage is reported uniformly and feeds
recall's `usage.cost_usd` (once `KORTEX_LLM_PRICES` is set). Its structured
output is best-effort — Converse enforces no schema, so JSON is requested in
the system prompt and parsed defensively. Retrieval planning falls back to
plain hybrid when that parse fails, so the failure mode is degraded, not
broken; a caller that needs guaranteed structure should point at Anthropic or
OpenAI.
