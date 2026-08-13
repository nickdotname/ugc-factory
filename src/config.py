"""Campaign configuration: schema, loading, and fail-loud validation.

Responsibility: turn ``campaigns/<slug>/config.yaml`` into a typed, fully
validated object, or raise ``ConfigError`` naming the offending key.

SPEC §2.2: "No campaign-specific logic anywhere in src/." This module is the
*only* place campaign differences are expressed. If a campaign needs a new
behaviour, it gets a new field here — never an ``if slug == ...`` anywhere.

SPEC §9: "Schema-validated on load. Fail loud with the offending key; never
silently default." ``extra="forbid"`` is what enforces the second half: a typo'd
key is an error, not a silently ignored line.
"""

from __future__ import annotations

import re
import zoneinfo
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.errors import ConfigError


class DedupeDimension(str, Enum):
    """A component of the combination tuple that dedupe can key on.

    An enum rather than free strings so a typo in ``dedupe_on`` fails at load
    (SPEC §2.2: "No stringly-typed status values").
    """

    HOOK = "hook"
    BODY = "body"
    MUSIC = "music"
    CAPTION = "caption"


class NotifyEvent(str, Enum):
    """Events that can trigger an alert to the campaign's webhook."""

    FAILURE = "failure"
    QUEUE_EMPTY = "queue_empty"
    QUOTA_HIGH = "quota_high"
    LICENSE_MISSING = "license_missing"
    DEDUPE_RELAXED = "dedupe_relaxed"
    DIGEST = "digest"


class PostType(str, Enum):
    """Channel-specific post type.

    Values match Buffer's ``PostType`` GraphQL enum exactly (verified against
    the live schema — see README §0). Keeping the wire values here means the
    publisher never translates, and a Buffer-side rename surfaces as one edit.
    """

    POST = "post"
    REEL = "reel"
    STORY = "story"
    SHORT = "short"


class _Yaml12Loader(yaml.SafeLoader):
    """A YAML loader that does NOT treat ``on``/``off``/``yes``/``no`` as booleans.

    PyYAML implements YAML 1.1, where those four words resolve to booleans. That
    turns SPEC §9's ``notify.on:`` key into the Python key ``True``, and would
    equally turn a caption or filename of ``no`` into ``False``. YAML 1.2 (and
    every other modern parser) restricts booleans to ``true``/``false``.

    Overriding the resolver here rather than quoting keys in every config file
    means campaign authors can write the config the spec documents, and a future
    ``off:``-shaped key cannot silently reintroduce the bug.
    """


