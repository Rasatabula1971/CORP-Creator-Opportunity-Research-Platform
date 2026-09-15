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

from sqlalchemy import insert, select, text
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
    "topics", "extra", "component_scores", "diagnostics",
})

_DATETIME_COLUMNS = frozenset({
    "collected_at", "captured_at", "executed_at", "published_at",
    "posted_at", "superseded_at", "created_at", "updated_at",
})


def _prep(row: dict[str, Any]) -> dict[str, Any]:
    """Serialize JSON-typed values, datetime strings, and enum instances for SQLite."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k in _JSON_COLUMNS and v is not None and not isinstance(v, str):
            out[k] = json.dumps(v)
        elif k in _DATETIME_COLUMNS and isinstance(v, str):
            out[k] = datetime.fromisoformat(v)
        elif hasattr(v, "value"):
            out[k] = v.value if isinstance(v.value, str) else str(v.value)
        else:
            out[k] = v
    return out


class WarmStore:
    """Async SQLite store for bulk CORP data (evidence, embeddings, content)."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._engine: AsyncEngine | None = None

    @property
    def path(self) -> Path:
        return self._path

    async def _get_engine(self) -> AsyncEngine:
        if self._engine is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._engine = create_async_engine(
                f"sqlite+aiosqlite:///{self._path}",
                echo=False,
            )
        return self._engine

    async def init_db(self) -> None:
        """Create all warm-store tables (idempotent)."""
        engine = await self._get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    # ------------------------------------------------------------------
    # Generic put — INSERT OR REPLACE for idempotent writes
    # ------------------------------------------------------------------

    async def _put(self, table, rows: list[dict[str, Any]]) -> int:
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
                placeholders = ", ".join(f":id{j}" for j in range(len(batch)))
                params = {f"id{j}": eid for j, eid in enumerate(batch)}
                rows = await conn.execute(
                    text(f"SELECT id, raw_text FROM evidence WHERE id IN ({placeholders})"),
                    params,
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
                placeholders = ", ".join(f":id{j}" for j in range(len(batch)))
                params = {f"id{j}": oid for j, oid in enumerate(batch)}
                rows = await conn.execute(
                    text(
                        f"SELECT id, embedding FROM problem_observations "
                        f"WHERE id IN ({placeholders}) AND embedding IS NOT NULL"
                    ),
                    params,
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
                    text(f"SELECT COUNT(*) FROM [{table.name}]")
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
