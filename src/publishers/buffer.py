"""Buffer GraphQL publisher (SPEC §0, §8).

Responsibility: implement ``Publisher`` against Buffer's GraphQL API.

API surface (verified against the live schema on 2026-08-12 — see README §0):

* One endpoint, ``POST https://api.buffer.com``, ``Authorization: Bearer <key>``
  with a personal API key. The legacy REST API is not used: Buffer stopped
  accepting new developer app registrations there (SPEC §0).
* ``createPost(input: CreatePostInput!): PostActionPayload!`` — a *union*, not a
  nullable object. Every failure mode is a distinct member type, which is what
  lets this module map errors to typed exceptions without ever reading a message
  string (SPEC §2.2).
* Media is URL-only: ``VideoAssetInput.url`` is ``String!`` and there is no
  upload field. ``thumbnailUrl`` is documented as "do not use — the API rejects
  video assets that set this field", so it is never sent.
* ``schedulingType: automatic`` asks Buffer's workers to publish unattended;
  ``notification`` only sends a reminder to a human. SPEC §0 is emphatic that
  reminder mode is not automation, so this module requests ``automatic`` and
  *verifies* what came back rather than assuming.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

import requests

from src.config import PostType
from src.errors import (
    AuthError,
    InvalidPostError,
    PublishError,
    QuotaError,
    RateLimitError,
)
from src.logging import StructuredLogger
from src.platforms import Service
from src.publishers.base import (
    MetricRow,
    PublishedPost,
    Publisher,
    PublishRequest,
)

ENDPOINT = "https://api.buffer.com"
REQUEST_TIMEOUT_SEC = 60

#: Selection set shared by createPost and editPost. ``__typename`` first because
#: it is what the error mapping dispatches on.
_POST_ACTION_PAYLOAD = """
    __typename
    ... on PostActionSuccess {
      post { id dueAt status schedulingType }
    }
    ... on NotFoundError { message }
    ... on UnauthorizedError { message }
    ... on UnexpectedError { message }
    ... on LimitReachedError { message }
    ... on InvalidInputError { message }
    ... on RestProxyError { code message link }
