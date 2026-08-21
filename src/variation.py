"""Per-variant creative treatment.

Responsibility: turn a variant id into a reproducible set of framing, grade and
pacing choices, and express them as ffmpeg filters.

Why seeded rather than random: a variant that performed well is worth knowing
the recipe for. ``treatment_for("abc123", config)`` returns the same treatment
on any machine, any day, so a winning render can be traced back to the exact
crop, grade and pace that produced it — and a losing one can be ruled out. An
unseeded ``random()`` would make every render un-reproducible and the A/B data
worthless.

What this is not: the numbers here are deliberately *perceptible*. Sub-1%
adjustments are invisible to a viewer, which makes them worthless as creative
variation — two cuts that look identical are identical for every purpose that
matters. Defaults sit at the low end of what a person would notice as "a
different edit" rather than the high end of what a machine would notice as
"a different file".

Ordering is load-bearing and is documented at ``video_filters``.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from src.config import VariationConfig


@dataclass(frozen=True)
class Treatment:
    """One variant's look, derived from its id."""

    #: Extra scale before cropping back to frame, as a fraction (0.04 = 4%).
    zoom: float
    #: Where the crop sits in the overscan, 0..1 on each axis. 0.5 is centred.
    anchor_x: float
    anchor_y: float
    #: Frame rotation in degrees. Small; the crop hides the corners.
    rotate_deg: float
    #: eq brightness, -1..1 in ffmpeg terms. Kept to a few percent.
    brightness: float
    #: eq saturation, 1.0 is unchanged.
    saturation: float
    #: hue rotation in degrees.
    hue_deg: float
    #: noise strength, 0 disables.
    grain: float
    #: playback rate. 1.0 is unchanged; affects video and audio together.
    speed: float
    #: Horizontal flip. Destroys on-screen text and mirrors any logo, so it is
    #: opt-in per campaign rather than part of the default mix.
    mirror: bool
    #: Music bed tempo, independent of ``speed``. 1.0 is unchanged.
    music_tempo: float = 1.0
    #: Shelf tilt on the bed in dB: positive is brighter, negative warmer.
    music_tilt_db: float = 0.0

    @property
    def rotate_rad(self) -> float:
        return math.radians(self.rotate_deg)

    def required_overscan(self, width: int, height: int) -> float:
        """Extra scale needed so rotation cannot expose a corner.

        Rotating a w x h frame by θ and cropping back to w x h needs the source
        scaled by ``cos θ + (h/w)·sin θ`` on the wide axis. At 0.6° on a 9:16
        frame that is about 2%, which is why rotation without overscan shows
        black wedges in the corners — the failure this exists to prevent.
        """
        if not self.rotate_deg:
            return 0.0
        theta = abs(self.rotate_rad)
        long_side, short_side = max(width, height), min(width, height)
        ratio = long_side / short_side
        return (math.cos(theta) + ratio * math.sin(theta)) - 1.0

    def video_filters(self, width: int, height: int, fps: int) -> str:
        """The filter chain, in the only order that composes correctly.

        1. ``scale`` up by the effective overscan — everything after this has
           material to spare at the edges.
        2. ``rotate`` while that spare material exists.
        3. ``crop`` back to frame at the anchor, which removes both the
           rotation's corners and the surplus from the zoom.
        4. ``hflip`` after cropping, so the anchor still means what it says.
        5. Grade, then grain: grain applied before a saturation change would be
           graded along with the picture and stop looking like grain.
        6. ``setsar``/``fps``/``format`` last, exactly as the un-varied path
           leaves them, because concat requires every part to agree.
        """
        # The zoom must cover the rotation, or the corners show.
        overscan = max(self.zoom, self.required_overscan(width, height))
        # A little headroom so rounding in scale cannot leave a one-pixel edge.
        overscan += 0.004 if self.rotate_deg else 0.0
        scaled_w = int(round(width * (1.0 + overscan)))
        scaled_h = int(round(height * (1.0 + overscan)))
        # Even dimensions keep yuv420p chroma subsampling exact.
        scaled_w += scaled_w % 2
        scaled_h += scaled_h % 2

        chain = [
            f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase",
        ]
        if self.rotate_deg:
            # bilinear=0 avoids softening the whole frame for a sub-degree turn.
            chain.append(
                f"rotate={self.rotate_rad:.6f}:ow=rotw({self.rotate_rad:.6f})"
                f":oh=roth({self.rotate_rad:.6f}):bilinear=0"
            )
        chain.append(
            f"crop={width}:{height}"
            f":(in_w-out_w)*{self.anchor_x:.4f}"
            f":(in_h-out_h)*{self.anchor_y:.4f}"
        )
        if self.mirror:
            chain.append("hflip")
        if self.brightness or self.saturation != 1.0:
            chain.append(
                f"eq=brightness={self.brightness:.4f}"
                f":saturation={self.saturation:.4f}"
            )
        if self.hue_deg:
            chain.append(f"hue=h={self.hue_deg:.3f}")
        if self.grain:
            # allf=t+u — temporal so it moves frame to frame, uniform so it
            # reads as film grain rather than as digital blocking.
            chain.append(f"noise=alls={self.grain:.0f}:allf=t+u")
        if self.speed != 1.0:
            chain.append(f"setpts=PTS/{self.speed:.5f}")
        chain += [f"setsar=1", f"fps={fps}", "format=yuv420p"]
        return ",".join(chain)

    def audio_filters(self) -> str:
        """Audio side of the speed change, or empty.

        Not optional when the video is re-timed: leaving audio at 1.0 while the
        picture runs at 0.97 desynchronises them by a second every thirty, and
        the drift is cumulative across a concatenated video.
        """
        if self.speed == 1.0:
            return ""
        return f"atempo={self.speed:.5f}"

    def music_filters(self) -> str:
        """Bed treatment, applied to the music only.

        Separate from ``audio_filters`` on purpose. That one retimes the
        clip's own audio to match a retimed picture and is not optional. This
        one shapes the bed underneath the voice, which can move freely because
        nothing is synchronised to it.

        Order: tempo first, then tone. atempo resamples, and shelving before
        a resample would move the corner frequencies along with it.
        """
        parts: list[str] = []
        if self.music_tempo != 1.0:
            parts.append(f"atempo={self.music_tempo:.5f}")
        if self.music_tilt_db:
            # A tilt, not a boost: lifting the top while trimming the bottom
            # by the same amount keeps the bed at roughly the same loudness,
            # so music_volume still means what it says.
            parts.append(f"treble=g={self.music_tilt_db:.2f}:f=8000")
            parts.append(f"bass=g={-self.music_tilt_db:.2f}:f=200")
        return ",".join(parts)

    def as_dict(self) -> dict[str, float | bool]:
        """Flat record for the queue, so a winner can be traced to its recipe."""
        return {
            "zoom": round(self.zoom, 4),
            "anchor_x": round(self.anchor_x, 3),
            "anchor_y": round(self.anchor_y, 3),
            "rotate_deg": round(self.rotate_deg, 3),
            "brightness": round(self.brightness, 4),
            "saturation": round(self.saturation, 4),
            "hue_deg": round(self.hue_deg, 2),
            "grain": round(self.grain, 2),
            "speed": round(self.speed, 4),
            "mirror": self.mirror,
            "music_tempo": round(self.music_tempo, 4),
            "music_tilt_db": round(self.music_tilt_db, 2),
        }


