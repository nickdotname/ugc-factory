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
from enum import Enum
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


class Scope(str, Enum):
    """What window a snapshot covers.

    The distinction matters more than it looks: snapshots are *aggregates over
    a window*, not daily increments. Two rolling snapshots taken a day apart
    overlap by 29 days, so adding them up would count almost everything twice.
    Lifetime totals therefore need their own query, not arithmetic over the
    rolling series.
    """

    #: A trailing window — good for "how are we doing lately".
    ROLLING = "rolling"
    #: Everything since the campaign began.
    LIFETIME = "lifetime"


class Snapshot(BaseModel):
    """Metrics for one campaign over one window, as of one moment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Local date the snapshot was taken; one snapshot per campaign per day.
    date: str
    # Defaulted so metrics files written before scopes existed still load;
    # everything recorded then was a 30-day rolling window.
    scope: Scope = Scope.ROLLING
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
        """Replace today's snapshot for this scope, or append it.

        Keyed on (date, scope): a lifetime and a rolling snapshot from the same
        day are different measurements and must not overwrite each other.
        """
        for index, existing in enumerate(self.snapshots):
            if existing.date == snapshot.date and existing.scope is snapshot.scope:
                self.snapshots[index] = snapshot
                break
        else:
            self.snapshots.append(snapshot)
        self.snapshots.sort(key=lambda s: (s.date, s.scope.value))

    def of(self, scope: Scope) -> list[Snapshot]:
        return [s for s in self.snapshots if s.scope is scope]

    def latest(self, scope: Scope = Scope.ROLLING) -> Snapshot | None:
        snaps = self.of(scope)
        return snaps[-1] if snaps else None

    def lifetime(self) -> Snapshot | None:
        """Totals since the campaign began, or None if never fetched."""
        return self.latest(Scope.LIFETIME)

    def series(
        self, metric_type: str, scope: Scope = Scope.ROLLING
    ) -> list[tuple[str, float]]:
        """(date, value) pairs for one metric, for charting."""
        return [(s.date, s.get(metric_type)) for s in self.of(scope)]

    def change(
        self, metric_type: str, days: int = 7, scope: Scope = Scope.ROLLING
    ) -> float | None:
        """Percent change over the last ``days`` snapshots, or None.

        Returns None rather than 0 when there is no baseline — "no data yet"
        and "no change" are different claims and a dashboard must not conflate
        them.
        """
        snaps = self.of(scope)
        if len(snaps) < 2:
            return None
        recent = snaps[-1].get(metric_type)
        index = max(0, len(snaps) - 1 - days)
        baseline = snaps[index].get(metric_type)
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


def lifetime_window(
    now: datetime, first_post: datetime | None = None
) -> tuple[datetime, datetime]:
    """The window covering everything the campaign has ever posted.

    Starts a day before the first recorded post so nothing is clipped by
    timezone rounding, and falls back to a year when there is no history yet.
    """
    end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if first_post is None:
        return end - timedelta(days=365), end
    return first_post.replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=1), end


def default_window(now: datetime, days: int = 30) -> tuple[datetime, datetime]:
    """The aggregation window to request.

    Buffer's input documents UTC midnight boundaries, so the window is snapped
    to whole days; a partial trailing day would make consecutive snapshots
    incomparable.
    """
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=days), end
