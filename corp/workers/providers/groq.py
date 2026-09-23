"""Groq free tier via its OpenAI-compatible chat completions endpoint.

JSON mode (``response_format: json_object``) matches the "just return JSON"
contract the pipelines already use with Gemini — no schema needed. Groq
requires the word "JSON" somewhere in the conversation for that mode; every
CORP prompt already says "Return JSON", and the default system message
guarantees it regardless.

Free tier observed on 2026-09-14 for openai/gpt-oss-20b: 1000 requests per
rolling day and 8,000 tokens per minute. The per-minute bucket is what bites:
Groq reserves ``max_completion_tokens`` against it, so a large budget means
few calls per minute. gpt-oss is a reasoning model: at the default effort it
spent ~500 reasoning tokens per extraction call and, on some inputs, hit the
completion budget before producing valid JSON ("max completion tokens reached
before generating a valid document"). ``reasoning_effort="low"`` cut that to
~16–100 tokens and fixed every such failure in live tests; measured
completions stayed under 500 tokens, so the default budget is 2048.
"""

import json
import logging
from typing import Any, cast

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from corp.workers.providers.errors import (
    ProviderError,
    ProviderExhaustedError,
    ProviderUnavailableError,
)
from corp.workers.providers.fair import _strip_code_fence
from corp.workers.providers.registry import LLMProvider, _warn_schema_violations

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_SYSTEM = "You are a precise research assistant. Respond with valid JSON only."


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class GroqProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-20b",
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_output_tokens: int = 2048,
        reasoning_effort: str | None = "low",
        base_url: str = GROQ_BASE_URL,
        client: httpx.AsyncClient | None = None,
        retry_attempts: int = 3,
        retry_wait_min: float = 1.0,
        retry_wait_max: float = 8.0,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._reasoning_effort = reasoning_effort or None
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )
        self._retry_attempts = retry_attempts
        self._retry_wait_min = retry_wait_min
        self._retry_wait_max = retry_wait_max

    @property
    def model_name(self) -> str:
        return f"groq/{self._model}"

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        system_text = system or DEFAULT_SYSTEM
        if "json" not in system_text.lower() and "json" not in prompt.lower():
            system_text += "\nRespond with valid JSON only."
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": prompt},
            ],
            "temperature": self._temperature,
            "max_completion_tokens": self._max_output_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        data = await self._post(payload)
        try:
            raw = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.model_name, f"unexpected response shape: {exc}") from exc
        if not isinstance(raw, str) or not raw.strip():
            raise ProviderError(self.model_name, "empty completion")
        result = json.loads(_strip_code_fence(raw))
        if not isinstance(result, dict):
            raise ProviderError(
                self.model_name, f"completion is not a JSON object ({type(result).__name__})"
            )
        _warn_schema_violations(self.model_name, result, schema)
        usage = data.get("usage") or {}
        logger.info(
            "LLM call completed: model=%s prompt_len=%d completion_tokens=%s",
            self.model_name,
            len(prompt),
            usage.get("completion_tokens"),
        )
        return result

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(_is_transient),
                wait=wait_exponential(
                    multiplier=1, min=self._retry_wait_min, max=self._retry_wait_max
                ),
                stop=stop_after_attempt(self._retry_attempts),
                reraise=True,
            ):
                with attempt:
                    resp = await self._client.post(url, json=payload)
                    if resp.status_code == 429:
                        raise self._exhausted(resp)
                    resp.raise_for_status()
                    return cast(dict[str, Any], resp.json())
        except ProviderExhaustedError:
            raise
        except httpx.HTTPStatusError as exc:
            if _is_transient(exc):
                raise ProviderUnavailableError(
                    self.model_name, f"HTTP {exc.response.status_code} after retries"
                ) from exc
            raise ProviderError(
                self.model_name, f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailableError(self.model_name, f"transport: {exc}") from exc
        raise ProviderUnavailableError(self.model_name, "retry loop exited without a response")

    def _exhausted(self, resp: httpx.Response) -> ProviderExhaustedError:
        """Classify a 429. ``daily`` only when the request budget is actually
        spent; otherwise pass Groq's own ``retry-after`` through untouched and
        let the pool decide whether to wait. Inferring "daily" from a long wait
        misfired live (a token-bucket stall was cooled for an hour)."""
        headers = resp.headers
        retry_after = _float_header(headers.get("retry-after"))
        remaining_requests = _float_header(headers.get("x-ratelimit-remaining-requests"))
        remaining_tokens = _float_header(headers.get("x-ratelimit-remaining-tokens"))
        daily = remaining_requests == 0.0
        try:
            message = resp.json().get("error", {}).get("message", resp.text[:300])
        except ValueError:
            message = resp.text[:300]
        detail = (
            f"429: {message} (remaining requests={remaining_requests}, "
            f"tokens={remaining_tokens}, retry-after={retry_after})"
        )
        return ProviderExhaustedError(
            self.model_name, detail, retry_after=retry_after, daily=daily
        )

    async def close(self) -> None:
        await self._client.aclose()


def _float_header(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
