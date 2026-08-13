#!/usr/bin/env python3
"""List Buffer channels and whether each defaults to reminder-based publishing.

Read-only. Creates nothing. This is the tool for finishing SPEC §0 once an
Instagram channel is connected:

    BUFFER_API_KEY=... python scripts/check_channel.py

``defaultToReminders: true`` on an Instagram channel means Buffer will only send
a push notification for someone to post by hand — SPEC §0 is explicit that this
is not automation. The publisher additionally verifies the mode of each post it
creates, so a channel flipped to reminders later still fails loud rather than
quietly never posting.
"""

from __future__ import annotations

import os
import sys

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.logging import get_logger  # noqa: E402
from src.publishers.buffer import BufferPublisher  # noqa: E402

CHANNELS = """
query UgcFactoryChannels($input: ChannelsInput!) {
  channels(input: $input) {
    id
    name
    service
    type
    isDisconnected
    isLocked
    isQueuePaused
    hasActiveMemberDevice
    timezone
    metadata {
      __typename
      ... on InstagramMetadata { defaultToReminders }
      ... on TiktokMetadata { defaultToReminders }
      ... on YoutubeMetadata { defaultToReminders }
    }
  }
}
"""


def main() -> int:
    api_key = os.environ.get("BUFFER_API_KEY") or os.environ.get("BUFFER_ACCESS_TOKEN")
    if not api_key:
        print("set BUFFER_API_KEY", file=sys.stderr)
        return 1

    publisher = BufferPublisher(api_key, get_logger(command="check_channel"))
    org = publisher._org_id()
    data = publisher._gql(CHANNELS, {"input": {"organizationId": org}})

    channels = data.get("channels") or []
    if not channels:
        print("no channels connected to this Buffer organization")
        return 1

    print(f"{'service':<12} {'name':<24} {'reminders':<10} {'id'}")
    print("-" * 78)
    instagram_ok = False
    for channel in channels:
        metadata = channel.get("metadata") or {}
        reminders = metadata.get("defaultToReminders")
        flag = "?" if reminders is None else ("YES" if reminders else "no")
        print(
            f"{channel['service']:<12} {str(channel['name'])[:23]:<24} "
            f"{flag:<10} {channel['id']}"
        )
        if channel["service"] == "instagram" and reminders is False:
            instagram_ok = True

    print()
    if not any(c["service"] == "instagram" for c in channels):
        print(
            "NO INSTAGRAM CHANNEL CONNECTED — SPEC §0 cannot be completed until "
            "one is. It must be a Business or Creator account."
        )
        return 1
    if instagram_ok:
        print(
            "Instagram channel does NOT default to reminders. Automatic "
            "publishing should work; confirm with the live publish test."
        )
        return 0
    print(
        "Instagram channel DEFAULTS TO REMINDERS. Unattended publishing will "
        "not work as configured — turn reminders off in Buffer, or confirm the "
        "account is a Business/Creator account."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
