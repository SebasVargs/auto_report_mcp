from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class — existing methods omitted for brevity."""

    @abstractmethod
    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 2048,
    ) -> dict:
        """Send a single-turn prompt and return a parsed JSON dict."""
        ...

    # ── NEW METHOD ────────────────────────────────────────────────
    def chat_json_with_history(
        self,
        system_prompt: str,
        history: list[dict],
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> dict:
        """
        Send a multi-turn conversation to the LLM and return a parsed JSON dict.

        Args:
            system_prompt: The system instruction (same as chat_json).
            history:       Previous turns as [{"role": "user"|"assistant", "content": "..."}].
                           Pass [] for a single-turn call.
            user_prompt:   The current user message (last turn).
            temperature:   Sampling temperature.
            max_tokens:    Max tokens for the response.

        Default implementation: concatenates history into user_prompt as plain text
        and calls chat_json(). Override in subclasses for native multi-turn support.
        """
        if not history:
            return self.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        history_lines = []
        for msg in history:
            role    = "Usuario" if msg.get("role") == "user" else "Asistente"
            content = msg.get("content", "")
            history_lines.append(f"{role}: {content}")

        history_block = "\n".join(history_lines)
        combined_prompt = (
            f"HISTORIAL DE CONVERSACIÓN PREVIA:\n{history_block}\n\n"
            f"{user_prompt}"
        )
        return self.chat_json(
            system_prompt=system_prompt,
            user_prompt=combined_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

class EmbeddingProvider(ABC):
    """
    Abstract interface for any text embedding provider.
    Concrete implementations: OpenAIEmbeddingProvider, OllamaEmbeddingProvider.
    """

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return a list of embedding vectors, one per input text."""
        ...

    def embed(self, text: str) -> list[float]:
        """Convenience method to embed a single text."""
        return self.embed_batch([text])[0]
