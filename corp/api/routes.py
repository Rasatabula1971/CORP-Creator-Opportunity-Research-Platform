"""API routes — CORP Step 8 endpoints."""

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from corp.config import settings
from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.competitive import Competitor
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.evidence import Evidence
from corp.core.models.intelligence import ProblemObservation
from corp.core.models.intent import CommercialSignal
from corp.core.models.niche import Niche
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.core.models.workflow import ResearchRun, RunStatus, RunType
from corp.core.schemas.campaign import CampaignResponse
from corp.core.schemas.campaign_niche import CampaignNicheDetailResponse
from corp.core.schemas.competitive import CompetitorResponse
from corp.core.schemas.creator import (
    CreatorDetailResponse,
    CreatorResponse,
    PlatformAccountResponse,
)
from corp.core.schemas.dossier import (
    DataCoverageResponse,
    DossierCreatorResponse,
    DossierOpportunityResponse,
    DossierPlatformAccountResponse,
    DossierResponse,
    DossierScoreResponse,
    DossierSignalResponse,
    LastRescanResponse,
    PersistedDossierResponse,
    WatchingDossierResponse,
)
from corp.core.schemas.evidence import EvidenceResponse
from corp.core.schemas.intelligence import ProblemClusterResponse, ProblemObservationResponse
from corp.core.schemas.intent import CommercialSignalResponse
from corp.core.schemas.scoring import OpportunityScoreResponse
from corp.core.schemas.workflow import DecisionCreate, DecisionResponse, ResearchRunResponse
from corp.core.state.gates import record_gate_a_decision
from corp.database import get_session
from corp.workers.dossier.generator import DossierGenerator

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Campaigns ────────────────────────────────────────────────────────


@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CampaignResponse]:
    total = (await session.execute(select(func.count()).select_from(Campaign))).scalar()
    response.headers["X-Total-Count"] = str(total or 0)
    result = await session.execute(
        select(Campaign).order_by(Campaign.created_at.desc()).offset(offset).limit(limit)
    )
    return [CampaignResponse.model_validate(c) for c in result.scalars().all()]


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    session: AsyncSession = Depends(get_session),
) -> CampaignResponse:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@router.get(
    "/campaigns/{campaign_id}/niches",
    response_model=list[CampaignNicheDetailResponse],
)
async def list_campaign_niches(
    campaign_id: str,
    response: Response,
    status: CampaignNicheStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CampaignNicheDetailResponse]:
    if await session.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    query = (
        select(CampaignNiche)
        .options(selectinload(CampaignNiche.niche))
        .where(CampaignNiche.campaign_id == campaign_id)
    )
    if status is not None:
        query = query.where(CampaignNiche.status == status)
    # Recursive discovery can yield hundreds of niches per campaign; the
    # client needs the total to know a page is a page (same as /creators).
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar()
    response.headers["X-Total-Count"] = str(total or 0)
    query = query.order_by(CampaignNiche.qualification_score.desc().nulls_last())
    result = await session.execute(query.offset(offset).limit(limit))
    return [CampaignNicheDetailResponse.model_validate(cn) for cn in result.scalars().all()]


@router.get("/campaigns/{campaign_id}/creators", response_model=list[CreatorResponse])
async def list_campaign_creators(
    campaign_id: str,
    response: Response,
    niche_status: CampaignNicheStatus = CampaignNicheStatus.SELECTED,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CreatorResponse]:
    if await session.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    query = (
        select(Creator)
        .join(CreatorNiche, CreatorNiche.creator_id == Creator.id)
        .join(CampaignNiche, CampaignNiche.niche_id == CreatorNiche.niche_id)
        .where(
            CampaignNiche.campaign_id == campaign_id,
            CampaignNiche.status == niche_status,
        )
        .distinct()
    )
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar()
    response.headers["X-Total-Count"] = str(total or 0)

    result = await session.execute(
        query.order_by(Creator.created_at.desc()).offset(offset).limit(limit)
    )
    return [CreatorResponse.model_validate(c) for c in result.scalars().all()]


# ── Creators ─────────────────────────────────────────────────────────


