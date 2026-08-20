"""The Buffer request tally.

The bug being fixed was not a wrong number — it was a threshold that could
never be reached, so these tests are mostly about the alarm being reachable at
all, and about the total covering the right set of campaigns.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.config import CampaignConfig
from src.errors import ValidationError
from src.logging import StructuredLogger
from src.ports import FrozenClock
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


def _config() -> CampaignConfig:
    return CampaignConfig.model_validate({
        "slug": "demo", "timezone": "UTC",
        "buffer": {"api_key_secret": "BUFFER_API_KEY",
                   "channel_id_secret": "BUFFER_CHANNEL_X"},
        "notify": {"webhook_secret": "DISCORD_WEBHOOK_X"},
    })


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


class TestTheLedgerIsPersisted:
    """The bug this guards: the ledger was written faithfully on an ephemeral
    runner and never committed, so every run began from an empty file and the
    rolling tally sat at zero for ever. Writing it is only half the job."""

    def test_a_run_with_requests_commits_the_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.cli as cli
        from src.vcs import Vcs

        committed: list[tuple[list[str], str]] = []

        class RecordingVcs(Vcs):
            def commit(self, paths, message):  # type: ignore[no-untyped-def]
                committed.append(([Path(p).name for p in paths], message))
                return True

        campaign = tmp_path / "campaigns" / "demo"
        campaign.mkdir(parents=True)
        monkeypatch.setattr(cli, "CAMPAIGNS_DIR", tmp_path / "campaigns")

        class Publisher:
            request_count = 37

        class Notifier:
            def notify(self, *a, **k): pass

        config = _config()
        cli._report_quota(
            Publisher(), Notifier(), config,  # type: ignore[arg-type]
            StructuredLogger({}, io.StringIO()),
            FrozenClock(datetime(2026, 8, 20, 12, tzinfo=timezone.utc)),
            RecordingVcs(),
        )
        assert committed, "the ledger was written but never committed"
        paths, message = committed[0]
        assert "quota.json" in paths and "demo" in message

    def test_a_run_that_spent_nothing_commits_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Topup runs every four hours; an empty commit each time is noise."""
        import src.cli as cli
        from src.vcs import Vcs

        committed: list[str] = []

        class RecordingVcs(Vcs):
            def commit(self, paths, message):  # type: ignore[no-untyped-def]
                committed.append(message)
                return True

        (tmp_path / "campaigns" / "demo").mkdir(parents=True)
        monkeypatch.setattr(cli, "CAMPAIGNS_DIR", tmp_path / "campaigns")

        class Idle:
            request_count = 0

        class Notifier:
            def notify(self, *a, **k): pass

        cli._report_quota(
            Idle(), Notifier(), _config(),  # type: ignore[arg-type]
            StructuredLogger({}, io.StringIO()),
            FrozenClock(datetime(2026, 8, 20, 12, tzinfo=timezone.utc)),
            RecordingVcs(),
        )
        assert committed == []

    def test_it_still_works_without_a_vcs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The metrics job commits through the workflow, not through GitVcs."""
        import src.cli as cli

        (tmp_path / "campaigns" / "demo").mkdir(parents=True)
        monkeypatch.setattr(cli, "CAMPAIGNS_DIR", tmp_path / "campaigns")

        class Publisher:
            request_count = 5

        class Notifier:
            def notify(self, *a, **k): pass

        cli._report_quota(
            Publisher(), Notifier(), _config(),  # type: ignore[arg-type]
            StructuredLogger({}, io.StringIO()),
            FrozenClock(datetime(2026, 8, 20, 12, tzinfo=timezone.utc)),
        )
        assert load_quota(tmp_path / "campaigns" / "demo" / "quota.json").days
