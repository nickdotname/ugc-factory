"""Per-platform text limits and the fields each platform actually has.

Responsibility: hold the one table of platform text rules, and validate against
it *early* — at config load and preflight — rather than discovering a limit at
publish time when the post cannot be retried without burning quota.

The important asymmetry this module exists for: Instagram and TikTok have a
single long free-text field, while YouTube has a **separate title with a hard
100-character cap** on top of its description. A pipeline that models "one
caption" and posts it everywhere produces a YouTube post whose title is either
missing or 2,000 characters of hashtags.

Limits verified August 2026 (see README). They are values here rather than
constants scattered through the publisher so that a platform changing its mind
— TikTok raised its cap from 2,200 to 4,000 in 2024 — is a one-line edit with a
test, not an archaeology expedition.
"""

from __future__ import annotations

import re
from typing import Sequence

from dataclasses import dataclass
from enum import Enum


class Service(str, Enum):
    """A social network Buffer can publish to.

    Values match Buffer's ``Service`` GraphQL enum and its
    ``PostInputMetaData`` field names, so the publisher never translates.
    """

    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"


@dataclass(frozen=True)
class PlatformLimits:
    """What one platform will accept in its text fields."""

    service: Service

    #: Maximum characters in the main description / caption body.
    description_max: int

    #: Maximum characters in a separate title field, or None when the platform
    #: has no such field (Instagram and TikTok put everything in one box).
    title_max: int | None

    #: Whether a post is rejected outright without a title.
    title_required: bool

    #: Roughly how much shows before the reader has to tap "more". Not enforced
    #: — it drives advice, because a description can be legal and still bury
    #: the hook.
    visible_chars: int

    #: Longest video the platform will accept *in this format*. The one that
    #: bites is YouTube: a Short is a Short because of its length, and a video
    #: over the boundary is not rejected — it is silently published as an
    #: ordinary video, losing the entire Shorts surface with no error to
    #: explain it.
    max_duration_sec: float = 60.0
    #: Shortest that will not be treated as a fragment.
    min_duration_sec: float = 3.0
    #: File size ceiling. Buffer fetches by URL, so this is the platform's
    #: limit rather than an upload cap.
    max_file_mb: float = 100.0

    @property
    def has_title(self) -> bool:
        return self.title_max is not None


#: The table. Sources and verification date are recorded in the README.
LIMITS: dict[Service, PlatformLimits] = {
    Service.INSTAGRAM: PlatformLimits(
        service=Service.INSTAGRAM,
        description_max=2_200,
        title_max=None,
        title_required=False,
        visible_chars=125,
        max_duration_sec=90.0,
        min_duration_sec=3.0,
        max_file_mb=100.0,
    ),
    Service.TIKTOK: PlatformLimits(
        service=Service.TIKTOK,
        # Raised from 2,200 to 4,000 in 2024. Anything hardcoding the old value
        # is not wrong yet, just needlessly restrictive.
        description_max=4_000,
        title_max=None,
        title_required=False,
        visible_chars=150,
        # TikTok permits far longer, but nothing in this pipeline wants a
        # three-minute ad and a low ceiling cannot cause a misclassification.
        max_duration_sec=180.0,
        min_duration_sec=3.0,
        max_file_mb=500.0,
    ),
    Service.YOUTUBE: PlatformLimits(
        service=Service.YOUTUBE,
        description_max=5_000,
        # The hard one. 100 characters, and Shorts only *displays* ~40.
        title_max=100,
        title_required=True,
        visible_chars=40,
        # Deliberately the old 60s boundary rather than the extended one.
        # The asymmetry decides it: capping short costs a length nothing here
        # wants, while capping long risks a video published as an ordinary
        # upload instead of a Short — no error, no Shorts distribution, and
        # nothing to explain why that post underperformed.
        max_duration_sec=60.0,
        min_duration_sec=3.0,
        max_file_mb=100.0,
    ),
}


def limits_for(service: Service) -> PlatformLimits:
    """Look up a platform's rules, failing loudly on an unknown service."""
    try:
        return LIMITS[service]
    except KeyError as exc:  # pragma: no cover - unreachable while Service is closed
        raise ValueError(f"no text limits recorded for service {service!r}") from exc


def effective_video_limits(
    service: Service,
    config_min: float,
    config_max: float,
    config_max_mb: float,
) -> tuple[float, float, float]:
    """The limits a render must actually satisfy: the tighter of the two.

    Campaign config is operator preference; the platform's number is a fact.
    Taking the tighter of each means a generous config cannot produce a file
    the platform will reject or reclassify, and a deliberately strict config
    is still honoured.
    """
    limits = limits_for(service)
    return (
        max(config_min, limits.min_duration_sec),
        min(config_max, limits.max_duration_sec),
        min(config_max_mb, limits.max_file_mb),
    )


