"""Direct Instagram publishing, against replayed responses.

No test here touches the network. The response shapes are the ones Instagram
documents for container creation, status, publish and insights.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.accounts import AccountConfig, AccountsConfig
from src.config import PostType
from src.errors import AuthError, InvalidPostError, PublishError, QuotaError
from src.logging import StructuredLogger
from src.platforms import Service
from src.publishers.base import PublishRequest
from src.publishers.buffer import BufferPublisher
from src import cli
from src.publishers.instagram import (
    FAILED,
    PUBLISHED,
    PUBLISHING,
    QUEUED,
    InstagramPublisher,
)

from tests.fakes import FakeResponse, FakeSession

NOW = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
CHANNEL = "17841400000000000"


def make(tmp_path: Path, session: FakeSession, *, now=NOW, login="instagram"):
    clock = {"now": now}
    publisher = InstagramPublisher(
        "fake-token",
        StructuredLogger({}, io.StringIO()),
        outbox_dir=tmp_path / "outbox",
        login=login,
        session=session,
        sleep=lambda _s: None,
        now=lambda: clock["now"],
    )
    return publisher, clock


import itertools
_N = itertools.count()


def request(**kw) -> PublishRequest:
    base = dict(
        channel_id=CHANNEL,
        text="Notta Problem – Close Quarters",
        video_url=f"https://example.test/v/render-x/{next(_N)}.mp4",   # each request its own video
        scheduled_for=NOW - timedelta(minutes=1),
        post_type=PostType.REEL,
        service=Service.INSTAGRAM,
    )
    base.update(kw)
    return PublishRequest(**base)  # type: ignore[arg-type]


def happy(session: FakeSession) -> FakeSession:
    # Later routes win, and "/media" is a prefix of "/media_publish".
    session.route("POST", f"/{CHANNEL}/media", FakeResponse(200, {"id": "cont-1"}))
    session.route("POST", f"/{CHANNEL}/media_publish", FakeResponse(200, {"id": "media-9"}))
    session.route("GET", "/cont-1", FakeResponse(200, {"status_code": "FINISHED"}))
    return session


def test_create_post_holds_the_post_and_contacts_nothing(tmp_path):
    session = FakeSession()
    publisher, _ = make(tmp_path, session)
    result = publisher.create_post(request(scheduled_for=NOW + timedelta(hours=3)))

    assert session.calls == []
    assert result.post_id.startswith("igo-")
    assert result.will_publish_automatically
    state = publisher.queue_state(CHANNEL)
    assert state.depth == 1 and state.next_due == NOW + timedelta(hours=3)
    assert publisher.touched and publisher.touched[0].is_file()


def test_a_post_not_yet_due_is_left_alone(tmp_path):
    session = FakeSession()
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request(scheduled_for=NOW + timedelta(minutes=10)))
    assert publisher.publish_due() == []
    assert session.calls == []


def test_due_post_is_published_and_never_twice(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    post = publisher.create_post(request())

    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED]
    assert changed[0]["media_id"] == "media-9"
    create = [c for c in session.calls if c.url.endswith(f"/{CHANNEL}/media")][0]
    assert create.kwargs["data"]["media_type"] == "REELS"
    assert create.kwargs["data"]["share_to_feed"] == "true"
    assert "thumb_offset" not in create.kwargs["data"], "no cover asked for: Instagram's own choice"
    assert create.kwargs["headers"]["Authorization"] == "Bearer fake-token"
    assert "fake-token" not in create.url

    before = len(session.calls)
    assert publisher.publish_due() == []
    assert len(session.calls) == before
    assert publisher.queue_state(CHANNEL).depth == 0
    assert publisher.find_scheduled_post(CHANNEL, NOW - timedelta(minutes=1)).post_id == post.post_id


def test_trial_reel_and_audio_are_sent_as_instagram_expects(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session, login="facebook")
    publisher.create_post(request(
        trial=True, trial_graduation="SS_PERFORMANCE",
        audio_id="aud-7", audio_volume=1, video_volume=100,
    ))
    publisher.publish_due()
    sent = [c for c in session.calls if c.url.endswith(f"/{CHANNEL}/media")][0]
    assert "graph.facebook.com" in sent.url
    data = sent.kwargs["data"]
    assert json.loads(data["trial_params"]) == {"graduation_strategy": "SS_PERFORMANCE"}
    assert "share_to_feed" not in data
    assert json.loads(data["audio_configuration"]) == {
        "audio_id": "aud-7", "audio_volume": 1, "video_volume": 100,
    }


def test_audio_needs_facebook_login(tmp_path):
    publisher, _ = make(tmp_path, FakeSession())
    with pytest.raises(InvalidPostError, match="Facebook Login"):
        publisher.create_post(request(audio_id="aud-7"))


def test_one_post_per_account_per_run(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request(scheduled_for=NOW - timedelta(hours=2)))
    publisher.create_post(request(scheduled_for=NOW - timedelta(hours=1)))
    assert len(publisher.publish_due()) == 1
    assert publisher.queue_state(CHANNEL).depth == 1


def test_a_post_far_past_its_slot_is_not_sent(tmp_path):
    session = FakeSession()
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request(scheduled_for=NOW - timedelta(hours=9)))
    changed = publisher.publish_due()
    assert changed[0]["status"] == FAILED and "missed its slot" in changed[0]["error"]
    assert session.calls == []


def test_dead_token_stops_the_account_and_keeps_the_post(tmp_path):
    session = FakeSession()
    session.route("POST", f"/{CHANNEL}/media", FakeResponse(
        400, {"error": {"message": "Error validating access token", "code": 190}}))
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request(scheduled_for=NOW - timedelta(hours=2)))
    publisher.create_post(request(scheduled_for=NOW - timedelta(hours=1)))
    changed = publisher.publish_due()
    assert len(changed) == 1 and changed[0]["status"] == QUEUED
    assert "access token" in changed[0]["error"]
    assert len(session.calls) == 1          # no retry, and the second never tried


def test_publishing_allowance_spent_is_a_quota_error():
    err = InstagramPublisher._classify(
        400, {"message": "limit", "code": 9, "error_subcode": 2207042}, "")
    assert isinstance(err, QuotaError)
    assert isinstance(InstagramPublisher._classify(400, {"code": 190}, ""), AuthError)
    assert isinstance(InstagramPublisher._classify(400, {"code": 100}, ""), InvalidPostError)
    assert InstagramPublisher._classify(500, None, "oops").retryable


def test_crash_between_container_and_publish_does_not_double_post(tmp_path):
    session = FakeSession()
    session.route("POST", f"/{CHANNEL}/media", FakeResponse(200, {"id": "cont-1"}))
    session.route("GET", "/cont-1", FakeResponse(200, {"status_code": "IN_PROGRESS"}))
    publisher, _ = make(tmp_path, session)
    post = publisher.create_post(request())
    changed = publisher.publish_due()          # times out while processing
    assert changed[0]["status"] == PUBLISHING and changed[0]["container_id"] == "cont-1"

    # Next run: Instagram says the container already went out.
    session.route("GET", "/cont-1", FakeResponse(200, {"status_code": "PUBLISHED"}))
    publisher.publish_due()
    item = publisher.outbox.load(post.post_id)
    assert item["status"] == PUBLISHED
    assert len([c for c in session.calls if c.url.endswith("/media")]) == 1  # one container only
    assert session.calls_to("media_publish") == []


def test_video_instagram_cannot_process_fails_for_good(tmp_path):
    session = FakeSession()
    session.route("POST", f"/{CHANNEL}/media", FakeResponse(200, {"id": "cont-1"}))
    session.route("GET", "/cont-1", FakeResponse(200, {"status_code": "ERROR", "status": "bad codec"}))
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request())
    changed = publisher.publish_due()
    assert changed[0]["status"] == FAILED and "bad codec" in changed[0]["error"]


def test_delete_cancels_a_held_post_but_not_a_published_one(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    held = publisher.create_post(request(scheduled_for=NOW + timedelta(hours=1)))
    publisher.delete_post(held.post_id)
    assert publisher.queue_state(CHANNEL).depth == 0

    sent = publisher.create_post(request())
    publisher.publish_due()
    with pytest.raises(PublishError, match="already gone"):
        publisher.delete_post(sent.post_id)


def test_post_metrics_use_the_names_the_pipeline_reads(tmp_path):
    session = happy(FakeSession())
    session.route("GET", "/media-9/insights", FakeResponse(200, {"data": [
        {"name": "views", "values": [{"value": 207}]},
        {"name": "shares", "values": [{"value": 10}]},
        {"name": "saved", "values": [{"value": 6}]},
        {"name": "ig_reels_avg_watch_time", "values": [{"value": 7270}]},
    ]}))
    publisher, _ = make(tmp_path, session)
    post = publisher.create_post(request())
    publisher.publish_due()
    rows = publisher.fetch_post_metrics(CHANNEL)
    assert rows[0].post_id == post.post_id      # the id the queue recorded
    assert rows[0].value("views") == 207
    assert rows[0].value("saves") == 6
    assert rows[0].value("averageTimeWatched") == pytest.approx(7.27)


def _account(**kw) -> AccountConfig:
    base = dict(name="band_ig", network="instagram", provider="instagram",
                api_key_secret="IG_TOKEN", channel_id=CHANNEL, post_type="reel")
    base.update(kw)
    return AccountConfig.model_validate(base)


def test_account_provider_rules():
    assert _account(trial_reels=True).trial_reels
    with pytest.raises(ValueError, match="slots"):
        _account(api_key_secret="BUFFER_API_KEY")
    with pytest.raises(ValueError, match="trial_reels"):
        _account(provider="buffer", api_key_secret="BUFFER_API_KEY", trial_reels=True)
    with pytest.raises(ValueError, match="instagram network"):
        _account(network="tiktok", post_type="post")
    # An account written before providers existed still means Buffer.
    old = AccountConfig.model_validate(dict(
        name="old", network="instagram", api_key_secret="BUFFER_API_KEY",
        channel_id="c1", post_type="reel"))
    assert old.provider.value == "buffer"
    assert AccountsConfig(accounts=(old, _account())).live


def test_publisher_is_picked_by_provider():
    log = StructuredLogger({}, io.StringIO())
    assert isinstance(cli._real_publisher(_account(), "t", log), InstagramPublisher)
    old = AccountConfig.model_validate(dict(
        name="old", network="instagram", api_key_secret="BUFFER_API_KEY",
        channel_id="c1", post_type="reel"))
    assert isinstance(cli._real_publisher(old, "k", log), BufferPublisher)


def test_send_next_publishes_one_post_ahead_of_its_slot(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request(scheduled_for=NOW + timedelta(hours=5)))
    publisher.create_post(request(scheduled_for=NOW + timedelta(hours=9)))

    changed = publisher.publish_due(send_next=True)
    assert [i["status"] for i in changed] == [PUBLISHED]
    assert publisher.queue_state(CHANNEL).depth == 1          # the later one still waits
    assert publisher.publish_due() == []


def test_a_carousel_makes_one_container_per_slide_then_publishes(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    post = publisher.create_post(request())
    item = next(i for i in publisher.outbox.items() if i["id"] == post.post_id)
    item["image_urls"] = ["https://example.test/v/render-x/a.jpg", "https://example.test/v/render-x/b.jpg"]
    item["video_url"] = None
    publisher.outbox.save(item)

    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED]
    creates = [c for c in session.calls if c.url.endswith(f"/{CHANNEL}/media")]
    assert [c.kwargs["data"].get("image_url") for c in creates[:2]] == item["image_urls"]
    assert creates[2].kwargs["data"]["media_type"] == "CAROUSEL"
    assert creates[2].kwargs["data"]["children"] == "cont-1,cont-1"


def test_the_reels_sound_is_named_when_asked(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request(audio_name="Talk – Close Quarters"))
    publisher.publish_due()
    sent = [c for c in session.calls if c.url.endswith(f"/{CHANNEL}/media")][0]
    assert sent.kwargs["data"]["audio_name"] == "Talk – Close Quarters"


def test_a_catalogue_track_keeps_its_own_name(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session, login="facebook")
    publisher.create_post(request(audio_id="aud-7", audio_name="Talk – Close Quarters"))
    publisher.publish_due()
    sent = [c for c in session.calls if c.url.endswith(f"/{CHANNEL}/media")][0]
    assert "audio_name" not in sent.kwargs["data"]


def test_a_refused_sound_name_does_not_cost_the_post(tmp_path):
    session = happy(FakeSession())

    def create(call):
        if "audio_name" in call.kwargs["data"]:
            return FakeResponse(400, {"error": {
                "message": "(#100) Param audio_name is not supported", "code": 100}})
        return FakeResponse(200, {"id": "cont-1"})

    session.route("POST", f"/{CHANNEL}/media", create)
    session.route("POST", f"/{CHANNEL}/media_publish", FakeResponse(200, {"id": "media-9"}))
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request(audio_name="Talk – Close Quarters"))
    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED]
    assert changed[0]["audio_name"] is None


def test_a_carousel_is_measured_without_the_reel_only_figures(tmp_path):
    session = happy(FakeSession())

    def insights(call):
        if "ig_reels" in call.kwargs["params"]["metric"]:
            return FakeResponse(400, {"error": {
                "message": "(#100) The Media Insights API does not support the "
                           "ig_reels_avg_watch_time metric for this media product type.",
                "code": 100}})
        return FakeResponse(200, {"data": [
            {"name": "views", "values": [{"value": 88}]},
            {"name": "saved", "values": [{"value": 4}]},
        ]})

    session.route("GET", "/media-9/insights", insights)
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request())
    publisher.publish_due()
    rows = publisher.fetch_post_metrics(CHANNEL)
    assert rows[0].value("views") == 88
    assert rows[0].value("saves") == 4
    assert rows[0].value("averageTimeWatched") is None


def _with_collaborators(publisher, post_id, names):
    item = next(i for i in publisher.outbox.items() if i["id"] == post_id)
    item["collaborators"] = names
    publisher.outbox.save(item)


def test_a_collab_reel_names_its_collaborators(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    post = publisher.create_post(request())
    _with_collaborators(publisher, post.post_id, ["@close__quarters"])
    publisher.publish_due()
    sent = [c for c in session.calls if c.url.endswith(f"/{CHANNEL}/media")][0]
    assert json.loads(sent.kwargs["data"]["collaborators"]) == ["close__quarters"]


def test_a_trial_reel_never_names_collaborators(tmp_path):
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    post = publisher.create_post(request(trial=True))
    _with_collaborators(publisher, post.post_id, ["close__quarters"])
    publisher.publish_due()
    sent = [c for c in session.calls if c.url.endswith(f"/{CHANNEL}/media")][0]
    assert "collaborators" not in sent.kwargs["data"]


def test_refused_collaborators_do_not_cost_the_post(tmp_path):
    session = happy(FakeSession())

    def create(call):
        if "collaborators" in call.kwargs["data"]:
            return FakeResponse(400, {"error": {
                "message": "(#100) Invalid collaborators", "code": 100}})
        return FakeResponse(200, {"id": "cont-1"})

    session.route("POST", f"/{CHANNEL}/media", create)
    session.route("POST", f"/{CHANNEL}/media_publish", FakeResponse(200, {"id": "media-9"}))
    publisher, _ = make(tmp_path, session)
    post = publisher.create_post(request())
    _with_collaborators(publisher, post.post_id, ["close__quarters"])
    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED]
    assert changed[0]["collaborators"] is None
    assert changed[0]["collaborators_refused"] == ["close__quarters"]


def test_a_cover_frame_is_asked_for_when_set(tmp_path: Path) -> None:
    """The maths videos start on an empty grid; their cover is a later frame."""
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request(cover_at_ms=5000))
    publisher.publish_due()
    create = [c for c in session.calls if c.url.endswith(f"/{CHANNEL}/media")][0]
    assert create.kwargs["data"]["thumb_offset"] == "5000"


def test_claim_is_made_durable_before_the_post_is_sent(tmp_path):
    """The claim has to leave the runner before Instagram is asked to publish."""
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request())
    seen: list[tuple[str, str, int]] = []

    def checkpoint(path, what):
        status = json.loads(path.read_text())["status"]
        seen.append((what, status, len(session.calls_to("/media_publish"))))

    publisher.checkpoint = checkpoint
    publisher.publish_due()
    assert seen == [("claim", PUBLISHING, 0), ("sent", PUBLISHED, 1)]


def test_a_refused_claim_sends_nothing(tmp_path):
    """Another run took the post first: this one must not publish it too."""
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request())

    def checkpoint(path, what):
        raise RuntimeError("someone else changed this post")

    publisher.checkpoint = checkpoint
    with pytest.raises(RuntimeError):
        publisher.publish_due()
    assert session.calls_to("/media_publish") == []


def test_a_sent_post_survives_a_failed_record(tmp_path):
    """Once the post is out, failing to write that down must not fail the post."""
    session = happy(FakeSession())
    publisher, _ = make(tmp_path, session)
    publisher.create_post(request())

    def checkpoint(path, what):
        if what == "sent":
            raise RuntimeError("push refused")

    publisher.checkpoint = checkpoint
    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED]


def test_an_account_that_just_posted_waits_an_hour(tmp_path):
    session = happy(FakeSession())
    publisher, clock = make(tmp_path, session)
    publisher.create_post(request(scheduled_for=NOW - timedelta(minutes=30)))
    publisher.create_post(request(scheduled_for=NOW - timedelta(minutes=5)))
    assert len(publisher.publish_due()) == 1
    clock["now"] = NOW + timedelta(minutes=40)
    assert publisher.publish_due() == [], "posted 40 minutes ago: the next one waits"
    assert publisher.queue_state(CHANNEL).depth == 1
    clock["now"] = NOW + timedelta(minutes=61)
    assert [i["status"] for i in publisher.publish_due()] == [PUBLISHED]


def test_a_video_is_held_once_per_account(tmp_path):
    """Two top-ups at once (2026-11-26) booked the same video twice; the second booking returns the first."""
    publisher, _ = make(tmp_path, happy(FakeSession()))
    a = publisher.create_post(request(video_url="https://example.test/v/same.mp4", scheduled_for=NOW + timedelta(hours=2)))
    b = publisher.create_post(request(video_url="https://example.test/v/same.mp4", scheduled_for=NOW + timedelta(hours=5)))
    assert a.post_id == b.post_id
    assert publisher.queue_state(CHANNEL).depth == 1
