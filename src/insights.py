"""Connections between the data already on disk.

Responsibility: derive what can honestly be concluded from ``history.json``,
``metrics.json`` and ``queue.json`` — and be equally explicit about what cannot.

Three facts about this data shape everything here:

**Metrics are channel aggregates, not per-post.** Buffer's
``aggregatedPostMetrics`` returns totals for a window. Nothing ties a view to a
video, so no amount of arithmetic attributes performance to a clip. Any panel
claiming "hook_03 is your best hook" from this data would be inventing it.

**There are very few snapshots.** Six daily points is not a trend. Correlation
coefficients over six observations are noise with a decimal point, so this
module refuses to compute them and says why.

**But the cross-platform comparison is unusually strong.** The campaigns post
*the same clips with the same captions* to three networks, which is a natural
experiment: content is held constant by design, and each side aggregates
~145 posts. Differences between platforms are therefore about the platforms,
not about the content — the one genuinely robust comparison available.

Everything is normalised per post before comparison. Raw totals mostly measure
how many times each channel was posted to, which is a fact about configuration
rather than about performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: Below this share of renders reaching an audience, the pipeline is mostly
#: producing videos nobody sees, which outranks any performance question.
DELIVERY_ALARM = 0.60

#: Fewer snapshots than this and a time series is not worth plotting, let alone
#: correlating.
MIN_SNAPSHOTS_FOR_TREND = 14


@dataclass(frozen=True)
class Finding:
    """One conclusion, with the numbers that produced it."""

    id: str
    severity: str  # "critical" | "warn" | "info"
    headline: str
    detail: str
    rows: tuple[tuple[str, ...], ...] = ()
    columns: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "headline": self.headline,
            "detail": self.detail,
            "columns": list(self.columns),
            "rows": [list(r) for r in self.rows],
        }


@dataclass
class CampaignFacts:
    """Everything one campaign contributes, already reduced to scalars."""

    slug: str
    service: str
    rendered: int
    published: float
    views: float
    reach: float
    post_count: float
    engagement_rate: float
    reactions: float
    comments: float
    shares: float
    saves: float
    snapshots: int
    reported: frozenset[str] = field(default_factory=frozenset)

    @property
    def delivery(self) -> float | None:
        """Share of rendered videos that actually published."""
        if not self.rendered:
            return None
        return self.published / self.rendered

    @property
    def views_per_post(self) -> float | None:
        if self.post_count <= 0:
            return None
        return self.views / self.post_count

    @property
    def reach_multiple(self) -> float | None:
        """Views per person reached — a rewatch signal, not a reach figure."""
        if self.reach <= 0:
            return None
        return self.views / self.reach

    def per_thousand_views(self, value: float) -> float | None:
        if self.views <= 0:
            return None
        return value / self.views * 1000.0


def _fmt(value: float | None, suffix: str = "", digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def delivery_finding(facts: list[CampaignFacts]) -> Finding | None:
    """Rendered against published — the pipeline's actual yield.

    This leads because it bounds everything else. A clip that never publishes
    has no performance to analyse, and a runway calculated from renders is
    measuring consumption rather than exposure.
    """
    usable = [f for f in facts if f.rendered and f.published is not None]
    if not usable:
        return None

    rendered = sum(f.rendered for f in usable)
    published = sum(f.published for f in usable)
    if rendered <= 0:
        return None
    share = published / rendered

    rows = tuple(
        (
            f.slug,
            f.service,
            f"{f.rendered:,}",
            f"{f.published:,.0f}",
            _fmt((f.delivery or 0) * 100, "%", 0),
        )
        for f in sorted(usable, key=lambda f: f.delivery or 0)
    )

    severity = "critical" if share < DELIVERY_ALARM else "info"
    lost = rendered - published
    detail = (
        f"{rendered:,} videos were rendered and {published:,.0f} reached a "
        f"network — {lost:,.0f} never published. Rendering outruns what the "
        f"channels actually publish, and the render job replaces queue.json "
        f"wholesale each night, so anything not yet pushed is discarded rather "
        f"than carried forward. Every discarded render still consumed a unique "
        f"combination from history, so the library's runway is being spent "
        f"roughly {rendered / max(1.0, published):.1f}× faster than content is "
        f"being seen."
    )
    if share >= DELIVERY_ALARM:
        detail = (
            f"{published:,.0f} of {rendered:,} rendered videos published. "
            f"Renders not pushed before the next night's batch are discarded, "
            f"so the gap is content produced and thrown away."
        )

    return Finding(
        id="delivery",
        severity=severity,
        headline=f"{share * 100:.0f}% of rendered videos actually published",
        detail=detail,
        columns=("Campaign", "Network", "Rendered", "Published", "Delivered"),
        rows=rows,
    )


def platform_finding(facts: list[CampaignFacts]) -> Finding | None:
    """Same clips, same captions, three networks — normalised per post.

    Robust precisely because the content is identical across the three by
    design. Totals are not comparable (they mostly reflect how often each
    channel was posted to); per-post figures are.
    """
    usable = [f for f in facts if f.views_per_post is not None]
    if len(usable) < 2:
        return None

    ranked = sorted(usable, key=lambda f: f.views_per_post or 0, reverse=True)
    best, worst = ranked[0], ranked[-1]

    rows = tuple(
        (
            f.service,
            f"{f.post_count:,.0f}",
            _fmt(f.views_per_post, "", 1),
            _fmt(f.engagement_rate, "%", 2),
            _fmt(f.reach_multiple, "×", 2),
        )
        for f in ranked
    )

    ratio = (best.views_per_post or 0) / max(0.01, worst.views_per_post or 0.01)
    detail = (
        f"{best.service} returns {_fmt(best.views_per_post)} views per post "
        f"against {worst.service}'s {_fmt(worst.views_per_post)} — {ratio:.1f}× "
        f"the reach for identical videos. Because the clips and captions are "
        f"shared, the difference is the network, not the content."
    )

    # The interesting tension is when reach and engagement disagree.
    by_engagement = sorted(usable, key=lambda f: f.engagement_rate, reverse=True)
    if by_engagement[0].service != best.service:
        detail += (
            f" Note they disagree: {by_engagement[0].service} has the highest "
            f"engagement rate ({by_engagement[0].engagement_rate:.2f}%) while "
            f"{best.service} has the widest reach. Volume and response are not "
            f"the same audience behaviour, and which matters depends on whether "
            f"you are selling or growing."
        )

    return Finding(
        id="platform",
        severity="info",
        headline=f"{best.service} reaches {ratio:.1f}× further per post than {worst.service}",
        detail=detail,
        columns=("Network", "Posts", "Views / post", "Eng. rate", "Views / reach"),
        rows=rows,
    )


def engagement_mix_finding(facts: list[CampaignFacts]) -> Finding | None:
    """What the audience does per 1,000 views, network by network.

    Rates rather than counts, so a channel with more posts does not look more
    engaging simply for being posted to more often.
    """
    usable = [f for f in facts if f.views > 0]
    if not usable:
        return None

    rows = tuple(
        (
            f.service,
            _fmt(f.per_thousand_views(f.reactions), "", 1),
            _fmt(f.per_thousand_views(f.comments), "", 2),
            _fmt(f.per_thousand_views(f.shares), "", 2) if "shares" in f.reported else "n/r",
            _fmt(f.per_thousand_views(f.saves), "", 2) if "saves" in f.reported else "n/r",
        )
        for f in sorted(usable, key=lambda f: f.per_thousand_views(f.reactions) or 0,
                        reverse=True)
    )
    return Finding(
        id="engagement_mix",
        severity="info",
        headline="What viewers do, per 1,000 views",
        detail=(
            "Normalised so a network posted to more often does not look more "
            "engaging for that reason alone. 'n/r' means the network does not "
            "report that metric at all — it is missing, not zero, and treating "
            "it as zero would drag that network's apparent engagement down."
        ),
        columns=("Network", "Reactions", "Comments", "Shares", "Saves"),
        rows=rows,
    )


#: Ways a caption asks for something. Deliberately a list of shapes rather
#: than exact strings — the point is to tell two *kinds* of ask apart, not to
#: parse English.
CTA_PATTERNS: tuple[tuple[str, str], ...] = (
    (r'comment\s+"?[\w\']+"?', "comment a keyword"),
    (r"\blink in bio\b", "link in bio"),
    (r"\bdm (?:me|us)\b", "DM"),
    (r"\b(?:tap|click|check) the link\b", "tap the link"),
    (r"\bsign up\b", "sign up"),
    (r"\bsave this\b", "save this"),
    (r"\bsend this to\b", "send to a friend"),
    (r"\bfollow for\b", "follow for more"),
    (r"\bjoin\b", "join"),
)

#: Above this share of the bank, one phrasing is not a majority — it is the
#: only one, and there is nothing to compare it against.
CTA_DOMINANCE = 0.8


def _ctas(caption: str) -> set[str]:
    import re

    return {
        label for pattern, label in CTA_PATTERNS
        if re.search(pattern, caption, re.IGNORECASE)
    }


def caption_diversity_finding(captions: Sequence[str]) -> Finding | None:
    """What the caption bank actually varies on, beyond how many there are.

    A count of descriptions reads like a count of distinct things, and it is
    not. Twenty-five captions that all end in the same ask are one ask tested
    twenty-five times — and the ask is the part a viewer is meant to act on,
    so it is the most valuable thing in the bank to vary and the easiest to
    forget to.
    """
    import re
    from collections import Counter

    if not captions:
        return None

    openings = Counter(
        " ".join(c.split()[:4]).lower().strip(",.") for c in captions
    )
    asks = Counter(ask for c in captions for ask in _ctas(c))
    without = sum(1 for c in captions if not _ctas(c))
    lengths = [len(c) for c in captions]

    rows = [
        ("Captions", f"{len(captions)}", ""),
        (
            "Distinct openings",
            f"{len(openings)}",
            "the first words carry search and the scroll-stop"
            if len(openings) == len(captions)
            else f"{len(captions) - len(openings)} repeat another caption's opening",
        ),
        (
            "Distinct asks",
            f"{len(asks)}",
            ", ".join(f"{label} x{n}" for label, n in asks.most_common(4))
            or "none recognised",
        ),
        (
            "Length",
            f"{min(lengths)}–{max(lengths)}",
            "characters",
        ),
    ]
    if without:
        rows.append(
            ("No recognised ask", f"{without}", "nothing for a viewer to act on")
        )

    severity, headline, detail = "info", "Caption bank", ""
    top = asks.most_common(1)
    if top and top[0][1] >= len(captions) * CTA_DOMINANCE:
        label, count = top[0]
        severity = "warn"
        headline = f'Every caption asks the same thing: "{label}"'
        detail = (
            f"{count} of {len(captions)} captions use it. The ask is the part a "
            f"viewer is meant to act on, which makes it the highest-leverage "
            f"thing in the bank to vary — and with one phrasing there is "
            f"nothing to compare it against, so a weak ask stays invisible. "
            f"Captions are text: three more asks is an afternoon, not a shoot."
        )
    else:
        headline = f"{len(openings)} openings and {len(asks)} asks across {len(captions)} captions"
        detail = (
            "A count of captions reads like a count of distinct things. These "
            "are the dimensions that actually differ."
        )

    return Finding(
        id="captions",
        severity=severity,
        headline=headline,
        detail=detail,
        columns=("Dimension", "Count", "Note"),
        rows=tuple(rows),
    )


def attribution_finding(
    by_service: Mapping[str, Sequence[Any]],
    matched: int,
    rendered: int,
    metric: str = "views",
) -> Finding | None:
    """Which clip earns the most, per network.

    Always per network. Instagram returns roughly 3.7x TikTok per post on
    these accounts, so a pooled median mostly measures which platform a clip
    happened to run on — two identical hooks weighted to different networks
    come out 3.7x apart, which is fiction that would get acted on. Ranking
    within a network also removes the bias for free: everything compared
    shares a baseline, so no index or normalisation is needed.

    A clip is not good in the abstract anyway. It is good on TikTok or good on
    Shorts, and those can disagree — which is the whole point of testing.
    """
    rows: list[tuple[str, ...]] = []
    leaders: list[tuple[str, Any, Any, float]] = []
    waiting: list[tuple[str, str, str]] = []

    for service, reports in sorted(by_service.items()):
        for report in reports:
            if not report.rankable:
                if report.ignored:
                    waiting.append((
                        service, report.dimension,
                        ", ".join(str(c) for _, c in report.ignored[:6]),
                    ))
                continue
            for option in report.options:
                rows.append((
                    service,
                    report.dimension,
                    option.option,
                    f"{option.median:,.0f}",
                    str(option.posts),
                    f"{option.worst:,.0f}–{option.best:,.0f}",
                ))
            best, worst = report.options[0], report.options[-1]
            if worst.median:
                leaders.append(
                    (service, report.dimension, best, best.median / worst.median)
                )

    if not rows:
        if not waiting:
            return None
        return Finding(
            id="attribution",
            severity="info",
            headline="Not enough published posts to rank clips yet",
            detail=(
                f"{matched} of {rendered} rendered videos have metrics. A "
                f"median needs a handful of posts behind it before it means "
                f"anything, and a confident order drawn from two posts is "
                f"worse than none because it gets acted on. Rankings appear "
                f"per network as the counts fill in."
            ),
            columns=("Network", "Dimension", "Posts per option so far"),
            rows=tuple(waiting),
        )

    leaders.sort(key=lambda x: x[3], reverse=True)
    service, dimension, best, ratio = leaders[0]
    detail = (
        f"Median {metric} per post, within each network, joined from "
        f"{matched} of {rendered} rendered videos. Biggest gap: "
        f"{best.option} leads {service}'s {dimension} field by {ratio:.1f}x."
    )
    if best.spread > ratio:
        detail += (
            f" Read that carefully — its own posts range "
            f"{best.worst:,.0f}–{best.best:,.0f}, wider than the gap between "
            f"clips, so something other than the clip is moving the number."
        )
    if len(by_service) > 1:
        detail += (
            " Networks are ranked separately on purpose: a clip is not good "
            "in the abstract, it is good on one network, and they disagree."
        )
    return Finding(
        id="attribution",
        severity="info",
        headline=f"{best.option} leads on {service} by {ratio:.1f}x",
        detail=detail,
        columns=("Network", "Dimension", "Clip", f"Median {metric}", "Posts",
                 "Range"),
        rows=tuple(rows),
    )


def underperformer_finding(found: Sequence[Any]) -> Finding | None:
    """Clips worth considering cutting, on evidence rather than on rank.

    Ranking last is not evidence: with six clips of identical quality each
    one comes last about a sixth of the time, because something always is.
    What is here instead is a sign test — how often a clip's posts land below
    the median of the *other* clips — which under the null is a coin flip per
    post and so can be quantified rather than eyeballed.

    A suggestion, never an action. Roughly one in thirty of these is a clip
    that was fine, and muting is reversible from the Randomizer panel.
    """
    if not found:
        return None
    return Finding(
        id="underperformers",
        severity="warn",
        headline=(
            f"{len(found)} clip{'s' if len(found) > 1 else ''} consistently "
            f"below the rest"
        ),
        detail=(
            "Not simply ranked last — something always is. These land below "
            "the median of the other clips in their field far more often than "
            "chance allows, over enough posts to mean it. Switch one off in "
            "the Randomizer and it stops being picked without being deleted, "
            "so the decision is reversible. About one in thirty of these will "
            "be a clip that was doing nothing wrong."
        ),
        columns=("Dimension", "Clip", "Below the rest", "Its median", "Others"),
        rows=tuple(
            (
                u.dimension,
                u.option,
                f"{u.below}/{u.posts} posts",
                f"{u.own_median:,.0f}",
                f"{u.field_median:,.0f}",
            )
            for u in found
        ),
    )


def limits_finding(facts: list[CampaignFacts]) -> Finding:
    """State plainly what this data cannot answer, and why.

    Included deliberately. The questions below are the ones most worth asking,
    and a dashboard that quietly omits them invites someone to assume the
    charts already answer them.
    """
    snapshots = max((f.snapshots for f in facts), default=0)
    rows = [
        (
            "Which clip performs best",
            "Metrics are channel totals, not per-post. Nothing links a view to "
            "a video, so clip-level ranking cannot be derived at any sample size.",
        ),
        (
            "Which caption performs best",
            "Same reason. The caption is recorded per post in history; the "
            "performance is not.",
        ),
        (
            "Best time to post",
            "Publish slots are known, per-post outcomes are not, so the two "
            "cannot be paired.",
        ),
    ]
    if snapshots < MIN_SNAPSHOTS_FOR_TREND:
        rows.append((
            "Trends over time",
            f"{snapshots} daily snapshots so far. A correlation over this many "
            f"points is noise with a decimal point; {MIN_SNAPSHOTS_FOR_TREND}+ "
            f"is where a direction starts to mean something.",
        ))
    return Finding(
        id="limits",
        severity="info",
        headline="What this data cannot tell you",
        detail=(
            "Every question below needs per-post metrics, which the pipeline "
            "has never fetched. They are listed so the panel above is not "
            "mistaken for an answer to them."
        ),
        columns=("Question", "Why not"),
        rows=tuple(rows),
    )


def build(
    facts: list[CampaignFacts],
    captions: Sequence[str] = (),
    attribution: Finding | None = None,
    underperformers: Finding | None = None,
) -> list[Finding]:
    """Every finding worth showing, most consequential first."""
    found = [
        delivery_finding(facts),
        attribution,
        underperformers,
        platform_finding(facts),
        caption_diversity_finding(captions),
        engagement_mix_finding(facts),
        limits_finding(facts),
    ]
    return [f for f in found if f is not None]
