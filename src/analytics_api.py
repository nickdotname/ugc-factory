"""HTTP transport for a product's admin analytics API.

A boundary module in the sense SPEC §2.2 means: it is the only place that
knows this API speaks JSON over HTTPS with a bearer token, and it imports
``requests`` for that reason. Everything above it sees ``ProductAnalytics``.

The endpoint, and the name of the secret holding its key, come from campaign
config. Nothing here names a product: a second brand pointing at a different
admin panel is configuration, not a code change.

Read-only by construction — the upstream is documented GET/OPTIONS only, and
this issues nothing but GETs.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Mapping

import requests

from src.analytics import (
    CohortGrid,
    CohortRow,
    DayCount,
    Labelled,
    Overview,
    ProductAnalytics,
)
from src.errors import AnalyticsAuthError, AnalyticsError, ValidationError
from src.logging import StructuredLogger

REQUEST_TIMEOUT_SEC = 30

#: A fetch is one or two calls against a per-minute ceiling, so the backoff is
#: here for correctness rather than because we expect to meet the limit.
MAX_ATTEMPTS = 3


class HttpProductAnalytics(ProductAnalytics):
    """Bearer-authenticated JSON analytics over HTTPS."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        log: StructuredLogger,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        if not api_key:
            raise AnalyticsAuthError("analytics API key is empty")
        if not base_url:
            raise ValidationError("analytics base_url is empty")
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._log = log
        self._session = session or requests.Session()
        self._max_attempts = max_attempts
        if sleep is None:
            import time

            sleep = time.sleep
        self._sleep = sleep
        self.request_count = 0

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """One GET, retrying only what a retry could fix."""
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self.request_count += 1
            try:
                response = self._session.request(
                    "GET",
                    f"{self._base}{path}",
                    params=dict(params or {}),
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=REQUEST_TIMEOUT_SEC,
                )
            except requests.RequestException as exc:
                last = AnalyticsError(f"analytics request failed: {exc}")
                if attempt == self._max_attempts:
                    raise last from exc
                self._sleep(2**attempt)
                continue

            if response.status_code in (401, 403):
                # Terminal, but a revoked key and a key missing one scope look
                # identical until you read the code, so carry it through.
                raise AnalyticsAuthError(
                    f"analytics API rejected the key (HTTP {response.status_code}): "
                    f"{_error_message(response)}. "
                    f"GET {self._base}/meta lists what a key actually reaches."
                )
            if response.status_code == 429:
                last = AnalyticsError("analytics API rate limited the request (HTTP 429)")
                if attempt == self._max_attempts:
                    raise last
                self._sleep(2**attempt)
                continue
            if response.status_code >= 500:
                last = AnalyticsError(f"analytics API returned HTTP {response.status_code}")
                if attempt == self._max_attempts:
                    raise last
                self._sleep(2**attempt)
                continue
            if response.status_code >= 400:
                # A 400 names the offending parameter, which is far more use
                # than the status on its own.
                raise ValidationError(
                    f"analytics API rejected the request "
                    f"(HTTP {response.status_code}): {_error_message(response)}"
                )

            try:
                body: dict[str, Any] = response.json()
            except ValueError as exc:
                raise AnalyticsError(
                    f"analytics API returned non-JSON: {response.text[:300]}"
                ) from exc
            if not isinstance(body, dict):
                raise AnalyticsError(
                    f"analytics API returned a non-object body: {str(body)[:200]}"
                )

            # Where an endpoint scans a bounded set it says so. Treating a
            # capped scan as complete is the mistake the flag exists to stop.
            if body.get("scan_capped"):
                self._log.warning("analytics_scan_capped", path=path)
            return body

        raise last or AnalyticsError("analytics request exhausted retries")

    def scopes(self) -> dict[str, object]:
        return self._get("/meta")

    def overview(self, since: date, until: date) -> Overview:
        if until < since:
            raise ValidationError(f"range ends before it starts: {since} to {until}")
        body = self._get(
            "/analytics/overview",
            {"from": since.isoformat(), "to": until.isoformat()},
        )
        return parse_overview(body, since, until)

    def cohorts(self, weeks: int = 12) -> CohortGrid:
        """Signup cohorts by week, with retention at each week offset."""
        if not 1 <= weeks <= 26:
            raise ValidationError(f"weeks must be 1-26, got {weeks}")
        return parse_cohorts(self._get("/analytics/cohorts", {"weeks": weeks}))


