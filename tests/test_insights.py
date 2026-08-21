"""Derived findings.

The risk in an analytics panel is not a crash — it is a confident number that
is wrong. These tests mostly pin down the normalisations and the refusals.
"""

from __future__ import annotations

import pytest

from src.insights import (
    caption_diversity_finding,
    MIN_SNAPSHOTS_FOR_TREND,
    CampaignFacts,
    build,
    delivery_finding,
    engagement_mix_finding,
    limits_finding,
    platform_finding,
)


def facts(**over: object) -> CampaignFacts:
    base = dict(
        slug="c", service="instagram", rendered=100, published=50.0,
        views=5000.0, reach=4000.0, post_count=50.0, engagement_rate=5.0,
        reactions=100.0, comments=10.0, shares=20.0, saves=30.0, snapshots=6,
        reported=frozenset({"views", "reach", "postCount", "reactions",
                            "comments", "shares", "saves"}),
    )
    base.update(over)
    return CampaignFacts(**base)  # type: ignore[arg-type]


class TestNormalisation:
    def test_views_per_post_divides_by_posts_not_renders(self) -> None:
        # Dividing by renders would understate every network that publishes
        # only a fraction of what it renders — which is all of them here.
        f = facts(rendered=400, published=50.0, post_count=50.0, views=5000.0)
        assert f.views_per_post == 100.0

    def test_views_per_post_is_unknown_without_posts(self) -> None:
        assert facts(post_count=0.0).views_per_post is None

    def test_reach_multiple_reports_rewatching(self) -> None:
        assert facts(views=8000.0, reach=4000.0).reach_multiple == 2.0

    def test_reach_multiple_is_unknown_when_reach_is_not_reported(self) -> None:
        # YouTube reports no reach; showing 0 would imply nobody saw it.
        assert facts(reach=0.0).reach_multiple is None

    def test_delivery_is_published_over_rendered(self) -> None:
        assert facts(rendered=200, published=50.0).delivery == 0.25

    def test_per_thousand_views_is_unknown_with_no_views(self) -> None:
        assert facts(views=0.0).per_thousand_views(10.0) is None


class TestDelivery:
    def test_a_low_yield_is_critical(self) -> None:
        found = delivery_finding([facts(rendered=100, published=22.0)])
        assert found is not None and found.severity == "critical"
        assert "22%" in found.headline

    def test_a_healthy_yield_is_not_alarming(self) -> None:
        found = delivery_finding([facts(rendered=100, published=90.0)])
        assert found is not None and found.severity == "info"

    def test_it_totals_across_campaigns(self) -> None:
        found = delivery_finding([
            facts(slug="a", rendered=100, published=20.0),
            facts(slug="b", rendered=100, published=40.0),
        ])
        assert found is not None and "30%" in found.headline

    def test_the_worst_campaign_is_listed_first(self) -> None:
        found = delivery_finding([
            facts(slug="good", rendered=100, published=80.0),
            facts(slug="bad", rendered=100, published=10.0),
        ])
        assert found is not None and found.rows[0][0] == "bad"

    def test_nothing_rendered_yields_no_finding(self) -> None:
        assert delivery_finding([facts(rendered=0)]) is None


class TestPlatformComparison:
    def test_it_ranks_by_views_per_post(self) -> None:
        found = platform_finding([
            facts(service="tiktok", post_count=20.0, views=800.0),
            facts(service="instagram", post_count=40.0, views=6000.0),
        ])
        assert found is not None
        assert found.rows[0][0] == "instagram"
        assert "instagram" in found.headline and "tiktok" in found.headline

    def test_totals_alone_would_have_ranked_them_differently(self) -> None:
        """The whole point of normalising: more posts is not more reach."""
        many_posts_low_reach = facts(service="tiktok", post_count=100.0, views=2000.0)
        few_posts_high_reach = facts(service="youtube", post_count=10.0, views=1500.0)
        found = platform_finding([many_posts_low_reach, few_posts_high_reach])
        assert found is not None
        assert found.rows[0][0] == "youtube"   # 150/post beats 20/post
        assert many_posts_low_reach.views > few_posts_high_reach.views

    def test_it_calls_out_reach_and_engagement_disagreeing(self) -> None:
        found = platform_finding([
            facts(service="youtube", post_count=10.0, views=5000.0, engagement_rate=0.7),
            facts(service="instagram", post_count=10.0, views=1000.0, engagement_rate=6.0),
        ])
        assert found is not None and "disagree" in found.detail

    def test_one_campaign_is_not_a_comparison(self) -> None:
        assert platform_finding([facts()]) is None


