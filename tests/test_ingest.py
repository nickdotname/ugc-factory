"""The drop folder: validation, naming, upload, and library sizing warnings."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest

from src.assets import MediaStore, RemoteAsset
from src.ingest import (
    Verdict,
    apply_plan,
    build_plan,
    combinations,
    ensure_inbox,
    library_health,
    next_index,
)
from src.logging import StructuredLogger
from src.models import PartKind
from src.render import FfmpegRenderer

from tests.conftest import needs_ffmpeg


class RecordingStore(MediaStore):
    def __init__(self, existing: list[str] | None = None) -> None:
        self.existing = existing or []
        self.published: list[str] = []
        self.fail = False

    def download_assets(self, tag: str, dest_dir: Path) -> list[Path]:
        return []

    def list_assets(self, tag: str) -> list[str]:
        return list(self.existing)

    def publish(self, tag: str, files: list[Path]) -> list[RemoteAsset]:
        if self.fail:
            raise RuntimeError("upload exploded")
        for f in files:
            assert f.is_file(), "staged file must exist at upload time"
            self.published.append(f.name)
        return [RemoteAsset(name=f.name, url=f"https://x/{f.name}", size_bytes=1)
                for f in files]

    def cleanup(self, prefix: str, older_than_days: int) -> list[str]:
        return []


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    d = tmp_path / "inbox"
    ensure_inbox(d)
    return d


class TestNextIndex:
    def test_starts_at_one_when_empty(self) -> None:
        assert next_index([], PartKind.HOOK) == 1

    def test_continues_an_existing_sequence(self) -> None:
        """A second ingest must append, never overwrite hook_01."""
        existing = ["hook_01.mp4", "hook_02.mp4", "body_01.mp4"]
        assert next_index(existing, PartKind.HOOK) == 3
        assert next_index(existing, PartKind.BODY) == 2
        assert next_index(existing, PartKind.MUSIC) == 1

    def test_handles_gaps_by_taking_the_highest(self) -> None:
        assert next_index(["hook_01.mp4", "hook_07.mp4"], PartKind.HOOK) == 8

    def test_ignores_unrelated_names(self) -> None:
        assert next_index(["LICENSES.md", "notes.txt"], PartKind.HOOK) == 1


@needs_ffmpeg
class TestBuildPlan:
    def _renderer(self, config, log) -> FfmpegRenderer:
        return FfmpegRenderer(config, log)

    def test_names_files_by_the_folder_they_were_dropped_in(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        """The folder assigns the role, so nobody memorises a prefix."""
        shutil.copy2(clips["portrait"], inbox / "hooks" / "my cool hook.mp4")
        shutil.copy2(clips["square"], inbox / "bodies" / "Main Video FINAL.mov")
        shutil.copy2(clips["music_short"], inbox / "music" / "song.mp3")

        plan = build_plan(inbox, [], self._renderer(config, logger), logger)
        names = {c.source.name: c.target_name for c in plan.candidates}
        assert names["my cool hook.mp4"] == "hook_01.mp4"
        assert names["Main Video FINAL.mov"] == "body_01.mov"
        assert names["song.mp3"] == "music_01.mp3"

    def test_spaces_and_case_never_reach_the_uploaded_name(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        shutil.copy2(clips["portrait"], inbox / "hooks" / "A Clip With Spaces.MP4")
        plan = build_plan(inbox, [], self._renderer(config, logger), logger)
        target = plan.candidates[0].target_name
        assert " " not in target and target == "hook_01.mp4"

    def test_continues_numbering_from_the_release(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        shutil.copy2(clips["portrait"], inbox / "hooks" / "new.mp4")
        plan = build_plan(inbox, ["hook_01.mp4", "hook_02.mp4"],
                          self._renderer(config, logger), logger)
        assert plan.candidates[0].target_name == "hook_03.mp4"

    def test_multiple_files_get_sequential_names(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        for n in ("a.mp4", "b.mp4", "c.mp4"):
            shutil.copy2(clips["portrait"], inbox / "hooks" / n)
        plan = build_plan(inbox, [], self._renderer(config, logger), logger)
        assert [c.target_name for c in plan.candidates] == [
            "hook_01.mp4", "hook_02.mp4", "hook_03.mp4",
        ]

    def test_rejects_a_file_ffprobe_cannot_read(
        self, inbox: Path, config, logger
    ) -> None:
        (inbox / "hooks" / "broken.mp4").write_text("not a video", encoding="utf-8")
        plan = build_plan(inbox, [], self._renderer(config, logger), logger)
        assert plan.candidates[0].verdict is Verdict.REJECTED
        assert not plan.uploadable

    def test_rejects_wrong_extension_for_the_folder(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        """An mp3 in hooks/ is a mistake worth catching immediately."""
        shutil.copy2(clips["music_short"], inbox / "hooks" / "song.mp3")
        plan = build_plan(inbox, [], self._renderer(config, logger), logger)
        assert plan.candidates[0].verdict is Verdict.REJECTED
        assert "not accepted here" in plan.candidates[0].notes[0]

    def test_rejects_a_video_dropped_into_music(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        shutil.copy2(clips["portrait"], inbox / "music" / "clip.mp4")
        plan = build_plan(inbox, [], self._renderer(config, logger), logger)
        assert plan.candidates[0].verdict is Verdict.REJECTED

    def test_landscape_is_warned_not_rejected(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        """The renderer crops it fine — rejecting would be a lie."""
        shutil.copy2(clips["landscape"], inbox / "bodies" / "wide.mp4")
        plan = build_plan(inbox, [], self._renderer(config, logger), logger)
        c = plan.candidates[0]
        assert c.verdict is Verdict.WARNED
        assert c.usable
        assert "centre-cropped" in c.notes[0]

    def test_silent_clip_is_warned_not_rejected(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        shutil.copy2(clips["silent"], inbox / "bodies" / "quiet.mp4")
        c = build_plan(inbox, [], self._renderer(config, logger), logger).candidates[0]
        assert c.verdict is Verdict.WARNED and c.usable
        assert "silence will be added" in c.notes[0]

    def test_long_hook_is_flagged(
        self, inbox: Path, clips: dict[str, Path], config, logger
    ) -> None:
        shutil.copy2(clips["long"], inbox / "hooks" / "long.mp4")
        c = build_plan(inbox, [], self._renderer(config, logger), logger).candidates[0]
        assert c.verdict is Verdict.WARNED and c.usable
        assert "long for a hook" in " ".join(c.notes)

    def test_hidden_files_are_ignored(
        self, inbox: Path, config, logger
    ) -> None:
        (inbox / "hooks" / ".DS_Store").write_bytes(b"junk")
        assert build_plan(inbox, [], self._renderer(config, logger), logger).candidates == []

    def test_empty_inbox_is_not_an_error(self, inbox: Path, config, logger) -> None:
        plan = build_plan(inbox, [], self._renderer(config, logger), logger)
        assert plan.candidates == []
        assert "empty" in plan.render_table()


@needs_ffmpeg
class TestApplyPlan:
    def test_uploads_under_the_generated_name(
        self, inbox: Path, clips: dict[str, Path], config, logger, tmp_path: Path
    ) -> None:
        shutil.copy2(clips["portrait"], inbox / "hooks" / "original name.mp4")
        store = RecordingStore()
        plan = build_plan(inbox, [], FfmpegRenderer(config, logger), logger)
        apply_plan(plan, inbox, store, "assets-x", logger, staging=tmp_path / "stage")
        assert store.published == ["hook_01.mp4"]

    def test_archives_uploaded_files_so_rerun_is_safe(
        self, inbox: Path, clips: dict[str, Path], config, logger, tmp_path: Path
    ) -> None:
        shutil.copy2(clips["portrait"], inbox / "hooks" / "a.mp4")
        store = RecordingStore()
        plan = build_plan(inbox, [], FfmpegRenderer(config, logger), logger)
        apply_plan(plan, inbox, store, "assets-x", logger, staging=tmp_path / "stage")

        assert not (inbox / "hooks" / "a.mp4").exists()
        assert (inbox / "_uploaded" / "hook_01.mp4").is_file()

        # A second run finds nothing, so nothing is double-uploaded.
        second = build_plan(inbox, ["hook_01.mp4"], FfmpegRenderer(config, logger), logger)
        assert second.uploadable == []

    def test_failed_upload_leaves_the_inbox_untouched(
        self, inbox: Path, clips: dict[str, Path], config, logger, tmp_path: Path
    ) -> None:
        """A failed run must be re-runnable, not half-consumed."""
        shutil.copy2(clips["portrait"], inbox / "hooks" / "a.mp4")
        store = RecordingStore()
        store.fail = True
        plan = build_plan(inbox, [], FfmpegRenderer(config, logger), logger)
        with pytest.raises(RuntimeError):
            apply_plan(plan, inbox, store, "assets-x", logger, staging=tmp_path / "s")
        assert (inbox / "hooks" / "a.mp4").is_file()

    def test_rejected_files_stay_in_the_inbox(
        self, inbox: Path, clips: dict[str, Path], config, logger, tmp_path: Path
    ) -> None:
        shutil.copy2(clips["portrait"], inbox / "hooks" / "good.mp4")
        (inbox / "hooks" / "bad.mp4").write_text("junk", encoding="utf-8")
        store = RecordingStore()
        plan = build_plan(inbox, [], FfmpegRenderer(config, logger), logger)
        apply_plan(plan, inbox, store, "assets-x", logger, staging=tmp_path / "s")
        assert (inbox / "hooks" / "bad.mp4").is_file()
        assert not (inbox / "hooks" / "good.mp4").exists()

    def test_staging_is_cleaned_up(
        self, inbox: Path, clips: dict[str, Path], config, logger, tmp_path: Path
    ) -> None:
        shutil.copy2(clips["portrait"], inbox / "hooks" / "a.mp4")
        stage = tmp_path / "stage"
        plan = build_plan(inbox, [], FfmpegRenderer(config, logger), logger)
        apply_plan(plan, inbox, RecordingStore(), "assets-x", logger, staging=stage)
        assert not stage.exists()


class TestLibraryHealth:
    """The sizing warnings, computed on the real numbers a user will have."""

    def test_flags_hook_cooldown_shortfall(self) -> None:
        # 6 hooks, 6/day, 3-day cooldown -> needs 18.
        warnings = library_health(6, 3, 5, 5, 1, 6, 3, 14)
        assert any("hook cooldown needs 18" in w for w in warnings)

    def test_flags_caption_cooldown_shortfall(self) -> None:
        warnings = library_health(6, 3, 5, 5, 1, 6, 3, 14)
        assert any("caption cooldown needs 84" in w for w in warnings)

    def test_flags_body_repetition(self) -> None:
        warnings = library_health(6, 3, 5, 5, 1, 6, 3, 14)
        assert any("goes out 2.0× a day" in w for w in warnings)

    def test_healthy_library_produces_no_warnings(self) -> None:
        # 25 captions, 2/day, cooldowns satisfied.
        assert library_health(6, 4, 5, 25, 1, 2, 3, 12) == []

    def test_no_warnings_for_an_empty_library(self) -> None:
        """Nothing uploaded yet is not a misconfiguration."""
        assert library_health(0, 0, 0, 0, 1, 6, 3, 14) == []


class TestCombinations:
    def test_matches_the_selector_ceiling(self) -> None:
        from src.selector import AssetLibrary

        lib = AssetLibrary(
            hooks=tuple(f"h{i}" for i in range(6)),
            bodies=tuple(f"b{i}" for i in range(3)),
            music=tuple(f"m{i}" for i in range(5)),
            captions=tuple(f"c{i}" for i in range(5)),
        )
        assert combinations(6, 3, 5, 5, 1) == lib.ceiling(1) == 450

    def test_no_music_counts_as_one_option(self) -> None:
        assert combinations(2, 2, 0, 3, 1) == 12

    def test_too_few_bodies_gives_zero(self) -> None:
        assert combinations(5, 1, 2, 2, 3) == 0
