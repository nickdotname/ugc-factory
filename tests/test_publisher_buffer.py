"""M6 — Buffer publisher against replayed fixtures (SPEC §2.2, §13 M6).

Every Buffer response shape here was taken from the live GraphQL schema
(introspected 2026-08-12, see README §0). No test in this file touches the
network; the one live check lives in ``test_buffer_live.py`` behind an env flag
and is never part of CI.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from src.config import PostType
from src.errors import (
    AuthError,
    InvalidPostError,
    PublishError,
    QuotaError,
    RateLimitError,
)
from src.logging import StructuredLogger
from src.publishers.base import DryRunPublisher, PublishRequest
from src.publishers.buffer import BufferPublisher

from tests.fakes import FakeResponse, FakeSession

DUE = datetime(2026, 8, 13, 13, 0, tzinfo=timezone.utc)


def make_publisher(session: FakeSession, **kw) -> BufferPublisher:
    return BufferPublisher(
        "fake-key",
        StructuredLogger({}, io.StringIO()),
        organization_id=kw.pop("organization_id", "org-123"),
        session=session,
        sleep=lambda _s: None,
        **kw,
    )


def request(**kw) -> PublishRequest:
    base = dict(
        channel_id="chan-abcd1234",
        text="a caption",
        video_url="https://github.com/o/r/releases/download/render-x/v.mp4",
        scheduled_for=DUE,
        post_type=PostType.REEL,
    )
    base.update(kw)
    return PublishRequest(**base)  # type: ignore[arg-type]


def gql_ok(data) -> FakeResponse:
    return FakeResponse(200, {"data": data})


def create_success(post_id="post-1", scheduling="automatic") -> FakeResponse:
    return gql_ok({"createPost": {
        "__typename": "PostActionSuccess",
        "post": {"id": post_id, "dueAt": DUE.isoformat(),
                 "status": "scheduled", "schedulingType": scheduling},
    }})


def create_error(typename: str, **extra) -> FakeResponse:
    return gql_ok({"createPost": {"__typename": typename,
                                  "message": "something went wrong", **extra}})


class TestCreatePostPayload:
    """The mutation input must match the verified schema exactly."""

    def test_sends_video_as_url_asset(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", create_success())
        make_publisher(s).create_post(request())
        sent = s.calls[0].json_body["variables"]["input"]
        assert sent["assets"] == [
            {"video": {"url": "https://github.com/o/r/releases/download/render-x/v.mp4"}}
        ]

    def test_never_sends_thumbnail_url(self) -> None:
        """The schema documents that setting it makes the API reject the asset."""
        s = FakeSession().route("POST", "api.buffer.com", create_success())
        make_publisher(s).create_post(request())
        assert "thumbnailUrl" not in str(s.calls[0].json_body)

    def test_requests_automatic_scheduling(self) -> None:
        """SPEC §0 — reminder mode is not automation."""
        s = FakeSession().route("POST", "api.buffer.com", create_success())
        make_publisher(s).create_post(request())
        assert s.calls[0].json_body["variables"]["input"]["schedulingType"] == "automatic"

    def test_pins_the_slot_with_custom_scheduled_mode(self) -> None:
        """addToQueue would silently discard the computed spread."""
        s = FakeSession().route("POST", "api.buffer.com", create_success())
        make_publisher(s).create_post(request())
        sent = s.calls[0].json_body["variables"]["input"]
        assert sent["mode"] == "customScheduled"
        assert sent["dueAt"].startswith("2026-08-13T13:00")

    def test_does_not_request_approval(self) -> None:
        """needsApproval:true parks the post where no cron job can clear it."""
        s = FakeSession().route("POST", "api.buffer.com", create_success())
        make_publisher(s).create_post(request())
        assert s.calls[0].json_body["variables"]["input"]["needsApproval"] is False

    def test_sends_instagram_reel_metadata(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", create_success())
        make_publisher(s).create_post(request())
        meta = s.calls[0].json_body["variables"]["input"]["metadata"]["instagram"]
        assert meta["type"] == "reel"
        assert meta["shouldShareToFeed"] is True

    def test_share_to_feed_is_configurable(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", create_success())
        make_publisher(s).create_post(request(share_to_feed=False))
        meta = s.calls[0].json_body["variables"]["input"]["metadata"]["instagram"]
        assert meta["shouldShareToFeed"] is False

    def test_returns_the_post_id(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", create_success("post-xyz"))
        assert make_publisher(s).create_post(request()).post_id == "post-xyz"


class TestReminderModeIsAFailure:
    """SPEC §0 — the assumption the whole architecture rests on."""

    def test_notification_mode_response_raises(self) -> None:
        s = FakeSession().route(
            "POST", "api.buffer.com", create_success(scheduling="notification")
        )
        with pytest.raises(InvalidPostError, match="not 'automatic'"):
            make_publisher(s).create_post(request())

    def test_reminder_error_names_the_actual_fix(self) -> None:
        s = FakeSession().route(
            "POST", "api.buffer.com", create_success(scheduling="notification")
        )
        with pytest.raises(InvalidPostError) as exc:
            make_publisher(s).create_post(request())
        assert "Business/Creator" in str(exc.value)

    def test_reminder_mode_is_not_retryable(self) -> None:
        s = FakeSession().route(
            "POST", "api.buffer.com", create_success(scheduling="notification")
        )
        with pytest.raises(InvalidPostError) as exc:
            make_publisher(s).create_post(request())
        assert exc.value.retryable is False


class TestTypedErrorMapping:
    """SPEC §2.2 — dispatch on __typename, never on message text."""

    @pytest.mark.parametrize(
        "typename,expected,retryable",
        [
            ("UnauthorizedError", AuthError, False),
            ("InvalidInputError", InvalidPostError, False),
            ("NotFoundError", InvalidPostError, False),
            ("LimitReachedError", QuotaError, False),
            ("UnexpectedError", PublishError, True),
        ],
    )
    def test_union_member_maps_to_typed_exception(
        self, typename: str, expected: type, retryable: bool
    ) -> None:
        s = FakeSession().route("POST", "api.buffer.com", create_error(typename))
        with pytest.raises(expected) as exc:
            make_publisher(s).create_post(request())
        assert exc.value.retryable is retryable

    def test_auth_failure_is_never_retried(self) -> None:
        """SPEC §12 — alert and stop, don't drain the queue."""
        s = FakeSession().route("POST", "api.buffer.com", create_error("UnauthorizedError"))
        with pytest.raises(AuthError):
            make_publisher(s).create_post(request())
        assert len(s.calls) == 1

    def test_rest_proxy_4xx_is_not_retryable(self) -> None:
        s = FakeSession().route(
            "POST", "api.buffer.com", create_error("RestProxyError", code=400)
        )
        with pytest.raises(InvalidPostError) as exc:
            make_publisher(s).create_post(request())
        assert exc.value.retryable is False

    def test_rest_proxy_5xx_is_retryable(self) -> None:
        s = FakeSession().route(
            "POST", "api.buffer.com", create_error("RestProxyError", code=503)
        )
        with pytest.raises(PublishError) as exc:
            make_publisher(s).create_post(request())
        assert exc.value.retryable is True

    def test_unknown_union_member_fails_loud_about_schema_drift(self) -> None:
        """A new Buffer error type must not be silently treated as success."""
        s = FakeSession().route("POST", "api.buffer.com", create_error("BrandNewError"))
        with pytest.raises(PublishError, match="schema may have changed"):
            make_publisher(s).create_post(request())

    def test_success_without_post_id_is_an_error(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok(
            {"createPost": {"__typename": "PostActionSuccess", "post": {}}}
        ))
        with pytest.raises(PublishError, match="without a post id"):
            make_publisher(s).create_post(request())


