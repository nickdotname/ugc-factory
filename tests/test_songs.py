"""Songs: each with its own track and captions, all cutting from one video pool."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from src import cli
from src.assets import MediaStore, RemoteAsset, fetch_library
from src.config import CampaignConfig, load_campaign
from src.ingest import build_plan, ensure_inbox, next_index
from src.models import PartKind
from src.queue import load_queue
from src.render import FfmpegRenderer

from tests.conftest import needs_ffmpeg


class TaggedStore(MediaStore):
    """A media store that keeps each Release in its own directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, tag: str) -> Path:
        return self.root / tag

    def download_assets(self, tag: str, dest_dir: Path) -> list[Path]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for item in sorted(self._dir(tag).iterdir()):
            shutil.copy2(item, dest_dir / item.name)
            out.append(dest_dir / item.name)
        return out

    def list_assets(self, tag: str) -> list[str]:
        folder = self._dir(tag)
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def publish(self, tag: str, files: list[Path]) -> list[RemoteAsset]:
        self._dir(tag).mkdir(parents=True, exist_ok=True)
        out = []
        for f in files:
            shutil.copy2(f, self._dir(tag) / f.name)
            out.append(RemoteAsset(
                name=f.name, url=f"https://example.test/{tag}/{f.name}",
                size_bytes=f.stat().st_size,
            ))
        return out

    def delete_assets(self, tag: str, names: list[str]) -> list[str]:
        return []

    def cleanup(self, prefix: str, older_than_days: int) -> list[str]:
        return []


CONFIG = """
slug: album
timezone: America/New_York
creatives:
  - name: first_song
    title: First Song
    assets_release: assets-album-first_song
    shared_videos: true
  - name: second_song
    title: Second Song
    assets_release: assets-album-second_song
    shared_videos: true
posting:
  posts_per_day: 6
  max_backlog_days: 1
  start_hour: 9
  end_hour: 21
  dry_run: true
video:
  preset: ultrafast
  crf: 32
composition:
  bodies_per_video: 0
  music_volume: 1.0
  clip_volume: 0.0
  music_cleared: true
  loop_to_min: true
selection:
  hook_cooldown_days: 0
  caption_cooldown_days: 0
buffer:
  api_key_secret: BUFFER_API_KEY
  channel_id: aaa111
notify:
  webhook_secret: DISCORD_WEBHOOK_E2E
""".strip()


@pytest.fixture
def album(tmp_path: Path, clips: dict[str, Path], monkeypatch) -> Path:
    """Two songs, each with its own track and captions, over three shared videos."""
    campaigns = tmp_path / "campaigns"
    slug_dir = campaigns / "album"
    slug_dir.mkdir(parents=True)
    (slug_dir / "config.yaml").write_text(CONFIG, encoding="utf-8")
    (slug_dir / "captions.txt").write_text("CAMPAIGN BANK", encoding="utf-8")
    for song in ("first_song", "second_song"):
        folder = slug_dir / "creatives" / song
        folder.mkdir(parents=True)
        (folder / "captions.txt").write_text(
            "\n---\n".join(f"about {song}, line {i}" for i in range(6)),
            encoding="utf-8",
        )

    releases = tmp_path / "releases"
    pool = releases / "assets-album"
    pool.mkdir(parents=True)
    for i in range(3):
        shutil.copy2(clips["portrait"], pool / f"hook_{i:02d}.mp4")
    for song in ("first_song", "second_song"):
        own = releases / f"assets-album-{song}"
        own.mkdir()
        shutil.copy2(clips["music_long"], own / f"music_{song}_01.mp3")

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cli, "CAMPAIGNS_DIR", campaigns)
    monkeypatch.setattr(cli, "_build_store", lambda env, log, clock: TaggedStore(releases))
    return slug_dir


class TestConfig:
    def test_a_song_takes_videos_from_the_campaign_and_music_from_itself(
        self, album: Path
    ) -> None:
        config = load_campaign(album.parent, "album")
        song = config.creatives[0]
        assert config.creative_video_tag(song) == "assets-album"
        assert config.creative_assets_tag(song) == "assets-album-first_song"

    def test_a_set_with_its_own_videos_is_unchanged(self, config: CampaignConfig) -> None:
        only = config.creatives[0]
        assert config.creative_video_tag(only) == config.creative_assets_tag(only)

    def test_sharing_videos_needs_somewhere_to_keep_the_track(self, album: Path) -> None:
        text = CONFIG.replace("    assets_release: assets-album-first_song\n", "")
        (album / "config.yaml").write_text(text, encoding="utf-8")
        with pytest.raises((ValidationError, Exception), match="shared_videos"):
            load_campaign(album.parent, "album")


