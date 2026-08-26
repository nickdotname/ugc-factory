"""Reading a product's acquisition figures, and what the join may claim.

The arithmetic is small. What these tests mostly pin down is the *limit*: a
product-wide daily count cannot become a per-post claim, however much one
would like it to, and the shape of the module should keep anyone from trying.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import requests

from src.analytics import (
    AnalyticsCache,
    DayCount,
    Overview,
    correlate,
    default_range,
    load_cache,
    range_from_clock,
    save_cache,
)
from src.analytics_api import HttpProductAnalytics, parse_overview
from src.errors import AnalyticsAuthError, AnalyticsError, ValidationError
from src.logging import StructuredLogger

BASE = "https://admin.example.org/api/v1"

BODY = {
    "range": {"from": "2026-07-01", "to": "2026-08-01"},
    "totals": {"users": 576, "active_projects": 247},
    "funnel": {"signups": 251, "swiped": 147, "d7_retained": 48},
    "series": {"signups_by_day": [
        {"day": "2026-07-01", "count": 7},
        {"day": "2026-07-02", "count": 9},
    ]},
    "retention": {"active_7d": 109, "active_30d": 233},
    "demographics": {"age_dist": {"18-21": 309}},
}


@pytest.fixture
def log() -> StructuredLogger:
    return StructuredLogger({}, io.StringIO())


class FakeResponse:
    def __init__(self, status: int, payload: object = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params,
                           "headers": headers})
        if not self._responses:
            raise AssertionError("more requests than responses queued")
        return self._responses.pop(0)


def source(log, *responses, **kw) -> HttpProductAnalytics:
    return HttpProductAnalytics(BASE, "k", log, session=FakeSession(*responses),
                                sleep=lambda _: None, **kw)


class TestReadingAnOverview:
    def test_it_pulls_the_fields_the_repo_uses(self, log) -> None:
        o = source(log, FakeResponse(200, BODY)).overview(
            date(2026, 7, 1), date(2026, 8, 1))
        assert (o.users, o.signups) == (576, 251)
        assert o.by_day == {date(2026, 7, 1): 7, date(2026, 7, 2): 9}

    def test_it_sends_the_key_iso_dates_and_the_configured_host(self, log) -> None:
        session = FakeSession(FakeResponse(200, BODY))
        HttpProductAnalytics(BASE, "secret", log, session=session,
                             sleep=lambda _: None).overview(
            date(2026, 7, 1), date(2026, 8, 1))
        call = session.calls[0]
        assert call["url"] == f"{BASE}/analytics/overview"
        assert call["headers"]["Authorization"] == "Bearer secret"
        assert call["params"] == {"from": "2026-07-01", "to": "2026-08-01"}

    def test_a_trailing_slash_on_the_base_url_does_not_double(self, log) -> None:
        session = FakeSession(FakeResponse(200, BODY))
        HttpProductAnalytics(BASE + "/", "k", log, session=session,
                             sleep=lambda _: None).overview(
            date(2026, 7, 1), date(2026, 8, 1))
        assert "//analytics" not in session.calls[0]["url"].removeprefix("https://")

    def test_unmodelled_fields_do_not_break_it(self, log) -> None:
        """The endpoint is shared with the product's dashboard and will grow."""
        body = {**BODY, "something_added_next_quarter": {"nested": [1, 2]}}
        assert source(log, FakeResponse(200, body)).overview(
            date(2026, 7, 1), date(2026, 8, 1)).signups == 251

    def test_a_missing_series_is_empty_not_an_error(self, log) -> None:
        body = {"range": BODY["range"], "totals": {}, "funnel": {}}
        assert source(log, FakeResponse(200, body)).overview(
            date(2026, 7, 1), date(2026, 8, 1)).by_day == {}

    def test_one_bad_row_does_not_lose_the_series(self, log) -> None:
        body = {**BODY, "series": {"signups_by_day": [
            {"day": "2026-07-01", "count": 7},
            {"day": "not-a-date", "count": 3},
            {"count": 4},
            {"day": "2026-07-03", "count": 5},
        ]}}
        assert source(log, FakeResponse(200, body)).overview(
            date(2026, 7, 1), date(2026, 8, 1)).by_day == {
                date(2026, 7, 1): 7, date(2026, 7, 3): 5}

    def test_a_datetime_in_the_series_is_reduced_to_its_date(self, log) -> None:
        body = {**BODY, "series": {"signups_by_day": [
            {"day": "2026-07-01T00:00:00Z", "count": 7}]}}
        assert source(log, FakeResponse(200, body)).overview(
            date(2026, 7, 1), date(2026, 8, 1)).by_day == {date(2026, 7, 1): 7}

    def test_an_inverted_range_is_refused_before_the_call(self, log) -> None:
        session = FakeSession()
        s = HttpProductAnalytics(BASE, "k", log, session=session, sleep=lambda _: None)
        with pytest.raises(ValidationError, match="ends before"):
            s.overview(date(2026, 8, 1), date(2026, 7, 1))
        assert session.calls == []

    def test_the_reported_range_wins_over_the_requested_one(self) -> None:
        """The API restates the window it actually served."""
        o = parse_overview(BODY, date(2020, 1, 1), date(2020, 1, 2))
        assert (o.range_from, o.range_to) == (date(2026, 7, 1), date(2026, 8, 1))

    def test_a_missing_range_falls_back_to_what_was_asked(self) -> None:
        o = parse_overview({"totals": {}}, date(2026, 7, 1), date(2026, 8, 1))
        assert (o.range_from, o.range_to) == (date(2026, 7, 1), date(2026, 8, 1))