"""

CREATE_POST = f"""
mutation UgcFactoryCreatePost($input: CreatePostInput!) {{
  createPost(input: $input) {{{_POST_ACTION_PAYLOAD}}}
}}
"""

DELETE_POST = """
mutation UgcFactoryDeletePost($input: DeletePostInput!) {
  deletePost(input: $input) {
    __typename
    ... on DeletePostSuccess { id }
    ... on VoidMutationError { message }
  }
}
"""

ACCOUNT = """
query UgcFactoryAccount {
  account { id organizations { id name } }
}
"""

POSTS = """
query UgcFactoryPosts($input: PostsInput!, $first: Int) {
  posts(input: $input, first: $first) {
    edges { node { id dueAt status schedulingType channelId } }
  }
}
"""

#: Union members that mean "this will never succeed as sent". Mapping by
#: ``__typename`` — not by message text — is what SPEC §2.2 requires: Buffer can
#: reword every one of these without inverting our retry logic.
_ERROR_MAP: dict[str, type[PublishError]] = {
    "UnauthorizedError": AuthError,
    "InvalidInputError": InvalidPostError,
    "NotFoundError": InvalidPostError,
    "LimitReachedError": QuotaError,
    # Genuinely unexpected server-side trouble is the one union member worth
    # retrying; PublishError.retryable is True.
    "UnexpectedError": PublishError,
}


class BufferPublisher(Publisher):
    """Publishes to a Buffer channel over GraphQL."""

    def __init__(
        self,
        api_key: str,
        log: StructuredLogger,
        *,
        organization_id: str | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
    ) -> None:
        if not api_key:
            raise AuthError("Buffer API key is empty")
        self._api_key = api_key
        self._log = log
        self._session = session or requests.Session()
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._organization_id = organization_id
        #: SPEC §3 — the free plan allows 3,000 requests per 30 days. Counting
        #: here rather than at the call sites means nothing can bypass the meter.
        self.request_count = 0

    # ----------------------------------------------------------------- plumbing

    def _gql(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one GraphQL operation, retrying only transient failures."""
        last: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self.request_count += 1
            try:
                response = self._session.request(
                    "POST",
                    ENDPOINT,
                    json={"query": query, "variables": dict(variables)},
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                    },
                    timeout=REQUEST_TIMEOUT_SEC,
                )
            except requests.RequestException as exc:
                last = RateLimitError(f"Buffer request failed: {exc}")
                if attempt == self._max_attempts:
                    raise last from exc
                self._sleep(2**attempt)
                continue

            if response.status_code in (401, 403):
                raise AuthError(
                    f"Buffer rejected the API key (HTTP {response.status_code}). "
                    f"Check the key is a current personal access token."
                )
            if response.status_code == 429:
                # Retryable, but each retry costs another request against the
                # 3,000/30-day budget, so back off rather than hammering.
                last = RateLimitError("Buffer rate limited the request (HTTP 429)")
                if attempt == self._max_attempts:
                    raise last
                self._sleep(2**attempt)
                continue
            if response.status_code >= 500:
                last = PublishError(f"Buffer returned HTTP {response.status_code}")
                if attempt == self._max_attempts:
                    raise last
                self._sleep(2**attempt)
                continue
            if response.status_code >= 400:
                raise InvalidPostError(
                    f"Buffer rejected the request (HTTP {response.status_code}): "
                    f"{response.text[:400]}"
                )

            try:
                body: dict[str, Any] = response.json()
            except ValueError as exc:
                raise PublishError(
                    f"Buffer returned non-JSON: {response.text[:300]}"
                ) from exc

            # Top-level `errors` means the *document* failed (validation, auth),
            # which no amount of retrying fixes.
            if body.get("errors"):
                messages = "; ".join(
                    str(e.get("message", e)) for e in body["errors"]
                )
                raise InvalidPostError(f"Buffer GraphQL error: {messages[:500]}")
            data = body.get("data")
            if not isinstance(data, dict):
                raise PublishError(f"Buffer response had no data: {str(body)[:300]}")
            return data

        raise last or PublishError("Buffer request exhausted retries")

    def _raise_for_payload(self, payload: Mapping[str, Any], operation: str) -> None:
        """Translate a union error member into a typed exception."""
        typename = str(payload.get("__typename", ""))
        message = str(payload.get("message", "")) or "(no message)"

        if typename == "RestProxyError":
            # Buffer proxying an upstream (Instagram) error. The numeric code is
            # the stable signal; 4xx from the network is our bad payload, 5xx is
            # theirs and worth a retry.
            code = payload.get("code")
            detail = f"Buffer RestProxyError code={code}: {message[:300]}"
            try:
                numeric = int(code)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise PublishError(detail)
            if 400 <= numeric < 500:
                raise InvalidPostError(detail)
            raise PublishError(detail)

        error_cls = _ERROR_MAP.get(typename)
        if error_cls is not None:
            raise error_cls(f"Buffer {operation} failed ({typename}): {message[:300]}")

        raise PublishError(
            f"Buffer {operation} returned unrecognised payload {typename!r} — "
            f"the schema may have changed: {str(payload)[:300]}"
        )

    def _org_id(self) -> str:
        """Resolve and cache the organization id the API requires for queries."""
        if self._organization_id:
            return self._organization_id
        data = self._gql(ACCOUNT, {})
        orgs = ((data.get("account") or {}).get("organizations")) or []
        if not orgs:
            raise AuthError(
                "Buffer account has no organizations — the API key may belong "
                "to a user without an organization"
            )
        self._organization_id = str(orgs[0]["id"])
        self._log.info("buffer_org_resolved", organization_id=self._organization_id)
        return self._organization_id

    # ------------------------------------------------------------------- reads

    def queue_depth(self, channel_id: str) -> int:
        """Count posts occupying a queue slot (SPEC §4.1).

        ``scheduled`` and ``sending`` both hold a slot; ``sent`` has released
        one and ``draft``/``error`` never held one. Counting anything else would
        make the top-up job push too few or too many.
        """
        data = self._gql(
            POSTS,
            {
                "input": {
                    "organizationId": self._org_id(),
                    "filter": {
                        "channelIds": [channel_id],
                        "status": ["scheduled", "sending"],
                    },
                },
                "first": 100,
            },
        )
        edges = ((data.get("posts") or {}).get("edges")) or []
        depth = len(edges)
        self._log.info(
            "buffer_queue_depth", channel_id_suffix=channel_id[-4:], depth=depth
        )
        return depth

    def find_scheduled_post(
        self, channel_id: str, scheduled_for: datetime
    ) -> PublishedPost | None:
        """Look for a post already occupying this slot (SPEC §11 crash resume).

        Matches within a one-minute window rather than on an exact timestamp:
        Buffer normalises ``dueAt`` to its own schedule granularity, so an exact
        comparison would report "not found" and cause the double-push this
        function exists to prevent.
        """
        window = timedelta(minutes=1)
        data = self._gql(
            POSTS,
            {
                "input": {
                    "organizationId": self._org_id(),
                    "filter": {
                        "channelIds": [channel_id],
                        "status": ["scheduled", "sending", "sent"],
                        "dueAt": {
                            "gte": (scheduled_for - window).isoformat(),
                            "lte": (scheduled_for + window).isoformat(),
                        },
                    },
                },
                "first": 20,
            },
        )
        edges = ((data.get("posts") or {}).get("edges")) or []
        if not edges:
            return None
        node = edges[0]["node"]
        return PublishedPost(
            post_id=str(node["id"]),
            scheduled_for=_parse_dt(node.get("dueAt")),
            will_publish_automatically=node.get("schedulingType") == "automatic",
        )

    # ------------------------------------------------------------------ writes

    def create_post(self, request: PublishRequest) -> PublishedPost:
        self._log.info("buffer_create_post", **request.redacted())

        metadata = _metadata_for(request)
        variables = {
            "input": {
                "channelId": request.channel_id,
                "text": request.text,
                # URL-only: VideoAssetInput.url is String! and there is no
                # upload path. thumbnailUrl is deliberately omitted — the schema
                # documents that setting it makes the API reject the asset.
                "assets": [{"video": {"url": request.video_url}}],
                # customScheduled + dueAt pins the post to our computed slot.
                # addToQueue would instead defer to Buffer's own schedule and
                # silently ignore the spread we calculated.
                "mode": "customScheduled",
                "dueAt": request.scheduled_for.isoformat(),
                # The whole point of the system (SPEC §0/§1).
                "schedulingType": "automatic",
                # NON_NULL in the schema. True would park every post in an
                # approval queue that no cron job can clear.
                "needsApproval": False,
                **({"metadata": metadata} if metadata else {}),
            }
        }

        data = self._gql(CREATE_POST, variables)
        payload = data.get("createPost") or {}
        if payload.get("__typename") != "PostActionSuccess":
            self._raise_for_payload(payload, "createPost")

        post = payload.get("post") or {}
        post_id = post.get("id")
        if not post_id:
            raise PublishError(
                f"Buffer reported success without a post id: {str(payload)[:300]}"
            )

        scheduling = post.get("schedulingType")
        automatic = scheduling == "automatic"
        if not automatic:
            # SPEC §0: reminder mode is a push notification someone taps by
            # hand. Surfacing it as a hard failure is deliberate — a silent
            # downgrade would look like a working pipeline that never posts.
            raise InvalidPostError(
                f"Buffer accepted post {post_id} in {scheduling!r} mode, not "
                f"'automatic'. The channel is set to reminder-based publishing, "
                f"so nothing will publish unattended. Turn off reminders for "
                f"this channel in Buffer, or the account is not an Instagram "
                f"Business/Creator account."
            )

        result = PublishedPost(
            post_id=str(post_id),
            scheduled_for=_parse_dt(post.get("dueAt")),
            will_publish_automatically=automatic,
        )
        self._log.info(
            "buffer_post_created",
            post_id=result.post_id,
            due_at=post.get("dueAt"),
            status=post.get("status"),
        )
        return result

    def fetch_metrics(
        self, channel_id: str, start: datetime, end: datetime
    ) -> tuple[list[MetricRow], datetime | None]:
        """Aggregate this channel's post metrics over a window.

        One request covers the whole window, which is what makes a daily cached
        snapshot affordable against the 3,000/30-day budget.
        """
        data = self._gql(
            AGGREGATED_METRICS,
            {
                "input": {
                    "organizationId": self._org_id(),
                    "channelIds": [channel_id],
                    "startDateTime": start.isoformat(),
                    "endDateTime": end.isoformat(),
                }
            },
        )
        payload = data.get("aggregatedPostMetrics") or {}
        rows = [
            MetricRow(
                type=str(m.get("type", "")),
                name=str(m.get("name", "")),
                # Buffer defaults a metric a network did not report to 0, so a
                # missing value is genuinely zero rather than unknown.
                value=float(m.get("value") or 0),
                unit=str(m.get("unit") or "count"),
            )
            for m in (payload.get("metrics") or [])
            if m.get("type")
        ]
        self._log.info(
            "buffer_metrics_fetched",
            channel_id_suffix=channel_id[-4:], rows=len(rows),
        )
        return rows, _parse_dt(payload.get("metricsUpdatedAt"))

    def delete_post(self, post_id: str) -> None:
        """Remove a still-queued post.

        SPEC §4.2 assumed no delete existed; the live schema does expose
        ``deletePost`` (README §0). It only helps while the post is queued —
        once Instagram has published, deletion in Buffer changes nothing.
        """
        data = self._gql(DELETE_POST, {"input": {"id": post_id}})
        payload = data.get("deletePost") or {}
        if payload.get("__typename") != "DeletePostSuccess":
            raise PublishError(
                f"Buffer deletePost failed: {payload.get('message', payload)}"
            )
        self._log.info("buffer_post_deleted", post_id=post_id)


