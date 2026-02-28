from __future__ import annotations

import json
import re

import httpx

from app.providers.base import LLMProvider, EmbeddingProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OllamaProvider(LLMProvider):
    """
    LLM provider backed by Ollama's OpenAI-compatible REST API.
    Works with:
      - Ollama running locally:  http://localhost:11434
      - LM Studio:               http://localhost:1234
      - Any OpenAI-compatible API with a custom base_url

    To use a different model, set OLLAMA_MODEL in .env.
    The model must already be pulled: `ollama pull llama3.2`
    """

    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 2500,
    ) -> dict:
        """Call Ollama /api/chat and return parsed JSON dict."""
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",  # Ollama native JSON mode
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            response = httpx.post(url, json=payload, timeout=180.0)
            response.raise_for_status()
            raw = response.json()["message"]["content"]
            return self._parse_json(raw)
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error: {e.response.status_code} — {e.response.text}")
            raise
        except httpx.ConnectError:
            raise ConnectionError(
                f"Could not connect to Ollama at {self._base_url}. "
                "Make sure Ollama is running: `ollama serve`"
            )
    def chat_json_with_history(
        self,
        system_prompt: str,
        history: list[dict],
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> dict:
        """
        Native Ollama multi-turn call using the /api/chat endpoint.
        Builds the messages array as: [system] + history + [current user message].
        """
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model":    self._model,        # use your existing model attribute
            "messages": messages,
            "stream":   False,
            "format":   "json",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        base_url = self._base_url.rstrip("/")  # use your existing base_url attribute
        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=120,
        )
        response.raise_for_status()

        raw = response.json().get("message", {}).get("content", "{}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                return json.loads(clean)
            except json.JSONDecodeError:
                return {"answer": raw}


    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        max_tokens: int = 2500,
    ) -> str:
        """Call Ollama /api/chat and return plain text."""
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            response = httpx.post(url, json=payload, timeout=180.0)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error: {e.response.status_code} — {e.response.text}")
            raise
        except httpx.ConnectError:
            raise ConnectionError(
                f"Could not connect to Ollama at {self._base_url}. "
                "Make sure Ollama is running: `ollama serve`"
            )

    @staticmethod
    def _parse_json(raw: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract from markdown blocks
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            
            # Fallback naive cleaning
            cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON from LLM: {raw[:200]}...")
                return {}


class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    Embedding provider backed by Ollama's /api/embeddings endpoint.
    Recommended model: nomic-embed-text (pull with `ollama pull nomic-embed-text`)
    """

    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            url = f"{self._base_url}/api/embeddings"
            try:
                response = httpx.post(
                    url,
                    json={"model": self._model, "prompt": text},
                    timeout=60.0,
                )
                response.raise_for_status()
                embeddings.append(response.json()["embedding"])
            except httpx.ConnectError:
                raise ConnectionError(
                    f"Could not connect to Ollama at {self._base_url}. "
                    "Make sure Ollama is running: `ollama serve`"
                )
        return embeddings