NEUTRAL = Treatment(
    zoom=0.0, anchor_x=0.5, anchor_y=0.5, rotate_deg=0.0,
    brightness=0.0, saturation=1.0, hue_deg=0.0, grain=0.0,
    speed=1.0, mirror=False,
)


def _stream(variant_id: str) -> "list[float]":
    """A deterministic 0..1 sequence from an id.

    SHA-256 rather than ``random.seed(hash(id))``: Python's ``hash`` of a str
    is salted per process, so the same variant would treat differently on every
    run — the exact opposite of the point.
    """
    digest = hashlib.sha256(variant_id.encode("utf-8")).digest()
    # 32 bytes is more than the eight draws below need.
    return [b / 255.0 for b in digest]


def treatment_for(variant_id: str, config: VariationConfig) -> Treatment:
    """The treatment for one variant. Same id, same result, always."""
    if not config.enabled:
        return NEUTRAL

    draw = _stream(variant_id)

    def spread(index: int, magnitude: float) -> float:
        """A signed value in [-magnitude, +magnitude]."""
        return (draw[index] * 2.0 - 1.0) * magnitude

    rotate = spread(3, config.rotate_max_deg)
    return Treatment(
        zoom=draw[0] * config.zoom_max,
        # Anchors stay off the extremes: a crop pinned hard to one edge
        # reframes the shot rather than nudging it, and subjects are centred.
        anchor_x=0.25 + draw[1] * 0.5,
        anchor_y=0.25 + draw[2] * 0.5,
        rotate_deg=rotate,
        brightness=spread(4, config.brightness_max),
        saturation=1.0 + spread(5, config.saturation_max),
        hue_deg=spread(6, config.hue_max_deg),
        grain=draw[7] * config.grain_max,
        speed=1.0 + spread(8, config.speed_max),
        mirror=bool(config.allow_mirror and draw[9] > 0.5),
        music_tempo=1.0 + spread(10, config.music_tempo_max),
        music_tilt_db=spread(11, config.music_tilt_db),
    )