# Rebuild the bool resolver for this loader only, matching just true/false.
_Yaml12Loader.yaml_implicit_resolvers = {
    key: [(tag, regex) for tag, regex in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12Loader.add_implicit_resolver(  # type: ignore[no-untyped-call]
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


class StrictModel(BaseModel):
    """Base for every config model: unknown keys are errors, values are frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PostingConfig(StrictModel):
    """When and how often to post (SPEC §9 ``posting``)."""

    # SPEC §4.5: Buffer's quota permits 24/day but Instagram's spam classifier
    # is a separate system. Build for 24, run at 6.
    posts_per_day: int = Field(default=6, ge=1, le=24)
    start_hour: int = Field(default=9, ge=0, le=23)
    end_hour: int = Field(default=22, ge=0, le=23)
    # SPEC §4.1: free-plan cap is queue *depth*, not a daily cap.
    max_buffer_queue: int = Field(default=10, ge=1, le=100)
    dry_run: bool = False

    @model_validator(mode="after")
    def _check_window(self) -> "PostingConfig":
        if self.end_hour <= self.start_hour:
            raise ValueError(
                f"posting.end_hour ({self.end_hour}) must be greater than "
                f"posting.start_hour ({self.start_hour})"
            )
        # Slots are spread across a half-open window; one post needs no gap, but
        # N posts need N-1 gaps of at least a minute to be distinguishable.
        window_minutes = (self.end_hour - self.start_hour) * 60
        if self.posts_per_day > 1 and window_minutes < self.posts_per_day:
            raise ValueError(
                f"posting window {self.start_hour}:00-{self.end_hour}:00 is "
                f"{window_minutes} minutes, too short for "
                f"{self.posts_per_day} posts/day"
            )
        return self


class VideoConfig(StrictModel):
    """Output video parameters (SPEC §9 ``video``)."""

    width: int = Field(default=1080, gt=0)
    height: int = Field(default=1920, gt=0)
    fps: int = Field(default=30, ge=1, le=120)
    crf: int = Field(default=23, ge=0, le=51)
    preset: str = "veryfast"
    # SPEC §4.3: Reels-tab eligibility is 5-90s. Outside that range Instagram
    # publishes a regular video post instead, so these are hard bounds, not
    # advisory ones. They are configurable but validated against the platform
    # limits below so a campaign cannot quietly opt out of Reel eligibility.
    min_duration_sec: float = Field(default=5.0, gt=0)
    max_duration_sec: float = Field(default=90.0, gt=0)
    max_file_mb: float = Field(default=100.0, gt=0)

    # Instagram's hard Reels bounds. A campaign may narrow, never widen.
    # ClassVar, not a field: these are platform facts, not campaign settings,
    # and must not be overridable from config.yaml.
    REELS_MIN_SEC: ClassVar[float] = 5.0
    REELS_MAX_SEC: ClassVar[float] = 90.0

    @field_validator("preset")
    @classmethod
    def _known_preset(cls, v: str) -> str:
        valid = {
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow", "placebo",
        }
        if v not in valid:
            raise ValueError(f"video.preset {v!r} is not an x264 preset")
        return v

    @model_validator(mode="after")
    def _check_durations(self) -> "VideoConfig":
        if self.max_duration_sec <= self.min_duration_sec:
            raise ValueError(
                f"video.max_duration_sec ({self.max_duration_sec}) must exceed "
                f"video.min_duration_sec ({self.min_duration_sec})"
            )
        if self.min_duration_sec < self.REELS_MIN_SEC:
            raise ValueError(
                f"video.min_duration_sec ({self.min_duration_sec}) is below "
                f"Instagram's {self.REELS_MIN_SEC}s Reels floor; below it the "
                f"post is not Reels-eligible (SPEC §4.3)"
            )
        if self.max_duration_sec > self.REELS_MAX_SEC:
            raise ValueError(
                f"video.max_duration_sec ({self.max_duration_sec}) exceeds "
                f"Instagram's {self.REELS_MAX_SEC}s Reels ceiling (SPEC §4.3)"
            )
        return self

    @model_validator(mode="after")
    def _check_vertical(self) -> "VideoConfig":
        # 9:16 is what makes a Reel eligible for the Reels tab. Allow a small
        # tolerance for odd dimensions but reject anything not clearly vertical.
        if self.height <= self.width:
            raise ValueError(
                f"video dimensions {self.width}x{self.height} are not vertical; "
                f"Reels require a 9:16 portrait frame (SPEC §4.3)"
            )
        return self


class CompositionConfig(StrictModel):
    """How the parts are assembled (SPEC §9 ``composition``)."""

    bodies_per_video: int = Field(default=1, ge=1, le=10)
    # SPEC §6: flat 10% for the whole video. No ducking, no per-section levels.
    music_volume: float = Field(default=0.10, ge=0.0, le=1.0)
    music_fade_out_sec: float = Field(default=1.5, ge=0.0, le=10.0)


class SelectionConfig(StrictModel):
    """Combination picking and dedupe rules (SPEC §9/§10 ``selection``)."""

    dedupe_on: tuple[DedupeDimension, ...] = (
        DedupeDimension.HOOK,
        DedupeDimension.BODY,
        DedupeDimension.MUSIC,
        DedupeDimension.CAPTION,
    )
    caption_cooldown_days: int = Field(default=14, ge=0)
    hook_cooldown_days: int = Field(default=3, ge=0)
    # SPEC §10 suggests >=90 days of unique combinations before the first
    # repeat. That is a judgement call about a campaign's tolerance for
    # repetition, not a platform limit, so it belongs in config rather than
    # hardcoded in preflight — a campaign running 1 post/day off a small
    # library may legitimately accept a shorter runway.
    min_runway_days: int = Field(default=90, ge=0)

    @field_validator("dedupe_on")
    @classmethod
    def _non_empty_unique(
        cls, v: tuple[DedupeDimension, ...]
    ) -> tuple[DedupeDimension, ...]:
        if not v:
            raise ValueError("selection.dedupe_on must name at least one dimension")
        if len(set(v)) != len(v):
            raise ValueError(f"selection.dedupe_on contains duplicates: {list(v)}")
        return v


class BufferConfig(StrictModel):
    """Buffer channel binding (SPEC §9 ``buffer``).

    Only *secret names* live here, never secret values — the config file is
    committed to a public repo (SPEC §3).
    """

    api_key_secret: str = Field(min_length=1)
    channel_id_secret: str = Field(min_length=1)
    post_type: PostType = PostType.REEL

    @field_validator("api_key_secret", "channel_id_secret")
    @classmethod
    def _looks_like_a_secret_name(cls, v: str) -> str:
        # A value that looks like an actual token rather than an env var name is
        # the failure mode that leaks credentials into git. Catch it at load.
        if not v.replace("_", "").isalnum() or not v.isupper():
            raise ValueError(
                f"{v!r} must be the NAME of an environment variable "
                f"(UPPER_SNAKE_CASE), not a secret value"
            )
        return v


class NotifyConfig(StrictModel):
    """Alerting (SPEC §9 ``notify``)."""

    webhook_secret: str = Field(min_length=1)
    on: tuple[NotifyEvent, ...] = (
        NotifyEvent.FAILURE,
        NotifyEvent.QUEUE_EMPTY,
        NotifyEvent.QUOTA_HIGH,
        NotifyEvent.LICENSE_MISSING,
    )

    @field_validator("webhook_secret")
    @classmethod
    def _looks_like_a_secret_name(cls, v: str) -> str:
        if not v.replace("_", "").isalnum() or not v.isupper():
            raise ValueError(
                f"notify.webhook_secret {v!r} must be the NAME of an "
                f"environment variable (UPPER_SNAKE_CASE), not a URL"
            )
        return v


class CampaignConfig(StrictModel):
    """One campaign: a brand, its assets, its channel, its cadence."""

    slug: str = Field(min_length=1, max_length=64)
    timezone: str
    posting: PostingConfig = PostingConfig()
    video: VideoConfig = VideoConfig()
    composition: CompositionConfig = CompositionConfig()
    selection: SelectionConfig = SelectionConfig()
    buffer: BufferConfig
    notify: NotifyConfig

    @field_validator("slug")
    @classmethod
    def _slug_is_path_safe(cls, v: str) -> str:
        # The slug becomes a directory name and part of a secret name, so it has
        # to be safe in both. Rejecting here beats sanitising at each use site.
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(
                f"slug {v!r} may contain only letters, digits, hyphen, underscore"
            )
        return v

    @field_validator("timezone")
    @classmethod
    def _real_timezone(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except Exception as exc:
            raise ValueError(f"timezone {v!r} is not a valid IANA zone: {exc}") from exc
        return v

    @property
    def zone(self) -> zoneinfo.ZoneInfo:
        """The campaign's timezone as a usable object."""
        return zoneinfo.ZoneInfo(self.timezone)


def load_config(path: Path) -> CampaignConfig:
    """Load and validate a campaign config, or raise ``ConfigError``.

    Every failure mode — missing file, unparseable YAML, wrong shape, bad value
    — surfaces as ``ConfigError`` with the offending key named. Nothing here
    falls back to a default when the file is wrong.
    """
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")

    try:
        raw: Any = yaml.load(path.read_text(encoding="utf-8"), Loader=_Yaml12Loader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if raw is None:
        raise ConfigError(f"{path} is empty")
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping, got {type(raw).__name__}")

    try:
        return CampaignConfig.model_validate(raw)
    except Exception as exc:
        # Pydantic's own message already names the offending key path; wrapping
        # it in our type keeps the CLI's error handling uniform.
        raise ConfigError(f"{path} failed validation:\n{exc}") from exc


def load_campaign(campaigns_dir: Path, slug: str) -> CampaignConfig:
    """Load ``campaigns/<slug>/config.yaml`` and check it agrees with its folder.

    A config whose ``slug`` disagrees with its directory name is the kind of
    copy-paste error that silently posts campaign A's content to campaign B's
    channel, so it is a hard failure.
    """
    config = load_config(campaigns_dir / slug / "config.yaml")
    if config.slug != slug:
        raise ConfigError(
            f"campaigns/{slug}/config.yaml declares slug {config.slug!r}; "
            f"it must match its directory name"
        )
    return config
