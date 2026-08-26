# Dogfood log

One line per friction point, timestamped, written *while* it happens.

> This log outranks the market research. If it disagrees with a priority in the
> plan, the log wins. — WU-0.3

## What counts as an entry

**Write one when:**

- something took longer than you expected, and you can say why
- you had to read the source to understand what a command wanted
- an error message did not tell you what to do next
- you wanted to do something obvious and there was no way to
- you did the same manual step for the second time
- you were about to trust an output and could not tell whether to

**Do not write one for:**

- a bug you can fix in under a minute — fix it, then log the *fact that the
  path was broken*, not the fix
- something you already knew was missing. This log is for what you learn by
  using it, and confirmation of a known gap is not learning.
- a feature idea. Those belong in an issue. Friction is what happened, not what
  you wish existed.

Rough entry shape — the *cost* is the part that matters, because it is what
ranks the fix:

```
2026-08-27 09:14 — `kortex init cursor` wrote the config but Cursor showed no
tools until I restarted it. Nothing said to restart. ~6 min lost.
```

**Acceptance: 7 consecutive days, ≥15 entries.**

---

## Day 0 — static pre-flight, not use

**These entries did not come from using Kortex.** They came from an agent
reading the setup path against the code, because the machine it runs on has
neither Docker nor Postgres, so it could not run the stack at all.

They are recorded here because they are the same *kind* of finding a first day
of use produces, and because fixing them first means the seven real days are
spent on friction that only use can reveal. They do **not** count toward the
≥15, and none of them is a substitute for a single hour of actually using this.

| # | Finding | Cost avoided | Status |
|---|---|---|---|
| 0.1 | **The headline "Try it in one command" did not work for anyone.** `docker run … kortex/kortex:local` names an image published nowhere. It exists only after a local `make local-build`. | First command a visitor runs, fails. | fixed |
| 0.2 | Even corrected, `ghcr.io/vedantnimbarte/kortex-local:latest` does not exist — CI tags `:main` and `:<sha>`; `:latest` only appears on a release tag, and the one tag (`v0.1.0`) points at an old docs commit. | Second failure, after the first is fixed. | fixed (docs now say `:main`) |
| 0.3 | The GHCR package is **private**: an anonymous pull returns 401. So even the right name and tag fail for anyone but the owner. | Third failure. | **open — needs you**, see `docs/distribution.md` |
| 0.4 | **`make seed` was not re-runnable.** `projects` has a `UNIQUE (workspace_id, slug)` and the seed created unconditionally, while org and workspace both checked first. A second `make seed` died on an integrity error. | Anyone who tears down and re-seeds — i.e. everyone, on day 1. | fixed |
| 0.5 | The verify step hardcoded `--scope-id 1`. The seed prints the real id, and a copy-pasted `1` writes into whichever scope happens to be first. Silent: the write succeeds, the search finds nothing. | A confusing first "recall returns nothing". | fixed (seed prints the exports; README uses them) |
| 0.6 | **57 of 101 settings were absent from `.env.example`** — including every governance toggle shipped in the last month (`PII_DETECTION`, `INJECTION_QUARANTINE`, `TRUST_FILTERING`, `DEDUP_ON_WRITE`, `CONFLICT_DETECTION`, `AUDIT_RETENTION_DAYS`). You cannot configure what you cannot see the name of. | Every feature the docs advertise looks unconfigurable. | fixed for the 17 user-facing ones; the rest are tuning constants |

### One thing to decide before you start

WU-0.3 says to wire `.mcp.json` **by hand**, on the grounds that doing it
manually is how you learn what `kortex init` must automate. That instruction
predates `kortex init`, which shipped in WU-1.1 and now does all of it.

Suggestion: do it by hand **once**, on day 1, and log what was annoying — then
use `kortex init` for the rest of the week and log whether it actually removed
that annoyance. That answers the question the original instruction was asking,
and also tests the thing that was built to answer it.

---

## Day 1 — <!-- date -->

<!--
Start:
  make local-build && make local-run      # or: make dev && make migrate && make seed
  kortex doctor
  kortex init claude-code
Then use it. Log as you go, not at the end of the day — the friction is
invisible in hindsight, which is the whole reason this file exists.
-->

_(no entries yet)_

## Day 2 — <!-- date -->

_(no entries yet)_

## Day 3 — <!-- date -->

_(no entries yet)_

## Day 4 — <!-- date -->

_(no entries yet)_

## Day 5 — <!-- date -->

_(no entries yet)_

## Day 6 — <!-- date -->

_(no entries yet)_

## Day 7 — <!-- date -->

_(no entries yet)_

---

## After day 7

Re-read the whole log in one sitting, then:

1. **Count the entries.** Under 15 means the week was not representative, not
   that the product is smooth. Extend rather than declare victory.
2. **Group by cost, not by component.** Three six-minute annoyances on the same
   path outrank one twenty-minute one nobody hits twice.
3. **Compare against `docs/implementation-plan.md`.** Anything the log ranks
   above what the plan ranks — the log wins. Say so explicitly and re-order.
4. **Open issues for the top five**, quoting the log entry verbatim. The
   timestamp and the cost are the argument; a paraphrase loses both.
