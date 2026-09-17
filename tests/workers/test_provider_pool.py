"""Unit tests for the provider pool — scripted fake providers, fake clock."""

import pytest

from corp.workers.providers.errors import (
    ProviderExhaustedError,
    ProviderUnavailableError,
)
from corp.workers.providers.pool import PooledProvider
from corp.workers.providers.registry import LLMProvider


class Fake(LLMProvider):
    """Answers from a script: each call pops a value to return or an exception to raise."""

    def __init__(self, name: str, script: list, closeable: bool = True):
        self._name = name
        self.script = list(script)
        self.calls = 0
        self.closed = False
        if not closeable:
            # Shadow the method so getattr(provider, "close", None) yields None,
            # like a provider that has no close() at all (e.g. GeminiProvider).
            self.close = None  # type: ignore[assignment]

    @property
    def model_name(self) -> str:
        return self._name

    async def generate_json(
        self, prompt: str, system: str | None = None, *, schema: dict | None = None
    ) -> dict:
        self.calls += 1
        item = self.script.pop(0) if self.script else {"from": self._name}
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def daily(name="gemini") -> ProviderExhaustedError:
    return ProviderExhaustedError(name, "429 daily cap", daily=True)


def _pool(*providers, clock=None, **kw) -> PooledProvider:
    clock = clock or Clock()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.t += seconds

    pool = PooledProvider(providers, clock=clock, sleep=fake_sleep, **kw)
    pool.sleeps = sleeps  # type: ignore[attr-defined]  # test-only visibility
    return pool


# ── Waiting out a short cooldown when nothing is available ───────────
# Found live: Gemini daily-capped, one Groq per-minute 429, then fifty
# instant failures because the pool had nobody left and did not wait.


async def test_waits_for_short_cooldown_when_no_provider_available():
    g = Fake("gemini", [daily()])
    q = Fake("groq", [ProviderExhaustedError("groq", "429", retry_after=5.0), {"from": "groq"}])
    clock = Clock()
    pool = _pool(g, q, clock=clock, max_wait_seconds=90)

    assert await pool.generate_json("p") == {"from": "groq"}
    assert pool.sleeps == [5.0]  # waited exactly the per-minute hint, once
    assert q.calls == 2
    assert g.calls == 1  # gemini never retried; its cap is 3600s away


async def test_does_not_wait_for_a_daily_cap():
    pool = _pool(Fake("gemini", [daily()]), Fake("groq", [daily("groq")]), max_wait_seconds=90)
    with pytest.raises(ProviderExhaustedError, match="exceeds max wait"):
        await pool.generate_json("p")
    assert pool.sleeps == []


async def test_total_wait_is_bounded():
    q = Fake("groq", [ProviderExhaustedError("groq", "429", retry_after=50.0)] * 3)
    pool = _pool(Fake("gemini", [daily()]), q, max_wait_seconds=60)
    with pytest.raises(ProviderExhaustedError, match="exceeds max wait"):
        await pool.generate_json("p")
    assert pool.sleeps == [50.0]  # one wait fit under the cap; a second would not
    assert q.calls == 2


async def test_slow_failures_count_against_the_wait_bound():
    """A provider that burns minutes timing out must not reset the cap.

    Before: the bound only summed sleep() time. A 190s Groq timeout set a
    cooldown that was already in the past, wait clamped to 0, and the loop
    retried the same provider forever with no sleep to count.
    """
    clock = Clock()

    class SlowFake(Fake):
        async def generate_json(self, prompt, system=None, *, schema=None):
            clock.t += 190.0  # the call itself takes longer than the cooldown
            return await super().generate_json(prompt, system=system, schema=schema)

    q = SlowFake("groq", [ProviderUnavailableError("groq", "timeout")] * 10)
    pool = _pool(
        Fake("gemini", [daily()]),
        q,
        clock=clock,
        transient_cooldown_seconds=60,
        max_wait_seconds=300,
    )
    with pytest.raises(ProviderExhaustedError, match="exceeds max wait"):
        await pool.generate_json("p")
    assert q.calls == 2  # t=1000 and again after the 60s cooldown; the third would pass the cap
    assert clock.t - 1000.0 >= 300.0


async def test_wait_uses_soonest_expiry_across_providers():
    g = Fake("gemini", [ProviderExhaustedError("gemini", "429", retry_after=30.0)])
    q = Fake("groq", [ProviderExhaustedError("groq", "429", retry_after=8.0), {"from": "groq"}])
    pool = _pool(g, q, max_wait_seconds=90)
    assert (await pool.generate_json("p"))["from"] == "groq"
    assert pool.sleeps == [8.0]


async def test_default_max_wait_covers_a_token_bucket_refill():
    """Found live (run #3): Groq asked for a 159s refill; a 90s bound failed
    every remaining item. The default must wait that out."""
    g = Fake("gemini", [daily()])
    q = Fake("groq", [ProviderExhaustedError("groq", "429", retry_after=159.0), {"from": "groq"}])
    pool = _pool(g, q)  # default max_wait_seconds
    assert (await pool.generate_json("p"))["from"] == "groq"
    assert pool.sleeps == [159.0]
    assert q.calls == 2


