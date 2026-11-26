"""YouTube Shorts, posted to directly (no Buffer in between).

Responsibility: upload Shorts through YouTube's Data API, behind the same
``Publisher`` seam Buffer and the direct Instagram publisher sit behind, so a
channel moves off Buffer by changing ``provider:`` in ``accounts.yaml``.

**The outbox, again.** YouTube has no "publish at" for an upload: a video is
public the moment processing ends (a ``publishAt`` exists, but only for a
video held private, which costs it the Shorts shelf's first hours). So, as
with Instagram, ``create_post`` holds the post in ``outbox/`` and
``publish_due`` sends what has come due. The files share Instagram's folder
and differ by prefix (``yto-``), so neither publisher sees the other's.

**Credentials.** One OAuth refresh token per channel: a Brand Account channel
is chosen at consent time, so even channels under one Google login need one
each (``YT_REFRESH_TOKEN_n``). The Cloud project's client id and secret are
shared (``YT_CLIENT_ID``, ``YT_CLIENT_SECRET``). An access token is minted
from the refresh token at call time and never stored. ``scripts/yt_connect.py``
is the one-time consent step, run on the operator's laptop.

**Quota.** Every project has a daily unit budget, and an upload is by far the
dearest call (1,600 units in the long-standing docs; later reports describe a
separate per-day upload bucket — the figures disagree, read the project's own
Cloud Console). A small ledger beside the outbox counts the day's uploads and
units, and the publisher refuses to start an upload past the cap rather than
discover the refusal from a 403 after the file has been sent.

**Metrics.** ``videos.list part=statistics``: views, likes, comments. Watch
time is the YouTube Analytics API, a different scope and endpoint: TODO.

Raw HTTPS through ``requests`` rather than ``google-api-python-client``: three
endpoints do not justify a dependency tree, and the fake session the other
publishers are tested with covers this one too.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

import requests

from src.errors import (
    AuthError,
    InvalidPostError,
    PublishError,
    QuotaError,
    RateLimitError,
)
from src.logging import StructuredLogger
from src.platforms import Service, limits_for
from src.ports import SystemClock
from src.publishers.base import (
    MetricRow,
    PostMetrics,
    PublishedPost,
    Publisher,
    PublishRequest,
    QueueState,
)
from src.publishers.instagram import (
    CANCELLED,
    FAILED,
    PUBLISHED,
    PUBLISHING,
    QUEUED,
    Outbox,
    _parse_dt,
    _utc,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
#: Upload for the insert, readonly for the figures (``videos.list``).
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
REQUEST_TIMEOUT_SEC = 60
UPLOAD_TIMEOUT_SEC = 300
ID_PREFIX = "yto-"
QUOTA_FILE = "youtube_quota.json"

#: Resumable uploads go in chunks that are multiples of 256 KiB. 8 MiB keeps a
#: 60-second Short under a dozen requests and lets a dropped connection resume.
CHUNK_SIZE = 8 * 1024 * 1024
#: Unit costs as documented. The insert's is the one that matters.
UPLOAD_UNITS = 1600
LIST_UNITS = 1
#: The default per-project daily cap: uploads first (the figure the review
#: settled on), units as a second guard against the documented 10,000.
DEFAULT_DAILY_UPLOADS = 100
DEFAULT_DAILY_UNITS = 10_000
#: YouTube's quota day resets at midnight Pacific.
QUOTA_ZONE = ZoneInfo("America/Los_Angeles")

POLL_INTERVAL_SEC = 15.0
POLL_ATTEMPTS = 12

#: A post this far past its slot is not sent (same reasoning as Instagram's).
DEFAULT_MAX_LATE = timedelta(hours=6)

CATEGORY_MUSIC = "10"
#: YouTube's total tag budget, in characters.
TAGS_MAX_CHARS = 500
_HASHTAG = re.compile(r"(?<![\w#])#(\w+)")

#: ``error.errors[].reason`` values and what each means for the run.
_AUTH_REASONS = {
    "authError", "forbidden", "insufficientPermissions",
    "youtubeSignupRequired", "unauthorized",
}
_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"}
_RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
_UPLOAD_FINAL = {"processed"}
_UPLOAD_BAD = {"failed", "rejected", "deleted"}

#: YouTube's statistics, mapped to the names the pipeline already reads.
_STATISTICS: tuple[tuple[str, str, str], ...] = (
    ("viewCount", "views", "Views"),
    ("likeCount", "reactions", "Reactions"),
    ("commentCount", "comments", "Comments"),
)
# TODO: watch time and average view duration live in the YouTube Analytics
# API (youtubeAnalytics.readonly, reports.query), not in videos.list.


def hashtags_to_tags(caption: str, budget: int = TAGS_MAX_CHARS) -> list[str]:
    """The caption's hashtags as YouTube tags, deduplicated, inside the budget."""
    tags: list[str] = []
    seen: set[str] = set()
    used = 0
    for match in _HASHTAG.finditer(caption or ""):
        tag = match.group(1)
        if tag.lower() in seen:
            continue
        # YouTube counts the tag plus a separator against the budget.
        if used + len(tag) + 1 > budget:
            break
        seen.add(tag.lower())
        tags.append(tag)
        used += len(tag) + 1
    return tags


