"""Typed models passed between modules.

Responsibility: define the shapes that cross module boundaries, so no module
hands another a bare ``dict``.

SPEC §2.2: "Pydantic models for config, queue items, and every API payload. No
dicts passed between modules. No stringly-typed status values — use enums."

Models that belong to exactly one module (Buffer wire payloads, for instance)
live with that module; this file holds only the shared vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """Base: unknown fields are errors, instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PartKind(str, Enum):
    """The role a source asset plays in a composition."""

    HOOK = "hook"
    BODY = "body"
    MUSIC = "music"


class MediaProbe(Model):
    """What ffprobe reports about a media file.

    Deliberately a narrow subset: only the fields the pipeline makes decisions
    on. ``has_audio`` in particular drives the silent-track substitution that
    SPEC §6 calls "the single most common cause of concat corruption".
    """

    path: Path
    duration_sec: float = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)
    fps: float = Field(ge=0)
    has_video: bool
    has_audio: bool
    video_codec: str | None = None
    audio_codec: str | None = None
    size_bytes: int = Field(ge=0)

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width


class Selection(Model):
    """One chosen combination of parts plus its caption (SPEC §10).

    This is the selector's output and the renderer's input. It names assets by
    *filename* rather than absolute path so the same selection is meaningful
    across the render machine and the history file.
    """

    hook: str
    bodies: tuple[str, ...] = Field(min_length=1)
    music: str | None
    #: The text the video is posted with — Instagram's caption box, TikTok's
    #: caption, YouTube's description. Never drawn onto the video.
    caption: str
    #: Separate short title, for platforms that have one (YouTube: 100 chars).
    #: None everywhere else, where the description is the only text field.
    title: str | None = None
    #: Where in the track the bed starts, in seconds. Quantised to the
    #: configured grid so it is a dedupe-able identity, not a free float.
    music_offset_sec: float = Field(default=0.0, ge=0.0)

    @property
    def tuple_key(self) -> tuple[str, ...]:
        """Stable ordering of the parts, for hashing and logging."""
        return (self.hook, *self.bodies, self.music or "", self.caption)


class RenderRequest(Model):
    """Everything the renderer needs to produce one video.

    Paths are absolute and already downloaded; the renderer never fetches.
    """

    item_id: str
    hook_path: Path
    body_paths: tuple[Path, ...] = Field(min_length=1)
    music_path: Path | None
    music_offset_sec: float = Field(default=0.0, ge=0.0)
    output_path: Path


class RenderResult(Model):
    """A rendered file that has passed every validation in SPEC §6."""

    item_id: str
    output_path: Path
    probe: MediaProbe


class QueueStatus(str, Enum):
    """State machine for a queue item (SPEC §11).

    ``pending -> claimed -> pushed``, with ``-> failed`` from any state and
    ``failed -> pending`` on retry while ``attempts < 3``.

    ``cancelled`` is the operator's own verdict, reachable from any state a
    human can act on. It is deliberately not ``failed``: nothing went wrong,
    somebody decided this video should not go out, and conflating the two would
    put a deliberate choice into the failure alerts.

    ``claimed`` exists solely to make a crash mid-push detectable: the top-up
    job writes and commits ``claimed`` *before* calling the publisher, so a job
    that dies between the two leaves evidence rather than an ambiguous
    ``pending`` that a naive rerun would push twice.
    """

    PENDING = "pending"
    CLAIMED = "claimed"
    PUSHED = "pushed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QueueItem(Model):
    """One rendered video awaiting publication (SPEC §11)."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    id: str
    scheduled_for: datetime
    video_url: str
    caption: str
    title: str | None = None
    parts: dict[str, str]
    status: QueueStatus = QueueStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    buffer_post_id: str | None = None
    last_error: str | None = None

    # SPEC §12 — retry 3 times, then stop and alert. ClassVar so it is a policy
    # constant rather than a per-item field that could be serialised and drift.
    MAX_ATTEMPTS: ClassVar[int] = 3

    @property
    def is_terminal(self) -> bool:
        """True when no further action will be taken on this item."""
        return self.status in (QueueStatus.PUSHED, QueueStatus.CANCELLED) or (
            self.status is QueueStatus.FAILED and self.attempts >= self.MAX_ATTEMPTS
        )


class Queue(Model):
    """The committed render output: a dated batch of items (SPEC §11)."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    generated_at: datetime
    items: list[QueueItem] = Field(default_factory=list)


class HistoryEntry(Model):
    """One published combination, appended forever (SPEC §11).

    Never pruned: the dedupe guarantee is only as good as the history behind it.
    """

    tuple_hash: str
    timestamp: datetime
    item_id: str
    hook: str
    bodies: tuple[str, ...]
    music: str | None
    music_offset_sec: float = 0.0
    caption: str
    title: str | None = None
    buffer_post_id: str | None = None


class History(Model):
    """Append-only log of every combination ever used."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    entries: list[HistoryEntry] = Field(default_factory=list)
