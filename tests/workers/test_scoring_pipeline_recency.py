"""Unit tests for scoring_pipeline._days_from_recency — no DB required."""

import math

from corp.workers.intelligence.scoring_pipeline import (
    _UNKNOWN_RECENCY_DAYS,
    _days_from_recency,
)


def test_recency_one_is_zero_days():
    assert _days_from_recency(1.0) == 0


def test_recency_zero_is_unknown_sentinel():
    """clustering.py reserves exactly 0.0 for "no timestamp data at all" —
    must not be treated as a specific (however old) measured age."""
    assert _days_from_recency(0.0) == _UNKNOWN_RECENCY_DAYS


def test_inverts_clustering_exponential_decay():
    days_ago = 400
    recency = math.exp(-days_ago / 365.0)
    assert _days_from_recency(recency) == days_ago


def test_different_old_ages_stay_distinguishable():
    """The bug this guards against: a 400-day-old cluster and a 4000-day-old
    cluster used to both saturate to recency_score=0.0 and therefore both
    map to the same days_since_newest — losing all distinction between
    "somewhat stale" and "ancient", and conflating both with "unknown"."""
    recency_400 = math.exp(-400 / 365.0)
    recency_4000 = math.exp(-4000 / 365.0)
    days_400 = _days_from_recency(recency_400)
    days_4000 = _days_from_recency(recency_4000)
    assert days_400 != days_4000
    assert days_400 < days_4000