@router.get("/creators", response_model=list[CreatorResponse])
async def list_creators(
    response: Response,
    status: CreatorStatus | None = None,
    min_score: float | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CreatorResponse]:
    query = select(Creator)

    if status is not None:
        query = query.where(Creator.status == status)

    if min_score is not None:
        scored_ids = (
            select(CreatorScore.creator_id)
            .where(
                CreatorScore.aggregate_score >= min_score,
                CreatorScore.superseded_at.is_(None),
            )
            .distinct()
        )
        query = query.where(Creator.id.in_(scored_ids))

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar()
    response.headers["X-Total-Count"] = str(total or 0)
    query = query.order_by(Creator.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return [CreatorResponse.model_validate(c) for c in result.scalars().all()]


@router.get("/creators/{creator_id}", response_model=CreatorDetailResponse)
async def get_creator(
    creator_id: str,
    session: AsyncSession = Depends(get_session),
) -> CreatorDetailResponse:
    result = await session.execute(
        select(Creator)
        .options(selectinload(Creator.platform_accounts))
        .where(Creator.id == creator_id)
    )
    creator = result.scalar_one_or_none()
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    accounts = [PlatformAccountResponse.model_validate(a) for a in creator.platform_accounts]
    resp = CreatorDetailResponse.model_validate(creator)
    resp.platform_accounts = accounts
    return resp


# ── Dossier ──────────────────────────────────────────────────────────


@router.get("/creators/{creator_id}/dossier")
async def get_dossier(
    creator_id: str,
    niche_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    # Only a missing creator/niche is a 404; other failures (e.g. a rules/YAML
    # parse error inside the generator) must not be masked as "not found".
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    if niche_id is not None:
        if await session.get(Niche, niche_id) is None:
            raise HTTPException(status_code=404, detail="Niche not found")
        linked = await session.execute(
            select(CreatorNiche.id).where(
                CreatorNiche.creator_id == creator_id, CreatorNiche.niche_id == niche_id
            )
        )
        if linked.first() is None:
            # Scoping to a niche the creator isn't in would render a
            # "Dossier scope" header over creator-only evidence.
            raise HTTPException(status_code=422, detail="Niche is not linked to this creator")
    gen = DossierGenerator(session, rules_path=settings.scoring_rules_path)
    html = await gen.generate(creator_id, niche_id)
    return Response(content=html, media_type="text/html")


@router.get("/creators/{creator_id}/dossier.json", response_model=DossierResponse)
async def get_dossier_json(
    creator_id: str,
    session: AsyncSession = Depends(get_session),
) -> DossierResponse:
    # Same 404-only-on-missing-creator semantics as the HTML endpoint above.
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    gen = DossierGenerator(session, rules_path=settings.scoring_rules_path)
    data = await gen.generate_data(creator_id)

    opportunities = [
        DossierOpportunityResponse(
            cluster=ProblemClusterResponse.model_validate(opp.cluster),
            score=OpportunityScoreResponse.model_validate(opp.score),
            signal=CommercialSignalResponse.model_validate(opp.signal) if opp.signal else None,
            observations=[ProblemObservationResponse.model_validate(o) for o in opp.observations],
            competitors=[CompetitorResponse.model_validate(c) for c in opp.competitors],
        )
        for opp in data.opportunities
    ]
    signals = [
        DossierSignalResponse(
            cluster_label=s.cluster_label,
            signal=CommercialSignalResponse.model_validate(s.signal),
        )
        for s in data.signals
    ]

    return DossierResponse(
        creator=DossierCreatorResponse.model_validate(data.creator),
        platform_accounts=[
            DossierPlatformAccountResponse.model_validate(a) for a in data.platform_accounts
        ],
        creator_score=DossierScoreResponse.model_validate(data.creator_score)
        if data.creator_score
        else None,
        score_band=data.score_band,
        weights=data.weights,
        opportunities=opportunities,
        signals=signals,
        data_coverage=DataCoverageResponse(
            source_count=data.data_coverage.source_count,
            evidence_count=data.data_coverage.evidence_count,
            cluster_count=data.data_coverage.cluster_count,
            observation_count=data.data_coverage.observation_count,
            competitor_count=data.data_coverage.competitor_count,
        ),
        generated_at=data.generated_at,
    )


@router.post(
    "/creators/{creator_id}/dossier/generate",
    response_model=PersistedDossierResponse,
    status_code=201,
)
async def generate_persisted_dossier(
    creator_id: str,
    session: AsyncSession = Depends(get_session),
) -> Dossier:
    """CORP1 Stage 5, T6: build and persist a real Dossier row (not the
    request-scoped view the two endpoints above compute). The niche is
    the creator's most-recently-observed CreatorNiche -- a creator with
    none has nothing to scope a dossier to."""
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    cn_result = await session.execute(
        select(CreatorNiche)
        .where(CreatorNiche.creator_id == creator_id)
        .order_by(CreatorNiche.last_observed_at.desc())
        .limit(1)
    )
    creator_niche = cn_result.scalar_one_or_none()
    if creator_niche is None:
        raise HTTPException(
            status_code=422, detail="Creator has no associated niche to generate a dossier for"
        )

    # R12a: the spec's step 6 -- product ideas are generated for the current
    # clusters before the dossier is persisted. T5 shipped the generator
    # unwired, so until now every real dossier had an empty Product
    # Concepts section. Best-effort: with no LLM provider configured the
    # dossier is still produced (ideas empty), never a 503.
    await _generate_product_ideas_best_effort(session, creator_id)

    gen = DossierGenerator(session, rules_path=settings.scoring_rules_path)
    try:
        dossier = await gen.generate_and_persist(creator_id, creator_niche.niche_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return dossier


async def _generate_product_ideas_best_effort(session: AsyncSession, creator_id: str) -> None:
    from corp.workers.intelligence.product_ideation import ProductIdeationGenerator
    from corp.workers.providers.factory import ProviderConfigError, build_provider

    try:
        provider = build_provider()
    except ProviderConfigError as exc:
        logger.warning("Skipping product ideation for %s: %s", creator_id, exc)
        return
    try:
        run = await ProductIdeationGenerator(
            provider, session, "rules/product_ideation_prompt.yaml"
        ).generate(creator_id)
        if run.status == "failed":
            logger.warning(
                "Product ideation failed for %s: %s", creator_id, run.error_message
            )
    except Exception:  # noqa: BLE001 -- ideas are additive; the dossier must still ship
        logger.exception("Product ideation crashed for %s; generating dossier without ideas",
                         creator_id)
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            try:
                await close()
            except Exception:  # noqa: BLE001
                logger.exception("Provider close() failed after ideation for %s", creator_id)


@router.get(
    "/creators/{creator_id}/dossier/persisted",
    response_model=PersistedDossierResponse,
)
async def get_persisted_dossier(
    creator_id: str,
    session: AsyncSession = Depends(get_session),
) -> Dossier:
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    result = await session.execute(
        select(Dossier)
        .where(Dossier.creator_id == creator_id, Dossier.superseded_at.is_(None))
        .order_by(Dossier.generated_at.desc())
        .limit(1)
    )
    dossier = result.scalar_one_or_none()
    if dossier is None:
        raise HTTPException(status_code=404, detail="No persisted dossier for this creator yet")
    return dossier


# ── Watching dossiers (re-scan schedule visibility) ────────────────


@router.get("/dossiers/watching", response_model=list[WatchingDossierResponse])
async def list_watching_dossiers(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[WatchingDossierResponse]:
    """Return all active (non-superseded) WATCHING dossiers joined with
    their creator name, niche name, and the niche's next_recheck_at.
    Used by the frontend re-scan schedule visibility page."""
    result = await session.execute(
        select(
            Dossier.id,
            Dossier.creator_id,
            Creator.name.label("creator_name"),
            Dossier.niche_id,
            Niche.canonical_name.label("niche_name"),
            Dossier.status,
            Dossier.generated_at,
            Dossier.content,
            Niche.next_recheck_at,
        )
        .join(Creator, Creator.id == Dossier.creator_id)
        .join(Niche, Niche.id == Dossier.niche_id)
        .where(
            Dossier.status == DossierStatus.WATCHING,
            Dossier.superseded_at.is_(None),
        )
        .order_by(Niche.next_recheck_at.asc().nulls_last())
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()
    failed_runs = await _latest_failed_rescans(session, [row.id for row in rows])
    return [
        WatchingDossierResponse(
            id=row.id,
            creator_id=row.creator_id,
            creator_name=row.creator_name,
            niche_id=row.niche_id,
            niche_name=row.niche_name,
            status=row.status.value if hasattr(row.status, "value") else row.status,
            generated_at=row.generated_at,
            next_recheck_at=row.next_recheck_at,
            last_rescan=_last_rescan(row.content or {}, failed_runs.get(row.id)),
        )
        for row in rows
    ]


async def _latest_failed_rescans(
    session: AsyncSession, dossier_ids: list[str]
) -> dict[str, ResearchRun]:
    """R12d: the newest failed ``watch_rescan`` run per targeted dossier
    (either trigger). The run's ``config_snapshot.dossier_id`` names the
    dossier it re-researched (which stays active on failure, ADR-0061).
    ``DISTINCT ON`` keeps this one row per dossier however many retries
    have failed."""
    if not dossier_ids:
        return {}
    target = ResearchRun.config_snapshot["dossier_id"].astext
    runs = (
        await session.execute(
            select(ResearchRun)
            .distinct(target)
            .where(
                ResearchRun.run_type == RunType.WATCH_RESCAN.value,
                ResearchRun.status == RunStatus.FAILED.value,
                target.in_(dossier_ids),
            )
            .order_by(
                target,
                ResearchRun.completed_at.desc().nulls_last(),
                ResearchRun.started_at.desc().nulls_last(),
            )
        )
    ).scalars()
    return {str((run.config_snapshot or {}).get("dossier_id")): run for run in runs}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _trigger(value: object) -> Literal["watch", "research_more"] | None:
    if value == "watch":
        return "watch"
    if value == "research_more":
        return "research_more"
    return None


def _last_rescan(
    content: dict[str, Any], failed: ResearchRun | None
) -> LastRescanResponse | None:
    """Whichever is newer: the dossier's own rescan block (unchanged, or
    resurfaced and since re-parked by the reviewer) or the latest failed
    re-research that targeted it."""
    produced: LastRescanResponse | None = None
    block = content.get("rescan")
    if isinstance(block, dict) and block.get("at"):
        try:
            produced = LastRescanResponse(
                outcome="resurfaced" if block.get("resurfaced") else "unchanged",
                trigger=_trigger(block.get("trigger")),
                at=_as_utc(datetime.fromisoformat(str(block["at"]))),
                reason=block.get("reason"),
                score_delta=block.get("score_delta"),
                new_evidence_count=block.get("new_evidence_count"),
                run_id=block.get("run_id"),
            )
        except (ValueError, TypeError, ValidationError):
            produced = None
    failure: LastRescanResponse | None = None
    failed_at = (failed.completed_at or failed.started_at) if failed is not None else None
    if failed is not None and failed_at is not None:
        failure = LastRescanResponse(
            outcome="failed",
            trigger=_trigger((failed.config_snapshot or {}).get("trigger")),
            at=_as_utc(failed_at),
            error=failed.error_message,
            run_id=failed.id,
        )
    if produced and failure:
        return failure if failure.at >= produced.at else produced
    return produced or failure


# ── Evidence ─────────────────────────────────────────────────────────


@router.get("/creators/{creator_id}/evidence", response_model=list[EvidenceResponse])
async def get_evidence(
    creator_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[EvidenceResponse]:
    creator = await session.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    run_ids = select(ResearchRun.id).where(ResearchRun.creator_id == creator_id)
    result = await session.execute(
        select(Evidence)
        .where(Evidence.research_run_id.in_(run_ids))
        .order_by(Evidence.collected_at.desc())
        .limit(limit)
    )
    return [EvidenceResponse.model_validate(e) for e in result.scalars().all()]


# ── Opportunities ────────────────────────────────────────────────────


@router.get(
    "/creators/{creator_id}/opportunities",
    response_model=list[OpportunityScoreResponse],
)
async def get_opportunities(
    creator_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[OpportunityScoreResponse]:
    creator = await session.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    result = await session.execute(
        select(OpportunityScore)
        .where(
            OpportunityScore.creator_id == creator_id,
            OpportunityScore.superseded_at.is_(None),
        )
        .order_by(OpportunityScore.aggregate_score.desc())
    )
    return [OpportunityScoreResponse.model_validate(o) for o in result.scalars().all()]


# ── Competitors ──────────────────────────────────────────────────────


@router.get(
    "/creators/{creator_id}/competitors",
    response_model=list[CompetitorResponse],
)
async def get_competitors(
    creator_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CompetitorResponse]:
    creator = await session.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    cluster_ids = select(OpportunityScore.problem_cluster_id).where(
        OpportunityScore.creator_id == creator_id,
        OpportunityScore.superseded_at.is_(None),
    )
    result = await session.execute(
        select(Competitor)
        .where(Competitor.problem_cluster_id.in_(cluster_ids))
        .offset(offset)
        .limit(limit)
    )
    return [CompetitorResponse.model_validate(c) for c in result.scalars().all()]


# ── Decisions (Gate A) ───────────────────────────────────────────────


@router.post(
    "/creators/{creator_id}/decisions",
    response_model=DecisionResponse,
    status_code=201,
)
async def create_decision(
    creator_id: str,
    body: DecisionCreate,
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    # The URL alone scopes the decision: DecisionCreate carries no creator_id
    # or gate field, so the body cannot disagree with the endpoint.
    creator = await session.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    try:
        decision = await record_gate_a_decision(
            session=session,
            creator=creator,
            decision=body.decision,
            rationale=body.rationale,
            decided_by=body.decided_by,
            opportunity_score_id=body.opportunity_score_id,
        )
    except ValueError as exc:
        # A decision Gate A doesn't accept (research_more belongs to the
        # dossier gate) or an opportunity_score_id that isn't this
        # creator's: the request is well-formed but wrong, not a server
        # fault. InvalidTransitionError keeps its own 409 handler.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await session.commit()
    return DecisionResponse.model_validate(decision)


# ── Observations ─────────────────────────────────────────────────────


@router.get(
    "/creators/{creator_id}/observations",
    response_model=list[ProblemObservationResponse],
)
async def get_observations(
    creator_id: str,
    category: str | None = None,
    urgency: str | None = None,
    source_side: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ProblemObservationResponse]:
    creator = await session.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    run_ids = select(ResearchRun.id).where(ResearchRun.creator_id == creator_id)
    evidence_ids = select(Evidence.id).where(Evidence.research_run_id.in_(run_ids))

    query = (
        select(ProblemObservation)
        .where(ProblemObservation.evidence_id.in_(evidence_ids))
    )
    if category:
        query = query.where(ProblemObservation.category == category)
    if urgency:
        query = query.where(ProblemObservation.urgency == urgency)
    if source_side:
        query = query.where(ProblemObservation.source_side == source_side)

    query = query.order_by(ProblemObservation.confidence.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return [ProblemObservationResponse.model_validate(o) for o in result.scalars().all()]


# ── Signals ──────────────────────────────────────────────────────────


@router.get(
    "/creators/{creator_id}/signals",
    response_model=list[CommercialSignalResponse],
)
async def get_signals(
    creator_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[CommercialSignalResponse]:
    creator = await session.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator not found")

    cluster_ids_subq = select(OpportunityScore.problem_cluster_id).where(
        OpportunityScore.creator_id == creator_id,
        OpportunityScore.superseded_at.is_(None),
    )
    result = await session.execute(
        select(CommercialSignal)
        .where(
            CommercialSignal.problem_cluster_id.in_(cluster_ids_subq),
            CommercialSignal.superseded_at.is_(None),
        )
        .order_by(CommercialSignal.confidence.desc())
    )
    return [CommercialSignalResponse.model_validate(s) for s in result.scalars().all()]


# ── Research Runs ────────────────────────────────────────────────────


@router.get("/research-runs", response_model=list[ResearchRunResponse])
async def list_research_runs(
    creator_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ResearchRunResponse]:
    query = select(ResearchRun)
    if creator_id:
        query = query.where(ResearchRun.creator_id == creator_id)
    query = query.order_by(ResearchRun.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    return [ResearchRunResponse.model_validate(r) for r in result.scalars().all()]

