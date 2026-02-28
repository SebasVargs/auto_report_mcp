"""
Provider factory — resolves LLM and Embedding providers from config.

Usage:
    from app.providers import get_llm_provider, get_embedding_provider

Set LLM_PROVIDER=openai|ollama in .env to switch providers.
"""
from __future__ import annotations

from app.providers.base import LLMProvider, EmbeddingProvider


def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider (singleton-friendly, stateless)."""
    from app.config import get_settings
    settings = get_settings()

    match settings.llm_provider.lower():
        case "openai":
            from app.providers.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
                base_url=settings.llm_base_url,
            )
        case "ollama":
            from app.providers.ollama_provider import OllamaProvider
            return OllamaProvider(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
            )
        case _:
            raise ValueError(
                f"Unknown LLM_PROVIDER: '{settings.llm_provider}'. "
                "Supported values: openai, ollama"
            )


def get_openai_provider() -> LLMProvider:
    """
    Always returns an OpenAI provider.
    Used for tasks that require a capable model (e.g. knowledge Q&A with large context),
    regardless of the global LLM_PROVIDER setting.
    Falls back to get_llm_provider() if OpenAI key is not configured.
    """
    from app.config import get_settings
    settings = get_settings()

    api_key = settings.openai_api_key
    if not api_key or api_key == "sk-placeholder":
        # No OpenAI key available — fall back to configured provider
        return get_llm_provider()

    from app.providers.openai_provider import OpenAIProvider
    return OpenAIProvider(
        api_key=api_key,
        model=settings.openai_model,
        base_url=settings.llm_base_url,
    )



def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured Embedding provider (singleton-friendly, stateless)."""
    from app.config import get_settings
    settings = get_settings()

    match settings.embedding_provider.lower():
        case "openai":
            from app.providers.openai_provider import OpenAIEmbeddingProvider
            return OpenAIEmbeddingProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_embedding_model,
                base_url=settings.embedding_base_url,
            )
        case "ollama":
            from app.providers.ollama_provider import OllamaEmbeddingProvider
            return OllamaEmbeddingProvider(
                base_url=settings.ollama_base_url,
                model=settings.ollama_embedding_model,
            )
        case _:
            raise ValueError(
                f"Unknown EMBEDDING_PROVIDER: '{settings.embedding_provider}'. "
                "Supported values: openai, ollama"
            )
