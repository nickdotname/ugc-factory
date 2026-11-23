"""What a studio video is about, read from recipes.json, for subject spacing."""
import json

from src.cli import _subjects
from src.config import SelectionConfig


def test_subjects_join_the_named_knobs(tmp_path):
    (tmp_path / "recipes.json").write_text(json.dumps({"nightly": [
        {"creative": "prologue", "clip": "hook_01.mp4", "knobs": {"topic": "fourier", "theme": "chalk"}},
        {"creative": "prologue", "clip": "hook_02.mp4", "knobs": {"topic": "sci8", "subject": "brain"}},
        {"creative": "talk", "file": "x.mp4", "knobs": {"topic": "zeta"}},          # never ingested: no clip name
    ], "archive": {"nightly": [{"creative": "prologue", "clip": "hook_01.mp4", "knobs": {"topic": "integral"}}]}}))
    got = _subjects(tmp_path, ("topic", "subject"))
    assert got == {("prologue", "hook_01.mp4"): "fourier", ("prologue", "hook_02.mp4"): "sci8/brain"}


def test_no_knobs_or_no_record_means_no_subjects(tmp_path):
    assert _subjects(tmp_path, ("topic",)) == {}
    (tmp_path / "recipes.json").write_text("{}")
    assert _subjects(tmp_path, ()) == {}


def test_spacing_is_off_by_default():
    s = SelectionConfig()
    assert s.subject_knobs == () and s.repeats is True
