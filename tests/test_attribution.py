"""Joining per-post metrics back to the clips that earned them.

The join is trivial. The statistics are not, and they are what these tests
are mostly about: four clips over a fortnight is a handful of posts each, and
social metrics are wildly overdispersed. A confident ranking off two posts is
worse than no ranking, because it gets acted on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.attribution import (
    MIN_POSTS_PER_OPTION,
    PostCache,
    attribute,
    coverage,
    load_posts,
    posts_path,
    save_posts,
)
from src.errors import ValidationError
from src.models import HistoryEntry
from src.publishers.base import MetricRow, PostMetrics

NOW = datetime(2026, 8, 21, tzinfo=timezone.utc)


def post(pid: str, views: float) -> PostMetrics:
    return PostMetrics(
        post_id=pid, service="instagram", sent_at=NOW,
        metrics=(MetricRow(type="views", name="Views", value=views),),
    )


def entry(pid: str | None, hook: str = "h1", body: str = "b1",
          caption: str = "c1") -> HistoryEntry:
    return HistoryEntry(
        tuple_hash=pid or "x", timestamp=NOW, item_id=pid or "x", hook=hook,
        bodies=(body,), music=None, caption=caption, buffer_post_id=pid,
    )


class TestTheJoin:
    def test_a_clip_is_ranked_by_the_posts_it_appeared_in(self) -> None:
        posts = {f"p{i}": post(f"p{i}", 100 if i < 4 else 900) for i in range(8)}
        history = [
            entry(f"p{i}", hook="weak" if i < 4 else "strong") for i in range(8)
        ]
        report = next(r for r in attribute(history, posts) if r.dimension == "hook")
        assert [o.option for o in report.options] == ["strong", "weak"]
        assert report.ratio == pytest.approx(9.0)

    def test_a_post_with_no_metrics_contributes_nothing(self) -> None:
        """Not a zero. A video published an hour ago has no figures yet, and
        counting it as zero would punish whichever clip was in it."""
        posts = {"p1": PostMetrics(post_id="p1", service="instagram")}
        history = [entry("p1")]
        assert all(not r.options for r in attribute(history, posts))

    def test_a_render_that_never_published_is_ignored(self) -> None:
        history = [entry(None) for _ in range(6)]
        assert attribute(history, {}) == []

    def test_each_body_in_a_multi_body_cut_gets_the_credit(self) -> None:
        """The question is which clip performs, and a clip appearing across
        several combinations is exactly the evidence needed."""
        posts = {"p1": post("p1", 500)}
        history = [HistoryEntry(
            tuple_hash="t", timestamp=NOW, item_id="1", hook="h1",
            bodies=("b1", "b2"), music=None, caption="c", buffer_post_id="p1",
        )]
        report = next(r for r in attribute(history, posts) if r.dimension == "body")
        assert {o.option for o in report.options} | {i[0] for i in report.ignored} == {"b1", "b2"}


class TestStatisticalHonesty:
    def test_an_option_below_the_floor_is_not_ranked(self) -> None:
        posts = {f"p{i}": post(f"p{i}", 100) for i in range(3)}
        history = [entry(f"p{i}", hook="rare") for i in range(3)]
        report = next(r for r in attribute(history, posts) if r.dimension == "hook")
        assert report.options == ()
        assert report.ignored == (("rare", 3),)

    def test_one_option_is_not_a_comparison(self) -> None:
        posts = {f"p{i}": post(f"p{i}", 100) for i in range(6)}
        history = [entry(f"p{i}", hook="only") for i in range(6)]
        report = next(r for r in attribute(history, posts) if r.dimension == "hook")
        assert not report.rankable and report.ratio is None

    def test_the_median_resists_one_viral_post(self) -> None:
        """A mean would hand the win to whichever clip happened to be in it."""
        values = [100, 110, 120, 130, 50_000]
        posts = {f"p{i}": post(f"p{i}", v) for i, v in enumerate(values)}
        history = [entry(f"p{i}", hook="h") for i in range(len(values))]
        report = next(r for r in attribute(history, posts) if r.dimension == "hook")
        assert report.ignored == () or report.options[0].median == 120

    def test_the_range_behind_a_median_is_kept(self) -> None:
        posts = {f"p{i}": post(f"p{i}", v)
                 for i, v in enumerate([10, 20, 30, 4000])}
        history = [entry(f"p{i}", hook="h") for i in range(4)]
        report = next(r for r in attribute(history, posts) if r.dimension == "hook")
        option = report.options[0]
        assert option.worst == 10 and option.best == 4000
        assert option.spread == pytest.approx(400)

    def test_the_floor_is_more_than_a_couple_of_posts(self) -> None:
        assert MIN_POSTS_PER_OPTION >= 4


class TestCoverage:
    def test_it_reports_how_much_output_is_measured(self) -> None:
        posts = {"p1": post("p1", 10)}
        history = [entry("p1"), entry("p2"), entry(None)]
        assert coverage(history, posts) == (1, 3)


class TestCache:
    def test_it_round_trips(self, tmp_path: Path) -> None:
        path = posts_path(tmp_path)
        save_posts(path, PostCache().merged_with([post("p1", 42)]))
        assert load_posts(path).posts["p1"].value("views") == 42

    def test_merging_keeps_posts_this_fetch_did_not_return(
        self, tmp_path: Path
    ) -> None:
        """Buffer stops returning a post once it falls off the paginated
        window, but its history entry lives forever — so replacing rather
        than merging would shrink the evidence base as a campaign ages."""
        cache = PostCache().merged_with([post("old", 1), post("p2", 2)])
        merged = cache.merged_with([post("p2", 99)])
        assert merged.posts["old"].value("views") == 1
        assert merged.posts["p2"].value("views") == 99

    def test_a_missing_cache_reads_as_empty(self, tmp_path: Path) -> None:
        assert load_posts(tmp_path / "nope.json").posts == {}

    def test_a_corrupt_cache_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "posts.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_posts(path)

    def test_a_failed_save_leaves_no_temp_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.attribution.os.replace",
            lambda s, d: (_ for _ in ()).throw(OSError("disk full")),
        )
        with pytest.raises(OSError):
            save_posts(posts_path(tmp_path), PostCache().merged_with([post("p", 1)]))
        assert list(tmp_path.iterdir()) == []
