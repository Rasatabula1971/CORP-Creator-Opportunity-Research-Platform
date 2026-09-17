"""Best-effort mirror of Postgres bulk rows into the SQLite warm store.

Every function is fire-and-forget: if the warm store is unreachable
(flash drive unplugged, path missing), it logs a warning and returns.
Pipelines never fail because of a warm-store error.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from corp.warmstore.store import WarmStore

logger = logging.getLogger(__name__)

_store: WarmStore | None = None


def _get_store() -> WarmStore | None:
    global _store
    if _store is not None:
        return _store
    try:
        from corp.config import settings
        _store = WarmStore(settings.warm_store_path)
        return _store
    except Exception:
        logger.warning("warm store unavailable", exc_info=True)
        return None


def model_to_dict(instance: object) -> dict[str, Any]:
    """Extract column values from a SQLAlchemy ORM instance as a plain dict."""
    table = instance.__class__.__table__
    result: dict[str, Any] = {}
    for col in table.columns:
        val = getattr(instance, col.key, None)
        if hasattr(val, "value"):
            val = val.value
        result[col.key] = val
    return result


def embedding_to_bytes(emb: Any) -> bytes | None:
    """Serialize an observation embedding for the warm store's BLOB column.

    The ORM value is a pgvector ``Vector``: a ``list[float]`` right after the
    cluster pipeline assigns it, or a ``numpy.ndarray`` once loaded from
    Postgres. Both are stored as little-endian float32; read back with
    ``np.frombuffer(blob, dtype="<f4")``.
    """
    if emb is None or isinstance(emb, bytes):
        return emb
    return np.asarray(emb, dtype="<f4").tobytes()


async def mirror_evidence(rows: list) -> None:
    store = _get_store()
    if store is None:
        return
    try:
        await store.init_db()
        await store.put_evidence([model_to_dict(r) for r in rows])
    except Exception:
        logger.warning("warm mirror failed: evidence (%d rows)", len(rows), exc_info=True)


async def mirror_observations(rows: list) -> None:
    store = _get_store()
    if store is None:
        return
    try:
        await store.init_db()
        dicts = []
        for r in rows:
            d = model_to_dict(r)
            d["embedding"] = embedding_to_bytes(getattr(r, "embedding", None))
            dicts.append(d)
        await store.put_observations(dicts)
    except Exception:
        logger.warning("warm mirror failed: observations (%d rows)", len(rows), exc_info=True)


async def mirror_content_items(rows: list) -> None:
    store = _get_store()
    if store is None:
        return
    try:
        await store.init_db()
        await store.put_content_items([model_to_dict(r) for r in rows])
    except Exception:
        logger.warning("warm mirror failed: content_items (%d rows)", len(rows), exc_info=True)


async def mirror_interactions(rows: list) -> None:
    store = _get_store()
    if store is None:
        return
    try:
        await store.init_db()
        await store.put_interactions([model_to_dict(r) for r in rows])
    except Exception:
        logger.warning("warm mirror failed: interactions (%d rows)", len(rows), exc_info=True)


async def mirror_metrics(rows: list) -> None:
    store = _get_store()
    if store is None:
        return
    try:
        await store.init_db()
        await store.put_metrics([model_to_dict(r) for r in rows])
    except Exception:
        logger.warning("warm mirror failed: metrics (%d rows)", len(rows), exc_info=True)


async def mirror_research_queries(rows: list) -> None:
    store = _get_store()
    if store is None:
        return
    try:
        await store.init_db()
        await store.put_research_queries([model_to_dict(r) for r in rows])
    except Exception:
        logger.warning("warm mirror failed: research_queries (%d rows)", len(rows), exc_info=True)


async def mirror_scores(
    creator_scores: list | None = None,
    opportunity_scores: list | None = None,
) -> None:
    store = _get_store()
    if store is None:
        return
    try:
        await store.init_db()
        if creator_scores:
            await store.put_creator_scores([model_to_dict(r) for r in creator_scores])
        if opportunity_scores:
            await store.put_opportunity_scores([model_to_dict(r) for r in opportunity_scores])
    except Exception:
        logger.warning("warm mirror failed: scores", exc_info=True)
