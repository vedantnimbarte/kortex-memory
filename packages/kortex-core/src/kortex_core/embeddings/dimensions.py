"""The one dimension every stored vector must have, and the check that enforces it.

``memories.embedding``, ``attachment_chunks.embedding`` and
``conversations.summary_embedding`` are all ``VECTOR(1024)``. Postgres will
reject a vector of any other length, so switching to an embedder that produces
a different width does not degrade quality — it stops writes entirely.

Before write-path integrity landed that failure was close to silent: the insert
raised, the worker logged, and the memory sat unembedded forever. It is visible
now, but the far better time to catch it is at boot, before a single write has
been accepted and lost.

This is why the constant lives here rather than as a literal in three model
files: the schema and the guard have to agree by construction.
"""

from __future__ import annotations

from typing import Final

EMBEDDING_DIM: Final[int] = 1024
"""Width of every vector column in the schema.

Changing it means a migration that rewrites all three columns and re-embeds the
entire corpus (``kortex admin reindex-embeddings``). It is not a config knob.
"""


class EmbeddingDimensionError(Exception):
    """Raised when a configured embedder cannot produce storable vectors."""


def check_dimension(*, name: str, model_id: str, dim: int) -> None:
    """Reject an embedder whose output will not fit the schema.

    Called when an embedder is constructed, so the failure surfaces on the
    first attempt to use it rather than as a stream of rejected inserts.
    """
    if dim == EMBEDDING_DIM:
        return
    raise EmbeddingDimensionError(
        f"embedder {name!r} (model {model_id!r}) produces {dim}-dimensional vectors, "
        f"but every vector column in this database is VECTOR({EMBEDDING_DIM}). "
        f"Postgres will reject every write.\n"
        f"  • If the model supports it, set KORTEX_EMBEDDER_DIM={EMBEDDING_DIM} "
        f"(OpenAI and Voyage can truncate).\n"
        f"  • Otherwise pick a {EMBEDDING_DIM}-dimensional model.\n"
        f"  • Changing the schema width means migrating all three vector columns "
        f"and re-embedding everything with `kortex admin reindex-embeddings`."
    )
