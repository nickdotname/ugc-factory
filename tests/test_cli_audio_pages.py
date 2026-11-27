"""The song's audio page: topup attaches a song's catalogue id (studio/songs/<slug>/song.json `ig_audio_id`)
to Reels posted directly to Facebook-login accounts, with the video's own sound kept at full volume."""

from __future__ import annotations

import json
from pathlib import Path

from src import cli
from src.config import CampaignConfig


def _config(**creative) -> CampaignConfig:
    return CampaignConfig.model_validate({
        "slug": "audio",
        "timezone": "America/New_York",
        "creatives": [{"name": "wont_be_the_same_again", "title": "Won't Be the Same Again", **creative}],
        "buffer": {"api_key_secret": "BUFFER_API_KEY", "channel_id": "x"},
        "notify": {"webhook_secret": "DISCORD_WEBHOOK"},
    })


def _song(tmp_path: Path, monkeypatch, **fields) -> None:
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    song = tmp_path / "studio" / "songs" / "wont-be-the-same-again"
    song.mkdir(parents=True)
    (song / "song.json").write_text(json.dumps({"slug": "wont-be-the-same-again", "title": "Won't Be the Same Again", **fields}))


def test_no_catalogue_id_means_no_tag(tmp_path, monkeypatch) -> None:
    _song(tmp_path, monkeypatch)
    assert cli._song_audio(_config(), "wont_be_the_same_again") is None
    assert cli._song_audio(_config(), "no_such_song") is None


def test_the_songs_id_is_read_from_its_song_json_with_the_video_kept_loud(tmp_path, monkeypatch) -> None:
    _song(tmp_path, monkeypatch, ig_audio_id="1234567890")
    assert cli._song_audio(_config(), "wont_be_the_same_again") == {
        "audio_id": "1234567890", "audio_volume": cli.AUDIO_TAG_VOLUME, "video_volume": cli.AUDIO_TAG_VIDEO_VOLUME,
    }
    # The track has no start offset, so the video's own (windowed) song stays the sound people hear.
    assert cli.AUDIO_TAG_VIDEO_VOLUME == 100 and cli.AUDIO_TAG_VOLUME == 1


def test_song_json_may_set_the_volumes(tmp_path, monkeypatch) -> None:
    _song(tmp_path, monkeypatch, ig_audio_id="42", ig_audio_volume=50, ig_video_volume=80)
    assert cli._song_audio(_config(), "wont_be_the_same_again") == {"audio_id": "42", "audio_volume": 50, "video_volume": 80}


def test_the_creatives_own_id_wins(tmp_path, monkeypatch) -> None:
    _song(tmp_path, monkeypatch, ig_audio_id="from-song")
    assert cli._song_audio(_config(ig_audio_id="from-creative"), "wont_be_the_same_again")["audio_id"] == "from-creative"
    # And works with no song.json at all (a campaign whose songs are not studio-prepared).
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path / "elsewhere")
    assert cli._song_audio(_config(ig_audio_id="from-creative"), "wont_be_the_same_again")["audio_id"] == "from-creative"