async def test_first_provider_answers_when_healthy():
    g, q = Fake("gemini", [{"a": 1}]), Fake("groq", [])
    pool = _pool(g, q)
    assert await pool.generate_json("p") == {"a": 1}
    assert (g.calls, q.calls) == (1, 0)
    assert pool.model_name == "gemini"


async def test_daily_cap_fails_over_and_cools_down():
    g, q = Fake("gemini", [daily()]), Fake("groq", [{"from": "groq"}])
    clock = Clock()
    pool = _pool(g, q, clock=clock, cooldown_seconds=3600)

    assert await pool.generate_json("p") == {"from": "groq"}
    assert pool.model_name == "groq"
    assert [p.model_name for p in pool.available()] == ["groq"]

    # Second call: gemini is skipped without being touched.
    await pool.generate_json("p")
    assert g.calls == 1
    assert q.calls == 2

    # After the cooldown gemini is tried again.
    clock.t += 3601
    g.script = [{"from": "gemini"}]
    assert await pool.generate_json("p") == {"from": "gemini"}
    assert g.calls == 2
    assert pool.model_name == "gemini"


async def test_per_minute_limit_uses_providers_retry_after():
    g = Fake("gemini", [ProviderExhaustedError("gemini", "429", retry_after=10.0)])
    q = Fake("groq", [])
    clock = Clock()
    pool = _pool(g, q, clock=clock, cooldown_seconds=3600)
    await pool.generate_json("p")
    assert pool.available() == [q]
    clock.t += 11
    assert pool.available() == [g, q]


async def test_retry_after_is_capped_by_cooldown_and_floored_at_one():
    clock = Clock()
    pool = _pool(
        Fake("a", [ProviderExhaustedError("a", "x", retry_after=99999.0)]),
        Fake("b", []),
        clock=clock,
        cooldown_seconds=100,
    )
    await pool.generate_json("p")
    clock.t += 101
    assert len(pool.available()) == 2

    pool2 = _pool(
        Fake("a", [ProviderExhaustedError("a", "x", retry_after=0.0)]), Fake("b", []), clock=clock
    )
    await pool2.generate_json("p")
    assert len(pool2.available()) == 1  # floored to 1s, still cooling at t+0


async def test_transient_outage_short_cooldown():
    g, q = Fake("gemini", [ProviderUnavailableError("gemini", "503")]), Fake("groq", [])
    clock = Clock()
    pool = _pool(g, q, clock=clock, transient_cooldown_seconds=60)
    assert (await pool.generate_json("p"))["from"] == "groq"
    clock.t += 59
    assert pool.available() == [q]
    clock.t += 2
    assert pool.available() == [g, q]


async def test_all_exhausted_raises_with_summary():
    pool = _pool(Fake("gemini", [daily()]), Fake("groq", [daily("groq")]))
    with pytest.raises(ProviderExhaustedError) as info:
        await pool.generate_json("p")
    assert info.value.provider == "pool"
    assert info.value.daily is True
    assert "gemini" in str(info.value) and "groq" in str(info.value)


async def test_all_cooling_raises_immediately_without_calls():
    g, q = Fake("gemini", [daily()]), Fake("groq", [daily("groq")])
    pool = _pool(g, q)
    with pytest.raises(ProviderExhaustedError):
        await pool.generate_json("p")
    with pytest.raises(ProviderExhaustedError, match="cooling"):
        await pool.generate_json("p")
    assert (g.calls, q.calls) == (1, 1)


async def test_call_specific_error_propagates_without_failover():
    g, q = Fake("gemini", [ValueError("unparseable")]), Fake("groq", [])
    pool = _pool(g, q)
    with pytest.raises(ValueError, match="unparseable"):
        await pool.generate_json("p")
    assert q.calls == 0
    assert pool.available() == [g, q]  # no cooldown for a per-call failure


async def test_model_name_before_any_call_is_first_available():
    g, q = Fake("gemini", [daily()]), Fake("groq", [])
    pool = _pool(g, q)
    assert pool.model_name == "gemini"
    await pool.generate_json("p")
    assert pool.model_name == "groq"


async def test_member_names_and_models_used_for_provenance():
    g, q = Fake("gemini", [daily()]), Fake("groq", [])
    clock = Clock()
    pool = _pool(g, q, clock=clock, cooldown_seconds=100)
    assert pool.member_names() == ["gemini", "groq"]
    assert pool.models_used() == set()

    await pool.generate_json("p")  # gemini capped → groq answers
    assert pool.models_used() == {"groq"}

    clock.t += 101
    g.script = [{"from": "gemini"}]
    await pool.generate_json("p")  # gemini back → answers
    assert pool.models_used() == {"groq", "gemini"}
    assert pool.member_names() == ["gemini", "groq"]  # unchanged by usage


async def test_close_closes_children_that_can_close():
    g, q = Fake("gemini", []), Fake("groq", [], closeable=False)
    pool = _pool(g, q)
    await pool.close()
    assert g.closed is True


def test_empty_pool_rejected():
    with pytest.raises(ValueError):
        PooledProvider([])
