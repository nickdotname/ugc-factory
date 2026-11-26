"""Instagram publisher changes from the 2026-11-26 review: the song's catalogue track, and insights that are denied.

Replayed responses only, the shapes Instagram documents; nothing here touches the network.
"""

from __future__ import annotations

import json

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
