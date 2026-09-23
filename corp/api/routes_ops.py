"""Write endpoints, background jobs, and the reads the review console needs."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from corp.api.jobs import (
    CAMPAIGN_PIPELINES,
    PIPELINES,
    JobResponse,
    registry,
    run_campaign_pipeline,
    run_discovery_scan,
    run_pipeline,
    run_research,
)
from corp.config import settings
from corp.core.models.campaign import Campaign
from corp.core.models.campaign_niche import CampaignNiche
from corp.core.models.creator import Creator, CreatorPlatformAccount
from corp.core.models.dossier import Dossier, DossierStatus
from corp.core.models.intelligence import (
    ProblemCluster,
    ProblemClusterMember,
    ProblemObservation,
)
from corp.core.models.intent import CommercialSignal
from corp.core.models.scoring import OpportunityScore
from corp.core.models.workflow import DecisionType, Gate, HumanDecision, ResearchRun
from corp.core.schemas.campaign import CampaignCreate, CampaignResponse
from corp.core.schemas.creator import (
    CreatorCreate,
    CreatorDetailResponse,
    PlatformAccountCreate,
    PlatformAccountResponse,
)
from corp.core.schemas.intelligence import ProblemClusterResponse, ProblemObservationResponse
from corp.core.schemas.scoring import OpportunityScoreResponse
from corp.core.schemas.workflow import DecisionResponse, ResearchRunResponse
from corp.core.state.gates import mirror_creator_status
from corp.database import get_session
from corp.workers.handoff.corp2_export import build_handoff_package
from corp.workers.intelligence.runs import active_clusters_for_creator
from corp.workers.providers.factory import ProviderConfigError, build_provider
from corp.workers.providers.fair import FairProvider

logger = logging.getLogger(__name__)

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


# CORP1 Stage 5, T8: the dossier-level four-state decision gate. Local to
# this module (not corp.core.schemas.workflow) because DecisionCreate/
# DecisionResponse there are the existing, still-unchanged Gate A
# (creator-status) contract this task must not disturb -- see ADR-0038.
class DossierDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DecisionType
    rationale: str | None = None
    decided_by: str | None = None


class DossierDecisionResponse(BaseModel):
    id: str
    dossier_id: str
    creator_id: str
    decision: DecisionType
    gate: Gate
    rationale: str | None
    decided_at: datetime
    dossier_status: DossierStatus
    job_id: str | None = None


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
        logger.exception("Provider construction failed")
        return {
            "provider": None,
            "kind": None,
            "error": {
                "code": "construction_failed",
                "detail": type(exc).__name__,
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

    try:
        if isinstance(provider, FairProvider):
            try:
                result = await provider.ping()
            except Exception as exc:  # noqa: BLE001 — a failed probe is the diagnosis
                payload["fair"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
            else:
                payload["fair"] = {
                    "ok": result.ok,
                    "provider_count": result.provider_count,
                    "provider_ids": result.provider_ids,
                    "solve_status": result.solve_status,
                    "solve_provider": result.solve_provider,
                    "solve_model": result.solve_model,
                    "detail": result.detail,
                }
    finally:
        # Every provider built here is throwaway. GroqProvider, PooledProvider
        # and FairProvider all hold an async client behind close(); bare
        # GeminiProvider does not expose one.
        close = getattr(provider, "close", None)
        if callable(close):
            await close()

    return payload


# ── Creators: write ──────────────────────────────────────────────────


@router.post("/creators", response_model=CreatorDetailResponse, status_code=201)
async def create_creator(
    body: CreatorCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> CreatorDetailResponse:
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
) -> PlatformAccountResponse:
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
) -> JobResponse:
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
) -> JobResponse:
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
async def list_jobs(
    creator_id: str | None = None, limit: int = Query(default=50, ge=1, le=200),
) -> list[JobResponse]:
    return registry.list(creator_id=creator_id, limit=limit)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str) -> JobResponse:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Campaigns: write ────────────────────────────────────────────────


@router.post("/campaigns", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    session: AsyncSession = Depends(get_session),
) -> CampaignResponse:
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
) -> JobResponse:
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
    # CORP1 Stage 5, T4: discover no longer needs a platform -- the
    # recursive discovery engine fans out across every relevant evidence
    # source automatically. `source` stays accepted (and unused) for any
    # caller still sending it.
    if stage == "discover" and not query:
        raise HTTPException(status_code=422, detail="discover requires query")
    job = registry.create(stage, campaign_id=campaign_id)
    work = lambda: run_campaign_pipeline(stage, campaign_id, source=source, query=query)  # noqa: E731
    background.add_task(registry.execute, job, work)
    return job


# ── Autonomous discovery (CORP1 Step 1, Level 0) ─────────────────────


class DiscoveryRunRequest(BaseModel):
    """Both entry points the spec freezes, on one endpoint.

    No body (or an empty one) is the autonomous pass: the trend scan picks
    the topics. Supplying ``topics`` is the user-suggested alternate entry
    point — the same drill engine, the same evidence and lineage, just a
    seed you chose instead of one Google Trends ranked.
    """

    model_config = ConfigDict(extra="forbid")

    topics: list[str] | None = Field(
        default=None,
        description="Seed topics to drill instead of running the trend scan.",
        max_length=25,
    )
    topics_per_pass: int | None = Field(
        default=None,
        ge=1,
        le=25,
        description="Override how many scanned topics this pass drills.",
    )
    campaign_id: str | None = Field(
        default=None,
        description="Attach to this campaign instead of the standing autonomous one.",
    )


@router.get("/discovery/status")
async def discovery_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Is the crawler actually crawling, and what would it do next?

    The scheduler's own startup line is a logger.info, which uvicorn's
    default log config does not print, so "is it on?" is otherwise
    unanswerable without reading .env. CORP is a pull-based dashboard by
    design (Stage 4: "no push-notification/attention engine"), so the
    honest place for this is an endpoint you can check.
    """
    from corp.workers.intelligence.trend_scan import TrendScanConfig, TrendScanner
    from corp.workers.scheduler.discovery_scan import (
        AUTONOMOUS_CAMPAIGN_NAME,
        momentum_readiness,
    )

    # trend_provider=None: this is a cheap status read, so it must not make
    # a live Trends call. Ordering here is rotation-only and indicative.
    # Construction is inside the try as well: an unreadable or malformed
    # catalogue raises in TrendScanner.__init__, and a status endpoint that
    # 500s exactly when the thing it reports on is broken is useless.
    cfg = None
    try:
        scanner = TrendScanner(
            session,
            trend_provider=None,
            config=TrendScanConfig.from_rules(settings.broad_topics_path),
        )
        cfg = scanner.config
        due, scan_stats = await scanner.scan(
            settings.discovery_topics_per_pass or cfg.topics_per_pass
        )
        next_topics = [s.topic for s in due]
        scan = scan_stats.as_dict()
        error = None
    except Exception as exc:  # noqa: BLE001 — a status read never 500s
        logger.exception("Discovery status: preview scan failed")
        next_topics, scan, error = [], {}, f"{type(exc).__name__}: {exc}"

    provider_ready = True
    provider_detail: str | None = None
    try:
        probe = build_provider()
    except ProviderConfigError as exc:
        provider_ready = False
        provider_detail = str(exc)
    except Exception as exc:  # noqa: BLE001
        provider_ready = False
        provider_detail = f"{type(exc).__name__}: {exc}"
    else:
        close = getattr(probe, "close", None)
        if callable(close):
            await close()

    momentum_source, momentum_available, momentum_detail = momentum_readiness(settings)

    result = await session.execute(
        select(Campaign.id).where(
            func.lower(Campaign.name) == AUTONOMOUS_CAMPAIGN_NAME.lower()
        ).limit(1)
    )
    return {
        "enabled": settings.discovery_enabled,
        "interval_seconds": settings.discovery_interval_seconds,
        "topics_per_pass": settings.discovery_topics_per_pass
        or (cfg.topics_per_pass if cfg else None),
        "catalogue_size": len(cfg.topics) if cfg else None,
        "geo": cfg.geo if cfg else None,
        # A pass needs an LLM to drill with; without one it fails immediately.
        "can_run": provider_ready,
        "provider_detail": provider_detail,
        # Whether topics will be ranked by live momentum or just rotated
        # through. Checks prerequisites only; no call is made to the source.
        "momentum_source": momentum_source,
        "momentum_available": momentum_available,
        "momentum_detail": momentum_detail,
        "autonomous_campaign_id": result.scalar_one_or_none(),
        # Rotation order: previewing momentum would spend quota on a status read.
        "next_topics": next_topics,
        "scan": scan,
        "error": error,
        "active_job": (job.id if (job := registry.active_of_kind("discovery")) else None),
    }


