"""Style-aware captions: a campaign's captions/<style>.txt wins for clips of that style (recipes.json).

physics_sims posts bouncing balls, wind tunnels and a reflex game from one bank: on 2026-11-26 "count the
bounces" went out under a wind-tunnel video and the wind-tunnel line under a pendulum.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src import cli
from src.config import CampaignConfig
from src.descriptions import load_bank
from src.models import DEFAULT_CREATIVE
from src.platforms import Service
from src.queue import load_queue

from tests.conftest import needs_ffmpeg
from tests.test_end_to_end import campaign, render_args  # noqa: F401  (fixtures)

REPO = Path(__file__).resolve().parent.parent
BAIT = re.compile(r"\b(comment|tag a|tag your|like this|follow|share this|watch (till|to) the end)\b", re.I)


def _config(tmp_path: Path) -> CampaignConfig:
    return CampaignConfig.model_validate({
        "slug": "styled", "timezone": "America/New_York",
        "creatives": [{"name": "talk", "title": "Talk"}],
        "buffer": {"api_key_secret": "BUFFER_API_KEY", "channel_id": "x"},
        "notify": {"webhook_secret": "DISCORD_WEBHOOK"},
    })


def test_the_style_bank_is_tried_first_then_the_song_then_the_campaign(tmp_path: Path) -> None:
    config = _config(tmp_path)
    creative = config.creatives[0]
    campaign_dir = tmp_path / "styled"
    (campaign_dir / "captions").mkdir(parents=True)
    (campaign_dir / "captions.txt").write_text("campaign", encoding="utf-8")
    assert cli._creative_bank_path(config, creative, campaign_dir, style="fluid") == campaign_dir / "captions.txt"
    (campaign_dir / "captions" / "fluid.txt").write_text("fluid", encoding="utf-8")
    assert cli._creative_bank_path(config, creative, campaign_dir, style="fluid") == campaign_dir / "captions" / "fluid.txt"
    assert cli._creative_bank_path(config, creative, campaign_dir, style="physics") == campaign_dir / "captions.txt"
    assert cli._creative_bank_path(config, creative, campaign_dir) == campaign_dir / "captions.txt"
    own = config.creative_dir(campaign_dir, creative) / "captions.txt"
    own.parent.mkdir(parents=True)
    own.write_text("song", encoding="utf-8")
    assert cli._creative_bank_path(config, creative, campaign_dir) == own
    assert cli._creative_bank_path(config, creative, campaign_dir, style="fluid") == campaign_dir / "captions" / "fluid.txt"


def test_physics_sims_banks_are_honest_and_apart() -> None:
    physics = REPO / "campaigns" / "physics_sims"
    paths = {
        "ball": physics / "captions.txt",
        "fluid": physics / "captions" / "fluid.txt",
        "stopit": physics / "captions" / "stopit.txt",
    }
    banks = {
        name: load_bank(path.read_text(encoding="utf-8"), Service.INSTAGRAM, source=str(path))
        for name, path in paths.items()
    }
    assert len(banks["fluid"]) == 12 and len(banks["stopit"]) == 12
    for name, bank in banks.items():
        for d in bank:
            assert "{name} – @close__quarters" in d.body, (name, d.body)
            assert not BAIT.search(d.body), (name, d.body)
            assert len(re.findall(r"(?<![\w#])#\w+", d.body)) <= 5, (name, d.body)
    openers = {name: {d.body.split("\n")[0] for d in bank} for name, bank in banks.items()}
    assert "air flowing past a paper plane, gusting on every kick" in openers["fluid"]
    # The wind-tunnel lines left the ball bank, and so did the claim the ball sim cannot make.
    assert not any("air" in line or "wind" in line or "physics are real" in line for line in openers["ball"])
    assert not (openers["ball"] & openers["fluid"]) and not (openers["ball"] & openers["stopit"])


@needs_ffmpeg
def test_render_captions_a_clip_from_its_styles_bank(campaign: Path, tmp_path: Path) -> None:  # noqa: F811
    """The e2e campaign with two of its three clips marked as `fluid` in recipes.json."""
    (campaign / "recipes.json").write_text(json.dumps({"nightly": [
        {"creative": DEFAULT_CREATIVE, "clip": "hook_00.mp4", "style": "fluid"},
        {"creative": DEFAULT_CREATIVE, "clip": "hook_01.mp4", "style": "fluid"},
        {"creative": DEFAULT_CREATIVE, "clip": "hook_02.mp4", "style": "physics"},
    ]}), encoding="utf-8")
    (campaign / "captions").mkdir()
    (campaign / "captions" / "fluid.txt").write_text(
        "\n\n---\n\n".join(f"fluid line {i}" for i in range(4)), encoding="utf-8"
    )
    assert cli.cmd_render(render_args(), {}) == 0
    items = load_queue(campaign / "queue.json").items
    assert len(items) == 3
    by_hook = {i.parts["hook"]: i.caption for i in items}
    assert by_hook["hook_00.mp4"].startswith("fluid line") and by_hook["hook_01.mp4"].startswith("fluid line")
    assert by_hook["hook_00.mp4"] != by_hook["hook_01.mp4"]
    assert by_hook["hook_02.mp4"].startswith("caption number")
