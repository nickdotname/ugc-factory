"""Direct YouTube publishing, against replayed responses.

No test here touches the network. The shapes are the ones Google documents
for the token endpoint, the resumable upload protocol, videos.list and the
error envelope.
"""

from __future__ import annotations

import io
import itertools
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.accounts import AccountConfig, AccountsConfig, Provider
from src.config import PostType, YOUTUBE_TOKEN_SLOTS
from src.errors import ConfigError, InvalidPostError
from src.logging import StructuredLogger
from src.platforms import Service
from src.publishers import DIRECT_PROVIDERS, real_publisher
from src.publishers.base import PublishRequest
from src.publishers.instagram import FAILED, PUBLISHED, PUBLISHING, QUEUED, Outbox
from src.publishers import youtube
from src.publishers.youtube import (
    QUOTA_FILE,
    TOKEN_URL,
    UPLOAD_URL,
    QuotaLedger,
    YouTubePublisher,
    description_for,
    hashtags_to_tags,
    short_title,
)

from tests.fakes import FakeResponse, FakeSession

NOW = datetime(2026, 11, 27, 3, 0, tzinfo=timezone.utc)   # 19:00 Pacific, Nov 26
CHANNEL = "UCabcdefghijklmnopqrstuv"
OTHER = "UCzyxwvutsrqponmlkjihgfe"
SESSION_URL = "https://upload.test/session/1"
#: Distinct from UPLOAD_URL, which also ends in youtube/v3/videos.
API_VIDEOS = "www.googleapis.com/youtube/v3/videos"
_N = itertools.count()


def make(tmp_path: Path, session: FakeSession, *, now=NOW, **kw):
    clock = {"now": now}
    stream = io.StringIO()
    publisher = YouTubePublisher(
        "refresh-secret-value",
        StructuredLogger({}, stream),
        client_id="cid", client_secret="csecret",
        outbox_dir=tmp_path / "outbox",
        token_secret="YT_REFRESH_TOKEN_3",
        session=session,
        sleep=lambda _s: None,
        now=lambda: clock["now"],
        download_dir=tmp_path / "dl",
        **kw,
    )
    return publisher, clock, stream


