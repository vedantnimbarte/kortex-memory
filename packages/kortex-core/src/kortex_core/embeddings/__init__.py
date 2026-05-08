"""Embeddings: pluggable embedders.

Default: ``BAAI/bge-large-en-v1.5`` via sentence-transformers (1024 dim).
Adapters: OpenAI, Voyage, Cohere (Anthropic uses Voyage as recommended).
"""

from kortex_core.embeddings.protocol import Embedder, EmbeddingError
from kortex_core.embeddings.registry import get_embedder, register_embedder

__all__ = [
    "Embedder",
    "EmbeddingError",
    "get_embedder",
    "register_embedder",
]
