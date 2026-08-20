"""The Buffer request tally.

The bug being fixed was not a wrong number — it was a threshold that could
never be reached, so these tests are mostly about the alarm being reachable at
all, and about the total covering the right set of campaigns.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.errors import ValidationError
from src.quota import (
    MONTHLY_ALLOWANCE,
    RETAIN_DAYS,
    WINDOW_DAYS,
    QuotaLedger,
    load_quota,
    quota_path,
    record_run,
    rolling_total,
    save_quota,
)

TODAY = date(2026, 8, 19)


class TestLedger:
    def test_runs_on_the_same_day_add_up(self) -> None:
        led = QuotaLedger().with_run(TODAY, 40).with_run(TODAY, 14)
        assert led.days[TODAY.isoformat()] == 54

    def test_days_are_kept_separately(self) -> None:
        led = QuotaLedger().with_run(TODAY, 10).with_run(date(2026, 8, 18), 20)
        assert len(led.days) == 2

    def test_long_expired_days_are_dropped(self) -> None:
        old = date(2026, 8, 19 - 1).replace(month=1)
        led = QuotaLedger().with_run(old, 999).with_run(TODAY, 1)
        assert old.isoformat() not in led.days

    def test_days_inside_the_retention_window_survive(self) -> None:
        recent = date(2026, 8, 19 - 5)
        led = QuotaLedger().with_run(recent, 7).with_run(TODAY, 1)
        assert led.days[recent.isoformat()] == 7

    def test_a_garbled_date_key_does_not_break_the_total(self) -> None:
        led = QuotaLedger(days={"not-a-date": 500, TODAY.isoformat(): 10})
        assert led.total_since(date(2026, 8, 1)) == 10


class TestRollingTotal:
    def test_it_sums_the_window_only(self) -> None:
        led = QuotaLedger(days={
            "2026-08-19": 100,          # today
            "2026-07-01": 900,          # well outside 30 days
        })
        assert rolling_total([led], TODAY) == 100

    def test_the_first_day_of_the_window_is_included(self) -> None:
        first = date(2026, 7, 21)  # 30 days inclusive, ending 2026-08-19
        assert rolling_total([QuotaLedger(days={first.isoformat(): 5})], TODAY) == 5

    def test_it_adds_up_every_campaign_on_the_key(self) -> None:
        """The allowance belongs to the Buffer account, not to one campaign.

        Three campaigns at 900 each is 2,700 against a 3,000 ceiling — the
        whole point of summing rather than reporting each in isolation.
        """
        each = QuotaLedger(days={TODAY.isoformat(): 900})
        assert rolling_total([each, each, each], TODAY) == 2700

    def test_the_alarm_threshold_is_now_reachable(self) -> None:
        """The old code compared one run — tens of requests — against 2,400."""
        busy = [QuotaLedger(days={TODAY.isoformat(): 900})] * 3
        assert rolling_total(busy, TODAY) > 2400
        assert rolling_total(busy, TODAY) < MONTHLY_ALLOWANCE

    def test_no_ledgers_is_zero(self) -> None:
        assert rolling_total([], TODAY) == 0


class TestPersistence:
    def test_a_run_round_trips(self, tmp_path: Path) -> None:
        path = quota_path(tmp_path)
        record_run(path, TODAY, 54)
        assert load_quota(path).days[TODAY.isoformat()] == 54

    def test_repeated_runs_accumulate_on_disk(self, tmp_path: Path) -> None:
        path = quota_path(tmp_path)
        for _ in range(4):
            record_run(path, TODAY, 25)
        assert load_quota(path).days[TODAY.isoformat()] == 100

    def test_a_zero_count_writes_nothing(self, tmp_path: Path) -> None:
        path = quota_path(tmp_path)
        record_run(path, TODAY, 0)
        assert not path.exists()

    def test_a_missing_ledger_reads_as_empty(self, tmp_path: Path) -> None:
        assert load_quota(tmp_path / "quota.json").days == {}

    def test_a_corrupt_ledger_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "quota.json"
        path.write_text("{nope", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_quota(path)

    def test_the_window_is_shorter_than_what_is_retained(self) -> None:
        # Otherwise a late-running job could drop a day still inside the window.
        assert RETAIN_DAYS > WINDOW_DAYS
