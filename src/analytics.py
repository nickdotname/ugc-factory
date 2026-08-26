"""What the posting produced downstream, and what that join may claim.

Responsibility: model a product's acquisition figures, cache them, and line
them up against the days this repo posted. The transport that fetches them is
deliberately elsewhere — this module is pure, so the arithmetic can be tested
without a network and swapped for a different admin API without touching it.

**Why this exists at all.** Everything else here optimises for views, because
views were the only figure available. Views were never the goal. A hook
earning 1,400 views and no signups is worth less than one earning 200 that
converts, and until now nothing in the pipeline could tell those apart.

**The limit, stated once.** A daily signup count is product-wide. It carries
no referrer, no campaign tag and no per-post identifier, so it supports "did
the days we posted differ from the days we did not" and nothing finer.
Ranking a *hook* by signups would need per-post links — instrumentation on the
product side, not arithmetic on this one. ``correlate`` is about days for that
reason, and the naming is meant to keep anyone from reading more into it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

from pydantic import Field

from src.errors import ValidationError
from src.models import Model


class DayCount(Model):
    """One day's figure from a daily series."""

    day: date
    count: int = Field(ge=0)




class Labelled(Model):
    """A named magnitude — a search term, a school, a partner."""

    label: str
    value: float = 0.0


class CohortRow(Model):
    """One signup week, and how much of it was still active later."""

    week: date
    size: int = Field(default=0, ge=0)
    #: offset in weeks -> share of the cohort still active, 0..1
    rates: dict[int, float] = Field(default_factory=dict)


class CohortGrid(Model):
    """Signup cohorts by week, newest last."""

    rows: tuple[CohortRow, ...] = ()

    @property
    def max_offset(self) -> int:
        return max((o for r in self.rows for o in r.rates), default=0)



class Overview(Model):
    """The slice of an acquisition report this repo actually uses.

    Deliberately not the whole payload. A source may also return retention,
    demographics and marketplace stats; modelling fields nothing reads would
    mean this file changes every time the upstream API grows one.
    """

    range_from: date
    range_to: date
    users: int = Field(default=0, ge=0)
    signups: int = Field(default=0, ge=0)
    signups_by_day: tuple[DayCount, ...] = ()

    #: The other daily series the same call returns. Kept because the question
    #: "did posting move anything" is not only about signups — a day that
    #: brought no signups but lifted DAU or projects still did something.
    dau_by_day: tuple[DayCount, ...] = ()
    swipes_by_day: tuple[DayCount, ...] = ()
    projects_by_day: tuple[DayCount, ...] = ()
    #: Runs far wider than the requested window, so it is the one series that
    #: can show posting against the product's whole history.
    new_users_by_day: tuple[DayCount, ...] = ()

    #: Scalar blocks, held as plain maps. Modelling each field would mean this
    #: file changes whenever the product adds a metric it already computes.
    funnel: dict[str, float] = Field(default_factory=dict)
    swipe_funnel: dict[str, float] = Field(default_factory=dict)
    retention: dict[str, float] = Field(default_factory=dict)
    engagement: dict[str, float] = Field(default_factory=dict)
    marketplace: dict[str, float] = Field(default_factory=dict)
    supply: dict[str, float] = Field(default_factory=dict)
    totals: dict[str, float] = Field(default_factory=dict)

    age_dist: tuple[Labelled, ...] = ()
    school_dist: tuple[Labelled, ...] = ()
    top_searches: tuple[Labelled, ...] = ()

    @property
    def by_day(self) -> dict[date, int]:
        return {row.day: row.count for row in self.signups_by_day}


class AnalyticsCache(Model):
    """Every report fetched, oldest first.

    Whole fetches rather than a merged day->count map, because a source can
    restate a day: a deleted account, or a late-arriving row. Keeping the
    fetches makes the restatement visible instead of silently overwriting what
    was believed yesterday.
    """

    fetches: list[Overview] = Field(default_factory=list)

    def latest_by_day(self) -> dict[date, int]:
        """Newest reported figure for each day, across every fetch."""
        merged: dict[date, int] = {}
        for overview in self.fetches:
            merged.update(overview.by_day)
        return merged


class ProductAnalytics(ABC):
    """Somewhere acquisition figures can be read from.

    The seam matches ``Publisher`` and ``MediaStore`` (SPEC §2.2): a second
    product's admin API becomes a new class rather than an edit to the CLI.
    """

    @abstractmethod
    def overview(self, since: date, until: date) -> Overview:
        """Acquisition figures covering ``[since, until]`` inclusive."""

    @abstractmethod
    def scopes(self) -> dict[str, object]:
        """What this credential can reach, for a readable failure up front."""


