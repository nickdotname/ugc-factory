"""A narrated clip (recipes.json knobs.voice == 'on', studio/voice.py on @what.if.town) goes out with the AI-voice
label on its caption; silent clips do not."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from src import cli
from src.models import DEFAULT_CREATIVE
from src.queue import load_queue

from tests.conftest import needs_ffmpeg
from tests.test_end_to_end import campaign, render_args  # noqa: F401  (fixtures)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'studio'))
import voice as V


def test_the_label_is_the_studios_disclosure_line() -> None:
    assert cli.AI_VOICE_LABEL == V.disclosure()


def test_disclosed_appends_once() -> None:
    assert cli._disclosed("a story\n#tag") == "a story\n#tag\n\nvoice: ai narration"
    assert cli._disclosed("a story  \n") == "a story\n\nvoice: ai narration"
    once = cli._disclosed("a story")
    assert cli._disclosed(once) == once and cli._disclosed("VOICE: AI NARRATION here") == "VOICE: AI NARRATION here"
    assert cli._disclosed(None) is None


def test_voiced_clips_reads_the_recipes(tmp_path: Path, monkeypatch) -> None:
    config = cli.CampaignConfig.model_validate({
        "slug": "voiced", "timezone": "America/New_York",
        "creatives": [{"name": "talk", "title": "Talk"}],
        "buffer": {"api_key_secret": "BUFFER_API_KEY", "channel_id": "x"},
        "notify": {"webhook_secret": "DISCORD_WEBHOOK"},
    })
    monkeypatch.setattr(cli, "_campaign_dir", lambda slug: tmp_path / slug)
    assert cli._voiced_clips(config) == {}
    (tmp_path / "voiced").mkdir()
    (tmp_path / "voiced" / "recipes.json").write_text(json.dumps({"nightly": [
        {"creative": "talk", "clip": "a.mp4", "style": "lowpoly", "knobs": {"voice": "on", "story": "burps"}},
        {"creative": "talk", "clip": "b.mp4", "style": "lowpoly", "knobs": {"voice": "off"}},
        {"creative": "talk", "clip": "c.mp4", "style": "lowpoly"},
        {"creative": "talk", "style": "lowpoly", "knobs": {"voice": "on"}},
    ]}), encoding="utf-8")
    assert cli._voiced_clips(config) == {"talk": {"a.mp4"}}


@needs_ffmpeg
def test_render_labels_the_narrated_clip_only(campaign: Path, tmp_path: Path) -> None:  # noqa: F811
    """The e2e campaign with one of its three clips narrated."""
    (campaign / "recipes.json").write_text(json.dumps({"nightly": [
        {"creative": DEFAULT_CREATIVE, "clip": "hook_00.mp4", "style": "lowpoly", "knobs": {"voice": "on"}},
        {"creative": DEFAULT_CREATIVE, "clip": "hook_01.mp4", "style": "lowpoly", "knobs": {"voice": "off"}},
    ]}), encoding="utf-8")
    assert cli.cmd_render(render_args(), {}) == 0
    items = load_queue(campaign / "queue.json").items
    assert len(items) == 3
    for item in items:
        narrated = item.parts["hook"] == "hook_00.mp4"
        assert item.caption.endswith("\n\n" + cli.AI_VOICE_LABEL) is narrated, item.caption
        assert item.caption.count(cli.AI_VOICE_LABEL) == (1 if narrated else 0)
        for text in item.captions.values():
            assert (cli.AI_VOICE_LABEL in text) is narrated
        for v in item.variants.values() if isinstance(item.variants, dict) else item.variants or ():
            assert (cli.AI_VOICE_LABEL in (v.caption or "")) is narrated
