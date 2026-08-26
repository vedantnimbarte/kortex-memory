# Benchmarks

> **Status: no results published yet.** The harness is built and tested; the
> numbers are not measured. This page exists so that when they are, there is
> one place to put them — and so nobody has to guess in the meantime.
>
> Anyone claiming Kortex's retrieval quality today is guessing, including us.

## Why this page is empty

Producing a comparable number needs three things at once: the LongMemEval /
LoCoMo corpora, a running deployment with an embedder, and a judge model to
grade answers. That is a machine with Docker, disk, and an API key — a run, not
a code change.

The harness is the part that could be built without those, and it is done:
[`scripts/eval/`](https://github.com/vedantnimbarte/kortex-memory/tree/main/scripts/eval).

## What will be reported

Two families of number, kept separate:

| Family | Needs | Says |
|---|---|---|
| **Retrieval** — recall@k, MRR | nothing beyond a running Kortex | the right memory came back |
| **Answer accuracy** — judged | a judge model (`--judge`) | the answer was right |

They are not interchangeable. A system can retrieve perfectly and answer badly,
and a table that merges them is the kind of vendor-favourable summary this
benchmark exists to avoid.

Alongside both: **p50/p95/p99 latency**, measured end-to-end over HTTP, for
`hybrid` and `agentic` modes on the same corpus.

### The frontier, and the decision that hangs on it

Agentic recall buys accuracy with latency and tokens. Whether that trade is
worth making cannot be answered by one agentic run at one latency — a single
disappointing number cannot tell "the mode is bad" apart from "the mode was
under-budgeted".

So the harness sweeps. `--budget-ms` is repeatable and runs agentic once per
latency ceiling; the report renders the curve plus a computed verdict:

```
| budget (ms) | accuracy | p95 (s) | vs hybrid |
|---|---|---|---|
| — (hybrid)  |   …      |   …     | baseline  |
| 250         |   …      |   …     |    …      |
| 1000        |   …      |   …     |    …      |
| 4000        |   …      |   …     |    …      |
```

The verdict is computed rather than eyeballed, deliberately. The temptation on
reading a disappointing table is to find a reason it does not count, and a
sentence written before anyone has seen the numbers is harder to argue with
than one written after. If agentic loses at every budget, the harness says so
and names the change: `KORTEX_AGENTIC_RETRIEVAL=false`, demoting it to opt-in.

It also refuses to conclude where it should. A suite with no ground truth and
no judge, or a sample under 30 questions, gets "not decidable" or an explicit
"indicative, not conclusive" instead of a verdict.

## Results

_None yet._ When a run completes, paste the table `scripts.eval.run` prints,
with its caveats, under a heading naming the suite, the deployment, and the
commit.

```
| mode | questions | recall@1 | recall@5 | MRR | accuracy | p50 (s) | p95 (s) | p99 (s) |
```

## How to produce them

```bash
# 1. A deployment to measure
docker run -d --name kortex-local -p 8000:8000 -v kortex-data:/data kortex/kortex:local

# 2. Wait for the write path to be healthy — querying before embeddings finish
#    measures the keyword fallback and reports it as vector search
kortex doctor

# 3. Run both modes over the same corpus
export KORTEX_API_URL=http://localhost:8000 KORTEX_API_KEY=kx_...
python -m scripts.eval.run \
  --suite longmemeval --data data/longmemeval_s.json \
  --mode hybrid --mode agentic \
  --budget-ms 250 --budget-ms 1000 --budget-ms 4000 \
  --judge \
  --out eval-longmemeval.json
```

Set `KORTEX_LLM_PRICES` first if the table should carry dollars, and start with
`--limit 20` to confirm the pipeline works before committing to a run that
ingests a haystack per question and takes hours.

Full instructions, dataset sources, and the expected schemas are in
[`scripts/eval/README.md`](https://github.com/vedantnimbarte/kortex-memory/blob/main/scripts/eval/README.md).

### Rules for what goes on this page

1. Both modes, same corpus. The `corpus` fingerprint in the output proves it.
2. Embeddings finished. The harness warns when they had not; discard that run.
3. Caveats published with the table, not omitted for tidiness.
4. **Unflattering results get published too.** If agentic recall loses to plain
   hybrid on the accuracy-latency frontier, that is the finding, and it should
   change the default rather than be quietly re-run.

## Known gaps in the harness

- **Cost is reported only when priced.** `cost_usd` is null unless
  `KORTEX_LLM_PRICES` is configured. The harness now says so in the caveats
  rather than leaving a blank column: null means unpriced, never free.
- **The judge is the model you configured.** Grading with the same family the
  system answers with is a known bias in this kind of benchmark. Point
  `KORTEX_LLM_PROVIDER` at a different vendor for the judge if the number will
  be published as a comparison.
- **Nothing has been run.** That is the only remaining gap, and it is not a
  code gap — see "Why this page is empty".

## Regression gate

Separately from publishing, `tests/integration/test_retrieval_quality.py`
scores a small synthetic corpus in ordinary CI and fails if recall or MRR drops
below a floor. That catches a broken ranker on the pull request that caused it.
Its floors are loose by design — it detects breakage, not drift, so retrieval
tweaks do not turn every build red. It deliberately does not gate `recall@1`:
under keyword-only search the gold document and a same-topic distractor score
close enough on cover density that their order is drift, not correctness.

**Synthetic numbers are never published as benchmark results.** They measure
the plumbing, not memory quality.