class TestEngagementMix:
    def test_unreported_metrics_are_marked_not_zeroed(self) -> None:
        """A missing metric is missing. Zero would libel the network."""
        found = engagement_mix_finding([
            facts(service="youtube", reported=frozenset({"views", "reactions", "comments"}))
        ])
        assert found is not None
        assert found.rows[0][3] == "n/r" and found.rows[0][4] == "n/r"

    def test_reported_metrics_are_rates_not_counts(self) -> None:
        found = engagement_mix_finding([facts(views=10_000.0, reactions=50.0)])
        assert found is not None and found.rows[0][1] == "5.0"


class TestLimits:
    def test_clip_attribution_is_always_refused(self) -> None:
        # No sample size fixes this — the data simply is not per-post.
        rows = limits_finding([facts(snapshots=9999)]).rows
        assert any("clip" in r[0].lower() for r in rows)

    def test_thin_history_adds_a_trend_warning(self) -> None:
        rows = limits_finding([facts(snapshots=6)]).rows
        assert any("Trends" in r[0] for r in rows)

    def test_a_long_history_drops_the_trend_warning(self) -> None:
        rows = limits_finding([facts(snapshots=MIN_SNAPSHOTS_FOR_TREND)]).rows
        assert not any("Trends" in r[0] for r in rows)


class TestBuild:
    def test_the_yield_problem_leads(self) -> None:
        found = build([facts(rendered=100, published=20.0), facts(slug="b")])
        assert found[0].id == "delivery"

    def test_the_limits_are_always_included(self) -> None:
        assert build([facts()])[-1].id == "limits"

    def test_no_data_still_states_the_limits(self) -> None:
        assert [f.id for f in build([])] == ["limits"]


class TestCaptionDiversity:
    """A count of captions reads like a count of distinct things. It is not."""

    def bank(self, ask: str = 'comment "create"', n: int = 10) -> list[str]:
        return [f"opening number {i} of the set, and then {ask}" for i in range(n)]

    def test_one_ask_across_the_bank_is_flagged(self) -> None:
        found = caption_diversity_finding(self.bank())
        assert found is not None and found.severity == "warn"
        assert "same thing" in found.headline

    def test_a_varied_bank_is_not_flagged(self) -> None:
        captions = (
            self.bank('comment "create"', 4)
            + self.bank("link in bio", 4)
            + self.bank("dm me", 4)
        )
        found = caption_diversity_finding(captions)
        assert found is not None and found.severity == "info"

    def test_it_counts_distinct_asks(self) -> None:
        found = caption_diversity_finding(
            self.bank('comment "create"', 5) + self.bank("link in bio", 5)
        )
        assert found is not None
        asks = next(r for r in found.rows if r[0] == "Distinct asks")
        assert asks[1] == "2"

    def test_repeated_openings_are_reported(self) -> None:
        captions = ["the same four words here A", "the same four words here B"]
        found = caption_diversity_finding(captions)
        assert found is not None
        row = next(r for r in found.rows if r[0] == "Distinct openings")
        assert row[1] == "1" and "repeat" in row[2]

    def test_captions_with_no_ask_are_counted(self) -> None:
        found = caption_diversity_finding(["just a statement about a thing"])
        assert found is not None
        assert any(r[0] == "No recognised ask" for r in found.rows)

    def test_an_empty_bank_yields_nothing(self) -> None:
        assert caption_diversity_finding([]) is None

    def test_ask_matching_ignores_case_and_quoting(self) -> None:
        one = caption_diversity_finding(['COMMENT "Create" below'])
        two = caption_diversity_finding(["comment create below"])
        assert one is not None and two is not None
        for found in (one, two):
            asks = next(r for r in found.rows if r[0] == "Distinct asks")
            assert asks[1] == "1"

    def test_it_appears_in_the_built_findings(self) -> None:
        from src.insights import build

        ids = [f.id for f in build([], self.bank())]
        assert "captions" in ids
