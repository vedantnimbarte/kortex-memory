"""End-to-end tests: the full stack over HTTP, no internal imports.

Marked ``e2e`` by ``tests/conftest.py`` and excluded from ``-m unit`` and
``-m integration``. These need a running API, worker, and database — see
RUNNING_LOCALLY.md — so they are not part of the default CI gate.
"""
