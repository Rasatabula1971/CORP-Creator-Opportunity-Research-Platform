"""Run a pipeline from the command line using the configured provider/adapter.

    python -m corp.workers.run add-creator "<name>" --platform youtube --handle @chan [--niche x]
    python -m corp.workers.run research <creator_id> [--skip-collect]
    python -m corp.workers.run collect <platform> <identifier> <creator_id>
    python -m corp.workers.run intelligence <creator_id>
    python -m corp.workers.run intent [creator_id]
    python -m corp.workers.run warm-init
    python -m corp.workers.run warm-status
    python -m corp.workers.run warm-export <out_dir>

`research` runs every stage in order and leaves the creator in HUMAN_REVIEW.
The single-stage commands exist for re-running one step.
"""

import argparse
import asyncio
import logging
import sys

from corp.config import settings
from corp.workers.adapters.registry import build_adapter
from corp.workers.providers.factory import build_provider

logger = logging.getLogger(__name__)


async def _close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is not None:
        await close()


async def _run_collect(platform: str, identifier: str, creator_id: str) -> int:
    adapter = build_adapter(platform)  # fail fast on config before touching the database

    from corp.database import async_session
    from corp.workers.acquisition.collector import AcquisitionCollector

    try:
        async with async_session() as session:
            run = await AcquisitionCollector(adapter, session).collect_creator_data(
                identifier, creator_id
            )
            await session.commit()
        print(f"research_run={run.id} status={run.status} platform={adapter.platform}")
        return 0 if run.status == "completed" else 1
    finally:
        await _close(adapter)


async def _run_llm(pipeline_name: str, creator_id: str | None) -> int:
    provider = build_provider()  # fail fast on config before touching the database

    # Imported here so argument parsing never needs a database engine.
    from corp.database import async_session
    from corp.workers.intelligence.intent_pipeline import IntentPipeline
    from corp.workers.intelligence.pipeline import IntelligencePipeline

    try:
        async with async_session() as session:
            if pipeline_name == "intelligence":
                if creator_id is None:
                    print("intelligence pipeline requires a creator_id", file=sys.stderr)
                    return 2
                run = await IntelligencePipeline(provider, session).run(creator_id)
            else:
                run = await IntentPipeline(provider, session).run(creator_id)
            await session.commit()
        print(f"research_run={run.id} status={run.status} model={provider.model_name}")
        return 0 if run.status == "completed" else 1
    finally:
        await _close(provider)


async def _run_add_creator(name: str, platform: str, handle: str, niche: str | None) -> int:
    from corp.core.models.creator import Creator, CreatorPlatformAccount
    from corp.database import async_session

    async with async_session() as session:
        creator = Creator(name=name, niche=niche, discovery_source="manual")
        session.add(creator)
        await session.flush()
        session.add(CreatorPlatformAccount(creator_id=creator.id, platform=platform, handle=handle))
        await session.commit()
        print(f"creator_id={creator.id} name={name!r} {platform}:{handle}")
    return 0


async def _run_research(creator_id: str, skip_collect: bool) -> int:
    provider = build_provider()

    from corp.database import async_session
    from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder
    from corp.workers.orchestrator import ResearchOrchestrator

    def embedder() -> SentenceTransformerEmbedder:
        return SentenceTransformerEmbedder(settings.embedding_model)

    try:
        async with async_session() as session:
            orchestrator = ResearchOrchestrator(session, provider, embedder)
            report = await orchestrator.run(creator_id, skip_collect=skip_collect)
        print(report.summary())
        return 0 if report.final_status == "human_review" else 1
    finally:
        await _close(provider)


async def _run_add_campaign(name: str) -> int:
    from corp.core.models.campaign import Campaign
    from corp.database import async_session

    async with async_session() as session:
        campaign = Campaign(name=name)
        session.add(campaign)
        await session.commit()
        print(f"campaign_id={campaign.id} name={name!r}")
    return 0


async def _run_discover(campaign_id: str, source: str, query: str) -> int:
    from corp.database import async_session
    from corp.workers.acquisition.discovery import NicheDiscoveryCollector
    from corp.workers.adapters.registry import build_adapter

    adapter = build_adapter(source)
    try:
        async with async_session() as session:
            collector = NicheDiscoveryCollector(adapter, session, settings.corp_data_path)
            run = await collector.discover(campaign_id, query)
            await session.commit()
        extra = (run.stats or {}).get("extra", {})
        print(
            f"research_run={run.id} status={run.status} "
            f"seen={extra.get('results_seen')} new={extra.get('new_results')} "
            f"duplicate={extra.get('duplicate_results')}"
        )
        return 0 if run.status == "completed" else 1
    finally:
        await _close(adapter)


