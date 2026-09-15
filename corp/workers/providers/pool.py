"""Failover across free-tier providers.

Same ``LLMProvider`` interface, so pipelines are unchanged. Providers are
tried in order; one that reports quota exhaustion or a transient outage is
put in cooldown and skipped until it expires. Call-specific errors (bad
prompt, unparseable answer) propagate at once without failover, so the
pipeline counts them against that one item rather than switching models
mid-run for no reason.

When *no* provider is available, the pool waits for the soonest cooldown to
expire if that is near (a per-minute limit), bounded by ``max_wait_seconds``
so a daily cap still fails fast. Found live: without this, one Groq
per-minute 429 turned the next fifty calls into instant failures.

Provenance: ``model_name`` reports the provider that answered the most
recent call, so each observation records the model that actually produced
it; ``models_used()`` is the set that answered during this pool's life, for
run-level records; ``member_names()`` lets idempotency checks treat the
pool's members as one family.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from corp.workers.providers.errors import (
    ProviderExhaustedError,
    ProviderUnavailableError,
)
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)


class PooledProvider(LLMProvider):
    def __init__(
        self,
        providers: Sequence[LLMProvider],
        *,
        cooldown_seconds: float = 3600.0,
        transient_cooldown_seconds: float = 60.0,
        # Found live: Groq's token bucket can ask for a 159s refill. For a
        # batch pipeline, waiting beats failing every remaining item, so the
        # bound matches the point past which the Groq provider itself reports
        # a long exhaustion (> 300s).
        max_wait_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not providers:
            raise ValueError("PooledProvider needs at least one provider")
        self._providers = list(providers)
        self._cooldown = cooldown_seconds
        self._transient_cooldown = transient_cooldown_seconds
        self._max_wait = max_wait_seconds
        self._clock = clock
        self._sleep = sleep
        self._cooling_until: dict[int, float] = {}
        self._last: LLMProvider | None = None
        self._used: set[str] = set()

    @property
    def model_name(self) -> str:
        if self._last is not None:
            return self._last.model_name
        available = self.available()
        return (available[0] if available else self._providers[0]).model_name

    def member_names(self) -> list[str]:
        return [p.model_name for p in self._providers]

    def models_used(self) -> set[str]:
        return set(self._used)

    def available(self) -> list[LLMProvider]:
        now = self._clock()
        return [
            p
            for i, p in enumerate(self._providers)
            if self._cooling_until.get(i, 0.0) <= now
        ]

    async def generate_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        waited = 0.0
        while True:
            now = self._clock()
            failures: list[str] = []
            any_daily = False
            for index, provider in enumerate(self._providers):
                if self._cooling_until.get(index, 0.0) > now:
                    continue
                try:
                    result = await provider.generate_json(prompt, system=system)
                except ProviderExhaustedError as exc:
                    wait = self._cooldown_for(exc)
                    any_daily = any_daily or exc.daily
                    self._cooling_until[index] = now + wait
                    logger.warning(
                        "provider %s exhausted (%s); cooling down %.0fs",
                        provider.model_name,
                        "daily cap" if exc.daily else "rate limit",
                        wait,
                    )
                    failures.append(str(exc))
                    continue
                except ProviderUnavailableError as exc:
                    self._cooling_until[index] = now + self._transient_cooldown
                    logger.warning(
                        "provider %s unavailable; cooling down %.0fs: %s",
                        provider.model_name,
                        self._transient_cooldown,
                        exc,
                    )
                    failures.append(str(exc))
                    continue
                self._last = provider
                self._used.add(provider.model_name)
                return result

            # Nobody answered: every provider is cooling. If the soonest expiry
            # is near, wait for it rather than failing the call.
            soonest = min(self._cooling_until.get(i, now) for i in range(len(self._providers)))
            wait = max(soonest - self._clock(), 0.0)
            if waited + wait <= self._max_wait:
                logger.info("all providers cooling; waiting %.1fs for the soonest", wait)
                await self._sleep(wait)
                waited += wait
                continue

            names = ", ".join(p.model_name for p in self._providers)
            raise ProviderExhaustedError(
                "pool",
                f"all {len(self._providers)} providers exhausted or cooling ({names}); "
                f"soonest retry in {wait:.0f}s exceeds max wait {self._max_wait:.0f}s; "
                f"last errors: {' | '.join(failures) or 'none this call'}",
                daily=any_daily,
            )

    def _cooldown_for(self, exc: ProviderExhaustedError) -> float:
        if exc.daily:
            return self._cooldown
        if exc.retry_after is not None:
            return min(max(exc.retry_after, 1.0), self._cooldown)
        return self._transient_cooldown

    async def close(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "close", None)
            if close is not None:
                await close()
