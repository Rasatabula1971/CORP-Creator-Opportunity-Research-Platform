"""API routes — CORP Step 8 endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche, CampaignNicheStatus
from corp.core.models.creator import Creator, CreatorStatus
from corp.core.models.creator_niche import CreatorNiche
from corp.core.models.evidence import Evidence
from corp.core.models.scoring import CreatorScore, OpportunityScore
from corp.core.models.workflow import Gate, ResearchRun
from corp.core.schemas.campaign import CampaignResponse
from corp.core.schemas.campaign_niche import CampaignNicheDetailResponse
from corp.core.schemas.creator import (
    CreatorDetailResponse,
    CreatorResponse,
    PlatformAccountResponse,
)
from corp.core.schemas.evidence import EvidenceResponse
from corp.core.schemas.scoring import OpportunityScoreResponse
from corp.core.schemas.workflow import DecisionCreate, DecisionResponse, ResearchRunResponse
from corp.core.state.gates import record_gate_a_decision
from corp.core.state.machine import InvalidTransitionError
from corp.database import get_session
from corp.workers.dossier.generator import DossierGenerator

router = APIRouter()


# ── Campaigns ────────────────────────────────────────────────────────


@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    response: Response,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
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
):
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
    status: CampaignNicheStatus | None = None,
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    query = (
        select(CampaignNiche)
        .options(selectinload(CampaignNiche.niche))
        .where(CampaignNiche.campaign_id == campaign_id)
    )
    if status is not None:
        query = query.where(CampaignNiche.status == status)
    query = query.order_by(CampaignNiche.qualification_score.desc().nulls_last())
    result = await session.execute(query)
    return [CampaignNicheDetailResponse.model_validate(cn) for cn in result.scalars().all()]


@router.get("/campaigns/{campaign_id}/creators", response_model=list[CreatorResponse])
async def list_campaign_creators(
    campaign_id: str,
    niche_status: CampaignNicheStatus = CampaignNicheStatus.SELECTED,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
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
        .order_by(Creator.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(query)
    return [CreatorResponse.model_validate(c) for c in result.scalars().all()]


# ── Creators ─────────────────────────────────────────────────────────


@router.get("/creators", response_model=list[CreatorResponse])
async def list_creators(
    response: Response,
    status: CreatorStatus | None = None,
    min_score: float | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
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
):
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
    session: AsyncSession = Depends(get_session),
):
    gen = DossierGenerator(session)
    try:
        html = await gen.generate(creator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Creator not found")
    return Response(content=html, media_type="text/html")


# ── Evidence ─────────────────────────────────────────────────────────


@router.get("/creators/{creator_id}/evidence", response_model=list[EvidenceResponse])
async def get_evidence(
    creator_id: str,
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session),
):
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
):
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
):
    # The URL scopes the decision to this creator and this endpoint only records
    # Gate A. Reject a body that says otherwise instead of silently overriding it,
    # so a caller never gets a 201 describing a decision different from what it sent.
    if body.creator_id != creator_id:
        raise HTTPException(
            status_code=400, detail="Body creator_id does not match the URL"
        )
    if body.gate != Gate.GATE_A:
        raise HTTPException(
            status_code=400, detail="This endpoint only records Gate A decisions"
        )

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
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    await session.commit()
    return DecisionResponse.model_validate(decision)


# ── Research Runs ────────────────────────────────────────────────────


@router.get("/research-runs", response_model=list[ResearchRunResponse])
async def list_research_runs(
    creator_id: str | None = None,
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session),
):
    query = select(ResearchRun)
    if creator_id:
        query = query.where(ResearchRun.creator_id == creator_id)
    query = query.order_by(ResearchRun.created_at.desc()).limit(limit)
    result = await session.execute(query)
    return [ResearchRunResponse.model_validate(r) for r in result.scalars().all()]
