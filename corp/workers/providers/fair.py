"""FAIR Free AI Router provider — governed multi-provider LLM backend."""

import hashlib
import json
import logging

import httpx

from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)


class FairProviderError(Exception):
    """FAIR routing failed and no output was returned."""

    def __init__(self, status: str, reason_code: str):
        self.status = status
        self.reason_code = reason_code
        super().__init__(f"FAIR solve {status}: {reason_code}")


class FairProvider(LLMProvider):
    """LLM provider backed by a FAIR Free AI Router instance.

    Sends prompts to FAIR's ``/v1/solve`` endpoint, which routes across
    free-tier providers (Groq, Gemini, Cloudflare, Mistral, etc.) with
    automatic failover, quality verification, and quota governance.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        api_key: str,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._api_key = api_key
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"X-Api-Key": self._api_key},
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    @property
    def model_name(self) -> str:
        return "fair-router"

    async def generate_json(self, prompt: str, system: str | None = None) -> dict:
        task = f"{system}\n\n{prompt}" if system else prompt

        payload = {
            "client_id": self._client_id,
            "task": task,
            "quality_level": "standard",
            "priority": "P2",
        }

        client = await self._get_client()
        resp = await client.post("/v1/solve", json=payload)
        resp.raise_for_status()

        result = resp.json()
        status = result["status"]
        reason_code = result.get("reason_code", "UNKNOWN")

        if status != "ACCEPTED" or result.get("output") is None:
            logger.warning(
                "FAIR solve not accepted: status=%s reason=%s request_id=%s",
                status,
                reason_code,
                result.get("request_id"),
            )
            raise FairProviderError(status, reason_code)

        raw = result["output"]
        parsed = json.loads(raw)

        provider_id = result.get("provider_id", "unknown")
        model_id = result.get("model_id", "unknown")
        response_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        logger.info(
            "FAIR call: provider=%s model=%s hash=%s prompt_len=%d",
            provider_id,
            model_id,
            response_hash,
            len(task),
        )
        return parsed
