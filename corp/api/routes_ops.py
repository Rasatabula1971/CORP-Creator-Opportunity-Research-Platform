"""Write endpoints, background jobs, and the reads the review console needs."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from corp.api.jobs import (
    CAMPAIGN_PIPELINES,
    PIPELINES,
    JobResponse,
    registry,
    run_campaign_pipeline,
    run_pipeline,
    run_research,
)
from corp.core.models.campaign import Campaign
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal
from corp.core.models.scoring import OpportunityScore
from corp.core.models.workflow import HumanDecision, ResearchRun
from corp.core.schemas.campaign import CampaignCreate, CampaignResponse
from corp.core.schemas.creator import (
    CreatorCreate,
    CreatorDetailResponse,
    PlatformAccountCreate,
    PlatformAccountResponse,
)
from corp.core.schemas.intelligence import ProblemClusterResponse, ProblemObservationResponse
from corp.core.schemas.scoring import OpportunityScoreResponse, ScoreResponse
from corp.core.schemas.workflow import DecisionResponse, ResearchRunResponse
from corp.database import get_session
from corp.workers.dossier.generator import DossierGenerator
from corp.workers.intelligence.runs import active_clusters_for_creator
from corp.workers.providers.factory import ProviderConfigError, build_provider
from corp.workers.providers.fair import FairProvider

router = APIRouter()


# ── Request / response models local to the API ──────────────────────


class CreatorCreateRequest(CreatorCreate):
    accounts: list[PlatformAccountCreate] = Field(default_factory=list)


class ResearchRequest(BaseModel):
    skip_collect: bool = False


class PipelineRunRequest(BaseModel):
    pipeline: str = Field(
        description="research | collect | intelligence | cluster | intent | scoring"
    )
    platform: str | None = None
    identifier: str | None = None
    skip_collect: bool = False


class CampaignPipelineRequest(BaseModel):
    source: str | None = None
    query: str | None = None


class SignalSummary(BaseModel):
    signal_level: str
    confidence: float | None
    rationale: str | None


class ClusterDetail(ProblemClusterResponse):
    creator_id: str | None = None
    signal: SignalSummary | None = None
    score: OpportunityScoreResponse | None = None
    member_count: int = 0


class DossierJson(BaseModel):
    creator: CreatorDetailResponse
    creator_score: ScoreResponse | None
    score_band: str
    weights: dict[str, float]
    opportunities: list[dict[str, Any]]
    data_coverage: dict[str, int]
    generated_at: str


# ── Health (registered on the app without auth; see app.py) ─────────


async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Providers: diagnose the active LLM provider ──────────────────────


@router.get("/providers/health")
async def provider_health() -> dict[str, Any]:
    """Diagnose the active LLM provider.

    Returns the active provider's name and, when it is FAIR, a live probe
    of the embedded router: how many free providers it has keys for, and
    whether a trivial schema-checked solve is accepted. The probe costs
    one real FAIR call — sits behind the same API key as the rest of
    ``routes_ops`` so it is not an unauthenticated way to burn quota.

    Its whole purpose is to diagnose provider state, so an unhealthy
    provider surfaces as data in the response, never as an HTTP 500:
    a missing configuration returns 503 with the reason, and any other
    provider construction failure returns 200 with an ``error`` block.
    """
    try:
        provider = build_provider()
    except ProviderConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        return {
            "provider": None,
            "kind": None,
            "error": {
                "code": "construction_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        }

    payload: dict[str, Any] = {
        "provider": provider.model_name,
        "kind": type(provider).__name__,
    }

    # PooledProvider and FairProvider both expose member_names(); bare
    # providers (GeminiProvider, GroqProvider) do not.
    member_names = getattr(provider, "member_names", None)
    if callable(member_names):
        payload["members"] = member_names()

    if isinstance(provider, FairProvider):
        try:
            result = await provider.ping()
        finally:
            await provider.close()
        payload["fair"] = {
            "ok": result.ok,
            "provider_count": result.provider_count,
            "provider_ids": result.provider_ids,
            "solve_status": result.solve_status,
            "solve_provider": result.solve_provider,
            "solve_model": result.solve_model,
            "detail": result.detail,
        }

    return payload


# ── Creators: write ──────────────────────────────────────────────────


@router.post("/creators", response_model=CreatorDetailResponse, status_code=201)
async def create_creator(
    body: CreatorCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    creator = Creator(
        name=body.name,
        niche=body.niche,
        discovery_source=body.discovery_source or "manual",
        notes=body.notes,
    )
    session.add(creator)
    await session.flush()
    for acct in body.accounts:
        session.add(CreatorPlatformAccount(creator_id=creator.id, **acct.model_dump()))
    await session.commit()

    result = await session.execute(
        select(Creator)
        .options(selectinload(Creator.platform_accounts))
        .where(Creator.id == creator.id)
    )
    creator = result.scalar_one()
    resp = CreatorDetailResponse.model_validate(creator)
    resp.platform_accounts = [
        PlatformAccountResponse.model_validate(a) for a in creator.platform_accounts
    ]
    return resp


@router.post(
    "/creators/{creator_id}/accounts",
    response_model=PlatformAccountResponse,
    status_code=201,
)
async def add_account(
    creator_id: str,
    body: PlatformAccountCreate,
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    existing = await session.execute(
        select(CreatorPlatformAccount).where(
            CreatorPlatformAccount.platform == body.platform,
            CreatorPlatformAccount.handle == body.handle,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="That platform handle is already registered")
    account = CreatorPlatformAccount(creator_id=creator_id, **body.model_dump())
    session.add(account)
    await session.commit()
    return PlatformAccountResponse.model_validate(account)


# ── Jobs ─────────────────────────────────────────────────────────────


@router.post("/creators/{creator_id}/research", response_model=JobResponse, status_code=202)
async def start_research(
    creator_id: str,
    background: BackgroundTasks,
    body: ResearchRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    if (active := registry.active_for(creator_id)) is not None:
        raise HTTPException(
            status_code=409, detail=f"A job is already running for this creator: {active.id}"
        )
    skip = body.skip_collect if body else False
    job = registry.create("research", creator_id)
    background.add_task(registry.execute, job, lambda: run_research(creator_id, skip))
    return job


@router.post("/creators/{creator_id}/runs", response_model=JobResponse, status_code=202)
async def start_pipeline(
    creator_id: str,
    body: PipelineRunRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    if body.pipeline not in PIPELINES:
        raise HTTPException(
            status_code=422, detail=f"pipeline must be one of {', '.join(PIPELINES)}"
        )
    if body.pipeline == "collect" and not (body.platform and body.identifier):
        raise HTTPException(status_code=422, detail="collect requires platform and identifier")
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    if (active := registry.active_for(creator_id)) is not None:
        raise HTTPException(
            status_code=409, detail=f"A job is already running for this creator: {active.id}"
        )
    job = registry.create(body.pipeline, creator_id)
    if body.pipeline == "research":
        work = lambda: run_research(creator_id, body.skip_collect)  # noqa: E731
    else:
        work = lambda: run_pipeline(  # noqa: E731
            body.pipeline, creator_id, body.platform, body.identifier
        )
    background.add_task(registry.execute, job, work)
    return job


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(creator_id: str | None = None, limit: int = Query(default=50, le=200)):
    return registry.list(creator_id=creator_id, limit=limit)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Campaigns: write ────────────────────────────────────────────────


@router.post("/campaigns", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    session: AsyncSession = Depends(get_session),
):
    campaign = Campaign(**body.model_dump())
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.post(
    "/campaigns/{campaign_id}/{stage}",
    response_model=JobResponse,
    status_code=202,
)
async def start_campaign_pipeline(
    campaign_id: str,
    stage: str,
    background: BackgroundTasks,
    body: CampaignPipelineRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    if stage not in CAMPAIGN_PIPELINES:
        raise HTTPException(
            status_code=422,
            detail=f"stage must be one of {', '.join(CAMPAIGN_PIPELINES)}",
        )
    if await session.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (active := registry.active_for_campaign(campaign_id)) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A job is already running for this campaign: {active.id}",
        )
    source = body.source if body else None
    query = body.query if body else None
    if stage == "discover" and not (source and query):
        raise HTTPException(status_code=422, detail="discover requires source and query")
    job = registry.create(stage, campaign_id=campaign_id)
    work = lambda: run_campaign_pipeline(stage, campaign_id, source=source, query=query)  # noqa: E731
    background.add_task(registry.execute, job, work)
    return job


# ── Reads the console needs ──────────────────────────────────────────


@router.get("/research-runs/{run_id}", response_model=ResearchRunResponse)
async def get_research_run(run_id: str, session: AsyncSession = Depends(get_session)):
    run = await session.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return ResearchRunResponse.model_validate(run)


@router.get("/creators/{creator_id}/clusters", response_model=list[ClusterDetail])
async def get_clusters(
    creator_id: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    clusters = await active_clusters_for_creator(session, creator_id)
    if not clusters:
        response.headers["X-Total-Count"] = "0"
        return []
    ids = [c.id for c in clusters]

    signals = (
        await session.execute(
            select(CommercialSignal)
            .where(
                CommercialSignal.problem_cluster_id.in_(ids),
                CommercialSignal.superseded_at.is_(None),
            )
            .order_by(CommercialSignal.created_at.desc())
        )
    ).scalars().all()
    signal_by_cluster: dict[str, CommercialSignal] = {}
    for s in signals:
        signal_by_cluster.setdefault(s.problem_cluster_id, s)

    scores = (
        await session.execute(
            select(OpportunityScore).where(
                OpportunityScore.problem_cluster_id.in_(ids),
                OpportunityScore.creator_id == creator_id,
                OpportunityScore.superseded_at.is_(None),
            )
        )
    ).scalars().all()
    score_by_cluster = {s.problem_cluster_id: s for s in scores}

    counts = dict(
        (
            await session.execute(
                select(ProblemClusterMember.cluster_id, func.count())
                .where(ProblemClusterMember.cluster_id.in_(ids))
                .group_by(ProblemClusterMember.cluster_id)
            )
        ).all()
    )

    out: list[ClusterDetail] = []
    for c in clusters:
        detail = ClusterDetail.model_validate(c)
        detail.creator_id = c.creator_id
        detail.member_count = int(counts.get(c.id, 0))
        if (sig := signal_by_cluster.get(c.id)) is not None:
            detail.signal = SignalSummary(
                signal_level=sig.signal_level.value,
                confidence=sig.confidence,
                rationale=sig.rationale,
            )
        if (sc := score_by_cluster.get(c.id)) is not None:
            detail.score = OpportunityScoreResponse.model_validate(sc)
        out.append(detail)
    out.sort(key=lambda d: d.score.aggregate_score if d.score else -1.0, reverse=True)
    response.headers["X-Total-Count"] = str(len(out))
    return out


@router.get("/clusters/{cluster_id}/observations", response_model=list[ProblemObservationResponse])
async def get_cluster_observations(
    cluster_id: str,
    response: Response,
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    if await session.get(ProblemCluster, cluster_id) is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    base = (
        select(ProblemObservation)
        .join(ProblemClusterMember, ProblemClusterMember.observation_id == ProblemObservation.id)
        .where(ProblemClusterMember.cluster_id == cluster_id)
    )
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar()
    rows = (
        await session.execute(
            base.order_by(ProblemClusterMember.similarity_score.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    response.headers["X-Total-Count"] = str(total or 0)
    return [ProblemObservationResponse.model_validate(o) for o in rows]


@router.get("/creators/{creator_id}/decisions", response_model=list[DecisionResponse])
async def get_decisions(creator_id: str, session: AsyncSession = Depends(get_session)):
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    rows = (
        await session.execute(
            select(HumanDecision)
            .where(HumanDecision.creator_id == creator_id)
            .order_by(HumanDecision.decided_at.desc())
        )
    ).scalars().all()
    return [DecisionResponse.model_validate(d) for d in rows]


@router.get("/creators/{creator_id}/dossier.json", response_model=DossierJson)
async def get_dossier_json(creator_id: str, session: AsyncSession = Depends(get_session)):
    """The dossier as data, so the console can render it natively."""
    try:
        data = await DossierGenerator(session).generate_data(creator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Creator not found")

    creator = CreatorDetailResponse.model_validate(data.creator)
    creator.platform_accounts = [
        PlatformAccountResponse.model_validate(a) for a in data.platform_accounts
    ]
    opportunities = [
        {
            "cluster": ProblemClusterResponse.model_validate(o.cluster).model_dump(),
            "score": OpportunityScoreResponse.model_validate(o.score).model_dump(mode="json"),
            "signal": (
                SignalSummary(
                    signal_level=o.signal.signal_level.value,
                    confidence=o.signal.confidence,
                    rationale=o.signal.rationale,
                ).model_dump()
                if o.signal
                else None
            ),
            "observations": [
                ProblemObservationResponse.model_validate(obs).model_dump()
                for obs in o.observations
            ],
        }
        for o in data.opportunities
    ]
    return DossierJson(
        creator=creator,
        creator_score=(
            ScoreResponse.model_validate(data.creator_score) if data.creator_score else None
        ),
        score_band=data.score_band,
        weights=data.weights,
        opportunities=opportunities,
        data_coverage={
            "source_count": data.data_coverage.source_count,
            "evidence_count": data.data_coverage.evidence_count,
            "cluster_count": data.data_coverage.cluster_count,
            "observation_count": data.data_coverage.observation_count,
        },
        generated_at=data.generated_at,
    )
