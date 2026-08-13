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
    ),
    Service.TIKTOK: PlatformLimits(
        service=Service.TIKTOK,
        # Raised from 2,200 to 4,000 in 2024. Anything hardcoding the old value
        # is not wrong yet, just needlessly restrictive.
        description_max=4_000,
        title_max=None,
        title_required=False,
        visible_chars=150,
    ),
    Service.YOUTUBE: PlatformLimits(
        service=Service.YOUTUBE,
        description_max=5_000,
        # The hard one. 100 characters, and Shorts only *displays* ~40.
        title_max=100,
        title_required=True,
        visible_chars=40,
    ),
}


def limits_for(service: Service) -> PlatformLimits:
    """Look up a platform's rules, failing loudly on an unknown service."""
    try:
        return LIMITS[service]
    except KeyError as exc:  # pragma: no cover - unreachable while Service is closed
        raise ValueError(f"no text limits recorded for service {service!r}") from exc


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


def advice(text: str, title: str | None, service: Service) -> list[str]:
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
    return notes
