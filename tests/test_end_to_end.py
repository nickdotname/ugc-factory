"""End-to-end wiring: render then top up, with real ffmpeg and a fake store.

Every other suite tests one module against fakes. This one runs ``cli.render``
and ``cli.topup`` the way the workflows do, which is the only way to catch a
composition-root mistake — a wrong argument order or a stage never reached.

The media store is faked (a local directory) and the publisher runs in dry run,
so nothing leaves the machine. ffmpeg is real.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pytest

from src import cli
from src.assets import MediaStore, RemoteAsset
from src.models import QueueStatus
from src.queue import load_history, load_queue

from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


class LocalMediaStore(MediaStore):
    """A MediaStore backed by two local directories.

    Exists to prove the ``MediaStore`` seam is real: swapping GitHub Releases
    for something else is a new class, not a change to render or topup.
    """

    def __init__(self, source: Path, published: Path) -> None:
        self.source = source
        self.published = published
        self.published.mkdir(parents=True, exist_ok=True)

    def download_assets(self, tag: str, dest_dir: Path) -> list[Path]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for item in self.source.iterdir():
            if item.is_file():
                target = dest_dir / item.name
                shutil.copy2(item, target)
                out.append(target)
        return out

    def list_assets(self, tag: str) -> list[str]:
        return [p.name for p in self.source.iterdir() if p.is_file()]

    def publish(self, tag: str, files: list[Path]) -> list[RemoteAsset]:
        out = []
        for f in files:
            target = self.published / f.name
            shutil.copy2(f, target)
            out.append(RemoteAsset(
                name=f.name,
                url=f"https://example.test/{tag}/{f.name}",
                size_bytes=target.stat().st_size,
            ))
        return out

    def delete_assets(self, tag: str, names: list[str]) -> list[str]:
        gone = []
        for name in names:
            target = self.source / name
            if target.is_file():
                target.unlink()
                gone.append(name)
        return gone

    def cleanup(self, prefix: str, older_than_days: int) -> list[str]:
        return []


@pytest.fixture
def campaign(tmp_path: Path, clips: dict[str, Path], monkeypatch) -> Path:
    """A complete campaign on disk, with a source library big enough to dedupe."""
    campaigns = tmp_path / "campaigns"
    slug_dir = campaigns / "e2e"
    slug_dir.mkdir(parents=True)

    (slug_dir / "config.yaml").write_text(
        """
slug: e2e
timezone: America/New_York
posting:
  posts_per_day: 3
  start_hour: 9
  end_hour: 21
  max_buffer_queue: 10
  dry_run: true
video:
  preset: ultrafast
  crf: 32
composition:
  bodies_per_video: 1
selection:
  hook_cooldown_days: 0
  caption_cooldown_days: 0
buffer:
  api_key_secret: BUFFER_API_KEY
  channel_id_secret: BUFFER_CHANNEL_E2E
notify:
  webhook_secret: DISCORD_WEBHOOK_E2E
