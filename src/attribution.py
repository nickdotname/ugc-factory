"""Which clip, caption or treatment actually earned the views.

Responsibility: join per-post metrics back to the parts each video was built
from, and report the result with enough honesty to be worth acting on.

This is the question the system has never been able to answer. ``metrics.json``
holds window totals per channel, and a window total cannot say which hook
earned it — so for the whole life of the project "which hook works" has been
unanswerable, and the library has grown by taste alone.

``history.json`` has always recorded ``buffer_post_id`` beside the exact hook,
bodies, music offset, caption and (since variation) the treatment. Buffer, it
turns out, returns per-post metrics inside the posts query at no extra request
cost. Those two facts together are all attribution needs.

**The statistics are the hard part, not the join.** Four body clips over a
fortnight is a handful of posts each, and social metrics are wildly
overdispersed — a single video catching an algorithm can outrank a hundred
others. So this reports medians rather than means, always shows how many posts
a figure rests on, and refuses to rank at all below a floor. A confident
ranking off three posts is worse than no ranking, because it gets acted on.
"""

from __future__ import annotations

import os
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from pydantic import Field

from src.config import Statistic
from src.errors import ValidationError
from src.models import HistoryEntry, Model
from src.publishers.base import PostMetrics

#: Posts per option before it is ranked at all. Below this the median is one
#: or two videos and says more about luck than about the clip.
MIN_POSTS_PER_OPTION = 4

#: Options needed before a comparison means anything. Ranking a field of one
#: is just restating that it exists.
MIN_OPTIONS = 2

#: Fold the ratio metrics away — they cannot be averaged across posts the way
#: counts can, and Buffer already reports them per post.
DEFAULT_METRIC = "views"



@dataclass(frozen=True)
class OptionPerformance:
    """One value of one dimension — a hook, a caption, a body clip."""

    dimension: str
    option: str
    posts: int
    median: float
    best: float
    worst: float
    #: The figure this option was ranked on, per the report's ``statistic``.
    #: Equal to ``median`` under the default, which is why it can be added
    #: without changing any existing ranking.
    score: float = 0.0

    @property
    def spread(self) -> float:
        """How unlike itself this option's posts were.

        A high spread means the option is not the thing driving the number,
        and is the honest counterweight to a flattering median.
        """
        return self.best / self.worst if self.worst else float("inf")


@dataclass(frozen=True)
class DimensionReport:
    """Every option of one dimension, ranked, with the caveats attached."""

    dimension: str
    metric: str
    options: tuple[OptionPerformance, ...]
    #: Which summary ``score`` holds, for display and for the render log.
    statistic: Statistic = Statistic.MEDIAN
    #: Which network these posts ran on. Rankings are always per network:
    #: Instagram returns roughly 3.7x TikTok per post on this account, so a
    #: pooled median mostly measures which platform a clip happened to run on.
    #: Two identical hooks, one weighted to Instagram and one to TikTok, come
    #: out 3.7x apart — an entirely fictional result that would get acted on.
    service: str = ""
    ignored: tuple[tuple[str, int], ...] = ()

    @property
    def rankable(self) -> bool:
        return len(self.options) >= MIN_OPTIONS

    @property
    def ratio(self) -> float | None:
        """Best score over worst — the size of the effect, if there is one."""
        if not self.rankable:
            return None
        worst = self.options[-1].score
        return self.options[0].score / worst if worst else None


def _parts_of(entry: HistoryEntry) -> dict[str, list[str]]:
    """The dimensions one post can be attributed to.

    Bodies are listed individually rather than as a tuple: the question is
    which *clip* performs, and a clip appearing in several combinations is
    exactly the evidence needed.
    """
    parts: dict[str, list[str]] = {
        "hook": [entry.hook],
        "body": list(entry.bodies),
        "caption": [entry.caption],
    }
    if entry.music:
        parts["music"] = [entry.music]
    return parts