def _metadata_for(request: PublishRequest) -> dict[str, Any] | None:
    """Build the channel-specific metadata block, keyed on the *service*.

    Keyed on service rather than post type: an earlier version branched on
    ``post_type`` alone, which meant a YouTube channel posting ``short`` fell
    through to no metadata at all — and YouTube rejects a post with no title.

    The field names match ``PostInputMetaData`` in Buffer's schema, and the
    NON_NULL members of each input are always sent; omitting one makes Buffer
    reject the whole mutation rather than defaulting it.
    """
    if request.service is Service.INSTAGRAM:
        return {
            "instagram": {
                "type": request.post_type.value,
                "shouldShareToFeed": request.share_to_feed,
            }
        }
    if request.service is Service.YOUTUBE:
        # YouTube is the one platform with a separate title, capped at 100
        # characters. PublishRequest has already refused an over-long or missing
        # one, so reaching here without a title is a programming error.
        if not request.title:
            raise InvalidPostError(
                "YouTube requires a title and none was supplied"
            )
        return {
            "youtube": {
                "title": request.title,
                # Both are required by the API. 22 = People & Blogs, the safest
                # default; made-for-kids must be declared explicitly.
                "categoryId": "22",
                "madeForKids": False,
            }
        }
    # TikTok: its metadata input exists but has no required members for a plain
    # video post — the description rides in `text`, as it does for Instagram.
    return None


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


AGGREGATED_METRICS = """
query UgcFactoryMetrics($input: AggregatedPostMetricsInput!) {
  aggregatedPostMetrics(input: $input) {
    metricsUpdatedAt
    metrics { type name value unit }
  }
}
"""
