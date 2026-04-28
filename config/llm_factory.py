"""
LLM Factory — centralized model creation with automatic provider fallback.

Provider chain: primary → secondary → tertiary (configurable via settings).
Each tier maps to a different model complexity: router < chat < analysis.
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel

from config.settings import settings

logger = logging.getLogger(__name__)

ProviderType = Literal["anthropic", "openai", "qwen"]
ModelTier = Literal["router", "analysis", "chat"]


def create_llm(
    tier: ModelTier = "analysis",
    provider: ProviderType | None = None,
    temperature: float | None = None,
    bind_tools: list | None = None,
) -> BaseChatModel:
    """
    Create a LangChain chat model with automatic provider fallback.

    Args:
        tier: Complexity tier — router (fast/cheap), analysis (powerful), chat (balanced)
        provider: Force a specific provider; None uses the configured primary chain
        temperature: Override default temperature for the tier
        bind_tools: Optional list of LangChain tools to bind to the model

    Returns:
        Configured BaseChatModel instance (optionally with tools bound)

    Raises:
        RuntimeError: All providers in the fallback chain failed
    """
    providers_to_try: list[ProviderType] = [provider] if provider else _get_provider_chain()

    last_exc: Exception | None = None
    for prov in providers_to_try:
        try:
            llm = _create_for_provider(prov, tier, temperature)
            if bind_tools:
                llm = llm.bind_tools(bind_tools)
            if prov != providers_to_try[0]:
                logger.warning("LLM fallback: using %s (primary failed)", prov)
            return llm
        except Exception as exc:
            logger.warning("Failed to create LLM with provider=%s: %s", prov, exc)
            last_exc = exc
            continue

    raise RuntimeError(f"All LLM providers failed. Last error: {last_exc}")


def _get_provider_chain() -> list[ProviderType]:
    """Return ordered list of providers to attempt, starting with primary."""
    primary = settings.llm_provider_primary
    if not settings.llm_fallback_enabled:
        return [primary]  # type: ignore[list-item]
    all_providers: list[ProviderType] = ["anthropic", "openai", "qwen"]
    chain: list[ProviderType] = [primary]  # type: ignore[list-item]
    chain.extend(p for p in all_providers if p != primary)
    return chain


def _get_model_name(provider: ProviderType, tier: ModelTier) -> str:
    mapping = {
        "anthropic": {
            "router": settings.router_model_anthropic,
            "analysis": settings.analysis_model_anthropic,
            "chat": settings.chat_model_anthropic,
        },
        "openai": {
            "router": settings.router_model_openai,
            "analysis": settings.analysis_model_openai,
            "chat": settings.chat_model_openai,
        },
        "qwen": {
            "router": settings.router_model_qwen,
            "analysis": settings.analysis_model_qwen,
            "chat": settings.chat_model_qwen,
        },
    }
    return mapping[provider][tier]


def _get_default_temperature(tier: ModelTier) -> float:
    return {
        "router": settings.router_temperature,
        "analysis": settings.analysis_temperature,
        "chat": settings.chat_temperature,
    }[tier]


def _create_for_provider(
    provider: ProviderType,
    tier: ModelTier,
    temperature: float | None,
) -> BaseChatModel:
    model_name = _get_model_name(provider, tier)
    temp = temperature if temperature is not None else _get_default_temperature(tier)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_name,
            temperature=temp,
            api_key=settings.anthropic_api_key,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI  # type: ignore[import]
        return ChatOpenAI(
            model=model_name,
            temperature=temp,
            api_key=settings.openai_api_key,
        )

    if provider == "qwen":
        from langchain_community.chat_models import ChatTongyi  # type: ignore[import]
        return ChatTongyi(
            model=model_name,
            temperature=temp,
            dashscope_api_key=settings.qwen_api_key,
            streaming=True,
        )

    raise ValueError(f"Unsupported provider: {provider}")
