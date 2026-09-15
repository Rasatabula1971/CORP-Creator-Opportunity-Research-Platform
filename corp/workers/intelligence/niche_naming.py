"""Name an evidence cluster as a niche candidate (Slice 8, §16).

The LLM's role here is the one §16 allows — *name a cluster* — and nothing
more. It sees only the member texts, must cite the evidence terms that justify
the name, and its answer is accepted only when every cited term actually
occurs in those texts. An ungrounded answer is not an error the caller must
handle; it simply is not used (``ClusterName.grounded`` is False) and the
deterministic keyword label stands.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from corp.workers.intelligence.errors import LLMCallError
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

NAMING_PROMPT_VERSION = "niche_name_v1"
MAX_TEXTS = 12
MAX_TEXT_CHARS = 300

# Strict-mode shape (every property required, no extras) — see
# docs/DECISIONS/0010 for why.
NICHE_NAME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", "is_broad_domain", "confidence", "evidence_terms"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "is_broad_domain": {"type": "boolean"},
        "confidence": {"type": "number"},
        "evidence_terms": {"type": "array", "items": {"type": "string"}},
    },
}

_SYSTEM_PROMPT = (
    "You name clusters of public market evidence (video titles, posts, comments) as "
    "candidate niches for creator research. A niche is the smallest coherent "
    "audience/problem domain that still has real activity — e.g. 'Home Espresso', "
    "'Sim Racing', 'Reef Aquariums' — not a broad industry like 'Cars' or 'Fitness'.\n\n"
    "Rules:\n"
    "- Name ONLY what the texts support. Do not add products, audiences or problems "
    "that are not in the texts.\n"
    "- The name is 2 to 5 words, Title Case, no punctuation.\n"
    "- Cite 3 to 6 evidence_terms: exact words or short phrases copied from the texts "
    "that justify the name. They must appear verbatim in the texts.\n"
    "- If the texts only support a broad industry or topic, still name it, and set "
    "is_broad_domain to true.\n"
    "- confidence is 0.0 to 1.0 for how clearly the texts form one niche.\n\n"
    'Return only JSON: {"name": str, "description": str (one sentence), '
    '"is_broad_domain": bool, "confidence": number, "evidence_terms": [str]}'
)

_TEMPLATE = (
    "Platform: {platform}\n"
    "Evidence texts ({count} of {total} in the cluster):\n{texts}\n\n"
    "Name this cluster as a candidate niche."
)


@dataclass(frozen=True, slots=True)
class ClusterName:
    name: str
    description: str
    is_broad_domain: bool
    confidence: float
    evidence_terms: list[str] = field(default_factory=list)
    grounded: bool = False
    ungrounded_terms: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def check_grounding(terms: list[str], texts: list[str]) -> list[str]:
    """Return the cited terms that do NOT occur in the texts (case/space-insensitive)."""
    corpus = _normalize(" \n ".join(texts))
    missing: list[str] = []
    for term in terms:
        needle = _normalize(term).strip()
        if len(needle) < 3 or needle not in corpus:
            missing.append(term)
    return missing


async def name_cluster(
    provider: LLMProvider, texts: list[str], *, platform: str = "mixed"
) -> ClusterName:
    """Ask the provider to name a cluster; verify every cited term against the texts.

    Raises :class:`LLMCallError` when the provider call itself fails. Returns a
    ``ClusterName`` whose ``grounded`` flag says whether the answer may be used
    as the candidate's label.
    """
    shown = [t.strip()[:MAX_TEXT_CHARS] for t in texts if t and t.strip()][:MAX_TEXTS]
    prompt = _TEMPLATE.format(
        platform=platform,
        count=len(shown),
        total=len(texts),
        texts="\n".join(f"- {t}" for t in shown),
    )
    try:
        result = await provider.generate_json(
            prompt, system=_SYSTEM_PROMPT, schema=NICHE_NAME_SCHEMA
        )
    except Exception as exc:
        logger.warning("Niche naming failed for %d texts: %s", len(texts), exc)
        raise LLMCallError("niche_naming", exc) from exc

    if not isinstance(result, dict):
        result = {}
    name = str(result.get("name") or "").strip()[:255]
    terms_raw = result.get("evidence_terms")
    terms = (
        [str(t).strip() for t in terms_raw if str(t).strip()] if isinstance(terms_raw, list) else []
    )
    missing = check_grounding(terms, shown) if terms else []
    grounded = bool(name) and bool(terms) and not missing
    if not grounded:
        logger.info(
            "Niche name %r not grounded (terms=%s missing=%s); keyword label will stand",
            name,
            terms,
            missing,
        )
    try:
        confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return ClusterName(
        name=name,
        description=str(result.get("description") or "").strip()[:2000],
        is_broad_domain=bool(result.get("is_broad_domain", False)),
        confidence=confidence,
        evidence_terms=terms[:10],
        grounded=grounded,
        ungrounded_terms=missing,
    )
