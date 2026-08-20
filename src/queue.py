"""Queue and history persistence, and the item state machine (SPEC §11).

Responsibility: own the on-disk state that survives between the render job and
the top-up job, and enforce the legal transitions between item states.

The state machine exists for one reason: the top-up job writes ``claimed`` **and
commits** before calling the publisher, so a job that dies mid-push leaves an
item in ``claimed`` rather than ``pending``. The next run then knows to
*investigate* rather than blindly re-push. Buffer does expose ``deletePost``
(README §0, contrary to SPEC §4.2's assumption), but only while the post is
still queued — once Instagram publishes a duplicate it is out for good, so
avoiding the double-push remains the correct design.

Note on the module name: this shadows the stdlib ``queue`` only for relative
imports, which Python 3 does not perform. ``import queue`` elsewhere still finds
the stdlib module.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

from src.errors import ValidationError
from src.logging import StructuredLogger
from src.models import (
    History,
    HistoryEntry,
    Queue,
    QueueItem,
    QueueStatus,
)

#: Legal transitions. Anything not listed here is a bug, and raising on it is
#: what keeps a partially-understood failure from corrupting the queue further.
ALLOWED_TRANSITIONS: dict[QueueStatus, frozenset[QueueStatus]] = {
    QueueStatus.PENDING: frozenset(
        {QueueStatus.CLAIMED, QueueStatus.FAILED, QueueStatus.CANCELLED}
    ),
    QueueStatus.CLAIMED: frozenset(
        {QueueStatus.PUSHED, QueueStatus.FAILED, QueueStatus.PENDING}
    ),
    # Reachable from pushed on purpose: a post already sitting in Buffer can
    # still be withdrawn before Buffer publishes it, and the queue has to be
    # able to record that rather than keep claiming the post exists.
    QueueStatus.PUSHED: frozenset({QueueStatus.CANCELLED}),
    QueueStatus.FAILED: frozenset({QueueStatus.PENDING, QueueStatus.CANCELLED}),
    QueueStatus.CANCELLED: frozenset(),  # terminal — a human decided
}

#: ``claimed`` is deliberately absent above. An item in that state may be
#: mid-push right now: the top-up job commits ``claimed`` *before* calling
#: Buffer, so cancelling one is a race against a publish already in flight.
CANCELLABLE: frozenset[QueueStatus] = frozenset(
    {QueueStatus.PENDING, QueueStatus.PUSHED, QueueStatus.FAILED}
)


class IllegalTransition(ValidationError):
    """An attempt to move an item between states that may not connect."""


def transition(item: QueueItem, to: QueueStatus, *, log: StructuredLogger) -> QueueItem:
    """Move an item to a new state, or raise ``IllegalTransition``.

    Mutates in place (``QueueItem`` is deliberately not frozen) and returns the
    same object, so callers can chain without wondering whether they hold a copy.
    """
    if to not in ALLOWED_TRANSITIONS[item.status]:
        raise IllegalTransition(
            f"item {item.id}: {item.status.value} -> {to.value} is not a legal "
            f"transition (allowed: "
            f"{sorted(s.value for s in ALLOWED_TRANSITIONS[item.status]) or 'none'})"
        )
    log.info(
        "queue_transition", item_id=item.id, was=item.status.value, now=to.value
    )
    item.status = to
    return item


def mark_failed(item: QueueItem, error: str, *, log: StructuredLogger) -> QueueItem:
    """Record a failure and increment the attempt counter.

    ``attempts`` counts *failures*, not tries, and is what bounds the retry loop
    at ``QueueItem.MAX_ATTEMPTS`` (SPEC §12).
    """
    item.attempts += 1
    # Truncated: a full API error payload in a committed JSON file makes every
    # future diff unreadable, and the full text is already in the log.
    item.last_error = error[:500]
    if item.status is not QueueStatus.FAILED:
        transition(item, QueueStatus.FAILED, log=log)
    else:
        log.info("queue_retry_failed", item_id=item.id, attempts=item.attempts)
    return item


def reset_for_retry(item: QueueItem, *, log: StructuredLogger) -> QueueItem:
    """Return a failed item to ``pending`` if it has attempts left."""
    if item.status is not QueueStatus.FAILED:
        raise IllegalTransition(
            f"item {item.id} is {item.status.value}, only failed items retry"
        )
    if item.attempts >= QueueItem.MAX_ATTEMPTS:
        raise IllegalTransition(
            f"item {item.id} has used all {QueueItem.MAX_ATTEMPTS} attempts"
        )
    return transition(item, QueueStatus.PENDING, log=log)


def mark_pushed(
    item: QueueItem, post_id: str, *, log: StructuredLogger
) -> QueueItem:
    """Record a successful publish."""
    transition(item, QueueStatus.PUSHED, log=log)
    item.buffer_post_id = post_id
    item.last_error = None
    return item


def carry_forward(
    queue: Queue, now: datetime, retention_days: int
) -> tuple[list[QueueItem], list[QueueItem]]:
    """Split last night's queue into what is still worth keeping, and what is not.

    Replacing the queue wholesale each night — which is what render used to do —
    silently discarded everything the top-up had not pushed yet. At a render
    rate above the channel's real publish rate that is most of the output: the
    videos were made, uploaded, and thrown away unseen.

    Two reasons an item is dropped rather than carried:

    * it is finished (pushed, cancelled, or failed past its retries), or
    * its media has aged out. Render Releases are deleted after the retention
      window, so an older item's ``video_url`` is a link to nothing and pushing
      it would fail at Buffer with a confusing fetch error.

    Returns ``(kept, dropped)`` so the caller can report the second rather than
    lose it quietly a second time.
    """
    horizon = now - timedelta(days=retention_days)
    kept: list[QueueItem] = []
    dropped: list[QueueItem] = []
    for item in queue.items:
        if item.is_terminal:
            continue  # finished business, not a loss
        # Without rendered_at (a queue file predating the field) fall back to
        # the slot, which is close enough: slots are always near the render.
        stamp = item.rendered_at or item.scheduled_for
        (dropped if stamp < horizon else kept).append(item)
    return kept, dropped


def cancel(item: QueueItem, *, log: StructuredLogger) -> QueueItem:
    """Withdraw an item on a human's say-so.

    Does not touch the publisher — whether Buffer also has to be told is the
    caller's problem, because only the caller knows if the push already
    happened. This records the decision; it does not enact it remotely.
    """
    if item.status not in CANCELLABLE:
        raise IllegalTransition(
            f"item {item.id} is {item.status.value} and cannot be cancelled; "
            f"a claimed item may be mid-push, so it must be reconciled first"
        )
    return transition(item, QueueStatus.CANCELLED, log=log)


def claimable(queue: Queue) -> list[QueueItem]:
    """Items eligible to be pushed, oldest scheduled slot first.

    Ordering by ``scheduled_for`` rather than list position means a partially
    drained queue still fills the earliest free slots first.
    """
    ready = [i for i in queue.items if i.status is QueueStatus.PENDING]
    return sorted(ready, key=lambda i: i.scheduled_for)


def stranded(queue: Queue) -> list[QueueItem]:
    """Items left ``claimed`` by a job that died mid-push (SPEC §11).

    These must never be pushed blindly. The caller reconciles each against the
    publisher's own record of what exists at that scheduled time.
    """
    return [i for i in queue.items if i.status is QueueStatus.CLAIMED]


def depth_needed(queue_depth: int, max_queue: int) -> int:
    """How many items to push to top the channel up to its cap (SPEC §4.1).

    Clamped at zero: a channel already at or over its cap needs nothing, and a
    negative count would otherwise become a slice that pushes everything.
    """
    return max(0, max_queue - queue_depth)


def upcoming_slots(
    now: datetime,
    count: int,
    start_hour: int,
    end_hour: int,
    posts_per_day: int,
    tz: tzinfo,
    *,
    min_lead: timedelta = timedelta(minutes=10),
    exclude: set[datetime] | None = None,
) -> list[datetime]:
    """The next ``count`` posting slots at or after ``now + min_lead``.

    Replaces "schedule everything for tomorrow". A slot that has already passed
    today is skipped rather than shifting the whole batch a day out, so a render
    at 14:50 fills the 15:00 slot instead of waiting until tomorrow.

    ``min_lead`` keeps a slot from landing so close to now that Buffer has no
    time to accept it before it is already due; a post scheduled for thirty
    seconds' time is a race, not a schedule.

    Cycles are generated from several consecutive days because a wrapping
    window's slots span two dates, and the current cycle may have started
    yesterday.
    """
    if count <= 0:
        return []
    local_now = now.astimezone(tz)
    earliest = local_now + min_lead

    candidates: list[datetime] = []
    # Start a day back: with a window that began yesterday afternoon, today's
    # remaining slots belong to yesterday's cycle.
    for offset in range(-1, 8):
        cycle_day = (local_now + timedelta(days=offset)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        candidates.extend(
            spread_schedule(cycle_day, posts_per_day, start_hour, end_hour)
        )

    taken = exclude or set()
    future = sorted({s for s in candidates if s >= earliest} - taken)
    return future[:count]


def spread_schedule(
    day: datetime, count: int, start_hour: int, end_hour: int
) -> list[datetime]:
    """Evenly spaced local times across the posting window (SPEC §9).

    Buffer ultimately controls publish timing, but a post still carries a
    ``dueAt``, and clustering them all at one instant would defeat the point of
    the window. The last slot lands strictly before the window closes.

    The window may wrap past midnight — ``start_hour: 15`` with
    ``end_hour: 15`` is a full day starting at 3pm — in which case the later
    slots naturally fall on the following calendar date. Callers must not
    assume every returned slot shares ``day``'s date.
    """
    if count <= 0:
        return []
    start = day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    span = (end_hour - start_hour) % 24 or 24
    window = timedelta(hours=span)
    if count == 1:
        return [start + window / 2]
    # count-1 gaps would put the final slot exactly at the window's close, which
    # belongs to the next window; divide by count instead and offset.
    step = window / count
    return [start + step * i for i in range(count)]


# --------------------------------------------------------------- persistence


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file and rename.

    A CI job killed mid-write would otherwise leave truncated JSON, and the next
    run would fail to parse the queue rather than resume it. ``os.replace`` is
    atomic on the same filesystem, so a reader sees either the old file or the
    new one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def load_queue(path: Path) -> Queue:
    """Read ``queue.json``, or return an empty queue if it does not exist yet."""
    if not path.is_file():
        return Queue(generated_at=datetime.fromtimestamp(0, tz=timezone.utc), items=[])
    try:
        return Queue.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        # Never "recover" by starting fresh: a corrupt queue whose items may
        # already be in Buffer must be looked at by a human, not overwritten.
        raise ValidationError(f"{path} is not a valid queue file: {exc}") from exc


def save_queue(path: Path, queue: Queue) -> None:
    _atomic_write(path, queue.model_dump_json(indent=2) + "\n")


def load_history(path: Path) -> History:
    """Read ``history.json``, or return an empty history."""
    if not path.is_file():
        return History()
    try:
        return History.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"{path} is not a valid history file: {exc}") from exc


def append_history(path: Path, entries: list[HistoryEntry]) -> History:
    """Append entries and persist. History is never pruned (SPEC §11).

    Read-modify-write is safe here because the workflows use a concurrency group
    that forbids two jobs for the same campaign running at once (SPEC §12).
    """
    history = load_history(path)
    history.entries.extend(entries)
    _atomic_write(path, history.model_dump_json(indent=2) + "\n")
    return history


def backfill_post_id(path: Path, item_id: str, post_id: str) -> None:
    """Record a publisher's post id against an existing history entry.

    History is append-only in the sense that entries are never *removed* (SPEC
    §11) — the combination was consumed at render time and stays consumed. The
    post id is simply not known until the top-up job runs, so it is filled in
    afterwards rather than duplicating the entry.
    """
    history = load_history(path)
    for index, entry in enumerate(history.entries):
        if entry.item_id == item_id:
            # HistoryEntry is frozen: replace the element rather than mutating
            # it, so the immutability guarantee holds everywhere else.
            history.entries[index] = entry.model_copy(
                update={"buffer_post_id": post_id}
            )
            _atomic_write(path, history.model_dump_json(indent=2) + "\n")
            return
