"""Music-first campaigns and hand-picked posts.

Covers what a release campaign needs that a UGC campaign never did: the song
loud and the clip silent, the song starting on an exact second, text drawn on
the picture, one clip per video, a creative (a song) with its own captions and
its own accounts, and a lineup of posts spelled out by hand.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src import cli
from src.accounts import AccountsConfig
from src.attribution import attribute
from src.config import CompositionConfig, CreativeConfig, OverlayConfig
from src.connect import plan_accounts, safe_prefix, slot_name
from src.descriptions import parse_bank
from src.errors import ConfigError
from src.lineup import Lineup, LineupEntry, due_entries, load_lineup
from src.models import History, HistoryEntry, QueueStatus
from src.publishers.base import MetricRow, PostMetrics
from src.queue import append_history, backfill_post_id, load_history, load_queue
from src.render import wrap_overlay
from src.selector import AssetLibrary

from tests.conftest import needs_ffmpeg
from tests.test_end_to_end import LocalMediaStore

UTC = timezone.utc


# --------------------------------------------------------------------- config


class TestConfig:
    def test_a_single_clip_video_is_allowed(self) -> None:
        assert CompositionConfig(bodies_per_video=0).bodies_per_video == 0

    def test_clip_volume_defaults_to_untouched(self) -> None:
        assert CompositionConfig().clip_volume == 1.0

    def test_empty_cue_list_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            CreativeConfig(name="song", music_cues={"music_01.mp3": ()})

    def test_overlay_colour_cannot_smuggle_filter_options(self) -> None:
        with pytest.raises(ValueError):
            OverlayConfig(color="white:box=1")


# ---------------------------------------------------------------- descriptions


class TestOverlayLine:
    def test_overlay_and_title_head_a_record_in_either_order(self) -> None:
        bank = parse_bank(
            "overlay: bro when it starts\ntitle: Song – Band\nthe caption\n"
            "---\n"
            "title: Other\noverlay: second line\nbody two"
        )
        assert [(d.overlay, d.title, d.body) for d in bank] == [
            ("bro when it starts", "Song – Band", "the caption"),
            ("second line", "Other", "body two"),
        ]

    def test_a_comment_header_does_not_hide_the_first_records_fields(self) -> None:
        """A header comment, a blank line, then the first record: its overlay
        and title must still be read as fields, not posted in the caption."""
        bank = parse_bank(
            "# notes about this file\n# more notes\n\n"
            "overlay: on screen\ntitle: The Title\nthe caption\n---\nsecond"
        )
        assert (bank[0].overlay, bank[0].title, bank[0].body) == (
            "on screen", "The Title", "the caption",
        )

    def test_shipped_banks_never_post_a_field_line_as_caption_text(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "campaigns"
        for path in root.glob("[!_]*/**/captions*.txt"):
            for record in parse_bank(path.read_text(encoding="utf-8")):
                assert not record.body.lower().startswith(("overlay:", "title:")), path

    def test_a_record_without_one_has_no_overlay(self) -> None:
        assert parse_bank("just a caption")[0].overlay is None

    def test_an_empty_overlay_line_is_an_error(self) -> None:
        with pytest.raises(ConfigError, match="overlay"):
            parse_bank("overlay:\ncaption")


class TestWrapOverlay:
    def test_wraps_on_word_boundaries(self) -> None:
        assert wrap_overlay("how bro starts moving when this comes on", 20) == [
            "how bro starts", "moving when this", "comes on",
        ]

    def test_a_pipe_forces_a_break(self) -> None:
        assert wrap_overlay("top line | bottom line", 40) == ["top line", "bottom line"]

    def test_emoji_are_dropped_rather_than_drawn_as_boxes(self) -> None:
        assert wrap_overlay("it's 2am ✨🔥", 40) == ["it's 2am"]


# -------------------------------------------------------------------- selector


class TestCues:
    def _library(self, **kw) -> AssetLibrary:
        return AssetLibrary(
            hooks=("hook_01.mp4",), bodies=(), music=("music_01.mp3",),
            captions=("c",), bodies_required=False, **kw,
        )

    def test_a_cued_track_starts_only_at_its_cues(self) -> None:
        library = self._library(
            music_cues={"music_01.mp3": (42.5, 73.0)},
            music_durations={"music_01.mp3": 200.0},
        )
        assert library.segments_for("music_01.mp3") == 2
        assert [library.offset_for("music_01.mp3", i) for i in range(2)] == [42.5, 73.0]

    def test_an_uncued_track_keeps_the_grid(self) -> None:
        library = self._library(music_durations={"music_01.mp3": 60.0})
        assert library.segments_for("music_01.mp3") == 4

    def test_a_library_with_no_bodies_is_valid_for_single_clip_videos(self) -> None:
        library = self._library()
        library.validate()
        assert library.ceiling(0) == 1


# ---------------------------------------------------------------------- lineup


class TestLineup:
    def test_duplicate_ids_are_rejected(self) -> None:
        entry = {"id": "a", "hook": "hook_01.mp4", "caption": "c"}
        with pytest.raises(ValueError, match="twice"):
            Lineup.model_validate({"posts": [entry, entry]})

    def test_missing_file_is_an_empty_lineup(self, tmp_path: Path) -> None:
        assert load_lineup(tmp_path / "lineup.yaml").posts == ()

    def test_unknown_keys_fail_loudly(self, tmp_path: Path) -> None:
        path = tmp_path / "lineup.yaml"
        path.write_text("posts:\n  - id: a\n    hook: h.mp4\n    caption: c\n    musik: x\n")
        with pytest.raises(ConfigError):
            load_lineup(path)

    def test_due_and_missed(self) -> None:
        zone = ZoneInfo("America/New_York")
        now = datetime(2026, 11, 12, 12, 0, tzinfo=zone)

        def entry(id_: str, at: datetime | None = None, **kw) -> LineupEntry:
            return LineupEntry(id=id_, hook="h.mp4", caption="c", at=at, **kw)

        lineup = Lineup(posts=(
            entry("done"),
            entry("untimed"),
            entry("soon", datetime(2026, 11, 13, 18, 0)),
            entry("far", datetime(2026, 11, 20, 18, 0)),
            entry("past", datetime(2026, 11, 11, 18, 0)),
            entry("held", skip=True),
        ))
        due, missed = due_entries(
            lineup, {"done"}, now, now + timedelta(days=2), zone
        )
        assert [e.id for e in due] == ["untimed", "soon"]
        assert [e.id for e in missed] == ["past"]


# --------------------------------------------------------------------- connect


class TestConnect:
    CHANNELS = [
        {"id": "ig1", "name": "creatives.lets.create", "service": "instagram",
         "metadata": {"defaultToReminders": True}},
        {"id": "tt1", "name": "creatives.lets.create", "service": "tiktok"},
        {"id": "yt1", "name": "Creatives", "service": "youtube"},
        {"id": "x1", "name": "creatives", "service": "twitter"},
    ]

    def test_names_and_slots(self) -> None:
        assert slot_name(1) == "BUFFER_API_KEY"
        assert slot_name(3) == "BUFFER_API_KEY_3"
        assert safe_prefix("creatives.lets.create") == "creatives_lets_create"

    def test_plan_registers_each_supported_channel_once(self, tmp_path: Path) -> None:
        from src.accounts import load_accounts

        existing = AccountsConfig.model_validate({"accounts: ": []} and {"accounts": [
            {"name": "nickdotname_ig", "network": "instagram",
             "api_key_secret": "BUFFER_API_KEY", "channel_id": "old1",
             "post_type": "reel"},
        ]})
        plan = plan_accounts(
            self.CHANNELS, "org9", "BUFFER_API_KEY_3", "creatives_lets_create",
            existing,
        )
        assert [a.name for a in plan.new] == [
            "creatives_lets_create_ig", "creatives_lets_create_tt",
            "creatives_lets_create_yt",
        ]
        assert plan.new[0].reminders is True
        assert plan.unsupported == (("creatives", "twitter"),)
        # Staggered away from the account already at offset 0, and each other.
        assert len({a.slot_offset_min for a in plan.new} | {0}) == 4

        # What it writes is a registry the loader accepts.
        path = tmp_path / "accounts.yaml"
        path.write_text(
            "accounts:\n  - name: nickdotname_ig\n    network: instagram\n"
            "    api_key_secret: BUFFER_API_KEY\n    channel_id: old1\n"
            "    post_type: reel\n" + plan.yaml
        )
        loaded = load_accounts(path)
        assert len(loaded.accounts) == 4
        assert loaded.by_name("creatives_lets_create_yt").title_strategy.value == "require"

    def test_a_channel_already_registered_is_not_added_again(self) -> None:
        existing = AccountsConfig.model_validate({"accounts": [
            {"name": "mine_tt", "network": "tiktok",
             "api_key_secret": "BUFFER_API_KEY_3", "channel_id": "tt1",
             "post_type": "post"},
        ]})
        plan = plan_accounts(self.CHANNELS[1:2], "org9", "BUFFER_API_KEY_3", "x", existing)
        assert plan.new == ()
        assert plan.already == (("creatives.lets.create", "mine_tt"),)
        assert plan.yaml == ""


# ------------------------------------------------------- per-account post ids


def _entry(item_id: str, **kw) -> HistoryEntry:
    return HistoryEntry(
        tuple_hash=item_id, timestamp=datetime(2026, 11, 1, tzinfo=UTC),
        item_id=item_id, hook="hook_01.mp4", bodies=(), music="music_01.mp3",
        caption="c", **kw,
    )


def _post(post_id: str, views: float, service: str = "tiktok") -> PostMetrics:
    return PostMetrics(
        post_id=post_id, service=service,
        metrics=(MetricRow(type="views", name="Views", value=views, unit="count"),),
    )


class TestPerAccountPostIds:
    def test_every_account_gets_its_own_id_and_the_first_is_primary(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "history.json"
        append_history(path, [_entry("v1")])
        backfill_post_id(path, "v1", "p-ig", account="a_ig", primary=True)
        backfill_post_id(path, "v1", "p-tt", account="a_tt", primary=False)
        entry = load_history(path).entries[0]
        assert entry.buffer_post_id == "p-ig"
        assert entry.post_ids == {"a_ig": "p-ig", "a_tt": "p-tt"}

    def test_attribution_counts_every_channel_a_video_went_to(self) -> None:
        history = [
            _entry(f"v{i}", buffer_post_id=f"a{i}", post_ids={"x": f"a{i}", "y": f"b{i}"})
            for i in range(3)
        ]
        posts = {f"a{i}": _post(f"a{i}", 100) for i in range(3)}
        posts |= {f"b{i}": _post(f"b{i}", 300) for i in range(3)}
        hook = next(r for r in attribute(history, posts) if r.dimension == "hook")
        # Six samples, not three: one per channel per video.
        assert hook.options[0].posts == 6
        assert hook.options[0].median == 200


# ------------------------------------------------------------------ end to end


@pytest.fixture
def release(tmp_path: Path, clips: dict[str, Path], monkeypatch) -> Path:
    """A music campaign: one song as a creative, two accounts, a lineup."""
    campaigns = tmp_path / "campaigns"
    slug_dir = campaigns / "rel"
    (slug_dir / "creatives" / "song_a").mkdir(parents=True)

    (slug_dir / "config.yaml").write_text(
        """
