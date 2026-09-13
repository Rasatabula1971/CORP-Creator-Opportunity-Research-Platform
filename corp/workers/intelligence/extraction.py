"""Per-comment problem/question/pain extraction via LLM."""

import logging
from dataclasses import dataclass

from corp.workers.intelligence.errors import LLMCallError
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = "extract_v1"

_SYSTEM_PROMPT = (
    "You are an analyst identifying audience problems, questions, pain points, "
    "and product requests from creator content comments. "
    "Extract only what is explicitly stated — do not infer or speculate."
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
- "is_inferred": false (only set true if you must synthesize across multiple signals — \
avoid this for single comments).
- "confidence": A float 0.0–1.0 for how clearly the comment states this.

Return JSON: {{"observations": [...]}}
If the comment contains no extractable problems/questions/pains, return {{"observations": []}}.
"""


@dataclass(frozen=True, slots=True)
class ExtractedObservation:
    """DTO for a single extracted problem observation."""

    text: str
    category: str
    is_inferred: bool
    confidence: float


async def extract_observations(
    provider: LLMProvider,
    comment_text: str,
    author: str | None,
    content_title: str | None,
    platform: str = "youtube",
) -> list[ExtractedObservation]:
    """Extract problem observations from a single comment.

    Returns a list of ExtractedObservation DTOs (may be empty).
    """
    prompt = _EXTRACTION_TEMPLATE.format(
        platform=platform,
        text=comment_text[:2000],
        author=author or "unknown",
        content_title=content_title or "untitled",
    )

    try:
        result = await provider.generate_json(prompt, system=_SYSTEM_PROMPT)
    except Exception as exc:
        logger.warning("Extraction failed for comment %.80r: %s", comment_text, exc)
        raise LLMCallError("extraction", exc) from exc

    raw_obs = result.get("observations", []) if isinstance(result, dict) else []
    if not isinstance(raw_obs, list):
        raw_obs = []
    observations: list[ExtractedObservation] = []
    for item in raw_obs:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        observations.append(
            ExtractedObservation(
                text=str(item["text"])[:500],
                category=str(item.get("category", "general")),
                is_inferred=bool(item.get("is_inferred", False)),
                confidence=min(1.0, max(0.0, float(item.get("confidence", 0.5)))),
            )
        )
    return observations
