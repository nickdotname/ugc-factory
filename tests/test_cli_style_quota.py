"""selection.style_quota: a night's slots reserved per studio style, filled from recipes.json's styles.

The review of 2026-11-26 found 27 rendered cutouts that never posted behind a 3x favour_styles boost that the
band style's performance medians cancelled. A quota fills its slots first, unposted clips first, and only then
hands the rest of the night to the ordinary selector.
"""

from __future__ import annotations

import io
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import cli
from src.config import CampaignConfig, SelectionConfig
from src.logging import StructuredLogger
from src.models import History, HistoryEntry, Selection
from src.ports import FrozenClock, SeededRng
from src.selector import AssetLibrary, Selector, tuple_hash

NOW = datetime(2026, 11, 26, 21, 0, tzinfo=timezone.utc)
SONGS = ("talk", "fixation", "prologue")
#: Each song: four clips, two of each style.
STYLE_OF = {"hook_01.mp4": "cutout", "hook_02.mp4": "cutout", "hook_03.mp4": "band", "hook_04.mp4": "band"}


def _config(tmp_path: Path, monkeypatch, **selection) -> CampaignConfig:
    campaigns = tmp_path / "campaigns"
    (campaigns / "quota").mkdir(parents=True)
    monkeypatch.setattr(cli, "CAMPAIGNS_DIR", campaigns)
    (campaigns / "quota" / "recipes.json").write_text(json.dumps({"nightly": [
        {"creative": song, "clip": clip, "style": style, "file": f"{song}_{clip}"}
        for song in SONGS for clip, style in STYLE_OF.items()
    ]}), encoding="utf-8")
    return CampaignConfig.model_validate({
        "slug": "quota",
        "timezone": "America/New_York",
        "creatives": [{"name": s, "title": s.title(), "assets_release": f"assets-quota-{s}"} for s in SONGS],
        "composition": {"bodies_per_video": 0},
        "selection": {"dedupe_on": ["hook"], "repeats": False, "hook_cooldown_days": 4,
                      "caption_cooldown_days": 0, **selection},
        "buffer": {"api_key_secret": "BUFFER_API_KEY", "channel_id": "x"},
        "notify": {"webhook_secret": "DISCORD_WEBHOOK"},
    })


def _library() -> AssetLibrary:
    return AssetLibrary(
        hooks=tuple(STYLE_OF), bodies=(), music=(),
        captions=tuple(f"caption {i}\nsong – band" for i in range(6)), bodies_required=False,
    )


def _posted(song: str, clip: str, config: CampaignConfig, days_ago: int) -> HistoryEntry:
    sel = Selection(hook=clip, bodies=(), music=None, caption="caption 0\nsong – band")
    return HistoryEntry(
        tuple_hash=tuple_hash(sel, config.selection.dedupe_on),
        timestamp=NOW.replace(day=NOW.day - days_ago), item_id="old",
        hook=clip, bodies=(), music=None, caption=sel.caption, creative=song,
    )


def _selector(config: CampaignConfig, seed: int = 1) -> Selector:
    return Selector(config.selection, FrozenClock(NOW), SeededRng(seed), StructuredLogger({}, io.StringIO()))


def _styles_of(picks, config: CampaignConfig) -> Counter:
    styles = cli._clip_styles(config)
    return Counter(styles[name][o.selection.hook] for name, o in picks)