class TestFetchLibrary:
    def test_videos_come_from_the_pool_and_music_from_the_song(
        self, album: Path, tmp_path: Path
    ) -> None:
        store = TaggedStore(tmp_path / "releases")
        lib = fetch_library(
            store, tmp_path / "work", "first_song",
            "assets-album-first_song", "assets-album",
        )
        assert [p.name for p in lib.hooks] == ["hook_00.mp4", "hook_01.mp4", "hook_02.mp4"]
        assert [p.name for p in lib.music] == ["music_first_song_01.mp3"]

    def test_a_song_with_no_track_yet_is_empty_not_an_error(
        self, album: Path, tmp_path: Path
    ) -> None:
        store = TaggedStore(tmp_path / "releases")
        lib = fetch_library(
            store, tmp_path / "work", "third", "assets-album-third", "assets-album"
        )
        assert len(lib.hooks) == 3 and lib.music == ()


class TestNaming:
    def test_a_songs_tracks_carry_its_name(self) -> None:
        have = ["music_01.mp3", "music_first_song_01.mp3", "music_first_song_02.mp3"]
        assert next_index(have, PartKind.MUSIC, "first_song") == 3
        assert next_index(have, PartKind.MUSIC, "second_song") == 1
        assert next_index(have, PartKind.MUSIC) == 2

    @needs_ffmpeg
    def test_a_plan_can_take_only_some_roles(
        self, tmp_path: Path, clips: dict[str, Path], config, logger
    ) -> None:
        inbox = tmp_path / "inbox"
        ensure_inbox(inbox)
        shutil.copy2(clips["portrait"], inbox / "hooks" / "a.mp4")
        shutil.copy2(clips["music_short"], inbox / "music" / "a.mp3")
        renderer = FfmpegRenderer(config, logger)

        music = build_plan(
            inbox, [], renderer, logger, kinds=(PartKind.MUSIC,), music_label="first_song"
        )
        assert [c.target_name for c in music.candidates] == ["music_first_song_01.mp3"]
        videos = build_plan(inbox, [], renderer, logger, kinds=(PartKind.HOOK, PartKind.BODY))
        assert [c.target_name for c in videos.candidates] == ["hook_01.mp4"]


def _ingest(tmp_path: Path, creative: str) -> int:
    return cli.cmd_ingest(
        argparse.Namespace(
            command="ingest", campaign="album", creative=creative, dry_run=False,
            report=str(tmp_path / "ingest.json"),
        ),
        {},
    )


@needs_ffmpeg
class TestIngest:
    def test_videos_join_the_pool_and_the_track_stays_with_its_song(
        self, album: Path, tmp_path: Path, clips: dict[str, Path]
    ) -> None:
        pool_inbox = tmp_path / "inbox" / "album"
        song_inbox = tmp_path / "inbox" / "album-second_song"
        ensure_inbox(pool_inbox)
        ensure_inbox(song_inbox)
        shutil.copy2(clips["portrait"], pool_inbox / "hooks" / "1a2b3c4d__new clip.mp4")
        shutil.copy2(clips["music_long"], song_inbox / "music" / "5e6f7a8b__chorus.mp3")

        assert _ingest(tmp_path, "second_song") == 0

        releases = tmp_path / "releases"
        assert "hook_03.mp4" in {p.name for p in (releases / "assets-album").iterdir()}
        assert {p.name for p in (releases / "assets-album-second_song").iterdir()} == {
            "music_second_song_01.mp3", "music_second_song_02.mp3",
        }
        # The other song's library is untouched, but sees the new video.
        assert len(list((releases / "assets-album-first_song").iterdir())) == 1

        report = json.loads((tmp_path / "ingest.json").read_text())
        assert {(r["inbox"], r["asset"], r["verdict"]) for r in report} == {
            ("album", "hook__1a2b3c4d__new clip.mp4", "ok"),
            ("album-second_song", "music__5e6f7a8b__chorus.mp3", "ok"),
        }

    def test_a_refused_file_is_reported_with_its_reason(
        self, album: Path, tmp_path: Path
    ) -> None:
        pool_inbox = tmp_path / "inbox" / "album"
        ensure_inbox(pool_inbox)
        (pool_inbox / "hooks" / "1a2b3c4d__not a video.mp4").write_bytes(b"nope")

        assert _ingest(tmp_path, "first_song") == 1

        (row,) = json.loads((tmp_path / "ingest.json").read_text())
        assert row["verdict"] == "rejected" and row["notes"]
        assert row["asset"] == "hook__1a2b3c4d__not a video.mp4"


@needs_ffmpeg
class TestRender:
    def test_every_post_pairs_a_song_with_its_own_captions_over_a_pooled_video(
        self, album: Path
    ) -> None:
        code = cli.cmd_render(
            argparse.Namespace(
                command="render", campaign="album", dry_run=True, count=None, plan=False
            ),
            {},
        )
        assert code == 0
        items = load_queue(album / "queue.json").items
        assert len(items) == 6
        seen = set()
        for item in items:
            song = item.creative
            seen.add(song)
            assert item.parts["music"] == f"music_{song}_01.mp3"
            assert item.caption.startswith(f"about {song}")
            assert item.parts["hook"] in {"hook_00.mp4", "hook_01.mp4", "hook_02.mp4"}
        assert seen == {"first_song", "second_song"}
