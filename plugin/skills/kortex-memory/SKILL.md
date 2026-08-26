---
name: kortex-memory
description: Decide what to write to long-term memory and when to read it back. Use whenever a decision is settled, a convention is agreed, a constraint is discovered, or a fix turns out to be non-obvious — and before starting work in an unfamiliar area, to check what was already decided. Also use when the user says "remember this", "what did we decide about", "why is this like this", or asks about a past decision.
---

# Writing and reading Kortex memory

The MCP tools give you a memory. This tells you when to use it, which is the
part that decides whether the memory is useful in six months or landfill.

## Read before you decide, not after

Before proposing an approach in an unfamiliar area, `recall` it. A memory layer
pays for itself the first time it stops you re-litigating a decision the team
already made — and costs the user nothing except when you skip it and rebuild
something that was deliberately removed.

Worth a `recall` first:

- a design or architecture choice in code you have not touched this session
- anything the user frames as "why is this like this"
- a convention question ("do we use X or Y here")
- before a large refactor, to find the constraint that explains the odd bit

Not worth it: reading a file, running a test, answering from what is already in
this conversation.

## Write the durable half, not the transcript

The failure mode is not writing too little. It is writing everything — a corpus
of "fixed a typo" that buries the three facts that mattered.

**Write when:**

| Signal | Example |
|---|---|
| A decision is settled, with a reason | "Postgres over DynamoDB for the ledger: we need joins" |
| A convention is agreed | "Migrations are named kkxNNNN, not by date" |
| A constraint is discovered the hard way | "plainto_tsquery ANDs its terms — a two-word query needs both" |
| A fix was non-obvious | "The MissingGreenlet came from onupdate=func.now() expiring the attribute" |
| The user says to | "remember that…" |

**Do not write:**

- anything already in the repository — code, README, CLAUDE.md, git history. A
  memory that restates a file is a second copy to keep in step, and it will
  drift.
- the fact that you ran a command, read a file, or fixed a lint error
- a summary of this conversation. Sessions are cheap. Conclusions are not.
- anything you are guessing about. Confidence you do not have is worse than
  silence, because it reads as settled later.

**One memory, one fact.** "We use Postgres and migrations are kkxNNNN and the
worker runs Celery" is three memories in a trench coat: it matches every query
weakly and answers none of them well.

**Write the why.** "Use Postgres" is worth little. "Postgres over DynamoDB
because the ledger needs joins" survives the next person who suggests
DynamoDB. The reason is the part that stops the decision being reopened.

## Scope it correctly

- **project** — the default. Decisions about this codebase.
- **workspace** — conventions that span several projects on one team.
- **org** — policy: security rules, compliance constraints, licensing.
- **session** — scratch that should not outlive the conversation. Rarely right.

Writing at too broad a scope is the more expensive mistake: an org-scoped note
about one repo's build quirk turns up in everyone's recalls forever.

## Sensitivity

Default `internal`. Raise it for anything a contractor or a wider team should
not read back — customer names, unannounced plans, security findings. Never
write a credential, a token, or a key, at any sensitivity: Kortex scans for
them and will redact or quarantine the write, but the right answer is not to
send them.

## What the responses are telling you

- **`deduped: true`** — an identical memory already existed and this folded
  into it. Nothing was lost. Do not "fix" it by rewording and writing again;
  that is how one fact becomes four near-duplicates that split every search.
- **`pending_review`** — the project gates writes, or the content read as an
  injection attempt. It is stored but invisible to recall until a human
  approves it. Tell the user rather than reporting a clean save.
- **`used_vector: false`** on a search — the embedder was unavailable and that
  was keyword-only. The results are real but ranked without semantics; a
  concept query may have missed something. Worth saying so.
- **`conflicts` on a hit** — something in the corpus contradicts it. Surface
  both to the user before acting; do not silently pick the newer one.

## Before the session ends

If the session settled something durable, write it before you finish. A
decision that lives only in a transcript is a decision the next session will
make again, differently.
