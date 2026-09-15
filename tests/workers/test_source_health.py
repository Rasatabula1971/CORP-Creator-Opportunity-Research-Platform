"""Tests for the source health tracker — circuit breaker logic."""

import time

import pytest

from corp.workers.adapters.health import (
    SourceHealthRecord,
    SourceHealthTracker,
    SourceStatus,
)


@pytest.fixture
def tmp_data(tmp_path):
    return tmp_path / "corp_data"


@pytest.fixture
def tracker(tmp_data):
    return SourceHealthTracker(
        tmp_data,
        degrade_after=3,
        disconnect_after=5,
        probe_cooldown=60.0,
    )


# ── SourceHealthRecord ───────────────────────────────────────────────


def test_record_roundtrip():
    rec = SourceHealthRecord(platform="appstore", total_successes=5)
    d = rec.to_dict()
    rec2 = SourceHealthRecord.from_dict(d)
    assert rec2.platform == "appstore"
    assert rec2.total_successes == 5


def test_record_from_dict_ignores_extra_keys():
    rec = SourceHealthRecord.from_dict({"platform": "x", "unknown_key": 123})
    assert rec.platform == "x"


# ── Healthy by default ───────────────────────────────────────────────


def test_new_source_is_healthy(tracker):
    assert tracker.get_status("hackernews") == SourceStatus.HEALTHY
    assert tracker.is_available("hackernews")


# ── Success resets failures ──────────────────────────────────────────


def test_success_resets_consecutive_failures(tracker):
    for _ in range(2):
        tracker.record_failure("hackernews", RuntimeError("timeout"))
    tracker.record_success("hackernews")

    rec = tracker.get_record("hackernews")
    assert rec.consecutive_failures == 0
    assert rec.status == SourceStatus.HEALTHY
    assert rec.total_failures == 2
    assert rec.total_successes == 1


# ── Degradation ──────────────────────────────────────────────────────


def test_degrades_after_threshold(tracker):
    for i in range(3):
        tracker.record_failure("appstore", RuntimeError(f"fail {i}"))

    assert tracker.get_status("appstore") == SourceStatus.DEGRADED
    assert tracker.is_available("appstore")


# ── Disconnection ────────────────────────────────────────────────────


def test_disconnects_after_threshold(tracker):
    for i in range(5):
        tracker.record_failure("appstore", RuntimeError(f"fail {i}"))

    assert tracker.get_status("appstore") == SourceStatus.DISCONNECTED
    assert not tracker.is_available("appstore")


# ── Probe after cooldown ─────────────────────────────────────────────


def test_probe_after_cooldown(tracker):
    for i in range(5):
        tracker.record_failure("appstore", RuntimeError(f"fail {i}"))

    assert not tracker.is_available("appstore")

    rec = tracker.get_record("appstore")
    rec.disconnected_at = time.time() - 120.0

    assert tracker.is_available("appstore")


# ── Failed probe re-arms the cooldown ────────────────────────────────


def test_failed_probe_rearms_cooldown(tracker):
    # disconnect_after=5 in the fixture.
    for i in range(5):
        tracker.record_failure("appstore", RuntimeError(f"fail {i}"))
    assert not tracker.is_available("appstore")

    # Cooldown elapses → one probe is allowed.
    rec = tracker.get_record("appstore")
    rec.disconnected_at = time.time() - 120.0
    assert tracker.is_available("appstore")

    # The probe fails. This must re-arm the cooldown, not leave it elapsed.
    tracker.record_failure("appstore", RuntimeError("probe failed"))
    assert tracker.get_status("appstore") == SourceStatus.DISCONNECTED
    assert not tracker.is_available("appstore")  # throttled again, not green-lit forever


# ── Recovery from disconnected ───────────────────────────────────────


def test_recovery_from_disconnected(tracker):
    for i in range(5):
        tracker.record_failure("appstore", RuntimeError(f"fail {i}"))
    assert tracker.get_status("appstore") == SourceStatus.DISCONNECTED

    tracker.record_success("appstore")
    assert tracker.get_status("appstore") == SourceStatus.HEALTHY
    assert tracker.is_available("appstore")


# ── Persistence ──────────────────────────────────────────────────────


def test_save_and_load(tmp_data):
    tracker1 = SourceHealthTracker(tmp_data)
    tracker1.record_success("hackernews")
    tracker1.record_failure("appstore", RuntimeError("down"))
    tracker1.save()

    tracker2 = SourceHealthTracker(tmp_data)
    tracker2.load()

    assert tracker2.get_record("hackernews").total_successes == 1
    assert tracker2.get_record("appstore").total_failures == 1


def test_load_missing_file(tracker):
    tracker.load()
    assert tracker.get_status("anything") == SourceStatus.HEALTHY


def test_load_corrupt_file(tmp_data):
    health_file = tmp_data / "adapter_health.json"
    health_file.parent.mkdir(parents=True, exist_ok=True)
    health_file.write_text("not json", encoding="utf-8")

    tracker = SourceHealthTracker(tmp_data)
    tracker.load()
    assert tracker.get_status("anything") == SourceStatus.HEALTHY


# ── Summary ──────────────────────────────────────────────────────────


def test_summary(tracker):
    tracker.record_success("hackernews")
    tracker.record_failure("appstore", RuntimeError("fail"))

    s = tracker.summary()
    assert "hackernews" in s
    assert "appstore" in s
    assert s["hackernews"]["total_successes"] == 1
    assert s["appstore"]["total_failures"] == 1


# ── Error message truncation ────────────────────────────────────────


def test_error_truncated(tracker):
    tracker.record_failure("x", RuntimeError("a" * 1000))
    rec = tracker.get_record("x")
    assert len(rec.last_error) <= 500
