"""M3 — selection, dedupe and relaxation (SPEC §10, §14).

Pure and fast: no ffmpeg, no network, no wall clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.config import DedupeDimension, SelectionConfig
from src.errors import SelectionError
from src.logging import StructuredLogger
from src.models import History, HistoryEntry, Selection
from src.ports import FrozenClock, SeededRng
from src.selector import (
    AssetLibrary,
    _lru_weights,
    Relaxation,
    Selector,
    days_until_first_repeat,
    tuple_hash,
)

NOW = datetime(2026, 8, 13, 5, 0, tzinfo=timezone.utc)


def make_library(hooks: int = 5, bodies: int = 6, music: int = 3, captions: int = 8):
    return AssetLibrary(
        hooks=tuple(f"hook_{i:02d}.mp4" for i in range(hooks)),
        bodies=tuple(f"body_{i:02d}.mp4" for i in range(bodies)),
        music=tuple(f"track_{i:02d}.mp3" for i in range(music)),
        captions=tuple(f"caption text {i}" for i in range(captions)),
    )


def make_selector(seed: int = 1234, **cfg) -> Selector:
    import io

    return Selector(
        SelectionConfig(**cfg),
        FrozenClock(NOW),
        SeededRng(seed),
        StructuredLogger({}, io.StringIO()),
    )


def entry(sel: Selection, when: datetime, dims=None) -> HistoryEntry:
    dims = dims or list(DedupeDimension)
    return HistoryEntry(
        tuple_hash=tuple_hash(sel, dims),
        timestamp=when,
        item_id="x",
        hook=sel.hook,
        bodies=sel.bodies,
        music=sel.music,
        caption=sel.caption,
    )


class TestTupleHash:
    def test_same_tuple_same_hash(self) -> None:
        a = Selection(hook="h", bodies=("b",), music="m", caption="c")
        b = Selection(hook="h", bodies=("b",), music="m", caption="c")
        assert tuple_hash(a, list(DedupeDimension)) == tuple_hash(b, list(DedupeDimension))

    def test_different_tuple_different_hash(self) -> None:
        a = Selection(hook="h1", bodies=("b",), music="m", caption="c")
        b = Selection(hook="h2", bodies=("b",), music="m", caption="c")
        assert tuple_hash(a, list(DedupeDimension)) != tuple_hash(b, list(DedupeDimension))

    def test_body_order_does_not_change_hash(self) -> None:
        """Same two bodies in either order is the same combination."""
        a = Selection(hook="h", bodies=("b1", "b2"), music="m", caption="c")
        b = Selection(hook="h", bodies=("b2", "b1"), music="m", caption="c")
        assert tuple_hash(a, list(DedupeDimension)) == tuple_hash(b, list(DedupeDimension))

    def test_only_configured_dimensions_matter(self) -> None:
        """Deduping on [hook] alone ignores a music difference."""
        a = Selection(hook="h", bodies=("b",), music="m1", caption="c")
        b = Selection(hook="h", bodies=("b",), music="m2", caption="c")
        dims = [DedupeDimension.HOOK]
        assert tuple_hash(a, dims) == tuple_hash(b, dims)
        assert tuple_hash(a, list(DedupeDimension)) != tuple_hash(b, list(DedupeDimension))

    def test_no_boundary_collision_between_fields(self) -> None:
        a = Selection(hook="ab", bodies=("c",), music=None, caption="x")
        b = Selection(hook="a", bodies=("bc",), music=None, caption="x")
        assert tuple_hash(a, list(DedupeDimension)) != tuple_hash(b, list(DedupeDimension))


class TestDeterminism:
    """SPEC §2.2 — a fixed seed must produce identical picks."""

    def test_same_seed_same_picks(self) -> None:
        lib, hist = make_library(), History()
        a = make_selector(seed=7).select_batch(lib, hist, 10, 1)
        b = make_selector(seed=7).select_batch(lib, hist, 10, 1)
        assert [o.selection for o in a] == [o.selection for o in b]

    def test_different_seed_different_picks(self) -> None:
        lib, hist = make_library(), History()
        a = make_selector(seed=7).select_batch(lib, hist, 10, 1)
        b = make_selector(seed=8).select_batch(lib, hist, 10, 1)
        assert [o.selection for o in a] != [o.selection for o in b]


class TestBatchUniqueness:
    def test_batch_has_no_duplicate_tuples(self) -> None:
        """SPEC §14 — render 30 videos, zero duplicate tuples."""
        outcomes = make_selector().select_batch(make_library(), History(), 30, 1)
        hashes = [tuple_hash(o.selection, list(DedupeDimension)) for o in outcomes]
        assert len(set(hashes)) == 30

    def test_batch_avoids_history(self) -> None:
        lib = make_library()
        first = make_selector(seed=1).select_batch(lib, History(), 20, 1)
        history = History(entries=[entry(o.selection, NOW - timedelta(days=30))
                                   for o in first])
        second = make_selector(seed=2).select_batch(lib, history, 20, 1)
        used = {e.tuple_hash for e in history.entries}
        for o in second:
            assert tuple_hash(o.selection, list(DedupeDimension)) not in used
            assert o.relaxation is Relaxation.NONE

    def test_multi_body_selection_picks_distinct_bodies(self) -> None:
        outcomes = make_selector().select_batch(make_library(), History(), 10, 3)
        for o in outcomes:
            assert len(o.selection.bodies) == 3
            assert len(set(o.selection.bodies)) == 3


class TestCooldowns:
    def test_hook_within_cooldown_is_not_reused(self) -> None:
        lib = AssetLibrary(
            hooks=("hot.mp4", "cold.mp4"),
            bodies=("b1.mp4", "b2.mp4"),
            music=(),
            captions=("c1", "c2", "c3", "c4"),
        )
        # "hot" was used yesterday; cooldown is 3 days.
        history = History(entries=[
            entry(Selection(hook="hot.mp4", bodies=("b1.mp4",), music=None, caption="c1"),
                  NOW - timedelta(days=1))
        ])
        sel = make_selector(hook_cooldown_days=3, caption_cooldown_days=0)
        for _ in range(15):
            out = sel.select_one(lib, history, 1)
            assert out.selection.hook == "cold.mp4"
            assert out.relaxation is Relaxation.NONE

    def test_hook_past_cooldown_is_available_again(self) -> None:
        lib = AssetLibrary(
            hooks=("only.mp4",), bodies=("b1.mp4",), music=(),
            captions=("c1", "c2"),
        )
        history = History(entries=[
            entry(Selection(hook="only.mp4", bodies=("b1.mp4",), music=None, caption="c1"),
                  NOW - timedelta(days=10))
        ])
        out = make_selector(hook_cooldown_days=3, caption_cooldown_days=0).select_one(
            lib, history, 1
        )
        assert out.relaxation is Relaxation.NONE

    def test_caption_within_cooldown_is_not_reused(self) -> None:
        lib = AssetLibrary(
            hooks=("h1.mp4", "h2.mp4"), bodies=("b1.mp4",), music=(),
            captions=("recent", "stale"),
        )
        history = History(entries=[
            entry(Selection(hook="h1.mp4", bodies=("b1.mp4",), music=None,
                            caption="recent"), NOW - timedelta(days=2))
        ])
        sel = make_selector(hook_cooldown_days=0, caption_cooldown_days=14)
        for _ in range(15):
            assert sel.select_one(lib, history, 1).selection.caption == "stale"


class TestRelaxationLadder:
    """SPEC §10/§14 — relax in documented order and report it."""

    def test_relaxes_hook_cooldown_first(self) -> None:
        # One hook, used yesterday, cooldown 3 days -> hook cooldown must give.
        lib = AssetLibrary(
            hooks=("only.mp4",), bodies=("b1.mp4",), music=(),
            captions=("c1", "c2", "c3"),
        )
        history = History(entries=[
            entry(Selection(hook="only.mp4", bodies=("b1.mp4",), music=None,
                            caption="c1"), NOW - timedelta(days=1))
        ])
        out = make_selector(hook_cooldown_days=3, caption_cooldown_days=0).select_one(
            lib, history, 1
        )
        assert out.relaxation is Relaxation.HOOK_COOLDOWN

    def test_relaxes_caption_cooldown_second(self) -> None:
        # Single hook and single caption, both recently used.
        lib = AssetLibrary(
            hooks=("only.mp4",), bodies=("b1.mp4", "b2.mp4"), music=(),
            captions=("c1",),
        )
        history = History(entries=[
            entry(Selection(hook="only.mp4", bodies=("b1.mp4",), music=None,
                            caption="c1"), NOW - timedelta(days=1))
        ])
        out = make_selector(hook_cooldown_days=3, caption_cooldown_days=14).select_one(
            lib, history, 1
        )
        # b2 is still free, so tuple dedupe need not give — only the cooldowns.
        assert out.relaxation is Relaxation.CAPTION_COOLDOWN
        assert out.selection.bodies == ("b2.mp4",)

    def test_relaxes_tuple_dedupe_last(self) -> None:
        """Every combination used: only then may an exact repeat be emitted."""
        lib = AssetLibrary(
            hooks=("h.mp4",), bodies=("b.mp4",), music=(), captions=("c",),
        )
        only = Selection(hook="h.mp4", bodies=("b.mp4",), music=None, caption="c")
        history = History(entries=[entry(only, NOW - timedelta(days=1))])
        out = make_selector(hook_cooldown_days=3, caption_cooldown_days=14).select_one(
            lib, history, 1
        )
        assert out.relaxation is Relaxation.TUPLE_DEDUPE
        assert out.selection == only

    def test_relaxation_is_logged_for_alerting(self) -> None:
        """SPEC §10 — 'Notify on any relaxation'."""
        import io

        stream = io.StringIO()
        sel = Selector(
            SelectionConfig(hook_cooldown_days=3, caption_cooldown_days=14),
            FrozenClock(NOW),
            SeededRng(1),
            StructuredLogger({}, stream),
        )
        lib = AssetLibrary(hooks=("h.mp4",), bodies=("b.mp4",), music=(), captions=("c",))
        only = Selection(hook="h.mp4", bodies=("b.mp4",), music=None, caption="c")
        sel.select_one(lib, History(entries=[entry(only, NOW - timedelta(days=1))]), 1)
        assert "dedupe_relaxed" in stream.getvalue()

    def test_no_relaxation_logged_when_library_is_healthy(self) -> None:
        import io

        stream = io.StringIO()
        sel = Selector(
            SelectionConfig(), FrozenClock(NOW), SeededRng(1),
            StructuredLogger({}, stream),
        )
        sel.select_batch(make_library(), History(), 5, 1)
        assert "dedupe_relaxed" not in stream.getvalue()


class TestLruWeighting:
    def test_never_used_assets_are_reached_quickly(self) -> None:
        """SPEC §7 — drop a file in and it is live next render."""
        lib = AssetLibrary(
            hooks=tuple(f"old_{i}.mp4" for i in range(5)) + ("brand_new.mp4",),
            bodies=("b.mp4",), music=(),
            captions=tuple(f"c{i}" for i in range(10)),
        )
        history = History(entries=[
            entry(Selection(hook=f"old_{i}", bodies=("b.mp4",), music=None,
                            caption=f"c{i}"), NOW - timedelta(days=1))
            for i in range(5)
        ])
        sel = make_selector(seed=3, hook_cooldown_days=0, caption_cooldown_days=0)
        picks = [sel.select_one(lib, history, 1).selection.hook for _ in range(30)]
        assert "brand_new.mp4" in picks

    def test_recently_used_assets_are_deprioritised(self) -> None:
        """Uniform random would pick ~50/50; LRU must favour the older asset."""
        lib = AssetLibrary(
            hooks=("fresh.mp4", "ancient.mp4"), bodies=("b.mp4",), music=(),
            captions=tuple(f"c{i}" for i in range(50)),
        )
        history = History(entries=[
            entry(Selection(hook="fresh.mp4", bodies=("b.mp4",), music=None,
                            caption="c0"), NOW - timedelta(days=1)),
            entry(Selection(hook="ancient.mp4", bodies=("b.mp4",), music=None,
                            caption="c1"), NOW - timedelta(days=120)),
        ])
        sel = make_selector(seed=11, hook_cooldown_days=0, caption_cooldown_days=0)
        picks = [sel.select_one(lib, history, 1).selection.hook for _ in range(100)]
        assert picks.count("ancient.mp4") > picks.count("fresh.mp4")


class TestLibraryValidation:
    def test_empty_hooks_is_a_selection_error(self) -> None:
        lib = AssetLibrary(hooks=(), bodies=("b",), music=(), captions=("c",))
        with pytest.raises(SelectionError, match="hooks"):
            make_selector().select_one(lib, History(), 1)

    def test_empty_captions_is_a_selection_error(self) -> None:
        lib = AssetLibrary(hooks=("h",), bodies=("b",), music=(), captions=())
        with pytest.raises(SelectionError, match="captions"):
            make_selector().select_one(lib, History(), 1)

    def test_too_few_bodies_for_bodies_per_video(self) -> None:
        lib = AssetLibrary(hooks=("h",), bodies=("b1", "b2"), music=(), captions=("c",))
        with pytest.raises(SelectionError, match="zero combinations"):
            make_selector().select_batch(lib, History(), 1, 5)

    def test_music_is_optional(self) -> None:
        lib = AssetLibrary(hooks=("h",), bodies=("b",), music=(), captions=("c1", "c2"))
        assert make_selector().select_one(lib, History(), 1).selection.music is None


class TestCeilingAndRunway:
    def test_ceiling_multiplies_the_dimensions(self) -> None:
        lib = make_library(hooks=5, bodies=6, music=3, captions=8)
        assert lib.ceiling(1) == 5 * 6 * 3 * 8

    def test_ceiling_uses_combinations_for_multi_body(self) -> None:
        lib = make_library(hooks=2, bodies=4, music=1, captions=1)
        assert lib.ceiling(2) == 2 * 6 * 1 * 1  # C(4,2) == 6

    def test_ceiling_treats_no_music_as_one_option(self) -> None:
        lib = AssetLibrary(hooks=("h",), bodies=("b",), music=(), captions=("c1", "c2"))
        assert lib.ceiling(1) == 2

    def test_runway_reports_days_until_first_repeat(self) -> None:
        lib = make_library(hooks=5, bodies=6, music=3, captions=8)  # 720 combos
        assert days_until_first_repeat(lib, History(), 1, 6) == 120.0

    def test_runway_accounts_for_history(self) -> None:
        lib = make_library(hooks=5, bodies=6, music=3, captions=8)
        hist = History(entries=[
            entry(Selection(hook=f"h{i}", bodies=("b",), music=None, caption=f"c{i}"),
                  NOW) for i in range(600)
        ])
        assert days_until_first_repeat(lib, hist, 1, 6) == 20.0

    def test_ceiling_is_logged_each_render(self) -> None:
        """SPEC §10 — log the combinatorial ceiling every render."""
        import io

        stream = io.StringIO()
        sel = Selector(SelectionConfig(), FrozenClock(NOW), SeededRng(1),
                       StructuredLogger({}, stream))
        sel.select_batch(make_library(), History(), 3, 1)
        assert "combinatorial_ceiling" in stream.getvalue()


class TestMusicSegments:
    """Whole songs cut into beds, rather than pre-clipped snippets."""

    def lib_with_durations(self, seconds: float = 180.0, segment: float = 15.0):
        return AssetLibrary(
            hooks=("h1.mp4", "h2.mp4"),
            bodies=("b1.mp4", "b2.mp4"),
            music=("song_a.mp3", "song_b.mp3"),
            captions=tuple(f"c{i}" for i in range(6)),
            music_durations={"song_a.mp3": seconds, "song_b.mp3": seconds},
            music_segment_sec=segment,
        )

    def test_a_long_track_yields_many_segments(self) -> None:
        lib = self.lib_with_durations(180.0, 15.0)
        assert lib.segments_for("song_a.mp3") == 12

    def test_unknown_duration_degrades_to_one_segment(self) -> None:
        """No probe data must still work — just always from 0:00."""
        lib = AssetLibrary(hooks=("h",), bodies=("b",), music=("m.mp3",),
                           captions=("c",))
        assert lib.segments_for("m.mp3") == 1
        assert lib.offset_for("m.mp3", 0) == 0.0

    def test_track_shorter_than_one_segment_yields_one(self) -> None:
        lib = self.lib_with_durations(8.0, 15.0)
        assert lib.segments_for("song_a.mp3") == 1

    def test_intro_skip_shifts_offsets(self) -> None:
        lib = AssetLibrary(
            hooks=("h",), bodies=("b",), music=("m.mp3",), captions=("c",),
            music_durations={"m.mp3": 100.0},
            music_segment_sec=10.0, music_skip_intro_sec=20.0,
        )
        assert lib.offset_for("m.mp3", 0) == 20.0
        assert lib.segments_for("m.mp3") == 8   # (100-20)/10

    def test_ceiling_counts_segments_not_tracks(self) -> None:
        """3 songs x 12 segments is 36 beds, not 3 — the point of the feature."""
        lib = AssetLibrary(
            hooks=("h",), bodies=("b",), captions=("c",),
            music=("a.mp3", "b.mp3", "c.mp3"),
            music_durations={"a.mp3": 180.0, "b.mp3": 180.0, "c.mp3": 180.0},
            music_segment_sec=15.0,
        )
        assert lib.total_music_options() == 36
        assert lib.ceiling(1) == 36

    def test_selection_carries_a_quantised_offset(self) -> None:
        lib = self.lib_with_durations()
        for _ in range(20):
            out = make_selector(seed=5).select_one(lib, History(), 1)
            offset = out.selection.music_offset_sec
            assert offset % 15.0 == 0, "offsets must snap to the grid"
            assert 0 <= offset < 180.0

    def test_offsets_actually_vary_across_a_batch(self) -> None:
        outcomes = make_selector(seed=9).select_batch(
            self.lib_with_durations(), History(), 20, 1
        )
        offsets = {o.selection.music_offset_sec for o in outcomes}
        assert len(offsets) > 1, "every video got the same bed"

    def test_same_track_different_offset_is_not_a_duplicate(self) -> None:
        """Two beds cut from one song are different content, not a repeat."""
        a = Selection(hook="h", bodies=("b",), music="m.mp3", caption="c",
                      music_offset_sec=0.0)
        b = Selection(hook="h", bodies=("b",), music="m.mp3", caption="c",
                      music_offset_sec=30.0)
        dims = list(DedupeDimension)
        assert tuple_hash(a, dims) != tuple_hash(b, dims)

    def test_identical_offsets_still_collide(self) -> None:
        a = Selection(hook="h", bodies=("b",), music="m.mp3", caption="c",
                      music_offset_sec=30.0)
        b = Selection(hook="h", bodies=("b",), music="m.mp3", caption="c",
                      music_offset_sec=30.0)
        dims = list(DedupeDimension)
        assert tuple_hash(a, dims) == tuple_hash(b, dims)

    def test_offsets_are_deterministic_under_a_fixed_seed(self) -> None:
        lib = self.lib_with_durations()
        a = make_selector(seed=3).select_batch(lib, History(), 10, 1)
        b = make_selector(seed=3).select_batch(lib, History(), 10, 1)
        assert [o.selection.music_offset_sec for o in a] == \
               [o.selection.music_offset_sec for o in b]

    def test_no_music_means_no_offset(self) -> None:
        lib = AssetLibrary(hooks=("h",), bodies=("b",), music=(),
                           captions=("c1", "c2"))
        out = make_selector().select_one(lib, History(), 1)
        assert out.selection.music is None
        assert out.selection.music_offset_sec == 0.0


class TestWithinBatchRecency:
    """The batch must not pick as if none of its own choices had happened.

    Before this, ``history`` did not change while a batch was built, so every
    pick in a night saw identical last-used data. Whichever clip started the
    evening least-recently-used stayed the heaviest-weighted choice for the
    whole batch and the night clustered on it — the exact failure LRU
    weighting exists to prevent.
    """

    def library(self, bodies: int = 4) -> AssetLibrary:
        return AssetLibrary(
            hooks=("h1.mp4", "h2.mp4", "h3.mp4"),
            bodies=tuple(f"b{i}.mp4" for i in range(bodies)),
            music=(),
            captions=tuple(f"c{i}" for i in range(40)),
        )

    def test_a_batch_spreads_across_the_pool(self) -> None:
        sel = make_selector(seed=7, hook_cooldown_days=0, caption_cooldown_days=0)
        outcomes = sel.select_batch(self.library(), History(), 8, 1)
        used = {o.selection.bodies[0] for o in outcomes}
        # Eight picks over four bodies must touch every one of them.
        assert used == set(self.library().bodies)

    def test_no_body_dominates_a_batch(self) -> None:
        from collections import Counter

        sel = make_selector(seed=3, hook_cooldown_days=0, caption_cooldown_days=0)
        outcomes = sel.select_batch(self.library(), History(), 12, 1)
        counts = Counter(o.selection.bodies[0] for o in outcomes)
        # An even split is 3 each. Allow slack for rejection sampling, but a
        # run of the old behaviour regularly put 6+ on one clip.
        assert max(counts.values()) <= 5, counts

    def test_the_batch_is_still_deterministic(self) -> None:
        """Same seed, same history, same picks — the acceptance tests rely on it."""
        first = make_selector(seed=99).select_batch(self.library(), History(), 6, 1)
        second = make_selector(seed=99).select_batch(self.library(), History(), 6, 1)
        assert [o.selection for o in first] == [o.selection for o in second]

    def test_cooldowns_are_not_applied_inside_a_batch(self) -> None:
        """Deliberate: a cooldown is a claim about library size, not a
        within-render rule.

        Three hooks cannot fill twelve videos under a 3-day cooldown. Enforcing
        it inside the batch would relax dedupe on every render of every night
        and bury the signal; ``library_health`` and preflight are where a
        too-small library is reported.
        """
        sel = make_selector(seed=5, hook_cooldown_days=3, caption_cooldown_days=14)
        outcomes = sel.select_batch(self.library(), History(), 12, 1)
        assert all(o.relaxation is Relaxation.NONE for o in outcomes)

    def test_history_is_not_mutated_by_selection(self) -> None:
        """Picks are not committed history — the caller writes that after the
        videos actually render."""
        history = History()
        make_selector(seed=1).select_batch(self.library(), history, 5, 1)
        assert history.entries == []


class TestRankWeighting:
    def test_never_used_outranks_everything(self) -> None:
        weights = _lru_weights(
            ("used", "fresh"),
            {"used": NOW - timedelta(days=1)},
            NOW,
        )
        assert weights[1] > weights[0]

    def test_order_is_by_recency_not_elapsed_time(self) -> None:
        """Scale-free: a microsecond apart ranks the same as a month apart.

        This is the whole point — within one batch every pick shares a moment,
        and an elapsed-days formula rounded them all to the same weight.
        """
        close = _lru_weights(
            ("a", "b"),
            {"a": NOW - timedelta(microseconds=2), "b": NOW - timedelta(microseconds=1)},
            NOW,
        )
        far = _lru_weights(
            ("a", "b"),
            {"a": NOW - timedelta(days=60), "b": NOW - timedelta(days=1)},
            NOW,
        )
        assert close == far
        assert close[0] > close[1]  # 'a' is older in both

    def test_the_most_recent_asset_stays_reachable(self) -> None:
        """Weight 0 would ban it outright; that is what cooldowns are for."""
        weights = _lru_weights(
            ("a", "b", "c"),
            {"a": NOW - timedelta(days=3), "b": NOW - timedelta(days=2),
             "c": NOW - timedelta(days=1)},
            NOW,
        )
        assert min(weights) >= 1.0

    def test_an_empty_pool_is_not_an_error(self) -> None:
        assert _lru_weights((), {}, NOW) == []
