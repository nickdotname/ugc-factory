"""The drop folder: take files a human dropped in, make them correct, upload.

Responsibility: remove every way a person can get an asset upload wrong.

Without this, adding a clip means knowing that Release assets are a flat
namespace, that the ``hook_``/``body_``/``music_`` prefix is therefore the only
thing assigning a role, that spaces in filenames break the concat list, and that
a file which ffprobe cannot read will not fail until 5 a.m. the next morning.
That is four pieces of trivia standing between someone and a working upload.

Instead: drop files in ``inbox/hooks``, ``inbox/bodies``, ``inbox/music`` and
run ``ingest``. This module probes every file, refuses the ones that cannot
work, names the rest correctly, and uploads them.

Deliberately *not* a re-encoder. ``render.py`` already normalises resolution,
frame rate, sample aspect ratio and missing audio, so re-encoding here would
throw away quality to fix problems that are already handled downstream. Ingest
only rejects what the renderer genuinely cannot rescue.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from src.assets import LocalLibrary, MediaStore
from src.errors import ValidationError
from src.logging import StructuredLogger
from src.models import PartKind
from src.render import Renderer

#: Where a human drops files, one directory per role. The directory is what
#: assigns the role, so nobody has to remember a naming convention.
INBOX_DIRS: dict[PartKind, str] = {
    PartKind.HOOK: "hooks",
    PartKind.BODY: "bodies",
    PartKind.MUSIC: "music",
}

#: Files that survive ingest are moved here, so re-running is safe and does not
#: upload the same clip twice under a second name.
ARCHIVE_DIR = "_uploaded"

_NUMBERED = re.compile(r"^(hook|body|music)_(\d+)", re.IGNORECASE)


class Verdict(str, Enum):
    """What ingest decided about one dropped file."""

    OK = "ok"
    WARNED = "warned"
    REJECTED = "rejected"


@dataclass
class Candidate:
    """One dropped file and what ingest concluded about it."""

    source: Path
    kind: PartKind
    target_name: str = ""
    verdict: Verdict = Verdict.OK
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.verdict is not Verdict.REJECTED


@dataclass
class IngestPlan:
    """Everything ingest intends to do, before it does any of it."""

    candidates: list[Candidate] = field(default_factory=list)

    @property
    def uploadable(self) -> list[Candidate]:
        return [c for c in self.candidates if c.usable]

    @property
    def rejected(self) -> list[Candidate]:
        return [c for c in self.candidates if not c.usable]

    def render_table(self) -> str:
        """A plain-text summary a human reads before confirming."""
        if not self.candidates:
            return "inbox is empty — nothing to upload"
        width = max(len(c.source.name) for c in self.candidates)
        lines = []
        for c in self.candidates:
            mark = {"ok": "✓", "warned": "!", "rejected": "✗"}[c.verdict.value]
            arrow = f"→ {c.target_name}" if c.usable else "→ skipped"
            lines.append(f"  {mark} {c.source.name:<{width}}  {arrow}")
            for note in c.notes:
                lines.append(f"      {note}")
        return "\n".join(lines)


def next_index(existing: list[str], kind: PartKind) -> int:
    """First free number for a role, continuing any existing sequence.

    Looks at what is already in the Release rather than at the inbox, so a
    second ingest run appends ``hook_07`` instead of overwriting ``hook_01``.
    """
    highest = 0
    for name in existing:
        match = _NUMBERED.match(name)
        if match and match.group(1).lower() == kind.value:
            highest = max(highest, int(match.group(2)))
    return highest + 1


def _probe_notes(path: Path, kind: PartKind, renderer: Renderer) -> tuple[Verdict, list[str]]:
    """Decide whether a file can work, and what the human should know.

    The bar is deliberately low: reject only what the renderer cannot fix.
    Everything it *can* fix — landscape framing, odd frame rates, non-square
    pixels, a missing audio track — is a note, not a rejection, because saying
    "rejected: landscape" about a clip the pipeline crops perfectly well would
    be a lie.
    """
    notes: list[str] = []
    try:
        probe = renderer.probe(path)
    except Exception as exc:  # noqa: BLE001 - any probe failure means unusable
        # ffmpeg's stderr is multi-line and mostly noise; the table needs one
        # line. The full text is already in the structured log.
        detail = " ".join(str(exc).split())
        return Verdict.REJECTED, [
            f"not a readable video file — {detail[:110]}"
        ]

    if kind is PartKind.MUSIC:
        if not probe.has_audio:
            return Verdict.REJECTED, ["no audio stream — not a usable music track"]
        if probe.duration_sec < 1.0:
            return Verdict.REJECTED, [f"only {probe.duration_sec:.1f}s long"]
        return Verdict.OK, notes

    if not probe.has_video:
        return Verdict.REJECTED, ["no video stream"]
    if probe.duration_sec < 0.5:
        return Verdict.REJECTED, [f"only {probe.duration_sec:.2f}s long — unusable"]

    verdict = Verdict.OK
    if not probe.is_vertical:
        notes.append(
            f"{probe.width}x{probe.height} is not vertical — will be centre-cropped "
            f"to 9:16, so keep the subject centred"
        )
        verdict = Verdict.WARNED
    if not probe.has_audio:
        notes.append("no audio track — silence will be added automatically")
        verdict = Verdict.WARNED
    if kind is PartKind.HOOK and probe.duration_sec > 10:
        notes.append(
            f"{probe.duration_sec:.0f}s is long for a hook — the first 1-2s decide "
            f"whether a Reel is watched"
        )
        verdict = Verdict.WARNED
    return verdict, notes


def build_plan(
    inbox: Path,
    existing: list[str],
    renderer: Renderer,
    log: StructuredLogger,
) -> IngestPlan:
    """Inspect every dropped file and decide its fate. Changes nothing."""
    plan = IngestPlan()
    counters = {kind: next_index(existing, kind) for kind in PartKind}

    for kind, dirname in INBOX_DIRS.items():
        folder = inbox / dirname
        if not folder.is_dir():
            continue
        suffixes = (
            LocalLibrary.AUDIO_SUFFIXES
            if kind is PartKind.MUSIC
            else LocalLibrary.VIDEO_SUFFIXES
        )
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            candidate = Candidate(source=path, kind=kind)

            if path.suffix.lower() not in suffixes:
                candidate.verdict = Verdict.REJECTED
                candidate.notes.append(
                    f"{path.suffix or 'no extension'} is not accepted here "
                    f"(expected {', '.join(suffixes)})"
                )
                plan.candidates.append(candidate)
                continue

            candidate.verdict, candidate.notes = _probe_notes(path, kind, renderer)
            if candidate.usable:
                # Extension is normalised to lowercase; the rest of the name is
                # generated, so spaces and unicode in the original cannot reach
                # the ffmpeg concat list or a URL.
                candidate.target_name = (
                    f"{kind.value}_{counters[kind]:02d}{path.suffix.lower()}"
                )
                counters[kind] += 1
            plan.candidates.append(candidate)

    log.info(
        "ingest_plan",
        found=len(plan.candidates),
        uploadable=len(plan.uploadable),
        rejected=len(plan.rejected),
    )
    return plan


def apply_plan(
    plan: IngestPlan,
    inbox: Path,
    store: MediaStore,
    tag: str,
    log: StructuredLogger,
    *,
    staging: Path,
) -> list[str]:
    """Upload the plan's files under their generated names.

    Files are copied into a staging directory under their target name first,
    because the media store uploads a path and takes its name from it — renaming
    in the inbox would mutate the user's own files.
    """
    if not plan.uploadable:
        return []

    staging.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for candidate in plan.uploadable:
        target = staging / candidate.target_name
        shutil.copy2(candidate.source, target)
        staged.append(target)

    store.publish(tag, staged)

    archive = inbox / ARCHIVE_DIR
    archive.mkdir(parents=True, exist_ok=True)
    uploaded: list[str] = []
    for candidate in plan.uploadable:
        # Move only after a successful upload, so a failed run leaves the inbox
        # exactly as the user left it and can simply be re-run.
        destination = archive / candidate.target_name
        shutil.move(str(candidate.source), str(destination))
        uploaded.append(candidate.target_name)
        log.info(
            "ingest_uploaded",
            source=candidate.source.name,
            name=candidate.target_name,
        )

    shutil.rmtree(staging, ignore_errors=True)
    return uploaded


def ensure_inbox(inbox: Path) -> None:
    """Create the drop folders if they are missing."""
    for dirname in INBOX_DIRS.values():
        (inbox / dirname).mkdir(parents=True, exist_ok=True)


def library_health(
    hooks: int,
    bodies: int,
    music: int,
    captions: int,
    bodies_per_video: int,
    posts_per_day: int,
    hook_cooldown_days: int,
    caption_cooldown_days: int,
) -> list[str]:
    """Warnings about a library that is too small for its configured cadence.

    Reported at ingest time — while someone is actually holding the files and
    can do something about it — rather than only at 5 a.m. when the selector
    starts relaxing its rules.
    """
    problems: list[str] = []

    if hooks and posts_per_day * hook_cooldown_days > hooks:
        needed = posts_per_day * hook_cooldown_days
        problems.append(
            f"hook cooldown needs {needed} hooks at {posts_per_day}/day with a "
            f"{hook_cooldown_days}-day cooldown; you have {hooks}. The selector "
            f"will relax it and alert every day."
        )
    if captions and posts_per_day * caption_cooldown_days > captions:
        needed = posts_per_day * caption_cooldown_days
        problems.append(
            f"caption cooldown needs {needed} captions at {posts_per_day}/day "
            f"with a {caption_cooldown_days}-day cooldown; you have {captions}. "
            f"Captions are just text — writing more is the cheapest fix."
        )
    if bodies and posts_per_day > bodies:
        per_day = posts_per_day / bodies
        problems.append(
            f"{bodies} body clips at {posts_per_day} posts/day means each one "
            f"goes out {per_day:.1f}× a day. Unique tuples do not make the "
            f"content look different to a viewer."
        )
    return problems


def combinations(
    hooks: int,
    bodies: int,
    music: int,
    captions: int,
    bodies_per_video: int,
    music_options: int | None = None,
) -> int:
    """Distinct combinations available.

    Delegates to ``AssetLibrary.ceiling`` rather than reimplementing the
    arithmetic. An earlier copy of the formula here drifted the moment music
    gained segments: this counted three *tracks* while the selector counted
    thirty-six *beds*, so preflight failed a runway check the selector would
    have passed. One formula, one answer.

    ``music_options`` is the true count of (track, segment) pairs when the
    caller has probed durations. Without it this falls back to counting tracks,
    which under-reports — safe, because it warns early rather than late.
    """
    from src.selector import AssetLibrary

    effective_music = music if music_options is None else music_options
    library = AssetLibrary(
        hooks=tuple(f"h{i}" for i in range(hooks)),
        bodies=tuple(f"b{i}" for i in range(bodies)),
        music=tuple(f"m{i}" for i in range(effective_music)),
        captions=tuple(f"c{i}" for i in range(captions)),
    )
    return library.ceiling(bodies_per_video)
