"""Per-comment and batch problem/question/pain extraction via LLM."""

import logging
from dataclasses import dataclass
from typing import Any

from corp.workers.intelligence.coerce import as_bool, as_float
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

# v3 adds sentiment/urgency (from main's tier2) and cross-comment batch mode.
EXTRACTION_PROMPT_VERSION = "extract_v3"

# JSON Schema of the answer, for providers that verify or enforce shape (FAIR,
# Groq json_schema). Strict-mode: every object lists every property as required
# and forbids extras. The parser below stays lenient so a usable answer is
# never rejected for a missing optional field.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["observations"],
    "properties": {
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "text",
                    "category",
                    "sentiment",
                    "urgency",
                    "is_inferred",
                    "confidence",
                ],
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string"},
                    "sentiment": {"type": "string"},
                    "urgency": {"type": "string"},
                    "is_inferred": {"type": "boolean"},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}

# Same schema, with the batch-mode extra `source_indices` field, which
# providers add for observations synthesized across multiple comments.
BATCH_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["observations"],
    "properties": {
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "text",
                    "category",
                    "sentiment",
                    "urgency",
                    "is_inferred",
                    "confidence",
                    "source_indices",
                ],
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string"},
                    "sentiment": {"type": "string"},
                    "urgency": {"type": "string"},
                    "is_inferred": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "source_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
            },
        }
    },
}

_SYSTEM_PROMPT = (
    "You are an analyst identifying audience problems, questions, pain points, "
    "and product requests from creator content comments. "
    "Extract what is explicitly stated and, in batch mode, synthesize patterns "
    "that appear across multiple comments."
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
- "is_inferred": false for a single comment (only true when synthesized across many).
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
1. Individual observations from single comments
2. Recurring patterns that appear across multiple comments (mark is_inferred=true \
and cite every supporting index)

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
    is_inferred: bool
    confidence: float
    sentiment: str = "neutral"
    urgency: str = "low"
    # Batch mode only: 0-based indices of the input comments the observation
    # is grounded in. None on single-comment extraction.
    source_indices: list[int] | None = None


_ALLOWED_SENTIMENT = {"positive", "neutral", "negative"}
_ALLOWED_URGENCY = {"low", "medium", "high"}


def _parse_observation(
    item: Any, fallback_index: int | None = None,
) -> ExtractedObservation | None:
    if not isinstance(item, dict) or not item.get("text"):
        return None

    sentiment_raw = str(item.get("sentiment", "neutral")).lower()
    sentiment = sentiment_raw if sentiment_raw in _ALLOWED_SENTIMENT else "neutral"

    urgency_raw = str(item.get("urgency", "low")).lower()
    urgency = urgency_raw if urgency_raw in _ALLOWED_URGENCY else "low"

    source_indices = item.get("source_indices")
    if source_indices is not None:
        if isinstance(source_indices, list):
            source_indices = [int(i) for i in source_indices if isinstance(i, (int, float))]
        else:
            source_indices = None
    if source_indices is None and fallback_index is not None:
        source_indices = [fallback_index]

    return ExtractedObservation(
        text=str(item["text"])[:500],
        category=str(item.get("category", "general")),
        sentiment=sentiment,
        urgency=urgency,
        is_inferred=as_bool(item.get("is_inferred"), False),
        confidence=min(1.0, max(0.0, as_float(item.get("confidence"), 0.5))),
        source_indices=source_indices,
    )


async def extract_observations(
    provider: LLMProvider,
    comment_text: str,
    author: str | None,
    content_title: str | None,
    platform: str = "youtube",
) -> list[ExtractedObservation]:
    """Extract problem observations from a single comment.

    Raises ``LLMCallError`` when the underlying provider fails, so the caller's
    pipeline can distinguish a real failure from "the comment had nothing
    extractable" (an empty list) rather than silently conflating the two.
    """
    prompt = _EXTRACTION_TEMPLATE.format(
        platform=platform,
        text=comment_text[:2000],
        author=author or "unknown",
        content_title=content_title or "untitled",
    )

    try:
        result = await provider.generate_json(
            prompt, system=_SYSTEM_PROMPT, schema=EXTRACTION_SCHEMA
        )
    except Exception as exc:
        logger.warning("Extraction failed for comment %.80r: %s", comment_text, exc)
        raise LLMCallError("extraction", exc) from exc

    raw_obs = result.get("observations", []) if isinstance(result, dict) else []
    if not isinstance(raw_obs, list):
        raw_obs = []
    observations: list[ExtractedObservation] = []
    for item in raw_obs:
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
        comments: List of ``{"text": str, "author": str | None}`` dicts. Order
            matters — each observation cites the input indices it came from.
        content_title: Title of the content the comments belong to.
        platform: Source platform.

    Returns:
        A list of ``ExtractedObservation``. Inferred (cross-comment) observations
        carry ``source_indices`` referencing every supporting comment.

    Raises ``LLMCallError`` on provider failure (same reasoning as the single-
    comment variant).
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
        result = await provider.generate_json(
            prompt, system=_SYSTEM_PROMPT, schema=BATCH_EXTRACTION_SCHEMA
        )
    except Exception as exc:
        logger.warning("Batch extraction failed for %d comments: %s", len(comments), exc)
        raise LLMCallError("extraction_batch", exc) from exc

    raw_obs = result.get("observations", []) if isinstance(result, dict) else []
    if not isinstance(raw_obs, list):
        raw_obs = []
    observations: list[ExtractedObservation] = []
    for item in raw_obs:
        obs = _parse_observation(item)
        if obs is not None:
            observations.append(obs)
    return observations
