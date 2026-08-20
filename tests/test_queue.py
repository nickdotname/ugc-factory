"""M5 — queue state machine and persistence (SPEC §11, §14)."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.errors import ValidationError
from src.logging import StructuredLogger
from src.models import History, HistoryEntry, Queue, QueueItem, QueueStatus
from src.queue import (
    IllegalTransition,
    append_history,
    cancel,
    claimable,
    depth_needed,
    load_history,
    load_queue,
    mark_failed,
    mark_pushed,
    reset_for_retry,
    save_queue,
    spread_schedule,
    stranded,
    upcoming_slots,
    transition,
)

NOW = datetime(2026, 8, 13, 5, 0, tzinfo=timezone.utc)


@pytest.fixture
def log() -> StructuredLogger:
    return StructuredLogger({}, io.StringIO())


def item(
    id_: str = "i1",
    status: QueueStatus = QueueStatus.PENDING,
    when: datetime | None = None,
    attempts: int = 0,
) -> QueueItem:
    return QueueItem(
        id=id_,
        scheduled_for=when or NOW,
        video_url=f"https://github.com/o/r/releases/download/render-x/{id_}.mp4",
        caption="a caption",
        parts={"hook": "hook_01.mp4", "body": "body_01.mp4", "music": "music_01.mp3"},
        status=status,
        attempts=attempts,
    )


class TestTransitions:
    def test_pending_to_claimed_is_legal(self, log: StructuredLogger) -> None:
        assert transition(item(), QueueStatus.CLAIMED, log=log).status is QueueStatus.CLAIMED

    def test_claimed_to_pushed_is_legal(self, log: StructuredLogger) -> None:
        i = item(status=QueueStatus.CLAIMED)
        assert transition(i, QueueStatus.PUSHED, log=log).status is QueueStatus.PUSHED

    def test_pending_to_pushed_is_illegal(self, log: StructuredLogger) -> None:
        """Skipping `claimed` would defeat the whole crash-resume design."""
        with pytest.raises(IllegalTransition, match="pending -> pushed"):
            transition(item(), QueueStatus.PUSHED, log=log)

    def test_pushed_never_re_enters_the_pipeline(self, log: StructuredLogger) -> None:
        """A published item must never be pushed a second time.

        ``cancelled`` is the one exception and is tested separately: it takes
        the item *out*, it does not put it back in.
        """
        for target in (QueueStatus.PENDING, QueueStatus.CLAIMED,
                       QueueStatus.PUSHED, QueueStatus.FAILED):
            with pytest.raises(IllegalTransition):
                transition(item(status=QueueStatus.PUSHED), target, log=log)

    def test_a_pushed_item_can_still_be_withdrawn(self, log: StructuredLogger) -> None:
        # Buffer holds the post until its slot comes up, so there is a real
        # window in which a human can still stop it.
        i = item(status=QueueStatus.PUSHED)
        assert cancel(i, log=log).status is QueueStatus.CANCELLED

    def test_a_pending_item_can_be_withdrawn(self, log: StructuredLogger) -> None:
        assert cancel(item(), log=log).status is QueueStatus.CANCELLED

    def test_a_claimed_item_cannot_be_withdrawn(self, log: StructuredLogger) -> None:
        """It may be mid-push right now — cancelling is a race with a publish."""
        with pytest.raises(IllegalTransition, match="reconciled"):
            cancel(item(status=QueueStatus.CLAIMED), log=log)

    def test_cancelled_is_terminal(self, log: StructuredLogger) -> None:
        for target in QueueStatus:
            with pytest.raises(IllegalTransition):
                transition(item(status=QueueStatus.CANCELLED), target, log=log)

    def test_a_cancelled_item_is_never_claimed_again(self, log: StructuredLogger) -> None:
        q = Queue(generated_at=NOW, items=[
            item(status=QueueStatus.CANCELLED), item(status=QueueStatus.PENDING),
        ])
        assert [i.status for i in claimable(q)] == [QueueStatus.PENDING]

    def test_cancelled_counts_as_finished(self) -> None:
        assert item(status=QueueStatus.CANCELLED).is_terminal

    def test_illegal_transition_is_a_validation_error(self, log: StructuredLogger) -> None:
        """Callers catching ValidationError must catch this too."""
        assert issubclass(IllegalTransition, ValidationError)
        with pytest.raises(ValidationError):
            transition(item(status=QueueStatus.PUSHED), QueueStatus.PENDING, log=log)

    def test_transition_is_logged(self) -> None:
        stream = io.StringIO()
        transition(item(), QueueStatus.CLAIMED, log=StructuredLogger({}, stream))
        assert "queue_transition" in stream.getvalue()


class TestFailureAndRetry:
    def test_mark_failed_increments_attempts_and_records_error(
        self, log: StructuredLogger
    ) -> None:
        i = mark_failed(item(), "buffer said no", log=log)
        assert i.status is QueueStatus.FAILED
        assert i.attempts == 1
        assert i.last_error == "buffer said no"

    def test_long_error_is_truncated(self, log: StructuredLogger) -> None:
        i = mark_failed(item(), "x" * 5000, log=log)
        assert i.last_error is not None and len(i.last_error) == 500

    def test_retry_returns_item_to_pending(self, log: StructuredLogger) -> None:
        i = mark_failed(item(), "transient", log=log)
        assert reset_for_retry(i, log=log).status is QueueStatus.PENDING

    def test_retry_blocked_after_max_attempts(self, log: StructuredLogger) -> None:
        """SPEC §12 — 3 attempts, then stop and alert."""
        i = item()
        for _ in range(QueueItem.MAX_ATTEMPTS):
            mark_failed(i, "nope", log=log)
            if i.attempts < QueueItem.MAX_ATTEMPTS:
                reset_for_retry(i, log=log)
        with pytest.raises(IllegalTransition, match="all 3 attempts"):
            reset_for_retry(i, log=log)

    def test_only_failed_items_retry(self, log: StructuredLogger) -> None:
        with pytest.raises(IllegalTransition, match="only failed items"):
            reset_for_retry(item(), log=log)

    def test_exhausted_item_is_terminal(self, log: StructuredLogger) -> None:
        i = item(attempts=3, status=QueueStatus.FAILED)
        assert i.is_terminal

    def test_failed_with_attempts_left_is_not_terminal(self) -> None:
        assert not item(attempts=1, status=QueueStatus.FAILED).is_terminal

    def test_mark_pushed_records_post_id_and_clears_error(
        self, log: StructuredLogger
    ) -> None:
        i = item(status=QueueStatus.CLAIMED)
        i.last_error = "an earlier failure"
        mark_pushed(i, "buffer-post-123", log=log)
        assert i.status is QueueStatus.PUSHED
        assert i.buffer_post_id == "buffer-post-123"
        assert i.last_error is None


class TestSelectionForPush:
    def test_claimable_returns_only_pending(self) -> None:
        q = Queue(generated_at=NOW, items=[
            item("a", QueueStatus.PENDING),
            item("b", QueueStatus.PUSHED),
            item("c", QueueStatus.CLAIMED),
            item("d", QueueStatus.FAILED),
        ])
        assert [i.id for i in claimable(q)] == ["a"]

    def test_claimable_is_ordered_by_scheduled_time(self) -> None:
        q = Queue(generated_at=NOW, items=[
            item("late", when=NOW + timedelta(hours=5)),
            item("early", when=NOW + timedelta(hours=1)),
            item("mid", when=NOW + timedelta(hours=3)),
        ])
        assert [i.id for i in claimable(q)] == ["early", "mid", "late"]

    def test_stranded_finds_claimed_items(self) -> None:
        """SPEC §14 — a job killed between claimed and pushed leaves evidence."""
        q = Queue(generated_at=NOW, items=[
            item("ok", QueueStatus.PENDING),
            item("stuck", QueueStatus.CLAIMED),
        ])
        assert [i.id for i in stranded(q)] == ["stuck"]


class TestDepthNeeded:
    def test_tops_up_to_the_cap(self) -> None:
        assert depth_needed(3, 10) == 7

    def test_full_queue_needs_nothing(self) -> None:
        """SPEC §14 — Buffer queue already at 10: push nothing, exit clean."""
        assert depth_needed(10, 10) == 0

    def test_over_full_queue_is_clamped_not_negative(self) -> None:
        assert depth_needed(12, 10) == 0

    def test_empty_queue_needs_the_full_cap(self) -> None:
        assert depth_needed(0, 10) == 10


class TestSchedule:
    def test_slots_are_inside_the_window(self) -> None:
        slots = spread_schedule(NOW, 6, 9, 22)
        assert all(9 <= s.hour < 22 for s in slots)

    def test_slots_are_evenly_spaced_and_ordered(self) -> None:
        slots = spread_schedule(NOW, 6, 9, 21)
        gaps = {(b - a) for a, b in zip(slots, slots[1:])}
        assert len(gaps) == 1
        assert slots == sorted(slots)

    def test_single_post_lands_mid_window(self) -> None:
        assert spread_schedule(NOW, 1, 9, 21)[0].hour == 15

    def test_zero_count_returns_no_slots(self) -> None:
        assert spread_schedule(NOW, 0, 9, 22) == []

    def test_max_cadence_still_fits(self) -> None:
        slots = spread_schedule(NOW, 24, 9, 22)
        assert len(slots) == 24 and len(set(slots)) == 24


class TestPersistence:
    def test_missing_queue_file_loads_empty(self, tmp_path: Path) -> None:
        assert load_queue(tmp_path / "queue.json").items == []

    def test_round_trip_preserves_state(self, tmp_path: Path) -> None:
        path = tmp_path / "queue.json"
        original = Queue(generated_at=NOW, items=[
            item("a", QueueStatus.PUSHED),
            item("b", QueueStatus.PENDING),
        ])
        original.items[0].buffer_post_id = "post-1"
        save_queue(path, original)
        loaded = load_queue(path)
        assert [i.id for i in loaded.items] == ["a", "b"]
        assert loaded.items[0].status is QueueStatus.PUSHED
        assert loaded.items[0].buffer_post_id == "post-1"

    def test_corrupt_queue_fails_loud_rather_than_resetting(self, tmp_path: Path) -> None:
        """A corrupt queue may hold items already in Buffer — never overwrite it."""
        path = tmp_path / "queue.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError, match="not a valid queue file"):
            load_queue(path)

    def test_unknown_status_value_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "queue.json"
        path.write_text(
            '{"generated_at":"2026-08-13T05:00:00Z","items":[{"id":"a",'
            '"scheduled_for":"2026-08-13T05:00:00Z","video_url":"u","caption":"c",'
            '"parts":{},"status":"halfway","attempts":0}]}',
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            load_queue(path)

    def test_write_is_atomic_and_leaves_no_temp_files(self, tmp_path: Path) -> None:
        path = tmp_path / "queue.json"
        save_queue(path, Queue(generated_at=NOW, items=[item()]))
        assert [p.name for p in tmp_path.iterdir()] == ["queue.json"]

    def test_history_appends_and_never_prunes(self, tmp_path: Path) -> None:
        path = tmp_path / "history.json"
        first = [HistoryEntry(tuple_hash=f"h{i}", timestamp=NOW, item_id=f"i{i}",
                              hook="hook_01.mp4", bodies=("body_01.mp4",),
                              music=None, caption="c") for i in range(3)]
        append_history(path, first)
        second = [HistoryEntry(tuple_hash="h9", timestamp=NOW, item_id="i9",
                               hook="hook_02.mp4", bodies=("body_02.mp4",),
                               music=None, caption="c2")]
        history = append_history(path, second)
        assert len(history.entries) == 4
        assert len(load_history(path).entries) == 4

    def test_missing_history_loads_empty(self, tmp_path: Path) -> None:
        assert load_history(tmp_path / "history.json").entries == []

    def test_corrupt_history_fails_loud(self, tmp_path: Path) -> None:
        path = tmp_path / "history.json"
        path.write_text("[[[", encoding="utf-8")
        with pytest.raises(ValidationError, match="not a valid history file"):
            load_history(path)


class TestCrashResume:
    """SPEC §14 — kill the top-up job between claimed and pushed."""

    def test_claim_is_persisted_before_the_push(self, tmp_path: Path,
                                                log: StructuredLogger) -> None:
        path = tmp_path / "queue.json"
        q = Queue(generated_at=NOW, items=[item("a")])
        transition(q.items[0], QueueStatus.CLAIMED, log=log)
        save_queue(path, q)  # simulate the commit, then die before publishing

        resumed = load_queue(path)
        assert [i.id for i in stranded(resumed)] == ["a"]
        assert claimable(resumed) == [], \
            "a stranded item must not look pushable to the next run"

    def test_stranded_item_can_be_released_back_to_pending(
        self, tmp_path: Path, log: StructuredLogger
    ) -> None:
        """After reconciling against Buffer and finding no post, retry is legal."""
        i = item("a", QueueStatus.CLAIMED)
        assert transition(i, QueueStatus.PENDING, log=log).status is QueueStatus.PENDING

    def test_stranded_item_can_be_completed_if_buffer_has_it(
        self, log: StructuredLogger
    ) -> None:
        """Reconciliation found the post — record it rather than pushing again."""
        i = item("a", QueueStatus.CLAIMED)
        mark_pushed(i, "found-in-buffer-123", log=log)
        assert i.status is QueueStatus.PUSHED
        assert i.buffer_post_id == "found-in-buffer-123"


class TestWrappingWindow:
    """A window may cross midnight — 'hourly from 3pm' needs it."""

    def test_equal_hours_means_a_full_day(self) -> None:
        slots = spread_schedule(NOW, 24, 15, 15)
        assert len(slots) == 24
        assert slots[0].hour == 15
        gaps = {(b - a) for a, b in zip(slots, slots[1:])}
        assert gaps == {timedelta(hours=1)}, "should be exactly hourly"

    def test_wrapping_window_rolls_into_the_next_day(self) -> None:
        slots = spread_schedule(NOW, 24, 15, 15)
        assert slots[0].day == NOW.day
        assert slots[-1].day == NOW.day + 1, "later slots land tomorrow"
        assert slots[-1].hour == 14

    def test_partial_wrap_is_supported(self) -> None:
        """15:00 -> 02:00 is eleven hours, not a negative window."""
        slots = spread_schedule(NOW, 11, 15, 2)
        assert len(slots) == 11
        assert slots[0].hour == 15
        assert slots[-1].hour == 1

    def test_non_wrapping_window_is_unchanged(self) -> None:
        slots = spread_schedule(NOW, 6, 9, 21)
        assert all(9 <= s.hour < 21 for s in slots)
        assert all(s.day == NOW.day for s in slots)

    def test_slots_are_always_ordered(self) -> None:
        for start, end in ((15, 15), (15, 2), (9, 21), (22, 6)):
            slots = spread_schedule(NOW, 12, start, end)
            assert slots == sorted(slots), f"{start}->{end}"


class TestUpcomingSlots:
    """Slots start from the next real opening, not from tomorrow."""

    TZ = timezone.utc

    def test_todays_remaining_slots_are_used(self) -> None:
        """A render at 14:50 must fill 15:00 today, not 15:00 tomorrow."""
        now = datetime(2026, 8, 13, 14, 50, tzinfo=self.TZ)
        slots = upcoming_slots(now, 3, 15, 15, 24, self.TZ)
        assert slots[0] == datetime(2026, 8, 13, 15, 0, tzinfo=self.TZ)
        assert [s.hour for s in slots] == [15, 16, 17]

    def test_passed_slots_are_skipped_not_deferred_a_day(self) -> None:
        now = datetime(2026, 8, 13, 18, 30, tzinfo=self.TZ)
        slots = upcoming_slots(now, 2, 15, 15, 24, self.TZ)
        assert slots[0] == datetime(2026, 8, 13, 19, 0, tzinfo=self.TZ)

    def test_min_lead_prevents_a_slot_landing_immediately(self) -> None:
        """14:59 must not schedule 15:00 — Buffer needs time to accept it."""
        now = datetime(2026, 8, 13, 14, 59, tzinfo=self.TZ)
        slots = upcoming_slots(now, 1, 15, 15, 24, self.TZ)
        assert slots[0] == datetime(2026, 8, 13, 16, 0, tzinfo=self.TZ)

    def test_slots_roll_into_the_next_day_when_today_is_exhausted(self) -> None:
        now = datetime(2026, 8, 13, 23, 30, tzinfo=self.TZ)
        slots = upcoming_slots(now, 3, 15, 15, 24, self.TZ)
        assert slots[0].day == 14
        assert [s.hour for s in slots] == [0, 1, 2]

    def test_every_slot_is_in_the_future(self) -> None:
        now = datetime(2026, 8, 13, 9, 17, tzinfo=self.TZ)
        for s in upcoming_slots(now, 24, 15, 15, 24, self.TZ):
            assert s > now

    def test_slots_are_unique_and_ordered(self) -> None:
        now = datetime(2026, 8, 13, 12, 0, tzinfo=self.TZ)
        slots = upcoming_slots(now, 48, 15, 15, 24, self.TZ)
        assert len(slots) == len(set(slots)) == 48
        assert slots == sorted(slots)

    def test_narrow_window_still_only_yields_its_own_hours(self) -> None:
        now = datetime(2026, 8, 13, 0, 0, tzinfo=self.TZ)
        slots = upcoming_slots(now, 12, 9, 17, 6, self.TZ)
        assert all(9 <= s.hour < 17 for s in slots), [str(s) for s in slots]

    def test_zero_count_returns_nothing(self) -> None:
        now = datetime(2026, 8, 13, 12, 0, tzinfo=self.TZ)
        assert upcoming_slots(now, 0, 15, 15, 24, self.TZ) == []


class TestStaleSlotHandling:
    """A slot chosen at render time may have passed by the time it is pushed.

    The batch is laid out at ~23:30 covering 24 hours, but the top-up runs
    every four hours and pushes at most `max_buffer_queue`. By mid-morning the
    early slots are behind us, and Buffer rejects a post dated in the past with
    a non-retryable error — which used to fail the whole run.
    """

    def test_a_past_slot_is_detectable(self) -> None:
        past = item("a", when=NOW - timedelta(hours=3))
        assert past.scheduled_for < NOW

    def test_upcoming_slots_never_returns_a_past_time(self) -> None:
        for hour in (0, 6, 11, 17, 23):
            now = datetime(2026, 8, 17, hour, 30, tzinfo=timezone.utc)
            for slot in upcoming_slots(now, 10, 15, 15, 24, timezone.utc):
                assert slot > now, f"{slot} is not after {now}"

    def test_reslotting_preserves_ordering_and_uniqueness(self) -> None:
        now = datetime(2026, 8, 17, 11, 30, tzinfo=timezone.utc)
        slots = upcoming_slots(now, 12, 15, 15, 24, timezone.utc)
        assert slots == sorted(slots)
        assert len(set(slots)) == len(slots)
