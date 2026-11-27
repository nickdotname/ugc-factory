"""Renderer changes from the 2026-11-26 review (docs/brain/reviews/2026-11-26/worlds.md, science.md): rocket's
situation line and early goal, nyc's meme lines written for a clip, fluid's frame-0 question, reveal's first stage."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "studio")); sys.path.insert(0, str(REPO / "studio" / "mathviz"))
pytest.importorskip("cv2")
ASK = re.compile(r"\?|\b(comment|tag|like|follow|share|save|watch|wait for)\b", re.I)


class TestRocket:
    R = pytest.importorskip("rocket_video")
    clips = json.loads((REPO / "studio" / "rocket" / "index.json").read_text())["clips"]

    def test_every_clip_has_its_moment_inside_it(self):
        for c in self.clips:
            assert c.get("at") is not None and 0 < c["at"] < c["dur"], c["asset"]

    def test_situation_lines_are_statements(self):
        lines = [self.R.situation(c) for c in self.clips]
        assert sum(1 for l in lines if l) >= 15
        for l in lines:
            assert not ASK.search(l), l

    def test_the_line_says_clock_then_score(self):
        assert self.R.situation({"clock": "0:03", "score": "2-2"}) == "0:03 left. 2-2."
        assert self.R.situation({"clock": "0:03"}) == ""
        assert self.R.situation({"line": "replay.", "clock": "1:00", "score": "1-1"}) == "replay."

    def test_tracks_stay_on_the_picture(self):
        for c in self.clips:
            if c["w"] > c["h"]:
                assert c.get("track") and all(0.2 <= x <= 0.8 for x in c["track"]), c["asset"]


class TestNycMemes:
    N = pytest.importorskip("nyc_video")
    places = json.loads((REPO / "studio" / "nyc" / "places.json").read_text())["clips"]

    def test_every_line_names_the_shot_it_needs(self):
        assert len(self.N.MEMES) >= 30
        for line, need in self.N.MEMES:
            assert line and need, line
            assert not re.search(r"\b(comment|tag a|tag your|follow|share|save this|link in bio)\b", line, re.I), line

    def test_most_lines_have_a_clip_that_pays_them_off(self):
        tags = {t for p in self.places.values() if not p.get("skip") for t in p.get("tags", ())}
        ready = [l for l, need in self.N.MEMES if need in tags]
        assert len(ready) >= 25, len(ready)

    def test_skipped_clips_carry_no_tags(self):
        for a, p in self.places.items():
            assert not (p.get("skip") and p.get("tags")), a