def events(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def request(**kw) -> PublishRequest:
    base = dict(
        channel_id=CHANNEL,
        title="the fear is the point",
        text="Talk — Close Quarters\n#closequarters #indie #education",
        first_comment="Talk, from EDUCATION (2026)",
        video_url=f"https://example.test/v/render-y/{next(_N)}.mp4",
        scheduled_for=NOW - timedelta(minutes=1),
        post_type=PostType.SHORT,
        service=Service.YOUTUBE,
    )
    base.update(kw)
    return PublishRequest(**base)  # type: ignore[arg-type]


def _range_end(call) -> tuple[int, int, int] | None:
    header = call.kwargs["headers"].get("Content-Range", "")
    m = re.match(r"bytes (\d+)-(\d+)/(\d+)", header)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def happy(session: FakeSession, *, size: int = 2500, status: str = "processed") -> FakeSession:
    session.route("POST", TOKEN_URL, FakeResponse(200, {"access_token": "at-1", "expires_in": 3600}))
    session.route("GET", "example.test/v/", FakeResponse(200, content=b"v" * size))
    session.route("POST", UPLOAD_URL, FakeResponse(200, {}, headers={"Location": SESSION_URL}))

    def put(call):
        header = call.kwargs["headers"].get("Content-Range", "")
        if header.startswith("bytes */"):
            return FakeResponse(308, {}, headers={})          # nothing held yet
        start, end, total = _range_end(call)
        if end + 1 >= total:
            return FakeResponse(200, {"id": "vid-1", "kind": "youtube#video"})
        return FakeResponse(308, {}, headers={"Range": f"bytes=0-{end}"})

    session.route("PUT", SESSION_URL, put)
    session.route("GET", API_VIDEOS, FakeResponse(200, {
        "items": [{"id": "vid-1", "status": {"uploadStatus": status}}],
    }))
    return session


# ----------------------------------------------------------------- helpers


def test_hashtags_become_tags_deduplicated_and_budgeted():
    assert hashtags_to_tags("x #One #two #one #Three") == ["One", "two", "Three"]
    assert hashtags_to_tags("#" + "a" * 600) == []
    assert hashtags_to_tags("no tags here, not even C#") == []


def test_description_carries_the_first_comment_and_stays_legal():
    text = description_for("caption <b>", "Talk — Close Quarters")
    assert text == "caption (b)\n\nTalk — Close Quarters"
    assert len(description_for("x" * 4990, "y" * 100)) == 5000
    assert description_for("caption", None) == "caption"


def test_title_is_capped_and_falls_back_to_the_first_line():
    assert short_title("a" * 120, "x") == "a" * 100
    assert short_title(None, "\n first line <3\nsecond") == "first line (3"
    assert short_title("", "") == "Untitled"


# -------------------------------------------------------------- the outbox


def test_create_post_holds_the_post_and_contacts_nothing(tmp_path):
    session = FakeSession()
    publisher, _, _ = make(tmp_path, session)
    result = publisher.create_post(request(scheduled_for=NOW + timedelta(hours=3)))
    assert session.calls == []
    assert result.post_id.startswith("yto-")
    state = publisher.queue_state(CHANNEL)
    assert state.depth == 1 and state.next_due == NOW + timedelta(hours=3)
    assert publisher.scheduled_slots(CHANNEL) == [NOW + timedelta(hours=3)]
    assert publisher.find_scheduled_post(CHANNEL, NOW + timedelta(hours=3)).post_id == result.post_id
    # Instagram's outbox shares the folder and must not see this file.
    assert Outbox(tmp_path / "outbox").items() == []


def test_the_wrong_service_or_a_missing_title_is_refused(tmp_path):
    publisher, _, _ = make(tmp_path, FakeSession())
    with pytest.raises(InvalidPostError):
        publisher.create_post(request(service=Service.INSTAGRAM, post_type=PostType.REEL, title=None))
    with pytest.raises(ValueError):          # PublishRequest itself refuses an untitled YouTube post
        request(title=None)


def test_same_video_is_held_once_per_channel(tmp_path):
    publisher, _, _ = make(tmp_path, FakeSession())
    first = publisher.create_post(request(video_url="https://example.test/v/same.mp4"))
    again = publisher.create_post(request(video_url="https://example.test/v/same.mp4"))
    assert again.post_id == first.post_id
    assert publisher.queue_state(CHANNEL).depth == 1


def test_cancel_only_before_it_goes_out(tmp_path):
    session = happy(FakeSession())
    publisher, _, _ = make(tmp_path, session)
    held = publisher.create_post(request(scheduled_for=NOW + timedelta(hours=1)))
    publisher.delete_post(held.post_id)
    assert publisher.queue_state(CHANNEL).depth == 0
    sent = publisher.create_post(request())
    publisher.publish_due()
    with pytest.raises(Exception, match="already gone"):
        publisher.delete_post(sent.post_id)


# ------------------------------------------------------------- publishing


def test_due_post_is_uploaded_in_chunks_and_never_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "CHUNK_SIZE", 1024)
    session = happy(FakeSession(), size=2500)
    publisher, _, stream = make(tmp_path, session)
    post = publisher.create_post(request(notify_subscribers=True))

    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED]
    item = changed[0]
    assert item["video_id"] == "vid-1" and item["processing"] == "processed"
    assert "upload_url" not in item

    # The token: refreshed once, through the body, never the URL; then reused.
    tokens = session.calls_to(TOKEN_URL)
    assert len(tokens) == 1
    assert tokens[0].kwargs["data"]["grant_type"] == "refresh_token"
    assert tokens[0].kwargs["data"]["refresh_token"] == "refresh-secret-value"
    assert "refresh-secret-value" not in tokens[0].url

    # The resumable init: metadata and the per-request switches.
    init = session.calls_to(UPLOAD_URL)[0]
    assert init.kwargs["params"] == {
        "uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "true",
    }
    assert init.kwargs["headers"]["Authorization"] == "Bearer at-1"
    assert init.kwargs["headers"]["X-Upload-Content-Length"] == "2500"
    body = init.kwargs["json"]
    assert body["snippet"]["title"] == "the fear is the point"
    assert body["snippet"]["description"].endswith("\n\nTalk, from EDUCATION (2026)")
    assert body["snippet"]["tags"] == ["closequarters", "indie", "education"]
    assert body["snippet"]["categoryId"] == "10"
    assert body["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "embeddable": True}

    # The bytes: a status probe, then three chunks with the right ranges.
    puts = session.calls_to(SESSION_URL)
    assert puts[0].kwargs["headers"]["Content-Range"] == "bytes */2500"
    assert [_range_end(c) for c in puts[1:]] == [(0, 1023, 2500), (1024, 2047, 2500), (2048, 2499, 2500)]
    assert sum(len(c.kwargs["data"]) for c in puts[1:]) == 2500

    # Processing was asked about, by id.
    poll = session.calls_to(API_VIDEOS)[0]
    assert poll.kwargs["params"] == {"part": "status,processingDetails", "id": "vid-1"}

    # The ledger: one upload, its units plus the one poll, under YouTube's day.
    ledger = json.loads((tmp_path / "outbox" / QUOTA_FILE).read_text())
    assert ledger == {"day": "2026-11-26", "uploads": 1, "units": 1601}

    before = len(session.calls)
    assert publisher.publish_due() == []
    assert len(session.calls) == before
    assert publisher.find_scheduled_post(CHANNEL, NOW - timedelta(minutes=1)).post_id == post.post_id
    assert not list((tmp_path / "dl").glob("*.mp4")), "the downloaded file is cleaned up"
    assert "youtube_post_published" in {e["event"] for e in events(stream)}


def test_the_claim_is_committed_before_the_bytes_go(tmp_path):
    session = happy(FakeSession())
    publisher, _, _ = make(tmp_path, session)
    publisher.create_post(request())
    seen: list[tuple[str, str, int]] = []

    def checkpoint(path: Path, what: str) -> None:
        state = json.loads(path.read_text())["status"]
        seen.append((what, state, len(session.calls_to(SESSION_URL))))

    publisher.checkpoint = checkpoint
    publisher.publish_due()
    assert seen[0] == ("claim", PUBLISHING, 0)
    assert seen[1][:2] == ("sent", PUBLISHED)


def test_a_half_sent_upload_is_resumed_not_restarted(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "CHUNK_SIZE", 1024)
    session = happy(FakeSession(), size=2500)

    def put(call):
        header = call.kwargs["headers"].get("Content-Range", "")
        if header.startswith("bytes */"):
            return FakeResponse(308, {}, headers={"Range": "bytes=0-1023"})   # the last run got this far
        start, end, total = _range_end(call)
        if end + 1 >= total:
            return FakeResponse(200, {"id": "vid-1"})
        return FakeResponse(308, {}, headers={"Range": f"bytes=0-{end}"})

    session.route("PUT", SESSION_URL, put)
    publisher, _, _ = make(tmp_path, session)
    held = publisher.create_post(request())
    item = publisher.outbox.load(held.post_id)
    item.update(status=PUBLISHING, upload_url=SESSION_URL, upload_size=2500)
    publisher.outbox.save(item)

    changed = publisher.publish_due()
    assert changed[0]["status"] == PUBLISHED and changed[0]["video_id"] == "vid-1"
    assert session.calls_to(UPLOAD_URL) == [], "no second insert"
    puts = session.calls_to(SESSION_URL)
    assert [_range_end(c) for c in puts[1:]] == [(1024, 2047, 2500), (2048, 2499, 2500)]
    ledger = json.loads((tmp_path / "outbox" / QUOTA_FILE).read_text())
    assert ledger["uploads"] == 0, "the insert was charged on the run that opened the session"


def test_processing_is_polled_until_done(tmp_path):
    answers = iter(["uploaded", "uploaded", "processed"])
    session = happy(FakeSession())
    session.route("GET", API_VIDEOS, lambda _c: FakeResponse(200, {
        "items": [{"id": "vid-1", "status": {"uploadStatus": next(answers)}}],
    }))
    slept: list[float] = []
    publisher, _, _ = make(tmp_path, session)
    publisher._sleep = slept.append
    publisher.create_post(request())
    changed = publisher.publish_due()
    assert changed[0]["status"] == PUBLISHED and changed[0]["processing"] == "processed"
    assert len(session.calls_to(API_VIDEOS)) == 3
    assert slept == [youtube.POLL_INTERVAL_SEC] * 2


def test_a_rejected_video_is_recorded_as_failed_with_its_id(tmp_path):
    session = happy(FakeSession())
    session.route("GET", API_VIDEOS, FakeResponse(200, {
        "items": [{"id": "vid-1", "status": {"uploadStatus": "rejected", "rejectionReason": "duplicate"}}],
    }))
    publisher, _, stream = make(tmp_path, session)
    publisher.create_post(request())
    changed = publisher.publish_due()
    assert changed[0]["status"] == FAILED
    assert changed[0]["video_id"] == "vid-1"
    assert "duplicate" in changed[0]["error"]
    assert "youtube_processing_failed" in {e["event"] for e in events(stream)}
    assert publisher.publish_due() == [], "a failed upload is not sent again"


def test_still_processing_after_the_polls_is_left_as_published(tmp_path):
    session = happy(FakeSession(), status="uploaded")
    publisher, _, stream = make(tmp_path, session)
    publisher.create_post(request())
    changed = publisher.publish_due()
    assert changed[0]["status"] == PUBLISHED and changed[0]["processing"] == "uploaded"
    assert len(session.calls_to(API_VIDEOS)) == youtube.POLL_ATTEMPTS
    assert "youtube_still_processing" in {e["event"] for e in events(stream)}


def test_a_post_long_past_its_slot_is_not_sent(tmp_path):
    session = happy(FakeSession())
    publisher, _, _ = make(tmp_path, session)
    publisher.create_post(request(scheduled_for=NOW - timedelta(hours=7)))
    changed = publisher.publish_due()
    assert changed[0]["status"] == FAILED and "missed its slot" in changed[0]["error"]
    assert session.calls_to(UPLOAD_URL) == []


def test_one_per_channel_per_run_oldest_first(tmp_path):
    session = happy(FakeSession())
    publisher, _, _ = make(tmp_path, session)
    publisher.create_post(request(scheduled_for=NOW - timedelta(minutes=30)))
    publisher.create_post(request(scheduled_for=NOW - timedelta(minutes=5)))
    publisher.create_post(request(channel_id=OTHER))
    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED, PUBLISHED]
    assert {i["channel_id"] for i in changed} == {CHANNEL, OTHER}
    assert publisher.queue_state(CHANNEL).depth == 1


