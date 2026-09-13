"""Provider selection — builds the configured LLMProvider from settings.

Selection order (``LLM_PROVIDER=auto``):
1. FAIR, when ``FAIR_URL`` is set — governed free-tier routing with failover.
2. Gemini free tier, when ``GEMINI_API_KEY`` is set.
Otherwise raise ``ProviderConfigError``.
"""

import logging

from corp.config import Settings
from corp.config import settings as default_settings
from corp.workers.providers.fair import FairProvider
from corp.workers.providers.registry import GeminiProvider, LLMProvider

logger = logging.getLogger(__name__)

PROVIDER_CHOICES = ("auto", "fair", "gemini")


class ProviderConfigError(Exception):
    """No usable LLM provider is configured."""


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

    if choice == "gemini" or (choice == "auto" and cfg.gemini_api_key):
        if not cfg.gemini_api_key:
            raise ProviderConfigError("LLM_PROVIDER=gemini requires GEMINI_API_KEY")
        logger.info("LLM provider: Gemini (%s)", cfg.gemini_model)
        return GeminiProvider(api_key=cfg.gemini_api_key, model=cfg.gemini_model)

    raise ProviderConfigError(
        "No LLM provider configured: set FAIR_URL (preferred) or GEMINI_API_KEY"
    )