class TestTransportErrors:
    def test_http_401_is_auth_error(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", FakeResponse(401))
        with pytest.raises(AuthError):
            make_publisher(s).create_post(request())

    def test_http_429_is_retried_then_raises_rate_limit(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", FakeResponse(429))
        with pytest.raises(RateLimitError):
            make_publisher(s).create_post(request())
        assert len(s.calls) == 3

    def test_http_500_is_retried(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", FakeResponse(500))
        with pytest.raises(PublishError):
            make_publisher(s).create_post(request())
        assert len(s.calls) == 3

    def test_transient_500_then_success(self) -> None:
        calls = {"n": 0}

        def handler(_r):
            calls["n"] += 1
            return FakeResponse(500) if calls["n"] == 1 else create_success()

        s = FakeSession().route("POST", "api.buffer.com", handler)
        assert make_publisher(s).create_post(request()).post_id == "post-1"

    def test_graphql_document_error_is_not_retryable(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", FakeResponse(
            200, {"errors": [{"message": 'Field "bogus" is required'}]}
        ))
        with pytest.raises(InvalidPostError, match="bogus"):
            make_publisher(s).create_post(request())
        assert len(s.calls) == 1

    def test_non_json_response_is_a_publish_error(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com",
                                FakeResponse(200, text="<html>maintenance</html>"))
        with pytest.raises(PublishError, match="non-JSON"):
            make_publisher(s).create_post(request())


class TestQueueDepth:
    def test_counts_slot_holding_posts(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": [
            {"node": {"id": f"p{i}", "status": "scheduled"}} for i in range(4)
        ]}}))
        assert make_publisher(s).queue_depth("chan-1") == 4

    def test_empty_queue_is_zero(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": []}}))
        assert make_publisher(s).queue_depth("chan-1") == 0

    def test_filters_to_scheduled_and_sending_only(self) -> None:
        """`sent` has released its slot; `draft`/`error` never held one."""
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": []}}))
        make_publisher(s).queue_depth("chan-1")
        statuses = s.calls[0].json_body["variables"]["input"]["filter"]["status"]
        assert set(statuses) == {"scheduled", "sending"}

    def test_scopes_the_query_to_one_channel(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": []}}))
        make_publisher(s).queue_depth("chan-xyz")
        assert s.calls[0].json_body["variables"]["input"]["filter"]["channelIds"] == \
            ["chan-xyz"]


class TestCrashReconciliation:
    """SPEC §11 — ask Buffer what exists before re-pushing."""

    def test_finds_an_existing_post_at_the_slot(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": [
            {"node": {"id": "already-there", "dueAt": DUE.isoformat(),
                      "status": "scheduled", "schedulingType": "automatic"}}
        ]}}))
        found = make_publisher(s).find_scheduled_post("chan-1", DUE)
        assert found is not None and found.post_id == "already-there"

    def test_returns_none_when_the_slot_is_free(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": []}}))
        assert make_publisher(s).find_scheduled_post("chan-1", DUE) is None

    def test_matches_within_a_tolerance_window(self) -> None:
        """Buffer normalises dueAt; an exact match would cause a double-push."""
        near = (DUE + timedelta(seconds=40)).isoformat()
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": [
            {"node": {"id": "close-enough", "dueAt": near,
                      "status": "scheduled", "schedulingType": "automatic"}}
        ]}}))
        found = make_publisher(s).find_scheduled_post("chan-1", DUE)
        assert found is not None and found.post_id == "close-enough"

    def test_a_post_at_a_different_hour_is_not_a_match(self) -> None:
        far = (DUE + timedelta(hours=2)).isoformat()
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": [
            {"node": {"id": "other-slot", "dueAt": far,
                      "status": "scheduled", "schedulingType": "automatic"}}
        ]}}))
        assert make_publisher(s).find_scheduled_post("chan-1", DUE) is None

    def test_no_unsupported_dueat_filter_is_sent(self) -> None:
        """`{gte, lte}` is not Buffer's DateTimeComparator shape; matching is
        done client-side so the query cannot be rejected."""
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": []}}))
        make_publisher(s).find_scheduled_post("chan-1", DUE)
        assert "dueAt" not in s.calls[0].json_body["variables"]["input"]["filter"]

    def test_posts_without_a_due_date_are_skipped(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": [
            {"node": {"id": "draft", "dueAt": None, "status": "scheduled"}}
        ]}}))
        assert make_publisher(s).find_scheduled_post("chan-1", DUE) is None

    def test_includes_sent_posts_in_reconciliation(self) -> None:
        """A post that already published still means: do not push again."""
        s = FakeSession().route("POST", "api.buffer.com", gql_ok({"posts": {"edges": []}}))
        make_publisher(s).find_scheduled_post("chan-1", DUE)
        statuses = s.calls[0].json_body["variables"]["input"]["filter"]["status"]
        assert "sent" in statuses