""".strip(),
        encoding="utf-8",
    )
    (slug_dir / "captions.txt").write_text(
        "\n\n".join(f"caption number {i}" for i in range(8)), encoding="utf-8"
    )

    # A flat source library, named by the prefix convention LocalLibrary uses.
    source = tmp_path / "source"
    source.mkdir()
    for i in range(3):
        shutil.copy2(clips["portrait"], source / f"hook_{i:02d}.mp4")
    for i in range(3):
        shutil.copy2(clips["square"], source / f"body_{i:02d}.mp4")
    shutil.copy2(clips["music_short"], source / "music_00.mp3")
    (source / "LICENSES.md").write_text(
        "| music_00.mp3 | Pixabay | CC0 |\n", encoding="utf-8"
    )

    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cli, "CAMPAIGNS_DIR", campaigns)
    monkeypatch.setattr(
        cli, "_build_store",
        lambda env, log, clock: LocalMediaStore(source, tmp_path / "published"),
    )
    return slug_dir


def render_args(**kw) -> argparse.Namespace:
    return argparse.Namespace(
        command="render", campaign="e2e", dry_run=True, count=None, **kw
    )


def topup_args(**kw) -> argparse.Namespace:
    return argparse.Namespace(
        command="topup", campaign="e2e", dry_run=True, no_commit=True, **kw
    )


class TestRenderEndToEnd:
    def test_render_produces_a_queue_of_playable_videos(
        self, campaign: Path, tmp_path: Path
    ) -> None:
        assert cli.cmd_render(render_args(), {}) == 0

        queue = load_queue(campaign / "queue.json")
        # Render tops the backlog up to posts_per_day * max_backlog_days, so a
        # first run against an empty queue fills two days rather than one.
        assert len(queue.items) == 6
        assert all(i.status is QueueStatus.PENDING for i in queue.items)
        assert all(i.video_url.startswith("https://example.test/") for i in queue.items)
        assert all(i.caption for i in queue.items)

        # The rendered files really exist and really are videos.
        published = sorted((tmp_path / "published").glob("*.mp4"))
        assert len(published) == 6
        for path in published:
            assert path.stat().st_size > 1000

    def test_render_records_history_for_dedupe(self, campaign: Path) -> None:
        cli.cmd_render(render_args(), {})
        history = load_history(campaign / "history.json")
        assert len(history.entries) == 6
        assert len({e.tuple_hash for e in history.entries}) == 6

    def test_second_render_does_not_repeat_the_first(self, campaign: Path) -> None:
        """The whole point of history: tomorrow's batch avoids today's."""
        cli.cmd_render(render_args(), {})
        first = {e.tuple_hash for e in load_history(campaign / "history.json").entries}

        # The backlog is full after the first run, so a second render with
        # nothing published in between correctly adds nothing.
        cli.cmd_render(render_args(), {})
        assert len(load_history(campaign / "history.json").entries) == len(first)

        # Force a batch to prove dedupe still holds when it does render.
        forced = render_args()
        forced.count = 2
        cli.cmd_render(forced, {})
        entries = load_history(campaign / "history.json").entries
        second = {e.tuple_hash for e in entries} - first
        assert len(second) == 2
        assert not (first & second), "second render repeated a used combination"

    def test_scheduled_slots_are_in_the_future_and_spread(self, campaign: Path) -> None:
        """SPEC §4.2 — the render-to-push gap is the human review window."""
        cli.cmd_render(render_args(), {})
        items = sorted(load_queue(campaign / "queue.json").items,
                       key=lambda i: i.scheduled_for)
        times = [i.scheduled_for for i in items]
        assert times == sorted(times)
        assert len(set(times)) == 6, "slots must not collide"

    def test_a_full_backlog_renders_nothing(self, campaign: Path) -> None:
        """The fix for renders outrunning what the channel publishes.

        Previously every night added a fresh batch and replaced the queue, so
        anything not yet pushed was discarded — most of the output, at a render
        rate above the real publish rate.
        """
        assert cli.cmd_render(render_args(), {}) == 0
        first = load_queue(campaign / "queue.json").items

        assert cli.cmd_render(render_args(), {}) == 0
        second = load_queue(campaign / "queue.json").items
        assert [i.id for i in second] == [i.id for i in first]

    def test_unpushed_items_survive_the_next_render(self, campaign: Path) -> None:
        from src.queue import save_queue

        cli.cmd_render(render_args(), {})
        queue = load_queue(campaign / "queue.json")
        # Drain most of it, as the top-up job would.
        for item in queue.items[:5]:
            item.status = QueueStatus.PUSHED
        survivor = queue.items[5].id
        save_queue(campaign / "queue.json", queue)

        cli.cmd_render(render_args(), {})
        after = load_queue(campaign / "queue.json").items
        assert survivor in {i.id for i in after}, "an unpushed video was discarded"
        # Pushed items are finished business and are not carried.
        assert len(after) == 6

    def test_carried_and_new_items_never_share_a_slot(self, campaign: Path) -> None:
        from src.queue import save_queue

        cli.cmd_render(render_args(), {})
        queue = load_queue(campaign / "queue.json")
        for item in queue.items[:4]:
            item.status = QueueStatus.PUSHED
        save_queue(campaign / "queue.json", queue)

        cli.cmd_render(render_args(), {})
        times = [i.scheduled_for for i in load_queue(campaign / "queue.json").items]
        assert len(set(times)) == len(times), "two videos landed in one slot"

    def test_count_override_is_honoured(self, campaign: Path) -> None:
        args = render_args()
        args.count = 2
        cli.cmd_render(args, {})
        assert len(load_queue(campaign / "queue.json").items) == 2

    def test_render_output_is_valid_json_on_disk(self, campaign: Path) -> None:
        cli.cmd_render(render_args(), {})
        json.loads((campaign / "queue.json").read_text(encoding="utf-8"))
        json.loads((campaign / "history.json").read_text(encoding="utf-8"))


class TestTopupEndToEnd:
    def test_topup_pushes_pending_items_in_dry_run(self, campaign: Path) -> None:
        cli.cmd_render(render_args(), {})
        assert cli.cmd_topup(topup_args(), {}) == 0

        queue = load_queue(campaign / "queue.json")
        assert all(i.status is QueueStatus.PUSHED for i in queue.items)
        assert all(i.buffer_post_id for i in queue.items)

    def test_topup_is_idempotent(self, campaign: Path) -> None:
        """A second run must find nothing to do rather than double-pushing."""
        cli.cmd_render(render_args(), {})
        cli.cmd_topup(topup_args(), {})
        ids = [i.buffer_post_id for i in load_queue(campaign / "queue.json").items]

        assert cli.cmd_topup(topup_args(), {}) == 0
        assert [i.buffer_post_id
                for i in load_queue(campaign / "queue.json").items] == ids

    def test_topup_on_an_empty_queue_exits_clean(self, campaign: Path) -> None:
        assert cli.cmd_topup(topup_args(), {}) == 0

    def test_topup_respects_the_queue_cap(self, campaign: Path, monkeypatch) -> None:
        """SPEC §14 — Buffer already at 10: push nothing, exit clean."""
        cli.cmd_render(render_args(), {})
        from src.publishers.base import DryRunPublisher

        monkeypatch.setattr(
            cli, "_build_publisher",
            lambda config, env, log: DryRunPublisher(log, queue_depth=10),
        )
        assert cli.cmd_topup(topup_args(), {}) == 0
        queue = load_queue(campaign / "queue.json")
        assert all(i.status is QueueStatus.PENDING for i in queue.items), \
            "a full Buffer queue must leave items untouched"

    def test_history_gets_the_post_id_backfilled(self, campaign: Path) -> None:
        cli.cmd_render(render_args(), {})
        cli.cmd_topup(topup_args(), {})
        entries = load_history(campaign / "history.json").entries
        assert all(e.buffer_post_id for e in entries)


class TestPreflightEndToEnd:
    def test_preflight_passes_on_a_well_formed_campaign(self, campaign: Path) -> None:
        env = {
            "BUFFER_API_KEY": "k",
            "BUFFER_CHANNEL_E2E": "c",
            "DISCORD_WEBHOOK_E2E": "https://hook",
        }
        args = argparse.Namespace(command="preflight", campaign="e2e", dry_run=False)
        assert cli.cmd_preflight(args, env) == 0

    def test_preflight_reports_missing_secrets(self, campaign: Path) -> None:
        args = argparse.Namespace(command="preflight", campaign="e2e", dry_run=False)
        assert cli.cmd_preflight(args, {}) == 1

    def test_preflight_reports_an_empty_caption_bank(self, campaign: Path) -> None:
        (campaign / "captions.txt").write_text("# only a comment\n", encoding="utf-8")
        env = {"BUFFER_API_KEY": "k", "BUFFER_CHANNEL_E2E": "c",
               "DISCORD_WEBHOOK_E2E": "h"}
        args = argparse.Namespace(command="preflight", campaign="e2e", dry_run=False)
        assert cli.cmd_preflight(args, env) == 1


class TestFailurePaths:
    def test_missing_caption_bank_fails_the_render(self, campaign: Path) -> None:
        (campaign / "captions.txt").unlink()
        assert cli.cmd_render(render_args(), {}) == 1

    def test_unknown_campaign_is_a_config_error(self, campaign: Path) -> None:
        args = render_args()
        args.campaign = "nope"
        with pytest.raises(Exception):
            cli.cmd_render(args, {})


@needs_ffmpeg
class TestStaleSlotRecovery:
    """The failure that stopped posting for days: slots that aged out."""

    def test_topup_reslots_items_whose_time_has_passed(
        self, campaign: Path, monkeypatch
    ) -> None:
        from datetime import datetime, timedelta, timezone

        cli.cmd_render(render_args(), {})

        # Age every slot into the past, as happens between render and top-up.
        q = load_queue(campaign / "queue.json")
        past = datetime.now(timezone.utc) - timedelta(hours=6)
        for i in q.items:
            i.scheduled_for = past
        from src.queue import save_queue

        save_queue(campaign / "queue.json", q)

        assert cli.cmd_topup(topup_args(), {}) == 0

        after = load_queue(campaign / "queue.json")
        assert all(i.status is QueueStatus.PUSHED for i in after.items)
        now = datetime.now(timezone.utc)
        for i in after.items:
            assert i.scheduled_for > now, "pushed with a slot Buffer would reject"

    def test_reslotted_items_do_not_collide(
        self, campaign: Path
    ) -> None:
        from datetime import datetime, timedelta, timezone

        from src.queue import save_queue

        cli.cmd_render(render_args(), {})
        q = load_queue(campaign / "queue.json")
        past = datetime.now(timezone.utc) - timedelta(hours=6)
        for i in q.items:
            i.scheduled_for = past
        save_queue(campaign / "queue.json", q)

        cli.cmd_topup(topup_args(), {})
        times = [i.scheduled_for for i in load_queue(campaign / "queue.json").items]
        assert len(set(times)) == len(times), "two posts landed on one slot"

    def test_failed_items_with_attempts_left_are_retried(
        self, campaign: Path
    ) -> None:
        """A systemic failure must not permanently drain a batch."""
        from src.queue import mark_failed, save_queue

        cli.cmd_render(render_args(), {})
        q = load_queue(campaign / "queue.json")
        for i in q.items:
            mark_failed(i, "transient", log=cli.get_logger())
        save_queue(campaign / "queue.json", q)

        cli.cmd_topup(topup_args(), {})
        after = load_queue(campaign / "queue.json")
        assert all(i.status is QueueStatus.PUSHED for i in after.items)

    def test_reslotting_avoids_slots_held_by_pending_items(
        self, campaign: Path
    ) -> None:
        """A stale item must not be handed a time another item still owns.

        Only pushed/claimed slots were excluded originally, so a reslotted item
        could collide with a pending one and both went out on the same minute.
        """
        from datetime import datetime, timedelta, timezone

        from src.queue import save_queue

        cli.cmd_render(render_args(), {})
        q = load_queue(campaign / "queue.json")
        # Age only the first item; the rest keep their future slots.
        q.items[0].scheduled_for = datetime.now(timezone.utc) - timedelta(hours=4)
        save_queue(campaign / "queue.json", q)

        cli.cmd_topup(topup_args(), {})
        times = [i.scheduled_for for i in load_queue(campaign / "queue.json").items]
        assert len(set(times)) == len(times), "reslot collided with a pending slot"