slug: rel
timezone: America/New_York
creatives:
  - name: song_a
    assets_release: assets-rel-song_a
    music_cues:
      music_00.mp3: [1, 2]
    accounts: [main_tt]
posting:
  posts_per_day: 3
  max_backlog_days: 1
  start_hour: 9
  end_hour: 21
  dry_run: true
  fan_out: true
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
""".strip(),
        encoding="utf-8",
    )
    # The campaign bank must never be used: the creative has its own.
    (slug_dir / "captions.txt").write_text("CAMPAIGN BANK", encoding="utf-8")
    (slug_dir / "creatives" / "song_a" / "captions.txt").write_text(
        "\n---\n".join(
            f"overlay: meme line {i}\nSong A – Band, caption {i}" for i in range(6)
        ),
        encoding="utf-8",
    )
    (slug_dir / "creatives" / "song_a" / "LICENSES.md").write_text(
        "| music_00.mp3 | ours | owned |\n", encoding="utf-8"
    )
    (slug_dir / "lineup.yaml").write_text(
        """
posts:
  - id: pinned-one
    hook: hook_01.mp4
    music: music_00.mp3
    music_start: 3.5
    overlay: the hand-written line
    caption: |
      Song A – Band
      hand-written caption
    accounts: [side_ig]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "accounts.yaml").write_text(
        """
accounts:
  - name: main_tt
    network: tiktok
    api_key_secret: BUFFER_API_KEY
    channel_id: tt111
    post_type: post
  - name: side_ig
    network: instagram
    api_key_secret: BUFFER_API_KEY_2
    channel_id: ig222
    post_type: reel
    slot_offset_min: 20
""".strip(),
        encoding="utf-8",
    )

    source = tmp_path / "source"
    source.mkdir()
    for i in range(3):
        shutil.copy2(clips["portrait"], source / f"hook_{i:02d}.mp4")
    shutil.copy2(clips["music_long"], source / "music_00.mp3")

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cli, "CAMPAIGNS_DIR", campaigns)
    monkeypatch.setattr(
        cli, "_build_store",
        lambda env, log, clock: LocalMediaStore(source, tmp_path / "published"),
    )
    return slug_dir


