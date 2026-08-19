"""The randomizer roster: muting a clip without deleting it.

The behaviour under test is narrow but load-bearing — a muted clip must be
invisible to the selector, and every number the operator is shown must agree
with that. A roster that only dimmed a card in the UI while the render kept
picking the clip would be worse than no feature at all.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from src.assets import LocalLibrary
from src.clips import (
    ClipRoster,
    filter_library,
    kind_of,
    load_roster,
    roster_path,
    save_roster,
)
from src.errors import ValidationError
from src.logging import StructuredLogger
from src.models import PartKind


def log() -> StructuredLogger:
    return StructuredLogger({}, io.StringIO())


def library(root: Path) -> LocalLibrary:
    for name in ("hook_01.mov", "hook_02.mov", "body_01.mp4", "body_02.mp4",
                 "music_01.mp3"):
        (root / name).write_bytes(b"x")
    return LocalLibrary.from_directory(root)


class TestRoster:
    def test_a_fresh_campaign_has_everything_enabled(self, tmp_path: Path) -> None:
        assert load_roster(tmp_path / "clips.json").disabled == ()

    def test_unknown_clips_are_enabled_by_default(self) -> None:
        # SPEC §7: drop a file in and it is live on the next render. A roster
        # listing what is OFF is what preserves that; listing what is ON would
        # make every new upload silently inert.
        assert ClipRoster(disabled=("hook_01.mov",)).is_enabled("hook_99.mov")

    def test_round_trips_through_disk(self, tmp_path: Path) -> None:
        path = roster_path(tmp_path)
        save_roster(path, ClipRoster(disabled=("body_02.mp4",)))
        assert load_roster(path).disabled == ("body_02.mp4",)

    def test_toggling_off_and_on_again_restores_the_exact_bytes(
        self, tmp_path: Path
    ) -> None:
        path = roster_path(tmp_path)
        save_roster(path, ClipRoster())
        before = path.read_bytes()
        save_roster(path, ClipRoster().with_(["a.mp4"], False).with_(["a.mp4"], True))
        assert path.read_bytes() == before

    def test_entries_are_sorted_and_deduplicated(self) -> None:
        roster = ClipRoster().with_(["b.mp4", "a.mp4", "b.mp4"], False)
        assert roster.disabled == ("a.mp4", "b.mp4")

    def test_enabling_something_never_muted_is_a_no_op(self) -> None:
        assert ClipRoster().with_(["a.mp4"], True).disabled == ()

    def test_a_corrupt_roster_raises_rather_than_unmuting_everything(
        self, tmp_path: Path
    ) -> None:
        # Recovering by returning an empty roster would put clips the operator
        # deliberately pulled back into tonight's posts.
        path = tmp_path / "clips.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_roster(path)

    def test_unknown_fields_are_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "clips.json"
        path.write_text('{"disabled": [], "enabled": ["x"]}', encoding="utf-8")
        with pytest.raises(ValidationError):
            load_roster(path)


class TestKindOf:
    def test_prefix_assigns_the_role(self) -> None:
        assert kind_of("hook_01.mov") is PartKind.HOOK
        assert kind_of("body_12.mp4") is PartKind.BODY
        assert kind_of("music_03.mp3") is PartKind.MUSIC

    def test_case_is_ignored(self) -> None:
        assert kind_of("HOOK_01.MOV") is PartKind.HOOK

    def test_a_stray_file_has_no_role(self) -> None:
        assert kind_of("LICENSES.md") is None


class TestFiltering:
    def test_muted_clips_never_reach_the_selector(self, tmp_path: Path) -> None:
        lib = filter_library(
            library(tmp_path), ClipRoster(disabled=("hook_02.mov", "music_01.mp3")),
            log(),
        )
        assert [p.name for p in lib.hooks] == ["hook_01.mov"]
        assert [p.name for p in lib.music] == []
        assert len(lib.bodies) == 2

    def test_an_empty_roster_returns_the_library_untouched(
        self, tmp_path: Path
    ) -> None:
        lib = library(tmp_path)
        assert filter_library(lib, ClipRoster(), log()) is lib

    def test_muting_a_name_that_is_not_there_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        lib = library(tmp_path)
        out = filter_library(lib, ClipRoster(disabled=("gone.mp4",)), log())
        assert len(out.hooks) == len(lib.hooks)

    def test_the_mute_is_logged_with_what_it_removed(self, tmp_path: Path) -> None:
        stream = io.StringIO()
        filter_library(
            library(tmp_path), ClipRoster(disabled=("hook_02.mov",)),
            StructuredLogger({}, stream),
        )
        assert "clips_muted" in stream.getvalue()

    def test_the_combination_ceiling_falls_when_a_clip_is_muted(
        self, tmp_path: Path
    ) -> None:
        # The point of filtering before the selector: runway is computed from
        # what can actually be picked, so muting is visible in the number.
        from src.selector import AssetLibrary

        def ceiling(lib: LocalLibrary) -> int:
            return AssetLibrary(
                hooks=tuple(p.name for p in lib.hooks),
                bodies=tuple(p.name for p in lib.bodies),
                music=tuple(p.name for p in lib.music),
                captions=("c1", "c2"),
            ).ceiling(1)

        full = library(tmp_path)
        muted = filter_library(full, ClipRoster(disabled=("hook_02.mov",)), log())
        assert ceiling(muted) < ceiling(full)


class TestSharedLibraries:
    """Campaigns pointing at one assets Release must share one drop folder.

    Without this, "I filmed three more hooks" means dropping the same three
    files into three folders and uploading them three times — and the clip
    cards on two of the three campaigns have no local copy to preview.
    """

    def config_for(self, slug: str, release: str | None):
        from src.config import CampaignConfig

        raw = {
            "slug": slug,
            "timezone": "UTC",
            "buffer": {
                "api_key_secret": "BUFFER_API_KEY",
                "channel_id_secret": "BUFFER_CHANNEL_X",
            },
            "notify": {"webhook_secret": "DISCORD_WEBHOOK_X"},
        }
        if release is not None:
            raw["assets_release"] = release
        return CampaignConfig.model_validate(raw)

    def test_a_campaign_with_its_own_release_uses_its_slug(self) -> None:
        config = self.config_for("clubs", None)
        assert config.assets_tag == "assets-clubs"
        assert config.library_key == "clubs"

    def test_campaigns_sharing_a_release_share_the_folder(self) -> None:
        keys = {
            self.config_for(slug, "assets-clubs").library_key
            for slug in ("clubs_tt", "clubs_yt")
        }
        assert keys == {"clubs"}

    def test_a_release_named_without_the_prefix_still_yields_a_folder(self) -> None:
        # Nothing forces the "assets-" convention on a hand-written config.
        assert self.config_for("x", "shared-library").library_key == "shared-library"

    def test_an_empty_derived_key_falls_back_to_the_slug(self) -> None:
        # "assets-" with nothing after it would otherwise name the inbox root
        # itself, putting one campaign's clips beside every other campaign.
        assert self.config_for("solo", "assets-").library_key == "solo"
