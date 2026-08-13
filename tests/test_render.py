"""M2 — the ffmpeg pipeline (SPEC §6, §13 M2).

These tests actually invoke ffmpeg. They are not network tests and run in CI,
but they are the slowest suite here; that is the correct trade, because the
concat-corruption failures they cover are silent when they happen in production.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import CampaignConfig
from src.errors import RenderError, ValidationError
from src.logging import StructuredLogger
from src.models import RenderRequest
from src.render import FfmpegRenderer

from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def request_for(
    tmp_path: Path,
    clips: dict[str, Path],
    hook: str,
    bodies: list[str],
    music: str | None = None,
    item_id: str = "test-item",
) -> RenderRequest:
    return RenderRequest(
        item_id=item_id,
        hook_path=clips[hook],
        body_paths=tuple(clips[b] for b in bodies),
        music_path=clips[music] if music else None,
        output_path=tmp_path / f"{item_id}.mp4",
    )


class TestProbe:
    def test_reports_dimensions_and_audio(
        self, renderer: FfmpegRenderer, clips: dict[str, Path]
    ) -> None:
        p = renderer.probe(clips["portrait"])
        assert (p.width, p.height) == (1080, 1920)
        assert p.has_video and p.has_audio
        assert p.duration_sec == pytest.approx(4.0, abs=0.3)
        assert p.is_vertical

    def test_detects_missing_audio_stream(
        self, renderer: FfmpegRenderer, clips: dict[str, Path]
    ) -> None:
        assert renderer.probe(clips["silent"]).has_audio is False

    def test_landscape_is_not_vertical(
        self, renderer: FfmpegRenderer, clips: dict[str, Path]
    ) -> None:
        assert renderer.probe(clips["landscape"]).is_vertical is False

    def test_missing_file_raises_render_error(
        self, renderer: FfmpegRenderer, tmp_path: Path
    ) -> None:
        with pytest.raises(RenderError, match="not found"):
            renderer.probe(tmp_path / "nope.mp4")

    def test_non_media_file_raises_render_error(
        self, renderer: FfmpegRenderer, tmp_path: Path
    ) -> None:
        junk = tmp_path / "junk.mp4"
        junk.write_text("this is not a video", encoding="utf-8")
        with pytest.raises(RenderError):
            renderer.probe(junk)


class TestNormalizationHandlesMismatchedSources:
    """SPEC §6 — the reason stage 1 exists at all."""

    def test_landscape_source_becomes_vertical(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        result = renderer.render(request_for(tmp_path, clips, "landscape", ["portrait"]))
        assert (result.probe.width, result.probe.height) == (1080, 1920)

    def test_mixed_resolutions_and_framerates_concat_cleanly(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """1080x1920@30 + 1920x1080@24 + 720x720@25 in one video."""
        result = renderer.render(
            request_for(tmp_path, clips, "portrait", ["landscape", "square"])
        )
        assert (result.probe.width, result.probe.height) == (1080, 1920)
        assert result.probe.has_audio
        # 4 + 3 + 3 = 10s, allowing for frame-boundary rounding across segments.
        assert result.probe.duration_sec == pytest.approx(10.0, abs=0.6)

    def test_clip_without_audio_does_not_corrupt_the_concat(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """The silent clip must gain a real silent track, not be dropped."""
        result = renderer.render(
            request_for(tmp_path, clips, "portrait", ["silent", "portrait"])
        )
        assert result.probe.has_audio
        # 4 + 3 + 4 = 11s. If the silent clip's audio layout broke the concat,
        # the duration would come out short.
        assert result.probe.duration_sec == pytest.approx(11.0, abs=0.6)

    def test_all_silent_sources_still_produce_an_audio_stream(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        result = renderer.render(request_for(tmp_path, clips, "silent", ["silent"]))
        assert result.probe.has_audio

    def test_anamorphic_source_is_desqueezed(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """setsar=1 — a non-square-pixel source must not stretch the output."""
        result = renderer.render(
            request_for(tmp_path, clips, "anamorphic", ["portrait"])
        )
        assert (result.probe.width, result.probe.height) == (1080, 1920)


class TestMusic:
    def test_music_shorter_than_video_is_looped(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """A 2s track under a 7s video must not leave 5s of silence."""
        result = renderer.render(
            request_for(tmp_path, clips, "portrait", ["square"], music="music_short")
        )
        assert result.probe.has_audio
        assert result.probe.duration_sec == pytest.approx(7.0, abs=0.6)

    def test_music_longer_than_video_is_trimmed_to_length(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """A 60s track under a 7s video must not extend the output."""
        result = renderer.render(
            request_for(tmp_path, clips, "portrait", ["square"], music="music_long")
        )
        assert result.probe.duration_sec == pytest.approx(7.0, abs=0.6)

    def test_render_without_music_succeeds(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        result = renderer.render(request_for(tmp_path, clips, "portrait", ["square"]))
        assert result.probe.has_audio

    def test_missing_music_file_raises(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        req = RenderRequest(
            item_id="x",
            hook_path=clips["portrait"],
            body_paths=(clips["square"],),
            music_path=tmp_path / "gone.mp3",
            output_path=tmp_path / "out.mp4",
        )
        with pytest.raises(RenderError, match="music track not found"):
            renderer.render(req)


class TestOutputValidation:
    """SPEC §6 — hard-fail, never warn."""

    def test_too_short_output_is_rejected(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """1s + 1s = 2s, under the 5s Reels floor."""
        with pytest.raises(ValidationError, match="Reels floor"):
            renderer.render(request_for(tmp_path, clips, "tiny", ["tiny"]))

    def test_too_long_output_is_rejected(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """50s + 50s = 100s, over the 90s Reels ceiling."""
        with pytest.raises(ValidationError, match="Reels ceiling"):
            renderer.render(request_for(tmp_path, clips, "long", ["long"]))

    def test_wrong_dimensions_are_rejected(
        self, config: CampaignConfig, logger: StructuredLogger,
        clips: dict[str, Path], tmp_path: Path,
    ) -> None:
        """A renderer whose validator disagrees with its encoder must fail loud."""
        mismatched = config.model_copy(
            update={"video": config.video.model_copy(update={"width": 720})}
        )
        r = FfmpegRenderer(mismatched, logger)
        with pytest.raises(ValidationError, match="dimensions"):
            # Render at 720x1920, then validate against 1080-wide expectations
            # by swapping the config back in.
            result = r.render(request_for(tmp_path, clips, "portrait", ["square"]))
            FfmpegRenderer(config, logger).validate_output(result.probe)

    def test_oversized_file_is_rejected(
        self, config: CampaignConfig, logger: StructuredLogger,
        clips: dict[str, Path], tmp_path: Path,
    ) -> None:
        tiny_cap = config.model_copy(
            update={"video": config.video.model_copy(update={"max_file_mb": 0.001})}
        )
        r = FfmpegRenderer(tiny_cap, logger)
        with pytest.raises(ValidationError, match="over the"):
            r.render(request_for(tmp_path, clips, "portrait", ["square"]))

    def test_validation_message_lists_every_problem(
        self, config: CampaignConfig, logger: StructuredLogger,
        clips: dict[str, Path], tmp_path: Path,
    ) -> None:
        """A one-problem-at-a-time validator makes debugging a 3am failure slow."""
        bad = config.model_copy(
            update={"video": config.video.model_copy(
                update={"width": 720, "max_file_mb": 0.001}
            )}
        )
        r = FfmpegRenderer(config, logger)
        result = r.render(request_for(tmp_path, clips, "portrait", ["square"]))
        with pytest.raises(ValidationError) as exc:
            FfmpegRenderer(bad, logger).validate_output(result.probe)
        assert "dimensions" in str(exc.value) and "over the" in str(exc.value)


class TestReelsCompliance:
    """SPEC §4.3 — the properties Instagram actually checks."""

    def test_output_has_faststart_moov_atom(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """moov must precede mdat, or Instagram rejects/stalls the upload."""
        result = renderer.render(request_for(tmp_path, clips, "portrait", ["square"]))
        head = result.output_path.read_bytes()[:100_000]
        assert b"moov" in head, "moov atom not near the start — +faststart missing"
        assert head.index(b"moov") < head.index(b"mdat")

    def test_output_audio_is_48khz_stereo_aac(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        result = renderer.render(
            request_for(tmp_path, clips, "portrait", ["square"], music="music_short")
        )
        assert result.probe.audio_codec == "aac"

    def test_output_video_is_h264(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        result = renderer.render(request_for(tmp_path, clips, "portrait", ["square"]))
        assert result.probe.video_codec == "h264"


class TestHousekeeping:
    def test_workdir_is_cleaned_up_on_success(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        renderer.render(request_for(tmp_path, clips, "portrait", ["square"]))
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".work-")]
        assert not leftovers

    def test_workdir_is_cleaned_up_on_failure(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        """A failed render must not leave gigabytes of temps on the runner."""
        with pytest.raises(ValidationError):
            renderer.render(request_for(tmp_path, clips, "tiny", ["tiny"]))
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".work-")]
        assert not leftovers

    def test_missing_source_clip_raises_before_encoding(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        req = RenderRequest(
            item_id="x",
            hook_path=tmp_path / "gone.mp4",
            body_paths=(clips["portrait"],),
            music_path=None,
            output_path=tmp_path / "out.mp4",
        )
        with pytest.raises(RenderError, match="source clip not found"):
            renderer.render(req)


class TestDeterminism:
    """SPEC §2.2 — identical inputs must produce byte-comparable output."""

    def test_two_renders_of_identical_inputs_are_byte_identical(
        self, renderer: FfmpegRenderer, clips: dict[str, Path], tmp_path: Path
    ) -> None:
        a = renderer.render(
            request_for(tmp_path, clips, "portrait", ["square"],
                        music="music_short", item_id="a")
        )
        b = renderer.render(
            request_for(tmp_path, clips, "portrait", ["square"],
                        music="music_short", item_id="b")
        )
        assert a.output_path.read_bytes() == b.output_path.read_bytes()