def attribute(
    history: Iterable[HistoryEntry],
    posts: Mapping[str, PostMetrics],
    metric: str = DEFAULT_METRIC,
    min_posts: int = MIN_POSTS_PER_OPTION,
    service: str = "",
    statistic: Statistic = Statistic.MEDIAN,
) -> list[DimensionReport]:
    """Rank each dimension's options by median performance.

    Only history entries with a post id *and* a matching metric are used. A
    rendered video that never published, or published too recently to have
    figures, contributes nothing rather than a zero — a zero would drag an
    option's median down for the crime of being scheduled late.
    """
    samples: dict[str, dict[str, list[float]]] = {}

    for entry in history:
        if not entry.buffer_post_id:
            continue
        post = posts.get(entry.buffer_post_id)
        if post is None:
            continue
        if service and post.service != service:
            continue
        value = post.value(metric)
        if value is None:
            continue
        for dimension, options in _parts_of(entry).items():
            bucket = samples.setdefault(dimension, {})
            for option in options:
                bucket.setdefault(option, []).append(value)

    reports: list[DimensionReport] = []
    for dimension, by_option in samples.items():
        ranked: list[OptionPerformance] = []
        ignored: list[tuple[str, int]] = []
        for option, values in by_option.items():
            if len(values) < min_posts:
                ignored.append((option, len(values)))
                continue
            middle = statistics.median(values)
            ranked.append(
                OptionPerformance(
                    dimension=dimension,
                    option=option,
                    posts=len(values),
                    # Kept whatever the ranking statistic is: it is the figure
                    # a reader recognises, and the dashboard still shows it.
                    median=middle,
                    best=max(values),
                    worst=min(values),
                    score=(
                        middle if statistic is Statistic.MEDIAN
                        else statistics.mean(values)
                    ),
                )
            )
        ranked.sort(key=lambda o: o.score, reverse=True)
        reports.append(
            DimensionReport(
                dimension=dimension,
                metric=metric,
                statistic=statistic,
                service=service,
                options=tuple(ranked),
                ignored=tuple(sorted(ignored, key=lambda x: -x[1])),
            )
        )

    # Dimensions with the most to say first.
    reports.sort(key=lambda r: (r.rankable, len(r.options)), reverse=True)
    return reports


def attribute_by_service(
    history: Sequence[HistoryEntry],
    posts: Mapping[str, PostMetrics],
    metric: str = DEFAULT_METRIC,
    min_posts: int = MIN_POSTS_PER_OPTION,
) -> dict[str, list[DimensionReport]]:
    """One ranking per network, which is the only kind that means anything.

    A clip is not good or bad in the abstract — it is good on TikTok or good
    on Shorts, and those can disagree. Ranking within a network also removes
    the platform-mix bias for free: every post being compared shares a
    baseline, so no normalisation or index is needed.
    """
    services = sorted({
        post.service for post in posts.values() if post.service
    })
    return {
        service: attribute(history, posts, metric, min_posts, service)
        for service in services
    }


#: Posts a clip needs before it can be called a dud. Chosen by simulation
#: rather than taste: at twelve posts and the share below, the test fires on
#: about 3% of clips that are in fact fine, and catches about 62% of clips
#: genuinely three times worse than the rest. Fewer posts, or a lower share,
#: trades that badly — 12 at 75% roughly triples the false positives.
MIN_POSTS_TO_CONDEMN = 12

#: Share of a clip's posts that must land below the median of the *others*.
#: Under the null — the clip being ordinary — each post is a coin flip, so
#: this is a sign test and a run this long is genuinely unlikely.
CONDEMN_SHARE = 0.8


@dataclass(frozen=True)
class Underperformer:
    """A clip whose posts land below the field far too often to be luck."""

    dimension: str
    option: str
    posts: int
    below: int
    field_median: float
    own_median: float

    @property
    def share(self) -> float:
        return self.below / self.posts if self.posts else 0.0