def _render(**kw) -> int:
    return cli.cmd_render(
        argparse.Namespace(
            command="render", campaign="rel", dry_run=True, count=None,
            **{"plan": False, **kw},
        ),
        {},
    )


def _topup() -> int:
    return cli.cmd_topup(
        argparse.Namespace(
            command="topup", campaign="rel", dry_run=True, no_commit=True
        ),
        {},
    )


@needs_ffmpeg
class TestReleaseCampaign:
    def test_lineup_goes_first_and_the_randomizer_fills_the_rest(
        self, release: Path
    ) -> None:
        assert _render() == 0
        items = load_queue(release / "queue.json").items
        assert len(items) == 3

        pinned = [i for i in items if i.lineup_id == "pinned-one"]
        assert len(pinned) == 1
        assert pinned[0] is items[0], "the hand-picked post takes the first slot"
        assert pinned[0].parts == {
            "hook": "hook_01.mp4", "bodies": "", "music": "music_00.mp3",
            "music_offset_sec": "3.5",
        }
        assert pinned[0].overlay == "the hand-written line"
        assert pinned[0].caption.startswith("Song A – Band\nhand-written")
        assert pinned[0].accounts == ["side_ig"]

        for item in items[1:]:
            assert item.lineup_id is None
            # From the creative's own bank, with that record's on-screen line.
            assert item.caption.startswith("Song A – Band, caption")
            assert item.overlay and item.overlay.startswith("meme line")
            # Only ever from a cue, never the 15-second grid.
            assert item.parts["music_offset_sec"] in {"1", "2"}
            assert item.parts["bodies"] == ""
            # The creative's own accounts.
            assert item.accounts == ["main_tt"]

    def test_a_lineup_entry_is_only_ever_rendered_once(self, release: Path) -> None:
        _render()
        _topup()
        _render()
        history = load_history(release / "history.json")
        assert [e.lineup_id for e in history.entries].count("pinned-one") == 1

    def test_each_video_reaches_only_the_accounts_it_names(
        self, release: Path
    ) -> None:
        _render()
        assert _topup() == 0
        items = load_queue(release / "queue.json").items
        for item in items:
            expected = ["side_ig"] if item.lineup_id else ["main_tt"]
            assert [p.account for p in item.posts] == expected
            assert all(p.status is QueueStatus.PUSHED for p in item.posts)

        history = load_history(release / "history.json")
        for entry in history.entries:
            account = "side_ig" if entry.lineup_id else "main_tt"
            assert list(entry.post_ids) == [account]

    def test_auto_fill_off_posts_only_the_lineup(self, release: Path) -> None:
        config = release / "config.yaml"
        config.write_text(
            config.read_text().replace(
                "selection:\n", "selection:\n  auto_fill: false\n"
            )
        )
        _render()
        items = load_queue(release / "queue.json").items
        assert [i.lineup_id for i in items] == ["pinned-one"]

    def test_a_typo_in_the_lineup_fails_before_anything_renders(
        self, release: Path, capsys
    ) -> None:
        lineup = release / "lineup.yaml"
        lineup.write_text(lineup.read_text().replace("hook_01.mp4", "hook_99.mp4"))
        assert _render() == 1
        assert not (release / "history.json").exists()

    def test_an_unknown_account_name_fails_loudly(self, release: Path) -> None:
        lineup = release / "lineup.yaml"
        lineup.write_text(lineup.read_text().replace("side_ig", "sdie_ig"))
        assert _render() == 1

    def test_a_paused_campaign_does_nothing(self, release: Path) -> None:
        config = release / "config.yaml"
        config.write_text(
            config.read_text().replace("posting:\n", "posting:\n  paused: true\n")
        )
        assert _render() == 0 and _topup() == 0
        assert not (release / "queue.json").exists()

    def test_queue_can_withdraw_one_account_of_one_video(
        self, release: Path, capsys
    ) -> None:
        _render()
        _topup()
        item = load_queue(release / "queue.json").items[0]

        def run(**kw) -> int:
            return cli.cmd_queue(
                argparse.Namespace(
                    command="queue", campaign="rel", dry_run=False,
                    **{"discard": None, "id": None, "account": None, **kw},
                ),
                {},
            )

        assert run() == 0
        assert "pinned-one" in capsys.readouterr().out
        assert run(discard="pushed", id=item.id[:8], account="side_ig") == 0
        after = load_queue(release / "queue.json").items
        assert after[0].posts[0].status is QueueStatus.CANCELLED
        assert all(p.status is QueueStatus.PUSHED for i in after[1:] for p in i.posts)


