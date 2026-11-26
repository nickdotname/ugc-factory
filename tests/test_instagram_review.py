"""Instagram publisher changes from the 2026-11-26 review: the song's catalogue track, and insights that are denied.

Replayed responses only, the shapes Instagram documents; nothing here touches the network.
"""

from __future__ import annotations

import json
from datetime import timedelta

from tests.test_publisher_instagram import CHANNEL, PUBLISHED, FakeResponse, FakeSession, happy, make, request


def test_a_refused_catalogue_track_does_not_cost_the_post(tmp_path):
    """An account Instagram will not let attach audio (Unified login, a track not cleared) still posts the
    Reel, as named original audio, and the record keeps the id that was refused."""
    session = happy(FakeSession())

    def create(call):
        if "audio_configuration" in call.kwargs["data"]:
            return FakeResponse(400, {"error": {
                "message": "(#10) Application does not have permission for this action", "code": 10}})
        return FakeResponse(200, {"id": "cont-1"})

    session.route("POST", f"/{CHANNEL}/media", create)
    session.route("POST", f"/{CHANNEL}/media_publish", FakeResponse(200, {"id": "media-9"}))
    publisher, _ = make(tmp_path, session, login="facebook")
    publisher.create_post(request(
        audio_id="aud-7", audio_volume=1, video_volume=100, audio_name="Talk – Close Quarters",
    ))
    changed = publisher.publish_due()
    assert [i["status"] for i in changed] == [PUBLISHED]
    assert changed[0]["audio_id"] is None and changed[0]["audio_refused"] == "aud-7"
    sent = [c for c in session.calls_to(f"/{CHANNEL}/media") if c.method == "POST"]
    assert json.loads(sent[0].kwargs["data"]["audio_configuration"]) == {
        "audio_id": "aud-7", "audio_volume": 1, "video_volume": 100,
    }
    assert "audio_configuration" not in sent[1].kwargs["data"]
    assert sent[1].kwargs["data"]["audio_name"] == "Talk – Close Quarters"


def _two_published(tmp_path, session, **make_kw):
    publisher, clock = make(tmp_path, session, **make_kw)
    publisher.create_post(request())
    publisher.create_post(request())
    publisher.publish_due(min_gap=timedelta(0))
    publisher.publish_due(min_gap=timedelta(0))
    assert [i["status"] for i in publisher.outbox.items()] == [PUBLISHED, PUBLISHED]
    return publisher


NO_PERMISSION = FakeResponse(400, {"error": {
    "message": "(#10) Application does not have permission for this action", "code": 10}})
FIGURES = FakeResponse(200, {"data": [{"name": "views", "values": [{"value": 12}]}]})


def test_an_account_whose_every_post_is_refused_for_permission_is_flagged(tmp_path):
    """Ten accounts ran a week with metrics: [] and a green job (2026-11-26 review)."""
    session = happy(FakeSession())
    session.route("GET", "/media-9/insights", NO_PERMISSION)
    publisher = _two_published(tmp_path, session)
    rows = publisher.fetch_post_metrics(CHANNEL)
    assert [r.metrics for r in rows] == [(), ()]                     # as before: the rows still come back
    denied = publisher.insights_denied[CHANNEL]
    assert denied["posts"] == 2 and denied["error_class"] == "InvalidPostError" and denied["graph_code"] == 10


def test_one_readable_post_means_the_token_can_read_and_nothing_is_flagged(tmp_path):
    session = happy(FakeSession())
    answers = iter([NO_PERMISSION, FIGURES])
    session.route("GET", "/media-9/insights", lambda call: (
        FakeResponse(200, {"data": []}) if "reels_skip_rate" in call.kwargs["params"]["metric"] else next(answers)
    ))
    publisher = _two_published(tmp_path, session)
    publisher.fetch_post_metrics(CHANNEL)
    assert publisher.insights_denied == {}


def test_a_refusal_that_is_not_about_permission_is_not_a_denial(tmp_path):
    """A trial reel or a post too new to have figures is refused too; that is the old, harmless case."""
    session = happy(FakeSession())
    session.route("GET", "/media-9/insights", FakeResponse(400, {"error": {
        "message": "(#100) Insights are not supported for this media type", "code": 100}}))
    publisher = _two_published(tmp_path, session)
    publisher.fetch_post_metrics(CHANNEL)
    assert publisher.insights_denied == {}


def test_a_page_token_that_cannot_see_the_post_falls_back_to_the_login_token(tmp_path, monkeypatch):
    """eye.trick.lab / fourier.reveal: the Page role lacks the Insights task, Dylan's own token may not."""
    monkeypatch.setenv("IG_PAGE_TOKENS", json.dumps({CHANNEL: "page-tok"}))
    session = happy(FakeSession())

    def insights(call):
        if call.kwargs["headers"]["Authorization"] == "Bearer page-tok":
            return FakeResponse(400, {"error": {
                "message": "Unsupported get request. Object with ID 'media-9' does not exist, cannot be "
                           "loaded due to missing permissions, or does not support this operation",
                "code": 100, "error_subcode": 33}})
        return FIGURES

    session.route("GET", "/media-9/insights", insights)
    publisher = _two_published(tmp_path, session, login="facebook")
    rows = publisher.fetch_post_metrics(CHANNEL)
    assert all(any(r.type == "views" and r.value == 12 for r in post.metrics) for post in rows)
    assert publisher.insights_denied == {}
    tokens = [c.kwargs["headers"]["Authorization"] for c in session.calls_to("/media-9/insights")]
    assert tokens[:2] == ["Bearer page-tok", "Bearer fake-token"]