def underperformers(
    history: Iterable[HistoryEntry],
    posts: Mapping[str, PostMetrics],
    metric: str = DEFAULT_METRIC,
    service: str = "",
) -> list[Underperformer]:
    """Clips worth considering cutting, on evidence rather than on rank.

    Ranking last is not evidence of anything. With six clips of identical
    quality, each one comes last about a sixth of the time — something always
    is. Simulating that was what ruled out the obvious implementation.

    Nor is comparing medians directly enough, because a median over five
    posts of a lognormal quantity is itself extremely noisy.

    What survives is a sign test: count how many of a clip's posts fall below
    the median of every post in its field. If the clip is ordinary that is a
    coin flip each time, so a long run of them is unlikely in a way that can
    be quantified rather than eyeballed.

    Never automatic. This returns a suggestion for a person, who can mute a
    clip in the roster and unmute it later — and roughly one in sixteen of
    these will be a clip that was fine.
    """
    values: dict[str, dict[str, list[float]]] = {}
    field: list[float] = []

    for entry in history:
        if not entry.buffer_post_id:
            continue
        post = posts.get(entry.buffer_post_id)
        if post is None:
            continue
        if service and post.service != service:
            continue
        value = post.value(metric)
        if value is None:
            continue
        field.append(value)
        for dimension, options in _parts_of(entry).items():
            bucket = values.setdefault(dimension, {})
            for option in options:
                bucket.setdefault(option, []).append(value)

    if len(field) < MIN_POSTS_TO_CONDEMN:
        return []

    found: list[Underperformer] = []
    for dimension, by_option in values.items():
        # A field of one has no field to be below.
        if len(by_option) < MIN_OPTIONS:
            continue
        for option, samples in by_option.items():
            if len(samples) < MIN_POSTS_TO_CONDEMN:
                continue
            # Leave-one-out: a clip is judged against the *other* clips, not
            # against a field it is a large part of. With four clips its own
            # posts are a quarter of the median it would be compared to,
            # which drags the bar down toward it and hides exactly the clip
            # this is looking for.
            others = [
                value
                for other, vals in by_option.items() if other != option
                for value in vals
            ]
            if not others:
                continue
            median = statistics.median(others)
            below = sum(1 for v in samples if v < median)
            if below / len(samples) >= CONDEMN_SHARE:
                found.append(Underperformer(
                    dimension=dimension, option=option, posts=len(samples),
                    below=below, field_median=median,
                    own_median=statistics.median(samples),
                ))
    found.sort(key=lambda u: (-u.share, u.own_median))
    return found


# ------------------------------------------------------- treatment effects

#: Posts needed before a treatment parameter is tested at all.
MIN_POSTS_FOR_TREATMENT = 30

#: Per-test significance, before correction. Corrected below by the number of
#: parameters actually tested, because testing twelve at the usual 5% bar
#: gives a 46% chance of declaring a winner every week whether or not
#: variation does anything.
TREATMENT_ALPHA = 0.05


@dataclass(frozen=True)
class TreatmentEffect:
    """Whether one knob of the variation engine moves the numbers."""

    parameter: str
    low_median: float
    high_median: float
    posts: int
    #: Corrected for how many parameters were tested together.
    p_value: float
    threshold: float

    @property
    def significant(self) -> bool:
        return self.p_value <= self.threshold

    @property
    def ratio(self) -> float:
        return self.high_median / self.low_median if self.low_median else 1.0