def cache_path(campaign_dir: Path) -> Path:
    return campaign_dir / "analytics.json"


def load_cache(path: Path) -> AnalyticsCache:
    if not path.is_file():
        return AnalyticsCache()
    try:
        return AnalyticsCache.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"{path} is not a readable analytics cache: {exc}") from exc


def save_cache(path: Path, cache: AnalyticsCache) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cache.model_dump_json(indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class DayJoin:
    """One day, with what went out and what came back."""

    day: date
    posts: int
    views: float
    signups: int

    @property
    def views_per_signup(self) -> float | None:
        """Views spent per signup, or None when nothing converted.

        None rather than infinity: a day with reach and no signups has an
        *undefined* cost per signup, and charting it as a huge number would
        dominate every average it touched.
        """
        return self.views / self.signups if self.signups else None


def correlate(
    posts_by_day: Mapping[date, int],
    views_by_day: Mapping[date, float],
    signups_by_day: Mapping[date, int],
) -> list[DayJoin]:
    """Line posting up against signups, day by day.

    A join, not an attribution — see the module docstring. Days present in
    only one source are kept: a day with signups and no posting is the control,
    and dropping it would delete the comparison this is for.
    """
    days = sorted({*posts_by_day, *views_by_day, *signups_by_day})
    return [
        DayJoin(
            day=day,
            posts=posts_by_day.get(day, 0),
            views=views_by_day.get(day, 0.0),
            signups=signups_by_day.get(day, 0),
        )
        for day in days
    ]


def default_range(today: date, days: int = 30) -> tuple[date, date]:
    """The trailing ``days`` ending today, inclusive at both ends."""
    if days < 1:
        raise ValidationError("range must cover at least one day")
    return today - timedelta(days=days - 1), today


def range_from_clock(now: datetime, days: int = 30) -> tuple[date, date]:
    """``default_range`` off an injected clock's instant (SPEC §2.2)."""
    return default_range(now.date(), days)

def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Correlation, or None when it would be meaningless.

    None below three pairs, and None when either side is constant — a flat
    series has no covariance to share, and returning 0.0 would read as
    "measured, no relationship" rather than "not measurable".
    """
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    if dx <= 0 or dy <= 0:
        return None
    return float(num / ((dx * dy) ** 0.5))


@dataclass(frozen=True)
class Lag:
    """How well one day's reach lines up with a later day's outcome."""

    days: int
    r: float | None
    n: int


def lag_scan(
    cause_by_day: Mapping[date, float],
    effect_by_day: Mapping[date, int],
    max_lag: int = 7,
) -> list[Lag]:
    """Correlate a driver against an outcome at each offset, 0..``max_lag``.

    Short-form video is not a same-day medium: someone watches, does nothing,
    and comes back. A same-day correlation alone would therefore understate a
    real effect and could easily invert its sign.

    This finds *where* the alignment is, not whether it is causal. With a few
    weeks of days, every one of these is noisy — ``n`` rides along with each
    point so a reader can see how thin the evidence is, and a peak that moves
    every time the data refreshes is noise rather than a discovery.
    """
    days = sorted(set(cause_by_day) & {d for d in effect_by_day})
    out: list[Lag] = []
    for lag in range(max_lag + 1):
        pairs = [
            (cause_by_day[d], effect_by_day[d + timedelta(days=lag)])
            for d in days
            if d in cause_by_day and (d + timedelta(days=lag)) in effect_by_day
        ]
        xs = [p[0] for p in pairs]
        ys = [float(p[1]) for p in pairs]
        out.append(Lag(days=lag, r=pearson(xs, ys), n=len(pairs)))
    return out


#: Monday-first, matching date.weekday().
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def by_weekday(series: Mapping[date, float]) -> list[tuple[str, float, int]]:
    """Mean value per weekday, with the count behind each mean.

    The count matters: over a month each weekday has four or five observations,
    and a difference between two of them is usually nothing.
    """
    buckets: dict[int, list[float]] = {i: [] for i in range(7)}
    for day, value in series.items():
        buckets[day.weekday()].append(float(value))
    return [
        (
            WEEKDAYS[i],
            (sum(buckets[i]) / len(buckets[i]) if buckets[i] else 0.0),
            len(buckets[i]),
        )
        for i in range(7)
    ]
