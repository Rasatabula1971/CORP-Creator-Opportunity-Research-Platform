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
        session.add(
            CreatorPlatformAccount(creator_id=creator.id, platform=platform, handle=handle)
        )
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

    args = parser.parse_args(argv)
    logging.basicConfig(level=settings.log_level)

    if args.pipeline == "add-creator":
        return asyncio.run(_run_add_creator(args.name, args.platform, args.handle, args.niche))
    if args.pipeline == "research":
        return asyncio.run(_run_research(args.creator_id, args.skip_collect))
    if args.pipeline == "collect":
        return asyncio.run(_run_collect(args.platform, args.identifier, args.creator_id))
    return asyncio.run(_run_llm(args.pipeline, args.creator_id))


if __name__ == "__main__":
    sys.exit(main())