async def _run_canonicalize(campaign_id: str, similarity_threshold: float) -> int:
    from corp.database import async_session
    from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder
    from corp.workers.intelligence.niche_canonicalization import CanonConfig, NicheCanonicalizer

    async with async_session() as session:
        canon = NicheCanonicalizer(
            SentenceTransformerEmbedder(settings.embedding_model),
            session,
            CanonConfig(similarity_threshold=similarity_threshold),
        )
        run = await canon.canonicalize(campaign_id)
        await session.commit()
    extra = (run.stats or {}).get("extra", {})
    print(
        f"research_run={run.id} status={run.status} "
        f"candidates={extra.get('candidates')} promoted={extra.get('promoted')} "
        f"merged={extra.get('merged')} campaign_niches={extra.get('campaign_niches_created')}"
    )
    return 0 if run.status == "completed" else 1


async def _run_verify(
    campaign_id: str, min_evidence: int, min_authors: int, allow_broad: bool,
) -> int:
    from corp.database import async_session
    from corp.workers.intelligence.niche_verification import NicheVerifier, VerifyConfig

    async with async_session() as session:
        verifier = NicheVerifier(
            session,
            VerifyConfig(
                min_evidence=min_evidence,
                min_authors=min_authors,
                reject_broad_domain=not allow_broad,
            ),
        )
        run = await verifier.verify(campaign_id)
        await session.commit()
    extra = (run.stats or {}).get("extra", {})
    print(
        f"research_run={run.id} status={run.status} "
        f"checked={extra.get('candidates_checked')} verified={extra.get('verified')} "
        f"failed={extra.get('failed_verification')}"
    )
    for r in extra.get("results", []):
        status = "PASS" if r["passed"] else "FAIL"
        reasons = f" ({'; '.join(r['reasons'])})" if r["reasons"] else ""
        print(f"  {status}: {r['niche']}{reasons}")
    return 0 if run.status == "completed" else 1


async def _run_estimate_ecosystem(
    campaign_id: str, search_count: int, min_followers: int, max_followers: int,
) -> int:
    from corp.database import async_session
    from corp.workers.adapters.registry import build_search_adapter
    from corp.workers.intelligence.ecosystem_estimator import (
        EcoConfig,
        EcosystemEstimator,
        YouTubeAPIEnricher,
    )

    adapter = build_search_adapter("youtube")
    enricher = None
    if settings.youtube_api_key:
        enricher = YouTubeAPIEnricher(settings.youtube_api_key)
        logger.info("YouTube API enricher enabled for subscriber counts")
    try:
        async with async_session() as session:
            estimator = EcosystemEstimator(
                adapter,
                session,
                EcoConfig(
                    search_count=search_count,
                    min_followers=min_followers,
                    max_followers=max_followers,
                ),
                enricher=enricher,
            )
            run = await estimator.estimate(campaign_id)
            await session.commit()
        extra = (run.stats or {}).get("extra", {})
        print(
            f"research_run={run.id} status={run.status} "
            f"niches_checked={extra.get('niches_checked')}"
        )
        for r in extra.get("results", []):
            print(
                f"  {r['niche']}: {r['total_creators']} creators, "
                f"{r['target_band_creators']} in target band"
            )
        return 0 if run.status == "completed" else 1
    finally:
        close = getattr(adapter, "close", None)
        if close is not None:
            await close()


async def _run_qualify(campaign_id: str, rules_path: str) -> int:
    from corp.database import async_session
    from corp.workers.intelligence.niche_qualification import NicheQualifier

    async with async_session() as session:
        qualifier = NicheQualifier(session, rules_path)
        run = await qualifier.qualify_campaign(campaign_id)
        await session.commit()
    extra = (run.stats or {}).get("extra", {})
    print(
        f"research_run={run.id} status={run.status} "
        f"niches_scored={extra.get('niches_scored')}"
    )
    for r in extra.get("results", []):
        print(
            f"  {r['niche']}: score={r['qualification_score']:.4f} "
            f"confidence={r['confidence']:.4f} "
            f"completeness={r['research_completeness']:.4f}"
        )
    return 0 if run.status == "completed" else 1


