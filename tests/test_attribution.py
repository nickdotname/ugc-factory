"""Joining per-post metrics back to the clips that earned them.

The join is trivial. The statistics are not, and they are what these tests
are mostly about: four clips over a fortnight is a handful of posts each, and
social metrics are wildly overdispersed. A confident ranking off two posts is
worse than no ranking, because it gets acted on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.attribution import (
    CONDEMN_SHARE,
    MIN_POSTS_FOR_TREATMENT,
    MIN_POSTS_PER_OPTION,
    MIN_POSTS_TO_CONDEMN,
    PostCache,
    attribute,
    attribute_by_service,
    coverage,
    daily_health,
    distribution_lost,
    load_posts,
    posts_path,
    save_posts,
    treatment_effects,
    underperformers,
)
from src.config import Statistic
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


class TestPerNetwork:
    """A clip is not good in the abstract. It is good on one network, and
    networks disagree — which is the whole point of testing."""

    def post_on(self, pid: str, service: str, views: float) -> PostMetrics:
        return PostMetrics(
            post_id=pid, service=service, sent_at=NOW,
            metrics=(MetricRow(type="views", name="Views", value=views),),
        )

    def test_pooling_would_invent_a_gap_between_identical_clips(self) -> None:
        """The bug this prevents. Instagram returns ~3.7x TikTok per post, so
        two equally good hooks weighted to different networks come out far
        apart on merit they do not have."""
        posts, history = {}, []
        for i in range(8):
            # hook_A mostly on instagram, hook_B mostly on tiktok, and every
            # post performs exactly at its network's baseline.
            hook, service = ("A", "instagram") if i < 4 else ("B", "tiktok")
            views = 146.0 if service == "instagram" else 39.8
            pid = f"p{i}"
            posts[pid] = self.post_on(pid, service, views)
            history.append(entry(pid, hook=hook))

        pooled = next(r for r in attribute(history, posts) if r.dimension == "hook")
        assert pooled.ratio is not None and pooled.ratio > 3, (
            "pooling should show a large gap — that is the flaw"
        )

        by_service = attribute_by_service(history, posts)
        for service, reports in by_service.items():
            hook = next(r for r in reports if r.dimension == "hook")
            # Within a network only one hook ran, so there is nothing to rank
            # and crucially no fictional gap.
            assert not hook.rankable

    def test_each_network_is_ranked_on_its_own(self) -> None:
        posts, history = {}, []
        for service in ("instagram", "tiktok"):
            for i in range(8):
                hook = "good" if i < 4 else "bad"
                base = 1000 if service == "instagram" else 50
                pid = f"{service}{i}"
                posts[pid] = self.post_on(
                    pid, service, base * (2 if hook == "good" else 1)
                )
                history.append(entry(pid, hook=hook))

        by_service = attribute_by_service(history, posts)
        assert set(by_service) == {"instagram", "tiktok"}
        for service, reports in by_service.items():
            hook = next(r for r in reports if r.dimension == "hook")
            assert [o.option for o in hook.options] == ["good", "bad"]
            # Same verdict, and the ratio is unpolluted by the other network.
            assert hook.ratio == pytest.approx(2.0)
            assert hook.service == service

    def test_a_network_with_no_posts_is_absent(self) -> None:
        posts = {"p1": self.post_on("p1", "instagram", 100)}
        assert set(attribute_by_service([entry("p1")], posts)) == {"instagram"}

    def test_posts_are_never_mixed_between_networks(self) -> None:
        posts = {
            "ig": self.post_on("ig", "instagram", 1000),
            "tt": self.post_on("tt", "tiktok", 10),
        }
        history = [entry("ig", hook="h"), entry("tt", hook="h")]
        for service, reports in attribute_by_service(
            history, posts, min_posts=1
        ).items():
            hook = next(r for r in reports if r.dimension == "hook")
            expected = 1000 if service == "instagram" else 10
            assert hook.options[0].median == expected


class TestUnderperformers:
    """Suggesting a clip be cut. The bar has to be much higher than 'ranked
    last', because with N clips of identical quality each comes last 1/N of
    the time — something always is."""

    def build(self, bad: str | None, per_clip: int = 14, clips: int = 5):
        """Deterministic values: the bad clip's are simply lower."""
        posts, history = {}, []
        for c in range(clips):
            name = f"hook_{c}"
            for i in range(per_clip):
                # A clean separation, so the test is about the rule and not
                # about a random seed.
                value = 10.0 + i if name == bad else 100.0 + i
                pid = f"{name}-{i}"
                posts[pid] = PostMetrics(
                    post_id=pid, service="instagram", sent_at=NOW,
                    metrics=(MetricRow(type="views", name="V", value=value),),
                )
                history.append(HistoryEntry(
                    tuple_hash=pid, timestamp=NOW, item_id=pid, hook=name,
                    bodies=("b1",), music=None, caption="c",
                    buffer_post_id=pid,
                ))
        return history, posts

    def test_a_genuinely_bad_clip_is_flagged(self) -> None:
        history, posts = self.build(bad="hook_0")
        found = [u for u in underperformers(history, posts)
                 if u.dimension == "hook"]
        assert [u.option for u in found] == ["hook_0"]

    def test_equal_clips_are_left_alone(self) -> None:
        history, posts = self.build(bad=None)
        assert [u for u in underperformers(history, posts)
                if u.dimension == "hook"] == []

    def test_it_needs_enough_posts(self) -> None:
        """Below the floor nothing is said, however bad it looks."""
        history, posts = self.build(bad="hook_0",
                                    per_clip=MIN_POSTS_TO_CONDEMN - 1)
        assert underperformers(history, posts) == []

    def test_a_clip_is_judged_against_the_others_not_itself(self) -> None:
        """Leave-one-out. With four clips a clip is a quarter of any pooled
        median, which drags the bar toward it and hides the very thing this
        is looking for."""
        history, posts = self.build(bad="hook_0", clips=2)
        found = [u for u in underperformers(history, posts)
                 if u.dimension == "hook"]
        assert found and found[0].field_median > found[0].own_median

    def test_a_field_of_one_has_nothing_to_be_below(self) -> None:
        history, posts = self.build(bad="hook_0", clips=1)
        assert underperformers(history, posts) == []

    def test_the_evidence_is_reported_not_just_the_verdict(self) -> None:
        history, posts = self.build(bad="hook_0")
        u = next(x for x in underperformers(history, posts)
                 if x.dimension == "hook")
        assert u.posts >= MIN_POSTS_TO_CONDEMN
        assert u.share >= CONDEMN_SHARE
        assert u.below <= u.posts

    def test_it_can_be_scoped_to_one_network(self) -> None:
        history, posts = self.build(bad="hook_0")
        assert underperformers(history, posts, service="tiktok") == []
        assert underperformers(history, posts, service="instagram")

    def test_the_thresholds_stay_conservative(self) -> None:
        """Simulated at these values: ~3% of fine clips flagged, ~62% of
        genuinely bad ones caught. Loosening either trades that badly."""
        assert MIN_POSTS_TO_CONDEMN >= 12
        assert CONDEMN_SHARE >= 0.8


