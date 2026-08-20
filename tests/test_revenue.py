"""The revenue ledger and the ratios built on it.

The arithmetic is the whole feature. A ratio that pairs a month of reach with a
week of money is not a smaller number — it is a wrong one, and it looks exactly
as convincing on a chart.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.errors import ValidationError
from src.revenue import (
    RevenueEntry,
    RevenueLedger,
    ledger_path,
    load_ledger,
    per_thousand,
    save_ledger,
)


def entry(start: str, end: str, amount: float, source: str = "manual") -> RevenueEntry:
    return RevenueEntry(
        period_start=date.fromisoformat(start),
        period_end=date.fromisoformat(end),
        amount=amount,
        source=source,
    )


class TestEntry:
    def test_a_single_day_entry_spans_one_day(self) -> None:
        assert entry("2026-08-05", "2026-08-05", 500).days == 1

    def test_days_count_both_ends(self) -> None:
        assert entry("2026-08-01", "2026-08-31", 310).days == 31

    def test_a_backwards_period_is_refused(self) -> None:
        with pytest.raises(ValueError):
            entry("2026-08-31", "2026-08-01", 100)

    def test_an_absurd_span_is_refused(self) -> None:
        with pytest.raises(ValueError):
            entry("2020-01-01", "2026-01-01", 100)

    def test_a_negative_amount_is_refused(self) -> None:
        with pytest.raises(ValueError):
            entry("2026-08-01", "2026-08-01", -5)

    def test_currency_must_be_a_three_letter_code(self) -> None:
        with pytest.raises(ValueError):
            RevenueEntry(
                period_start=date(2026, 8, 1), period_end=date(2026, 8, 1),
                amount=1, currency="dollars",
            )

    def test_entries_get_distinct_ids(self) -> None:
        # Positional deletion would remove the wrong row once an earlier one
        # is gone.
        assert entry("2026-08-01", "2026-08-01", 1).id != \
               entry("2026-08-01", "2026-08-01", 1).id


class TestProRating:
    def test_a_month_contributes_only_its_overlapping_days(self) -> None:
        # $310 over 31 days is $10/day; ten days of it is $100, not $310.
        led = RevenueLedger().with_entry(entry("2026-08-01", "2026-08-31", 310))
        assert led.total_in(date(2026, 8, 1), date(2026, 8, 10)) == pytest.approx(100)

    def test_a_window_entirely_outside_contributes_nothing(self) -> None:
        led = RevenueLedger().with_entry(entry("2026-08-01", "2026-08-31", 310))
        assert led.total_in(date(2026, 9, 1), date(2026, 9, 30)) == 0

    def test_a_window_containing_everything_gets_the_whole_amount(self) -> None:
        led = RevenueLedger().with_entry(entry("2026-08-01", "2026-08-31", 310))
        assert led.total_in(date(2026, 7, 1), date(2026, 9, 30)) == pytest.approx(310)

    def test_a_one_day_payment_inside_the_window_counts_in_full(self) -> None:
        led = RevenueLedger().with_entry(entry("2026-08-05", "2026-08-05", 500))
        assert led.total_in(date(2026, 7, 20), date(2026, 8, 19)) == pytest.approx(500)

    def test_the_daily_series_sums_back_to_the_total(self) -> None:
        led = (RevenueLedger()
               .with_entry(entry("2026-08-01", "2026-08-31", 310))
               .with_entry(entry("2026-08-05", "2026-08-05", 500)))
        assert sum(v for _, v in led.daily()) == pytest.approx(810, abs=0.01)

    def test_the_daily_series_has_one_row_per_covered_day(self) -> None:
        led = RevenueLedger().with_entry(entry("2026-08-01", "2026-08-31", 310))
        assert len(led.daily()) == 31


class TestDoubleCounting:
    def test_two_sources_overlapping_is_not_a_problem(self) -> None:
        # A brand deal during an affiliate week is two real payments.
        led = (RevenueLedger()
               .with_entry(entry("2026-08-01", "2026-08-07", 100, "affiliate"))
               .with_entry(entry("2026-08-03", "2026-08-03", 500, "brand deal")))
        assert led.double_counting() == []

    def test_one_source_overlapping_itself_is_reported(self) -> None:
        led = (RevenueLedger()
               .with_entry(entry("2026-08-01", "2026-08-31", 310, "app"))
               .with_entry(entry("2026-08-15", "2026-09-05", 200, "app")))
        problems = led.double_counting()
        assert len(problems) == 1 and "counted twice" in problems[0]

    def test_adjacent_periods_do_not_overlap(self) -> None:
        led = (RevenueLedger()
               .with_entry(entry("2026-08-01", "2026-08-15", 100, "app"))
               .with_entry(entry("2026-08-16", "2026-08-31", 100, "app")))
        assert led.double_counting() == []


class TestPerThousand:
    def test_the_ordinary_case(self) -> None:
        assert per_thousand(310.0, 155_000) == pytest.approx(2.0)

    def test_no_views_is_unknown_not_zero(self) -> None:
        # Charting "unknown" as 0 would read as "earns nothing per view",
        # which is the opposite of what a revenue-with-no-reach row means.
        assert per_thousand(500.0, 0) is None


class TestPersistence:
    def test_round_trips(self, tmp_path: Path) -> None:
        path = ledger_path(tmp_path)
        save_ledger(path, RevenueLedger().with_entry(entry("2026-08-01", "2026-08-31", 310)))
        assert load_ledger(path).total() == pytest.approx(310)

    def test_a_missing_ledger_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert load_ledger(tmp_path / "revenue.json").entries == ()

    def test_a_corrupt_ledger_raises_rather_than_zeroing_the_money(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "revenue.json"
        path.write_text("{oops", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_ledger(path)

    def test_entries_are_kept_in_period_order(self, tmp_path: Path) -> None:
        led = (RevenueLedger()
               .with_entry(entry("2026-08-20", "2026-08-20", 1))
               .with_entry(entry("2026-08-01", "2026-08-01", 2)))
        assert [e.period_start.isoformat() for e in led.entries] == \
               ["2026-08-01", "2026-08-20"]

    def test_removing_takes_only_the_named_entry(self) -> None:
        first = entry("2026-08-01", "2026-08-01", 1)
        led = RevenueLedger().with_entry(first).with_entry(
            entry("2026-08-02", "2026-08-02", 2))
        assert led.without(first.id).total() == pytest.approx(2)


class TestLedgerSummaries:
    def test_span_covers_earliest_to_latest(self) -> None:
        led = (RevenueLedger()
               .with_entry(entry("2026-08-05", "2026-08-05", 500))
               .with_entry(entry("2026-07-01", "2026-07-31", 300)))
        assert led.span() == (date(2026, 7, 1), date(2026, 8, 5))

    def test_an_empty_ledger_has_no_span(self) -> None:
        assert RevenueLedger().span() is None

    def test_by_source_totals_and_ranks(self) -> None:
        led = (RevenueLedger()
               .with_entry(entry("2026-08-01", "2026-08-01", 100, "affiliate"))
               .with_entry(entry("2026-08-02", "2026-08-02", 500, "brand deal"))
               .with_entry(entry("2026-08-03", "2026-08-03", 50, "affiliate")))
        assert led.by_source() == [("brand deal", 500.0), ("affiliate", 150.0)]

    def test_by_source_on_an_empty_ledger(self) -> None:
        assert RevenueLedger().by_source() == []

    def test_currencies_reports_every_code_present(self) -> None:
        led = RevenueLedger(entries=(
            RevenueEntry(period_start=date(2026, 8, 1), period_end=date(2026, 8, 1),
                         amount=1, currency="USD"),
            RevenueEntry(period_start=date(2026, 8, 2), period_end=date(2026, 8, 2),
                         amount=1, currency="eur"),
        ))
        assert led.currencies == {"USD", "EUR"}


class TestSaveFailure:
    def test_a_failed_save_leaves_no_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.revenue.os.replace",
            lambda s, d: (_ for _ in ()).throw(OSError("disk full")),
        )
        with pytest.raises(OSError):
            save_ledger(ledger_path(tmp_path),
                        RevenueLedger().with_entry(entry("2026-08-01", "2026-08-01", 1)))
        assert list(tmp_path.iterdir()) == []

    def test_a_failed_save_does_not_destroy_the_previous_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Money records are the last thing that should be lost to a half-write."""
        path = ledger_path(tmp_path)
        save_ledger(path, RevenueLedger().with_entry(entry("2026-08-01", "2026-08-01", 310)))
        monkeypatch.setattr(
            "src.revenue.os.replace",
            lambda s, d: (_ for _ in ()).throw(OSError("disk full")),
        )
        with pytest.raises(OSError):
            save_ledger(path, RevenueLedger())
        assert load_ledger(path).total() == pytest.approx(310)