@needs_ffmpeg
class TestMusicFirstMix:
    def test_the_song_is_loud_and_the_clip_is_silent(
        self, config, logger, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        import subprocess

        from src.models import RenderRequest
        from src.render import FfmpegRenderer

        music_first = config.model_copy(update={
            "composition": CompositionConfig(
                bodies_per_video=0, music_volume=1.0, clip_volume=0.0,
                loop_to_min=True,
            ),
        })
        out = tmp_path / "out.mp4"
        FfmpegRenderer(music_first, logger).render(RenderRequest(
            item_id="mix", hook_path=clips["portrait"], body_paths=(),
            music_path=clips["music_long"], music_offset_sec=2.0,
            output_path=out, overlay_text="on screen | two lines",
        ))

        def level(freq: int) -> float:
            proc = subprocess.run(
                ["ffmpeg", "-hide_banner", "-i", str(out), "-af",
                 f"bandpass=f={freq}:w=30,volumedetect", "-f", "null", "-"],
                capture_output=True, text=True, timeout=120,
            )
            line = next(l for l in proc.stderr.splitlines() if "mean_volume" in l)
            return float(line.split("mean_volume:")[1].split("dB")[0])

        # A 4-second clip, looped past the 5-second floor rather than refused.
        assert FfmpegRenderer(music_first, logger).probe(out).duration_sec > 7.5

        # Fixture clips carry a 440 Hz tone; the fixture music is 220 Hz.
        assert level(440) < level(220) - 25


# --------------------------------------------------------------------- metrics


class _FakeBuffer:
    """Stands in for BufferPublisher: refuses long windows, as the free plan does."""

    seen: list[tuple[str, str]] = []

    def __init__(self, api_key: str, log, organization_id=None) -> None:
        self.key = api_key
        self.request_count = 0

    def fetch_metrics(self, channel, start, end):
        from src.errors import InvalidPostError

        self.request_count += 1
        if (end - start).days > 31:
            raise InvalidPostError(
                "Buffer GraphQL error: Free-plan Insights are limited to the "
                "last 31 days of history."
            )
        return [MetricRow(type="views", name="Views", value=5.0, unit="count")], None

    def fetch_post_metrics(self, channel, limit=200):
        self.request_count += 1
        type(self).seen.append((self.key, channel))
        return [_post(f"post-{channel}", 10.0)]


class TestMetricsUnderFanOut:
    def test_old_campaign_still_gets_every_accounts_figures(
        self, release: Path, monkeypatch
    ) -> None:
        """The regression that froze metrics for weeks: once a campaign's first
        post is over 31 days old Buffer refuses the lifetime window, and that
        refusal used to abort the run before any per-post figure was fetched.
        """
        from src.attribution import load_posts, posts_path

        config = release / "config.yaml"
        config.write_text(config.read_text().replace("dry_run: true", "dry_run: false"))
        append_history(release / "history.json", [
            _entry("old").model_copy(
                update={"timestamp": datetime.now(UTC) - timedelta(days=90)}
            )
        ])
        _FakeBuffer.seen = []
        monkeypatch.setattr(cli, "BufferPublisher", _FakeBuffer)

        code = cli.cmd_metrics(
            argparse.Namespace(command="metrics", campaign="rel", dry_run=False, days=30),
            {"BUFFER_API_KEY": "key-one", "BUFFER_API_KEY_2": "key-two"},
        )
        assert code == 0
        # Each account read through its own login.
        assert _FakeBuffer.seen == [("key-one", "tt111"), ("key-two", "ig222")]
        cached = load_posts(posts_path(release)).posts
        assert cached["post-tt111"].account == "main_tt"
        assert cached["post-ig222"].account == "side_ig"


# ------------------------------------------------- per-account versions, funnel


@pytest.fixture
def network(release: Path) -> Path:
    """The release campaign, with a version per account and a funnel."""
    config = release / "config.yaml"
    text = config.read_text()
    text = text.replace("    accounts: [main_tt]\n", "    title: Song A\n")
    text += """
variation:
  enabled: true
  per_account: true
  speed_max: 0.0
  music_tempo_max: 0.0
  music_tilt_db: 0.0
  trim_start_max_sec: 0.3
  overlay_shift_max: 0.02
funnel:
  name: The Album
  cta:
    - "full song: {name}, link in bio"
  cta_by_network:
    instagram:
      - "listen: {link}"
  first_comment:
    - "{name} is out now"
  end_card: "{name} | on Spotify"
  end_card_sec: 1.0
"""
    config.write_text(text)
    (release / "lineup.yaml").write_text("posts: []\n")
    return release


@needs_ffmpeg
class TestPerAccountVersions:
    def test_each_account_gets_a_different_video_not_a_regraded_copy(
        self, network: Path, tmp_path: Path
    ) -> None:
        assert _render() == 0
        items = load_queue(network / "queue.json").items
        assert len(items) == 3
        for item in items:
            assert set(item.variants) == {"main_tt", "side_ig"}
            a, b = item.variants["main_tt"], item.variants["side_ig"]
            assert a.video_url != b.video_url
            # Structurally different, which is the part that counts.
            assert a.parts["hook"] != b.parts["hook"]
            assert a.overlay != b.overlay
            assert a.parts["music_offset_sec"] != b.parts["music_offset_sec"]
            # And each recorded with its own recipe.
            assert a.treatment != b.treatment
            assert item.video_url == a.video_url
        assert len(list((tmp_path / "published").glob("*.mp4"))) == 6

    def test_the_song_itself_is_never_retimed(self, network: Path) -> None:
        _render()
        for item in load_queue(network / "queue.json").items:
            for variant in item.variants.values():
                assert variant.treatment["music_tempo"] == 1.0
                assert variant.treatment["speed"] == 1.0

    def test_every_caption_carries_the_ask_for_its_network(
        self, network: Path
    ) -> None:
        _render()
        for item in load_queue(network / "queue.json").items:
            # The creative's own title fills {name}, not the campaign's.
            assert item.variants["main_tt"].caption.endswith(
                "full song: Song A, link in bio"
            )
            # Instagram's own line needs a link nobody set, so it falls back
            # to the shared one rather than posting "listen: ".
            assert item.variants["side_ig"].caption.endswith(
                "full song: Song A, link in bio"
            )
            assert item.first_comment == "Song A is out now"

    def test_push_sends_each_account_its_own_file_and_text(
        self, network: Path, monkeypatch
    ) -> None:
        from src.publishers.base import DryRunPublisher

        sent: list = []
        original = DryRunPublisher.create_post

        def capture(self, request):
            sent.append(request)
            return original(self, request)

        monkeypatch.setattr(DryRunPublisher, "create_post", capture)
        _render()
        assert _topup() == 0
        items = {i.id: i for i in load_queue(network / "queue.json").items}
        assert len(sent) == 6
        for request in sent:
            owner = next(
                (i, name) for i in items.values()
                for name, v in i.variants.items() if v.video_url == request.video_url
            )
            item, name = owner
            assert request.text == item.variants[name].caption
            assert request.first_comment == "Song A is out now"

    def test_history_records_what_each_account_was_shown(self, network: Path) -> None:
        _render()
        for entry in load_history(network / "history.json").entries:
            assert set(entry.variants) == {"main_tt", "side_ig"}
            assert entry.variants["main_tt"]["hook"] == entry.hook
            assert entry.variants["side_ig"]["hook"] != entry.hook

    def test_attribution_credits_the_clip_each_account_actually_posted(self) -> None:
        history = [
            _entry(
                f"v{i}", post_ids={"x": f"a{i}", "y": f"b{i}"},
                variants={"x": {"hook": "hook_01.mp4"}, "y": {"hook": "hook_02.mp4"}},
            )
            for i in range(8)
        ]
        posts = {f"a{i}": _post(f"a{i}", 100) for i in range(8)}
        posts |= {f"b{i}": _post(f"b{i}", 900) for i in range(8)}
        hook = next(r for r in attribute(history, posts) if r.dimension == "hook")
        assert [(o.option, o.median) for o in hook.options] == [
            ("hook_02.mp4", 900), ("hook_01.mp4", 100),
        ]


@needs_ffmpeg
class TestEndCard:
    def test_end_card_appears_only_at_the_end(
        self, config, logger, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        import subprocess

        from src.config import FunnelConfig
        from src.models import RenderRequest
        from src.render import FfmpegRenderer

        carded = config.model_copy(update={
            "composition": CompositionConfig(bodies_per_video=0, loop_to_min=True),
            "funnel": FunnelConfig(end_card="Song A | on Spotify", end_card_sec=1.0),
        })

        def frame_bytes(path: Path, at: float) -> bytes:
            return subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path),
                 "-frames:v", "1", "-vf", "crop=iw:ih*0.2:0:ih*0.66,scale=64:16",
                 "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                capture_output=True, timeout=60,
            ).stdout

        renderer = FfmpegRenderer(carded, logger)
        plain = tmp_path / "plain.mp4"
        with_card = tmp_path / "card.mp4"
        base = dict(
            hook_path=clips["portrait"], body_paths=(), music_path=None,
        )
        renderer.render(RenderRequest(item_id="p", output_path=plain, **base))
        renderer.render(RenderRequest(
            item_id="p", output_path=with_card,
            end_card_text="Song A | on Spotify", **base,
        ))
        length = renderer.probe(with_card).duration_sec
        # Identical early on (including the first pass of the looped clip)...
        assert frame_bytes(plain, 1.0) == frame_bytes(with_card, 1.0)
        assert frame_bytes(plain, 3.5) == frame_bytes(with_card, 3.5)
        # ...and different in the last second, where the card is drawn.
        assert frame_bytes(plain, length - 0.4) != frame_bytes(with_card, length - 0.4)


