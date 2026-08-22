"""Combination picking and dedupe (SPEC §10).

Responsibility: choose ``(hook, body…, music, caption)`` tuples that have not
been used before, respecting per-dimension cooldowns, and say loudly when the
library is too small to keep doing so.

Pure functions over injected ``Clock`` and ``Rng`` (SPEC §2.2) — given a fixed
seed and a fixed history, this module produces identical picks every time, which
is what makes the acceptance tests in SPEC §14 meaningful rather than flaky.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Mapping, Sequence

from src.config import DedupeDimension, SelectionConfig
from src.errors import SelectionError
from src.logging import StructuredLogger
from src.models import History, HistoryEntry, Selection
from src.ports import Clock, Rng


class Relaxation(str, Enum):
    """How far the selector had to bend its rules to find a pick.

    SPEC §10 fixes the order: hook cooldown, then caption cooldown, then
    full-tuple dedupe. Each step is strictly more permissive than the last, and
    any step past ``NONE`` means the library is too small for the cadence and
    must be reported.
    """

    NONE = "none"
    HOOK_COOLDOWN = "hook_cooldown"
    CAPTION_COOLDOWN = "caption_cooldown"
    TUPLE_DEDUPE = "tuple_dedupe"


#: The ladder, most restrictive first. Order is load-bearing: relaxing tuple
#: dedupe first would produce visible exact repeats while cooldowns — a much
#: softer constraint — were still being honoured.
RELAXATION_ORDER: tuple[Relaxation, ...] = (
    Relaxation.NONE,
    Relaxation.HOOK_COOLDOWN,
    Relaxation.CAPTION_COOLDOWN,
    Relaxation.TUPLE_DEDUPE,
)


@dataclass(frozen=True)
class AssetLibrary:
    """The pool of parts available for one campaign, by filename."""

    hooks: tuple[str, ...]
    bodies: tuple[str, ...]
    music: tuple[str, ...]
    captions: tuple[str, ...]
    #: Track filename -> duration in seconds. Empty means "unknown", which
    #: degrades to a single segment per track starting at 0:00 — the old
    #: behaviour, so a campaign that cannot probe still works.
    music_durations: Mapping[str, float] = field(default_factory=dict)
    #: Grid the offsets snap to. Mirrors composition.music_segment_sec.
    music_segment_sec: float = 15.0
    music_skip_intro_sec: float = 0.0

    def validate(self) -> None:
        """Fail loud on an unusable library rather than picking from nothing."""
        empty = [
            name
            for name, pool in (
                ("hooks", self.hooks),
                ("bodies", self.bodies),
                ("captions", self.captions),
            )
            if not pool
        ]
        if empty:
            raise SelectionError(
                f"asset library is missing required parts: {', '.join(empty)}"
            )

    def segments_for(self, track: str) -> int:
        """How many distinct beds one track yields.

        Because the renderer loops the track, an offset near the end is fine —
        it wraps. So this depends only on track length, not on video length.
        """
        duration = self.music_durations.get(track, 0.0)
        usable = duration - self.music_skip_intro_sec
        if usable <= 0 or self.music_segment_sec <= 0:
            return 1
        return max(1, int(usable // self.music_segment_sec))

    def offset_for(self, track: str, segment: int) -> float:
        """Start time in seconds for a given segment index."""
        return self.music_skip_intro_sec + segment * self.music_segment_sec

    def total_music_options(self) -> int:
        """Every (track, segment) pair — the real size of the music dimension."""
        if not self.music:
            return 1
        return sum(self.segments_for(t) for t in self.music)

    def ceiling(self, bodies_per_video: int, bodies_max: int | None = None) -> int:
        """Total distinct combinations available.

        SPEC §10 asks for this to be logged every render: at 6 posts/day you
        want >= 90 days of unique combos (540) before the first repeat.

        When a range of body counts is allowed, every count contributes its own
        combinations — a one-body cut and a two-body cut are different videos
        and hash differently, so the totals add rather than replace.
        """
        from math import comb

        if len(self.bodies) < bodies_per_video:
            return 0
        # Clamped from both ends: a max below the min would otherwise make the
        # range empty and report zero combinations for a library that has
        # plenty, and a max above the library size cannot be satisfied. Config
        # rejects an inverted range, but this is public and should not depend
        # on the caller having been validated.
        top = min(
            max(bodies_max or bodies_per_video, bodies_per_video),
            len(self.bodies),
        )
        body_combos = sum(
            comb(len(self.bodies), n)
            for n in range(bodies_per_video, top + 1)
        )
        # Counts (track, segment) pairs, not tracks: three songs cut into
        # twelve segments each is thirty-six distinct beds, not three.
        music_options = self.total_music_options()
        return len(self.hooks) * body_combos * music_options * len(self.captions)


@dataclass(frozen=True)
class SelectionOutcome:
    """One pick plus how much rule-bending it required."""

    selection: Selection
    relaxation: Relaxation


def tuple_hash(selection: Selection, dimensions: Sequence[DedupeDimension]) -> str:
    """Stable hash of the dimensions a campaign dedupes on.

    Only the configured dimensions contribute, so a campaign that dedupes on
    ``[hook, body]`` treats two tuples differing only by music as the same
    combination — which is what it asked for.

    Sorted-and-joined with a separator that cannot appear in a filename, so
    ``("ab", "c")`` and ``("a", "bc")`` cannot collide.
    """
    parts: list[str] = []
    for dim in sorted(dimensions, key=lambda d: d.value):
        if dim is DedupeDimension.HOOK:
            parts.append(f"hook={selection.hook}")
        elif dim is DedupeDimension.BODY:
            parts.append("body=" + ",".join(sorted(selection.bodies)))
        elif dim is DedupeDimension.MUSIC:
            # The offset is part of the music identity: two beds cut from
            # different points of one track are genuinely different content,
            # and hashing only the filename would collapse them into one.
            offset = f"@{selection.music_offset_sec:.0f}" if selection.music else ""
            parts.append(f"music={selection.music or ''}{offset}")
        elif dim is DedupeDimension.CAPTION:
            # Captions are free text and can be long; hash rather than embed.
            digest = hashlib.sha256(selection.caption.encode("utf-8")).hexdigest()[:16]
            parts.append(f"caption={digest}")
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _last_used(
    entries: Iterable[HistoryEntry], extract: str
) -> dict[str, datetime]:
    """Most recent use time per asset, for cooldowns and LRU weighting."""
    seen: dict[str, datetime] = {}
    for entry in entries:
        values: Sequence[str]
        if extract == "hook":
            values = (entry.hook,)
        elif extract == "caption":
            values = (entry.caption,)
        elif extract == "music":
            values = (entry.music,) if entry.music else ()
        else:
            values = entry.bodies
        for value in values:
            prior = seen.get(value)
            if prior is None or entry.timestamp > prior:
                seen[value] = entry.timestamp
    return seen


def _lru_weights(
    pool: Sequence[str], last_used: Mapping[str, datetime], now: datetime
) -> list[float]:
    """Weight each asset by its position in the recency order.

    SPEC §10: "Weight toward least-recently-used assets, not uniform random —
    uniform random clusters repeats visibly."

    **Rank, not elapsed time.** An earlier version used ``age_in_days + 1``,
    which has no resolution below a day — and a night's batch is picked in one
    instant, so every asset chosen that evening collapsed to the same weight.
    Once each clip had been used once, the remaining twenty-odd picks were
    uniform random, which is precisely what the weighting exists to avoid. It
    showed up in the output as a near-2x spread between the most and least used
    body clip over 148 renders.

    Ranking is scale-free: it discriminates identically whether two uses are a
    month apart or a microsecond apart, so the same function serves the
    across-days case and the within-batch case.

    Never-used assets sort oldest and so carry the maximum weight, which keeps
    SPEC §7's promise that a clip dropped in is picked up promptly. The
    least-weighted asset still has weight 1 rather than 0 — a just-used clip
    stays reachable, because banning it outright is what cooldowns are for.
    """
    if not pool:
        return []
    # Never used sorts first: no timestamp is older than any timestamp.
    floor = datetime.min.replace(tzinfo=now.tzinfo)
    order = sorted(range(len(pool)), key=lambda i: (last_used.get(pool[i]) or floor))

    weights = [0.0] * len(pool)
    for rank, index in enumerate(order):
        # rank 0 is the least recently used and gets the largest weight.
        weights[index] = float(len(pool) - rank)
    return weights


def performance_multipliers(
    pool: Sequence[str],
    medians: Mapping[str, float],
    weight: float,
    max_boost: float,
) -> list[float]:
    """Scale each option by how it has actually performed, gently.

    Ranked rather than proportional. Social metrics span orders of magnitude
    — one video catching an algorithm outruns a hundred — so scaling directly
    by median views would hand a single lucky clip almost every future slot.
    Position in the order is the durable signal; the size of the gap is
    mostly noise.

    Three properties keep this from becoming a feedback loop:

    * an option with no measurement sits at the middle, neither rewarded nor
      punished for being new — otherwise a fresh clip could never earn data;
    * the best option is at most ``max_boost`` times the worst, however far
      apart their numbers are;
    * nothing reaches zero, so every clip keeps a path back into rotation and
      a bad early run is recoverable.
    """
    if weight <= 0 or not pool:
        return [1.0] * len(pool)

    measured = [name for name in pool if name in medians]
    if len(measured) < 2:
        # One measurement is not a comparison, and ranking a field of one
        # would just declare it the winner.
        return [1.0] * len(pool)

    order = sorted(measured, key=lambda n: medians[n])
    position = {name: i / (len(order) - 1) for i, name in enumerate(order)}

    span = max_boost - 1.0
    return [
        1.0 + weight * span * position.get(name, 0.5)
        for name in pool
    ]


class Selector:
    """Picks combinations for one campaign."""

    def __init__(
        self,
        config: SelectionConfig,
        clock: Clock,
        rng: Rng,
        log: StructuredLogger,
        *,
        max_attempts_per_level: int = 400,
    ) -> None:
        self._config = config
        self._clock = clock
        self._rng = rng
        self._log = log
        # Rejection sampling is simple and fast while the library is large
        # relative to history. The cap bounds the pathological case where almost
        # every combination is already used, at which point relaxing is correct.
        self._max_attempts = max_attempts_per_level

    def select_batch(
        self,
        library: AssetLibrary,
        history: History,
        count: int,
        bodies_per_video: int,
        bodies_max: int | None = None,
        performance: Mapping[str, Mapping[str, float]] | None = None,
    ) -> list[SelectionOutcome]:
        """Pick ``count`` combinations, none repeating within the batch.

        Within-batch uniqueness matters independently of history: two identical
        videos scheduled four hours apart is the most visible possible failure.
        """
        library.validate()
        if count <= 0:
            return []

        ceiling = library.ceiling(bodies_per_video, bodies_max)
        self._log.info(
            "combinatorial_ceiling",
            hooks=len(library.hooks),
            bodies=len(library.bodies),
            music=len(library.music),
            captions=len(library.captions),
            bodies_per_video=bodies_per_video,
            total_combinations=ceiling,
            used_combinations=len(history.entries),
        )
        if ceiling == 0:
            raise SelectionError(
                f"library yields zero combinations: {len(library.bodies)} bodies "
                f"cannot fill bodies_per_video={bodies_per_video}"
            )

        outcomes: list[SelectionOutcome] = []
        batch_hashes: set[str] = set()

        # Each pick becomes history for the picks that follow it.
        #
        # Without this the whole batch saw identical last-used data, because
        # ``history`` does not change while the batch is being built. LRU
        # weighting then does nothing *within* a night: whichever clip started
        # the evening with the highest age stayed the heaviest-weighted choice
        # for all of it, so the batch clustered on it — the exact failure the
        # weighting exists to prevent, and measurable in the output as a
        # near-2x spread between the most and least used body clip.
        #
        # Kept separate from ``history`` rather than appended to a copy of it:
        # these picks must not count as committed history for cooldowns or
        # tuple dedupe, only for recency.
        recent: list[HistoryEntry] = []
        now = self._clock.now()

        for _ in range(count):
            outcome = self.select_one(
                library, history, bodies_per_video,
                exclude=batch_hashes, recent=recent, bodies_max=bodies_max,
                performance=performance,
            )
            selection = outcome.selection
            digest = tuple_hash(selection, self._config.dedupe_on)
            batch_hashes.add(digest)
            recent.append(
                HistoryEntry(
                    tuple_hash=digest,
                    # Spaced by a microsecond each so the recency ranking can
                    # order picks made within this batch. Identical stamps
                    # would tie, and ties are what made the weighting inert
                    # here in the first place.
                    timestamp=now + timedelta(microseconds=len(recent)),
                    # No id exists yet — the render has not run. This entry
                    # never leaves this method.
                    item_id="",
                    hook=selection.hook,
                    bodies=selection.bodies,
                    music=selection.music,
                    music_offset_sec=selection.music_offset_sec,
                    caption=selection.caption,
                )
            )
            outcomes.append(outcome)
        return outcomes

    def select_one(
        self,
        library: AssetLibrary,
        history: History,
        bodies_per_video: int,
        *,
        exclude: set[str] | None = None,
        recent: Sequence[HistoryEntry] = (),
        bodies_max: int | None = None,
        performance: Mapping[str, Mapping[str, float]] | None = None,
    ) -> SelectionOutcome:
        """Pick one combination, relaxing rules in SPEC §10's documented order.

        ``recent`` carries picks already made in the current batch. They feed
        the LRU *weighting* only, never the cooldown filter or tuple dedupe.

        The distinction is deliberate. Weighting is about spreading choices
        evenly, and a clip chosen ninety seconds ago is plainly the most
        recently used one — ignoring that is what let a batch cluster. Cooldown
        is a different claim: that a library can sustain a cadence. Applying it
        inside a batch would mean six hooks could not fill thirty videos under
        a three-day cooldown — true, but a statement about library size that
        belongs in ``library_health`` and preflight, not something to discover
        by relaxing dedupe mid-render every single night.
        """
        library.validate()
        exclude = exclude or set()
        now = self._clock.now()

        used_hashes = {e.tuple_hash for e in history.entries}
        # Cooldowns judge the committed history only.
        hook_cooldown_last = _last_used(history.entries, "hook")
        caption_cooldown_last = _last_used(history.entries, "caption")
        # Weighting also sees this batch, so each pick pushes its own parts
        # down the order for the picks that follow.
        weighted = [*history.entries, *recent]
        hook_last = _last_used(weighted, "hook")
        caption_last = _last_used(weighted, "caption")
        music_last = _last_used(weighted, "music")
        body_last = _last_used(weighted, "body")

        # How many body clips this particular video gets. Chosen once, before
        # the relaxation ladder, so a pick that needs relaxing keeps the shape
        # it started with rather than quietly becoming a different structure.
        top = min(bodies_max or bodies_per_video, len(library.bodies))
        wanted = (
            bodies_per_video if top <= bodies_per_video
            else self._rng.choice(tuple(range(bodies_per_video, top + 1)))
        )

        for level in RELAXATION_ORDER:
            candidate = self._try_level(
                library=library,
                bodies_per_video=wanted,
                level=level,
                now=now,
                used_hashes=used_hashes,
                exclude=exclude,
                hook_cooldown_last=hook_cooldown_last,
                caption_cooldown_last=caption_cooldown_last,
                hook_last=hook_last,
                caption_last=caption_last,
                music_last=music_last,
                body_last=body_last,
                performance=performance,
            )
            if candidate is None:
                continue
            if level is not Relaxation.NONE:
                # SPEC §10: "Notify on any relaxation — it means the library is
                # too small for the cadence." Logged at warning so the digest
                # and the alerting path both see it.
                self._log.warning(
                    "dedupe_relaxed",
                    level=level.value,
                    hooks=len(library.hooks),
                    bodies=len(library.bodies),
                    captions=len(library.captions),
                    history_size=len(history.entries),
                )
            return SelectionOutcome(selection=candidate, relaxation=level)

        raise SelectionError(
            "no valid combination exists even with all dedupe rules relaxed; "
            f"library has {len(library.hooks)} hooks, {len(library.bodies)} bodies, "
            f"{len(library.captions)} captions, {len(library.music)} music tracks"
        )

    def _try_level(
        self,
        *,
        library: AssetLibrary,
        bodies_per_video: int,
        level: Relaxation,
        now: datetime,
        used_hashes: set[str],
        exclude: set[str],
        hook_cooldown_last: Mapping[str, datetime],
        caption_cooldown_last: Mapping[str, datetime],
        hook_last: Mapping[str, datetime],
        caption_last: Mapping[str, datetime],
        music_last: Mapping[str, datetime],
        body_last: Mapping[str, datetime],
        performance: Mapping[str, Mapping[str, float]] | None = None,
    ) -> Selection | None:
        """Attempt a pick under one relaxation level, or return None."""
        # Each level switches off exactly one more constraint than the previous.
        enforce_hook_cooldown = level is Relaxation.NONE
        enforce_caption_cooldown = level in (Relaxation.NONE, Relaxation.HOOK_COOLDOWN)
        enforce_tuple_dedupe = level is not Relaxation.TUPLE_DEDUPE

        hook_cutoff = now - timedelta(days=self._config.hook_cooldown_days)
        caption_cutoff = now - timedelta(days=self._config.caption_cooldown_days)

        hooks = list(library.hooks)
        if enforce_hook_cooldown:
            hooks = [
                h for h in hooks if hook_cooldown_last.get(h, datetime.min.replace(
                    tzinfo=now.tzinfo)) <= hook_cutoff
            ]
        captions = list(library.captions)
        if enforce_caption_cooldown:
            captions = [
                c for c in captions if caption_cooldown_last.get(
                    c, datetime.min.replace(tzinfo=now.tzinfo)) <= caption_cutoff
            ]
        if not hooks or not captions:
            return None

        hook_w = _lru_weights(hooks, hook_last, now)
        caption_w = _lru_weights(captions, caption_last, now)
        body_w = _lru_weights(library.bodies, body_last, now)
        music_w = _lru_weights(library.music, music_last, now) if library.music else []

        # Performance scales recency rather than replacing it. Multiplying
        # keeps the spread-evenly behaviour underneath: a proven clip is
        # favoured, but a proven clip used an hour ago still yields to one
        # that has not been seen for a week. Replacing the weights would let
        # a single winner run every slot until its cooldown bit.
        if performance:
            config = self._config
            for pool, weights, dimension in (
                (hooks, hook_w, "hook"),
                (captions, caption_w, "caption"),
                (list(library.bodies), body_w, "body"),
                (list(library.music), music_w, "music"),
            ):
                medians = performance.get(dimension) or {}
                if not medians or not pool:
                    continue
                boosts = performance_multipliers(
                    pool, medians,
                    config.performance_weight, config.performance_max_boost,
                )
                for index, boost in enumerate(boosts):
                    weights[index] *= boost

        for _ in range(self._max_attempts):
            hook = self._rng.weighted_choice(hooks, hook_w)
            bodies = self._pick_bodies(library.bodies, body_w, bodies_per_video)
            if bodies is None:
                return None
            music = (
                self._rng.weighted_choice(library.music, music_w)
                if library.music
                else None
            )
            # Segment choice is uniform rather than LRU-weighted: segments of
            # one track are interchangeable, and tracking recency per segment
            # would bloat history for no perceptible gain.
            music_offset = 0.0
            if music is not None:
                segments = library.segments_for(music)
                index = self._rng.choice(tuple(range(segments)))
                music_offset = library.offset_for(music, index)
            caption = self._rng.weighted_choice(captions, caption_w)

            candidate = Selection(
                hook=hook, bodies=bodies, music=music, caption=caption,
                music_offset_sec=music_offset,
            )
            digest = tuple_hash(candidate, self._config.dedupe_on)
            if digest in exclude:
                # Always enforced: two identical videos in one batch is the most
                # visible failure there is, and no relaxation level excuses it.
                continue
            if enforce_tuple_dedupe and digest in used_hashes:
                continue
            return candidate
        return None

    def _pick_bodies(
        self, pool: Sequence[str], weights: Sequence[float], n: int
    ) -> tuple[str, ...] | None:
        """Pick ``n`` distinct bodies, LRU-weighted, order preserved as picked."""
        if len(pool) < n:
            return None
        remaining = list(pool)
        remaining_w = list(weights)
        chosen: list[str] = []
        for _ in range(n):
            pick = self._rng.weighted_choice(remaining, remaining_w)
            index = remaining.index(pick)
            remaining.pop(index)
            remaining_w.pop(index)
            chosen.append(pick)
        return tuple(chosen)


def days_until_first_repeat(
    library: AssetLibrary, history: History, bodies_per_video: int, posts_per_day: int
) -> float:
    """Runway before the library is exhausted, for the weekly digest (SPEC §12)."""
    if posts_per_day <= 0:
        return float("inf")
    remaining = library.ceiling(bodies_per_video) - len(history.entries)
    return max(0.0, remaining / posts_per_day)
