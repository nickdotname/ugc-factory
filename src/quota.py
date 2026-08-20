"""How much of Buffer's request allowance has actually been spent.

Responsibility: turn a per-run request count into a rolling 30-day total that
can be compared against the 3,000-request allowance the free plan gives.

**The bug this replaces.** ``_report_quota`` compared a *single run's* count
against 2,400 — a threshold meant for a *30-day* total. A top-up run makes tens
of requests, so the alarm could not fire under any circumstances. Silence read
as "plenty left" when it actually meant nothing was being measured.

**Why the tally is per campaign but the budget is not.** The allowance belongs
to the Buffer *account*, and several campaigns share one key: three campaigns
posting to three networks off ``BUFFER_API_KEY`` spend one pot. Counting per
campaign would understate the total threefold.

The obvious fix — one shared counter file — would race. Campaign workflows have
their own concurrency groups, so two can run at the same moment, and a
read-modify-write from both loses one of them. So each campaign writes only its
own file, and the total is summed across campaigns *when it is read*. No
contention, and the arithmetic is done where it can see everything.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from pydantic import Field

from src.errors import ValidationError
from src.models import Model

#: Filename inside a campaign directory.
QUOTA_FILE = "quota.json"

#: Buffer's free plan, per SPEC §3.
MONTHLY_ALLOWANCE = 3000

#: The window the allowance is measured over.
WINDOW_DAYS = 30

#: Kept a little longer than the window so a late run cannot lose a day that
#: is still inside it.
RETAIN_DAYS = 40


class QuotaLedger(Model):
    """Requests this campaign made, by local date."""

    days: dict[str, int] = Field(default_factory=dict)

    def total_since(self, first: date) -> int:
        total = 0
        for day, count in self.days.items():
            parsed = _parse(day)
            if parsed is not None and parsed >= first:
                total += count
        return total

    def with_run(self, day: date, count: int) -> "QuotaLedger":
        """Add one run's requests to a day, dropping anything long expired."""
        cutoff = day - timedelta(days=RETAIN_DAYS)
        kept = {
            k: v for k, v in self.days.items()
            if (parsed := _parse(k)) is not None and parsed > cutoff
        }
        key = day.isoformat()
        kept[key] = kept.get(key, 0) + count
        return QuotaLedger(days=dict(sorted(kept.items())))


def _parse(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def quota_path(campaign_dir: Path) -> Path:
    return campaign_dir / QUOTA_FILE


def load_quota(path: Path) -> QuotaLedger:
    if not path.is_file():
        return QuotaLedger()
    try:
        return QuotaLedger.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"{path} is not a valid quota ledger: {exc}") from exc


def save_quota(path: Path, ledger: QuotaLedger) -> None:
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


def record_run(path: Path, day: date, count: int) -> QuotaLedger:
    """Fold one run's request count into a campaign's ledger."""
    if count <= 0:
        return load_quota(path)
    ledger = load_quota(path).with_run(day, count)
    save_quota(path, ledger)
    return ledger


def rolling_total(ledgers: list[QuotaLedger], today: date) -> int:
    """Requests over the trailing window, across every ledger sharing a key."""
    first = today - timedelta(days=WINDOW_DAYS - 1)
    return sum(ledger.total_since(first) for ledger in ledgers)
