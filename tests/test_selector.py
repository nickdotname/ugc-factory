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