def _rank_sum_p(low: Sequence[float], high: Sequence[float]) -> float:
    """Two-sided Mann-Whitney U, normal approximation.

    A rank test rather than a t-test because views are lognormal and nowhere
    near normal; ranks do not care. The normal approximation is fine at the
    sample sizes this refuses to run below.
    """
    import math

    n1, n2 = len(low), len(high)
    if n1 < 2 or n2 < 2:
        return 1.0

    combined = sorted([(v, 0) for v in low] + [(v, 1) for v in high])
    ranks: list[float] = [0.0] * len(combined)
    index = 0
    while index < len(combined):
        stop = index
        while stop + 1 < len(combined) and combined[stop + 1][0] == combined[index][0]:
            stop += 1
        # Ties share the average of the ranks they span.
        average = (index + stop) / 2 + 1
        for position in range(index, stop + 1):
            ranks[position] = average
        index = stop + 1

    rank_sum = sum(r for r, (_, group) in zip(ranks, combined) if group == 0)
    u = rank_sum - n1 * (n1 + 1) / 2
    mean = n1 * n2 / 2
    sd = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sd == 0:
        return 1.0
    z = (u - mean) / sd
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def treatment_effects(
    history: Iterable[HistoryEntry],
    posts: Mapping[str, PostMetrics],
    metric: str = DEFAULT_METRIC,
    service: str = "",
) -> list[TreatmentEffect]:
    """Does any of the creative variation actually change performance?

    Without this the variation engine runs blind: it applies a different
    punch-in, grade and pace to every video and nothing ever asks whether it
    helps. The recipe is recorded per post precisely so it can be.

    Each parameter is split at its median into a low and a high half and the
    two are compared with a rank test. The significance bar is divided by the
    number of parameters tested — twelve of them at the usual 5% would
    declare a winner about half the weeks whether or not variation does
    anything, and that is a machine for inventing findings.
    """
    samples: list[tuple[dict[str, float], float]] = []
    for entry in history:
        if not entry.buffer_post_id or not entry.treatment:
            continue
        post = posts.get(entry.buffer_post_id)
        if post is None:
            continue
        if service and post.service != service:
            continue
        value = post.value(metric)
        if value is None:
            continue
        samples.append((entry.treatment, value))

    if len(samples) < MIN_POSTS_FOR_TREATMENT:
        return []

    parameters = sorted({
        key for recipe, _ in samples for key in recipe
        # Anchors are where the crop sits, not how much of anything; they
        # have no natural low-to-high ordering to split on.
        if not key.startswith("anchor")
    })
    if not parameters:
        return []
    threshold = TREATMENT_ALPHA / len(parameters)

    effects: list[TreatmentEffect] = []
    for parameter in parameters:
        pairs = [
            (float(recipe[parameter]), value)
            for recipe, value in samples if parameter in recipe
        ]
        if len(pairs) < MIN_POSTS_FOR_TREATMENT:
            continue
        midpoint = statistics.median(setting for setting, _ in pairs)
        low = [v for setting, v in pairs if setting <= midpoint]
        high = [v for setting, v in pairs if setting > midpoint]
        if len(low) < 2 or len(high) < 2:
            continue
        effects.append(TreatmentEffect(
            parameter=parameter,
            low_median=statistics.median(low),
            high_median=statistics.median(high),
            posts=len(pairs),
            p_value=_rank_sum_p(low, high),
            threshold=threshold,
        ))

    effects.sort(key=lambda e: e.p_value)
    return effects


def coverage(
    history: Sequence[HistoryEntry], posts: Mapping[str, PostMetrics]
) -> tuple[int, int]:
    """(attributable posts, rendered videos) — how much of the output is measured.

    Worth showing beside any ranking. A ranking drawn from a fifth of the
    output is a ranking of that fifth.
    """
    matched = sum(
        1 for e in history if e.buffer_post_id and e.buffer_post_id in posts
    )
    return matched, len(history)



# --------------------------------------------------------------- persistence

#: Filename inside a campaign directory.
POSTS_FILE = "posts.json"


class PostCache(Model):
    """Per-post metrics kept between runs.

    Accumulated rather than replaced. Buffer stops returning a post once it
    falls off the end of the paginated window, and the history entry it
    belongs to lives forever — so discarding what was fetched last time would
    quietly shrink the evidence base as the campaign ages.
    """

    posts: dict[str, PostMetrics] = Field(default_factory=dict)

    def merged_with(self, fresh: Iterable[PostMetrics]) -> "PostCache":
        """Newer figures win; posts absent from this fetch are kept."""
        combined = dict(self.posts)
        for post in fresh:
            if post.post_id:
                combined[post.post_id] = post
        return PostCache(posts=combined)


def posts_path(campaign_dir: Path) -> Path:
    return campaign_dir / POSTS_FILE


def load_posts(path: Path) -> PostCache:
    if not path.is_file():
        return PostCache()
    try:
        return PostCache.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"{path} is not a valid post cache: {exc}") from exc


def save_posts(path: Path, cache: PostCache) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = cache.model_dump_json(indent=2) + "\n"
    handle, temp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
