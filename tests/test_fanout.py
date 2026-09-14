"""Phase 2 — one render, many channels, each tracked on its own.

Pure: no network, no ffmpeg, no clock.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest

from src.logging import StructuredLogger
from src.models import AccountPost, Queue, QueueItem, QueueStatus
from src.platforms import Service
from src.queue import (
    IllegalTransition,
    claimable_for,
    ensure_posts,
    mark_post_failed,
    mark_post_pushed,
    post_for,
    recompute_status,
    reset_post_for_retry,
    stranded_for,
    sync_status,
    transition_post,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

ACCOUNTS = [
    ("nick_ig", Service.INSTAGRAM),
    ("nick_tt", Service.TIKTOK),
    ("other_ig", Service.INSTAGRAM),
]


def log() -> StructuredLogger:
    return StructuredLogger({}, io.StringIO())


def item(item_id: str = "a", **kw) -> QueueItem:
    return QueueItem(
        id=item_id, scheduled_for=NOW, video_url="https://x/v.mp4",
        caption="c", parts={}, **kw,
    )


def push(i: QueueItem, account: str, post_id: str = "p1") -> AccountPost:
    """Claim then push, the way top-up does — PENDING goes to PUSHED only
    through CLAIMED, which is what makes a crash mid-push detectable."""
    post = post_for(i, account)
    transition_post(post, QueueStatus.CLAIMED, i.id, log=log())
    return mark_post_pushed(post, post_id, i.id, log=log())


class TestExpansion:
    def test_it_adds_one_record_per_account(self) -> None:
        i = item()
        added = ensure_posts(i, ACCOUNTS)
        assert len(added) == 3
        assert [p.account for p in i.posts] == ["nick_ig", "nick_tt", "other_ig"]
        assert all(p.status is QueueStatus.PENDING for p in i.posts)

    def test_it_is_idempotent(self) -> None:
        """Top-up expands on every run; twice must not mean two posts."""
        i = item()
        ensure_posts(i, ACCOUNTS)
        added = ensure_posts(i, ACCOUNTS)
        assert added == []
        assert len(i.posts) == 3

    def test_a_new_account_reaches_videos_already_queued(self) -> None:
        i = item()
        ensure_posts(i, ACCOUNTS[:2])
        added = ensure_posts(i, ACCOUNTS)
        assert [p.account for p in added] == ["other_ig"]

    def test_a_removed_account_keeps_its_record(self) -> None:
        """Deleting history out from under the metrics is never the right
        answer to an account being disconnected."""
        i = item()
        ensure_posts(i, ACCOUNTS)
        push(i, "other_ig", "p9")
        ensure_posts(i, ACCOUNTS[:2])
        assert post_for(i, "other_ig").buffer_post_id == "p9"


class TestPerAccountProgress:
    def _expanded(self) -> QueueItem:
        i = item()
        ensure_posts(i, ACCOUNTS)
        return i

    def test_claimable_is_per_account(self) -> None:
        i = self._expanded()
        push(i, "nick_ig")
        q = Queue(generated_at=NOW, items=[i])

        assert claimable_for(q, "nick_ig") == []
        assert [x.id for x in claimable_for(q, "nick_tt")] == ["a"]

    def test_one_account_failing_leaves_the_others_alone(self) -> None:
        i = self._expanded()
        mark_post_failed(post_for(i, "nick_tt"), "channel disconnected", i.id,
                         log=log())
        q = Queue(generated_at=NOW, items=[i])

        assert [x.id for x in claimable_for(q, "nick_ig")] == ["a"]
        assert [x.id for x in claimable_for(q, "other_ig")] == ["a"]
        assert post_for(i, "nick_ig").last_error is None

    def test_stranded_is_per_account(self) -> None:
        i = self._expanded()
        transition_post(post_for(i, "nick_tt"), QueueStatus.CLAIMED, i.id, log=log())
        q = Queue(generated_at=NOW, items=[i])

        assert [x.id for x in stranded_for(q, "nick_tt")] == ["a"]
        assert stranded_for(q, "nick_ig") == []

    def test_a_claimed_record_is_not_pushable(self) -> None:
        """SPEC §11, per channel: a crash mid-fan-out must be reconciled,
        never re-pushed blindly."""
        i = self._expanded()
        transition_post(post_for(i, "nick_ig"), QueueStatus.CLAIMED, i.id, log=log())
        q = Queue(generated_at=NOW, items=[i])
        assert claimable_for(q, "nick_ig") == []

    def test_attempts_are_counted_per_account(self) -> None:
        i = self._expanded()
        p = post_for(i, "nick_tt")
        mark_post_failed(p, "boom", i.id, log=log())
        reset_post_for_retry(p, i.id, log=log())
        mark_post_failed(p, "boom", i.id, log=log())
        assert p.attempts == 2
        assert post_for(i, "nick_ig").attempts == 0

    def test_retrying_a_record_with_no_attempts_left_is_refused(self) -> None:
        i = self._expanded()
        p = post_for(i, "nick_tt")
        for _ in range(QueueItem.MAX_ATTEMPTS):
            mark_post_failed(p, "boom", i.id, log=log())
            if p.status is QueueStatus.FAILED and p.attempts < QueueItem.MAX_ATTEMPTS:
                reset_post_for_retry(p, i.id, log=log())
        with pytest.raises(IllegalTransition):
            reset_post_for_retry(p, i.id, log=log())

    def test_an_illegal_record_transition_raises(self) -> None:
        i = self._expanded()
        p = push(i, "nick_ig")
        with pytest.raises(IllegalTransition):
            transition_post(p, QueueStatus.CLAIMED, i.id, log=log())


class TestRollup:
    """The item's own status is what every existing reader asks — the queue
    panel, carry_forward, the digest — so it has to keep meaning something."""

    def _expanded(self) -> QueueItem:
        i = item()
        ensure_posts(i, ACCOUNTS)
        return i

    def test_an_unexpanded_item_keeps_its_own_status(self) -> None:
        i = item(status=QueueStatus.PUSHED)
        assert recompute_status(i) is QueueStatus.PUSHED

    def test_it_is_pending_while_any_account_is(self) -> None:
        i = self._expanded()
        push(i, "nick_ig")
        assert recompute_status(i) is QueueStatus.PENDING

    def test_it_is_claimed_while_any_account_is_mid_push(self) -> None:
        i = self._expanded()
        transition_post(post_for(i, "nick_ig"), QueueStatus.CLAIMED, i.id, log=log())
        assert recompute_status(i) is QueueStatus.CLAIMED

    def test_it_is_pushed_only_when_every_account_is(self) -> None:
        i = self._expanded()
        for name, _ in ACCOUNTS:
            push(i, name, "p")
        assert sync_status(i).status is QueueStatus.PUSHED

    def test_it_is_failed_when_nothing_is_left_to_try(self) -> None:
        i = self._expanded()
        push(i, "nick_ig")
        for name in ("nick_tt", "other_ig"):
            p = post_for(i, name)
            for _ in range(QueueItem.MAX_ATTEMPTS):
                if p.status is QueueStatus.FAILED:
                    p.status = QueueStatus.PENDING
                mark_post_failed(p, "boom", i.id, log=log())
        assert recompute_status(i) is QueueStatus.FAILED

    def test_a_partly_published_item_is_not_reported_as_published(self) -> None:
        """The dangerous rounding error: calling it done while two channels
        never received it would drop those two silently."""
        i = self._expanded()
        push(i, "nick_ig")
        mark_post_failed(post_for(i, "nick_tt"), "boom", i.id, log=log())
        assert recompute_status(i) is QueueStatus.PENDING


class TestBackwardCompatibility:
    def test_a_queue_written_before_fanout_still_loads(self) -> None:
        i = item()
        assert i.posts == []
        assert i.status is QueueStatus.PENDING

    def test_an_account_post_round_trips_through_json(self) -> None:
        i = item()
        ensure_posts(i, ACCOUNTS)
        push(i, "nick_ig")
        q = Queue(generated_at=NOW, items=[i])

        again = Queue.model_validate_json(q.model_dump_json())
        post = again.items[0].posts[0]
        assert post.account == "nick_ig"
        assert post.network is Service.INSTAGRAM
        assert post.buffer_post_id == "p1"


class TestPerNetworkBanks:
    """Fan-out sends one video to networks whose copy is genuinely
    different — not one caption rephrased, a different caption."""

    def _campaign(self, tmp_path, **banks: str):
        from pathlib import Path

        d = tmp_path / "camp"
        (d / "captions").mkdir(parents=True)
        (d / "captions.txt").write_text("shared one\n\nshared two\n", encoding="utf-8")
        for network, text in banks.items():
            (d / "captions" / f"{network}.txt").write_text(text, encoding="utf-8")
        return Path(d)

    def test_a_network_without_its_own_bank_falls_back(self, tmp_path) -> None:
        from src.config import TitleStrategy
        from src.descriptions import load_network_banks

        d = self._campaign(tmp_path)
        banks = load_network_banks(
            d, [Service.INSTAGRAM, Service.TIKTOK],
            {s: TitleStrategy.DERIVE for s in Service},
        )
        assert [x.body for x in banks[Service.TIKTOK]] == ["shared one", "shared two"]

    def test_a_network_with_its_own_bank_uses_it(self, tmp_path) -> None:
        from src.config import TitleStrategy
        from src.descriptions import load_network_banks

        d = self._campaign(tmp_path, tiktok="tik one\n\ntik two\n")
        banks = load_network_banks(
            d, [Service.INSTAGRAM, Service.TIKTOK],
            {s: TitleStrategy.DERIVE for s in Service},
        )
        assert [x.body for x in banks[Service.TIKTOK]] == ["tik one", "tik two"]
        assert [x.body for x in banks[Service.INSTAGRAM]] == ["shared one", "shared two"]

    def test_a_missing_bank_entirely_is_reported(self, tmp_path) -> None:
        from src.config import TitleStrategy
        from src.descriptions import load_network_banks
        from src.errors import ConfigError

        empty = tmp_path / "bare"
        empty.mkdir()
        with pytest.raises(ConfigError, match="no description bank"):
            load_network_banks(
                empty, [Service.TIKTOK], {Service.TIKTOK: TitleStrategy.DERIVE}
            )


class TestPickByRecency:
    def test_it_favours_what_has_gone_longest_unused(self) -> None:
        from src.ports import SeededRng
        from src.selector import pick_by_recency

        from collections import Counter
        pool = ["fresh", "stale"]
        last = {"stale": NOW, "fresh": NOW.replace(year=2020)}
        picks = Counter(
            pick_by_recency(pool, last, NOW, SeededRng(i)) for i in range(60)
        )
        assert picks["fresh"] > picks["stale"]

    def test_a_cooled_down_option_is_held_back(self) -> None:
        from datetime import timedelta

        from src.ports import SeededRng
        from src.selector import pick_by_recency

        pool = ["used_today", "free"]
        last = {"used_today": NOW - timedelta(hours=1)}
        for seed in range(20):
            assert pick_by_recency(
                pool, last, NOW, SeededRng(seed), cooldown_days=2
            ) == "free"

    def test_the_cooldown_gives_way_rather_than_blocking_a_post(self) -> None:
        """A caption repeating sooner than intended beats a video that
        cannot post at all."""
        from datetime import timedelta

        from src.ports import SeededRng
        from src.selector import pick_by_recency

        pool = ["only"]
        last = {"only": NOW - timedelta(hours=1)}
        assert pick_by_recency(
            pool, last, NOW, SeededRng(1), cooldown_days=14
        ) == "only"

    def test_an_empty_bank_is_reported(self) -> None:
        from src.errors import SelectionError
        from src.ports import SeededRng
        from src.selector import pick_by_recency

        with pytest.raises(SelectionError):
            pick_by_recency([], {}, NOW, SeededRng(1))
