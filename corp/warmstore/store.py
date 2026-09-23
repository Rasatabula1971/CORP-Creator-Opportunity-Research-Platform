"""WarmStore — async SQLite store for bulk CORP data.

Provides idempotent put/get operations for the 8 warm tables.  Pipelines
write to both Postgres and the warm store; the web dashboard reads only
from Postgres, so the flash drive is optional at query time.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Table, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from corp.warmstore.schema import (
    ALL_TABLES,
    audience_interactions,
    content_items,
    creator_scores,
    evidence,
    metadata,
    metrics_snapshots,
    opportunity_scores,
    problem_observations,
    research_queries,
)

_JSON_COLUMNS = frozenset({
    "topics", "extra", "tags", "component_scores", "diagnostics",
})

_DATETIME_COLUMNS = frozenset({
    "collected_at", "captured_at", "executed_at", "published_at",
    "posted_at", "superseded_at", "created_at", "updated_at", "extracted_at",
})


def _prep(row: dict[str, Any]) -> dict[str, Any]:
    """Serialize JSON-typed values, datetime strings, and enum instances for SQLite."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k in _JSON_COLUMNS and v is not None and not isinstance(v, str):
            out[k] = json.dumps(v)
        elif k in _DATETIME_COLUMNS and isinstance(v, datetime):
            out[k] = v.isoformat()
        elif k in _DATETIME_COLUMNS and isinstance(v, str):
            out[k] = v  # already an ISO-8601 string
        elif hasattr(v, "value"):
            out[k] = v.value if isinstance(v.value, str) else str(v.value)
        else:
            out[k] = v
    return out


