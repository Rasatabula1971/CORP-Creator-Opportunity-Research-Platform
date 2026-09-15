"""FAIR Free AI Router — in-process, governed routing across every free provider.

FAIR is an embeddable library (its HTTP server was removed upstream in
FAIR ``ac61429``), so this adapter wraps ``fair.embedded.module.FAIR``
directly behind the :class:`LLMProvider` interface. FAIR does internally
what :class:`PooledProvider` does across two members — per-provider quota
governance, cooldowns, failover — for every free provider it holds a key
for, and it judges each answer before handing it back.

CORP passes the JSON schema of the expected output with every call. FAIR
accepts a schema-conformant answer at its ``STRUCTURE_VALIDATED`` tier
(FAIR PR #6, commodity/standard quality); without a schema an open-ended
answer is "unverified" and FAIR escalates instead of returning it.

FAIR's outcome maps onto the pool's error vocabulary so a FAIR provider can
sit inside a :class:`PooledProvider` like any other member:

* every attempt hit a quota → :class:`ProviderExhaustedError`
* providers unreachable / FAIR's validator failed → :class:`ProviderUnavailableError`
* answers came back but none passed quality → :class:`ProviderError`
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from corp.workers.providers.errors import (
    ProviderError,
    ProviderExhaustedError,
    ProviderUnavailableError,
)
from corp.workers.providers.registry import LLMProvider

if TYPE_CHECKING:
    from corp.config import Settings

logger = logging.getLogger(__name__)

PROVIDER_ID = "fair"
QUALITY_LEVELS = ("commodity", "standard", "advanced", "high_impact_support")

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_QUOTA_ERRORS = frozenset({"QUOTA_EXHAUSTED", "RATE_LIMITED"})
# A rate-limited member with no retry hint: sit out briefly, not for the daily cooldown.
_RATE_LIMIT_RETRY_SECONDS = 60.0


def _strip_code_fence(text: str) -> str:
    """Free models often wrap JSON in a markdown fence even when told not to."""
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text


# FAIR provider ids → the label CORP's own provider for that vendor records.
# Provenance names the *model*, not the route: an observation extracted by
# gpt-oss-20b is the same work whether Groq was called directly or via FAIR, and
# `_already_extracted` must see it that way (else switching to FAIR re-extracts
# everything the pool already did — seen live in run #7).
_VENDOR_PREFIX = {"google_gemini_api": "", "groq": "groq/"}


def _model_label(provider_id: str | None, model_id: str | None) -> str:
    provider = provider_id or "unknown"
    model = model_id or "unknown"
    prefix = _VENDOR_PREFIX.get(provider, f"{provider}/")
    return f"{prefix}{model}"


class FairUnavailableError(Exception):
    """FAIR cannot be used in this process (not installed, or no provider key)."""


def fair_available() -> bool:
    """True when the ``fair`` package is importable (installed from its repo)."""
    try:
        return importlib.util.find_spec("fair") is not None
    except (ImportError, ValueError):
        return False


def build_fair_provider(cfg: Settings) -> FairProvider:
    """Construct FAIR from CORP settings.

    Keys come from CORP's own Gemini/Groq settings plus, optionally, FAIR's
    own ``.env`` (``FAIR_ENV_FILE``) — that is where the keys for the other
    free providers (Mistral, Cloudflare, OpenRouter, NVIDIA, ...) live.
    """
    try:
        from fair.embedded.module import FAIR  # type: ignore[import-not-found]
    except ImportError as exc:
        raise FairUnavailableError(
            "the fair package is not installed; pip install -e <path to FAIR repo>"
        ) from exc

    if cfg.fair_quality_level not in QUALITY_LEVELS:
        raise FairUnavailableError(
            f"FAIR_QUALITY_LEVEL must be one of {QUALITY_LEVELS}, got {cfg.fair_quality_level!r}"
        )

    router = FAIR(
        gemini_api_key=cfg.gemini_api_key or None,
        groq_api_key=cfg.groq_api_key or None,
        env_file=cfg.fair_env_file or None,
        quality_level=cfg.fair_quality_level,
        timeout_seconds=cfg.fair_timeout_seconds,
        cache_enabled=cfg.fair_cache_enabled,
    )
    providers = router.providers()
    if not providers:
        raise FairUnavailableError(
            "FAIR found no provider keys (set GEMINI_API_KEY/GROQ_API_KEY or FAIR_ENV_FILE)"
        )
    logger.info(
        "LLM provider: FAIR with %d providers: %s",
        len(providers),
        ", ".join(p["provider_id"] for p in providers),
    )
    if router.skipped:
        logger.warning("FAIR skipped providers: %s", router.skipped)
    return FairProvider(
        router,
        client_id=cfg.fair_client_id,
        quality_level=cfg.fair_quality_level,
        priority=cfg.fair_priority,
        max_output_tokens=cfg.fair_max_output_tokens,
    )


class FairProvider(LLMProvider):
    """LLMProvider backed by an in-process FAIR router.

    ``router`` is a ``fair.embedded.module.FAIR`` instance (or anything with
    the same ``solve`` / ``providers`` / ``close`` surface, for tests).
    """

    def __init__(
        self,
        router: Any,
        *,
        client_id: str = "corp",
        quality_level: str = "standard",
        priority: str = "P2",
        max_output_tokens: int = 2048,
    ) -> None:
        self._fair = router
        self._client_id = client_id
        self._quality_level = quality_level
        self._priority = priority
        self._max_output_tokens = max_output_tokens
        self._last_model: str | None = None
        self._used: set[str] = set()

    # ── provenance (same surface as PooledProvider) ──────────────────

    @property
    def model_name(self) -> str:
        """The model that answered the last call (vendor-canonical label, e.g.
        ``gemini-3.6-flash`` or ``groq/openai/gpt-oss-20b``); ``fair-router`` before any."""
        return self._last_model or "fair-router"

    def member_names(self) -> list[str]:
        """Every model FAIR may route to, plus the pre-call label: one family
        for idempotency, exactly as a pool's members are."""
        names = ["fair-router"]
        for entry in self._fair.providers():
            names.extend(_model_label(entry["provider_id"], m) for m in entry.get("models", []))
        return names

    def models_used(self) -> set[str]:
        return set(self._used)

    async def close(self) -> None:
        await self._fair.close()

    # ── generation ───────────────────────────────────────────────────

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        task = f"{system}\n\n{prompt}" if system else prompt
        if schema is None:
            logger.warning(
                "FAIR call without an expected schema: an open-ended answer cannot pass "
                "FAIR's quality gate and will escalate"
            )
        try:
            result = await self._fair.solve(
                task,
                task_type="extraction",
                expected_schema=schema,
                quality_level=self._quality_level,
                client_id=self._client_id,
                priority=self._priority,
                max_output_tokens=self._max_output_tokens,
            )
        except Exception as exc:
            raise ProviderError(PROVIDER_ID, f"solve() raised {type(exc).__name__}: {exc}") from exc

        if result.status != "ACCEPTED" or result.output is None:
            raise self._classify(result)

        raw = result.output
        try:
            parsed = json.loads(_strip_code_fence(raw))
        except json.JSONDecodeError as exc:
            raise ProviderError(PROVIDER_ID, f"accepted output is not JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ProviderError(PROVIDER_ID, "accepted output is not a JSON object")

        label = _model_label(result.provider_id, result.model_id)
        self._last_model = label
        self._used.add(label)
        logger.info(
            "FAIR call: model=%s verification=%s cache_hit=%s hash=%s prompt_len=%d",
            label,
            getattr(result, "verification_state", "?"),
            getattr(result, "cache_hit", False),
            hashlib.sha256(raw.encode()).hexdigest()[:16],
            len(task),
        )
        return parsed

    @staticmethod
    def _classify(result: Any) -> ProviderError:
        """Map a non-accepted SolveResponse onto the pool's error vocabulary."""
        attempts = list(getattr(result, "attempts", []) or [])
        errors = [getattr(a, "error_type", None) for a in attempts]
        detail = ", ".join(
            f"{getattr(a, 'provider_id', '?')}/{getattr(a, 'model_id', '?')}:"
            f"{getattr(a, 'disposition', '?')}"
            + (f"({a.error_type})" if getattr(a, "error_type", None) else "")
            for a in attempts
        )
        reason = getattr(result, "reason_code", "UNKNOWN")
        message = f"{result.status} {reason}: {detail or 'no attempts'}"

        if result.status == "FAILED":
            return ProviderUnavailableError(PROVIDER_ID, message)
        if reason == "ALL_FREE_MODELS_UNAVAILABLE":
            if attempts and all(e in _QUOTA_ERRORS for e in errors):
                daily = all(e == "QUOTA_EXHAUSTED" for e in errors)
                return ProviderExhaustedError(
                    PROVIDER_ID,
                    message,
                    retry_after=None if daily else _RATE_LIMIT_RETRY_SECONDS,
                    daily=daily,
                )
            return ProviderUnavailableError(PROVIDER_ID, message)
        # ALL_FREE_MODELS_FAILED_QUALITY and anything else: answers came back
        # but none passed. That is about this prompt, not the provider's health.
        best = getattr(result, "best_quality_score", None)
        minimum = getattr(result, "minimum_required", None)
        return ProviderError(PROVIDER_ID, f"{message} (best={best}, required={minimum})")
