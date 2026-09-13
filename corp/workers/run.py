"""Run an LLM-backed pipeline from the command line using the configured provider.

    python -m corp.workers.run intelligence <creator_id>
    python -m corp.workers.run intent [creator_id]
"""

import argparse
import asyncio
import logging
import sys

from corp.config import settings
from corp.workers.providers.factory import build_provider

logger = logging.getLogger(__name__)


async def _run(pipeline_name: str, creator_id: str | None) -> int:
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
        print(f"research_run={run.id} status={run.status} model={provider.model_name}")
        return 0 if run.status == "completed" else 1
    finally:
        close = getattr(provider, "close", None)
        if close is not None:
            await close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pipeline", choices=["intelligence", "intent"])
    parser.add_argument("creator_id", nargs="?")
    args = parser.parse_args(argv)
    logging.basicConfig(level=settings.log_level)
    return asyncio.run(_run(args.pipeline, args.creator_id))


if __name__ == "__main__":
    sys.exit(main())