def _error_message(response: requests.Response) -> str:
    """Pull a structured ``error.message`` out, or fall back to the body."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code", ""))
            message = str(error.get("message", ""))
            return f"{code}: {message}".strip(": ") or str(payload)[:200]
    return str(payload)[:200]


def parse_overview(
    body: Mapping[str, Any], since: date, until: date
) -> Overview:
    """Map a response, tolerating fields this repo does not model.

    Every lookup is defensive on purpose. The endpoint is shared with the
    product's own dashboard and will grow fields; a parse that demanded the
    exact documented shape would break on an addition that does not concern us.
    """
    reported = body.get("range") or {}
    totals = body.get("totals") or {}
    funnel = body.get("funnel") or {}
    series = body.get("series") or {}
    demographics = body.get("demographics") or {}
    acquisition = body.get("acquisition") or {}

    return Overview(
        range_from=_as_date(reported.get("from"), since),
        range_to=_as_date(reported.get("to"), until),
        users=int(totals.get("users") or 0),
        signups=int(funnel.get("signups") or 0),
        signups_by_day=_series(series.get("signups_by_day")),
        dau_by_day=_series(series.get("dau_by_day")),
        swipes_by_day=_series(series.get("swipes_by_day")),
        projects_by_day=_series(series.get("projects_by_day")),
        # This one counts with "new", not "count".
        new_users_by_day=_series(acquisition.get("cumulative_by_day"), "new"),
        funnel=_numbers(funnel),
        swipe_funnel=_numbers(body.get("swipe_funnel")),
        retention=_numbers(body.get("retention")),
        engagement=_numbers(body.get("engagement")),
        marketplace=_numbers(body.get("marketplace")),
        supply=_numbers(body.get("supply")),
        totals=_numbers(totals),
        age_dist=tuple(
            Labelled(label=str(k), value=float(v))
            for k, v in (demographics.get("age_dist") or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ),
        school_dist=_labelled(demographics.get("school_dist"), "school", "count"),
        top_searches=_labelled(body.get("top_searches"), "query", "count"),
    )


def _as_date(raw: Any, fallback: date | None = None) -> date:
    """Parse an ISO date or datetime; the API documents ISO 8601 UTC."""
    from datetime import datetime as _dt

    if isinstance(raw, _dt):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return _dt.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    if fallback is not None:
        return fallback
    raise ValueError(f"not an ISO date: {raw!r}")


def _series(raw: Any, key: str = "count") -> tuple[DayCount, ...]:
    """A daily series, skipping rows that cannot be read.

    ``key`` varies across the payload — most series count with ``count`` and
    the cumulative one uses ``new`` — so it is a parameter rather than an
    assumption that would silently yield an empty series.
    """
    rows: list[DayCount] = []
    for row in raw or []:
        if not isinstance(row, Mapping):
            continue
        day, count = row.get("day"), row.get(key)
        if day is None or count is None:
            continue
        try:
            rows.append(DayCount(day=_as_date(day), count=int(count)))
        except (ValueError, TypeError):
            continue
    return tuple(sorted(rows, key=lambda d: d.day))


def _numbers(raw: Any) -> dict[str, float]:
    """Flatten a scalar block, dropping anything not a plain number."""
    out: dict[str, float] = {}
    if not isinstance(raw, Mapping):
        return out
    for key, value in raw.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[str(key)] = float(value)
        elif isinstance(value, Mapping):
            # One level of nesting, flattened: weekly_churn.rate becomes
            # weekly_churn_rate rather than being lost.
            for inner, deep in value.items():
                if isinstance(deep, (int, float)) and not isinstance(deep, bool):
                    out[f"{key}_{inner}"] = float(deep)
    return out


def _labelled(raw: Any, label_key: str, value_key: str) -> tuple[Labelled, ...]:
    rows: list[Labelled] = []
    for row in raw or []:
        if not isinstance(row, Mapping):
            continue
        label, value = row.get(label_key), row.get(value_key)
        if label is None or value is None:
            continue
        try:
            rows.append(Labelled(label=str(label), value=float(value)))
        except (ValueError, TypeError):
            continue
    return tuple(rows)


def parse_cohorts(body: Mapping[str, Any]) -> CohortGrid:
    """Map the cohort matrix, tolerating gaps.

    A cohort reports only the offsets it has cells for, so a missing offset is
    a genuine absence of activity rather than an error — it stays missing
    instead of becoming a zero the grid would render as a measured value.
    """
    rows: list[CohortRow] = []
    for raw in body.get("cohorts") or []:
        if not isinstance(raw, Mapping):
            continue
        try:
            week = _as_date(raw.get("week"))
        except ValueError:
            continue
        rates: dict[int, float] = {}
        for cell in raw.get("cells") or []:
            if not isinstance(cell, Mapping):
                continue
            offset, rate = cell.get("offset"), cell.get("rate")
            if offset is None or rate is None:
                continue
            try:
                rates[int(offset)] = float(rate)
            except (ValueError, TypeError):
                continue
        rows.append(CohortRow(week=week, size=int(raw.get("size") or 0), rates=rates))
    return CohortGrid(rows=tuple(sorted(rows, key=lambda r: r.week)))