# ------------------------------------------------------------------ quota


def test_the_daily_cap_stops_uploads_and_logs_quota_exhausted(tmp_path):
    session = happy(FakeSession())
    publisher, _, stream = make(tmp_path, session, daily_uploads=1)
    publisher.create_post(request(scheduled_for=NOW - timedelta(minutes=30)))
    publisher.create_post(request(channel_id=OTHER))
    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED, QUEUED]
    assert "daily YouTube cap" in changed[1]["error"]
    names = [e["event"] for e in events(stream)]
    assert "quota_exhausted" in names and "youtube_quota_refused" in names
    assert len(session.calls_to(UPLOAD_URL)) == 1
    again = publisher.publish_due()
    assert [i["status"] for i in again] == [QUEUED], "still capped: left for tomorrow"
    assert again[0]["attempts"] == 0, "waiting on quota is not an attempt"
    assert len(session.calls_to(UPLOAD_URL)) == 1


def test_the_ledger_rolls_over_at_midnight_pacific(tmp_path):
    ledger = QuotaLedger(tmp_path / "q.json", daily_uploads=1, daily_units=10_000)
    ledger.charge(NOW, 1600, upload=True)
    assert not ledger.can_upload(NOW)
    assert not ledger.can_upload(NOW + timedelta(hours=4))        # 23:00 Pacific, same day
    assert ledger.can_upload(NOW + timedelta(hours=6))            # 01:00 Pacific, next day
    assert ledger.load(NOW + timedelta(hours=6)) == {"day": "2026-11-27", "uploads": 0, "units": 0}