class TestFailures:
    def test_401_is_terminal_and_points_at_meta(self, log) -> None:
        s = source(log, FakeResponse(401, {"error": {"code": "unauthorized",
                                                     "message": "bad key"}}))
        with pytest.raises(AnalyticsAuthError, match="/meta") as caught:
            s.overview(date(2026, 7, 1), date(2026, 8, 1))
        assert caught.value.retryable is False

    def test_403_carries_the_missing_scope_through(self, log) -> None:
        s = source(log, FakeResponse(403, {"error": {"code": "missing_scope",
                                                     "message": "needs analytics"}}))
        with pytest.raises(AnalyticsAuthError, match="missing_scope"):
            s.overview(date(2026, 7, 1), date(2026, 8, 1))

    def test_an_auth_failure_is_not_retried(self, log) -> None:
        """Retrying burns requests against a per-minute ceiling and fixes nothing."""
        session = FakeSession(FakeResponse(401, {"error": {}}))
        s = HttpProductAnalytics(BASE, "k", log, session=session, sleep=lambda _: None)
        with pytest.raises(AnalyticsAuthError):
            s.overview(date(2026, 7, 1), date(2026, 8, 1))
        assert len(session.calls) == 1

    def test_429_backs_off_then_succeeds(self, log) -> None:
        waits: list[float] = []
        s = HttpProductAnalytics(BASE, "k", log, sleep=waits.append,
                                 session=FakeSession(FakeResponse(429),
                                                     FakeResponse(200, BODY)))
        assert s.overview(date(2026, 7, 1), date(2026, 8, 1)).signups == 251
        assert waits == [2]

    def test_a_persistent_429_is_reported_as_retryable(self, log) -> None:
        s = source(log, FakeResponse(429), FakeResponse(429), FakeResponse(429))
        with pytest.raises(AnalyticsError, match="429") as caught:
            s.overview(date(2026, 7, 1), date(2026, 8, 1))
        assert caught.value.retryable is True

    def test_a_500_is_retried(self, log) -> None:
        s = source(log, FakeResponse(500), FakeResponse(200, BODY))
        assert s.overview(date(2026, 7, 1), date(2026, 8, 1)).signups == 251

    def test_400_names_the_bad_parameter(self, log) -> None:
        s = source(log, FakeResponse(400, {"error": {"code": "bad_param",
                                                     "message": "weeks must be 1-26"}}))
        with pytest.raises(ValidationError, match="weeks must be 1-26"):
            s.overview(date(2026, 7, 1), date(2026, 8, 1))

    def test_a_transport_error_retries_then_raises(self, log) -> None:
        class Broken:
            calls = 0

            def request(self, *a, **k):
                Broken.calls += 1
                raise requests.RequestException("connection reset")

        s = HttpProductAnalytics(BASE, "k", log, session=Broken(), sleep=lambda _: None)
        with pytest.raises(AnalyticsError, match="connection reset"):
            s.overview(date(2026, 7, 1), date(2026, 8, 1))
        assert Broken.calls == 3

    def test_non_json_is_reported_with_the_body(self, log) -> None:
        s = source(log, FakeResponse(200, None, text="<html>gateway</html>"))
        with pytest.raises(AnalyticsError, match="gateway"):
            s.overview(date(2026, 7, 1), date(2026, 8, 1))

    def test_a_capped_scan_is_warned_about(self) -> None:
        """A truncated view must never be mistaken for a complete one."""
        stream = io.StringIO()
        HttpProductAnalytics(
            BASE, "k", StructuredLogger({}, stream), sleep=lambda _: None,
            session=FakeSession(FakeResponse(200, {**BODY, "scan_capped": True})),
        ).overview(date(2026, 7, 1), date(2026, 8, 1))
        assert "analytics_scan_capped" in stream.getvalue()

    def test_an_empty_key_is_refused_at_construction(self, log) -> None:
        with pytest.raises(AnalyticsAuthError):
            HttpProductAnalytics(BASE, "", log)

    def test_an_empty_base_url_is_refused_at_construction(self, log) -> None:
        with pytest.raises(ValidationError):
            HttpProductAnalytics("", "k", log)


