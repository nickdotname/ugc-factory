"""Performance metrics: fetch on a schedule, cache, read cheaply.

Responsibility: turn Buffer's aggregated post metrics into a dated time series
committed to the repo, so the dashboard can show trends without touching the
API.

**Why cached rather than live.** Buffer's free plan allows 3,000 API requests
per 30 days, and posting three campaigns at 24/day already spends ~2,700 of
them. A dashboard that queried on page load would exhaust the remainder in an
afternoon and stop the posting it exists to measure. One scheduled fetch per
campaign per day costs 90/month and leaves the posting budget intact.

The cache is append-only per day: each run overwrites *today's* snapshot and
leaves prior days alone, so re-running is safe and the series still accumulates
into a trend the API itself does not offer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.errors import ValidationError


class Metric(BaseModel):
    """One measured value, named as the backend reports it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Matches Buffer's ``PostMetricType`` enum (impressions, reach, likes, …).
    type: str
    name: str
    value: float
    #: ``count`` or ``percentage`` — a percentage must never be summed.
    unit: str = "count"

    @property
    def is_percentage(self) -> bool:
        return self.unit == "percentage"


class Snapshot(BaseModel):
    """Metrics for one campaign over one window, as of one moment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Local date the snapshot was taken; one snapshot per campaign per day.
    date: str
    fetched_at: datetime
    window_start: datetime
    window_end: datetime
    service: str
    metrics: list[Metric] = Field(default_factory=list)
    #: Buffer's own freshness marker. Networks report metrics on a lag, so a
    #: snapshot can be newer than the data inside it.
    metrics_updated_at: datetime | None = None

    def get(self, metric_type: str) -> float:
        for metric in self.metrics:
            if metric.type == metric_type:
                return metric.value
        return 0.0

    @property
    def post_count(self) -> int:
        return int(self.get("postCount"))


class MetricsHistory(BaseModel):
    """Every snapshot taken for a campaign, oldest first."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    snapshots: list[Snapshot] = Field(default_factory=list)

    def upsert(self, snapshot: Snapshot) -> None:
        """Replace today's snapshot, or append it.

        Re-running on the same day refreshes rather than duplicating, which
        matters because network metrics keep moving for days after a post.
        """
        for index, existing in enumerate(self.snapshots):
            if existing.date == snapshot.date:
                self.snapshots[index] = snapshot
                break
        else:
            self.snapshots.append(snapshot)
        self.snapshots.sort(key=lambda s: s.date)

    def latest(self) -> Snapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def series(self, metric_type: str) -> list[tuple[str, float]]:
        """(date, value) pairs for one metric, for charting."""
        return [(s.date, s.get(metric_type)) for s in self.snapshots]

    def change(self, metric_type: str, days: int = 7) -> float | None:
        """Percent change over the last ``days`` snapshots, or None.

        Returns None rather than 0 when there is no baseline — "no data yet"
        and "no change" are different claims and a dashboard must not conflate
        them.
        """
        if len(self.snapshots) < 2:
            return None
        recent = self.snapshots[-1].get(metric_type)
        index = max(0, len(self.snapshots) - 1 - days)
        baseline = self.snapshots[index].get(metric_type)
        if baseline == 0:
            return None
        return (recent - baseline) / baseline * 100.0


def load_metrics(path: Path) -> MetricsHistory:
    """Read a campaign's metrics cache, or return an empty one."""
    if not path.is_file():
        return MetricsHistory()
    try:
        return MetricsHistory.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        # Unlike the queue, a corrupt metrics cache is not dangerous — nothing
        # publishes off it — but silently discarding history would hide the
        # corruption, so it still fails loud.
        raise ValidationError(f"{path} is not a valid metrics file: {exc}") from exc


def save_metrics(path: Path, history: MetricsHistory) -> None:
    from src.queue import _atomic_write

    _atomic_write(path, history.model_dump_json(indent=2) + "\n")


def default_window(now: datetime, days: int = 30) -> tuple[datetime, datetime]:
    """The aggregation window to request.

    Buffer's input documents UTC midnight boundaries, so the window is snapped
    to whole days; a partial trailing day would make consecutive snapshots
    incomparable.
    """
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=days), end
