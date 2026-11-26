"""Instagram, posted to directly (no scheduling service in between).

Responsibility: publish Reels through Instagram's own Graph API, behind the
same ``Publisher`` seam Buffer sits behind, so an account moves from one to
the other by changing ``provider:`` in ``accounts.yaml`` and nothing else.

**Why there is an outbox.** The pipeline was built around a backend that
*holds* posts: ``topup`` hands over a video and a time, and the backend
publishes it when that time comes. Instagram's API has no such thing — a
publish call publishes now. Rather than teach every caller the difference,
this module keeps the held posts itself: ``create_post`` writes a small file
under ``outbox/`` and returns at once, and ``publish_due`` (run every few
minutes by its own workflow) sends whatever has come due. To everything above
the seam it still looks like a queue with a depth and a next-due time.

One file per post, not one list: two workflows touch the outbox (``topup``
adds, ``publish-due`` marks sent) and files that never share a line cannot
conflict when both push.

**Ids.** The id handed back from ``create_post`` is the outbox id, and it is
the id every figure is later filed under — the queue records it at push time,
before Instagram has issued a media id, and attribution joins on what the
queue recorded. The media id is kept on the outbox item and used only to ask
Instagram for the numbers.

**Two logins, one class.** Instagram Login talks to ``graph.instagram.com``;
Facebook Login talks to ``graph.facebook.com`` and is the only one that can
attach a track from Instagram's music catalogue (``audio_id``). The calls are
otherwise the same, so the host is the single thing that differs.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from src.errors import (
    AuthError,
    InvalidPostError,
    PublishError,
    QuotaError,
    RateLimitError,
)
from src.logging import StructuredLogger
from src.platforms import Service
from src.ports import SystemClock
from src.publishers.base import (
    MetricRow,
    PostMetrics,
    PublishedPost,
    Publisher,
    PublishRequest,
    QueueState,
)

HOSTS: dict[str, str] = {
    "instagram": "https://graph.instagram.com",
    "facebook": "https://graph.facebook.com",
}
DEFAULT_API_VERSION = "v27.0"
REQUEST_TIMEOUT_SEC = 60
OUTBOX_DIR = "outbox"
ID_PREFIX = "igo-"

#: Instagram asks for a container to be polled about once a minute for at
#: most five. A Reel of this size is usually ready well inside that.
POLL_INTERVAL_SEC = 15.0
POLL_ATTEMPTS = 20

#: A post this far past its slot is not sent. Publishing a backlog the moment
#: a broken token is replaced would put a day of videos out in one minute.
DEFAULT_MAX_LATE = timedelta(hours=6)
#: Two posts on one account less than this apart: the second does worse (2026-11-25: 77 such posts since Nov 17,
#: median 72 views against 89). Reels, carousels and fact reels are queued by separate jobs, so the publisher keeps
#: them apart: a post whose account published less than this ago waits for a later run.
MIN_GAP = timedelta(minutes=60)

QUEUED = "queued"
PUBLISHING = "publishing"
PUBLISHED = "published"
FAILED = "failed"
CANCELLED = "cancelled"

#: Graph error codes that mean "the token is no good".
_AUTH_CODES = {102, 190}
#: ... "slow down" ...
_RATE_CODES = {4, 17, 32, 613, 80002}
#: ... and "this account has published all it may for now" (the 24-hour
#: publishing allowance), which waiting within a run does not fix.
_QUOTA_SUBCODES = {2207042}
#: Instagram's own hiccups: it timed out fetching the media (2207003, also
#: reported as code -2) or had a server error (2207001). Worth another try.
_TRANSIENT_SUBCODES = {2207001, 2207003}

#: Instagram's metric names, mapped to the names the rest of the pipeline
#: already reads (they were Buffer's, and attribution is written against
#: them). ``scale`` converts units: Instagram reports watch time in
#: milliseconds, the cache holds seconds and minutes.
#: Instagram cuts a longer name short on its own; this keeps it deliberate.
AUDIO_NAME_MAX = 80

_INSIGHTS: tuple[tuple[str, str, str, float], ...] = (
    ("views", "views", "Views", 1.0),
    ("reach", "reach", "Reach", 1.0),
    ("likes", "reactions", "Reactions", 1.0),
    ("comments", "comments", "Comments", 1.0),
    ("shares", "shares", "Shares", 1.0),
    ("saved", "saves", "Saves", 1.0),
    ("ig_reels_avg_watch_time", "averageTimeWatched", "Avg. Watch Time (sec)", 1 / 1000),
    ("ig_reels_video_view_total_time", "totalTimeWatched", "Watch Time (min)", 1 / 60000),
)

#: Asked for separately: newer figures (Dec 2025) that an older post, a
#: carousel or an API version may refuse, and that are not worth losing the
#: others for. ``reels_skip_rate`` is the share of viewers who swiped away in
#: the first three seconds: the most direct measure of an opening.
_EXTRA_INSIGHTS: tuple[tuple[str, str, str, float], ...] = (
    ("reels_skip_rate", "skipRate", "Skip Rate (%)", 1.0),
    ("reposts", "reposts", "Reposts", 1.0),
)

#: Instagram allows five hashtags on a post or Reel (since December 2025).
MAX_HASHTAGS = 5
_HASHTAG = re.compile(r"(?<![\w#])#\w+")


def cap_hashtags(caption: str, limit: int = MAX_HASHTAGS) -> str:
    """The caption with only its first ``limit`` hashtags: the rest are dropped,
    and the spaces they leave are tidied, so a post is never refused for them."""
    seen = 0

    def keep(match: re.Match[str]) -> str:
        nonlocal seen
        seen += 1
        return match.group(0) if seen <= limit else ""

    out = _HASHTAG.sub(keep, caption)
    if seen <= limit:
        return caption
    return "\n".join(re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in out.split("\n"))


def _collaborators(item: Mapping[str, Any]) -> str:
    """The post's collaborators as Instagram takes them: a JSON list of up to
    three usernames, without the @. Empty when there are none."""
    names = [str(n).lstrip("@").strip() for n in (item.get("collaborators") or [])]
    names = [n for n in names if n][:3]
    return json.dumps(names) if names else ""


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


class Outbox:
    """Posts waiting for their slot, one JSON file each."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    @property
    def directory(self) -> Path:
        return self._dir

    def path_for(self, post_id: str) -> Path:
        return self._dir / f"{post_id}.json"

    def save(self, item: Mapping[str, Any]) -> Path:
        """Write one item atomically: a half-written file would be a lost post."""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(str(item["id"]))
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(item, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return path

    def load(self, post_id: str) -> dict[str, Any] | None:
        path = self.path_for(post_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def items(self) -> list[dict[str, Any]]:
        if not self._dir.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for path in sorted(self._dir.glob(f"{ID_PREFIX}*.json")):
            item = self.load(path.stem)
            if item is not None:
                found.append(item)
        return found

    def for_channel(self, channel_id: str, *statuses: str) -> list[dict[str, Any]]:
        return [
            i for i in self.items()
            if i.get("channel_id") == channel_id
            and (not statuses or i.get("status") in statuses)
        ]


def _page_tokens() -> dict[str, str]:
    """IG_PAGE_TOKENS: a JSON object of Instagram account id -> Page token, or nothing."""
    import json
    import os
    try:
        data = json.loads(os.environ.get("IG_PAGE_TOKENS") or "{}")
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in data.items() if v} if isinstance(data, dict) else {}


class InstagramPublisher(Publisher):
    """Publishes Reels through the Instagram Graph API."""

    def __init__(
        self,
        access_token: str,
        log: StructuredLogger,
        *,
        outbox_dir: Path,
        login: str = "instagram",
        api_version: str = DEFAULT_API_VERSION,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not access_token:
            raise AuthError("Instagram access token is empty")
        if login not in HOSTS:
            raise ValueError(f"login must be one of {sorted(HOSTS)}, got {login!r}")
        self._token = access_token
        #: Never-expiring Page tokens by Instagram account id (scripts/page_tokens.py
        #: mints them from IG_TOKEN into the IG_PAGE_TOKENS secret). When one covers the
        #: account being worked on, it is used instead of the shared login token.
        self._page_tokens: dict[str, str] = _page_tokens() if login == "facebook" else {}
        self._acting: str | None = None
        self._log = log
        self._login = login
        self._base = f"{HOSTS[login]}/{api_version}"
        self._session = session or requests.Session()
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._now: Callable[[], datetime] = now or SystemClock().now
        self.outbox = Outbox(outbox_dir)
        #: Same meter the Buffer publisher keeps, so callers that total
        #: requests across publishers need not care which kind they hold.
        self.request_count = 0
        #: Files written during this run, for the caller to commit.
        self.touched: list[Path] = []
        #: Called with (file, "claim") just before a post is sent and with
        #: (file, "sent") just after, so the caller can make each step durable
        #: (commit and push it) instead of once at the end of the run. A
        #: "claim" that raises stops the post from being sent.
        self.checkpoint: Callable[[Path, str], None] | None = None

    # ----------------------------------------------------------------- plumbing

    def _call(
        self, method: str, path: str, params: Mapping[str, Any]
    ) -> dict[str, Any]:
        """One Graph API call, retrying only what a retry can fix."""
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self.request_count += 1
            try:
                response = self._session.request(
                    method,
                    f"{self._base}/{path.lstrip('/')}",
                    params=dict(params) if method == "GET" else None,
                    data=dict(params) if method != "GET" else None,
                    # A header, never a query parameter: a token in a URL ends
                    # up in logs and error messages.
                    headers={"Authorization": f"Bearer {self._page_tokens.get(self._acting or '', self._token)}"},
                    timeout=REQUEST_TIMEOUT_SEC,
                )
            except requests.RequestException as exc:
                last = RateLimitError(f"Instagram request failed: {exc}")
                if attempt == self._max_attempts:
                    raise last from exc
                self._sleep(2**attempt)
                continue

            try:
                body: Any = response.json()
            except ValueError:
                body = None

            error = body.get("error") if isinstance(body, dict) else None
            if response.status_code < 400 and not error:
                if not isinstance(body, dict):
                    raise PublishError(
                        f"Instagram returned non-JSON: {response.text[:300]}"
                    )
                return body

            failure = self._classify(response.status_code, error, response.text)
            if failure.retryable and attempt < self._max_attempts:
                last = failure
                self._sleep(2**attempt)
                continue
            raise failure

        raise last or PublishError("Instagram request failed")  # pragma: no cover

    @staticmethod
    def _classify(
        status: int, error: Mapping[str, Any] | None, text: str
    ) -> PublishError:
        code = int((error or {}).get("code") or 0)
        subcode = int((error or {}).get("error_subcode") or 0)
        message = str((error or {}).get("message") or text[:300])
        detail = f"{message} (HTTP {status}, code {code}, subcode {subcode})"
        if code in _AUTH_CODES or status == 401:
            return AuthError(
                f"Instagram rejected the access token: {detail}. Tokens last "
                f"60 days; issue a new one and store it in the account's slot."
            )
        if subcode in _QUOTA_SUBCODES or code == 9:
            return QuotaError(f"Instagram's publishing allowance is spent: {detail}")
        if code in _RATE_CODES or status == 429:
            return RateLimitError(f"Instagram rate limited the request: {detail}")
        if status >= 500 or code in (1, 2, -2) or subcode in _TRANSIENT_SUBCODES:
            return PublishError(f"Instagram had a temporary failure: {detail}")
        return InvalidPostError(f"Instagram rejected the request: {detail}")

    # -------------------------------------------------------------- the seam

    def queue_state(self, channel_id: str) -> QueueState:
        waiting = self.outbox.for_channel(channel_id, QUEUED, PUBLISHING)
        due = [d for d in (_parse_dt(i.get("scheduled_for")) for i in waiting) if d]
        return QueueState(depth=len(waiting), next_due=min(due) if due else None)

    def create_post(self, request: PublishRequest) -> PublishedPost:
        """Hold one post for its slot. Nothing is sent to Instagram here."""
        if request.service is not Service.INSTAGRAM:
            raise InvalidPostError(
                f"the Instagram publisher cannot post to {request.service.value}"
            )
        if request.audio_id and self._login != "facebook":
            raise InvalidPostError(
                "attaching a track from Instagram's music catalogue needs an "
                "account connected through Facebook Login (login: facebook)"
            )
        # A video goes to an account once. Two top-ups running together (2026-11-26: the cron and the clock's
        # dispatch) booked the same videos twice, and eye.trick.lab and fourier.reveal posted them twice.
        for held in self.outbox.for_channel(request.channel_id, QUEUED, PUBLISHING, PUBLISHED):
            if held.get("video_url") == request.video_url:
                self._log.warning("instagram_duplicate_not_held", post_id=held.get("id"))
                when = _parse_dt(held.get("scheduled_for")) or request.scheduled_for
                return PublishedPost(post_id=str(held.get("id")), scheduled_for=when, will_publish_automatically=True)
        post_id = f"{ID_PREFIX}{uuid.uuid4()}"
        item: dict[str, Any] = {
            "id": post_id,
            "channel_id": request.channel_id,
            "status": QUEUED,
            "video_url": request.video_url,
            "caption": request.text,
            "first_comment": request.first_comment,
            "share_to_feed": request.share_to_feed,
            "trial": request.trial,
            "trial_graduation": request.trial_graduation,
            "cover_at_ms": request.cover_at_ms,
            "audio_id": request.audio_id,
            "audio_volume": request.audio_volume,
            "video_volume": request.video_volume,
            "audio_name": request.audio_name,
            "scheduled_for": _utc(request.scheduled_for).isoformat(),
            "created_at": self._now().isoformat(),
            "attempts": 0,
        }
        self.touched.append(self.outbox.save(item))
        self._log.info("instagram_post_held", post_id=post_id, **request.redacted())
        return PublishedPost(
            post_id=post_id,
            scheduled_for=request.scheduled_for,
            will_publish_automatically=True,
        )

    def scheduled_slots(self, channel_id: str) -> list[datetime]:
        return [
            d for d in (
                _parse_dt(i.get("scheduled_for"))
                for i in self.outbox.for_channel(channel_id, QUEUED, PUBLISHING)
            ) if d
        ]

    def find_scheduled_post(
        self, channel_id: str, scheduled_for: datetime
    ) -> PublishedPost | None:
        wanted = _utc(scheduled_for)
        for item in self.outbox.for_channel(channel_id, QUEUED, PUBLISHING, PUBLISHED):
            due = _parse_dt(item.get("scheduled_for"))
            if due is not None and abs((due - wanted).total_seconds()) < 60:
                return PublishedPost(post_id=str(item["id"]), scheduled_for=due)
        return None

    def delete_post(self, post_id: str) -> None:
        item = self.outbox.load(post_id)
        if item is None:
            raise PublishError(f"no held Instagram post with id {post_id}")
        if item.get("status") in (PUBLISHED, PUBLISHING):
            raise PublishError(
                f"{post_id} has already gone to Instagram and can only be "
                f"removed in the app"
            )
        item["status"] = CANCELLED
        self.touched.append(self.outbox.save(item))
        self._log.info("instagram_post_cancelled", post_id=post_id)

    # ------------------------------------------------------------ publishing

    def _container_params(self, item: Mapping[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {
            "media_type": "REELS",
            "video_url": item["video_url"],
            "caption": cap_hashtags(item.get("caption") or ""),
        }
        if item.get("cover_at_ms") is not None:
            # The frame shown on the profile grid; without it, the first frame.
            params["thumb_offset"] = str(int(item["cover_at_ms"]))
        if item.get("trial"):
            # A trial reel is shown to non-followers only, and Instagram
            # refuses share_to_feed alongside it.
            params["trial_params"] = json.dumps(
                {"graduation_strategy": item.get("trial_graduation") or "MANUAL"}
            )
        else:
            params["share_to_feed"] = "true" if item.get("share_to_feed", True) else "false"
            # A collab post shows on every collaborator's profile and to their
            # followers. Instagram allows up to three, and not on a trial reel.
            collab = _collaborators(item)
            if collab:
                params["collaborators"] = collab
        if item.get("audio_id"):
            audio: dict[str, Any] = {"audio_id": str(item["audio_id"])}
            for key in ("audio_volume", "video_volume"):
                if item.get(key) is not None:
                    audio[key] = int(item[key])
            params["audio_configuration"] = json.dumps(audio)
        elif item.get("audio_name"):
            # The Reel's own sound, named. A track from the catalogue already
            # carries its own name, so this is only for original audio.
            params["audio_name"] = str(item["audio_name"])[:AUDIO_NAME_MAX]
        return params

    def _wait_until_ready(self, container_id: str) -> str:
        status = "IN_PROGRESS"
        for _ in range(POLL_ATTEMPTS):
            body = self._call("GET", container_id, {"fields": "status_code,status"})
            status = str(body.get("status_code") or "")
            if status in ("FINISHED", "PUBLISHED"):
                return status
            if status in ("ERROR", "EXPIRED"):
                raise InvalidPostError(
                    f"Instagram could not process the video: "
                    f"{body.get('status') or status}"
                )
            self._sleep(POLL_INTERVAL_SEC)
        raise PublishError(
            f"Instagram was still processing the video after "
            f"{int(POLL_ATTEMPTS * POLL_INTERVAL_SEC)}s; it will be tried again"
        )

    def _publish_one(self, item: dict[str, Any]) -> None:
        """Send one held post. Saves after every step that cannot be redone."""
        channel = str(item["channel_id"])
        self._acting = channel
        item["attempts"] = int(item.get("attempts") or 0) + 1

        if item.get("image_urls") and not item.get("container_id"):
            # A carousel: one container per slide, then one that holds them.
            children = list(item.get("children") or [])
            for url in list(item["image_urls"])[len(children):]:
                made = self._call(
                    "POST", f"{channel}/media",
                    {"image_url": url, "is_carousel_item": "true"},
                )
                if not made.get("id"):
                    raise PublishError(f"Instagram returned no id for a slide: {made}")
                children.append(str(made["id"]))
                item["children"] = children
                self.touched.append(self.outbox.save(item))
            carousel: dict[str, Any] = {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": cap_hashtags(item.get("caption") or ""),
            }
            if _collaborators(item):
                carousel["collaborators"] = _collaborators(item)
            try:
                created = self._call("POST", f"{channel}/media", carousel)
            except InvalidPostError as exc:
                if "collaborators" not in carousel:
                    raise
                self._log.warning(
                    "instagram_collaborators_refused",
                    post_id=item["id"], error=str(exc)[:200],
                )
                item["collaborators_refused"] = item.get("collaborators")
                item["collaborators"] = None
                del carousel["collaborators"]
                created = self._call("POST", f"{channel}/media", carousel)
            item["container_id"] = str(created.get("id") or "")
            if not item["container_id"]:
                raise PublishError(f"Instagram returned no container id: {created}")
        if not item.get("container_id"):
            try:
                created = self._call(
                    "POST", f"{channel}/media", self._container_params(item)
                )
            except InvalidPostError as exc:
                # A collaborator and a name for the sound are niceties; the
                # post is the point. If Instagram will not take them, send the
                # Reel without them (collaborators first: they are the newer ask).
                if _collaborators(item):
                    self._log.warning(
                        "instagram_collaborators_refused",
                        post_id=item["id"], error=str(exc)[:200],
                    )
                    item["collaborators_refused"] = item.get("collaborators")
                    item["collaborators"] = None
                elif item.get("audio_name") and not item.get("audio_id"):
                    self._log.warning(
                        "instagram_audio_name_refused",
                        post_id=item["id"], error=str(exc)[:200],
                    )
                    item["audio_name"] = None
                else:
                    raise
                created = self._call(
                    "POST", f"{channel}/media", self._container_params(item)
                )
            item["container_id"] = str(created.get("id") or "")
            if not item["container_id"]:
                raise PublishError(f"Instagram returned no container id: {created}")
        # Saved as `publishing` BEFORE the publish call: if the job dies in
        # between, the next run finds the container and asks Instagram what
        # became of it instead of posting the video a second time.
        item["status"] = PUBLISHING
        claim = self.outbox.save(item)
        self.touched.append(claim)
        if self.checkpoint is not None:
            # A file on the runner's disk is gone when the job ends. The claim
            # only protects anything once it is on the branch, so it goes
            # there now; if it cannot, the post is not sent on this run.
            self.checkpoint(claim, "claim")

        state = self._wait_until_ready(str(item["container_id"]))
        if state != "PUBLISHED":
            published = self._call(
                "POST", f"{channel}/media_publish",
                {"creation_id": item["container_id"]},
            )
            item["media_id"] = str(published.get("id") or "") or None
        item["status"] = PUBLISHED
        item["published_at"] = self._now().isoformat()
        item.pop("error", None)
        sent = self.outbox.save(item)
        self.touched.append(sent)
        if self.checkpoint is not None:
            try:
                self.checkpoint(sent, "sent")
            except Exception as exc:  # noqa: BLE001 - the post is out
                # The claim is already on the branch, so the next run asks
                # Instagram about the container instead of sending it again.
                self._log.exception("instagram_sent_not_recorded", exc, post_id=item["id"])

        comment = item.get("first_comment")
        if comment and item.get("media_id"):
            try:
                self._call("POST", f"{item['media_id']}/comments", {"message": comment})
            except PublishError as exc:
                # The post is out; a missing comment is not worth failing it.
                self._log.warning(
                    "instagram_first_comment_failed",
                    post_id=item["id"], error=str(exc)[:200],
                )

    def publish_due(
        self,
        *,
        channel_ids: set[str] | None = None,
        max_per_channel: int = 1,
        max_late: timedelta = DEFAULT_MAX_LATE,
        max_attempts: int = 3,
        send_next: bool = False,
        min_gap: timedelta = MIN_GAP,
    ) -> list[dict[str, Any]]:
        """Send every held post whose slot has arrived. Returns what changed.

        ``send_next`` sends each account's earliest held post now, whatever its
        slot: the "post one right now" switch, for a first post or a check.

        At most ``max_per_channel`` per account per run, oldest first, so an
        account that fell behind catches up one slot at a time rather than
        all at once. A token or allowance failure stops that account for this
        run — everything behind it would fail the same way. A post whose
        account published less than ``min_gap`` ago waits (``send_next`` aside).
        """
        now = self._now()
        changed: list[dict[str, Any]] = []
        sent: dict[str, int] = {}
        blocked: set[str] = set()

        waiting = [
            i for i in self.outbox.items()
            if i.get("status") in (QUEUED, PUBLISHING)
            and (channel_ids is None or i.get("channel_id") in channel_ids)
        ]
        waiting.sort(key=lambda i: str(i.get("scheduled_for") or ""))
        last: dict[str, datetime] = {}
        for i in self.outbox.items():
            at = _parse_dt(i.get("published_at")) if i.get("status") == PUBLISHED else None
            ch = str(i.get("channel_id"))
            if at is not None and (ch not in last or at > last[ch]): last[ch] = at

        posted = {(str(i.get("channel_id")), i.get("video_url")) for i in self.outbox.items()
                  if i.get("status") == PUBLISHED and i.get("video_url")}
        for item in waiting:
            channel = str(item.get("channel_id"))
            due = _parse_dt(item.get("scheduled_for"))
            if item.get("status") == QUEUED and (channel, item.get("video_url")) in posted:
                item["status"] = FAILED                       # this account already posted this exact video
                item["error"] = "this video was already posted on this account; not sent again"
                self.touched.append(self.outbox.save(item)); changed.append(item)
                self._log.warning("instagram_duplicate_skipped", post_id=item["id"])
                continue
            if sent.get(channel, 0) >= max_per_channel:
                continue
            if send_next and due is not None and due > now and item.get("status") == QUEUED:
                due = now
            if due is None or due > now or channel in blocked:
                continue
            if (not send_next and item.get("status") == QUEUED and channel in last
                    and now - last[channel] < min_gap and now - due < max_late - min_gap):
                continue                                  # the account posted under an hour ago: a later run sends it
            if item.get("status") == QUEUED and now - due > max_late:
                item["status"] = FAILED
                item["error"] = (
                    f"missed its slot by more than {max_late} and was not sent"
                )
                self.touched.append(self.outbox.save(item))
                changed.append(item)
                self._log.warning("instagram_post_expired", post_id=item["id"])
                continue
            try:
                self._publish_one(item)
            except (AuthError, QuotaError) as exc:
                item["status"] = QUEUED if not item.get("container_id") else PUBLISHING
                item["error"] = str(exc)[:500]
                self.touched.append(self.outbox.save(item))
                blocked.add(channel)
                changed.append(item)
                self._log.exception("instagram_account_blocked", exc, post_id=item["id"])
                continue
            except PublishError as exc:
                final = not exc.retryable or int(item.get("attempts") or 0) >= max_attempts
                item["status"] = FAILED if final else item.get("status", QUEUED)
                if final:
                    item.pop("container_id", None)
                item["error"] = str(exc)[:500]
                self.touched.append(self.outbox.save(item))
                changed.append(item)
                self._log.exception("instagram_publish_failed", exc, post_id=item["id"])
                continue
            sent[channel] = sent.get(channel, 0) + 1
            last[channel] = now
            changed.append(item)
            self._log.info(
                "instagram_post_published",
                post_id=item["id"], media_id=item.get("media_id"),
                trial=bool(item.get("trial")),
            )
        return changed

    # --------------------------------------------------------------- figures

    def publishing_allowance(self, channel_id: str) -> tuple[int, int] | None:
        """(used, total) of the rolling 24-hour publishing allowance."""
        self._acting = channel_id
        body = self._call(
            "GET", f"{channel_id}/content_publishing_limit",
            {"fields": "quota_usage,config"},
        )
        rows = body.get("data") or []
        if not rows:
            return None
        row = rows[0]
        total = int(((row.get("config") or {}).get("quota_total")) or 0)
        return int(row.get("quota_usage") or 0), total

    def _media_metrics(self, media_id: str) -> tuple[MetricRow, ...]:
        try:
            try:
                body = self._call(
                    "GET", f"{media_id}/insights",
                    {"metric": ",".join(name for name, *_ in _INSIGHTS)},
                )
            except InvalidPostError as exc:
                if "ig_reels" not in str(exc):
                    raise
                # A carousel is not a Reel, and asking for a Reel-only figure
                # makes Instagram refuse the whole request. Ask again for the
                # figures every kind of post has.
                body = self._call(
                    "GET", f"{media_id}/insights",
                    {"metric": ",".join(
                        name for name, *_ in _INSIGHTS
                        if not name.startswith("ig_reels")
                    )},
                )
        except InvalidPostError as exc:
            # A trial reel, or one too new to have figures, is refused rather
            # than returned empty. That is not worth losing the others for.
            self._log.warning(
                "instagram_insights_unavailable",
                media_id=media_id, error=str(exc)[:200],
            )
            return ()
        try:
            extra = self._call(
                "GET", f"{media_id}/insights",
                {"metric": ",".join(name for name, *_ in _EXTRA_INSIGHTS)},
            )
            body = {"data": list(body.get("data") or []) + list(extra.get("data") or [])}
        except (InvalidPostError, PublishError) as exc:
            self._log.info("instagram_extra_insights_unavailable",
                           media_id=media_id, error=str(exc)[:120])
        values: dict[str, float] = {}
        for row in body.get("data") or []:
            points = row.get("values") or []
            raw = points[0].get("value") if points else row.get("total_value", {}).get("value")
            try:
                values[str(row.get("name"))] = float(raw or 0.0)
            except (TypeError, ValueError):
                continue
        return tuple(
            MetricRow(type=kind, name=label, value=values[name] * scale)
            for name, kind, label, scale in _INSIGHTS + _EXTRA_INSIGHTS
            if name in values
        )

    def fetch_post_metrics(self, channel_id: str, limit: int = 200) -> list[PostMetrics]:
        """Per-post figures for what this account published through here."""
        self._acting = channel_id
        done = [
            i for i in self.outbox.for_channel(channel_id, PUBLISHED)
            if i.get("media_id")
        ]
        done.sort(key=lambda i: str(i.get("published_at") or ""), reverse=True)
        collected = [
            PostMetrics(
                post_id=str(item["id"]),
                service=Service.INSTAGRAM.value,
                sent_at=_parse_dt(item.get("published_at")),
                metrics=self._media_metrics(str(item["media_id"])),
            )
            for item in done[:limit]
        ]
        self._log.info(
            "instagram_post_metrics_fetched",
            channel_id_suffix=channel_id[-4:], posts=len(collected),
            requests=self.request_count,
        )
        return collected

    def fetch_metrics(
        self, channel_id: str, start: datetime, end: datetime
    ) -> tuple[list[MetricRow], datetime | None]:
        """Window totals, summed from the posts published inside the window."""
        totals: dict[str, MetricRow] = {}
        lo, hi = _utc(start), _utc(end)
        for post in self.fetch_post_metrics(channel_id):
            if post.sent_at is None or not (lo <= post.sent_at <= hi):
                continue
            for row in post.metrics:
                if row.type in ("averageTimeWatched",):
                    continue  # an average of averages would mean nothing
                seen = totals.get(row.type)
                totals[row.type] = row.model_copy(
                    update={"value": row.value + (seen.value if seen else 0.0)}
                )
        return list(totals.values()), self._now()
