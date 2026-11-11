"""The lineup: posts spelled out by hand instead of drawn by the randomizer.

Responsibility: turn ``campaigns/<slug>/lineup.yaml`` into validated entries,
each naming exactly which clip, which song from which second, which on-screen
line and which caption one video gets — and, optionally, which accounts it
goes to and when.

Why it exists: the randomizer answers "keep the channel fed without repeating
yourself". It cannot answer "this clip, on this lyric, with this joke, on
Friday at six" — and for a release that is most of what matters. The two
compose: render takes due lineup entries first and lets the randomizer fill
whatever slots are left, unless ``selection.auto_fill`` is off, in which case
the lineup is the whole schedule.

An entry is consumed once. Its ``id`` is written to the queue item and to
``history.json`` when it renders, and an id found there is never rendered
again — so the file can keep its finished entries as a record, and re-running
render is always safe.

    posts:
      - id: bro-moving-01
        creative: sunday_song          # default: the campaign's first
        hook: hook_03.mp4              # the clip (or first clip)
        bodies: []                     # more clips to cut to, in order
        music: music_01.mp3            # omit for no music
        music_start: 42.5              # seconds into the track
        overlay: how bro starts moving | when this comes on
        caption: |
          Sunday Song – Close Quarters
          out now everywhere
        title: Sunday Song – Close Quarters   # YouTube; derived if omitted
        captions:                      # optional per-network overrides
          tiktok: sunday song by close quarters #newmusic
        accounts: [nickdotname_tt]     # default: everywhere the creative goes
        at: 2026-11-14 18:00           # campaign timezone; default: next slot
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator

from src.config import StrictModel, Yaml12Loader
from src.errors import ConfigError
from src.platforms import Service

#: Filename of the lineup inside a campaign directory.
LINEUP_FILE = "lineup.yaml"

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class LineupEntry(StrictModel):
    """One hand-specified post."""

    id: str
    creative: str | None = None
    hook: str = Field(min_length=1)
    bodies: tuple[str, ...] = ()
    music: str | None = None
    music_start: float = Field(default=0.0, ge=0.0)
    overlay: str | None = None
    caption: str = Field(min_length=1)
    title: str | None = None
    #: Per-network caption overrides, keyed by network name.
    captions: dict[Service, str] = Field(default_factory=dict)
    accounts: tuple[str, ...] = ()
    #: When to publish. Naive times are read in the campaign's timezone.
    at: datetime | None = None
    #: Keep an entry in the file without posting it.
    skip: bool = False

    @field_validator("id")
    @classmethod
    def _id_is_plain(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError(
                f"lineup id {v!r} must be letters, digits, dot, dash or "
                f"underscore (it is written into history as the entry's name)"
            )
        return v

    @field_validator("caption")
    @classmethod
    def _caption_is_trimmed(cls, v: str) -> str:
        return v.strip()


class Lineup(StrictModel):
    posts: tuple[LineupEntry, ...] = ()

    @field_validator("posts")
    @classmethod
    def _ids_are_unique(cls, v: tuple[LineupEntry, ...]) -> tuple[LineupEntry, ...]:
        seen: set[str] = set()
        for entry in v:
            if entry.id in seen:
                raise ValueError(
                    f"lineup id {entry.id!r} is used twice; ids are how a "
                    f"finished entry is told from a new one"
                )
            seen.add(entry.id)
        return v


def lineup_path(campaign_dir: Path) -> Path:
    return campaign_dir / LINEUP_FILE


def load_lineup(path: Path) -> Lineup:
    """Read the lineup, or an empty one if the campaign has none."""
    if not path.is_file():
        return Lineup()
    try:
        raw: Any = yaml.load(path.read_text(encoding="utf-8"), Loader=Yaml12Loader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if raw is None:
        return Lineup()
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path} must contain a YAML mapping with a `posts:` list"
        )
    try:
        return Lineup.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"{path} failed validation:\n{exc}") from exc


def due_entries(
    lineup: Lineup,
    done_ids: set[str],
    now: datetime,
    horizon: datetime,
    zone: Any,
) -> tuple[list[LineupEntry], list[LineupEntry]]:
    """Entries to render now, and timed entries whose moment has passed.

    Returns ``(due, missed)``. An untimed entry is due as soon as it is
    unfinished. A timed one is due once its time is inside ``horizon`` — the
    window render is filling — and is *missed* if that time went by before it
    was ever rendered, which is reported rather than posted late: a post
    written for Friday at six is not obviously still wanted on Sunday.
    """
    due: list[LineupEntry] = []
    missed: list[LineupEntry] = []
    for entry in lineup.posts:
        if entry.skip or entry.id in done_ids:
            continue
        if entry.at is None:
            due.append(entry)
            continue
        when = resolve_time(entry.at, zone)
        if when <= now:
            missed.append(entry)
        elif when <= horizon:
            due.append(entry)
    return due, missed


def resolve_time(at: datetime, zone: Any) -> datetime:
    """A lineup time as an aware datetime in the campaign's zone."""
    return at.replace(tzinfo=zone) if at.tzinfo is None else at
