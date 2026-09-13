"""Commercial intent classification via LLM + rules hierarchy."""

import logging
from dataclasses import dataclass
from pathlib import Path

from corp.core.intent.hierarchy import classify_signal_level, load_intent_rules
from corp.core.models.intent import SignalLevel
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

INTENT_PROMPT_VERSION = "intent_v1"

_SYSTEM_PROMPT = (
    "You are a commercial intent analyst. Given a problem cluster and "
    "representative audience comments, classify the commercial purchase intent "
    "level and explain your reasoning."
)

_CLASSIFICATION_TEMPLATE = """\
Analyze the following problem cluster from a creator's audience.

Cluster label: "{label}"
Cluster description: "{description}"
Frequency: {frequency} observations
Evidence strength: {evidence_strength}

Representative comments:
{comments}

Signal hierarchy (highest to lowest):
- validation: Audience already paying for alternatives or reviewing competitors
- strong: Direct purchase intent, pricing questions, explicit product requests
- moderate: Specific problem descriptions, comparison seeking, solution hunting
- weak: General complaints, vague wishes, opinions without action

Classify the commercial intent of this cluster.
Return JSON: {{
  "signal_level": "validation" | "strong" | "moderate" | "weak",
  "rationale": "One-sentence explanation of why this level was chosen",
  "confidence": 0.0-1.0,
  "key_indicators": ["list", "of", "specific", "phrases", "from", "comments"]
}}
"""


@dataclass(frozen=True, slots=True)
class IntentClassification:
    """DTO for a classified commercial signal."""

    signal_level: SignalLevel
    rationale: str
    confidence: float
    key_indicators: list[str]


async def classify_cluster_intent(
    provider: LLMProvider,
    label: str,
    description: str,
    frequency: int,
    evidence_strength: float,
    representative_texts: list[str],
    rules_path: str | Path | None = None,
) -> IntentClassification:
    """Classify a problem cluster's commercial intent.

    Uses both LLM classification and rules-table matching. The rules-table
    result is used as a floor: the LLM can elevate but not lower the signal.
    """
    rules_level = _rules_classify(representative_texts, rules_path)

    llm_result = await _llm_classify(
        provider, label, description, frequency, evidence_strength, representative_texts
    )

    final_level = _reconcile(rules_level, llm_result.signal_level)

    return IntentClassification(
        signal_level=final_level,
        rationale=llm_result.rationale,
        confidence=llm_result.confidence,
        key_indicators=llm_result.key_indicators,
    )


def _rules_classify(
    texts: list[str],
    rules_path: str | Path | None,
) -> SignalLevel:
    """Classify using the YAML rules table as a baseline."""
    if rules_path is None:
        rules_path = Path("rules/intent.yaml")
    try:
        rules = load_intent_rules(rules_path)
    except FileNotFoundError:
        logger.warning("Intent rules not found at %s, defaulting to WEAK", rules_path)
        return SignalLevel.WEAK

    return classify_signal_level(texts, rules)


_LEVEL_ORDER = {
    SignalLevel.WEAK: 0,
    SignalLevel.MODERATE: 1,
    SignalLevel.STRONG: 2,
    SignalLevel.VALIDATION: 3,
}


def _reconcile(rules_level: SignalLevel, llm_level: SignalLevel) -> SignalLevel:
    """Take the higher of rules-table and LLM classifications."""
    if _LEVEL_ORDER.get(llm_level, 0) >= _LEVEL_ORDER.get(rules_level, 0):
        return llm_level
    return rules_level


async def _llm_classify(
    provider: LLMProvider,
    label: str,
    description: str,
    frequency: int,
    evidence_strength: float,
    texts: list[str],
) -> IntentClassification:
    comments_str = "\n".join(f"- {t[:300]}" for t in texts[:10])
    prompt = _CLASSIFICATION_TEMPLATE.format(
        label=label,
        description=description[:500],
        frequency=frequency,
        evidence_strength=evidence_strength,
        comments=comments_str,
    )

    try:
        result = await provider.generate_json(prompt, system=_SYSTEM_PROMPT)
    except Exception as exc:
        logger.warning("LLM intent classification failed for cluster %s: %s", label, exc)
        raise LLMCallError("intent", exc) from exc

    if not isinstance(result, dict):
        result = {}
    level_str = str(result.get("signal_level", "weak")).lower()
    try:
        level = SignalLevel(level_str)
    except ValueError:
        level = SignalLevel.WEAK

    return IntentClassification(
        signal_level=level,
        rationale=str(result.get("rationale", ""))[:500],
        confidence=min(1.0, max(0.0, float(result.get("confidence", 0.5)))),
        key_indicators=[str(k)[:200] for k in result.get("key_indicators", [])[:10]],
    )
