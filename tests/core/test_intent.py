from corp.core.models.intent import SignalLevel
from corp.core.intent.hierarchy import classify_signal_level


RULES = {
    "levels": {
        "validation": {"keywords": ["bought", "purchased", "subscribed", "paying for"]},
        "strong": {"keywords": ["where can I buy", "pricing", "recommend a"]},
        "moderate": {"keywords": ["how do I", "struggling with", "frustrated"]},
        "weak": {"keywords": ["annoying", "wish", "sucks"]},
    }
}


def test_validation_signal():
    result = classify_signal_level(["I already purchased this"], RULES)
    assert result == SignalLevel.VALIDATION


def test_strong_signal():
    result = classify_signal_level(["where can I buy one?"], RULES)
    assert result == SignalLevel.STRONG


def test_moderate_signal():
    result = classify_signal_level(["how do I fix this?"], RULES)
    assert result == SignalLevel.MODERATE


def test_weak_signal():
    result = classify_signal_level(["this is annoying"], RULES)
    assert result == SignalLevel.WEAK


def test_unknown_defaults_to_weak():
    result = classify_signal_level(["hello world"], RULES)
    assert result == SignalLevel.WEAK


def test_highest_match_wins():
    result = classify_signal_level(
        ["I already purchased this and it's annoying"], RULES
    )
    assert result == SignalLevel.VALIDATION


# ── whole-word matching (no substring false positives) ───────────────

_VS_RULES = {
    "levels": {
        "validation": {"keywords": ["vs", "compared"]},
        "strong": {"keywords": ["pricing"]},
        "moderate": {"keywords": []},
        "weak": {"keywords": []},
    }
}


def test_keyword_does_not_match_inside_another_word():
    # "vs" must not fire on "devs"; "compared" must not fire on "comparedware".
    assert classify_signal_level(["the devs are great"], _VS_RULES) == SignalLevel.WEAK
    assert classify_signal_level(["comparedware rocks"], _VS_RULES) == SignalLevel.WEAK
    assert classify_signal_level(["I love my new tvs"], _VS_RULES) == SignalLevel.WEAK


def test_keyword_matches_as_whole_word():
    assert classify_signal_level(["React vs Vue"], _VS_RULES) == SignalLevel.VALIDATION
    assert (
        classify_signal_level(["I compared them all"], _VS_RULES)
        == SignalLevel.VALIDATION
    )


def test_multiword_phrase_still_matches():
    assert classify_signal_level(["what is the pricing?"], _VS_RULES) == SignalLevel.STRONG
