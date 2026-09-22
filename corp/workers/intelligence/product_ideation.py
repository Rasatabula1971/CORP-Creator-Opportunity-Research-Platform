"""Product idea generation (CORP1 Stage 5, T5).

Takes one creator's active problem clusters (evidence, already-extracted
audience signals) plus the creator's own profile, and asks an LLM to
propose 3-5 concrete digital products per cluster that would fit the
creator's brand. Every idea must cite evidence_terms that verifiably
appear in the cluster's evidence, exactly the same grounding mechanism
T3's niche synthesis uses (``niche_naming.check_grounding``, reused
unchanged) -- an idea that fails grounding is dropped, never given a
fabricated rationale. See ``corp.core.models.product_idea`` for why this
traces provenance via ``ProductIdeaEvidence`` back to the observation rows
rather than writing a separate ``origin = inference`` Evidence row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.creator import Creator
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import ProblemCluster, ProblemClusterMember, ProblemObservation
from corp.core.models.product_idea import (
    ProductIdea,
    ProductIdeaComplexity,
    ProductIdeaEvidence,
    ProductIdeaType,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.core.scoring.niche_qualification import load_rules
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.niche_naming import check_grounding
from corp.workers.intelligence.runs import (
    PipelineStats,
    active_clusters_for_creator,
    fail_run,
    finish_run,
    start_run,
    supersede,
)
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

PIPELINE = "product_ideation"

_TYPE_VALUES = ", ".join(t.value for t in ProductIdeaType)
_COMPLEXITY_VALUES = ", ".join(c.value for c in ProductIdeaComplexity)

SYSTEM_PROMPT = (
    "You propose concrete digital products for a content creator's audience, "
    "based only on the problems their audience actually raises. A good idea "
    "is something the creator could brand and sell to their own audience -- "
    "a template, calculator, guide, checklist, course, app, tracker, "
    "database, membership, or AI tool.\n\n"
    "Rules:\n"
    "- Propose ONLY products the evidence supports. Do not invent problems, "
    "audiences, or products not grounded in the evidence shown.\n"
    "- Each product must plausibly fit the creator's own niche and brand.\n"
    f"- type must be exactly one of: {_TYPE_VALUES}\n"
    f"- complexity must be exactly one of: {_COMPLEXITY_VALUES} (build effort "
    "for the creator, not the audience's problem severity)\n"
    "- Cite 2 to 6 evidence_terms: exact words or short phrases copied from "
    "the evidence that justify this specific product. They must appear "
    "verbatim in the evidence shown.\n"
    "- fit_rationale is one or two sentences on why this fits this creator's "
    "brand specifically, not creators in general.\n"
    "- price_min/price_max are a plausible USD range for this exact product.\n"
    "- Return between {min_ideas} and {max_ideas} ideas, strongest evidence first.\n\n"
    'Return only JSON: {{"ideas": [{{"title": str, "description": str, '
    '"type": str, "complexity": str, "price_min": number, "price_max": number, '
    '"fit_rationale": str, "evidence_terms": [str]}}]}}'
)

PROMPT_TEMPLATE = (
    "Creator: {creator_name}"
    "{creator_niche}\n"
    "Problem cluster: {cluster_label}\n"
    "Evidence ({count} of {total} items):\n{texts}\n\n"
    "Propose digital products for this creator's audience based on this problem cluster."
)


@dataclass(frozen=True, slots=True)
class ProposedIdea:
    title: str
    description: str
    idea_type: ProductIdeaType
    complexity: ProductIdeaComplexity
    price_min: float | None
    price_max: float | None
    fit_rationale: str
    evidence_terms: list[str] = field(default_factory=list)


def _schema(min_ideas: int, max_ideas: int) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["ideas"],
        "properties": {
            "ideas": {
                "type": "array",
                "minItems": min_ideas,
                "maxItems": max_ideas,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "title",
                        "description",
                        "type",
                        "complexity",
                        "price_min",
                        "price_max",
                        "fit_rationale",
                        "evidence_terms",
                    ],
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "type": {"type": "string"},
                        "complexity": {"type": "string"},
                        "price_min": {"type": "number"},
                        "price_max": {"type": "number"},
                        "fit_rationale": {"type": "string"},
                        "evidence_terms": {"type": "array", "items": {"type": "string"}},
                    },
                },
            }
        },
    }


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


async def propose_ideas(
    provider: LLMProvider,
    creator: Creator,
    cluster: ProblemCluster,
    texts: list[str],
    *,
    min_ideas: int,
    max_ideas: int,
    max_text_chars: int,
) -> list[ProposedIdea]:
    """Ask the provider for ideas grounded in ``texts``; keep only the
    ones whose cited evidence_terms are actually grounded in what was
    shown, and whose type/complexity match the frozen vocabulary."""
    shown = [t.strip()[:max_text_chars] for t in texts if t and t.strip()][:40]
    if not shown:
        return []

    creator_niche = f" (niche: {creator.niche})" if creator.niche else ""
    prompt = PROMPT_TEMPLATE.format(
        creator_name=creator.name,
        creator_niche=creator_niche,
        cluster_label=cluster.label,
        count=len(shown),
        total=len(texts),
        texts="\n".join(f"- {t}" for t in shown),
    )
    system = SYSTEM_PROMPT.format(min_ideas=min_ideas, max_ideas=max_ideas)
    try:
        result = await provider.generate_json(
            prompt, system=system, schema=_schema(min_ideas, max_ideas)
        )
    except Exception as exc:
        logger.warning("Product ideation failed for cluster %r: %s", cluster.label, exc)
        raise LLMCallError("product_ideation", exc) from exc

    raw_ideas = result.get("ideas") if isinstance(result, dict) else None
    if not isinstance(raw_ideas, list):
        return []

    out: list[ProposedIdea] = []
    for item in raw_ideas[:max_ideas]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:255]
        if not title:
            continue
        type_raw = str(item.get("type") or "").strip().lower()
        complexity_raw = str(item.get("complexity") or "").strip().lower()
        try:
            idea_type = ProductIdeaType(type_raw)
            complexity = ProductIdeaComplexity(complexity_raw)
        except ValueError:
            logger.info("Idea %r has unknown type/complexity (%r/%r); dropped",
                        title, type_raw, complexity_raw)
            continue
        terms_raw = item.get("evidence_terms")
        terms = (
            [str(t).strip() for t in terms_raw if str(t).strip()]
            if isinstance(terms_raw, list)
            else []
        )
        missing = check_grounding(terms, shown) if terms else terms
        if not terms or missing:
            logger.info(
                "Idea %r not grounded (terms=%s missing=%s); dropped", title, terms, missing
            )
            continue
        fit_rationale = str(item.get("fit_rationale") or "").strip()
        if not fit_rationale:
            continue
        out.append(
            ProposedIdea(
                title=title,
                description=str(item.get("description") or "").strip()[:2000],
                idea_type=idea_type,
                complexity=complexity,
                price_min=_as_price(item.get("price_min")),
                price_max=_as_price(item.get("price_max")),
                fit_rationale=fit_rationale[:1000],
                evidence_terms=terms[:10],
            )
        )
    return out


def _as_price(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class IdeationConfig:
    min_ideas: int
    max_ideas: int
    max_evidence_texts: int
    max_text_chars: int
    prompt_version: str

    @classmethod
    def from_rules(cls, rules_path: str) -> IdeationConfig:
        rules = load_rules(rules_path)
        generation = rules.get("generation", {})
        return cls(
            min_ideas=int(generation.get("min_ideas", 3)),
            max_ideas=int(generation.get("max_ideas", 5)),
            max_evidence_texts=int(generation.get("max_evidence_texts", 40)),
            max_text_chars=int(generation.get("max_text_chars", 300)),
            prompt_version=str(rules.get("prompt_version", "product_ideation_v1")),
        )


class ProductIdeationGenerator:
    def __init__(
        self,
        provider: LLMProvider,
        session: AsyncSession,
        rules_path: str,
        config: IdeationConfig | None = None,
    ) -> None:
        self._provider = provider
        self._session = session
        self._config = config or IdeationConfig.from_rules(rules_path)

    async def generate(self, creator_id: str) -> ResearchRun:
        creator = await self._session.get(Creator, creator_id)
        if creator is None:
            raise ValueError(f"Creator not found: {creator_id}")

        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=creator_id,
            config={
                "min_ideas": self._config.min_ideas,
                "max_ideas": self._config.max_ideas,
            },
            prompt_versions={"ideation": self._config.prompt_version},
            model_versions={"primary": self._provider.model_name},
            scope=RunScope.CREATOR,
            run_type=RunType.CREATOR_RESEARCH,
        )
        stats = PipelineStats()

        try:
            clusters = await active_clusters_for_creator(self._session, creator_id)
            stats.extra["clusters"] = len(clusters)
            ideas_created = 0

            for cluster in clusters:
                members = await self._load_evidence(cluster.id)
                if not members:
                    stats.skip()
                    continue
                try:
                    proposed = await propose_ideas(
                        self._provider,
                        creator,
                        cluster,
                        [ev.raw_text for _, ev in members],
                        min_ideas=self._config.min_ideas,
                        max_ideas=self._config.max_ideas,
                        max_text_chars=self._config.max_text_chars,
                    )
                except LLMCallError as exc:
                    stats.fail(exc)
                    continue

                for idea in proposed:
                    supporting = _evidence_supporting(idea, members)
                    if not supporting:
                        stats.skip()
                        continue
                    row = ProductIdea(
                        creator_id=creator_id,
                        problem_cluster_id=cluster.id,
                        research_run_id=run.id,
                        title=idea.title,
                        description=idea.description,
                        idea_type=idea.idea_type,
                        complexity=idea.complexity,
                        price_min=idea.price_min,
                        price_max=idea.price_max,
                        fit_rationale=idea.fit_rationale,
                        evidence_terms=idea.evidence_terms,
                        evidence_count=len(supporting),
                        generation_prompt_version=self._config.prompt_version,
                        generation_model_version=self._provider.model_name,
                    )
                    self._session.add(row)
                    await self._session.flush()
                    for ev in supporting:
                        self._session.add(
                            ProductIdeaEvidence(product_idea_id=row.id, evidence_id=ev.id)
                        )
                    await self._session.flush()
                    ideas_created += 1
                    stats.ok()

            stats.extra["ideas_created"] = ideas_created

            superseded = await supersede(
                self._session,
                ProductIdea,
                ProductIdea.creator_id == creator_id,
                ProductIdea.research_run_id != run.id,
            )
            stats.extra["superseded"] = superseded

            used = getattr(self._provider, "models_used", None)
            run.model_versions = {
                **(run.model_versions or {}),
                "used": sorted(used()) if used else [self._provider.model_name],
            }
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Product ideation failed for creator %s", creator_id)
            raise

    async def _load_evidence(self, cluster_id: str) -> list[tuple[ProblemObservation, Evidence]]:
        result = await self._session.execute(
            select(ProblemObservation, Evidence)
            .join(
                ProblemClusterMember,
                ProblemClusterMember.observation_id == ProblemObservation.id,
            )
            .join(Evidence, Evidence.id == ProblemObservation.evidence_id)
            .where(ProblemClusterMember.cluster_id == cluster_id)
        )
        return [(obs, ev) for obs, ev in result.all()]


def _evidence_supporting(
    idea: ProposedIdea, pool: list[tuple[ProblemObservation, Evidence]]
) -> list[Evidence]:
    """Full-text (untruncated) superset match: every DISTINCT evidence row
    whose raw_text contains at least one of the idea's grounded
    evidence_terms. Deduped by evidence id -- two observations in the same
    cluster can share one underlying Evidence row, and ProductIdeaEvidence
    has a unique (product_idea_id, evidence_id) index."""
    terms = [_normalize(t) for t in idea.evidence_terms]
    seen: set[str] = set()
    out = []
    for _, ev in pool:
        if ev.id in seen:
            continue
        text = _normalize(ev.raw_text)
        if any(term in text for term in terms):
            seen.add(ev.id)
            out.append(ev)
    return out
