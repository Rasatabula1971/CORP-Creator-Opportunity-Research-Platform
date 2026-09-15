"""Run a pipeline from the command line using the configured provider/adapter.

    python -m corp.workers.run add-creator "<name>" --platform youtube --handle @chan [--niche x]
    python -m corp.workers.run research <creator_id> [--skip-collect]
    python -m corp.workers.run collect <platform> <identifier> <creator_id>
    python -m corp.workers.run intelligence <creator_id>
    python -m corp.workers.run intent [creator_id]

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

    def embedder():
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
    from corp.workers.adapters.registry import build_adapter
    from corp.workers.intelligence.ecosystem_estimator import EcoConfig, EcosystemEstimator

    adapter = build_adapter("youtube")
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
    if args.pipeline == "estimate-ecosystem":
        return asyncio.run(
            _run_estimate_ecosystem(
                args.campaign_id, args.search_count,
                args.min_followers, args.max_followers,
            )
        )
    if args.pipeline == "discover":
        return asyncio.run(_run_discover(args.campaign_id, args.source, args.query))
    return asyncio.run(_run_llm(args.pipeline, args.creator_id))


if __name__ == "__main__":
    sys.exit(main())
