from corp.core.scoring.engine import compute_hash, compute_score


def test_compute_score_weighted_average():
    components = {"frequency": 0.8, "recency": 0.6, "intent": 0.9}
    weights = {"frequency": 0.25, "recency": 0.15, "intent": 0.20}
    score = compute_score(components, weights)
    expected = (0.8 * 0.25 + 0.6 * 0.15 + 0.9 * 0.20) / (0.25 + 0.15 + 0.20)
    assert abs(score - expected) < 1e-10


def test_compute_score_zero_weights():
    components = {"a": 0.5}
    weights = {"b": 1.0}
    assert compute_score(components, weights) == 0.0


def test_compute_hash_deterministic():
    components = {"frequency": 0.8, "recency": 0.6}
    h1 = compute_hash(components, "v1.0.0")
    h2 = compute_hash(components, "v1.0.0")
    assert h1 == h2


def test_compute_hash_changes_with_input():
    c1 = {"frequency": 0.8, "recency": 0.6}
    c2 = {"frequency": 0.8, "recency": 0.7}
    assert compute_hash(c1, "v1.0.0") != compute_hash(c2, "v1.0.0")


def test_compute_hash_changes_with_rule_version():
    components = {"frequency": 0.8}
    assert compute_hash(components, "v1.0.0") != compute_hash(components, "v1.1.0")
