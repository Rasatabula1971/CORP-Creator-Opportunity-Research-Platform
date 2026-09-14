"""LLM provider abstraction with deterministic call logging."""

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import google.generativeai as genai
from google.api_core.exceptions import (
    DeadlineExceeded,
    ResourceExhausted,
    ServiceUnavailable,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_RETRYABLE = (ResourceExhausted, ServiceUnavailable, DeadlineExceeded)


class LLMProvider(ABC):
    """Abstract LLM provider with JSON-mode generation."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    async def generate_json(self, prompt: str, system: str | None = None) -> dict: ...


class GeminiProvider(LLMProvider):
    """Google Gemini provider using the free tier."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        temperature: float = 0.0,
    ) -> None:
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model,
            system_instruction=None,
        )
        self._model_id = model
        self._temperature = temperature

    @property
    def model_name(self) -> str:
        return self._model_id

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    async def _generate_with_retry(self, model: Any, prompt: str, config: Any) -> Any:
        try:
            return await model.generate_content_async(prompt, generation_config=config)
        except _RETRYABLE as exc:
            logger.warning("Gemini call rate-limited/unavailable, retrying: %s", exc)
            raise

    async def generate_json(self, prompt: str, system: str | None = None) -> dict:
        model = self._model
        if system:
            model = genai.GenerativeModel(
                self._model_id, system_instruction=system
            )

        config = genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=self._temperature,
        )
        response = await self._generate_with_retry(model, prompt, config)
        raw = response.text
        result = json.loads(raw)

        response_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        logger.info(
            "LLM call: model=%s hash=%s prompt_len=%d",
            self._model_id,
            response_hash,
            len(prompt),
        )
        return result


def _response_hash(data: dict) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()[:16]
