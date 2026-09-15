"""Provider selection — builds the configured LLMProvider from settings.

Selection order (``LLM_PROVIDER=auto``):
1. FAIR, when ``FAIR_URL`` is set — governed free-tier routing with failover.
2. Otherwise every configured key in ``LLM_PROVIDER_ORDER`` (default
   ``gemini,groq``): two or more become a :class:`PooledProvider` that fails
   over on quota exhaustion; exactly one is returned bare.
Otherwise raise ``ProviderConfigError``.
"""

import logging

from corp.config import Settings
from corp.config import settings as default_settings
from corp.workers.providers.fair import FairProvider
from corp.workers.providers.groq import GroqProvider
from corp.workers.providers.pool import PooledProvider
from corp.workers.providers.registry import GeminiProvider, LLMProvider

logger = logging.getLogger(__name__)

PROVIDER_CHOICES = ("auto", "fair", "gemini", "groq", "pool")
POOL_MEMBERS = ("gemini", "groq")


class ProviderConfigError(Exception):
    """No usable LLM provider is configured."""


def _gemini(cfg: Settings) -> GeminiProvider:
    logger.info("LLM provider: Gemini (%s)", cfg.gemini_model)
    return GeminiProvider(api_key=cfg.gemini_api_key, model=cfg.gemini_model)


def _groq(cfg: Settings) -> GroqProvider:
    logger.info("LLM provider: Groq (%s)", cfg.groq_model)
    return GroqProvider(
        api_key=cfg.groq_api_key,
        model=cfg.groq_model,
        timeout=cfg.groq_timeout_seconds,
        max_output_tokens=cfg.groq_max_output_tokens,
        reasoning_effort=cfg.groq_reasoning_effort or None,
    )


def _configured_members(cfg: Settings) -> list[LLMProvider]:
    members: list[LLMProvider] = []
    for name in (s.strip().lower() for s in cfg.llm_provider_order.split(",")):
        if not name:
            continue
        if name not in POOL_MEMBERS:
            raise ProviderConfigError(
                f"LLM_PROVIDER_ORDER entries must be in {POOL_MEMBERS}, got {name!r}"
            )
        if name == "gemini" and cfg.gemini_api_key:
            members.append(_gemini(cfg))
        elif name == "groq" and cfg.groq_api_key:
            members.append(_groq(cfg))
    return members


def build_provider(cfg: Settings | None = None) -> LLMProvider:
    """Return the LLMProvider selected by configuration."""
    cfg = cfg or default_settings
    choice = cfg.llm_provider.lower()
    if choice not in PROVIDER_CHOICES:
        raise ProviderConfigError(
            f"LLM_PROVIDER must be one of {PROVIDER_CHOICES}, got {cfg.llm_provider!r}"
        )

    if choice == "fair" or (choice == "auto" and cfg.fair_url):
        if not cfg.fair_url:
            raise ProviderConfigError("LLM_PROVIDER=fair requires FAIR_URL")
        logger.info("LLM provider: FAIR at %s (client_id=%s)", cfg.fair_url, cfg.fair_client_id)
        return FairProvider(
            base_url=cfg.fair_url,
            client_id=cfg.fair_client_id,
            api_key=cfg.fair_api_key,
            timeout=cfg.fair_timeout_seconds,
            quality_level=cfg.fair_quality_level,
            priority=cfg.fair_priority,
        )

    if choice == "gemini":
        if not cfg.gemini_api_key:
            raise ProviderConfigError("LLM_PROVIDER=gemini requires GEMINI_API_KEY")
        return _gemini(cfg)

    if choice == "groq":
        if not cfg.groq_api_key:
            raise ProviderConfigError("LLM_PROVIDER=groq requires GROQ_API_KEY")
        return _groq(cfg)

    members = _configured_members(cfg)
    if choice == "pool":
        if not members:
            raise ProviderConfigError(
                "LLM_PROVIDER=pool requires GEMINI_API_KEY and/or GROQ_API_KEY"
            )
        return PooledProvider(
            members,
            cooldown_seconds=cfg.llm_cooldown_seconds,
            max_wait_seconds=cfg.llm_max_wait_seconds,
        )

    # auto
    if len(members) >= 2:
        logger.info("LLM provider: pool of %s", [m.model_name for m in members])
        return PooledProvider(
            members,
            cooldown_seconds=cfg.llm_cooldown_seconds,
            max_wait_seconds=cfg.llm_max_wait_seconds,
        )
    if members:
        return members[0]
    raise ProviderConfigError(
        "No LLM provider configured: set FAIR_URL (preferred), GEMINI_API_KEY and/or GROQ_API_KEY"
    )
