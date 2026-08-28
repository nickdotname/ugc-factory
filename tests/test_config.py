"""M1 — config schema and fail-loud validation (SPEC §9, §2.2).

These tests are pure: no network, no ffmpeg, no clock.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.config import (
    CampaignConfig,
    DedupeDimension,
    PostType,
    load_campaign,
    load_config,
)
from src.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[1]

MINIMAL = """
slug: demo
timezone: America/New_York
buffer:
  api_key_secret: BUFFER_API_KEY
  channel_id_secret: BUFFER_CHANNEL_DEMO
notify:
  webhook_secret: DISCORD_WEBHOOK_DEMO
"""


def write(tmp_path: Path, body: str, name: str = "config.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


class TestDefaults:
    def test_minimal_config_loads_with_documented_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(write(tmp_path, MINIMAL))
        assert cfg.slug == "demo"
        # SPEC §4.5 — default cadence is 6, not the 24 ceiling.
        assert cfg.posting.posts_per_day == 6
        assert cfg.posting.max_buffer_queue == 10
        assert cfg.video.width == 1080 and cfg.video.height == 1920
        assert cfg.composition.music_volume == 0.10
        assert cfg.buffer.post_type is PostType.REEL
        assert cfg.selection.dedupe_on == (
            DedupeDimension.HOOK,
            DedupeDimension.BODY,
            DedupeDimension.MUSIC,
            DedupeDimension.CAPTION,
        )

    def test_config_is_frozen(self, tmp_path: Path) -> None:
        cfg = load_config(write(tmp_path, MINIMAL))
        with pytest.raises(Exception):
            cfg.posting.posts_per_day = 24  # type: ignore[misc]

    def test_zone_resolves(self, tmp_path: Path) -> None:
        cfg = load_config(write(tmp_path, MINIMAL))
        assert cfg.zone.key == "America/New_York"


class TestFailLoud:
    def test_missing_file_is_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="config not found"):
            load_config(tmp_path / "nope.yaml")

    def test_empty_file_is_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="is empty"):
            load_config(write(tmp_path, ""))

    def test_malformed_yaml_is_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not valid YAML"):
            load_config(write(tmp_path, "slug: [unclosed\n"))

    def test_non_mapping_is_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="must contain a YAML mapping"):
            load_config(write(tmp_path, "- a\n- b\n"))

    def test_missing_required_section_names_the_key(self, tmp_path: Path) -> None:
        body = "slug: demo\ntimezone: America/New_York\n"
        with pytest.raises(ConfigError, match="buffer"):
            load_config(write(tmp_path, body))

    def test_unknown_key_is_rejected_not_ignored(self, tmp_path: Path) -> None:
        """A typo must fail, never be silently dropped (SPEC §9)."""
        body = MINIMAL + "\nposting:\n  posts_per_dya: 12\n"
        with pytest.raises(ConfigError, match="posts_per_dya"):
            load_config(write(tmp_path, body))

    def test_unknown_top_level_key_is_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\ncolour: blue\n"
        with pytest.raises(ConfigError, match="colour"):
            load_config(write(tmp_path, body))


class TestPostingValidation:
    @pytest.mark.parametrize("n", [0, -1, 25, 100])
    def test_posts_per_day_bounds(self, tmp_path: Path, n: int) -> None:
        body = MINIMAL + f"\nposting:\n  posts_per_day: {n}\n"
        with pytest.raises(ConfigError, match="posts_per_day"):
            load_config(write(tmp_path, body))

    def test_posts_per_day_24_is_allowed(self, tmp_path: Path) -> None:
        """SPEC §4.5 — build for 24 even though we run at 6."""
        body = MINIMAL + "\nposting:\n  posts_per_day: 24\n"
        assert load_config(write(tmp_path, body)).posting.posts_per_day == 24

    def test_end_before_start_wraps_past_midnight(self, tmp_path: Path) -> None:
        """22:00 -> 09:00 is an eleven-hour overnight window, not an error.

        This used to be rejected. Posting hourly from an afternoon start time
        needs a window that crosses midnight, so an end earlier than the start
        is now the documented way to express one.
        """
        body = MINIMAL + "\nposting:\n  start_hour: 22\n  end_hour: 9\n"
        assert load_config(write(tmp_path, body)).posting.window_hours == 11

    def test_window_too_short_for_cadence_is_rejected(self, tmp_path: Path) -> None:
        # 1 hour = 60 minutes cannot hold 61 distinguishable slots.
        body = MINIMAL + "\nposting:\n  posts_per_day: 24\n  start_hour: 9\n  end_hour: 10\n"
        cfg_ok = load_config(write(tmp_path, body))
        assert cfg_ok.posting.posts_per_day == 24  # 60 minutes >= 24 posts, fine


class TestVideoValidation:
    def test_below_reels_floor_is_rejected(self, tmp_path: Path) -> None:
        """SPEC §4.3 — under 5s is not Reels-eligible."""
        body = MINIMAL + "\nvideo:\n  min_duration_sec: 3\n"
        with pytest.raises(ConfigError, match="Reels floor"):
            load_config(write(tmp_path, body))

    def test_above_reels_ceiling_is_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nvideo:\n  max_duration_sec: 180\n"
        with pytest.raises(ConfigError, match="Reels ceiling"):
            load_config(write(tmp_path, body))

    def test_narrowing_within_reels_bounds_is_allowed(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nvideo:\n  min_duration_sec: 12\n  max_duration_sec: 45\n"
        cfg = load_config(write(tmp_path, body))
        assert (cfg.video.min_duration_sec, cfg.video.max_duration_sec) == (12.0, 45.0)

    def test_landscape_output_is_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nvideo:\n  width: 1920\n  height: 1080\n"
        with pytest.raises(ConfigError, match="not vertical"):
            load_config(write(tmp_path, body))

    def test_square_output_is_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nvideo:\n  width: 1080\n  height: 1080\n"
        with pytest.raises(ConfigError, match="not vertical"):
            load_config(write(tmp_path, body))

    def test_inverted_durations_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nvideo:\n  min_duration_sec: 60\n  max_duration_sec: 30\n"
        with pytest.raises(ConfigError, match="must exceed"):
            load_config(write(tmp_path, body))

    def test_bad_preset_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nvideo:\n  preset: turbo\n"
        with pytest.raises(ConfigError, match="not an x264 preset"):
            load_config(write(tmp_path, body))

    def test_reels_bounds_are_not_configurable(self, tmp_path: Path) -> None:
        """Platform facts must not be overridable from campaign config."""
        body = MINIMAL + "\nvideo:\n  REELS_MAX_SEC: 600\n"
        with pytest.raises(ConfigError, match="REELS_MAX_SEC"):
            load_config(write(tmp_path, body))


class TestSecretsAreNamesNotValues:
    """A committed public repo must never contain a real token (SPEC §3)."""

    def test_a_raw_token_as_the_key_name_is_rejected(self, tmp_path: Path) -> None:
        """Now caught by the slot check, which is stricter than the name check:
        the key must be one of the slots the workflows actually pass through."""
        body = MINIMAL.replace("BUFFER_API_KEY", "1/abc-real-looking-token")
        with pytest.raises(ConfigError, match="must be one of"):
            load_config(write(tmp_path, body))

    def test_an_unwired_key_slot_is_rejected(self, tmp_path: Path) -> None:
        """A name no workflow exports would load here and fail at 05:00."""
        body = MINIMAL.replace("BUFFER_API_KEY", "BUFFER_API_KEY_MYBRAND")
        with pytest.raises(ConfigError, match="must be one of"):
            load_config(write(tmp_path, body))

    def test_every_wired_slot_is_accepted(self, tmp_path: Path) -> None:
        from src.config import BUFFER_KEY_SLOTS

        for slot in BUFFER_KEY_SLOTS:
            body = MINIMAL.replace("BUFFER_API_KEY", slot)
            assert load_config(write(tmp_path, body)).buffer.api_key_secret == slot

    def test_webhook_url_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL.replace(
            "DISCORD_WEBHOOK_DEMO", "https://discord.com/api/webhooks/123/abc"
        )
        with pytest.raises(ConfigError, match="NAME of an environment"):
            load_config(write(tmp_path, body))


class TestSelectionValidation:
    def test_empty_dedupe_on_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nselection:\n  dedupe_on: []\n"
        with pytest.raises(ConfigError, match="at least one dimension"):
            load_config(write(tmp_path, body))

    def test_duplicate_dedupe_dimension_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nselection:\n  dedupe_on: [hook, hook]\n"
        with pytest.raises(ConfigError, match="duplicates"):
            load_config(write(tmp_path, body))

    def test_unknown_dedupe_dimension_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nselection:\n  dedupe_on: [hook, vibes]\n"
        with pytest.raises(ConfigError, match="vibes"):
            load_config(write(tmp_path, body))


class TestYaml11BooleanTrap:
    """PyYAML resolves on/off/yes/no to booleans; the spec uses `on:` as a key."""

    def test_notify_on_key_is_not_parsed_as_boolean(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nnotify:\n  webhook_secret: HOOK\n  on: [failure]\n"
        cfg = load_config(write(tmp_path, body))
        assert [e.value for e in cfg.notify.on] == ["failure"]

    def test_true_and_false_still_parse_as_booleans(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nposting:\n  dry_run: true\n"
        assert load_config(write(tmp_path, body)).posting.dry_run is True
        body = MINIMAL + "\nposting:\n  dry_run: false\n"
        assert load_config(write(tmp_path, body)).posting.dry_run is False


class TestSlugAndTimezone:
    def test_bad_timezone_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL.replace("America/New_York", "Mars/Olympus_Mons")
        with pytest.raises(ConfigError, match="not a valid IANA zone"):
            load_config(write(tmp_path, body))

    def test_path_traversal_slug_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL.replace("slug: demo", "slug: ../../etc")
        with pytest.raises(ConfigError, match="may contain only"):
            load_config(write(tmp_path, body))

    def test_slug_must_match_directory(self, tmp_path: Path) -> None:
        (tmp_path / "other").mkdir()
        write(tmp_path / "other", MINIMAL)
        with pytest.raises(ConfigError, match="must match its directory name"):
            load_campaign(tmp_path, "other")

    def test_matching_slug_and_directory_loads(self, tmp_path: Path) -> None:
        (tmp_path / "demo").mkdir()
        write(tmp_path / "demo", MINIMAL)
        assert load_campaign(tmp_path, "demo").slug == "demo"


class TestShippedCampaigns:
    """The configs actually committed to this repo must be valid."""

    def test_clubs_config_is_valid(self) -> None:
        cfg = load_campaign(REPO_ROOT / "campaigns", "clubs")
        assert cfg.slug == "clubs"
        assert cfg.buffer.post_type is PostType.REEL

    def test_template_config_is_structurally_valid(self) -> None:
        """The template must parse, so `cp -r` produces a working starting point."""
        cfg = load_config(REPO_ROOT / "campaigns" / "_template" / "config.yaml")
        assert cfg.slug == "CHANGEME"
        assert cfg.posting.dry_run is True

    def test_no_campaign_specific_logic_in_src(self) -> None:
        """SPEC §2.2 — a grep for 'clubs' in src/ must return nothing."""
        offenders = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            if "clubs" in path.read_text(encoding="utf-8").lower():
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert not offenders, f"campaign slug leaked into src/: {offenders}"


class TestWrappingPostingWindow:
    def test_equal_start_and_end_is_a_full_day(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nposting:\n  posts_per_day: 24\n  start_hour: 15\n  end_hour: 15\n"
        cfg = load_config(write(tmp_path, body))
        assert cfg.posting.window_hours == 24

    def test_window_may_cross_midnight(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nposting:\n  posts_per_day: 6\n  start_hour: 22\n  end_hour: 6\n"
        assert load_config(write(tmp_path, body)).posting.window_hours == 8

    def test_ordinary_window_unchanged(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nposting:\n  start_hour: 9\n  end_hour: 21\n"
        assert load_config(write(tmp_path, body)).posting.window_hours == 12

    def test_too_many_posts_for_a_short_window_still_rejected(self, tmp_path: Path) -> None:
        body = MINIMAL + "\nposting:\n  posts_per_day: 24\n  start_hour: 1\n  end_hour: 1\n"
        load_config(write(tmp_path, body))  # 24h window, fine


class TestShippedCaptionsMeetDemand:
    """The banks that actually ship, against the demand actually recorded.

    A unit test cannot catch a caption rewrite that quietly stops speaking to
    what people search for — the copy stays valid, the platforms accept it,
    and only the coverage figure moves. This is the guard that fails in CI
    rather than in Discord a day later.
    """

    def _campaigns_with_cached_demand(self):
        import json

        from src.campaigns import list_campaigns

        found = []
        for summary in list_campaigns(REPO_ROOT / "campaigns"):
            if not summary.valid:
                continue
            cache = REPO_ROOT / "campaigns" / summary.slug / "analytics.json"
            if not cache.is_file():
                continue
            fetches = json.loads(cache.read_text()).get("fetches") or []
            if not fetches or not fetches[-1].get("top_searches"):
                continue
            found.append((summary, fetches[-1]["top_searches"]))
        return found

    def test_shipped_banks_clear_their_own_configured_floor(self) -> None:
        from src.analytics import vocabulary_gap
        from src.campaigns import list_campaigns
        from src.config import load_campaign

        cached = self._campaigns_with_cached_demand()
        if not cached:
            pytest.skip("no campaign has fetched demand data yet")

        for summary, searches in cached:
            config = load_campaign(REPO_ROOT / "campaigns", summary.slug)
            # One brand's banks against one product's search log, matching how
            # the alert itself groups them.
            corpus = ""
            for other in list_campaigns(REPO_ROOT / "campaigns"):
                if other.valid and other.assets_tag == summary.assets_tag:
                    bank = REPO_ROOT / "campaigns" / other.slug / "captions.txt"
                    if bank.is_file():
                        corpus += "\n" + bank.read_text(encoding="utf-8")
            gap = vocabulary_gap(
                [(s["label"], int(s["value"])) for s in searches], corpus
            )
            assert gap.coverage is not None
            floor = config.notify.demand_coverage_floor
            assert gap.coverage >= floor, (
                f"{summary.slug}: captions speak to "
                f"{gap.coverage * 100:.0f}% of search volume, under its "
                f"{floor * 100:.0f}% floor. Unmet: "
                f"{[t.query for t in gap.worst(6)]}"
            )
