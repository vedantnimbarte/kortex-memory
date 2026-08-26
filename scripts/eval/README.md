# Benchmarks

Measures what a Kortex deployment actually retrieves, over HTTP, so the numbers
describe the system as it runs rather than a library call.

## Quick check (no downloads)

```bash
make local-build && make local-run   # or ghcr.io/vedantnimbarte/kortex-local:main
export KORTEX_API_URL=http://localhost:8000
export KORTEX_API_KEY=kx_...          # kortex key create
python -m scripts.eval.run --suite synthetic --mode hybrid --mode agentic
```

The synthetic suite is generated deterministically and needs no dataset. It
measures the **plumbing** — ingest, embed, retrieve, rank — not long-context
memory quality. Use it to confirm the harness works and to catch regressions.
**Never publish synthetic numbers as a benchmark result.**

## Real suites

Neither dataset is redistributed here; download them from their authors.

| Suite | Where | `--data` |
|---|---|---|
| `longmemeval` | [xiaowu0162/LongMemEval](https://github.com/xiaowu0162/LongMemEval) (and the V2 repo) | the `longmemeval_s.json` / V2 equivalent |
| `locomo` | the LoCoMo release from its authors | the samples JSON |

```bash
python -m scripts.eval.run \
  --suite longmemeval --data data/longmemeval_s.json \
  --mode hybrid --mode agentic \
  --budget-ms 250 --budget-ms 1000 --budget-ms 4000 \
  --judge \
  --out eval-longmemeval.json
```

`--budget-ms` is repeatable and runs agentic mode once per latency ceiling.
That is what produces the accuracy-vs-latency frontier and the verdict the
report ends with — including, if it comes to that, "demote agentic to opt-in".
Without at least two budgets you get two dots and no curve.

`--limit N` caps instances while iterating; a full LongMemEval run ingests a
haystack per question and takes hours.

### Schemas the loaders expect

The loaders validate up front and name the missing keys rather than reading
`.get(...)` into empty strings, because a benchmark that runs to completion on
a misread file reports numbers that mean nothing.

- **LongMemEval** — a JSON list; each item needs `question_id`, `question`,
  `answer`, `haystack_sessions`, and optionally `haystack_session_ids`,
  `haystack_dates`, `answer_session_ids`, `question_type`. Without
  `answer_session_ids` there is no retrieval ground truth and only latency is
  reported.
- **LoCoMo** — a JSON list; each sample needs `conversation` (with `session_N`
  lists and optional `session_N_date_time`) and `qa` (each with `question`,
  and optionally `answer`, `evidence`, `category`).

If a dataset has changed shape, fix the loader in `datasets.py`. Do not make it
tolerant.

## What gets measured

**Retrieval** — `recall@k` and MRR against the gold documents. No LLM needed.
This says the right memory came back; it does not say the answer was right.

**Answer accuracy** — only with `--judge`, which synthesises answers and grades
them with the configured LLM. This is the number comparable with published
LongMemEval results.

The two are reported separately and never merged. A system can retrieve
perfectly and answer badly.

**Latency** — p50/p95/p99 of the end-to-end API call, per mode.

### Known gaps

- **Cost needs prices.** Recall reports `usage` with tokens and latency, but
  `cost_usd` is null unless `KORTEX_LLM_PRICES` is configured. Set it before a
  run if the table should carry dollars.
- **The judge is the model you configured.** Grading with the same family the
  system answers with is a known bias. Point `KORTEX_LLM_PROVIDER` at a
  different vendor for the judge if the number will be published as a
  comparison.

## Rules for publishing a number

1. Run both modes over the same corpus. The `corpus` fingerprint in the output
   proves they scored the same inputs.
2. Confirm embeddings finished. The harness warns when it queried before the
   queue drained; those answers are keyword fallback, not vector search, and
   the run should be discarded.
3. Publish the caveats with the table. `render_markdown` emits them for exactly
   this reason.
4. **Publish the result even when it is unflattering.** If agentic recall loses
   to plain hybrid, that is the finding, and the honest number buys more
   credibility than a favourable one nobody can reproduce.

## Regression gate

`tests/integration/test_retrieval_quality.py` runs a small fixture corpus in
normal CI and fails if recall drops below a floor. That is what catches a
retrieval regression on every PR; this harness is for the published numbers.