class TestTheJoin:
    def test_it_lines_up_posting_against_signups(self) -> None:
        rows = correlate({date(2026, 8, 1): 12, date(2026, 8, 2): 3},
                         {date(2026, 8, 1): 2400.0, date(2026, 8, 2): 300.0},
                         {date(2026, 8, 1): 8, date(2026, 8, 2): 2})
        assert [(r.posts, r.views, r.signups) for r in rows] == [
            (12, 2400.0, 8), (3, 300.0, 2)]

    def test_a_day_present_in_only_one_source_still_appears(self) -> None:
        """A quiet day is the comparison; dropping it deletes the control."""
        rows = correlate({}, {}, {date(2026, 8, 3): 5})
        assert [(r.day, r.posts, r.signups) for r in rows] == [(date(2026, 8, 3), 0, 5)]

    def test_views_per_signup_is_undefined_rather_than_huge(self) -> None:
        rows = correlate({date(2026, 8, 1): 12}, {date(2026, 8, 1): 2400.0}, {})
        assert rows[0].views_per_signup is None

    def test_views_per_signup_divides_when_it_can(self) -> None:
        rows = correlate({date(2026, 8, 1): 12}, {date(2026, 8, 1): 2400.0},
                         {date(2026, 8, 1): 8})
        assert rows[0].views_per_signup == 300.0

    def test_days_come_back_in_order(self) -> None:
        rows = correlate({date(2026, 8, 5): 1}, {}, {date(2026, 8, 1): 2})
        assert [r.day for r in rows] == [date(2026, 8, 1), date(2026, 8, 5)]


class TestCache:
    def test_it_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "analytics.json"
        save_cache(path, AnalyticsCache(fetches=[Overview(
            range_from=date(2026, 7, 1), range_to=date(2026, 7, 2),
            users=5, signups=2,
            signups_by_day=(DayCount(day=date(2026, 7, 1), count=2),))]))
        assert load_cache(path).fetches[0].signups == 2

    def test_a_missing_file_is_an_empty_cache(self, tmp_path: Path) -> None:
        assert load_cache(tmp_path / "nothing.json").fetches == []

    def test_a_corrupt_cache_is_refused_not_silently_dropped(self, tmp_path: Path) -> None:
        path = tmp_path / "analytics.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_cache(path)

    def test_a_later_fetch_restates_an_earlier_day(self) -> None:
        """A source can revise a day; newest wins, and both are kept."""
        cache = AnalyticsCache(fetches=[
            Overview(range_from=date(2026, 7, 1), range_to=date(2026, 7, 1),
                     signups_by_day=(DayCount(day=date(2026, 7, 1), count=7),)),
            Overview(range_from=date(2026, 7, 1), range_to=date(2026, 7, 1),
                     signups_by_day=(DayCount(day=date(2026, 7, 1), count=9),)),
        ])
        assert cache.latest_by_day() == {date(2026, 7, 1): 9}
        assert len(cache.fetches) == 2


class TestRange:
    def test_it_covers_the_trailing_window_inclusive(self) -> None:
        assert default_range(date(2026, 8, 30), 30) == (date(2026, 8, 1),
                                                        date(2026, 8, 30))

    def test_one_day_is_today_twice(self) -> None:
        assert default_range(date(2026, 8, 30), 1) == (date(2026, 8, 30),
                                                       date(2026, 8, 30))

    def test_an_empty_window_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            default_range(date(2026, 8, 30), 0)

    def test_it_takes_its_today_from_an_injected_clock(self) -> None:
        """SPEC §2.2 — nothing outside ports reads wall time."""
        now = datetime(2026, 8, 30, 5, 25, tzinfo=timezone.utc)
        assert range_from_clock(now, 2) == (date(2026, 8, 29), date(2026, 8, 30))
