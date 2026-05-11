"""LLM protocol + adapters.

The planner LLM (``llm_model_planner``) emits a structured ``QueryPlan`` via
tool calling; the summarizer LLM (``llm_model_summarizer``) writes the
``ContextBundle``. Both go through :class:`LLM` so providers are swappable.
"""

from kortex_core.llm.protocol import LLM, LlmError, LlmMessage, LlmResponse
from kortex_core.llm.registry import get_llm, register_llm

__all__ = [
    "LLM",
    "LlmError",
    "LlmMessage",
    "LlmResponse",
    "get_llm",
    "register_llm",
]
