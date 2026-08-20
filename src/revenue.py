"""What the posting actually earned, and how that compares to reach.

Responsibility: hold a dated ledger of money per campaign, and answer "how much
came in over this window" for any window — which is what makes a revenue-to-
views ratio meaningful rather than decorative.

**Why a ledger of periods rather than a daily number.** Money does not arrive
daily. A brand deal lands on one date, an affiliate payout covers a week, a
creator-fund payment covers a month. Forcing that into per-day rows would mean
inventing figures. Instead each entry names the span it covers, and any query
pro-rates it across that span. A monthly payment overlapping a 30-day window by
eleven days therefore contributes eleven thirtieths of itself — not all of it,
and not nothing.

**Why the window matters so much here.** ``metrics.json`` stores *aggregates
over a trailing window*, not daily increments (see ``metrics.Scope``). Views on
2026-08-19 means "views over the 30 days ending then". Dividing that by one
week's revenue would compare a month of reach against a week of money and
produce a number four times too small. So every ratio this module computes
pulls revenue from **the snapshot's own window**, which is the only pairing that
is apples to apples.

Revenue never comes from Buffer — it has no such data. It arrives either typed
in by a human or through a ``RevenueFetcher``.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import Field, field_validator

from src.errors import ValidationError
from src.models import Model

#: Filename inside a campaign directory.
LEDGER_FILE = "revenue.json"

#: Refuse a span longer than this; it is a typo, not a payout period.
MAX_PERIOD_DAYS = 400


class RevenueEntry(Model):
    """One sum of money and the span of time it covers."""

    #: Stable handle so the dashboard can delete a specific row. Generated
    #: rather than positional: an index shifts when an earlier row is removed.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    #: Inclusive, ISO ``YYYY-MM-DD``. A single-day entry has start == end.
    period_start: date
    period_end: date
    amount: float = Field(ge=0)
    currency: str = "USD"
    #: Free text: "brand deal", "affiliate", "creator fund". Kept as a label
    #: rather than an enum because the categories are the operator's, not ours.
    source: str = "manual"
    note: str | None = None
    entered_at: datetime | None = None

    @field_validator("currency")
    @classmethod
    def _iso_ish(cls, v: str) -> str:
        code = v.strip().upper()
        if not (code.isalpha() and len(code) == 3):
            raise ValueError(f"currency must be a 3-letter code, got {v!r}")
        return code

    def model_post_init(self, _: object) -> None:
        if self.period_end < self.period_start:
            raise ValueError(
                f"period ends before it starts: {self.period_start} → {self.period_end}"
            )
        if self.days > MAX_PERIOD_DAYS:
            raise ValueError(
                f"period spans {self.days} days, which is longer than any payout "
                f"period — check the dates"
            )

    @property
    def days(self) -> int:
        """Length of the span in days, counting both ends."""
        return (self.period_end - self.period_start).days + 1

    @property
    def per_day(self) -> float:
        return self.amount / self.days

    def overlap_days(self, start: date, end: date) -> int:
        """How many of this entry's days fall inside ``[start, end]``."""
        first = max(self.period_start, start)
        last = min(self.period_end, end)
        return max(0, (last - first).days + 1)

    def amount_in(self, start: date, end: date) -> float:
        """The pro-rated share of this entry attributable to a window."""
        return self.per_day * self.overlap_days(start, end)


