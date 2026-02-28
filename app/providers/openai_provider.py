from __future__ import annotations

import json
import time

from openai import OpenAI, RateLimitError, APIError

from app.providers.base import LLMProvider, EmbeddingProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_BATCH_SIZE = 100  # OpenAI hard limit per request


class OpenAIProvider(LLMProvider):
    """
    LLM provider backed by the OpenAI Chat Completions API.
    Also works with any OpenAI-compatible endpoint via base_url override.
    """

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 2500,
    ) -> dict:
        """Call OpenAI and return parsed JSON dict. Robust against markdown fences."""
        response = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw = response.choices[0].message.content or "{}"
        return self._parse_json(raw)

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 2500,
    ) -> str:
        """Call OpenAI and return raw text."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def chat_json_with_history(
        self,
        system_prompt: str,
        history: list[dict],
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> dict:
        """
        Native OpenAI multi-turn call.
        Builds: [system] + history + [current user message with RAG context].
        """
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            cleaned = (
                raw.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
            )
            return json.loads(cleaned)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Embedding provider backed by the OpenAI Embeddings API.
    Includes automatic batching and exponential backoff on rate limits.
    """

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), _MAX_BATCH_SIZE):
            batch = texts[i : i + _MAX_BATCH_SIZE]
            all_embeddings.extend(self._call_with_retry(batch))
        return all_embeddings

    def _call_with_retry(self, texts: list[str], max_retries: int = 4) -> list[list[float]]:
        for attempt in range(max_retries):
            try:
                response = self._client.embeddings.create(model=self._model, input=texts)
                return [
                    item.embedding
                    for item in sorted(response.data, key=lambda x: x.index)
                ]
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(f"Rate limited. Waiting {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
            except APIError as e:
                if attempt == max_retries - 1:
                    raise
                logger.error(f"OpenAI API error: {e}. Retrying...")
                time.sleep(2 ** attempt)
        raise RuntimeError("Max retries exceeded for OpenAI embedding API")