def test_a_units_ceiling_also_holds(tmp_path):
    ledger = QuotaLedger(tmp_path / "q.json", daily_uploads=100, daily_units=3000)
    ledger.charge(NOW, 1600, upload=True)
    assert not ledger.can_upload(NOW)


def test_youtubes_own_quota_refusal_waits_for_the_next_slot(tmp_path):
    session = happy(FakeSession())
    refusal = FakeResponse(403, {"error": {"code": 403, "message": "quota", "errors": [
        {"reason": "quotaExceeded", "domain": "youtube.quota"}]}})
    session.route("POST", UPLOAD_URL, refusal)
    publisher, _, stream = make(tmp_path, session)
    publisher.create_post(request())
    changed = publisher.publish_due()
    assert changed[0]["status"] == QUEUED and "quota" in changed[0]["error"]
    assert "youtube_quota_refused" in {e["event"] for e in events(stream)}

    session.route("POST", UPLOAD_URL, FakeResponse(200, {}, headers={"Location": SESSION_URL}))
    changed = publisher.publish_due()
    assert changed[0]["status"] == PUBLISHED


def test_upload_limit_exceeded_is_the_same_wait(tmp_path):
    session = happy(FakeSession())
    session.route("POST", UPLOAD_URL, FakeResponse(403, {"error": {"errors": [
        {"reason": "uploadLimitExceeded"}], "message": "The user has exceeded the number of videos they may upload."}}))
    publisher, _, _ = make(tmp_path, session)
    publisher.create_post(request())
    assert publisher.publish_due()[0]["status"] == QUEUED