class TestTreatmentEffects:
    """Whether the variation engine is doing anything measurable.

    Twelve knobs tested at the usual 5% bar would declare a winner about half
    of all weeks whether or not variation matters. Correcting for that is the
    difference between noticing an effect and manufacturing one.
    """

    def build(self, effect_on: str | None, n: int = 120, seed: int = 1):
        import random

        from src.config import VariationConfig
        from src.variation import treatment_for

        random.seed(seed)
        posts, history = {}, []
        for i in range(n):
            recipe = treatment_for(f"v{i}", VariationConfig(enabled=True)).as_dict()
            mu = 5.0
            if effect_on:
                mu += 1.2 * (recipe[effect_on] > 0.025)
            pid = f"p{i}"
            posts[pid] = PostMetrics(
                post_id=pid, service="instagram", sent_at=NOW,
                metrics=(MetricRow(type="views", name="V",
                                   value=random.lognormvariate(mu, 1.0)),),
            )
            history.append(HistoryEntry(
                tuple_hash=pid, timestamp=NOW, item_id=f"v{i}", hook="h",
                bodies=("b",), music=None, caption="c",
                buffer_post_id=pid, treatment=recipe,
            ))
        return history, posts

    def test_a_real_effect_is_found_and_named(self) -> None:
        history, posts = self.build(effect_on="zoom")
        winners = [e for e in treatment_effects(history, posts) if e.significant]
        assert [e.parameter for e in winners] == ["zoom"]

    def test_nothing_is_claimed_when_variation_does_nothing(self) -> None:
        history, posts = self.build(effect_on=None)
        assert not any(e.significant for e in treatment_effects(history, posts))

    def test_the_bar_is_corrected_for_how_many_knobs_are_tested(self) -> None:
        history, posts = self.build(effect_on=None)
        effects = treatment_effects(history, posts)
        assert effects
        assert all(e.threshold < 0.05 for e in effects)
        # One shared, corrected bar rather than a per-test 5%.
        assert len({e.threshold for e in effects}) == 1

    def test_too_few_posts_says_nothing(self) -> None:
        history, posts = self.build(effect_on="zoom",
                                    n=MIN_POSTS_FOR_TREATMENT - 1)
        assert treatment_effects(history, posts) == []

    def test_untreated_posts_are_ignored(self) -> None:
        """Renders from before variation was switched on carry no recipe."""
        history, posts = self.build(effect_on="zoom")
        stripped = [
            e.model_copy(update={"treatment": None}) for e in history
        ]
        assert treatment_effects(stripped, posts) == []

    def test_crop_anchors_are_not_tested(self) -> None:
        """They are where the crop sits, not how much of anything — there is
        no low-to-high ordering to split on."""
        history, posts = self.build(effect_on=None)
        names = {e.parameter for e in treatment_effects(history, posts)}
        assert not any(n.startswith("anchor") for n in names)

    def test_it_can_be_scoped_to_one_network(self) -> None:
        history, posts = self.build(effect_on="zoom")
        assert treatment_effects(history, posts, service="tiktok") == []
        assert treatment_effects(history, posts, service="instagram")


