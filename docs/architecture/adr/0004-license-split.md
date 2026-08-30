# ADR 0004: License split — Apache-2.0 core, `ee/` for future enterprise features

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

Kortex is an open-source-core product with a managed cloud. That model only
works if the line between the two is written down *before* the first enterprise
feature is built, because the ambiguity — not the license — is what costs
adoption.

Two pieces of evidence, both from open-source memory vendors whose users
hit this line the hard way:

- Mem0 [#5863](https://github.com/mem0ai/mem0/issues/5863), "Difference in API
  surface between Platform mode and Standalone/OSS mode" — OSS users
  discovering they are second-class *after* they built on it.
- The question a Mem0 founder was asked on Hacker News: *"Will you support the
  open source version as a first class citizen for the long term?"* An
  unanswered version of that question poisons the acquisition channel, since
  the people who evaluate a memory layer are exactly the people who have been
  re-licensed before.

Today the whole repository is Apache-2.0: the `LICENSE` file and the
declaration in `pyproject.toml` agree. Nothing lives in `ee/`; the directory
does not exist. So this decision costs nothing to make now and gets more
expensive every week it is deferred.

## Decision

**1. Everything in the repository as of this ADR stays Apache-2.0, permanently.**
No shipped code is ever retro-licensed. If a feature is in `packages/` today, it
is Apache-2.0 for the life of the project, including in every future release.
This is the load-bearing half of the decision — the other half is only credible
because of it.

**2. Only *future* enterprise features land in `ee/`, under a source-available
license.** The list, and nothing beyond it:

- SSO/OIDC + SAML, and SCIM provisioning
- Audit-log **export**: retention policy, immutability guarantees, SIEM sinks
- BYOK for embeddings and blob storage
- Data-residency controls
- Whatever SOC 2 Type II evidence collection requires as code

**3. The audit *trail* is Apache-2.0; only the export machinery is enterprise.**
The recording side already shipped Apache-2.0 and stays that way: the
action vocabulary, the tamper-evident hash chain, the middleware that captures
caller IP and user agent, the query API. A self-hoster can read their own audit
log, and can write their own exporter against it. What `ee/` sells is the
supported path to a SIEM, not the existence of the record. A product that
records what happened to your data and then charges you to see it is the
behaviour this ADR exists to rule out.

**4. Nothing that already works keeps working only in `ee/`.** An enterprise
feature may not be implemented by removing or degrading an Apache-2.0 code
path. If SSO lands in `ee/`, password + API-key auth stays complete in core.

**5. The specific license for `ee/` is deferred** until the first `ee/` feature
is actually written — which is gated on a named enterprise prospect.
Choosing between BSL, Elastic License 2.0 and a commercial EULA in the abstract
is a decision without inputs. The constraint recorded now: it must permit
self-hosting for the licensee's own use, because "run it yourself" is the
product's whole wedge.

## Consequences

- The README can state the guarantee in one line, with no asterisk and no
  "contact sales" footnote. That is the point.
- Contributors know what they are contributing to. A CLA is *not* required for
  core, since core is not going to be re-licensed.
- The cloud's moat is operations, not withheld source: managed Postgres,
  backups, upgrades, uptime. If that is not enough of a moat, the answer is a
  better cloud, not a narrower core.
- We give up the option to move a shipped feature behind the paywall later.
  Deliberately. That option is worth less than the trust of the people who
  would notice it being exercised.
- `ee/` stays empty and unmentioned until the first enterprise feature has a
  named prospect. An `ee/` directory with a placeholder README is a promise to
  charge for something, made before there is anything to charge for.
