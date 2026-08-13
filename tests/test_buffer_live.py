"""The one test that touches the live Buffer API.

SPEC §2.2: "One optional integration test hits the live API behind an env flag,
and it is never part of CI."

Run it deliberately:

    UGC_LIVE_BUFFER=1 BUFFER_API_KEY=... pytest tests/test_buffer_live.py -v

The read-only checks (schema shape, channel listing, queue depth) are safe to
run any time. The publish check is gated *separately* and additionally requires
``UGC_LIVE_BUFFER_PUBLISH=1`` plus a channel id, because it creates a real post
on a real account — SPEC §13 M6 says to point it at a throwaway account first.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone

import pytest

from src.logging import StructuredLogger
from src.publishers.base import PublishRequest
from src.publishers.buffer import BufferPublisher

live = pytest.mark.skipif(
    os.environ.get("UGC_LIVE_BUFFER") != "1",
    reason="live Buffer test — set UGC_LIVE_BUFFER=1 to run",
)
live_publish = pytest.mark.skipif(
    os.environ.get("UGC_LIVE_BUFFER_PUBLISH") != "1"
    or not os.environ.get("BUFFER_TEST_CHANNEL_ID"),
    reason="creates a real post — set UGC_LIVE_BUFFER_PUBLISH=1 and "
           "BUFFER_TEST_CHANNEL_ID to run",
)

pytestmark = live


@pytest.fixture
def publisher() -> BufferPublisher:
    key = os.environ.get("BUFFER_API_KEY")
    if not key:
        pytest.skip("BUFFER_API_KEY not set")
    return BufferPublisher(key, StructuredLogger({}, io.StringIO()))


def test_credentials_resolve_an_organization(publisher: BufferPublisher) -> None:
    """Cheapest possible proof that the key works."""
    assert publisher._org_id()


def test_queue_depth_is_readable(publisher: BufferPublisher) -> None:
    channel = os.environ.get("BUFFER_TEST_CHANNEL_ID")
    if not channel:
        pytest.skip("BUFFER_TEST_CHANNEL_ID not set")
    depth = publisher.queue_depth(channel)
    assert 0 <= depth <= 100


@live_publish
def test_creates_a_real_reel_in_automatic_mode(publisher: BufferPublisher) -> None:
    """The §0 question, answered against the live API.

    If this raises ``InvalidPostError`` mentioning 'not automatic', the channel
    is in reminder mode and the architecture assumption in SPEC §0 is false for
    this account — read the error, do not paper over it.

    Cleans up after itself via deletePost so a repeat run does not fill the
    free plan's 10-post queue.
    """
    channel = os.environ["BUFFER_TEST_CHANNEL_ID"]
    video_url = os.environ.get(
        "BUFFER_TEST_VIDEO_URL",
        "https://github.com/anthropics/anthropic-sdk-python/raw/main/README.md",
    )
    due = datetime.now(timezone.utc) + timedelta(days=2)

    post = publisher.create_post(
        PublishRequest(
            channel_id=channel,
            text="ugc-factory live test — safe to delete",
            video_url=video_url,
            scheduled_for=due,
        )
    )
    try:
        assert post.will_publish_automatically, (
            "Buffer accepted the post in reminder mode — SPEC §0's assumption "
            "does not hold for this channel"
        )
        assert post.post_id
    finally:
        publisher.delete_post(post.post_id)
