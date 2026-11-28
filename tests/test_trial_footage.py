"""New band footage can be tried on non-followers first: a clip marked `trial` in studio/lofi/index.json makes every
video built from it a trial reel, while the band account itself posts normal reels (2026-11-28)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src import cli

REPO = Path(__file__).resolve().parents[1]


class _Cfg:
    slug = "band"


def test_trial_clips_come_from_the_recipes_plan(tmp_path, monkeypatch) -> None:
    camp = tmp_path / "band"; camp.mkdir()
    (camp / "recipes.json").write_text(json.dumps({"nightly": [
        {"creative": "wbtsa", "clip": "hook_30.mp4", "style": "cutout", "plan": {"footage": ["plaza_a1"], "trial": True}},
        {"creative": "wbtsa", "clip": "hook_31.mp4", "style": "cutout", "plan": {"footage": ["wbtsa_b1"], "trial": False}},
        {"creative": "wbtsa", "clip": "hook_32.mp4", "style": "band"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(cli, "_campaign_dir", lambda slug: tmp_path / slug)
    assert cli._trial_clips(_Cfg()) == {"wbtsa": {"hook_30.mp4"}}


def _lofi(monkeypatch):
    """studio/lofi_video.py reads its song from argv when imported: give it a real one."""
    sys.path.insert(0, str(REPO / "studio")); sys.path.insert(0, str(REPO / "studio" / "mathviz"))
    monkeypatch.setattr(sys, "argv", ["lofi_video.py", str(REPO / "studio" / "songs" / "wont-be-the-same-again")])
    import lofi_video as LV
    return LV


def test_a_video_says_it_used_trial_footage(monkeypatch) -> None:
    LV = _lofi(monkeypatch)
    monkeypatch.setattr(LV.LIB, "index", lambda: {"clips": [{"id": "plaza_a1", "trial": True}, {"id": "wbtsa_b1"}]})
    LV.USED.clear(); LV.USED.update({"wbtsa_b1"})
    assert LV.footage_record() == {"footage": ["wbtsa_b1"], "trial": False}
    LV.USED.add("plaza_a1")
    assert LV.footage_record() == {"footage": ["plaza_a1", "wbtsa_b1"], "trial": True}


def test_the_newest_clip_of_a_person_wins_where_two_overlap(monkeypatch) -> None:
    LV = _lofi(monkeypatch)
    monkeypatch.setattr(LV, "CLIPS", {"b": [("wbtsa_b1", 80.0, 571, 10), ("plaza_b1", 111.27, 125, 10)]})
    monkeypatch.setattr(LV.LIB, "frame", lambda cid, k: cid)
    LV._cache.clear(); LV.USED.clear()
    assert LV.person("b", 115.0) == "plaza_b1" and LV.person("b", 90.0) == "wbtsa_b1"
