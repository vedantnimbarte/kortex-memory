# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private vulnerability reporting: go to the
[Security tab](https://github.com/vedantnimbarte/kortex-memory/security) and
choose *Report a vulnerability*. That opens a private thread with the
maintainer.

Please include what you were able to do, the steps to reproduce it, and the
version or commit you tested. If you have a patch, attach it — it will be
credited.

Expect an acknowledgement within a few days. Kortex is pre-1.0 and maintained
by one person, so please be patient with fixes, and let us know if you plan to
disclose publicly so a fix can land first.

## What we consider a vulnerability

Kortex is a multi-tenant memory layer, so the sharpest risks are about data
crossing a boundary it should not:

- **Cross-tenant reads or writes.** Any path where one org can observe or
  modify another org's memories, sessions, attachments, or metadata. This is
  the highest-severity class; there is a dedicated CI lint
  (`tools/ruff_plugins/tenant_check.py`) and a regression test suite for it.
- **Sensitivity-tier bypass.** Reading `confidential`/`secret` memories above
  the caller's effective ceiling.
- **Authentication or authorization flaws.** API-key scope escalation, JWT
  forgery or replay, RBAC role bypass.
- **Memory poisoning that survives.** Content that gets stored and then
  re-injected into later sessions as if it were trusted context.
- **Secret disclosure.** API keys, database URLs, or embeddings leaking
  through logs, error responses, or telemetry.

## Scope notes

Kortex is self-hosted. Deployments are configured by their operators, so
misconfiguration of *your* instance (an unauthenticated `/metrics` exposed to
the internet, a default `KORTEX_JWT_SECRET` left in place) is not a
vulnerability in Kortex — but a default that makes that mistake easy to make
*is*, and we want to hear about it.

## Supported versions

Pre-1.0: only the latest tagged release and `main` receive fixes.
