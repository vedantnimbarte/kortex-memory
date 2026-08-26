# Portability

Memory is the worst thing to be locked into. It is the accumulated record of
what your team decided and why, it gets more valuable the longer you keep it,
and by the time you want to move it you have the most to lose. A memory layer
that is hard to leave is not sticky — it is a hostage situation with a nicer
landing page.

So the commitments below are deliberately specific. A promise you cannot check
is marketing.

## What we commit to

**1. Everything you put in comes back out.** `kortex export` writes a plain
`tar` of JSONL plus the original attachment blobs. Not a database dump, not a
proprietary container — files you can read with `tar -xf` and `cat`. Memories,
their links, their metadata, their attachments, the lot.

**2. No proprietary format, ever.** The export is JSONL and the schema is in
this repository. If Kortex disappeared tomorrow, a competent engineer could
load your corpus into Postgres in an afternoon with no cooperation from us.

**3. The open-source build is the product.** Not a demo, not a crippled tier
that exists to funnel you to a paid one. Managed Kortex runs the same code:
same retrieval, same governance, same MCP tools. What you pay for is not having
to run Postgres, not a feature flag.

**4. Import is as good as export.** Leaving is easy in both directions —
including the direction that brings a competitor's corpus here. That is the
next section.

**5. No export tax.** Export is not gated behind a plan, a support ticket, a
notice period, or a "contact sales". It is a CLI command and an API endpoint,
available on the free tier.

## Coming from somewhere else

```bash
kortex import ./mem0-export.json --from mem0 --scope-type project --scope-id 7 --dry-run
```

`--dry-run` parses the file, shows what it made of it, and writes nothing.
**Run it first.** None of these vendors publishes a versioned export contract —
the shapes are whatever a given SDK version emits, and they move.

| `--from` | Reads | Notes |
|---|---|---|
| `mem0` | `get_all()` output, bare list or `{"results": […]}` | Categories are kept as metadata, not mapped onto Kortex kinds |
| `zep` | Facts / graph edges | Invalidated facts are skipped; transcripts are not imported |
| `letta` | Agent file — core blocks and archival passages | Core blocks arrive flagged for pinning |
| `json` | Any array of objects with a text field | The escape hatch for everything else |

Three things about how import works that are worth knowing before you run it on
a large corpus:

**Imports are governed like any other write.** Records go through the ordinary
create path, so dedup, PII scanning, the trust policy and review gating all
apply. An import that bypassed governance would be a hole straight through it,
and "it came from an import" is not an argument a compliance reviewer accepts.

**Imports are idempotent.** Content-hash dedup is on by default, so a run that
dies halfway can simply be re-run — the repeats fold into what is already
stored instead of doubling it.

**Imports are lossless even where they are imperfect.** Any field the parser
has no place for is kept in the memory's `metadata` under the source's name. A
field you had a reason to store is not dropped because our schema had no column
for it.

If a parser misreads your file, it is about thirty lines in
[`packages/kortex-cli/src/kortex_cli/importers.py`](https://github.com/vedantnimbarte/kortex-memory/blob/main/packages/kortex-cli/src/kortex_cli/importers.py)
and a pull request is very welcome.

## Leaving

```bash
kortex export scope --scope-type project --scope-id 7 -o kortex-export.tar
tar -tf kortex-export.tar
```

```text
manifest.json
memories.jsonl
memory_links.jsonl
attachments.jsonl
attachment_chunks.jsonl
blobs/<public_id>/<filename>
```

One JSON object per line. `manifest.json` records the source scope and the
counts, so you can verify nothing was silently dropped.

Two honest caveats:

**Embeddings are not in the export.** Vectors are specific to the model that
produced them and are worthless to anything using a different one, so they are
regenerated on import rather than carried across. That is not a lock-in
mechanism — it is that a `bge-large-en-v1.5` vector means nothing to
`text-embedding-3-large`. The text they were computed from is all there.

**Decay and access statistics reset.** Import creates new memories, so
`access_count` and `decay_score` start fresh. Importance, pinning and tier
survive; the usage history does not.

## What we are not promising

We are not promising the API will never change — it is 0.x and it will. We are
promising that when it does, the export format stays readable and a migration
path exists.

We are not promising every managed feature will be free. Hosting costs money.
We are promising that the difference is operational, not a feature the
open-source build has been deliberately denied.