async def _run_select(
    campaign_id: str, top_n: int, min_score: float, min_confidence: float,
) -> int:
    from corp.database import async_session
    from corp.workers.intelligence.niche_selection import NicheSelector, SelectionConfig

    async with async_session() as session:
        selector = NicheSelector(
            session,
            SelectionConfig(top_n=top_n, min_score=min_score, min_confidence=min_confidence),
        )
        run = await selector.select(campaign_id)
        await session.commit()
    extra = (run.stats or {}).get("extra", {})
    print(
        f"research_run={run.id} status={run.status} "
        f"ranked={extra.get('niches_ranked')} selected={extra.get('selected')} "
        f"rejected={extra.get('rejected')}"
    )
    for r in extra.get("results", []):
        mark = "SELECTED" if r["selected"] else "REJECTED"
        print(f"  #{r['rank']} {mark}: {r['niche']} (score={r['score']:.4f}) — {r['rationale']}")
    return 0 if run.status == "completed" else 1


async def _run_onboard(
    campaign_id: str, search_count: int, max_per_niche: int,
    min_followers: int | None, max_followers: int | None,
) -> int:
    from corp.database import async_session
    from corp.workers.acquisition.creator_onboarding import CreatorOnboarder, OnboardConfig
    from corp.workers.adapters.registry import build_search_adapter
    from corp.workers.intelligence.ecosystem_estimator import YouTubeAPIEnricher

    adapter = build_search_adapter("youtube")
    enricher = YouTubeAPIEnricher(settings.youtube_api_key) if settings.youtube_api_key else None
    if enricher is not None:
        logger.info("YouTube API enricher enabled for subscriber counts")
    try:
        async with async_session() as session:
            onboarder = CreatorOnboarder(
                adapter,
                session,
                OnboardConfig(
                    search_count=search_count,
                    max_creators_per_niche=max_per_niche,
                    min_followers=min_followers,
                    max_followers=max_followers,
                ),
                enricher=enricher,
            )
            run = await onboarder.onboard(campaign_id)
            await session.commit()
        extra = (run.stats or {}).get("extra", {})
        print(
            f"research_run={run.id} status={run.status} "
            f"niches_processed={extra.get('niches_processed')} "
            f"creators_created={extra.get('creators_created')} "
            f"creators_linked={extra.get('creators_linked')}"
        )
        for r in extra.get("results", []):
            print(
                f"  {r['niche']}: {r['channels_found']} channels, "
                f"{r['creators_created']} new, {r['creators_linked']} linked"
            )
        return 0 if run.status == "completed" else 1
    finally:
        close = getattr(adapter, "close", None)
        if close is not None:
            await close()


async def _run_research_campaign(
    campaign_id: str, limit: int | None, skip_collect: bool, force: bool,
) -> int:
    from corp.database import async_session
    from corp.workers.campaign_research import BatchConfig, CampaignResearchBatch
    from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder
    from corp.workers.orchestrator import ResearchOrchestrator

    provider = build_provider()

    def embedder() -> SentenceTransformerEmbedder:
        return SentenceTransformerEmbedder(settings.embedding_model)

    try:
        async with async_session() as session:
            orchestrator = ResearchOrchestrator(session, provider, embedder)
            batch = CampaignResearchBatch(
                orchestrator, session,
                BatchConfig(limit=limit, skip_collect=skip_collect, force=force),
            )
            run = await batch.run_campaign(campaign_id)
            await session.commit()
        extra = (run.stats or {}).get("extra", {})
        print(
            f"research_run={run.id} status={run.status} "
            f"total={extra.get('creators_total')} succeeded={extra.get('succeeded')} "
            f"incomplete={extra.get('incomplete')} skipped={extra.get('skipped')} "
            f"errored={extra.get('errored')}"
        )
        for r in extra.get("results", []):
            print(f"  {r['outcome']}: {r['name']} ({r['creator_id']}) — {r['reason']}")
        return 0 if run.status == "completed" else 1
    finally:
        await _close(provider)


async def _run_prune(retention_days: int, apply: bool) -> int:
    from corp.database import async_session
    from corp.workers.maintenance import PruneService

    async with async_session() as session:
        report = await PruneService(session, retention_days=retention_days).prune(apply=apply)
        if apply:
            await session.commit()

    verb = "deleted" if apply else "would delete (dry-run; pass --apply to remove)"
    print(f"prune retention={report.retention_days}d cutoff={report.cutoff}")
    print(f"  metrics_snapshots: {report.metrics_snapshots:,} {verb}")
    return 0


async def _run_warm_init() -> int:
    from corp.warmstore.store import WarmStore

    store = WarmStore(settings.warm_store_path)
    await store.init_db()
    print(f"warm store initialized: {store.path}")
    await store.close()
    return 0


async def _run_warm_status() -> int:
    from corp.warmstore.store import WarmStore

    store = WarmStore(settings.warm_store_path)
    await store.init_db()
    counts = await store.count_rows()
    total = 0
    for table, count in counts.items():
        print(f"  {table}: {count:,}")
        total += count
    print(f"  total: {total:,}")
    print(f"  path: {store.path}")
    await store.close()
    return 0