@router.post("/discovery/run", response_model=JobResponse, status_code=202)
async def start_discovery_scan(
    background: BackgroundTasks,
    body: DiscoveryRunRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    """Run one discovery pass now, whether or not the scheduler is enabled."""
    topics = [t.strip() for t in (body.topics or [])] if body else []
    topics = [t for t in topics if t]
    if body and body.topics is not None and not topics:
        raise HTTPException(status_code=422, detail="topics must not be blank")

    campaign_id = body.campaign_id if body else None
    if campaign_id is not None:
        if await session.get(Campaign, campaign_id) is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if (active := registry.active_for_campaign(campaign_id)) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A job is already running for this campaign: {active.id}",
            )

    per_pass = body.topics_per_pass if body else None
    job = registry.create("discovery", campaign_id=campaign_id)
    work = lambda: run_discovery_scan(  # noqa: E731
        topics=topics or None, topics_per_pass=per_pass, campaign_id=campaign_id
    )
    background.add_task(registry.execute, job, work)
    return job


# ── Reads the console needs ──────────────────────────────────────────


@router.get("/research-runs/{run_id}", response_model=ResearchRunResponse)
async def get_research_run(
    run_id: str, session: AsyncSession = Depends(get_session),
) -> ResearchRunResponse:
    run = await session.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return ResearchRunResponse.model_validate(run)


