"""Source health tracker — circuit breaker for tolerated adapters.

Tracks per-adapter success/failure rates. After consecutive failures exceed
a threshold, the source is marked ``degraded``; after further failures it
becomes ``disconnected`` and is skipped in discovery runs. A disconnected
source gets one probe attempt after a cooldown period to check recovery.
This is the spec's "monitored, and after continued no response they are
disconnected" behaviour.

State is persisted as JSON under ``CORP_DATA_PATH/adapter_health.json``.
This is operational state, not research data — loss is non-critical, but
the write is atomic (tmp file + ``os.replace``) so a crash mid-write cannot
leave truncated JSON that ``load()`` would swallow, silently resetting every
source to healthy.

The tracker is consumed by :class:`~corp.workers.intelligence.niche_discovery
.RecursiveNicheDiscovery`, which is constructed fresh per job and per watch
re-scan — so the tracker must outlive it, or consecutive-failure counts
would reset before a breaker could ever trip. Use :func:`get_shared_tracker`
rather than constructing one per engine.
"""

import asyncio
import functools
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from corp.workers.failures import describe_failure

logger = logging.getLogger(__name__)

DEFAULT_DEGRADE_AFTER = 3
DEFAULT_DISCONNECT_AFTER = 6
DEFAULT_PROBE_COOLDOWN_SECONDS = 3600.0


class SourceStatus:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


@dataclass
class SourceHealthRecord:
    platform: str
    status: str = SourceStatus.HEALTHY
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error: str | None = None
    disconnected_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceHealthRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SourceHealthTracker:
    """Tracks adapter health and implements circuit-breaker logic.

    Usage::

        tracker = SourceHealthTracker(data_path)
        tracker.load()

        if tracker.is_available("appstore"):
            try:
                items = await adapter.collect(query)
                tracker.record_success("appstore")
            except Exception as exc:
                tracker.record_failure("appstore", exc)

        tracker.save()
    """

    def __init__(
        self,
        data_path: str | Path,
        degrade_after: int = DEFAULT_DEGRADE_AFTER,
        disconnect_after: int = DEFAULT_DISCONNECT_AFTER,
        probe_cooldown: float = DEFAULT_PROBE_COOLDOWN_SECONDS,
    ) -> None:
        self._path = Path(data_path) / "adapter_health.json"
        self._degrade_after = degrade_after
        self._disconnect_after = disconnect_after
        self._probe_cooldown = probe_cooldown
        self._records: dict[str, SourceHealthRecord] = {}

    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for platform, record_data in data.items():
                self._records[platform] = SourceHealthRecord.from_dict(record_data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load health state: %s", exc)

    def save(self) -> None:
        """Atomically replace the state file. A partial write would be read
        back as corrupt JSON and swallowed by ``load()``, which resets every
        source to healthy — so the rename, not the write, is what publishes.

        The temp name is unique per *writer*, not per process: ``save_async``
        hands this to ``asyncio.to_thread``, and two concurrent fan-outs in
        one process (a job and the R12 re-scan tick) would otherwise have two
        real threads writing the same temp path — truncating each other and
        publishing interleaved bytes, i.e. exactly the corruption this method
        exists to prevent. ``fsync`` before the rename so the durability claim
        holds through an OS crash, not just a process crash."""
        tmp: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {p: r.to_dict() for p, r in self._records.items()},
                indent=2,
            )
            tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
            tmp = None
        except OSError as exc:
            logger.warning("Could not save health state: %s", exc)
        finally:
            # A failed replace (Windows: destination held open by a scanner)
            # would otherwise orphan one temp file per attempt.
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    async def save_async(self) -> None:
        """``save()`` off the event loop — callers are async pipelines."""
        await asyncio.to_thread(self.save)

    def _get(self, platform: str) -> SourceHealthRecord:
        if platform not in self._records:
            self._records[platform] = SourceHealthRecord(platform=platform)
        return self._records[platform]

    def record_success(self, platform: str) -> None:
        rec = self._get(platform)
        rec.consecutive_failures = 0
        rec.total_successes += 1
        rec.last_success_at = time.time()
        if rec.status != SourceStatus.HEALTHY:
            logger.info("Source %s recovered to healthy", platform)
        rec.status = SourceStatus.HEALTHY
        rec.disconnected_at = None

    def record_failure(self, platform: str, exc: BaseException) -> None:
        rec = self._get(platform)
        rec.consecutive_failures += 1
        rec.total_failures += 1
        rec.last_failure_at = time.time()
        rec.last_error = describe_failure(exc)

        if rec.consecutive_failures >= self._disconnect_after:
            if rec.status != SourceStatus.DISCONNECTED:
                logger.warning(
                    "Source %s disconnected after %d consecutive failures",
                    platform,
                    rec.consecutive_failures,
                )
            else:
                logger.info(
                    "Source %s probe failed; re-arming disconnect cooldown", platform
                )
            # Re-arm the cooldown on every failure at/over the threshold — including
            # a failed probe of an already-disconnected source. Setting it only on
            # the transition left disconnected_at in the past after the first
            # cooldown, so is_available() green-lit a probe on every subsequent run
            # and the breaker never throttled again.
            rec.disconnected_at = time.time()
            rec.status = SourceStatus.DISCONNECTED
        elif rec.consecutive_failures >= self._degrade_after:
            if rec.status == SourceStatus.HEALTHY:
                logger.warning(
                    "Source %s degraded after %d consecutive failures",
                    platform,
                    rec.consecutive_failures,
                )
            rec.status = SourceStatus.DEGRADED

    def is_available(self, platform: str) -> bool:
        rec = self._get(platform)
        if rec.status != SourceStatus.DISCONNECTED:
            return True
        if rec.disconnected_at is None:
            return False
        elapsed = time.time() - rec.disconnected_at
        if elapsed >= self._probe_cooldown:
            logger.info(
                "Source %s cooldown elapsed (%.0fs); allowing probe attempt",
                platform,
                elapsed,
            )
            return True
        return False

    def get_status(self, platform: str) -> str:
        return self._get(platform).status

    def get_record(self, platform: str) -> SourceHealthRecord:
        return self._get(platform)

    def summary(self) -> dict[str, dict[str, Any]]:
        return {p: r.to_dict() for p, r in self._records.items()}


# maxsize=None, not 1: keyed on the path, a size-1 cache would evict on every
# call if two paths ever alternated, silently handing each caller a freshly
# loaded tracker — the per-instance failure mode this singleton exists to
# avoid, with nothing failing loudly to reveal it.
@functools.cache
def _shared_tracker(data_path: str) -> SourceHealthTracker:
    tracker = SourceHealthTracker(data_path)
    tracker.load()
    return tracker


def get_shared_tracker(data_path: str | None = None) -> SourceHealthTracker:
    """The process-wide tracker, loaded from disk once.

    Discovery engines are constructed per job and per watch re-scan; a
    per-engine tracker would reload a fresh copy each time and two live
    engines would last-writer-wins each other's counts. One instance per
    process keeps consecutive failures accumulating, which is the only way
    ``disconnect_after`` is ever reached. Single-process deployment is the
    assumption here (``start_corp.bat`` runs uvicorn with no ``--workers``),
    the same assumption ``JobRegistry`` already makes.
    """
    from corp.config import settings

    return _shared_tracker(data_path or settings.corp_data_path)