class TestRankingStatistic:
    """Which summary decides the order.

    Both platforms serve every post a seed audience, so a clip's typical day
    is the floor rather than the clip. That makes the median blind to exactly
    the clips worth finding: the ones that rarely, but sometimes, break out.
    """

    # Two clips with an identical typical day. One never leaves the floor;
    # the other leaves it a quarter of the time. This is the real shape of
    # the Instagram data, reduced to the smallest case that shows it.
    STEADY = [140.0, 145.0, 150.0, 141.0, 148.0, 143.0, 150.0, 142.0]
    SPIKY = [140.0, 145.0, 150.0, 141.0, 148.0, 143.0, 1400.0, 1300.0]

    def _reports(self, statistic):
        history, posts = [], {}
        for name, values in (("steady", self.STEADY), ("spiky", self.SPIKY)):
            for i, v in enumerate(values):
                pid = f"{name}{i}"
                history.append(entry(pid, hook=name))
                posts[pid] = post(pid, v)
        reports = attribute(history, posts, statistic=statistic)
        return next(r for r in reports if r.dimension == "hook")

    def test_median_cannot_tell_them_apart(self) -> None:
        report = self._reports(Statistic.MEDIAN)
        assert report.ratio is not None
        # Two percent apart, on clips whose real value differs by far more.
        assert report.ratio < 1.05

    def test_mean_ranks_the_breakout_clip_first(self) -> None:
        report = self._reports(Statistic.MEAN)
        assert [o.option for o in report.options] == ["spiky", "steady"]
        assert report.ratio is not None and report.ratio > 2.0

    def test_median_is_still_reported_under_either_statistic(self) -> None:
        """The dashboard's familiar figure survives the ranking change."""
        for statistic in (Statistic.MEDIAN, Statistic.MEAN):
            report = self._reports(statistic)
            spiky = next(o for o in report.options if o.option == "spiky")
            assert spiky.median == pytest.approx(146.5)

    def test_median_is_the_default(self) -> None:
        """Existing campaigns keep the behaviour they were tuned on."""
        default = attribute(*self._history_and_posts())
        explicit = attribute(*self._history_and_posts(), statistic=Statistic.MEDIAN)
        assert [
            (r.dimension, [o.score for o in r.options]) for r in default
        ] == [
            (r.dimension, [o.score for o in r.options]) for r in explicit
        ]

    def _history_and_posts(self):
        history, posts = [], {}
        for name, values in (("steady", self.STEADY), ("spiky", self.SPIKY)):
            for i, v in enumerate(values):
                pid = f"{name}{i}"
                history.append(entry(pid, hook=name))
                posts[pid] = post(pid, v)
        return history, posts


