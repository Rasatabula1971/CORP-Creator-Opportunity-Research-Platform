"""Provider health signals the pool acts on.

Only these two trigger failover. Anything else a provider raises is treated
as call-specific (a bad prompt, an unparseable answer) and propagates so the
pipeline can count it against that one item.
"""


class ProviderError(Exception):
    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"{provider}: {message}")


class ProviderExhaustedError(ProviderError):
    """A quota that will not clear inside one call's retry window.

    ``retry_after`` is the provider's own hint in seconds when it gave one.
    ``daily`` marks a per-day cap: the hint (if any) is meaningless for it —
    Gemini says "retry in 40s" on a cap that resets at midnight.
    """

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        retry_after: float | None = None,
        daily: bool = False,
    ) -> None:
        self.retry_after = retry_after
        self.daily = daily
        super().__init__(provider, message)


class ProviderUnavailableError(ProviderError):
    """Transient failure (5xx, timeout, transport) that outlasted the retry budget."""