@router.get("/creators/{creator_id}/clusters", response_model=list[ClusterDetail])
async def get_clusters(
    creator_id: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> list[ClusterDetail]:
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

    count_rows = (
        await session.execute(
            select(ProblemClusterMember.cluster_id, func.count())
            .where(ProblemClusterMember.cluster_id.in_(ids))
            .group_by(ProblemClusterMember.cluster_id)
        )
    ).all()
    counts: dict[str, int] = {row[0]: row[1] for row in count_rows}

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
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ProblemObservationResponse]:
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
async def get_decisions(
    creator_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[DecisionResponse]:
    if await session.get(Creator, creator_id) is None:
        raise HTTPException(status_code=404, detail="Creator not found")
    rows = (
        await session.execute(
            select(HumanDecision)
            .where(HumanDecision.creator_id == creator_id)
            .order_by(HumanDecision.decided_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [DecisionResponse.model_validate(d) for d in rows]


# ── Dossier decision gate (CORP1 Stage 5, T8) ───────────────────────


async def _run_research_more(dossier_id: str, niche_id: str, campaign_id: str) -> dict[str, Any]:
    """Work function for the Research More decision outcome (T8, completed
    by R12a). Runs the full re-research chain through WatchRescanner --
    niche drill at depth+1, creator re-research, product ideation, a new
    dossier version -- and always resurfaces the result to PENDING_REVIEW.
    On failure the rescanner puts the dossier back to PENDING_REVIEW so it
    is never stuck in research_more_in_progress."""
    from corp.api.jobs import _embedder_factory
    from corp.database import async_session
    from corp.workers.providers.factory import build_provider
    from corp.workers.watch_rescan import build_watch_rescanner

    provider = build_provider()
    try:
        async with async_session() as session:
            try:
                rescanner = build_watch_rescanner(
                    session,
                    provider,
                    _embedder_factory(),
                    scoring_rules_path=settings.scoring_rules_path,
                    niche_rules_path="rules/niche_discovery_prompt.yaml",
                    ideation_rules_path="rules/product_ideation_prompt.yaml",
                )
                outcome = await rescanner.rescan(dossier_id, trigger="research_more")
                await session.commit()
            except Exception:
                # Persist the failed run row and the PENDING_REVIEW restore if
                # the session can still commit; then ALWAYS re-check in a
                # fresh transaction -- a rolled-back session commits cleanly
                # having lost the restore, and the route committed
                # research_more_in_progress before this job started. "Never
                # stuck" is the design's contract; the check is status-guarded
                # so a second restore is a no-op.
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
                async with async_session() as fresh:
                    dossier = await fresh.get(Dossier, dossier_id)
                    if (
                        dossier is not None
                        and dossier.status == DossierStatus.RESEARCH_MORE_IN_PROGRESS
                    ):
                        dossier.status = DossierStatus.PENDING_REVIEW
                        await fresh.commit()
                raise
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            await close()
    return {
        "run_id": outcome.run_id,
        "status": "completed",
        "dossier_id": outcome.dossier_id,
        "previous_dossier_id": outcome.previous_dossier_id,
        "niche_id": niche_id,
        "campaign_id": campaign_id,
        "reason": outcome.decision.reason,
    }


@router.post(
    "/dossiers/{dossier_id}/decision",
    response_model=DossierDecisionResponse,
    status_code=201,
)
async def record_dossier_decision(
    dossier_id: str,
    body: DossierDecisionRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> DossierDecisionResponse:
    """The four-state dossier decision gate: Reject / Research More / Watch
    / Approve, exhaustively typed by DecisionType so no other value can
    reach here. Distinct from POST /creators/{id}/decisions (Gate A,
    creator-status-scoped, untouched by this task) -- this gate decides on
    a specific Dossier and always records a new, append-only HumanDecision
    row naming it via dossier_id."""
    dossier = await session.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")
    if dossier.superseded_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Dossier has been superseded by a newer version",
        )
    if dossier.status not in (DossierStatus.PENDING_REVIEW, DossierStatus.WATCHING):
        raise HTTPException(
            status_code=409,
            detail=f"Dossier already decided (status={dossier.status.value})",
        )

    campaign_niche: CampaignNiche | None = None
    if body.decision == DecisionType.RESEARCH_MORE:
        campaign_niche = (
            await session.execute(
                select(CampaignNiche)
                .where(CampaignNiche.niche_id == dossier.niche_id)
                .order_by(CampaignNiche.created_at.desc())
            )
        ).scalars().first()
        if campaign_niche is None:
            raise HTTPException(
                status_code=422,
                detail="Dossier's niche has no campaign association; cannot start Research More",
            )
        if (active := registry.active_for_campaign(campaign_niche.campaign_id)) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A job is already running for this campaign: {active.id}",
            )

    decision_row = HumanDecision(
        creator_id=dossier.creator_id,
        dossier_id=dossier.id,
        decision=body.decision,
        gate=Gate.GATE_D,
        rationale=body.rationale,
        decided_by=body.decided_by,
    )
    session.add(decision_row)

    job_id: str | None = None
    if body.decision == DecisionType.REJECT:
        dossier.status = DossierStatus.REJECTED
    elif body.decision == DecisionType.WATCH:
        dossier.status = DossierStatus.WATCHING
    elif body.decision == DecisionType.APPROVE:
        dossier.status = DossierStatus.APPROVED
    elif body.decision == DecisionType.RESEARCH_MORE:
        assert campaign_niche is not None  # validated above
        dossier.status = DossierStatus.RESEARCH_MORE_IN_PROGRESS
        job = registry.create("research_more", campaign_id=campaign_niche.campaign_id)
        job_id = job.id
        dossier_id_ = dossier.id
        niche_id, campaign_id = dossier.niche_id, campaign_niche.campaign_id
        background.add_task(
            registry.execute,
            job,
            lambda: _run_research_more(dossier_id_, niche_id, campaign_id),
        )

    await session.flush()
    # R12b: Creator.status follows its active dossiers (watch → WATCHING,
    # approve → APPROVED, reject → REJECTED; a pending/in-progress dossier on
    # another niche keeps the creator in HUMAN_REVIEW).
    await mirror_creator_status(session, dossier.creator_id)
    await session.commit()
    return DossierDecisionResponse(
        id=decision_row.id,
        dossier_id=dossier.id,
        creator_id=dossier.creator_id,
        decision=decision_row.decision,
        gate=decision_row.gate,
        rationale=decision_row.rationale,
        decided_at=decision_row.decided_at,
        dossier_status=dossier.status,
        job_id=job_id,
    )


@router.get("/dossiers/{dossier_id}/handoff")
async def get_handoff_package(
    dossier_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return the CORP2 handoff package for an approved dossier."""
    dossier = await session.get(Dossier, dossier_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="Dossier not found")
    if dossier.superseded_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Dossier has been superseded — use the current version",
        )
    if dossier.status != DossierStatus.APPROVED:
        raise HTTPException(
            status_code=403,
            detail="Handoff only available for approved dossiers",
        )
    try:
        package = await build_handoff_package(session, dossier_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return package.to_dict()
