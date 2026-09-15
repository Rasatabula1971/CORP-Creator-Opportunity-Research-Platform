"""Topic classification for creator content via LLM."""

import logging
from typing import Any

from corp.workers.intelligence.errors import LLMCallError
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

TOPIC_PROMPT_VERSION = "topics_v1"

# JSON Schema of the answer, for providers that verify or enforce shape (FAIR).
# Strict-mode shape (Groq's json_schema mode rejects anything else): every object
# lists all its properties as required and forbids extras. The parser below stays
# lenient for providers that only see the prompt.
TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topics"],
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "confidence", "evidence_count"],
                "properties": {
                    "name": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_count": {"type": "integer"},
                },
            },
        }
    },
}

_SYSTEM_PROMPT = (
    "You classify a creator's content into topic categories based on their "
    "video titles, descriptions, and audience comments."
)

_TOPIC_TEMPLATE = """\
Given the following content items from a {platform} creator, identify the main topics \
they cover.

Content titles and descriptions:
{content_list}

Return JSON: {{"topics": [
  {{"name": "topic name", "confidence": 0.0-1.0, "evidence_count": N}}
]}}

Rules:
- Include 3–10 topics, ordered by relevance.
- Each topic name should be 1–4 words.
- confidence reflects how central this topic is to the creator's content.
- evidence_count is how many of the listed items relate to this topic.
"""


async def classify_topics(
    provider: LLMProvider,
    content_items: list[dict],
    platform: str = "youtube",
) -> list[dict]:
    """Classify a creator's content into topics.

    Args:
        provider: LLM provider instance.
        content_items: List of dicts with 'title' and optional 'description' keys.
        platform: Source platform name.

    Returns:
        List of topic dicts: [{"name": str, "confidence": float, "evidence_count": int}].
    """
    lines: list[str] = []
    for i, item in enumerate(content_items[:50], 1):
        title = item.get("title", "untitled")
        desc = item.get("description", "")
        line = f"{i}. {title}"
        if desc:
            line += f" — {desc[:200]}"
        lines.append(line)

    prompt = _TOPIC_TEMPLATE.format(
        platform=platform,
        content_list="\n".join(lines),
    )

    try:
        result = await provider.generate_json(prompt, system=_SYSTEM_PROMPT, schema=TOPIC_SCHEMA)
    except Exception as exc:
        logger.warning("Topic classification failed: %s", exc)
        raise LLMCallError("topics", exc) from exc

    raw_topics = result.get("topics", []) if isinstance(result, dict) else []
    if not isinstance(raw_topics, list):
        raw_topics = []
    topics: list[dict] = []
    for t in raw_topics:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        topics.append(
            {
                "name": str(t["name"])[:100],
                "confidence": min(1.0, max(0.0, float(t.get("confidence", 0.5)))),
                "evidence_count": int(t.get("evidence_count", 0)),
            }
        )
    return topics