def short_title(title: str | None, fallback: str) -> str:
    """A title YouTube takes: no angle brackets, inside the limit, never empty."""
    text = (title or "").strip()
    if not text:
        lines = [line.strip() for line in fallback.splitlines() if line.strip()]
        text = lines[0] if lines else ""
    text = text.replace("<", "(").replace(">", ")")
    limit = limits_for(Service.YOUTUBE).title_max or 100
    return text[:limit] or "Untitled"


def description_for(caption: str, first_comment: str | None) -> str:
    """Caption plus the first-comment line: Shorts have no first-comment API,
    and the song credit the comment carries belongs somewhere."""
    parts = [caption.rstrip()]
    if first_comment and first_comment.strip():
        parts.append(first_comment.strip())
    text = "\n\n".join(parts).replace("<", "(").replace(">", ")")
    return text[: limits_for(Service.YOUTUBE).description_max]


class YouTubeOutbox(Outbox):
    """Instagram's outbox, listing only this publisher's files."""

    def items(self) -> list[dict[str, Any]]:
        if not self._dir.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for path in sorted(self._dir.glob(f"{ID_PREFIX}*.json")):
            item = self.load(path.stem)
            if item is not None:
                found.append(item)
        return found


class QuotaLedger:
    """The day's spend against the project's quota, in one small file.

    Per project, not per channel: every channel's uploads draw on the same
    budget, so the file is shared and keyed by YouTube's own day.
    """

    def __init__(
        self, path: Path, *, daily_uploads: int, daily_units: int
    ) -> None:
        self.path = path
        self.daily_uploads = daily_uploads
        self.daily_units = daily_units

    @staticmethod
    def day(now: datetime) -> str:
        return _utc(now).astimezone(QUOTA_ZONE).strftime("%Y-%m-%d")

    def load(self, now: datetime) -> dict[str, Any]:
        state: dict[str, Any] = {}
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                state = raw if isinstance(raw, dict) else {}
            except ValueError:
                state = {}
        if state.get("day") != self.day(now):
            state = {"day": self.day(now), "uploads": 0, "units": 0}
        return state

    def can_upload(self, now: datetime) -> bool:
        state = self.load(now)
        return (
            int(state.get("uploads") or 0) < self.daily_uploads
            and int(state.get("units") or 0) + UPLOAD_UNITS <= self.daily_units
        )

    def charge(self, now: datetime, units: int, *, upload: bool = False) -> Path:
        state = self.load(now)
        state["units"] = int(state.get("units") or 0) + units
        if upload:
            state["uploads"] = int(state.get("uploads") or 0) + 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path


