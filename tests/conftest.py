"""Shared test fixtures.

Source clips are *generated* with ffmpeg rather than committed. Binary fixtures
in git go stale, bloat the tree, and hide what they actually contain; a
generator states the awkward property each clip is testing (SPEC §13 M2:
"Deliberately test mismatched resolutions, missing audio streams, landscape
sources, music shorter and longer than the video").

Generated clips are cached in a session-scoped tmp dir so a full run pays the
ffmpeg cost once.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.config import CampaignConfig
from src.logging import StructuredLogger
from src.render import FfmpegRenderer

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

needs_ffmpeg = pytest.mark.skipif(
    not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed"
)


def _ffmpeg(*args: str) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-v", "error", *args],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"fixture generation failed: {proc.stderr[-800:]}")


def _make_clip(
    dest: Path,
    *,
    width: int,
    height: int,
    fps: int,
    seconds: float,
    audio: bool,
    sar: str | None = None,
) -> None:
    """Generate a synthetic clip with the given awkward properties."""
    args = [
        "-f", "lavfi",
        "-i", f"testsrc=size={width}x{height}:rate={fps}:duration={seconds}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]

    vf = "format=yuv420p"
    if sar:
        vf = f"setsar={sar}," + vf
    args += ["-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-t", str(seconds)]
    if audio:
        args += ["-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest"]
    else:
        args += ["-an"]
    args += [str(dest)]
    _ffmpeg(*args)


def _make_audio(dest: Path, *, seconds: float) -> None:
    _ffmpeg(
        "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={seconds}",
        "-c:a", "libmp3lame", "-b:a", "128k",
        "-t", str(seconds),
        str(dest),
    )


@pytest.fixture(scope="session")
def clips(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A library of deliberately mismatched source clips."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("clips")

    made: dict[str, Path] = {}

    # The happy case: already the target shape.
    made["portrait"] = d / "portrait.mp4"
    _make_clip(made["portrait"], width=1080, height=1920, fps=30, seconds=4, audio=True)

    # Landscape source — must be centre-cropped to 9:16, not pillarboxed.
    made["landscape"] = d / "landscape.mp4"
    _make_clip(made["landscape"], width=1920, height=1080, fps=24, seconds=3, audio=True)

    # Square source at a third frame rate.
    made["square"] = d / "square.mp4"
    _make_clip(made["square"], width=720, height=720, fps=25, seconds=3, audio=True)

    # No audio stream at all — SPEC §6 calls this the most common cause of
    # concat corruption.
    made["silent"] = d / "silent.mp4"
    _make_clip(made["silent"], width=1080, height=1920, fps=30, seconds=3, audio=False)

    # Non-square pixels — concatenating this unfixed yields a stretched segment.
    made["anamorphic"] = d / "anamorphic.mp4"
    _make_clip(
        made["anamorphic"], width=1440, height=1080, fps=30, seconds=3,
        audio=True, sar="4/3",
    )

    # Long enough on its own to blow the 90s Reels ceiling when combined.
    made["long"] = d / "long.mp4"
    _make_clip(made["long"], width=1080, height=1920, fps=30, seconds=50, audio=True)

    # Too short to reach the 5s Reels floor by itself.
    made["tiny"] = d / "tiny.mp4"
    _make_clip(made["tiny"], width=1080, height=1920, fps=30, seconds=1, audio=True)

    # Music shorter than any video (must loop) and longer (must be trimmed).
    made["music_short"] = d / "music_short.mp3"
    _make_audio(made["music_short"], seconds=2)
    made["music_long"] = d / "music_long.mp3"
    _make_audio(made["music_long"], seconds=60)

    return made


@pytest.fixture
def config() -> CampaignConfig:
    """A valid campaign config with no campaign-specific content."""
    return CampaignConfig.model_validate(
        {
            "slug": "testcamp",
            "timezone": "America/New_York",
            "video": {"preset": "ultrafast", "crf": 30},
            "buffer": {
                "api_key_secret": "BUFFER_API_KEY",
                "channel_id_secret": "BUFFER_CHANNEL_TESTCAMP",
            },
            "notify": {"webhook_secret": "DISCORD_WEBHOOK_TESTCAMP"},
        }
    )


@pytest.fixture
def logger() -> StructuredLogger:
    """A logger that writes to a throwaway buffer, keeping test output clean."""
    import io

    return StructuredLogger({}, io.StringIO())


@pytest.fixture
def renderer(config: CampaignConfig, logger: StructuredLogger) -> FfmpegRenderer:
    return FfmpegRenderer(config, logger)