class TestSilentAccountAlert:
    def test_an_account_that_stopped_publishing_is_reported(
        self, release: Path, monkeypatch
    ) -> None:
        """Buffer accepts the post, the queue says pushed, the network refuses
        it afterwards: only the absence shows."""
        now = datetime.now(UTC)

        class Stale(_FakeBuffer):
            def fetch_post_metrics(self, channel, limit=200):
                when = now if channel == "tt111" else now - timedelta(days=40)
                return [_post(f"post-{channel}", 10.0).model_copy(
                    update={"sent_at": when}
                )]

        sent: list[str] = []

        class Recorder:
            def notify(self, event, message):
                sent.append(message)
                return True

            def failure(self, *a, **k):
                sent.append("failure")

        config = release / "config.yaml"
        config.write_text(config.read_text().replace("dry_run: true", "dry_run: false"))
        monkeypatch.setattr(cli, "BufferPublisher", Stale)
        monkeypatch.setattr(cli, "notifier_for", lambda *a, **k: Recorder())
        assert cli.cmd_metrics(
            argparse.Namespace(command="metrics", campaign="rel", dry_run=False, days=30),
            {"BUFFER_API_KEY": "k1", "BUFFER_API_KEY_2": "k2"},
        ) == 0
        alerts = [m for m in sent if "nothing has published" in m]
        assert len(alerts) == 1
        assert "side_ig" in alerts[0] and "main_tt since" not in alerts[0]
