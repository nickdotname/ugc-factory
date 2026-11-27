"""studio/text_video.py's two-beat cards, kinds and captions, and the caption hook in src/cli.py that puts a card's
own line first (docs/brain/reviews/2026-11-26/notes.md §9 items 2, 4, 11)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from src import cli
from src.descriptions import load_bank
from src.models import DEFAULT_CREATIVE
from src.platforms import Service
from src.queue import load_queue

from tests.conftest import needs_ffmpeg
from tests.test_end_to_end import campaign, render_args  # noqa: F401  (fixtures)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "studio")); sys.path.insert(0, str(REPO / "studio" / "mathviz"))
T = pytest.importorskip("text_video")
BAIT = re.compile(r"\b(comment|tag a|tag your|like this|follow|share this|link in bio|stream)\b", re.I)
PAGES = ("notes_app", "notes_her", "notes_him", "notes_date", "notes_college")


class TestBeats:
    def test_a_blank_line_is_the_pause_and_keeps_its_gap(self):
        assert T.beats("i'm in my healing era\n\n(i muted their story)") == ("i'm in my healing era", "(i muted their story)", True)

    def test_a_several_line_block_splits_after_its_first_line(self):
        assert T.beats("how to get over someone:\n- delete the pictures\n- block the number") == (
            "how to get over someone:", "- delete the pictures\n- block the number", False)

    def test_a_slash_marks_the_payoff(self):
        assert T.beats("he said he'd change and he did. / his number") == ("he said he'd change and he did.", "his number", False)

    def test_a_long_one_liner_splits_before_its_last_clause(self):
        head, tail, gap = T.beats("i'm not ghosting you i read it, replied in my head, and moved on with my life")
        assert (head, tail, gap) == ("i'm not ghosting you i read it, replied in my head,", "and moved on with my life", False)
        assert T.beats("the group chat has been silent for 3 days. somebody did something")[1] == "somebody did something"

    def test_no_punctuation_turns_on_the_last_conjunction(self):
        head, tail, _ = T.beats("my roommate put a sock on the door and i've been in the library for 6 hours")
        assert head == "my roommate put a sock on the door" and tail == "and i've been in the library for 6 hours"

    def test_a_short_or_unsplittable_line_is_one_beat(self):
        assert T.beats("no further questions") == ("no further questions", None, False)
        assert T.beats("my toxic trait is thinking a 20 minute nap will fix a 4 year problem")[1] is None
        # the payoff is never one word and the setup never two
        assert T.beats("one two three four five six seven, eight")[1] is None

    def test_every_bank_line_keeps_a_readable_setup(self):
        for page, (name, pre) in {"notes_app": ("lines.txt", "n"), "notes_her": ("her.txt", "h"), "notes_him": ("him.txt", "m"),
                                  "notes_date": ("date.txt", "d"), "notes_college": ("college.txt", "c")}.items():
            T.BANK = str(REPO / "studio" / "notes" / name); T.PREFIX = pre
            lines = T.bank()
            split = 0
            for _, text in lines:
                head, tail, _ = T.beats(text)
                assert head.strip() and (tail is None or tail.strip()), (page, text)
                if tail is not None:
                    split += 1
                    # a derived split (no pause written in) never leaves one word on either side
                    assert "\n" in text.strip("\n") or (len(head.split()) >= 3 and len(tail.split()) >= 2), (page, text)
            assert split >= len(lines) // 2, (page, split, len(lines))   # most cards have two beats to learn from
        T.BANK = str(REPO / "studio" / "notes" / "lines.txt"); T.PREFIX = "n"


class TestKindAndCaption:
    def test_kinds_are_read_off_the_line(self):
        assert T.kind_of("if i send you a song at 2am that is the most serious thing i will ever do") == "song"
        assert T.kind_of("how to get over someone:\n- delete the pictures\n- block the number\n- hear one song") == "list"
        assert T.kind_of("i'm in my healing era\n\n(i muted their story)") == "two-beat"
        assert T.kind_of("he said \"you're different\" and now i'm too busy being different to text back") == "friend"
        assert T.kind_of("my toxic trait is thinking a 20 minute nap will fix a 4 year problem") == "self"
        assert set(T.KINDS) == {"song", "friend", "self", "list", "two-beat"}

    def test_the_caption_is_the_card_or_its_first_beat(self):
        assert T.caption_of("i'm in my healing era\n\n(i muted their story)") == "i'm in my healing era"
        assert T.caption_of("how to get over someone:\n- delete the pictures") == "how to get over someone:"
        assert T.caption_of("he said he'd change and he did. / his number") == "he said he'd change and he did."
        # a clause split keeps the whole line: half a sentence is no caption
        text = "i'm not ghosting you i read it, replied in my head, and moved on with my life"
        assert T.caption_of(text) == text
        assert T.caption_of("no further questions") == "no further questions"

    def test_looks_are_not_shared_between_pages(self):
        import importlib
        pages = {}
        for mod in ("text_her_video", "text_him_video", "text_date_video", "text_college_video"):
            importlib.import_module(mod); pages[mod] = set(T.LOOK_W)
        pages["text_video"] = {"dusk", "orchid", "notes"}          # the wrappers overwrite the module's own
        looks = list(pages.values())
        for a in range(len(looks)):
            for b in range(a + 1, len(looks)):
                assert not (looks[a] & looks[b]), (looks[a], looks[b])
        assert set().union(*looks) <= set(T.LOOKS)
        assert "asphalt" in pages["text_him_video"] and pages["text_college_video"] == {"paper"}
        importlib.reload(T)


class TestCaptionHook:
    def test_the_card_opens_the_caption_once_and_only_when_it_fits(self):
        body = "🎧 Talk – @close__quarters\n#notesapp #relatable"
        assert cli.card_caption("i'm in my healing era", body, Service.INSTAGRAM) == "i'm in my healing era\n" + body
        assert cli.card_caption("", body, Service.INSTAGRAM) == body
        assert cli.card_caption("Talk", body, Service.INSTAGRAM) == body
        assert cli.card_caption("x" * 2300, body, Service.INSTAGRAM) == body

    def test_cards_come_from_the_recipes_plan(self, tmp_path: Path, monkeypatch) -> None:
        from src.config import CampaignConfig
        config = CampaignConfig.model_validate({
            "slug": "cards", "timezone": "America/New_York",
            "buffer": {"api_key_secret": "BUFFER_API_KEY", "channel_id": "x"},
            "notify": {"webhook_secret": "DISCORD_WEBHOOK"},
        })
        monkeypatch.setattr(cli, "CAMPAIGNS_DIR", tmp_path)
        assert cli._clip_cards(config) == {}
        (tmp_path / "cards").mkdir()
        (tmp_path / "cards" / "recipes.json").write_text(json.dumps({"nightly": [
            {"creative": "talk", "clip": "hook_00.mp4", "style": "notes", "plan": {"caption": "be so serious", "kind": "self"}},
            {"creative": "talk", "clip": "hook_01.mp4", "style": "notes", "plan": None},
            {"creative": "talk", "clip": "hook_02.mp4", "style": "notes"},
        ]}), encoding="utf-8")
        assert cli._clip_cards(config) == {"talk": {"hook_00.mp4": "be so serious"}}
        assert cli._clip_styles(config)["talk"]["hook_02.mp4"] == "notes"

    @needs_ffmpeg
    def test_render_opens_a_text_cards_caption_on_its_line(self, campaign: Path, tmp_path: Path) -> None:  # noqa: F811
        (campaign / "recipes.json").write_text(json.dumps({"nightly": [
            {"creative": DEFAULT_CREATIVE, "clip": "hook_00.mp4", "style": "notes", "plan": {"caption": "i'm in my healing era"}},
            {"creative": DEFAULT_CREATIVE, "clip": "hook_01.mp4", "style": "notes", "plan": {"caption": "no further questions"}},
        ]}), encoding="utf-8")
        assert cli.cmd_render(render_args(), {}) == 0
        by_hook = {i.parts["hook"]: i.caption for i in load_queue(campaign / "queue.json").items}
        assert by_hook["hook_00.mp4"].startswith("i'm in my healing era\ncaption number")
        assert by_hook["hook_01.mp4"].startswith("no further questions\ncaption number")
        assert by_hook["hook_02.mp4"].startswith("caption number")


def test_the_notes_pages_captions_are_a_credit_and_real_hashtags() -> None:
    for page in PAGES:
        path = REPO / "campaigns" / page / "captions.txt"
        bank = load_bank(path.read_text(encoding="utf-8"), Service.INSTAGRAM, source=str(path))
        assert len(bank) >= 5, page
        for d in bank:
            assert "\n" not in d.body and d.body.startswith("🎧 {name} – @close__quarters #"), (page, d.body)
            tags = re.findall(r"(?<![\w#])#\w+", d.body)
            assert 3 <= len(tags) <= 4 and "#createmode" not in tags, (page, d.body)
            assert not BAIT.search(d.body), (page, d.body)
        text = (REPO / "campaigns" / page / "config.yaml").read_text(encoding="utf-8")
        assert "\n  cta: []\n" in text, page
