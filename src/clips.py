"""Which uploaded clips the randomizer is allowed to use.

Responsibility: hold a per-campaign on/off switch for every asset in the
library, so a clip can be pulled out of rotation — or put back — without
deleting anything.

Why this exists: before it, "stop using that hook" meant deleting the file from
the assets Release. That is destructive (the clip is gone, and re-uploading it
gets a new number), slow (a network round trip), and unrecoverable if it turns
out the clip was fine. Muting is the operation people actually want nine times
out of ten: a clip flops, it comes out of the mix for a while, it may go back
in.

Stored as a list of *disabled* names rather than enabled ones, which keeps SPEC
§7's promise intact: a clip that was just dropped in has no entry, so it is live
on the next render without anyone having to remember to switch it on.

The roster lives in ``campaigns/<slug>/clips.json``, next to ``history.json``,
because it is campaign state the workflows read — the same clip file may be
muted for one campaign and running in another.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable

from pydantic import Field

from src.assets import LocalLibrary
from src.errors import ValidationError
from src.logging import StructuredLogger
from src.models import Model, PartKind

#: Filename of the roster inside a campaign directory.
ROSTER_FILE = "clips.json"


class ClipRoster(Model):
    """The set of asset filenames held out of the randomizer.

    Names are Release asset filenames (``hook_03.mov``), which is the same
    vocabulary ``Selection`` and ``history.json`` already speak — so a muted
    clip is greppable across the whole system without a translation table.
    """

    disabled: tuple[str, ...] = Field(default_factory=tuple)

    def is_enabled(self, name: str) -> bool:
        return name not in self.disabled

    def with_(self, names: Iterable[str], enabled: bool) -> "ClipRoster":
        """A copy with ``names`` switched on or off.

        Kept sorted and de-duplicated so the file is stable under git: toggling
        a clip off and on again produces byte-identical JSON, and a diff shows
        only what actually changed.
        """
        current = set(self.disabled)
        if enabled:
            current -= set(names)
        else:
            current |= set(names)
        return ClipRoster(disabled=tuple(sorted(current)))


def roster_path(campaign_dir: Path) -> Path:
    return campaign_dir / ROSTER_FILE


def load_roster(path: Path) -> ClipRoster:
    """Read the roster, or return an empty one if the campaign has never used it."""
    if not path.is_file():
        return ClipRoster()
    try:
        return ClipRoster.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        # Never fall back to "everything is enabled": that would silently put a
        # clip the operator deliberately pulled back into tonight's posts, which
        # is precisely the failure this file exists to prevent.
        raise ValidationError(f"{path} is not a valid clip roster: {exc}") from exc


def save_roster(path: Path, roster: ClipRoster) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = roster.model_dump_json(indent=2) + "\n"
    # Same atomic dance as queue.json: a half-written roster read by the render
    # job would either crash it or mute the wrong clips.
    handle, temp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def kind_of(name: str) -> PartKind | None:
    """The role a Release asset filename encodes, by its prefix."""
    lowered = name.lower()
    for kind in PartKind:
        if lowered.startswith(kind.value):
            return kind
    return None


def filter_library(
    library: LocalLibrary, roster: ClipRoster, log: StructuredLogger | None = None
) -> LocalLibrary:
    """Drop every muted clip from a library before the selector ever sees it.

    Filtering here rather than inside the selector keeps the selector's
    arithmetic honest: ``ceiling()`` counts what it was handed, so the runway
    number the digest reports is the runway of the clips actually in rotation,
    not of everything ever uploaded.
    """
    if not roster.disabled:
        return library

    def keep(paths: tuple[Path, ...]) -> tuple[Path, ...]:
        return tuple(p for p in paths if roster.is_enabled(p.name))

    filtered = LocalLibrary(
        hooks=keep(library.hooks),
        bodies=keep(library.bodies),
        music=keep(library.music),
    )
    if log is not None:
        removed = (
            len(library.hooks) - len(filtered.hooks)
            + len(library.bodies) - len(filtered.bodies)
            + len(library.music) - len(filtered.music)
        )
        if removed:
            log.info(
                "clips_muted",
                count=removed,
                hooks=len(filtered.hooks),
                bodies=len(filtered.bodies),
                music=len(filtered.music),
                names=list(roster.disabled),
            )
    return filtered
