"""The publishing seam (SPEC §8, §16).

Responsibility: define what the pipeline needs from *any* scheduling backend, so
that swapping Buffer for the Instagram Graph API — or adding TikTok — is a new
file rather than a refactor.

SPEC §16: "the ``Publisher`` ABC is the seam. Honor it in v1 even though only
Buffer exists." Nothing above this layer may know that Buffer is GraphQL, that
its queue cap is 10, or that its errors are a union type.

``find_scheduled_post`` is here because of SPEC §11's crash-resume requirement:
after a job dies between ``claimed`` and ``pushed``, the next run must ask the
backend what actually exists before deciding whether to push again.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.config import PostType
from src.logging import StructuredLogger
from src.platforms import Service, check_description, check_title


class PublishRequest(BaseModel):
    """One post to be scheduled. Backend-neutral by construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel_id: str = Field(min_length=1)
    #: The description posted alongside the video. Instagram's caption box,
    #: TikTok's caption, YouTube's description — never drawn onto the frame.
    text: str
    #: Separate short title. Required by YouTube (100 chars), absent elsewhere.
    title: str | None = None
    #: Which network this channel is, so the backend knows which metadata block
    #: to build and which text limits apply.
    service: Service = Service.INSTAGRAM
    #: Must be publicly fetchable — every backend worth using pulls by URL
    #: rather than accepting an upload.
    video_url: str = Field(min_length=1)
    scheduled_for: datetime
    post_type: PostType = PostType.REEL
    #: Instagram-specific but harmless elsewhere: whether a Reel also appears in
    #: the main feed. Backends that have no such concept ignore it.
    share_to_feed: bool = True

    @model_validator(mode="after")
    def _within_platform_limits(self) -> "PublishRequest":
        """Refuse a request the platform would reject.

        Last line of defence: the description bank is validated at load, but a
        request assembled any other way must not reach the network only to come
        back as an opaque provider error that costs quota to discover.
        """
        problems = check_description(self.text, self.service) + check_title(
            self.title, self.service
        )
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def redacted(self) -> dict[str, object]:
        """A log-safe view: no full caption, no channel id."""
        return {
            "channel_id_suffix": self.channel_id[-4:],
            "video_url": self.video_url,
            "scheduled_for": self.scheduled_for.isoformat(),
            "post_type": self.post_type.value,
            "service": self.service.value,
            "text_chars": len(self.text),
            "title_chars": len(self.title) if self.title else 0,
        }


class PublishedPost(BaseModel):
    """What a backend reports back about a scheduled post."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    post_id: str = Field(min_length=1)
    scheduled_for: datetime | None = None
    #: False means the backend will only *remind* someone to post by hand.
    #: SPEC §0: "Reminder mode is not automation." A publisher that cannot
    #: guarantee automatic publishing must surface it here rather than
    #: reporting a success that will never publish itself.
    will_publish_automatically: bool = True


class Publisher(ABC):
    """A scheduling backend."""

    @abstractmethod
    def queue_depth(self, channel_id: str) -> int:
        """How many posts are currently queued for this channel (SPEC §4.1)."""

    @abstractmethod
    def create_post(self, request: PublishRequest) -> PublishedPost:
        """Schedule one post, or raise a ``PublishError`` subclass."""

    @abstractmethod
    def find_scheduled_post(
        self, channel_id: str, scheduled_for: datetime
    ) -> PublishedPost | None:
        """Find an existing post at this slot, for crash reconciliation."""

    @abstractmethod
    def delete_post(self, post_id: str) -> None:
        """Remove a still-queued post. Raises if it has already published."""


class DryRunPublisher(Publisher):
    """Records what would have been published without contacting anything.

    SPEC §9's ``dry_run`` and SPEC §13 M6 ("dry_run first"). Deliberately not a
    subclass of the real publisher: inheriting would risk one un-overridden
    method reaching the network, which is the exact thing dry run must rule out.
    """

    def __init__(self, log: StructuredLogger, *, queue_depth: int = 0) -> None:
        self._log = log
        self._depth = queue_depth
        self.published: list[PublishRequest] = []

    def queue_depth(self, channel_id: str) -> int:
        return self._depth

    def create_post(self, request: PublishRequest) -> PublishedPost:
        self.published.append(request)
        self._log.info("dry_run_post", **request.redacted())
        return PublishedPost(
            post_id=f"dry-run-{len(self.published)}",
            scheduled_for=request.scheduled_for,
        )

    def find_scheduled_post(
        self, channel_id: str, scheduled_for: datetime
    ) -> PublishedPost | None:
        return None

    def delete_post(self, post_id: str) -> None:
        self._log.info("dry_run_delete", post_id=post_id)