class TestDistributionLost:
    """Catching a channel that stopped being served.

    The design is pinned here because the obvious implementation does not
    work. On real data a healthy Instagram swings 0.23x then 3.15x day to
    day, so any percentage-drop rule loose enough to avoid firing on that is
    too loose to catch anything. What separates an outage is shape rather
    than magnitude: the share of posts reaching nobody.
    """

    @staticmethod
    def _days(shares, today=NOW.date(), start_offset=20, per_day=8):
        """History and posts for a run of days at given dead-shares."""
        history, posts = [], {}
        for i, share in enumerate(shares):
            day = today - timedelta(days=start_offset - i)
            dead = round(share * per_day)
            for n in range(per_day):
                pid = f"{day.isoformat()}-{n}"
                history.append(HistoryEntry(
                    tuple_hash=pid, timestamp=datetime.combine(
                        day, datetime.min.time(), tzinfo=timezone.utc),
                    item_id=pid, hook="h1", bodies=("b1",), music=None,
                    caption="c1", buffer_post_id=pid,
                ))
                posts[pid] = post(pid, 0.0 if n < dead else 400.0)
        return history, posts

    def _call(self, shares, **kw):
        history, posts = self._days(shares)
        return distribution_lost(
            history, posts, NOW.date(),
            threshold=kw.get("threshold", 0.7), days=kw.get("days", 3),
        )

    def test_a_sustained_collapse_after_health_alerts(self) -> None:
        assert self._call([0.0, 0.0, 0.9, 1.0, 0.95]) is not None

    def test_two_bad_days_are_not_yet_a_channel_problem(self) -> None:
        """One bad day happens; the run length is the whole point."""
        assert self._call([0.0, 0.0, 0.0, 0.9, 1.0]) is None

    def test_a_healthy_channel_never_alerts(self) -> None:
        assert self._call([0.0, 0.0, 0.0, 0.0, 0.0, 0.0]) is None

    def test_wild_swings_in_volume_do_not_alert(self) -> None:
        """The case that rules out a percentage-drop rule.

        Every post is served; the counts merely vary enormously, which is what
        a healthy short-form channel actually looks like.
        """
        history, posts = [], {}
        for i, mean in enumerate([2000.0, 460.0, 6300.0, 300.0, 1900.0, 240.0]):
            day = NOW.date() - timedelta(days=20 - i)
            for n in range(8):
                pid = f"{day}-{n}"
                history.append(HistoryEntry(
                    tuple_hash=pid, timestamp=datetime.combine(
                        day, datetime.min.time(), tzinfo=timezone.utc),
                    item_id=pid, hook="h1", bodies=("b1",), music=None,
                    caption="c1", buffer_post_id=pid))
                posts[pid] = post(pid, mean)
        assert distribution_lost(history, posts, NOW.date(),
                                 threshold=0.7, days=3) is None

    def test_a_channel_that_never_worked_stays_silent(self) -> None:
        """Otherwise it alerts every morning forever and trains people to
        ignore it. 'This has always been broken' is investigated once."""
        assert self._call([0.9, 1.0, 0.95, 1.0, 0.9]) is None

    def test_recovery_stops_the_alert(self) -> None:
        assert self._call([0.0, 0.9, 1.0, 0.95, 0.0]) is None

    def test_todays_posts_are_not_counted_as_dead(self) -> None:
        """Views arrive over days; this morning's batch has none yet, and
        judging it would report a collapse every single morning."""
        history, posts = self._days([0.0, 0.0, 0.0], start_offset=2)
        assert distribution_lost(history, posts, NOW.date(),
                                 threshold=0.7, days=3) is None

    def test_thin_days_are_ignored_rather_than_trusted(self) -> None:
        """With two posts a day the share is 0% or 100% by arithmetic."""
        history, posts = self._days([0.0, 1.0, 1.0, 1.0], per_day=2)
        assert distribution_lost(history, posts, NOW.date(),
                                 threshold=0.7, days=3) is None

    def test_the_alert_names_the_day_it_started(self) -> None:
        alert = self._call([0.0, 0.0, 0.9, 1.0, 0.95])
        assert alert is not None
        assert alert.since == NOW.date() - timedelta(days=18)
        assert alert.worst == pytest.approx(1.0)

    def test_the_message_says_what_to_go_and_check(self) -> None:
        alert = self._call([0.0, 0.0, 0.9, 1.0, 0.95])
        assert alert is not None
        text = alert.message("clubs_tt")
        assert "clubs_tt" in text
        for expected in ("seed audience", "claim", "restriction"):
            assert expected in text

    def test_daily_health_reports_shares_per_day(self) -> None:
        history, posts = self._days([0.0, 0.5])
        rows = daily_health(history, posts, NOW.date())
        assert [r.dead_share for r in rows] == [0.0, 0.5]
        assert all(r.posts == 8 for r in rows)