class YouTubePublisher(Publisher):
    """Uploads Shorts through the YouTube Data API."""

    def __init__(
        self,
        refresh_token: str,
        log: StructuredLogger,
        *,
        client_id: str,
        client_secret: str,
        outbox_dir: Path,
        token_secret: str = "YT_REFRESH_TOKEN",
        daily_uploads: int = DEFAULT_DAILY_UPLOADS,
        daily_units: int = DEFAULT_DAILY_UNITS,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        now: Callable[[], datetime] | None = None,
        download_dir: Path | None = None,
    ) -> None:
        if not refresh_token:
            raise AuthError(f"{token_secret} is empty")
        if not client_id or not client_secret:
            raise AuthError("YT_CLIENT_ID / YT_CLIENT_SECRET are empty")
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        #: The NAME of the slot, for log lines. Never the value.
        self._token_secret = token_secret
        self._log = log
        self._session = session or requests.Session()
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._now: Callable[[], datetime] = now or SystemClock().now
        self._download_dir = download_dir
        self._access: tuple[str, datetime] | None = None
        self.outbox = YouTubeOutbox(outbox_dir)
        self.quota = QuotaLedger(
            outbox_dir / QUOTA_FILE,
            daily_uploads=daily_uploads, daily_units=daily_units,
        )
        #: True once Google has refused the refresh token: nothing more is
        #: tried on this slot until the operator re-runs the consent step.
        self.reauth_needed = False
        self.request_count = 0
        self.touched: list[Path] = []
        self.checkpoint: Callable[[Path, str], None] | None = None

    # ----------------------------------------------------------------- tokens

    def _mark_reauth(self, detail: str) -> AuthError:
        self.reauth_needed = True
        self._log.error("youtube_reauth_needed", secret=self._token_secret, error=detail[:200])
        return AuthError(
            f"YouTube refused the credentials in {self._token_secret}: {detail}. "
            f"Re-run scripts/yt_connect.py for this channel and store the new "
            f"refresh token in that secret."
        )

    def _access_token(self) -> str:
        if self.reauth_needed:
            raise AuthError(f"{self._token_secret} needs re-authorisation")
        now = self._now()
        if self._access and self._access[1] - now > timedelta(seconds=60):
            return self._access[0]
        self.request_count += 1
        try:
            response = self._session.request(
                "POST", TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=REQUEST_TIMEOUT_SEC,
            )
        except requests.RequestException as exc:
            raise RateLimitError(f"Google's token endpoint did not answer: {exc}") from exc
        try:
            body: Any = response.json()
        except ValueError:
            body = {}
        if response.status_code < 400 and isinstance(body, dict) and body.get("access_token"):
            ttl = int(body.get("expires_in") or 3600)
            self._access = (str(body["access_token"]), now + timedelta(seconds=ttl))
            return self._access[0]
        error = str((body or {}).get("error") or f"HTTP {response.status_code}")
        detail = f"{error}: {(body or {}).get('error_description') or ''}".strip(": ")
        if response.status_code >= 500:
            raise PublishError(f"Google's token endpoint failed: {detail}")
        # invalid_grant: revoked, expired (unverified projects' tokens die after
        # a week), or the channel's password changed. invalid_client: the
        # project's client id/secret. Either way a person has to act.
        raise self._mark_reauth(detail)

    # --------------------------------------------------------------- plumbing

    @staticmethod
    def _classify(status: int, body: Any, text: str) -> PublishError:
        error = body.get("error") if isinstance(body, dict) else None
        error = error if isinstance(error, dict) else {}
        first = (error.get("errors") or [{}])[0] if isinstance(error.get("errors"), list) else {}
        reason = str((first or {}).get("reason") or error.get("status") or "")
        message = str(error.get("message") or text[:300])
        detail = f"{message} (HTTP {status}, reason {reason or 'none'})"
        if status == 401 or reason in _AUTH_REASONS:
            return AuthError(detail)
        if reason in _QUOTA_REASONS:
            return QuotaError(f"YouTube's quota or upload allowance is spent: {detail}")
        if status == 429 or reason in _RATE_REASONS:
            return RateLimitError(f"YouTube rate limited the request: {detail}")
        if status >= 500:
            return PublishError(f"YouTube had a temporary failure: {detail}")
        return InvalidPostError(f"YouTube rejected the request: {detail}")

    def _send(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """One HTTP call with the access token, retrying network failures."""
        last: Exception | None = None
        extra = dict(kwargs.pop("headers", None) or {})
        timeout = kwargs.pop("timeout", REQUEST_TIMEOUT_SEC)
        for attempt in range(1, self._max_attempts + 1):
            token = self._access_token()
            self.request_count += 1
            try:
                return self._session.request(
                    method, url, headers={"Authorization": f"Bearer {token}", **extra},
                    timeout=timeout, **kwargs,
                )
            except requests.RequestException as exc:
                last = RateLimitError(f"YouTube request failed: {exc}")
                if attempt == self._max_attempts:
                    raise last from exc
                self._sleep(2**attempt)
        raise last or PublishError("YouTube request failed")  # pragma: no cover

    def _api(
        self, method: str, path: str, *, params: Mapping[str, Any] | None = None,
        json_body: Any = None, units: int = LIST_UNITS,
    ) -> dict[str, Any]:
        """One Data API call. Charged to the ledger whatever the answer: YouTube
        bills a refused request too."""
        for attempt in range(1, self._max_attempts + 1):
            response = self._send(
                method, f"{API_BASE}/{path.lstrip('/')}",
                params=dict(params or {}), json=json_body,
            )
            self.touched.append(self.quota.charge(self._now(), units))
            try:
                body: Any = response.json()
            except ValueError:
                body = None
            if response.status_code < 400:
                return body if isinstance(body, dict) else {}
            failure = self._classify(response.status_code, body, response.text)
            if isinstance(failure, AuthError):
                raise self._mark_reauth(str(failure))
            if failure.retryable and attempt < self._max_attempts:
                self._sleep(2**attempt)
                continue
            raise failure
        raise PublishError("YouTube request failed")  # pragma: no cover

    # -------------------------------------------------------------- the seam

    def queue_state(self, channel_id: str) -> QueueState:
        waiting = self.outbox.for_channel(channel_id, QUEUED, PUBLISHING)
        due = [d for d in (_parse_dt(i.get("scheduled_for")) for i in waiting) if d]
        return QueueState(depth=len(waiting), next_due=min(due) if due else None)

    def create_post(self, request: PublishRequest) -> PublishedPost:
        """Hold one post for its slot. Nothing is sent to YouTube here."""
        if request.service is not Service.YOUTUBE:
            raise InvalidPostError(
                f"the YouTube publisher cannot post to {request.service.value}"
            )
        if not (request.title or "").strip():
            raise InvalidPostError("YouTube requires a title and none was supplied")
        for held in self.outbox.for_channel(request.channel_id, QUEUED, PUBLISHING, PUBLISHED):
            if held.get("video_url") == request.video_url:
                self._log.warning("youtube_duplicate_not_held", post_id=held.get("id"))
                when = _parse_dt(held.get("scheduled_for")) or request.scheduled_for
                return PublishedPost(post_id=str(held.get("id")), scheduled_for=when)
        post_id = f"{ID_PREFIX}{uuid.uuid4()}"
        item: dict[str, Any] = {
            "id": post_id,
            "channel_id": request.channel_id,
            "status": QUEUED,
            "video_url": request.video_url,
            "title": request.title,
            "caption": request.text,
            "first_comment": request.first_comment,
            "notify_subscribers": request.notify_subscribers,
            "scheduled_for": _utc(request.scheduled_for).isoformat(),
            "created_at": self._now().isoformat(),
            "attempts": 0,
        }
        self.touched.append(self.outbox.save(item))
        self._log.info("youtube_post_held", post_id=post_id, **request.redacted())
        return PublishedPost(post_id=post_id, scheduled_for=request.scheduled_for)

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
            raise PublishError(f"no held YouTube post with id {post_id}")
        if item.get("status") in (PUBLISHED, PUBLISHING):
            raise PublishError(
                f"{post_id} has already gone to YouTube and can only be removed in YouTube Studio"
            )
        item["status"] = CANCELLED
        self.touched.append(self.outbox.save(item))
        self._log.info("youtube_post_cancelled", post_id=post_id)

    # ------------------------------------------------------------ publishing

    def _metadata(self, item: Mapping[str, Any]) -> dict[str, Any]:
        caption = str(item.get("caption") or "")
        return {
            "snippet": {
                "title": short_title(item.get("title"), caption),
                "description": description_for(caption, item.get("first_comment")),
                "tags": hashtags_to_tags(caption),
                "categoryId": CATEGORY_MUSIC,
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
                "embeddable": True,
            },
        }

    def _fetch_video(self, url: str) -> Path:
        """The rendered file, pulled to disk: YouTube takes bytes, not a URL."""
        self.request_count += 1
        try:
            response = self._session.request("GET", url, stream=True, timeout=UPLOAD_TIMEOUT_SEC)
        except requests.RequestException as exc:
            raise PublishError(f"could not fetch the video: {exc}") from exc
        if response.status_code >= 400:
            raise PublishError(f"could not fetch the video: HTTP {response.status_code} from {url}")
        if self._download_dir is not None:
            self._download_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            delete=False, suffix=".mp4", dir=self._download_dir,
        )
        with handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        path = Path(handle.name)
        if path.stat().st_size == 0:
            path.unlink(missing_ok=True)
            raise PublishError(f"the video at {url} is empty")
        return path

    def _start_upload(self, item: dict[str, Any], size: int) -> str:
        """Open a resumable upload session. This is the call that costs."""
        response = self._send(
            "POST", UPLOAD_URL,
            params={
                "uploadType": "resumable",
                "part": "snippet,status",
                "notifySubscribers": "true" if item.get("notify_subscribers") else "false",
            },
            headers={
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(size),
            },
            json=self._metadata(item),
        )
        self.touched.append(self.quota.charge(self._now(), UPLOAD_UNITS, upload=True))
        if response.status_code >= 400:
            try:
                body: Any = response.json()
            except ValueError:
                body = None
            failure = self._classify(response.status_code, body, response.text)
            if isinstance(failure, AuthError):
                raise self._mark_reauth(str(failure))
            raise failure
        location = str(response.headers.get("Location") or "")
        if not location:
            raise PublishError("YouTube opened no upload session (no Location header)")
        return location

    def _upload_offset(self, upload_url: str, size: int) -> int | dict[str, Any]:
        """Ask the session how much it holds: an offset to resume from, or the
        finished video when a previous run completed the upload before dying."""
        response = self._send(
            "PUT", upload_url,
            headers={"Content-Range": f"bytes */{size}", "Content-Length": "0"},
            timeout=UPLOAD_TIMEOUT_SEC,
        )
        if response.status_code in (200, 201):
            body = response.json()
            return body if isinstance(body, dict) else {}
        if response.status_code == 308:
            had = str(response.headers.get("Range") or "")
            match = re.search(r"-(\d+)$", had)
            return int(match.group(1)) + 1 if match else 0
        if response.status_code in (404, 410):
            raise PublishError("YouTube's upload session expired; a new one is opened next run")
        try:
            body = response.json()
        except ValueError:
            body = None
        raise self._classify(response.status_code, body, response.text)

    def _send_bytes(self, item: dict[str, Any], path: Path, size: int) -> dict[str, Any]:
        upload_url = str(item["upload_url"])
        state = self._upload_offset(upload_url, size)
        if isinstance(state, dict):
            return state
        offset = state
        with path.open("rb") as handle:
            while offset < size:
                handle.seek(offset)
                chunk = handle.read(CHUNK_SIZE)
                end = offset + len(chunk) - 1
                response = self._send(
                    "PUT", upload_url, data=chunk,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{size}",
                    },
                    timeout=UPLOAD_TIMEOUT_SEC,
                )
                if response.status_code in (200, 201):
                    body = response.json()
                    return body if isinstance(body, dict) else {}
                if response.status_code == 308:
                    had = str(response.headers.get("Range") or "")
                    match = re.search(r"-(\d+)$", had)
                    offset = int(match.group(1)) + 1 if match else end + 1
                    continue
                try:
                    body = response.json()
                except ValueError:
                    body = None
                failure = self._classify(response.status_code, body, response.text)
                if isinstance(failure, AuthError):
                    raise self._mark_reauth(str(failure))
                raise failure
        raise PublishError("YouTube took every byte and returned no video")  # pragma: no cover

    def _wait_processed(self, item: dict[str, Any]) -> None:
        """Poll processing. Informational: the video exists either way, and a
        second upload is the one thing a slow processor must never cause."""
        video_id = str(item["video_id"])
        for _ in range(POLL_ATTEMPTS):
            body = self._api(
                "GET", "videos",
                params={"part": "status,processingDetails", "id": video_id},
            )
            rows = body.get("items") or []
            status = (rows[0].get("status") or {}) if rows else {}
            upload_status = str(status.get("uploadStatus") or "")
            item["processing"] = upload_status or "unknown"
            if upload_status in _UPLOAD_FINAL:
                return
            if upload_status in _UPLOAD_BAD:
                reason = status.get("failureReason") or status.get("rejectionReason") or upload_status
                item["status"] = FAILED
                item["error"] = f"YouTube {upload_status} the video: {reason}"
                self._log.warning("youtube_processing_failed", post_id=item["id"], reason=str(reason))
                return
            self._sleep(POLL_INTERVAL_SEC)
        self._log.info("youtube_still_processing", post_id=item["id"], video_id=video_id)

    def _publish_one(self, item: dict[str, Any]) -> None:
        """Send one held post. Saves after every step that cannot be redone."""
        now = self._now()
        if not item.get("upload_url") and not self.quota.can_upload(now):
            state = self.quota.load(now)
            self._log.warning(
                "quota_exhausted", day=state.get("day"), uploads=state.get("uploads"),
                units=state.get("units"), cap=self.quota.daily_uploads,
            )
            raise QuotaError(
                f"the project's daily YouTube cap ({self.quota.daily_uploads} uploads, "
                f"{self.quota.daily_units} units) is spent for {state.get('day')}"
            )

        # Counted only once something is tried: a day spent waiting on quota
        # must not use up the retries a real failure gets.
        item["attempts"] = int(item.get("attempts") or 0) + 1
        path = self._fetch_video(str(item["video_url"]))
        try:
            size = path.stat().st_size
            if not item.get("upload_url"):
                item["upload_url"] = self._start_upload(item, size)
                item["upload_size"] = size
            # Saved as `publishing` BEFORE the bytes go: if the job dies
            # mid-upload, the next run resumes this session instead of opening
            # another, which would cost another 1,600 units and risk a double.
            item["status"] = PUBLISHING
            claim = self.outbox.save(item)
            self.touched.append(claim)
            if self.checkpoint is not None:
                self.checkpoint(claim, "claim")
            try:
                video = self._send_bytes(item, path, size)
            except PublishError as exc:
                if "expired" in str(exc):
                    item.pop("upload_url", None)
                raise
        finally:
            path.unlink(missing_ok=True)

        item["video_id"] = str(video.get("id") or "") or None
        if not item["video_id"]:
            raise PublishError(f"YouTube returned no video id: {video}")
        item["status"] = PUBLISHED
        item["published_at"] = self._now().isoformat()
        item.pop("error", None)
        item.pop("upload_url", None)
        sent = self.outbox.save(item)
        self.touched.append(sent)
        if self.checkpoint is not None:
            try:
                self.checkpoint(sent, "sent")
            except Exception as exc:  # noqa: BLE001 - the post is out
                self._log.exception("youtube_sent_not_recorded", exc, post_id=item["id"])
        try:
            self._wait_processed(item)
        except PublishError as exc:
            self._log.warning("youtube_processing_unknown", post_id=item["id"], error=str(exc)[:200])
        self.touched.append(self.outbox.save(item))

    def publish_due(
        self,
        *,
        channel_ids: set[str] | None = None,
        max_per_channel: int = 1,
        max_late: timedelta = DEFAULT_MAX_LATE,
        max_attempts: int = 3,
        send_next: bool = False,
    ) -> list[dict[str, Any]]:
        """Send every held post whose slot has arrived. Returns what changed.

        A credentials failure stops that channel for the run; a quota failure
        stops every channel, because the budget is the project's.
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
        posted = {
            (str(i.get("channel_id")), i.get("video_url")) for i in self.outbox.items()
            if i.get("status") == PUBLISHED and i.get("video_url")
        }
        for item in waiting:
            channel = str(item.get("channel_id"))
            due = _parse_dt(item.get("scheduled_for"))
            if item.get("status") == QUEUED and (channel, item.get("video_url")) in posted:
                item["status"] = FAILED
                item["error"] = "this video was already posted on this channel; not sent again"
                self.touched.append(self.outbox.save(item)); changed.append(item)
                self._log.warning("youtube_duplicate_skipped", post_id=item["id"])
                continue
            if sent.get(channel, 0) >= max_per_channel or channel in blocked or self.reauth_needed:
                continue
            if send_next and due is not None and due > now and item.get("status") == QUEUED:
                due = now
            if due is None or due > now:
                continue
            if item.get("status") == QUEUED and now - due > max_late:
                item["status"] = FAILED
                item["error"] = f"missed its slot by more than {max_late} and was not sent"
                self.touched.append(self.outbox.save(item)); changed.append(item)
                self._log.warning("youtube_post_expired", post_id=item["id"])
                continue
            try:
                self._publish_one(item)
            except QuotaError as exc:
                # Left where it was: the next slot is the retry.
                item["status"] = PUBLISHING if item.get("upload_url") else QUEUED
                item["error"] = str(exc)[:500]
                self.touched.append(self.outbox.save(item)); changed.append(item)
                self._log.warning("youtube_quota_refused", post_id=item["id"], error=str(exc)[:200])
                break
            except AuthError as exc:
                item["status"] = PUBLISHING if item.get("upload_url") else QUEUED
                item["error"] = str(exc)[:500]
                self.touched.append(self.outbox.save(item)); changed.append(item)
                blocked.add(channel)
                self._log.exception("youtube_channel_blocked", exc, post_id=item["id"])
                continue
            except PublishError as exc:
                final = not exc.retryable or int(item.get("attempts") or 0) >= max_attempts
                item["status"] = FAILED if final else (PUBLISHING if item.get("upload_url") else QUEUED)
                if final:
                    item.pop("upload_url", None)
                item["error"] = str(exc)[:500]
                self.touched.append(self.outbox.save(item)); changed.append(item)
                self._log.exception("youtube_publish_failed", exc, post_id=item["id"])
                continue
            sent[channel] = sent.get(channel, 0) + 1
            changed.append(item)
            self._log.info(
                "youtube_post_published", post_id=item["id"],
                video_id=item.get("video_id"), processing=item.get("processing"),
            )
        return changed

    # --------------------------------------------------------------- figures

    def _statistics(self, video_ids: list[str]) -> dict[str, tuple[MetricRow, ...]]:
        """Per-video figures, fifty ids a call (one unit each call)."""
        out: dict[str, tuple[MetricRow, ...]] = {}
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start:start + 50]
            try:
                body = self._api(
                    "GET", "videos", params={"part": "statistics", "id": ",".join(batch)},
                )
            except InvalidPostError as exc:
                self._log.warning("youtube_statistics_unavailable", error=str(exc)[:200])
                continue
            for row in body.get("items") or []:
                stats = row.get("statistics") or {}
                metrics: list[MetricRow] = []
                for key, kind, label in _STATISTICS:
                    if key not in stats:
                        continue  # likes hidden, or comments off: no figure, not zero
                    try:
                        metrics.append(MetricRow(type=kind, name=label, value=float(stats[key])))
                    except (TypeError, ValueError):
                        continue
                out[str(row.get("id"))] = tuple(metrics)
        return out

    def fetch_post_metrics(self, channel_id: str, limit: int = 200) -> list[PostMetrics]:
        """Per-post figures for what this channel published through here."""
        done = [i for i in self.outbox.for_channel(channel_id, PUBLISHED) if i.get("video_id")]
        done.sort(key=lambda i: str(i.get("published_at") or ""), reverse=True)
        done = done[:limit]
        stats = self._statistics([str(i["video_id"]) for i in done]) if done else {}
        collected = [
            PostMetrics(
                post_id=str(item["id"]),
                service=Service.YOUTUBE.value,
                sent_at=_parse_dt(item.get("published_at")),
                metrics=stats.get(str(item["video_id"]), ()),
                fetched_at=self._now(),
            )
            for item in done
        ]
        self._log.info(
            "youtube_post_metrics_fetched",
            channel_id_suffix=channel_id[-4:], posts=len(collected), requests=self.request_count,
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
                seen = totals.get(row.type)
                totals[row.type] = row.model_copy(
                    update={"value": row.value + (seen.value if seen else 0.0)}
                )
        return list(totals.values()), self._now()
