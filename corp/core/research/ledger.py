"""Research query ledger — the persistence service for ResearchQuery (§13).

Two operations: record an executed query under its run, and look up what has
been searched before by run, source and/or exact query text. Exact text only;
semantic/equivalent-query matching and cooldown heuristics are later slices.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from corp.core.models.research_query import ResearchQuery, ResearchQueryStatus


async def record_query(
    session: AsyncSession,
    *,
    research_run_id: str,
    source: str,
    query: str,
    results_seen: int = 0,
    new_results: int = 0,
    duplicate_results: int = 0,
    archive_reference: str | None = None,
    status: ResearchQueryStatus = ResearchQueryStatus.SUCCEEDED,
    error: str | None = None,
    executed_at: datetime | None = None,
) -> ResearchQuery:
    row = ResearchQuery(
        research_run_id=research_run_id,
        source=source,
        query=query,
        executed_at=executed_at or datetime.now(UTC),
        results_seen=results_seen,
        new_results=new_results,
        duplicate_results=duplicate_results,
        archive_reference=archive_reference,
        status=status,
        error=error,
    )
    session.add(row)
    await session.flush()
    return row


async def find_queries(
    session: AsyncSession,
    *,
    research_run_id: str | None = None,
    source: str | None = None,
    query: str | None = None,
) -> list[ResearchQuery]:
    """Previous executions matching every given filter, newest first.

    Passing ``source`` and ``query`` together answers "has this exact query
    been run against this source before, and what did it yield each time?"
    """
    stmt = select(ResearchQuery)
    if research_run_id is not None:
        stmt = stmt.where(ResearchQuery.research_run_id == research_run_id)
    if source is not None:
        stmt = stmt.where(ResearchQuery.source == source)
    if query is not None:
        stmt = stmt.where(ResearchQuery.query == query)
    stmt = stmt.order_by(ResearchQuery.executed_at.desc(), ResearchQuery.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())
