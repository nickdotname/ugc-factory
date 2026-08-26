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
from typing import Mapping

from pydantic import Field

from src.errors import ValidationError
from src.models import Model


class DayCount(Model):
    """One day's figure from a daily series."""

    day: date
    count: int = Field(ge=0)


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
