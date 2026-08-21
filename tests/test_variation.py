"""Per-variant creative treatment.

Two properties carry the feature. It has to be reproducible — a variant that
performs is worth knowing the recipe for, and an unseeded treatment makes the
A/B data worthless. And the filter chain has to compose in the right order, or
rotation shows black corners and a crop anchor stops meaning what it says.
"""

from __future__ import annotations

import math
import subprocess
import sys

import pytest

from src.config import VariationConfig
from src.variation import NEUTRAL, Treatment, treatment_for

ON = VariationConfig(enabled=True)


class TestReproducibility:
    def test_the_same_id_always_treats_the_same(self) -> None:
        assert treatment_for("item-7", ON) == treatment_for("item-7", ON)

    def test_different_ids_treat_differently(self) -> None:
        assert treatment_for("item-7", ON) != treatment_for("item-8", ON)

    def test_it_survives_a_different_process(self) -> None:
        """Seeding on Python's hash() of a string would break this.

        str hashing is salted per process, so the same variant would look
        different on every run — the exact opposite of being able to trace a
        winner back to its recipe.
        """
        script = (
            "import json,sys;"
            "sys.path.insert(0,'.');"
            "from src.config import VariationConfig;"
            "from src.variation import treatment_for;"
            "print(json.dumps(treatment_for('item-7',"
            " VariationConfig(enabled=True)).as_dict()))"
        )
        runs = {
            subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, check=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
            ).stdout.strip()
            for seed in ("0", "1", "12345")
        }
        assert len(runs) == 1, "treatment changed with the hash seed"


class TestDisabled:
    def test_off_by_default(self) -> None:
        assert VariationConfig().enabled is False

    def test_disabled_returns_the_neutral_treatment(self) -> None:
        assert treatment_for("anything", VariationConfig()) is NEUTRAL

    def test_the_neutral_treatment_changes_nothing(self) -> None:
        assert NEUTRAL.speed == 1.0 and NEUTRAL.saturation == 1.0
        assert NEUTRAL.zoom == 0.0 and NEUTRAL.rotate_deg == 0.0
        assert NEUTRAL.audio_filters() == ""


class TestRanges:
    @pytest.mark.parametrize("variant", [f"v{i}" for i in range(60)])
    def test_every_draw_stays_inside_the_configured_bounds(
        self, variant: str
    ) -> None:
        t = treatment_for(variant, ON)
        assert 0.0 <= t.zoom <= ON.zoom_max
        assert abs(t.rotate_deg) <= ON.rotate_max_deg
        assert abs(t.brightness) <= ON.brightness_max
        assert abs(t.saturation - 1.0) <= ON.saturation_max
        assert abs(t.hue_deg) <= ON.hue_max_deg
        assert 0.0 <= t.grain <= ON.grain_max
        assert abs(t.speed - 1.0) <= ON.speed_max

    @pytest.mark.parametrize("variant", [f"v{i}" for i in range(40)])
    def test_the_crop_anchor_never_pins_to_an_edge(self, variant: str) -> None:
        """A hard-edge anchor reframes the shot instead of nudging it, and
        subjects are centred."""
        t = treatment_for(variant, ON)
        assert 0.2 <= t.anchor_x <= 0.8
        assert 0.2 <= t.anchor_y <= 0.8

    def test_a_zeroed_config_produces_no_movement(self) -> None:
        flat = VariationConfig(
            enabled=True, zoom_max=0, rotate_max_deg=0, brightness_max=0,
            saturation_max=0, hue_max_deg=0, grain_max=0, speed_max=0,
        )
        t = treatment_for("v1", flat)
        assert t.zoom == 0 and t.rotate_deg == 0 and t.speed == 1.0


