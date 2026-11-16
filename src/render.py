"""Video assembly: the two-stage ffmpeg pipeline of SPEC §6.

Responsibility: turn a hook clip, one or more body clips and an optional music
track into one Reels-eligible MP4 — and refuse to emit anything that is not.

This module is the *only* place in ``src/`` that calls ``subprocess`` (SPEC
§2.2). Everything else talks to the ``Renderer`` ABC.

Why two stages (SPEC §6): the concat demuxer copies streams without decoding,
so it requires every input to already agree on resolution, frame rate, sample
aspect ratio, codec and *stream layout*. Real source clips agree on none of
those, and some have no audio track at all. Concatenating them directly yields
corrupt or desynced output — usually silently. So stage 1 re-encodes each clip
to an identical shape (unavoidable), and stage 2 concatenates the results with
``-c copy`` (fast) while mixing in music.

Every ffmpeg flag below that looks arbitrary carries a comment explaining why it
is there, because most of them are load-bearing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

from src.config import CampaignConfig
from src.errors import RenderError, ValidationError
from src.logging import StructuredLogger
from src.models import MediaProbe, RenderRequest, RenderResult
from src.platforms import Service, effective_video_limits
from src.variation import NEUTRAL, Treatment, treatment_for

#: Sample rate Instagram expects for Reels audio (SPEC §4.3).
AUDIO_RATE = 48000
AUDIO_CHANNELS = 2
AUDIO_BITRATE = "128k"

#: Fonts are named relative to the repo root (``overlay.font_file``).
REPO_ROOT = Path(__file__).resolve().parents[1]


def wrap_overlay(text: str, max_chars: int) -> list[str]:
    """Break on-screen text into lines that fit the frame.

    ffmpeg's drawtext does not wrap, so the wrapping is decided here, on
    word boundaries. A ``|`` in the text is a line break the writer chose and
    is always honoured. Characters outside the Basic Multilingual Plane are
    dropped: that is emoji, which a text font has no glyphs for and would
    draw as empty boxes.
    """
    cleaned = "".join(
        ch for ch in text
        if ord(ch) < 0x2190 or 0x2C00 <= ord(ch) < 0xFE00
    )
    lines: list[str] = []
    for chunk in cleaned.split("|"):
        current = ""
        for word in chunk.split():
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > max_chars:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def _filter_path(path: Path) -> str:
    """A path quoted for use inside an ffmpeg filter option."""
    escaped = str(path).replace("\\", "/").replace("'", r"\'").replace(":", r"\:")
    return f"'{escaped}'"


#: How long ffmpeg may run on a single invocation before we treat it as hung.
#: Generous: a 90s 1080x1920 encode on a cold CI runner is slow but not slower
#: than this, and a hang here would otherwise block the whole nightly job.
FFMPEG_TIMEOUT_SEC = 900
FFPROBE_TIMEOUT_SEC = 60


class Renderer(ABC):
    """Assembles source clips into a finished, validated video."""

    @abstractmethod
    def probe(self, path: Path) -> MediaProbe:
        """Inspect a media file. Raises ``RenderError`` if it is unreadable."""

    @abstractmethod
    def render(self, request: RenderRequest) -> RenderResult:
        """Produce one validated video, or raise.

        Implementations must never return a file that fails ``validate_output``.
        """


def _run(
    argv: Sequence[str],
    *,
    timeout: int,
    log: StructuredLogger,
    stage: str,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, raising ``RenderError`` on any failure.

    ffmpeg writes progress to stderr even on success, so stderr is only
    surfaced when the return code is non-zero — and then it is truncated,
    because a full ffmpeg dump buries the one useful line.
    """
    log.debug("subprocess_start", stage=stage, argv=list(argv))
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RenderError(
            f"{argv[0]} not found on PATH — install ffmpeg before rendering"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(
            f"{argv[0]} timed out after {timeout}s during {stage}"
        ) from exc

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        raise RenderError(
            f"{argv[0]} failed during {stage} (exit {proc.returncode}):\n"
            + "\n".join(tail)
        )
    return proc


class FfmpegRenderer(Renderer):
    """The real renderer, driving ffmpeg/ffprobe as subprocesses."""

    def __init__(
        self,
        config: CampaignConfig,
        log: StructuredLogger,
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        workdir: Path | None = None,
        services: Sequence[Service] | None = None,
    ) -> None:
        #: Every network the output must be valid on. Under fan-out one file
        #: goes to several, so it has to clear the strictest of them — not
        #: just the campaign's own nominal one.
        self._services: tuple[Service, ...] = tuple(
            dict.fromkeys(services or (config.buffer.service,))
        )
        self._config = config
        self._log = log
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._workdir = workdir

    def _limits(self) -> tuple[float, float, float, Service, Service]:
        """(floor, ceiling, max MB, network setting the floor, the ceiling)."""
        v = self._config.video
        per = {
            svc: effective_video_limits(
                svc, v.min_duration_sec, v.max_duration_sec, v.max_file_mb
            )
            for svc in self._services
        }
        floor_svc = max(per, key=lambda k: per[k][0])
        ceiling_svc = min(per, key=lambda k: per[k][1])
        return (
            per[floor_svc][0], per[ceiling_svc][1],
            min(limit[2] for limit in per.values()), floor_svc, ceiling_svc,
        )

    # ---------------------------------------------------------------- probing

    def probe(self, path: Path) -> MediaProbe:
        if not path.is_file():
            raise RenderError(f"media file not found: {path}")

        proc = _run(
            [
                self._ffprobe,
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            timeout=FFPROBE_TIMEOUT_SEC,
            log=self._log,
            stage="probe",
        )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RenderError(f"ffprobe returned unparseable JSON for {path}") from exc

        streams = data.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

        # Duration lives on the container for most files but only on the stream
        # for some (notably raw/streamed sources), so try both before giving up.
        duration = _first_float(
            (data.get("format") or {}).get("duration"),
            (video or {}).get("duration"),
            (audio or {}).get("duration"),
        )
        if duration is None:
            raise RenderError(f"could not determine duration of {path}")

        return MediaProbe(
            path=path,
            duration_sec=duration,
            width=int((video or {}).get("width") or 0),
            height=int((video or {}).get("height") or 0),
            fps=_parse_rational((video or {}).get("avg_frame_rate")),
            has_video=video is not None,
            has_audio=audio is not None,
            video_codec=(video or {}).get("codec_name"),
            audio_codec=(audio or {}).get("codec_name"),
            size_bytes=path.stat().st_size,
        )

    # --------------------------------------------------------------- stage one

    def _overlay_filters(
        self,
        text: str | None,
        workdir: Path,
        *,
        y: float | None = None,
        scale: float = 1.0,
        tag: str = "overlay",
        enable: str = "",
    ) -> str:
        """drawtext filters for one video's on-screen text, or ``""``.

        One filter per line, each centred on its own width: a single
        multi-line drawtext left-aligns its lines to the widest one, which
        reads as a paragraph rather than a caption. Each line goes through a
        text file so no caption punctuation can break the filter string.
        """
        o = self._config.overlay
        # The switch is for the line drawn over the whole clip. The end card
        # has its own (an empty funnel.end_card) and only borrows the styling:
        # turning the meme line off for clips that already carry text must not
        # also take away the one place the song is named on screen.
        if not text or (tag == "overlay" and not o.enabled):
            return ""
        lines = wrap_overlay(text, o.max_chars)
        if not lines:
            return ""
        font = REPO_ROOT / o.font_file
        if not font.is_file():
            raise RenderError(
                f"overlay font not found: {font} (overlay.font_file is "
                f"relative to the repo root)"
            )
        v = self._config.video
        size = max(8, round(v.width * o.size * scale))
        line_height = round(size * 1.28)
        border = round(size * o.outline)
        top = round(v.height * min(0.95, max(0.0, o.y if y is None else y)))
        when = f":enable='{enable}'" if enable else ""
        filters: list[str] = []
        for index, line in enumerate(lines):
            textfile = workdir / f"{tag}-{index:02d}.txt"
            textfile.write_text(line, encoding="utf-8")
            filters.append(
                f"drawtext=fontfile={_filter_path(font)}"
                f":textfile={_filter_path(textfile.resolve())}"
                f":fontsize={size}:fontcolor={o.color}"
                f":borderw={border}:bordercolor={o.outline_color}"
                f":x=(w-text_w)/2:y={top + index * line_height}{when}"
            )
        return ",".join(filters)

    def _normalize(
        self, src: Path, dest: Path, treatment: "Treatment | None" = None,
        overlay: str = "", trim_start: float = 0.0,
    ) -> None:
        """Re-encode one clip to the campaign's exact output shape.

        After this runs on every clip, all temps share resolution, fps, SAR,
        pixel format, codec and stream layout — the preconditions the concat
        demuxer needs in stage 2.
        """
        v = self._config.video
        probe = self.probe(src)
        if not probe.has_video:
            raise RenderError(f"{src.name} has no video stream")

        argv: list[str] = [self._ffmpeg, "-y", "-nostdin"]

        # Bit-exact flags strip the encoder version string and creation time
        # from the output. Without them two renders of identical inputs differ
        # in their metadata, which breaks the byte-comparability SPEC §2.2 asks
        # for and makes the acceptance tests unfalsifiable.
        argv += ["-fflags", "+bitexact"]

        # Only when it leaves a usable clip: trimming a two-second clip by
        # most of a second would change what the video is, not nudge it.
        if trim_start > 0 and probe.duration_sec - trim_start >= 2.0:
            argv += ["-ss", f"{trim_start:.3f}"]
        argv += ["-i", str(src)]

        if not probe.has_audio:
            # SPEC §6: a clip with no audio stream is the single most common
            # cause of concat corruption — the demuxer expects every segment to
            # have the same streams in the same order. Attaching real silence
            # (not "-an") keeps the layout uniform.
            argv += [
                "-f", "lavfi",
                "-i", f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}",
            ]
            audio_map = "1:a"
        else:
            audio_map = "0:a"

        # scale=...:force_original_aspect_ratio=increase then crop is a centre-
        # crop cover fit: scale up until BOTH dimensions are >= target, then trim
        # the overflow. This is what turns landscape and square sources into a
        # filled 9:16 frame with no pillarboxing.
        # setsar=1 forces square pixels — a source with a non-1 sample aspect
        # ratio would otherwise concat into a stretched segment.
        # A variant's treatment replaces the whole chain rather than appending
        # to it: zoom, rotation and crop have to compose in a specific order
        # (see Treatment.video_filters), and the plain path is just the
        # treatment with every knob at zero.
        if treatment is not None and treatment is not NEUTRAL:
            vf = treatment.video_filters(v.width, v.height, v.fps)
        else:
            vf = (
                f"scale={v.width}:{v.height}:force_original_aspect_ratio=increase,"
                f"crop={v.width}:{v.height},"
                f"setsar=1,"
                f"fps={v.fps},"
                f"format=yuv420p"  # broad player/Instagram compatibility
            )

        if overlay:
            # Last in the chain, after any treatment: the text must sit square
            # and sharp on the finished frame, not be zoomed, rotated or
            # regraded along with the footage under it.
            vf = f"{vf},{overlay}"

        audio_filters = treatment.audio_filters() if treatment else ""
        argv += [
            "-map", "0:v:0",
            "-map", audio_map,
            "-vf", vf,
        ]
        if audio_filters:
            # Mandatory whenever the picture is retimed: audio left at 1.0
            # against video at 0.97 drifts a second every thirty, and the error
            # accumulates across every part of a concatenated video.
            argv += ["-af", audio_filters]
        argv += [
            "-c:v", "libx264",
            "-crf", str(v.crf),
            "-preset", v.preset,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", AUDIO_BITRATE,
            "-ar", str(AUDIO_RATE),
            "-ac", str(AUDIO_CHANNELS),
            # Strip all source metadata: chapter markers and rotation matrices
            # from phone footage survive concat and confuse downstream players.
            "-map_metadata", "-1",
            # -shortest matters only in the silent-audio case, where anullsrc is
            # an infinite source and would otherwise never end.
            "-shortest",
            str(dest),
        ]
        _run(argv, timeout=FFMPEG_TIMEOUT_SEC, log=self._log, stage="normalize")

    # --------------------------------------------------------------- stage two

    def _concat_and_mix(
        self,
        parts: Sequence[Path],
        music: Path | None,
        dest: Path,
        workdir: Path,
        music_offset_sec: float = 0.0,
        treatment: "Treatment | None" = None,
        final_part: Path | None = None,
    ) -> None:
        """Concatenate normalized parts and lay music under the whole video."""
        c = self._config.composition
        if c.loop_to_min:
            floor = self._limits()[0]
            once = sum(self.probe(p).duration_sec for p in parts)
            if 0 < once < floor:
                # A hair over, so encoder rounding cannot land it back under.
                repeats = int((floor + 0.25) // once) + 1
                self._log.info(
                    "looped_to_min", once_sec=round(once, 2), repeats=repeats,
                    floor=floor,
                )
                parts = list(parts) * repeats
        if final_part is not None:
            # The end card belongs on the last thing a viewer sees, once —
            # not on every pass of a looped clip.
            parts = [*list(parts)[:-1], final_part]

        listfile = workdir / "concat.txt"
        # The concat demuxer's own quoting rules: single quotes around the path,
        # with any literal single quote escaped as '\''.
        listfile.write_text(
            "".join(
                "file '{}'\n".format(str(p.resolve()).replace("'", "'\\''"))
                for p in parts
            ),
            encoding="utf-8",
        )

        argv: list[str] = [self._ffmpeg, "-y", "-nostdin", "-fflags", "+bitexact"]
        # -safe 0 permits absolute paths in the list file.
        argv += ["-f", "concat", "-safe", "0", "-i", str(listfile)]

        clip_volume = c.clip_volume
        if music is None and clip_volume != 1.0:
            # No bed to mix, but the clips' own level is being changed, so the
            # audio is re-encoded while the picture is still copied.
            argv += [
                "-af", f"volume={clip_volume}",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CHANNELS),
                "-map_metadata", "-1",
                "-movflags", "+faststart",
                str(dest),
            ]
            _run(argv, timeout=FFMPEG_TIMEOUT_SEC, log=self._log, stage="concat")
            return

        if music is None:
            # No music: the concatenated audio is the final audio, and the whole
            # file can be stream-copied.
            argv += [
                "-c", "copy",
                "-map_metadata", "-1",
                "-movflags", "+faststart",
                str(dest),
            ]
            _run(argv, timeout=FFMPEG_TIMEOUT_SEC, log=self._log, stage="concat")
            return

        # -stream_loop -1 must precede the input it applies to. SPEC §6: a track
        # shorter than the video would otherwise leave silence for the remainder.
        argv += ["-stream_loop", "-1", "-i", str(music)]

        duration = sum(self.probe(p).duration_sec for p in parts)
        fade_start = max(0.0, duration - c.music_fade_out_sec)

        # atrim cuts the (now infinitely looped) music to the video length,
        # starting at the chosen offset so the bed can come from anywhere in
        # the track rather than always from 0:00. Because the input is looped,
        # an offset near the end simply wraps — no need to know the track
        # length here.
        # asetpts rebases timestamps after the trim, without which the mixed
        # track starts at the wrong offset.
        # A fade-IN matters once the start is arbitrary: dropping in mid-phrase
        # at full level pops audibly.
        # amix normalize=0 is essential: with the default normalize=1 ffmpeg
        # divides every input by the number of inputs, which would halve the
        # spoken audio and make music_volume mean something other than what it
        # says. duration=first ties the mix length to the video's own audio.
        start = max(0.0, music_offset_sec)
        fade_in = min(c.music_fade_in_sec, duration / 2)
        # The bed's own treatment goes first, before the trim: atempo changes
        # how much material a given number of seconds contains, so trimming
        # first and retiming after would leave the bed short of the video.
        bed = treatment.music_filters() if treatment else ""
        bed = f"{bed}," if bed else ""
        filter_complex = (
            f"[1:a]volume={c.music_volume},"
            f"{bed}"
            f"atrim={start:.3f}:{start + duration:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade_in:.3f},"
            f"afade=t=out:st={fade_start:.3f}:d={c.music_fade_out_sec}[music];"
            # The clips' own sound at its configured level: untouched under a
            # bed, silent when the song is the content.
            f"[0:a]volume={clip_volume}[clips];"
            f"[clips][music]amix=inputs=2:duration=first:normalize=0[aout]"
        )

        argv += [
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            # Video is already in its final form from stage 1 — copying it keeps
            # this stage fast and avoids a second generation of encode loss.
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", AUDIO_BITRATE,
            "-ar", str(AUDIO_RATE),
            "-ac", str(AUDIO_CHANNELS),
            "-map_metadata", "-1",
            # SPEC §4.3: Instagram requires the moov atom at the front of the
            # file. Without +faststart it lands at the end and the upload is
            # rejected or stalls. This flag is mandatory, not an optimisation.
            "-movflags", "+faststart",
            str(dest),
        ]
        _run(argv, timeout=FFMPEG_TIMEOUT_SEC, log=self._log, stage="concat_mix")

    # ------------------------------------------------------------------ public

    def render(self, request: RenderRequest) -> RenderResult:
        log = self._log.bind(item_id=request.item_id)
        log.info(
            "render_start",
            hook=request.hook_path.name,
            bodies=[p.name for p in request.body_paths],
            music=request.music_path.name if request.music_path else None,
            music_offset_sec=request.music_offset_sec,
        )

        sources = [request.hook_path, *request.body_paths]
        for src in sources:
            if not src.is_file():
                raise RenderError(f"source clip not found: {src}")
        if request.music_path is not None and not request.music_path.is_file():
            raise RenderError(f"music track not found: {request.music_path}")

        request.output_path.parent.mkdir(parents=True, exist_ok=True)

        workdir = self._workdir or request.output_path.parent / f".work-{request.item_id}"
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            # One treatment for the whole video, keyed on the item id: the
            # parts of a single cut must share a grade and a pace, or the
            # joins become visible at exactly the moment attention is highest.
            treatment = treatment_for(request.item_id, self._config.variation)
            if treatment is not NEUTRAL:
                log.info("variant_treatment", **treatment.as_dict())

            overlay = self._overlay_filters(
                request.overlay_text, workdir,
                y=self._config.overlay.y + treatment.overlay_shift,
            )
            normalized: list[Path] = []
            for index, src in enumerate(sources):
                temp = workdir / f"norm-{index:03d}.mp4"
                self._normalize(
                    src, temp, treatment, overlay,
                    trim_start=treatment.trim_start if index == 0 else 0.0,
                )
                normalized.append(temp)
                log.debug("normalized", source=src.name, temp=temp.name)

            final_part: Path | None = None
            funnel = self._config.funnel
            if request.end_card_text:
                # A second copy of the last clip carrying the end card, timed
                # against that clip's own finished length.
                length = self.probe(normalized[-1]).duration_sec
                start = max(0.0, length - funnel.end_card_sec)
                card = self._overlay_filters(
                    request.end_card_text, workdir,
                    y=funnel.end_card_y, scale=0.8, tag="endcard",
                    enable=f"gte(t,{start:.3f})",
                )
                if card:
                    final_part = workdir / "norm-end.mp4"
                    self._normalize(
                        sources[-1], final_part, treatment,
                        ",".join(f for f in (overlay, card) if f),
                        trim_start=treatment.trim_start if len(sources) == 1 else 0.0,
                    )

            self._concat_and_mix(
                normalized, request.music_path, request.output_path, workdir,
                request.music_offset_sec, treatment, final_part,
            )
        finally:
            # Temps are large; leaving them behind fills a CI runner's disk
            # partway through a 24-video batch.
            shutil.rmtree(workdir, ignore_errors=True)

        probe = self.probe(request.output_path)
        self.validate_output(probe)
        log.info(
            "render_ok",
            duration_sec=round(probe.duration_sec, 2),
            size_mb=round(probe.size_bytes / 1_000_000, 2),
            dimensions=f"{probe.width}x{probe.height}",
        )
        return RenderResult(
            item_id=request.item_id, output_path=request.output_path, probe=probe,
            # None when variation is off, so an untreated render records
            # nothing rather than a row of zeros that reads as a real recipe.
            treatment=(
                treatment.as_dict() if treatment is not NEUTRAL else None
            ),
        )

    def validate_output(self, probe: MediaProbe) -> None:
        """Hard-fail the checks in SPEC §6.

        These are failures, never warnings. SPEC §4.2's original premise was that
        a bad file reaching Buffer could not be recalled; the live API does in
        fact expose ``deletePost`` (see README §0), but deletion only helps while
        the post is still queued. Once Instagram publishes it, it is out — so the
        gate stays hard.
        """
        v = self._config.video
        floor, ceiling, max_mb, floor_svc, ceiling_svc = self._limits()
        problems: list[str] = []

        if not probe.has_video:
            problems.append("no video stream")
        if not probe.has_audio:
            problems.append("no audio stream")
        if probe.duration_sec < floor:
            problems.append(
                f"duration {probe.duration_sec:.2f}s is under the {floor:.0f}s "
                f"floor for {floor_svc.value}"
            )
        if probe.duration_sec > ceiling:
            problems.append(
                f"duration {probe.duration_sec:.2f}s exceeds the {ceiling:.0f}s "
                f"ceiling for {ceiling_svc.value}"
            )
        if (probe.width, probe.height) != (v.width, v.height):
            problems.append(
                f"dimensions {probe.width}x{probe.height} != "
                f"configured {v.width}x{v.height}"
            )
        size_mb = probe.size_bytes / 1_000_000
        if size_mb > max_mb:
            problems.append(
                f"file is {size_mb:.1f} MB, over the {max_mb:.0f} MB cap"
            )

        if problems:
            raise ValidationError(
                f"{probe.path.name} failed render validation: " + "; ".join(problems)
            )


def _first_float(*values: object) -> float | None:
    """Return the first value parseable as a positive float."""
    for value in values:
        if value is None:
            continue
        try:
            parsed = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _parse_rational(value: object) -> float:
    """Parse ffprobe's ``"30000/1001"`` frame-rate notation.

    ffprobe reports ``0/0`` for streams with no meaningful frame rate, which
    must come back as 0.0 rather than raising.
    """
    if not isinstance(value, str) or "/" not in value:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
    num, _, den = value.partition("/")
    try:
        numerator, denominator = float(num), float(den)
    except ValueError:
        return 0.0
    return numerator / denominator if denominator else 0.0
