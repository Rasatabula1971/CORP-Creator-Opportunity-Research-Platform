"""Problem/question/pain extraction via LLM — single and batch modes."""

import logging
from dataclasses import dataclass

from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = "extract_v2"

_SYSTEM_PROMPT = (
    "You are an analyst identifying audience problems, questions, pain points, "
    "and product requests from creator content comments. "
    "Extract what is explicitly stated and synthesize patterns across comments."
)

_EXTRACTION_TEMPLATE = """\
Analyze the following audience comment from a {platform} creator's content.

Comment: "{text}"
Author: {author}
Content title: {content_title}

Extract every distinct problem, question, pain point, or product request the commenter \
expresses. For each, determine:
- "text": A concise one-sentence description of the problem/question/pain/request.
- "category": One of "problem", "question", "pain_point", "feature_request", or "general".
- "sentiment": One of "positive", "neutral", or "negative".
- "urgency": One of "low", "medium", or "high". \
High = desperate, blocked, or can't work without a solution. \
Medium = frustrated, actively seeking alternatives. \
Low = mild observation, passing mention.
- "is_inferred": false (only set true if you must synthesize across multiple signals — \
avoid this for single comments).
- "confidence": A float 0.0–1.0 for how clearly the comment states this.

Return JSON: {{"observations": [...]}}
If the comment contains no extractable problems/questions/pains, return {{"observations": []}}.
"""

_BATCH_EXTRACTION_TEMPLATE = """\
Analyze the following batch of {count} audience comments from a {platform} creator's \
content titled "{content_title}".

Comments:
{comments}

Extract distinct problems, questions, pain points, and product requests. Look for:
1. **Individual observations** from single comments
2. **Recurring patterns** that appear across multiple comments (mark is_inferred=true)

For each observation:
- "text": Concise one-sentence description
- "category": "problem" | "question" | "pain_point" | "feature_request" | "general"
- "sentiment": "positive" | "neutral" | "negative"
- "urgency": "low" | "medium" | "high" \
(high = desperate/blocked, medium = frustrated/seeking, low = mild/observational)
- "is_inferred": true only if synthesized across multiple comments
- "confidence": float 0.0–1.0
- "source_indices": list of 0-based comment indices that support this observation

Return JSON: {{"observations": [...]}}
If no extractable problems/questions/pains exist, return {{"observations": []}}.
"""


@dataclass(frozen=True, slots=True)
class ExtractedObservation:
    """DTO for a single extracted problem observation."""

    text: str
    category: str
    sentiment: str
    urgency: str
    is_inferred: bool
    confidence: float
    source_indices: list[int] | None = None


def _parse_observation(
    item: dict, fallback_index: int | None = None,
) -> ExtractedObservation | None:
    if not isinstance(item, dict) or not item.get("text"):
        return None

    sentiment_raw = str(item.get("sentiment", "neutral")).lower()
    sentiment = sentiment_raw if sentiment_raw in ("positive", "neutral", "negative") else "neutral"

    urgency_raw = str(item.get("urgency", "low")).lower()
    urgency = urgency_raw if urgency_raw in ("low", "medium", "high") else "low"

    source_indices = item.get("source_indices")
    if source_indices is not None and not isinstance(source_indices, list):
        source_indices = None
    if source_indices is None and fallback_index is not None:
        source_indices = [fallback_index]

    return ExtractedObservation(
        text=str(item["text"])[:500],
        category=str(item.get("category", "general")),
        sentiment=sentiment,
        urgency=urgency,
        is_inferred=bool(item.get("is_inferred", False)),
        confidence=min(1.0, max(0.0, float(item.get("confidence", 0.5)))),
        source_indices=source_indices,
    )


async def extract_observations(
    provider: LLMProvider,
    comment_text: str,
    author: str | None,
    content_title: str | None,
    platform: str = "youtube",
) -> list[ExtractedObservation]:
    """Extract problem observations from a single comment."""
    prompt = _EXTRACTION_TEMPLATE.format(
        platform=platform,
        text=comment_text[:2000],
        author=author or "unknown",
        content_title=content_title or "untitled",
    )

    try:
        result = await provider.generate_json(prompt, system=_SYSTEM_PROMPT)
    except Exception:
        logger.exception("Extraction failed for comment: %.80s", comment_text)
        return []

    observations: list[ExtractedObservation] = []
    for item in result.get("observations", []):
        obs = _parse_observation(item)
        if obs is not None:
            observations.append(obs)
    return observations


async def extract_observations_batch(
    provider: LLMProvider,
    comments: list[dict],
    content_title: str | None,
    platform: str = "youtube",
) -> list[ExtractedObservation]:
    """Extract observations from a batch of comments with cross-comment synthesis.

    Args:
        provider: LLM provider.
        comments: List of {"text": str, "author": str | None} dicts.
        content_title: Title of the content the comments belong to.
        platform: Source platform.

    Returns:
        List of ExtractedObservation with source_indices linking back to input.
    """
    if not comments:
        return []

    comment_lines = []
    for i, c in enumerate(comments):
        author = c.get("author") or "unknown"
        text = (c.get("text") or "")[:500]
        comment_lines.append(f"[{i}] @{author}: {text}")

    prompt = _BATCH_EXTRACTION_TEMPLATE.format(
        count=len(comments),
        platform=platform,
        content_title=content_title or "untitled",
        comments="\n".join(comment_lines),
    )

    try:
        result = await provider.generate_json(prompt, system=_SYSTEM_PROMPT)
    except Exception:
        logger.exception("Batch extraction failed for %d comments", len(comments))
        return []

    observations: list[ExtractedObservation] = []
    for item in result.get("observations", []):
        obs = _parse_observation(item)
        if obs is not None:
            observations.append(obs)
    return observations
