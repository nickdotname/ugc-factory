"""Metrics caching and the dashboard's data source. No network."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.errors import ValidationError
from src.logging import StructuredLogger
from src.metrics import (
    Metric,
    MetricsHistory,
    Snapshot,
    default_window,
    load_metrics,
    save_metrics,
)
from src.publishers.base import DryRunPublisher
from src.publishers.buffer import BufferPublisher

from tests.fakes import FakeResponse, FakeSession

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def snap(date: str, **values: float) -> Snapshot:
    return Snapshot(
        date=date,
        fetched_at=NOW,
        window_start=NOW - timedelta(days=30),
        window_end=NOW,
        service="instagram",
        metrics=[
            Metric(type=k, name=k.title(), value=v,
                   unit="percentage" if "Rate" in k else "count")
            for k, v in values.items()
        ],
    )


class TestSnapshot:
    def test_get_returns_zero_for_an_absent_metric(self) -> None:
        assert snap("2026-08-13", reach=100).get("clicks") == 0.0

    def test_post_count_is_read_from_metrics(self) -> None:
        assert snap("2026-08-13", postCount=7).post_count == 7

    def test_percentage_units_are_flagged(self) -> None:
        s = snap("2026-08-13", engagementRate=4.2)
        assert s.metrics[0].is_percentage


class TestHistory:
    def test_upsert_replaces_the_same_day(self) -> None:
        """Network metrics keep moving for days; a re-run must refresh."""
        h = MetricsHistory()
        h.upsert(snap("2026-08-13", reach=100))
        h.upsert(snap("2026-08-13", reach=250))
        assert len(h.snapshots) == 1
        assert h.latest() is not None and h.latest().get("reach") == 250

    def test_upsert_appends_a_new_day(self) -> None:
        h = MetricsHistory()
        h.upsert(snap("2026-08-13", reach=100))
        h.upsert(snap("2026-08-14", reach=140))
        assert len(h.snapshots) == 2

    def test_snapshots_stay_sorted_regardless_of_insert_order(self) -> None:
        h = MetricsHistory()
        h.upsert(snap("2026-08-15", reach=3))
        h.upsert(snap("2026-08-13", reach=1))
        h.upsert(snap("2026-08-14", reach=2))
        assert [s.date for s in h.snapshots] == [
            "2026-08-13", "2026-08-14", "2026-08-15"
        ]

    def test_series_is_chartable_pairs(self) -> None:
        h = MetricsHistory()
        h.upsert(snap("2026-08-13", reach=10))
        h.upsert(snap("2026-08-14", reach=20))
        assert h.series("reach") == [("2026-08-13", 10.0), ("2026-08-14", 20.0)]

    def test_change_computes_percent_growth(self) -> None:
        h = MetricsHistory()
        h.upsert(snap("2026-08-13", reach=100))
        h.upsert(snap("2026-08-14", reach=150))
        assert h.change("reach", days=7) == pytest.approx(50.0)

    def test_change_is_none_without_a_baseline(self) -> None:
        """'No data yet' and 'no change' are different claims."""
        h = MetricsHistory()
        h.upsert(snap("2026-08-13", reach=100))
        assert h.change("reach") is None

    def test_change_is_none_when_baseline_is_zero(self) -> None:
        h = MetricsHistory()
        h.upsert(snap("2026-08-13", reach=0))
        h.upsert(snap("2026-08-14", reach=50))
        assert h.change("reach") is None

    def test_latest_is_none_when_empty(self) -> None:
        assert MetricsHistory().latest() is None


class TestPersistence:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.json"
        h = MetricsHistory()
        h.upsert(snap("2026-08-13", reach=100, engagementRate=3.5))
        save_metrics(path, h)
        loaded = load_metrics(path)
        assert len(loaded.snapshots) == 1
        assert loaded.latest() is not None
        assert loaded.latest().get("engagementRate") == 3.5

    def test_missing_file_is_empty_history(self, tmp_path: Path) -> None:
        assert load_metrics(tmp_path / "absent.json").snapshots == []

    def test_corrupt_file_fails_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError, match="not a valid metrics file"):
            load_metrics(path)


class TestWindow:
    def test_window_snaps_to_whole_days(self) -> None:
        """A partial trailing day makes consecutive snapshots incomparable."""
        start, end = default_window(NOW, days=30)
        assert end.hour == 0 and end.minute == 0
        assert (end - start).days == 30


class TestBufferFetch:
    def _session(self, metrics, updated="2026-08-13T10:00:00Z") -> FakeSession:
        return FakeSession().route("POST", "api.buffer.com", FakeResponse(200, {
            "data": {"aggregatedPostMetrics": {
                "metricsUpdatedAt": updated, "metrics": metrics,
            }}
        }))

    def _publisher(self, session) -> BufferPublisher:
        return BufferPublisher("k", StructuredLogger({}, io.StringIO()),
                               organization_id="org", session=session,
                               sleep=lambda _s: None)

    def test_parses_rows(self) -> None:
        s = self._session([
            {"type": "reach", "name": "Reach", "value": 1234, "unit": "count"},
            {"type": "engagementRate", "name": "Eng. Rate", "value": 4.2,
             "unit": "percentage"},
        ])
        rows, updated = self._publisher(s).fetch_metrics(
            "chan", NOW - timedelta(days=30), NOW
        )
        assert [r.type for r in rows] == ["reach", "engagementRate"]
        assert rows[0].value == 1234.0
        assert updated is not None

    def test_one_request_per_window(self) -> None:
        """What makes a daily snapshot affordable against the 3,000 budget."""
        s = self._session([])
        p = self._publisher(s)
        p.fetch_metrics("chan", NOW - timedelta(days=30), NOW)
        assert p.request_count == 1

    def test_scopes_to_the_requested_channel(self) -> None:
        s = self._session([])
        self._publisher(s).fetch_metrics("chan-xyz", NOW - timedelta(days=1), NOW)
        assert s.calls[0].json_body["variables"]["input"]["channelIds"] == ["chan-xyz"]

    def test_missing_value_is_zero_not_an_error(self) -> None:
        s = self._session([{"type": "saves", "name": "Saves", "unit": "count"}])
        rows, _ = self._publisher(s).fetch_metrics("c", NOW, NOW)
        assert rows[0].value == 0.0

    def test_rows_without_a_type_are_dropped(self) -> None:
        s = self._session([{"name": "Mystery", "value": 5}])
        rows, _ = self._publisher(s).fetch_metrics("c", NOW, NOW)
        assert rows == []

    def test_empty_response_is_not_an_error(self) -> None:
        """Before the first post publishes there is genuinely nothing."""
        s = self._session([], updated=None)
        rows, updated = self._publisher(s).fetch_metrics("c", NOW, NOW)
        assert rows == [] and updated is None

    def test_dry_run_publisher_reports_nothing(self) -> None:
        rows, updated = DryRunPublisher(
            StructuredLogger({}, io.StringIO())
        ).fetch_metrics("c", NOW, NOW)
        assert rows == [] and updated is None


class TestDashboardData:
    """The web app must read the cache and never call Buffer."""

    def test_metrics_endpoint_reads_from_disk_only(self, tmp_path: Path) -> None:
        import inspect

        from src.web import WebApp

        source = inspect.getsource(WebApp.metrics)
        assert "load_metrics" in source
        for forbidden in ("BufferPublisher", "fetch_metrics", "_store"):
            assert forbidden not in source, (
                f"dashboard must not reach the network: found {forbidden}"
            )

    def test_campaign_without_data_is_reported_not_hidden(
        self, tmp_path: Path, config
    ) -> None:
        from src.web import WebApp

        campaigns = tmp_path / "campaigns" / "demo"
        campaigns.mkdir(parents=True)
        bank = campaigns / "captions.txt"
        bank.write_text("one", encoding="utf-8")

        app = WebApp(
            config=config, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=bank, log=StructuredLogger({}, io.StringIO()),
            clock=__import__("src.ports", fromlist=["FrozenClock"]).FrozenClock(NOW),
        )
        result = app.metrics()
        assert result["campaigns"][0]["has_data"] is False

    def test_latest_snapshot_is_surfaced_with_change(
        self, tmp_path: Path, config
    ) -> None:
        from src.ports import FrozenClock
        from src.web import WebApp

        campaigns = tmp_path / "campaigns" / "demo"
        campaigns.mkdir(parents=True)
        bank = campaigns / "captions.txt"
        bank.write_text("one", encoding="utf-8")

        h = MetricsHistory()
        h.upsert(snap("2026-08-12", reach=100))
        h.upsert(snap("2026-08-13", reach=150))
        save_metrics(campaigns / "metrics.json", h)

        app = WebApp(
            config=config, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=bank, log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW),
        )
        card = app.metrics()["campaigns"][0]
        assert card["has_data"] and card["date"] == "2026-08-13"
        reach = next(m for m in card["metrics"] if m["type"] == "reach")
        assert reach["value"] == 150
        assert reach["change"] == pytest.approx(50.0)
        assert card["series"]["reach"] == [
            ("2026-08-12", 100.0), ("2026-08-13", 150.0)
        ]


class TestLifetimeScope:
    """All-time totals need their own query, not arithmetic over the series."""

    def lifesnap(self, date: str, **values: float) -> Snapshot:
        from src.metrics import Scope

        return Snapshot(
            date=date, scope=Scope.LIFETIME, fetched_at=NOW,
            window_start=NOW - timedelta(days=200), window_end=NOW,
            service="instagram",
            metrics=[Metric(type=k, name=k.title(), value=v)
                     for k, v in values.items()],
        )

    def test_rolling_and_lifetime_coexist_on_one_day(self) -> None:
        """Same date, different measurement — neither may overwrite the other."""
        from src.metrics import Scope

        h = MetricsHistory()
        h.upsert(snap("2026-08-18", reach=100))
        h.upsert(self.lifesnap("2026-08-18", reach=5000))
        assert len(h.snapshots) == 2
        assert h.latest(Scope.ROLLING).get("reach") == 100
        assert h.lifetime().get("reach") == 5000

    def test_lifetime_upsert_replaces_only_its_own_scope(self) -> None:
        h = MetricsHistory()
        h.upsert(snap("2026-08-18", reach=100))
        h.upsert(self.lifesnap("2026-08-18", reach=5000))
        h.upsert(self.lifesnap("2026-08-18", reach=5200))
        assert len(h.snapshots) == 2
        assert h.lifetime().get("reach") == 5200

    def test_lifetime_is_none_before_it_is_ever_fetched(self) -> None:
        h = MetricsHistory()
        h.upsert(snap("2026-08-18", reach=100))
        assert h.lifetime() is None

    def test_series_is_scoped(self) -> None:
        from src.metrics import Scope

        h = MetricsHistory()
        h.upsert(snap("2026-08-17", reach=90))
        h.upsert(snap("2026-08-18", reach=100))
        h.upsert(self.lifesnap("2026-08-18", reach=5000))
        assert h.series("reach") == [("2026-08-17", 90.0), ("2026-08-18", 100.0)]
        assert h.series("reach", Scope.LIFETIME) == [("2026-08-18", 5000.0)]

    def test_change_only_compares_within_a_scope(self) -> None:
        """Mixing a 30-day figure with a lifetime one would report nonsense."""
        h = MetricsHistory()
        h.upsert(snap("2026-08-17", reach=100))
        h.upsert(self.lifesnap("2026-08-17", reach=9000))
        h.upsert(snap("2026-08-18", reach=150))
        h.upsert(self.lifesnap("2026-08-18", reach=9500))
        assert h.change("reach") == pytest.approx(50.0)

    def test_old_files_without_a_scope_load_as_rolling(self) -> None:
        """Metrics written before scopes existed were 30-day windows."""
        raw = (
            '{"snapshots":[{"date":"2026-08-01","fetched_at":"2026-08-01T00:00:00Z",'
            '"window_start":"2026-07-02T00:00:00Z","window_end":"2026-08-01T00:00:00Z",'
            '"service":"instagram","metrics":[]}]}'
        )
        h = MetricsHistory.model_validate_json(raw)
        from src.metrics import Scope

        assert h.snapshots[0].scope is Scope.ROLLING
        assert h.lifetime() is None


class TestLifetimeWindow:
    def test_starts_before_the_first_post(self) -> None:
        from src.metrics import lifetime_window

        first = datetime(2026, 8, 13, 21, 0, tzinfo=timezone.utc)
        start, end = lifetime_window(NOW, first)
        assert start < first, "a post on the boundary would be clipped"
        assert end > NOW

    def test_falls_back_to_a_year_without_history(self) -> None:
        from src.metrics import lifetime_window

        start, end = lifetime_window(NOW, None)
        assert (end - start).days >= 365

    def test_window_covers_more_than_the_rolling_one(self) -> None:
        from src.metrics import default_window, lifetime_window

        r_start, _ = default_window(NOW, 30)
        l_start, _ = lifetime_window(NOW, datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert l_start < r_start