class TestMirror:
    def test_mirroring_is_off_unless_allowed(self) -> None:
        """It reverses on-screen text and flips a logo."""
        assert VariationConfig().allow_mirror is False
        assert not any(
            treatment_for(f"v{i}", ON).mirror for i in range(50)
        )

    def test_allowing_it_produces_some(self) -> None:
        allowed = VariationConfig(enabled=True, allow_mirror=True)
        assert any(treatment_for(f"v{i}", allowed).mirror for i in range(30))


class TestOverscan:
    def test_rotation_demands_overscan(self) -> None:
        rotated = Treatment(**{**NEUTRAL.__dict__, "rotate_deg": 0.6})
        assert rotated.required_overscan(1080, 1920) > 0

    def test_no_rotation_needs_none(self) -> None:
        assert NEUTRAL.required_overscan(1080, 1920) == 0.0

    def test_the_overscan_matches_the_geometry(self) -> None:
        """cos θ + (long/short)·sin θ — the cover factor for a rotated crop."""
        t = Treatment(**{**NEUTRAL.__dict__, "rotate_deg": 0.6})
        theta = math.radians(0.6)
        expected = (math.cos(theta) + (1920 / 1080) * math.sin(theta)) - 1.0
        assert t.required_overscan(1080, 1920) == pytest.approx(expected)

    def test_the_chain_scales_past_the_frame_when_rotating(self) -> None:
        """Rotating without spare material is what shows black corners."""
        t = Treatment(**{**NEUTRAL.__dict__, "rotate_deg": 0.6})
        chain = t.video_filters(1080, 1920, 30)
        scaled_w = int(chain.split("scale=")[1].split(":")[0])
        assert scaled_w > 1080


class TestFilterChain:
    def test_the_order_composes(self) -> None:
        t = treatment_for("v1", VariationConfig(enabled=True, allow_mirror=True))
        chain = t.video_filters(1080, 1920, 30)
        # scale must precede rotate, rotate must precede crop, crop before flip.
        order = [chain.find(f) for f in ("scale=", "crop=")]
        assert order[0] < order[1]
        if "rotate=" in chain:
            assert chain.find("scale=") < chain.find("rotate=") < chain.find("crop=")
        if "hflip" in chain:
            assert chain.find("crop=") < chain.find("hflip")

    def test_it_still_ends_the_way_concat_requires(self) -> None:
        """Every part must agree on SAR, rate and pixel format or the concat
        demuxer cannot stream-copy them together."""
        chain = treatment_for("v1", ON).video_filters(1080, 1920, 30)
        assert chain.endswith("setsar=1,fps=30,format=yuv420p")

    def test_the_crop_returns_to_the_exact_frame(self) -> None:
        """Odd resolutions get downgraded in delivery, so this one never jitters."""
        for i in range(20):
            chain = treatment_for(f"v{i}", ON).video_filters(1080, 1920, 30)
            assert "crop=1080:1920" in chain

    def test_audio_is_retimed_whenever_the_picture_is(self) -> None:
        """Video at 0.97 against audio at 1.0 drifts a second every thirty."""
        for i in range(30):
            t = treatment_for(f"v{i}", ON)
            if t.speed != 1.0:
                assert f"atempo={t.speed:.5f}" == t.audio_filters()
                assert f"setpts=PTS/{t.speed:.5f}" in t.video_filters(1080, 1920, 30)

    def test_grain_is_applied_after_the_grade(self) -> None:
        """Graded grain stops looking like grain."""
        t = Treatment(**{**NEUTRAL.__dict__, "grain": 6.0, "saturation": 1.05})
        chain = t.video_filters(1080, 1920, 30)
        assert chain.find("eq=") < chain.find("noise=")


class TestTraceability:
    def test_the_recipe_is_recorded_flat(self) -> None:
        record = treatment_for("item-7", ON).as_dict()
        assert set(record) == {
            "zoom", "anchor_x", "anchor_y", "rotate_deg", "brightness",
            "saturation", "hue_deg", "grain", "speed", "mirror",
        }
        assert all(isinstance(v, (int, float, bool)) for v in record.values())