class TestStyleQuota:
    def test_the_quota_is_filled_before_anything_else_and_unposted_clips_first(self, tmp_path, monkeypatch) -> None:
        config = _config(tmp_path, monkeypatch, style_quota={"cutout": 2, "band": 1})
        # talk's cutouts both posted a week ago (outside the cooldown, so the selector would happily repeat
        # them); fixation's and prologue's never did. The quota must take the unposted ones.
        pools = {
            "talk": (_library(), History(entries=[
                _posted("talk", "hook_01.mp4", config, 7), _posted("talk", "hook_02.mp4", config, 7),
            ])),
            "fixation": (_library(), History()),
            "prologue": (_library(), History()),
        }
        log = StructuredLogger({}, io.StringIO())
        for seed in range(12):
            picks, after = cli._quota_picks(
                config, _selector(config, seed), pools, {s: 1.0 for s in SONGS}, 3,
                cli._clip_styles(config), NOW, log,
            )
            assert _styles_of(picks, config) == Counter({"cutout": 2, "band": 1})
            assert all(name != "talk" for name, o in picks if STYLE_OF[o.selection.hook] == "cutout")
            # What the quota took is now history for the ordinary selector.
            for name, o in picks:
                assert o.selection.hook in {e.hook for e in after[name][1].entries}
            assert len({(n, o.selection.hook) for n, o in picks}) == 3

    def test_used_clips_fill_a_style_when_the_unposted_run_out(self, tmp_path, monkeypatch) -> None:
        config = _config(tmp_path, monkeypatch, style_quota={"cutout": 3})
        pools = {
            song: (_library(), History(entries=[
                _posted(song, "hook_01.mp4", config, 9), _posted(song, "hook_02.mp4", config, 9),
            ]))
            for song in SONGS
        }
        # One unposted cutout in the whole account; the other two slots come from cutouts posted nine days ago.
        pools["prologue"] = (_library(), History(entries=[_posted("prologue", "hook_01.mp4", config, 9)]))
        picks, _ = cli._quota_picks(
            config, _selector(config), pools, {s: 1.0 for s in SONGS}, 3, cli._clip_styles(config), NOW,
            StructuredLogger({}, io.StringIO()),
        )
        assert _styles_of(picks, config) == Counter({"cutout": 3})
        assert ("prologue", "hook_02.mp4") in {(n, o.selection.hook) for n, o in picks}

    def test_a_style_nobody_has_leaves_its_slots_to_the_selector(self, tmp_path, monkeypatch) -> None:
        config = _config(tmp_path, monkeypatch, style_quota={"lofi": 2, "band": 1})
        out = io.StringIO()
        picks, after = cli._quota_picks(
            config, _selector(config), {s: (_library(), History()) for s in SONGS}, {s: 1.0 for s in SONGS},
            3, cli._clip_styles(config), NOW, StructuredLogger({}, out),
        )
        assert _styles_of(picks, config) == Counter({"band": 1})
        assert "style_quota_short" in out.getvalue()
        # The ordinary selector fills the rest against the updated pools and never repeats the quota's pick.
        rest = _selector(config).select_batch_multi(after, {s: 1.0 for s in SONGS}, 2, 0)
        hooks = {(n, o.selection.hook) for n, o in picks} | {(n, o.selection.hook) for n, o in rest}
        assert len(hooks) == 3

    def test_the_quota_never_exceeds_the_count(self, tmp_path, monkeypatch) -> None:
        config = _config(tmp_path, monkeypatch, style_quota={"cutout": 2, "band": 2})
        picks, _ = cli._quota_picks(
            config, _selector(config), {s: (_library(), History()) for s in SONGS}, {s: 1.0 for s in SONGS},
            1, cli._clip_styles(config), NOW, StructuredLogger({}, io.StringIO()),
        )
        assert _styles_of(picks, config) == Counter({"cutout": 1})

    def test_favour_styles_still_works_without_a_quota(self, tmp_path, monkeypatch) -> None:
        config = _config(tmp_path, monkeypatch, favour_styles={"cutout": 3})
        assert config.selection.style_quota is None
        boost = cli._style_boost(config)
        assert boost == {s: {"hook_01.mp4": 3.0, "hook_02.mp4": 3.0} for s in SONGS}

    def test_the_config_key_is_selection_style_quota(self) -> None:
        assert SelectionConfig(style_quota={"cutout": 2, "band": 1}).style_quota == {"cutout": 2, "band": 1}
        assert SelectionConfig().style_quota is None
        with pytest.raises(ValueError, match="style_quota"):
            SelectionConfig(style_quota={"cutout": 0})
