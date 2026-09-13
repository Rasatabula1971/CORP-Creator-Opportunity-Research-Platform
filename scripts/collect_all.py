"""Run Reddit, TikTok, and Instagram adapters together.

Usage:
    # Dry run — collect and print summary (no DB required)
    python scripts/collect_all.py --reddit creatoreconomy --tiktok @creator --instagram creator

    # Persist to DB via AcquisitionCollector
    python scripts/collect_all.py --reddit creatoreconomy --persist --creator-name "Some Creator"

    # All three platforms for the same creator
    python scripts/collect_all.py \\
        --reddit creatoreconomy \\
        --tiktok @creatorname \\
        --instagram creatorname \\
        --persist --creator-name "Creator Name"
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corp.config import settings
from corp.workers.adapters.base import NormalizedContent, SourceAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collect_all")


def build_adapters(args: argparse.Namespace) -> list[tuple[SourceAdapter, str]]:
    """Return (adapter, identifier) pairs for each requested platform."""
    pairs: list[tuple[SourceAdapter, str]] = []

    if args.reddit:
        from corp.workers.adapters.reddit import RedditAdapter

        adapter = RedditAdapter(
            max_posts=args.max_posts,
            max_comments_per_post=args.max_comments,
        )
        for sub in args.reddit:
            pairs.append((adapter, sub))

    if args.tiktok:
        from corp.workers.adapters.tiktok import TikTokAdapter

        adapter = TikTokAdapter(
            max_videos=args.max_posts,
            include_comments=True,
        )
        for handle in args.tiktok:
            pairs.append((adapter, handle))

    if args.instagram:
        from corp.workers.adapters.instagram import InstagramAdapter

        adapter = InstagramAdapter(
            max_posts=args.max_posts,
            max_comments_per_post=args.max_comments,
            username=settings.instagram_username or None,
            password=settings.instagram_password or None,
        )
        for username in args.instagram:
            pairs.append((adapter, username))

    return pairs


def print_summary(platform: str, identifier: str, items: list[NormalizedContent]) -> None:
    content_counts: dict[str, int] = {}
    for item in items:
        content_counts[item.content_type] = content_counts.get(item.content_type, 0) + 1

    total_text = sum(len(item.text) for item in items if item.text)

    logger.info(
        "[%s/%s] %d items collected — %s — %d chars of text",
        platform,
        identifier,
        len(items),
        ", ".join(f"{k}: {v}" for k, v in sorted(content_counts.items())),
        total_text,
    )


async def run_adapter(adapter: SourceAdapter, identifier: str) -> list[NormalizedContent]:
    platform = adapter.platform
    logger.info("[%s] Starting collection for %s ...", platform, identifier)
    t0 = time.monotonic()
    try:
        items = await adapter.collect(identifier)
        elapsed = time.monotonic() - t0
        print_summary(platform, identifier, items)
        logger.info("[%s/%s] Finished in %.1fs", platform, identifier, elapsed)
        return items
    except Exception:
        elapsed = time.monotonic() - t0
        logger.exception("[%s/%s] Failed after %.1fs", platform, identifier, elapsed)
        return []


async def persist_results(
    all_results: list[tuple[SourceAdapter, str, list[NormalizedContent]]],
    creator_name: str,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from corp.core.models.creator import Creator, CreatorPlatformAccount, CreatorStatus
    from corp.workers.acquisition.collector import AcquisitionCollector

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(
            select(Creator).where(Creator.name == creator_name)
        )
        creator = result.scalar_one_or_none()

        if not creator:
            creator = Creator(name=creator_name, status=CreatorStatus.COLLECTING)
            session.add(creator)
            await session.flush()
            logger.info("Created new Creator: %s (id=%s)", creator_name, creator.id)
        else:
            logger.info("Using existing Creator: %s (id=%s)", creator_name, creator.id)

        for adapter, identifier, items in all_results:
            if not items:
                continue

            existing = await session.execute(
                select(CreatorPlatformAccount).where(
                    CreatorPlatformAccount.creator_id == creator.id,
                    CreatorPlatformAccount.platform == adapter.platform,
                    CreatorPlatformAccount.handle == identifier,
                )
            )
            if not existing.scalar_one_or_none():
                session.add(CreatorPlatformAccount(
                    creator_id=creator.id,
                    platform=adapter.platform,
                    handle=identifier,
                ))

            collector = AcquisitionCollector(adapter, session)
            run = await collector.collect_creator_data(identifier, creator.id)
            logger.info(
                "[%s/%s] Persisted — ResearchRun id=%s status=%s",
                adapter.platform,
                identifier,
                run.id,
                run.status,
            )

        creator.status = CreatorStatus.COLLECTED
        await session.commit()

    await engine.dispose()
    logger.info("All results persisted to database.")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CORP adapters (Reddit, TikTok, Instagram) together.",
    )
    parser.add_argument("--reddit", nargs="+", metavar="SUBREDDIT",
                        help="Subreddit name(s) to collect, e.g. creatoreconomy")
    parser.add_argument("--tiktok", nargs="+", metavar="HANDLE",
                        help="TikTok username(s), e.g. @creatorname")
    parser.add_argument("--instagram", nargs="+", metavar="USERNAME",
                        help="Instagram username(s), e.g. creatorname")
    parser.add_argument("--max-posts", type=int, default=20,
                        help="Max posts/videos per source (default: 20)")
    parser.add_argument("--max-comments", type=int, default=50,
                        help="Max comments per post (default: 50)")
    parser.add_argument("--persist", action="store_true",
                        help="Persist results to the CORP database")
    parser.add_argument("--creator-name", type=str,
                        help="Creator name for DB persistence (required with --persist)")
    parser.add_argument("--output", type=str, metavar="FILE",
                        help="Write raw results as JSON to a file")

    args = parser.parse_args()

    if not (args.reddit or args.tiktok or args.instagram):
        parser.error("Provide at least one of --reddit, --tiktok, or --instagram")

    if args.persist and not args.creator_name:
        parser.error("--creator-name is required when using --persist")

    pairs = build_adapters(args)
    logger.info("Running %d collection job(s) ...", len(pairs))

    all_results: list[tuple[SourceAdapter, str, list[NormalizedContent]]] = []
    for adapter, identifier in pairs:
        items = await run_adapter(adapter, identifier)
        all_results.append((adapter, identifier, items))

    total = sum(len(items) for _, _, items in all_results)
    logger.info("Grand total: %d items across %d sources", total, len(all_results))

    if args.output:
        output_data = []
        for adapter, identifier, items in all_results:
            for item in items:
                output_data.append(item.model_dump(mode="json"))
        Path(args.output).write_text(json.dumps(output_data, indent=2, default=str))
        logger.info("Wrote %d items to %s", len(output_data), args.output)

    if args.persist:
        await persist_results(all_results, args.creator_name)


if __name__ == "__main__":
    asyncio.run(main())
