"""LLM registry. ``KORTEX_LLM_PROVIDER`` selects the active adapter."""

from __future__ import annotations

from collections.abc import Callable

from kortex_core.llm.protocol import LLM
from kortex_core.settings import get_settings

_factories: dict[str, Callable[[], LLM]] = {}
_singletons: dict[str, LLM] = {}


def register_llm(name: str, factory: Callable[[], LLM]) -> None:
    _factories[name] = factory


def get_llm(name: str | None = None) -> LLM:
    name = name or get_settings().llm_provider
    if name in _singletons:
        return _singletons[name]
    if name not in _factories:
        _bootstrap_default_factories()
    if name not in _factories:
        raise KeyError(f"unknown llm provider: {name}")
    instance = _factories[name]()
    _singletons[name] = instance
    return instance


def reset() -> None:
    """Drop singleton cache (tests only)."""
    _singletons.clear()


def _bootstrap_default_factories() -> None:
    if "anthropic" not in _factories:
        from kortex_core.llm.anthropic import AnthropicLLM

        _factories["anthropic"] = lambda: AnthropicLLM()
    if "openai" not in _factories:
        from kortex_core.llm.openai import OpenAILLM

        _factories["openai"] = lambda: OpenAILLM()
    if "openrouter" not in _factories:
        from kortex_core.llm.openrouter import OpenRouterLLM

        _factories["openrouter"] = lambda: OpenRouterLLM()
    if "ollama" not in _factories:
        from kortex_core.llm.ollama import OllamaLLM

        _factories["ollama"] = lambda: OllamaLLM()