def config_conflicts(
    service: Service, config_max: float, config_max_mb: float
) -> list[str]:
    """Where a campaign's own limits are looser than the platform allows.

    Not an error — the render is clamped either way — but a config claiming a
    90-second ceiling on YouTube is describing something that will not be a
    Short, and that is worth saying once at preflight rather than never.
    """
    limits = limits_for(service)
    notes: list[str] = []
    if config_max > limits.max_duration_sec:
        notes.append(
            f"video.max_duration_sec is {config_max:.0f}s but {service.value} "
            f"allows {limits.max_duration_sec:.0f}s here; renders are clamped "
            f"to {limits.max_duration_sec:.0f}s"
        )
    if config_max_mb > limits.max_file_mb:
        notes.append(
            f"video.max_file_mb is {config_max_mb:.0f} but {service.value} "
            f"allows {limits.max_file_mb:.0f}"
        )
    return notes


def check_description(text: str, service: Service) -> list[str]:
    """Problems that would make this description fail on the given platform."""
    limits = limits_for(service)
    problems: list[str] = []
    if not text.strip():
        problems.append("description is empty")
    if len(text) > limits.description_max:
        problems.append(
            f"description is {len(text)} characters, over "
            f"{service.value}'s {limits.description_max} limit"
        )
    return problems


def check_title(title: str | None, service: Service) -> list[str]:
    """Problems with a title for the given platform.

    A title supplied to a platform with no title field is *not* an error — the
    same bank feeds every campaign, and Instagram simply ignores it.
    """
    limits = limits_for(service)
    problems: list[str] = []

    if not limits.has_title:
        return problems

    if not (title or "").strip():
        if limits.title_required:
            problems.append(
                f"{service.value} requires a title; add a 'title:' line to the "
                f"description record"
            )
        return problems

    assert title is not None and limits.title_max is not None
    if len(title) > limits.title_max:
        problems.append(
            f"title is {len(title)} characters, over {service.value}'s "
            f"{limits.title_max} limit: {title[:60]!r}..."
        )
    return problems


#: Which field a platform actually indexes for search.
#:
#: They differ, and the difference is easy to get backwards. YouTube ranks a
#: Short largely on its *title*; the description is close to invisible to
#: search. TikTok indexes the caption, and weights the opening of it. Writing
#: one text and posting it to both means one of them is unsearchable.
SEARCH_FIELD: dict[Service, str] = {
    Service.INSTAGRAM: "caption",
    Service.TIKTOK: "caption",
    Service.YOUTUBE: "title",
}


def _mentions(text: str, phrase: str) -> bool:
    """Whole-phrase, case-insensitive match on word boundaries.

    Boundaries matter: "nyu" appearing inside "denyung" is not a mention, and
    counting it would report a keyword as covered when it is not there.
    """
    pattern = r"\b" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _first_words(text: str, count: int) -> str:
    return " ".join(text.split()[:count])


def keyword_advice(
    text: str,
    title: str | None,
    service: Service,
    keywords: Sequence[str],
    front_load_words: int = 4,
) -> list[str]:
    """Notes about searchability, against this campaign's target phrases.

    Search is the traffic that does not decay the way a feed placement does,
    and it is the part of a caption people write last and least. These are
    notes, never errors: a post with no keyword still publishes fine, it is
    just invisible to the half of the audience that arrives by searching.
    """
    if not keywords:
        return []

    field = SEARCH_FIELD[service]
    subject = (title or "") if field == "title" else text
    notes: list[str] = []

    if field == "title" and not (title or "").strip():
        # Caught as a hard error elsewhere when the platform requires one; the
        # point here is that an empty title is an empty search surface.
        return [
            f"no title — on {service.value} the title is the search surface, "
            f"not the description"
        ]

    hits = [k for k in keywords if _mentions(subject, k)]
    if not hits:
        shown = ", ".join(f"'{k}'" for k in keywords[:3])
        notes.append(
            f"no target keyword in the {field} ({shown}) — "
            f"{service.value} indexes the {field} for search"
        )
        return notes

    opening = _first_words(subject, front_load_words)
    if not any(_mentions(opening, k) for k in hits):
        notes.append(
            f"'{hits[0]}' appears in the {field} but not in the first "
            f"{front_load_words} words; front-loading it is what ranks"
        )

    if field == "title" and text and any(_mentions(text, k) for k in keywords) \
            and not hits:
        notes.append(
            f"keyword is in the description but not the title — on "
            f"{service.value} that is the wrong field for search"
        )
    return notes


def advice(
    text: str,
    title: str | None,
    service: Service,
    keywords: Sequence[str] = (),
    front_load_words: int = 4,
) -> list[str]:
    """Non-blocking notes about text that is legal but likely to underperform."""
    limits = limits_for(service)
    notes: list[str] = []
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if len(first_line) > limits.visible_chars:
        notes.append(
            f"first line is {len(first_line)} chars; {service.value} shows about "
            f"{limits.visible_chars} before 'more'"
        )
    if limits.has_title and title and len(title) > limits.visible_chars:
        notes.append(
            f"title is {len(title)} chars; {service.value} displays about "
            f"{limits.visible_chars}"
        )
    notes += keyword_advice(text, title, service, keywords, front_load_words)
    return notes
