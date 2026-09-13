"""Creator-side extraction — what problems does the creator themselves talk about?

Audience comments say what followers struggle with. The creator's own titles,
descriptions and transcripts say what the creator already addresses. The
overlap (or gap) between the two is the creator-content alignment signal.
Observations from this path are stored with ``source_side="creator"`` and
are kept out of audience clustering.
"""

import logging

from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.extraction import ExtractedObservation
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

CREATOR_PROMPT_VERSION = "creator_v1"

_SYSTEM_PROMPT = (
    "You are an analyst reading a creator's own content. Identify the audience "
    "problems, questions, and needs the creator explicitly addresses or promises "
    "to solve. Report only what the content itself states."
)

_TEMPLATE = """\
Below is a piece of {platform} content published by a creator.

Title: {title}

Content (description and/or transcript, may be truncated):
\"\"\"
{body}
\"\"\"

List every distinct audience problem, question, or need that this content addresses. \
For each, give:
- "text": one sentence naming the problem or need, in the audience's terms.
- "category": one of "problem", "question", "pain_point", "feature_request", or "general".
- "is_inferred": false unless you had to infer it from indirect cues.
- "confidence": 0.0 to 1.0.

Return JSON: {{"observations": [...]}}
"""


async def extract_creator_problems(
    provider: LLMProvider,
    title: str | None,
    body: str,
    platform: str = "youtube",
    max_body_chars: int = 6000,
) -> list[ExtractedObservation]:
    prompt = _TEMPLATE.format(
        platform=platform,
        title=(title or "untitled")[:300],
        body=body[:max_body_chars],
    )
    try:
        result = await provider.generate_json(prompt, system=_SYSTEM_PROMPT)
    except Exception as exc:
        logger.warning("Creator-content extraction failed for %.60r: %s", title, exc)
        raise LLMCallError("creator_extraction", exc) from exc

    raw = result.get("observations", []) if isinstance(result, dict) else []
    if not isinstance(raw, list):
        raw = []
    out: list[ExtractedObservation] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        out.append(
            ExtractedObservation(
                text=str(item["text"])[:500],
                category=str(item.get("category", "general")),
                is_inferred=bool(item.get("is_inferred", False)),
                confidence=min(1.0, max(0.0, float(item.get("confidence", 0.5)))),
            )
        )
    return out
