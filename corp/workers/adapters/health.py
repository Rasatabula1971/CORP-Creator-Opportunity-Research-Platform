"""Source health tracker — circuit breaker for tolerated adapters.

Tracks per-adapter success/failure rates. After consecutive failures exceed
a threshold, the source is marked ``degraded``; after further failures it
becomes ``disconnected`` and is skipped in multi-source runs. A disconnected
source gets one probe attempt after a cooldown period to check recovery.

State is persisted as JSON under ``CORP_DATA_PATH/adapter_health.json``.
This is operational state, not research data — loss is non-critical.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {p: r.to_dict() for p, r in self._records.items()},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not save health state: %s", exc)

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
        rec.last_error = str(exc)[:500]

        if rec.consecutive_failures >= self._disconnect_after:
            if rec.status != SourceStatus.DISCONNECTED:
                logger.warning(
                    "Source %s disconnected after %d consecutive failures",
                    platform,
                    rec.consecutive_failures,
                )
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