async def _run_warm_export(out_dir: str) -> int:
    from corp.warmstore.store import WarmStore

    store = WarmStore(settings.warm_store_path)
    await store.init_db()
    exported = await store.export_jsonl(out_dir)
    total = 0
    for table, count in exported.items():
        print(f"  {table}: {count:,} rows")
        total += count
    print(f"  total: {total:,} rows exported to {out_dir}")
    await store.close()
    return 0


async def _run_candidates(campaign_id: str, min_cluster_size: int, no_llm: bool) -> int:
    from corp.database import async_session
    from corp.workers.intelligence.embeddings import SentenceTransformerEmbedder
    from corp.workers.intelligence.niche_candidates import CandidateConfig, NicheCandidateGenerator

    provider = None if no_llm else build_provider()
    try:
        async with async_session() as session:
            generator = NicheCandidateGenerator(
                SentenceTransformerEmbedder(settings.embedding_model),
                provider,
                session,
                CandidateConfig(min_cluster_size=min_cluster_size),
            )
            run = await generator.generate(campaign_id)
            await session.commit()
        extra = (run.stats or {}).get("extra", {})
        print(
            f"research_run={run.id} status={run.status} evidence={extra.get('evidence')} "
            f"candidates={extra.get('candidates')} noise={extra.get('noise')} "
            f"superseded={extra.get('superseded')} "
            f"llm_failures={extra.get('llm_naming_failures')} "
            f"ungrounded={extra.get('llm_names_ungrounded')}"
        )
        return 0 if run.status == "completed" else 1
    finally:
        if provider is not None:
            await _close(provider)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="pipeline", required=True)

    add = sub.add_parser("add-creator", help="register a creator and one platform account")
    add.add_argument("name")
    add.add_argument("--platform", required=True, help="youtube | reddit | tiktok | web")
    add.add_argument("--handle", required=True, help="@channel, r/<sub>, u/<user>, or a URL")
    add.add_argument("--niche")

    research = sub.add_parser("research", help="run every stage for a creator, in order")
    research.add_argument("creator_id")
    research.add_argument("--skip-collect", action="store_true")

    collect = sub.add_parser("collect", help="collect a creator's public data via an adapter")
    collect.add_argument("platform", help="youtube | reddit | tiktok | web")
    collect.add_argument("identifier", help="channel handle, r/<sub>, or u/<user>")
    collect.add_argument("creator_id")

    intel = sub.add_parser("intelligence", help="extract problems + classify topics")
    intel.add_argument("creator_id")

    intent = sub.add_parser("intent", help="classify commercial intent per cluster")
    intent.add_argument("creator_id", nargs="?")

    add_campaign = sub.add_parser("add-campaign", help="create a research campaign")
    add_campaign.add_argument("name")

    candidates = sub.add_parser(
        "candidates", help="group a campaign's discovery evidence into staged niche candidates"
    )
    candidates.add_argument("campaign_id")
    candidates.add_argument("--min-cluster-size", type=int, default=3)
    candidates.add_argument("--no-llm", action="store_true", help="keyword labels only")

    canon = sub.add_parser(
        "canonicalize",
        help="promote staged candidates to canonical niches, merging duplicates",
    )
    canon.add_argument("campaign_id")
    canon.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.82,
        help="cosine similarity threshold for deduplication (default 0.82)",
    )

    verify = sub.add_parser(
        "verify", help="verify candidate niches against evidence-quality thresholds"
    )
    verify.add_argument("campaign_id")
    verify.add_argument("--min-evidence", type=int, default=5)
    verify.add_argument("--min-authors", type=int, default=3)
    verify.add_argument(
        "--allow-broad", action="store_true", help="do not reject broad-domain niches"
    )

    qual = sub.add_parser(
        "qualify", help="score verified niches by evidence, ecosystem, specificity"
    )
    qual.add_argument("campaign_id")
    qual.add_argument(
        "--rules", default="rules/niche_qualification.yaml",
        help="path to qualification rules YAML (default: rules/niche_qualification.yaml)",
    )

    select = sub.add_parser(
        "select", help="rank qualified niches and mark the winners SELECTED"
    )
    select.add_argument("campaign_id")
    select.add_argument("--top-n", type=int, default=5)
    select.add_argument("--min-score", type=float, default=0.0)
    select.add_argument("--min-confidence", type=float, default=0.0)

    research_campaign = sub.add_parser(
        "research-campaign",
        help="run the full per-creator research pipeline for every onboarded creator",
    )
    research_campaign.add_argument("campaign_id")
    research_campaign.add_argument("--limit", type=int, default=None)
    research_campaign.add_argument("--skip-collect", action="store_true")
    research_campaign.add_argument(
        "--force", action="store_true",
        help="re-research creators that already progressed past DISCOVERED",
    )

    onboard = sub.add_parser(
        "onboard", help="materialize Creator rows from ecosystem search for SELECTED niches"
    )
    onboard.add_argument("campaign_id")
    onboard.add_argument("--search-count", type=int, default=20)
    onboard.add_argument("--max-per-niche", type=int, default=10)
    onboard.add_argument("--min-followers", type=int, default=None)
    onboard.add_argument("--max-followers", type=int, default=None)

    eco = sub.add_parser(
        "estimate-ecosystem",
        help="estimate creator ecosystem size for verified niches",
    )
    eco.add_argument("campaign_id")
    eco.add_argument("--search-count", type=int, default=20)
    eco.add_argument("--min-followers", type=int, default=10_000)
    eco.add_argument("--max-followers", type=int, default=200_000)

    discover = sub.add_parser(
        "discover", help="niche discovery (light): one source, one query, under a campaign"
    )
    discover.add_argument("campaign_id")
    discover.add_argument("source", help="reddit | youtube | tiktok | web")
    discover.add_argument(
        "query", help="youtube: 'ytsearch5:<keywords>' (yt-dlp search); reddit: r/<subreddit>"
    )

    prune = sub.add_parser(
        "prune",
        help="delete safe-to-drop bulk history (metrics_snapshots) from Postgres; "
        "the warm store keeps the full record",
    )
    prune.add_argument("--retention-days", type=int, default=90)
    prune.add_argument(
        "--apply", action="store_true", help="actually delete (default is a dry-run)"
    )

    sub.add_parser("warm-init", help="initialize the warm store SQLite database")
    sub.add_parser("warm-status", help="show warm store row counts and path")
    warm_export = sub.add_parser("warm-export", help="export warm store tables to JSONL")
    warm_export.add_argument("out_dir", help="output directory for JSONL files")

    args = parser.parse_args(argv)
    logging.basicConfig(level=settings.log_level)

    if args.pipeline == "add-creator":
        return asyncio.run(_run_add_creator(args.name, args.platform, args.handle, args.niche))
    if args.pipeline == "research":
        return asyncio.run(_run_research(args.creator_id, args.skip_collect))
    if args.pipeline == "collect":
        return asyncio.run(_run_collect(args.platform, args.identifier, args.creator_id))
    if args.pipeline == "add-campaign":
        return asyncio.run(_run_add_campaign(args.name))
    if args.pipeline == "candidates":
        return asyncio.run(_run_candidates(args.campaign_id, args.min_cluster_size, args.no_llm))
    if args.pipeline == "canonicalize":
        return asyncio.run(_run_canonicalize(args.campaign_id, args.similarity_threshold))
    if args.pipeline == "verify":
        return asyncio.run(
            _run_verify(args.campaign_id, args.min_evidence, args.min_authors, args.allow_broad)
        )
    if args.pipeline == "qualify":
        return asyncio.run(_run_qualify(args.campaign_id, args.rules))
    if args.pipeline == "select":
        return asyncio.run(
            _run_select(args.campaign_id, args.top_n, args.min_score, args.min_confidence)
        )
    if args.pipeline == "onboard":
        return asyncio.run(
            _run_onboard(
                args.campaign_id, args.search_count, args.max_per_niche,
                args.min_followers, args.max_followers,
            )
        )
    if args.pipeline == "research-campaign":
        return asyncio.run(
            _run_research_campaign(
                args.campaign_id, args.limit, args.skip_collect, args.force,
            )
        )
    if args.pipeline == "estimate-ecosystem":
        return asyncio.run(
            _run_estimate_ecosystem(
                args.campaign_id, args.search_count,
                args.min_followers, args.max_followers,
            )
        )
    if args.pipeline == "discover":
        return asyncio.run(_run_discover(args.campaign_id, args.source, args.query))
    if args.pipeline == "prune":
        return asyncio.run(_run_prune(args.retention_days, args.apply))
    if args.pipeline == "warm-init":
        return asyncio.run(_run_warm_init())
    if args.pipeline == "warm-status":
        return asyncio.run(_run_warm_status())
    if args.pipeline == "warm-export":
        return asyncio.run(_run_warm_export(args.out_dir))
    return asyncio.run(_run_llm(args.pipeline, args.creator_id))


if __name__ == "__main__":
    sys.exit(main())
