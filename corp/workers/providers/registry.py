"""LLM provider abstraction with deterministic call logging."""

import hashlib
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from corp.workers.providers.errors import (
    ProviderError,
    ProviderExhaustedError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)

# Any 5xx (503 unavailable, 504 deadline, ...) is worth a retry; 4xx is not.
_TRANSIENT = (genai_errors.ServerError,)
_RETRY_IN_RE = re.compile(r"retry in (\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


class LLMProvider(ABC):
    """Abstract LLM provider with JSON-mode generation."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Return the model's JSON-object answer.

        ``schema`` is the JSON Schema of the answer the caller expects. Providers
        that can enforce or verify it do (FAIR); the others accept it and
        rely on the prompt.
        """


def classify_quota_error(model: str, exc: BaseException) -> ProviderExhaustedError:
    """Turn a Gemini 429 into a pool signal.

    Gemini reports a per-day cap and a per-minute limit with the same
    exception type. The message tells them apart via the quota id
    (``GenerateRequestsPerDayPerProjectPerModel-FreeTier`` vs ``...PerMinute...``).
    The "Please retry in Ns" hint is only honoured for the per-minute case;
    on a daily cap it is misleading (observed: "retry in 40s" on a cap that
    resets at midnight).
    """
    text = str(exc)
    daily = "PerDay" in text or "per day" in text.lower()
    match = _RETRY_IN_RE.search(text)
    retry_after = float(match.group(1)) if (match and not daily) else None
    return ProviderExhaustedError(model, text[:300], retry_after=retry_after, daily=daily)


class GeminiProvider(LLMProvider):
    """Google Gemini provider using the free tier."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        temperature: float = 0.0,
        retry_attempts: int = 4,
        retry_wait_min: float = 2.0,
        retry_wait_max: float = 30.0,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model_id = model
        self._temperature = temperature
        self._retry_attempts = retry_attempts
        self._retry_wait_min = retry_wait_min
        self._retry_wait_max = retry_wait_max

    @property
    def model_name(self) -> str:
        return self._model_id

    async def _generate_with_retry(self, prompt: str, config: Any) -> Any:
        """Retry only transient errors (5xx). A 429 is never retried here:
        it becomes ProviderExhaustedError immediately so a pool can fail over
        instead of this call sleeping through a cap that will not clear."""
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(_TRANSIENT),
                wait=wait_exponential(
                    multiplier=1, min=self._retry_wait_min, max=self._retry_wait_max
                ),
                stop=stop_after_attempt(self._retry_attempts),
                reraise=True,
            ):
                with attempt:
                    return await self._client.aio.models.generate_content(
                        model=self._model_id, contents=prompt, config=config
                    )
        except genai_errors.ClientError as exc:
            if exc.code == 429:
                raise classify_quota_error(self._model_id, exc) from exc
            raise
        except _TRANSIENT as exc:
            raise ProviderUnavailableError(
                self._model_id, f"{type(exc).__name__} after {self._retry_attempts} attempts"
            ) from exc
        raise ProviderUnavailableError(self._model_id, "retry loop exited without a response")

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        del schema  # JSON mode only; the prompt describes the shape
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=self._temperature,
        )
        response = await self._generate_with_retry(prompt, config)
        raw = response.text
        # ``text`` is None when no part carried text: safety block, MAX_TOKENS
        # on a thought-only part, no candidates. json.loads(None) would be an
        # opaque TypeError against the item; name it as a provider error.
        if not isinstance(raw, str) or not raw.strip():
            raise ProviderError(
                self._model_id, f"empty completion (finish_reason={_finish_reason(response)})"
            )
        result = json.loads(raw)

        response_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        logger.info(
            "LLM call: model=%s hash=%s prompt_len=%d",
            self._model_id,
            response_hash,
            len(prompt),
        )
        return result  # type: ignore[no-any-return]


def _finish_reason(response: Any) -> str | None:
    """Why the first candidate stopped, for error messages; None when unknown."""
    candidates = getattr(response, "candidates", None) or []
    reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    return getattr(reason, "name", reason)  # enum -> its name; str/None as-is


def _response_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()[:16]