# ----------------------------------------------------------------- re-auth


def test_a_dead_refresh_token_blocks_the_channel_and_names_the_secret(tmp_path):
    session = happy(FakeSession())
    session.route("POST", TOKEN_URL, FakeResponse(400, {
        "error": "invalid_grant", "error_description": "Token has been expired or revoked.",
    }))
    publisher, _, stream = make(tmp_path, session)
    publisher.create_post(request())
    publisher.create_post(request(channel_id=OTHER))
    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [QUEUED]
    assert "YT_REFRESH_TOKEN_3" in changed[0]["error"]
    assert publisher.reauth_needed
    reauth = [e for e in events(stream) if e["event"] == "youtube_reauth_needed"]
    assert reauth and reauth[0]["secret"] == "YT_REFRESH_TOKEN_3"
    assert "refresh-secret-value" not in stream.getvalue()
    assert session.calls_to(UPLOAD_URL) == [], "nothing is tried without a token"
    assert len(session.calls_to(TOKEN_URL)) == 1, "the second channel is skipped, not retried"


def test_a_forbidden_answer_from_the_api_is_a_reauth_too(tmp_path):
    session = happy(FakeSession())
    session.route("POST", UPLOAD_URL, FakeResponse(403, {"error": {"errors": [
        {"reason": "forbidden"}], "message": "Forbidden"}}))
    publisher, _, stream = make(tmp_path, session)
    publisher.create_post(request())
    changed = publisher.publish_due()
    assert changed[0]["status"] == QUEUED and publisher.reauth_needed
    assert "youtube_reauth_needed" in {e["event"] for e in events(stream)}
    assert "youtube_channel_blocked" in {e["event"] for e in events(stream)}


def test_a_dropped_connection_is_retried_with_the_same_headers(tmp_path):
    import requests

    session = happy(FakeSession())
    inner = session._routes[:]            # the PUT handler registered by happy()
    dropped = {"done": False}

    def flaky(call):
        if not dropped["done"]:
            dropped["done"] = True
            raise requests.ConnectionError("reset")
        for m, fragment, handler in inner:
            if m == "PUT" and fragment in call.url:
                return handler(call)
        raise AssertionError("unrouted")

    session.route("PUT", SESSION_URL, flaky)
    publisher, _, _ = make(tmp_path, session)
    publisher.create_post(request())
    assert publisher.publish_due()[0]["status"] == PUBLISHED
    puts = session.calls_to(SESSION_URL)
    assert puts[0].kwargs["headers"]["Content-Range"] == puts[1].kwargs["headers"]["Content-Range"] == "bytes */2500"


def test_a_server_error_is_retried_then_given_up(tmp_path):
    session = happy(FakeSession())
    session.route("POST", UPLOAD_URL, FakeResponse(503, {"error": {"message": "backend"}}))
    publisher, _, _ = make(tmp_path, session)
    publisher.create_post(request())
    for _ in range(2):
        assert publisher.publish_due()[0]["status"] == QUEUED
    assert publisher.publish_due()[0]["status"] == FAILED


# ---------------------------------------------------------------- figures