class TestDelete:
    def test_delete_succeeds(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok(
            {"deletePost": {"__typename": "DeletePostSuccess", "id": "p1"}}
        ))
        make_publisher(s).delete_post("p1")
        assert s.calls[0].json_body["variables"]["input"]["id"] == "p1"

    def test_delete_failure_raises(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", gql_ok(
            {"deletePost": {"__typename": "VoidMutationError", "message": "already sent"}}
        ))
        with pytest.raises(PublishError, match="already sent"):
            make_publisher(s).delete_post("p1")


class TestQuotaMetering:
    """SPEC §3 — 3,000 requests per 30 days is the ceiling to design against."""

    def test_every_request_is_counted(self) -> None:
        s = FakeSession().route("POST", "api.buffer.com", create_success())
        p = make_publisher(s)
        p.create_post(request())
        p.create_post(request())
        assert p.request_count == 2

    def test_retries_are_counted_too(self) -> None:
        """Retries spend budget; a meter that ignored them would under-report."""
        s = FakeSession().route("POST", "api.buffer.com", FakeResponse(500))
        p = make_publisher(s)
        with pytest.raises(PublishError):
            p.create_post(request())
        assert p.request_count == 3

    def test_org_lookup_is_cached(self) -> None:
        """Resolving the org on every call would waste ~1/3 of the budget."""
        s = FakeSession()
        s.route("POST", "api.buffer.com", lambda r: (
            gql_ok({"account": {"id": "a", "organizations": [{"id": "org-9", "name": "n"}]}})
            if "Account" in r.json_body["query"]
            else gql_ok({"posts": {"edges": []}})
        ))
        p = make_publisher(s, organization_id=None)
        p.queue_depth("c1")
        p.queue_depth("c1")
        account_calls = [c for c in s.calls if "Account" in c.json_body["query"]]
        assert len(account_calls) == 1


class TestConstruction:
    def test_empty_api_key_fails_loud(self) -> None:
        with pytest.raises(AuthError, match="empty"):
            BufferPublisher("", StructuredLogger({}, io.StringIO()))


class TestDryRunPublisher:
    def test_records_without_publishing(self) -> None:
        p = DryRunPublisher(StructuredLogger({}, io.StringIO()))
        result = p.create_post(request())
        assert result.post_id.startswith("dry-run-")
        assert len(p.published) == 1

    def test_reports_configurable_queue_depth(self) -> None:
        assert DryRunPublisher(StructuredLogger({}, io.StringIO()),
                               queue_depth=7).queue_depth("c") == 7

    def test_is_not_a_subclass_of_the_real_publisher(self) -> None:
        """Inheriting would risk an un-overridden method reaching the network."""
        assert not issubclass(DryRunPublisher, BufferPublisher)


class TestRedaction:
    def test_redacted_view_omits_caption_and_full_channel_id(self) -> None:
        r = request().redacted()
        assert "a caption" not in str(r)
        assert r["channel_id_suffix"] == "1234"
