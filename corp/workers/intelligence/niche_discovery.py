"""Recursive niche discovery (CORP1 Stage 3/4/5, T3; extended by T8).

Supersedes the single-level "discover -> drill-down" description from the
CORP1 spec's Phase 1.3/1.4 with the frozen recursive behavior: a broad
topic (depth 0) fans out across every capability provider in parallel, an
LLM synthesizes named niches from the returned evidence -- grounded only,
never invented -- and each niche that is not yet specific enough for a
concrete digital product recurses into itself as the next query, one level
deeper, until it is specific enough or the depth-3 hard cap is reached.

CORP1 Stage 5, T8 (four-state decision gate) added ``research_more()``: a
second public entrypoint, distinct from ``discover()``, that resumes
drilling one already-canonical niche one level deeper instead of starting
a fresh depth-0 scan from a broad topic. See its docstring.

Two design decisions made here, not fully settled by the frozen spec:

1. **Which adapters fan out.** Only ``AdapterFamily.NICHE`` adapters --
   the ones T2 wired whose ``collect()`` takes a free-text keyword.
   YouTube (API) and Reddit also implement ``ProblemProvider`` (T2), but
   their ``collect()`` expects a channel handle / subreddit name, not an
   arbitrary topic string -- calling ``fetch_problems("home espresso")``
   on ``YouTubeAdapter`` would try to resolve "home espresso" as a channel
   and fail. Excluding creator-bound adapters from topic-keyword fan-out
   is the same guard :class:`corp.workers.acquisition.multi_discovery.
   MultiSourceDiscovery` already uses, applied here for the same reason.

2. **The T2-flagged duplicate-evidence risk** (ADR-0032): Reddit, AppStore
   and Marketplace each implement two capabilities that delegate to the
   same ``collect()``. Resolved here as *intentional* two-lens evidence:
   the same raw item is persisted once per distinct ``evidence_type`` it
   legitimately represents (a marketplace listing IS both a transaction
   signal and a solution signal), but never duplicated *within* one type.
   See ``_collect_evidence``.

The exclusion rule from Stage 3 ("Niche Exclusion Rules") is checked
deterministically against ``rules/niche_discovery_prompt.yaml`` -- never by
LLM judgment -- both before spending evidence-collection budget on a
keyword and again on every synthesized candidate's name+description, since
evidence can reveal a category the raw keyword did not.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.campaign import Campaign
from corp.core.models.evidence import Evidence, EvidenceOrigin, EvidenceType
from corp.core.models.niche import Niche, NicheAlias
from corp.core.models.niche_candidate import (
    NicheCandidate,
    NicheCandidateEvidence,
    NicheCandidateStatus,
)
from corp.core.models.workflow import ResearchRun, RunScope, RunType
from corp.core.scoring.niche_qualification import load_rules
from corp.workers.adapters.base import AdapterFamily, NormalizedContent, SourceAdapter
from corp.workers.adapters.registry import build_adapter
from corp.workers.intelligence.errors import LLMCallError
from corp.workers.intelligence.niche_naming import check_grounding
from corp.workers.intelligence.runs import PipelineStats, fail_run, finish_run, start_run
from corp.workers.providers.capabilities import (
    CAPABILITY_INTERFACES,
    EvidenceProvider,
)
from corp.workers.providers.registry import LLMProvider

logger = logging.getLogger(__name__)

PIPELINE = "niche_discovery_recursive"

# The T2-wired adapters whose family is NICHE (free-text keyword collection).
# YouTube and Reddit also implement capability interfaces (T2) but are
# creator-bound (channel handle / subreddit) -- excluded here, see module
# docstring point 1.
NICHE_FAN_OUT_PLATFORMS: tuple[str, ...] = (
    "stackexchange",
    "searchdemand",
    "amazon_reviews",
    "marketplace",
    "hackernews",
    "wikipedia",
    "googletrends",
    "appstore",
)

SYNTHESIS_SYSTEM_PROMPT = (
    "You identify specific niches from public market evidence (search trends, "
    "forum questions, product listings, reviews). A niche is the smallest "
    "coherent audience/problem domain that still has real activity -- e.g. "
    "'Home Espresso', 'Sim Racing', 'Reef Aquariums' -- not a broad industry "
    "like 'Cars' or 'Fitness'.\n\n"
    "Rules:\n"
    "- Identify ONLY niches the evidence actually supports. Do not invent "
    "audiences, problems or products that are not in the evidence.\n"
    "- Each name is 2 to 5 words, Title Case, no punctuation.\n"
    "- For each niche, cite 2 to 6 evidence_terms: exact words or short "
    "phrases copied from the evidence that justify it. They must appear "
    "verbatim in the evidence shown.\n"
    "- specific_enough is true only if you could name ONE concrete digital "
    "product (a template, calculator, guide, course, tracker, database) for "
    "this niche's audience right now. If the niche is still broad enough "
    "that many unrelated products could fit, set it false -- this niche "
    "needs another round of drilling.\n"
    "- Return up to {max_niches} niches, most specific/best-evidenced first.\n\n"
    'Return only JSON: {{"niches": [{{"name": str, "description": str (one '
    'sentence), "specific_enough": bool, "evidence_terms": [str]}}]}}'
)

SYNTHESIS_TEMPLATE = (
    "Topic: {topic}\n"
    "Evidence ({count} of {total} items):\n{texts}\n\n"
    "Identify up to {max_niches} specific niches within this topic."
)

SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["niches"],
    "properties": {
        "niches": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "description", "specific_enough", "evidence_terms"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "specific_enough": {"type": "boolean"},
                    "evidence_terms": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


@dataclass(frozen=True, slots=True)
class SynthesizedNiche:
    name: str
    description: str
    specific_enough: bool
    evidence_terms: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def matched_exclusion(text: str, exclusions: dict[str, list[str]]) -> str | None:
    """Deterministic substring match against Stage 3's exclusion categories.
    Returns the matched category name, or None. Never an LLM judgment call."""
    lowered = _normalize(text)
    for category, terms in exclusions.items():
        for term in terms:
            if _normalize(term) in lowered:
                return category
    return None


async def synthesize_niches(
    provider: LLMProvider,
    topic: str,
    texts: list[str],
    *,
    max_niches: int,
    max_text_chars: int,
) -> list[SynthesizedNiche]:
    """Ask the provider to identify niches from ``texts``; keep only the
    ones whose cited evidence_terms are actually grounded in what was
    shown. Ungrounded niches are dropped, not fabricated a fallback name --
    "niches come from evidence, not imagination" (CORP1 Stage 3)."""
    shown = [t.strip()[:max_text_chars] for t in texts if t and t.strip()][:40]
    if not shown:
        return []
    prompt = SYNTHESIS_TEMPLATE.format(
        topic=topic,
        count=len(shown),
        total=len(texts),
        texts="\n".join(f"- {t}" for t in shown),
        max_niches=max_niches,
    )
    system = SYNTHESIS_SYSTEM_PROMPT.format(max_niches=max_niches)
    try:
        result = await provider.generate_json(prompt, system=system, schema=SYNTHESIS_SCHEMA)
    except Exception as exc:
        logger.warning("Niche synthesis failed for topic %r: %s", topic, exc)
        raise LLMCallError("niche_discovery_synthesis", exc) from exc

    raw_niches = result.get("niches") if isinstance(result, dict) else None
    if not isinstance(raw_niches, list):
        return []

    out: list[SynthesizedNiche] = []
    for item in raw_niches[:max_niches]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:255]
        if not name:
            continue
        terms_raw = item.get("evidence_terms")
        terms = (
            [str(t).strip() for t in terms_raw if str(t).strip()]
            if isinstance(terms_raw, list)
            else []
        )
        missing = check_grounding(terms, shown) if terms else terms  # no terms = ungrounded
        if not terms or missing:
            logger.info(
                "Synthesized niche %r not grounded (terms=%s missing=%s); dropped",
                name,
                terms,
                missing,
            )
            continue
        out.append(
            SynthesizedNiche(
                name=name,
                description=str(item.get("description") or "").strip()[:2000],
                specific_enough=bool(item.get("specific_enough", False)),
                evidence_terms=terms[:10],
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class DiscoveryConfig:
    max_depth: int
    breadth_depth_0: int
    breadth_per_branch: int
    recheck_days: int
    max_evidence_texts: int
    max_text_chars: int
    exclusions: dict[str, list[str]]

    @classmethod
    def from_rules(cls, rules_path: str) -> DiscoveryConfig:
        rules = load_rules(rules_path)
        recursion = rules.get("recursion", {})
        synthesis = rules.get("synthesis", {})
        return cls(
            max_depth=int(recursion.get("max_depth", 3)),
            breadth_depth_0=int(recursion.get("breadth_depth_0", 15)),
            breadth_per_branch=int(recursion.get("breadth_per_branch", 10)),
            recheck_days=int(recursion.get("recheck_days", 90)),
            max_evidence_texts=int(synthesis.get("max_evidence_texts", 40)),
            max_text_chars=int(synthesis.get("max_text_chars", 300)),
            exclusions=dict(rules.get("exclusions", {})),
        )


class RecursiveNicheDiscovery:
    """Broad topic -> capability fan-out -> LLM synthesis -> recurse.

    ``provider`` is required (not optional): unlike keyword-clustering
    niche generation, this pipeline's entire premise (Option B) is
    LLM synthesis across multi-source evidence -- there is no
    deterministic fallback for "identify several niches from a raw
    evidence pool" the way a single cluster has a keyword label.
    """

    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        rules_path: str,
        config: DiscoveryConfig | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._config = config or DiscoveryConfig.from_rules(rules_path)

    async def discover(self, campaign_id: str, topic: str) -> ResearchRun:
        if await self._session.get(Campaign, campaign_id) is None:
            raise ValueError(f"Campaign not found: {campaign_id}")

        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "topic": topic,
                "max_depth": self._config.max_depth,
                "breadth_depth_0": self._config.breadth_depth_0,
                "breadth_per_branch": self._config.breadth_per_branch,
            },
            prompt_versions={"synthesis": "niche_discovery_v1"},
            model_versions={"primary": self._provider.model_name},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_DISCOVERY,
            campaign_id=campaign_id,
        )
        stats = PipelineStats()
        try:
            await self._drill(
                run, campaign_id, topic, parent_candidate_id=None, depth=0, stats=stats
            )
            used = getattr(self._provider, "models_used", None)
            run.model_versions = {
                **(run.model_versions or {}),
                "used": sorted(used()) if used else [self._provider.model_name],
            }
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Recursive niche discovery failed for campaign %s", campaign_id)
            raise

    async def research_more(self, niche_id: str, campaign_id: str) -> ResearchRun:
        """CORP1 Stage 5, T8's "Research More" decision outcome: resume
        drilling one SPECIFIC canonical niche one level deeper and re-query
        evidence sources for it, per the Stage 3 spec's own wording ("CORP1
        automatically drills one level deeper into the niche and re-queries
        all evidence sources for that specific niche").

        Unlike :meth:`discover`, which always starts a fresh recursion at
        depth 0 for a broad topic, this resumes from wherever the niche's
        own drill history left off: it anchors the new candidates as
        children of the most recently promoted :class:`NicheCandidate` for
        this niche (if one exists) at ``that candidate's depth + 1``, or
        falls back to ``niche.depth + 1`` with no parent anchor if the
        niche has no traceable candidate lineage (e.g. seeded manually).

        Also bypasses the registry-freshness skip that :meth:`_drill` would
        otherwise apply — a human explicitly asking to research this niche
        again right now must not silently no-op just because it was
        recently scanned. Only this top-level call bypasses the check;
        any further auto-recursion triggered from here still respects it
        normally, same as every other drill.
        """
        niche = await self._session.get(Niche, niche_id)
        if niche is None:
            raise ValueError(f"Niche not found: {niche_id}")
        if await self._session.get(Campaign, campaign_id) is None:
            raise ValueError(f"Campaign not found: {campaign_id}")

        # NicheCandidate.niche_id is set by BOTH the PROMOTED branch of
        # canonicalization (this candidate created the niche) and the
        # MERGED branch (this candidate was folded into an existing
        # niche from some other, possibly unrelated, campaign/drill run)
        # -- see niche_canonicalization.canonicalize(). Only a PROMOTED
        # candidate's depth/lineage is this niche's own drill history; a
        # MERGED one is a different candidate's history that happens to
        # point here, and anchoring on it would silently research_more()
        # against the wrong tree (Stage 8 review finding).
        parent_candidate = (
            await self._session.execute(
                select(NicheCandidate)
                .where(
                    NicheCandidate.niche_id == niche_id,
                    NicheCandidate.status == NicheCandidateStatus.PROMOTED,
                )
                .order_by(NicheCandidate.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        parent_candidate_id = parent_candidate.id if parent_candidate else None
        depth = (parent_candidate.depth if parent_candidate else niche.depth) + 1

        run = await start_run(
            self._session,
            pipeline=PIPELINE,
            creator_id=None,
            config={
                "topic": niche.canonical_name,
                "research_more_of_niche_id": niche.id,
                "max_depth": self._config.max_depth,
                "breadth_per_branch": self._config.breadth_per_branch,
            },
            prompt_versions={"synthesis": "niche_discovery_v1"},
            model_versions={"primary": self._provider.model_name},
            scope=RunScope.NICHE,
            run_type=RunType.NICHE_DISCOVERY,
            campaign_id=campaign_id,
            niche_id=niche.id,
        )
        stats = PipelineStats()
        try:
            await self._drill(
                run,
                campaign_id,
                niche.canonical_name,
                parent_candidate_id=parent_candidate_id,
                depth=depth,
                stats=stats,
                skip_registry_check=True,
            )
            used = getattr(self._provider, "models_used", None)
            run.model_versions = {
                **(run.model_versions or {}),
                "used": sorted(used()) if used else [self._provider.model_name],
            }
            return await finish_run(self._session, run, stats)
        except Exception as exc:
            if run.status == "running":
                await fail_run(self._session, run, exc)
            logger.exception("Research More failed for niche %s", niche_id)
            raise

    # ── The recursive step ──────────────────────────────────────────────

    async def _drill(
        self,
        run: ResearchRun,
        campaign_id: str,
        keyword: str,
        parent_candidate_id: str | None,
        depth: int,
        stats: PipelineStats,
        *,
        skip_registry_check: bool = False,
    ) -> None:
        if not skip_registry_check and await self._is_registry_fresh(keyword):
            logger.info("Skipping %r at depth %d: registry entry still fresh", keyword, depth)
            stats.skip()
            return

        excluded = matched_exclusion(keyword, self._config.exclusions)
        if excluded is not None:
            logger.info("Skipping %r at depth %d: matched exclusion %r", keyword, depth, excluded)
            stats.skip()
            return

        evidence_rows = await self._collect_evidence(run, keyword, stats)
        if not evidence_rows:
            stats.skip()
            return

        breadth = self._config.breadth_depth_0 if depth == 0 else self._config.breadth_per_branch
        try:
            niches = await synthesize_niches(
                self._provider,
                keyword,
                [e.raw_text for e in evidence_rows],
                max_niches=breadth,
                max_text_chars=self._config.max_text_chars,
            )
        except LLMCallError as exc:
            stats.fail(exc)
            return

        for niche in niches:
            await self._handle_niche(
                run, campaign_id, niche, evidence_rows, parent_candidate_id, depth, stats
            )

    async def _handle_niche(
        self,
        run: ResearchRun,
        campaign_id: str,
        niche: SynthesizedNiche,
        evidence_rows: list[Evidence],
        parent_candidate_id: str | None,
        depth: int,
        stats: PipelineStats,
    ) -> None:
        members = _evidence_supporting(niche, evidence_rows)
        if not members:
            # Grounded against the (possibly truncated) shown texts, but no
            # full-length row contains the term -- extremely unlikely, but
            # the evidence_count >= 1 constraint means we cannot persist a
            # candidate with nothing to point at.
            stats.skip()
            return

        excluded_category = matched_exclusion(
            f"{niche.name} {niche.description}", self._config.exclusions
        )
        candidate = NicheCandidate(
            campaign_id=campaign_id,
            research_run_id=run.id,
            label=niche.name,
            description=niche.description,
            naming_method="llm",
            naming_terms=niche.evidence_terms,
            naming_confidence=None,
            evidence_count=len(members),
            source_count=len({m.source_platform for m in members}),
            author_count=len({m.author_handle for m in members if m.author_handle}),
            earliest_collected_at=min((m.collected_at for m in members), default=None),
            latest_collected_at=max((m.collected_at for m in members), default=None),
            representative_text=niche.description,
            naming_prompt_version="niche_discovery_v1",
            naming_model_version=self._provider.model_name,
            parent_candidate_id=parent_candidate_id,
            depth=depth,
        )
        if excluded_category is not None:
            candidate.status = NicheCandidateStatus.REJECTED
            candidate.extra = {"excluded_category": excluded_category}

        self._session.add(candidate)
        await self._session.flush()
        for m in members:
            self._session.add(NicheCandidateEvidence(candidate_id=candidate.id, evidence_id=m.id))
        await self._session.flush()
        stats.ok()

        if excluded_category is not None:
            # Rejected: never recurses, never reaches canonicalization or
            # creator discovery (NicheCandidateStatus.REJECTED is excluded
            # from every downstream STAGED-only query).
            return

        if not niche.specific_enough and depth < self._config.max_depth:
            candidate.status = NicheCandidateStatus.DRILLING
            await self._session.flush()
            await self._drill(run, campaign_id, niche.name, candidate.id, depth + 1, stats)
            if candidate.status == NicheCandidateStatus.DRILLING:
                candidate.status = NicheCandidateStatus.STAGED
                await self._session.flush()

    # ── Registry check (CORP1 Stage 3 research registry) ────────────────

    async def _is_registry_fresh(self, keyword: str) -> bool:
        """True when ``keyword`` already matches a canonical Niche (or
        alias) whose next_recheck_at has not passed yet -- skip re-drilling
        it. A niche with no next_recheck_at set (never scanned by a stage
        that populates it) is always treated as due.

        Exact case-insensitive match via func.lower(...) == keyword.lower(),
        not ilike(keyword) -- ilike treats unescaped '%'/'_' in the keyword
        as SQL wildcards, which could turn an exact-match lookup into an
        unintended pattern match on a raw topic string (Stage 8 review
        finding). This mirrors the exact mechanism the functional
        case-insensitive uniqueness index on Niche.canonical_name already
        uses (docs/DECISIONS/0002)."""
        now = datetime.now(UTC)
        lowered = keyword.lower()
        result = await self._session.execute(
            select(Niche.next_recheck_at)
            .outerjoin(NicheAlias, NicheAlias.niche_id == Niche.id)
            .where(
                (func.lower(Niche.canonical_name) == lowered)
                | (func.lower(NicheAlias.alias) == lowered),
            )
            .limit(1)
        )
        next_recheck_at = result.scalar_one_or_none()
        return next_recheck_at is not None and next_recheck_at > now

    # ── Evidence collection: capability fan-out ─────────────────────────

    async def _collect_evidence(
        self, run: ResearchRun, keyword: str, stats: PipelineStats
    ) -> list[Evidence]:
        """Fan ``keyword`` out across every NICHE-family adapter's
        capability methods in parallel. The same raw item reached through
        two different capabilities on one adapter (Reddit/AppStore/
        Marketplace, T2) is persisted once per distinct evidence_type --
        never duplicated within one type. See module docstring point 2."""
        adapters: list[SourceAdapter] = []
        for platform in NICHE_FAN_OUT_PLATFORMS:
            try:
                adapters.append(build_adapter(platform))
            except Exception as exc:
                logger.warning("Could not build adapter %s: %s", platform, exc)

        tasks: list[Any] = []
        task_meta: list[tuple[SourceAdapter, type[EvidenceProvider]]] = []
        for adapter in adapters:
            if adapter.family != AdapterFamily.NICHE:
                continue
            for capability_cls in CAPABILITY_INTERFACES:
                if not isinstance(adapter, capability_cls):
                    continue
                method = _fetch_method(adapter, capability_cls)
                if method is None:
                    continue
                tasks.append(method(keyword))
                task_meta.append((adapter, capability_cls))

        results = await _gather_safely(tasks)

        seen: set[tuple[EvidenceType, str, str]] = set()
        new_rows: list[Evidence] = []
        # Every row relevant to THIS keyword's synthesis, whether inserted
        # just now or already in the DB from an earlier drill level whose
        # query happened to surface the same item. A prior call's dedup
        # must never starve a later call of evidence it needs to see --
        # only the DB write is deduplicated, not what synthesis is shown.
        evidence_pool: list[Evidence] = []
        for (adapter, capability_cls), outcome in zip(task_meta, results, strict=True):
            if isinstance(outcome, BaseException):
                logger.warning(
                    "%s.%s failed for %r: %s",
                    type(adapter).__name__,
                    capability_cls.__name__,
                    keyword,
                    outcome,
                )
                stats.fail(outcome)
                continue
            evidence_type = capability_cls.evidence_type
            for item in outcome:
                key = (evidence_type, item.source_platform, item.external_id)
                if key in seen:
                    continue
                seen.add(key)
                existing = await self._find_existing(evidence_type, item)
                if existing is not None:
                    evidence_pool.append(existing)
                    continue
                ev = _to_evidence(item, run.id, evidence_type)
                self._session.add(ev)
                new_rows.append(ev)
                evidence_pool.append(ev)
            stats.ok()

        for adapter in adapters:
            if hasattr(adapter, "close"):
                try:
                    await adapter.close()
                except Exception:
                    pass

        if new_rows:
            await self._session.flush()
        return evidence_pool

    async def _find_existing(
        self, evidence_type: EvidenceType, item: NormalizedContent
    ) -> Evidence | None:
        result = await self._session.execute(
            select(Evidence)
            .where(
                Evidence.source_platform == item.source_platform,
                Evidence.source_id == item.external_id,
                Evidence.evidence_type == evidence_type,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


def _fetch_method(adapter: SourceAdapter, capability_cls: type[EvidenceProvider]) -> Any:
    """The one abstract method ``capability_cls`` declares, bound to
    ``adapter``. Each capability interface (T1) has exactly one -- this
    just avoids hardcoding fetch_problems/fetch_trend/... as a lookup
    table here, which would need updating every time a capability is
    added."""
    for name in vars(capability_cls):
        if name.startswith("fetch_") and callable(getattr(capability_cls, name, None)):
            return getattr(adapter, name)
    return None


async def _gather_safely(tasks: list[Any]) -> list[Any]:
    if not tasks:
        return []
    return await asyncio.gather(*tasks, return_exceptions=True)


def _evidence_supporting(niche: SynthesizedNiche, pool: list[Evidence]) -> list[Evidence]:
    """Full-text (untruncated) superset match: every row whose raw_text
    contains at least one of the niche's grounded evidence_terms."""
    terms = [_normalize(t) for t in niche.evidence_terms]
    out = []
    for row in pool:
        text = _normalize(row.raw_text)
        if any(term in text for term in terms):
            out.append(row)
    return out


def _to_evidence(item: NormalizedContent, run_id: str, evidence_type: EvidenceType) -> Evidence:
    return Evidence(
        source_type=item.content_type,
        source_id=item.external_id,
        source_platform=item.source_platform,
        raw_text=item.text,
        author_handle=item.author,
        source_url=item.url,
        access_method=item.access_method,
        compliance_status=item.compliance_status,
        research_run_id=run_id,
        evidence_type=evidence_type,
        origin=EvidenceOrigin.OBSERVATION,
    )