def test_statistics_map_into_post_metrics(tmp_path):
    session = happy(FakeSession())
    publisher, clock, _ = make(tmp_path, session)
    publisher.create_post(request())
    publisher.publish_due()
    session.route("GET", API_VIDEOS, FakeResponse(200, {"items": [{
        "id": "vid-1",
        "statistics": {"viewCount": "1234", "likeCount": "56", "commentCount": "7", "favoriteCount": "0"},
    }]}))
    posts = publisher.fetch_post_metrics(CHANNEL)
    assert len(posts) == 1
    post = posts[0]
    assert post.service == "youtube" and post.sent_at == NOW
    assert post.value("views") == 1234.0
    assert post.value("reactions") == 56.0
    assert post.value("comments") == 7.0
    assert post.value("totalTimeWatched") is None, "watch time is the Analytics API: not here"
    call = session.calls_to(API_VIDEOS)[-1]
    assert call.kwargs["params"] == {"part": "statistics", "id": "vid-1"}

    rows, fresh = publisher.fetch_metrics(CHANNEL, NOW - timedelta(hours=1), NOW + timedelta(hours=1))
    assert {r.type: r.value for r in rows} == {"views": 1234.0, "reactions": 56.0, "comments": 7.0}
    assert fresh == NOW
    assert publisher.fetch_metrics(CHANNEL, NOW + timedelta(days=1), NOW + timedelta(days=2))[0] == []


def test_hidden_likes_are_absent_not_zero(tmp_path):
    session = happy(FakeSession())
    publisher, _, _ = make(tmp_path, session)
    publisher.create_post(request())
    publisher.publish_due()
    session.route("GET", API_VIDEOS, FakeResponse(200, {"items": [{
        "id": "vid-1", "statistics": {"viewCount": "10", "commentCount": "0"},
    }]}))
    post = publisher.fetch_post_metrics(CHANNEL)[0]
    assert post.value("views") == 10.0 and post.value("reactions") is None


# ------------------------------------------------------------ the factory


def _account(**kw) -> AccountConfig:
    base = dict(
        name="rotation_yt", network="youtube", provider="youtube",
        api_key_secret="YT_REFRESH_TOKEN_1", channel_id=CHANNEL,
        post_type="short", title_strategy="require",
    )
    base.update(kw)
    return AccountConfig.model_validate(base)


def test_accounts_accept_a_youtube_provider_on_its_slots():
    account = _account()
    assert account.provider is Provider.YOUTUBE and account.provider in DIRECT_PROVIDERS
    assert YOUTUBE_TOKEN_SLOTS[0] == "YT_REFRESH_TOKEN_1" and len(YOUTUBE_TOKEN_SLOTS) == 16
    with pytest.raises(ValueError, match="api_key_secret must be one of"):
        _account(api_key_secret="IG_TOKEN")
    with pytest.raises(ValueError, match="provider youtube can only post to"):
        _account(network="instagram", post_type="reel")
    AccountsConfig.model_validate({"accounts": [_account().model_dump(mode="json")]})


def test_the_factory_builds_a_youtube_publisher_from_the_env(tmp_path):
    log = StructuredLogger({}, io.StringIO())
    env = {"YT_CLIENT_ID": "cid", "YT_CLIENT_SECRET": "cs", "YT_DAILY_UPLOADS": "40"}
    publisher = real_publisher(_account(), "rt", log, env=env, outbox_dir=tmp_path / "outbox")
    assert isinstance(publisher, YouTubePublisher)
    assert publisher.quota.daily_uploads == 40
    assert publisher._token_secret == "YT_REFRESH_TOKEN_1"
    with pytest.raises(ConfigError, match="YT_CLIENT_ID"):
        real_publisher(_account(), "rt", log, env={}, outbox_dir=tmp_path / "outbox")


def test_a_youtube_account_resolves_through_account_publishers(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src import cli

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    log = StructuredLogger({}, io.StringIO())
    config = SimpleNamespace(slug="t", posting=SimpleNamespace(dry_run=False))
    env = {"YT_REFRESH_TOKEN_1": "rt", "YT_CLIENT_ID": "cid", "YT_CLIENT_SECRET": "cs", "YT_DAILY_UPLOADS": "7"}
    publishers = cli._account_publishers([_account()], config, env, log)  # type: ignore[arg-type]
    publisher = publishers["YT_REFRESH_TOKEN_1"]
    assert isinstance(publisher, YouTubePublisher)
    assert publisher.outbox.directory == tmp_path / "outbox"
    assert publisher.quota.daily_uploads == 7
    assert cli._held_post_paths(publisher) == []            # nothing written yet
    publisher.create_post(request(scheduled_for=NOW + timedelta(hours=1)))
    assert cli._held_post_paths(publisher) == [tmp_path / "outbox"]
    with pytest.raises(ConfigError, match="YT_CLIENT_ID"):
        cli._account_publishers([_account()], config, {"YT_REFRESH_TOKEN_1": "rt"}, log)  # type: ignore[arg-type]