class WarmStore:
    """Async SQLite store for bulk CORP data (evidence, embeddings, content)."""

    _project_root = Path(__file__).resolve().parents[2]

    def __init__(self, db_path: str | Path) -> None:
        p = Path(db_path)
        self._path = p if p.is_absolute() else self._project_root / p
        self._engine: AsyncEngine | None = None
        self._schema_ready = False

    @property
    def path(self) -> Path:
        return self._path

    async def _get_engine(self) -> AsyncEngine:
        if self._engine is None:
            # Create only the DB's own directory, never the tree above it. With
            # parents=True, an unmounted external drive (e.g. /mnt/flash missing)
            # got a fresh empty warm store fabricated on the root filesystem,
            # which then shadows the real mount and splits rows across two DBs.
            # Without parents=True, a missing parent tree raises FileNotFoundError,
            # which the fire-and-forget mirror in sync.py logs and skips — matching
            # its "path missing -> log and return" contract.
            self._path.parent.mkdir(exist_ok=True)
            self._engine = create_async_engine(
                f"sqlite+aiosqlite:///{self._path}",
                echo=False,
            )
        return self._engine

    async def init_db(self) -> None:
        """Create all warm-store tables (idempotent), then heal column drift.

        ``metadata.create_all`` only creates tables that don't exist yet — an
        existing SQLite file predating a schema.py column addition (e.g. the
        extraction-stamp or tier-2 columns) keeps its old shape forever and
        every mirror write into it raises OperationalError. Since this store
        is a disposable bulk mirror (Postgres is the source of truth; see
        module docstring), it's safe to widen it in place: add whatever
        columns the current schema has that the on-disk table doesn't.
        """
        if self._schema_ready:
            return
        engine = await self._get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            for table in ALL_TABLES:
                # Table names come only from ALL_TABLES metadata, never user input.
                result = await conn.execute(
                    text(f"PRAGMA table_info([{table.name}])")  # nosemgrep
                )
                existing = {row[1] for row in result.fetchall()}
                for col in table.columns:
                    if col.name in existing:
                        continue
                    ddl = f"ALTER TABLE [{table.name}] ADD COLUMN [{col.name}] {col.type}"
                    # table/column/type are SQLAlchemy schema metadata, never external input.
                    await conn.execute(text(ddl))  # nosemgrep
        self._schema_ready = True

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    # ------------------------------------------------------------------
    # Generic put — INSERT OR REPLACE for idempotent writes
    # ------------------------------------------------------------------

    async def _put(self, table: Table, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        engine = await self._get_engine()
        prepped = [_prep(r) for r in rows]
        async with engine.begin() as conn:
            for row in prepped:
                stmt = insert(table).prefix_with("OR REPLACE").values(**row)
                await conn.execute(stmt)
        return len(prepped)

    async def put_evidence(self, rows: list[dict[str, Any]]) -> int:
        return await self._put(evidence, rows)

    async def put_observations(self, rows: list[dict[str, Any]]) -> int:
        return await self._put(problem_observations, rows)

    async def put_content_items(self, rows: list[dict[str, Any]]) -> int:
        return await self._put(content_items, rows)

    async def put_interactions(self, rows: list[dict[str, Any]]) -> int:
        return await self._put(audience_interactions, rows)

    async def put_metrics(self, rows: list[dict[str, Any]]) -> int:
        return await self._put(metrics_snapshots, rows)

    async def put_research_queries(self, rows: list[dict[str, Any]]) -> int:
        return await self._put(research_queries, rows)

    async def put_creator_scores(self, rows: list[dict[str, Any]]) -> int:
        return await self._put(creator_scores, rows)

    async def put_opportunity_scores(self, rows: list[dict[str, Any]]) -> int:
        return await self._put(opportunity_scores, rows)

    # ------------------------------------------------------------------
    # Read helpers — return dicts keyed by primary ID
    # ------------------------------------------------------------------

    async def get_evidence_text(self, ids: list[str]) -> dict[str, str]:
        """Return {id: raw_text} for the given evidence IDs."""
        if not ids:
            return {}
        engine = await self._get_engine()
        result: dict[str, str] = {}
        async with engine.connect() as conn:
            for i in range(0, len(ids), 500):
                batch = ids[i : i + 500]
                rows = await conn.execute(
                    select(evidence.c.id, evidence.c.raw_text).where(
                        evidence.c.id.in_(batch)
                    )
                )
                for row in rows:
                    result[row.id] = row.raw_text
        return result

    async def get_observation_embeddings(self, ids: list[str]) -> dict[str, bytes]:
        """Return {id: embedding_bytes} for the given observation IDs."""
        if not ids:
            return {}
        engine = await self._get_engine()
        result: dict[str, bytes] = {}
        async with engine.connect() as conn:
            for i in range(0, len(ids), 500):
                batch = ids[i : i + 500]
                rows = await conn.execute(
                    select(
                        problem_observations.c.id,
                        problem_observations.c.embedding,
                    ).where(
                        problem_observations.c.id.in_(batch),
                        problem_observations.c.embedding.is_not(None),
                    )
                )
                for row in rows:
                    result[row.id] = row.embedding
        return result

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def count_rows(self) -> dict[str, int]:
        """Return {table_name: row_count} for every warm table."""
        engine = await self._get_engine()
        counts: dict[str, int] = {}
        async with engine.connect() as conn:
            for table in ALL_TABLES:
                result = await conn.execute(
                    select(func.count()).select_from(table)
                )
                counts[table.name] = result.scalar() or 0
        return counts

    async def export_jsonl(self, out_dir: str | Path) -> dict[str, int]:
        """Export every table to a JSONL file under out_dir. Returns row counts."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        engine = await self._get_engine()
        exported: dict[str, int] = {}
        async with engine.connect() as conn:
            for table in ALL_TABLES:
                rows = await conn.execute(select(table))
                count = 0
                path = out / f"{table.name}.jsonl"
                with open(path, "w") as f:
                    for row in rows:
                        record = dict(row._mapping)
                        for k, v in record.items():
                            if isinstance(v, bytes):
                                record[k] = v.hex()
                        f.write(json.dumps(record, default=str) + "\n")
                        count += 1
                exported[table.name] = count
        return exported