class RevenueLedger(Model):
    """Every entry for one campaign. Append-mostly; nothing is aggregated away."""

    entries: tuple[RevenueEntry, ...] = Field(default_factory=tuple)

    @property
    def currencies(self) -> set[str]:
        return {e.currency for e in self.entries}

    def total_in(self, start: date, end: date) -> float:
        """Revenue attributable to a window, pro-rating any entry that straddles it."""
        return sum(e.amount_in(start, end) for e in self.entries)

    def total(self) -> float:
        return sum(e.amount for e in self.entries)

    def span(self) -> tuple[date, date] | None:
        """Earliest and latest dates the ledger covers."""
        if not self.entries:
            return None
        return (
            min(e.period_start for e in self.entries),
            max(e.period_end for e in self.entries),
        )

    def daily(self) -> list[tuple[str, float]]:
        """Pro-rated revenue per calendar day, ascending.

        Every entry is spread evenly across its own days, so a monthly payout
        shows as a low plateau rather than a spike on an arbitrary date. Honest
        about what is known: the total is right, the shape within a period is
        an assumption, and pretending otherwise would invent daily figures.
        """
        buckets: dict[date, float] = {}
        for entry in self.entries:
            for offset in range(entry.days):
                day = entry.period_start + timedelta(days=offset)
                buckets[day] = buckets.get(day, 0.0) + entry.per_day
        return [(d.isoformat(), round(v, 4)) for d, v in sorted(buckets.items())]

    def by_source(self) -> list[tuple[str, float]]:
        """Total per source label, largest first."""
        totals: dict[str, float] = {}
        for entry in self.entries:
            totals[entry.source] = totals.get(entry.source, 0.0) + entry.amount
        return sorted(totals.items(), key=lambda kv: -kv[1])

    def with_entry(self, entry: RevenueEntry) -> "RevenueLedger":
        ordered = sorted(
            (*self.entries, entry), key=lambda e: (e.period_start, e.period_end)
        )
        return RevenueLedger(entries=tuple(ordered))

    def without(self, entry_id: str) -> "RevenueLedger":
        return RevenueLedger(
            entries=tuple(e for e in self.entries if e.id != entry_id)
        )

    def double_counting(self) -> list[str]:
        """Same-source entries covering the same days.

        Two sources overlapping is normal — a brand deal during an affiliate
        week is two real payments. The same source twice over one day is a
        duplicate entry, and every total above is silently wrong until it is
        fixed, so it is reported rather than merged.
        """
        problems: list[str] = []
        by_source: dict[str, list[RevenueEntry]] = {}
        for entry in self.entries:
            by_source.setdefault(entry.source, []).append(entry)
        for source, group in by_source.items():
            ordered = sorted(group, key=lambda e: e.period_start)
            for earlier, later in zip(ordered, ordered[1:]):
                if later.period_start <= earlier.period_end:
                    problems.append(
                        f"two {source!r} entries cover "
                        f"{later.period_start}–{min(earlier.period_end, later.period_end)}; "
                        f"that revenue is counted twice"
                    )
        return problems


def ledger_path(campaign_dir: Path) -> Path:
    return campaign_dir / LEDGER_FILE


def load_ledger(path: Path) -> RevenueLedger:
    if not path.is_file():
        return RevenueLedger()
    try:
        return RevenueLedger.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        # Money is the one thing nobody wants silently zeroed by a parse error.
        raise ValidationError(f"{path} is not a valid revenue ledger: {exc}") from exc


def save_ledger(path: Path, ledger: RevenueLedger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = ledger.model_dump_json(indent=2) + "\n"
    handle, temp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def per_thousand(revenue: float, views: float) -> float | None:
    """Revenue per 1,000 views, or None when there is no reach to divide by.

    Returning None rather than 0.0 matters: a campaign with money and no
    recorded views has an *unknown* RPM, and charting it as zero would read as
    "earns nothing per view", which is the opposite of the truth.
    """
    if views <= 0:
        return None
    return revenue / views * 1000.0


class RevenueFetcher(ABC):
    """Somewhere revenue can be read from automatically.

    The seam exists so an external source — an admin panel's API, a payment
    processor — becomes a new class here rather than an edit to the dashboard,
    matching how ``MediaStore`` and ``Publisher`` are treated (SPEC §2.2).

    Nothing implements it yet: an implementation needs the endpoint, its auth
    scheme and its response shape, and guessing any of those would produce a
    class that fails at the first real call.
    """

    @abstractmethod
    def fetch(self, since: date, until: date) -> list[RevenueEntry]:
        """Revenue entries covering ``[since, until]``, as the source reports them."""
