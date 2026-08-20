#!/usr/bin/env python3
"""Does Buffer expose metrics for an individual post?

The whole clip- and caption-performance question turns on this one fact, and
nothing in the codebase answers it. ``aggregatedPostMetrics`` returns channel
totals over a window; the ``posts`` query the diagnose command uses asks for no
metrics at all. Whether a per-post field exists has never been checked.

Costs **one** GraphQL request — an introspection query, which reads the schema
and touches no posts. Run it and the answer is definitive:

    ./scripts/check_post_metrics.py

Needs BUFFER_API_KEY in the environment or in .env at the repo root, which is
what the dashboard's Keys panel writes.

If a per-post metric field exists, the follow-up question is affordability, not
feasibility: ~1,080 posts a month against the request budget the quota panel
now measures. If it does not exist, clip-level performance is a dead end
through Buffer and the alternative is each network's own API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.keys import read_env  # noqa: E402
from src.logging import StructuredLogger  # noqa: E402

#: Names worth reporting if they turn up on the Post type. Kept broad: the
#: point is to discover what exists, not to confirm a guess.
INTERESTING = (
    "metric", "analytic", "statistic", "insight", "performance",
    "view", "impression", "reach", "like", "engagement",
)

INTROSPECT = """
query UgcFactoryPostFields {
  __type(name: "Post") {
    name
    fields {
      name
      description
      type { name kind ofType { name kind } }
    }
  }
}
"""


def main() -> int:
    import io
    import os

    key = os.environ.get("BUFFER_API_KEY") or read_env(REPO_ROOT / ".env").get(
        "BUFFER_API_KEY"
    )
    if not key:
        print(
            "No BUFFER_API_KEY found.\n\n"
            "Paste it in the dashboard's Keys panel (./ugc web), or set it in\n"
            "the environment, then run this again.",
            file=sys.stderr,
        )
        return 2

    from src.publishers.buffer import BufferPublisher

    log = StructuredLogger({}, io.StringIO())
    publisher = BufferPublisher(key, log)
    data = publisher._gql(INTROSPECT, {})

    node = data.get("__type")
    if not node:
        print("Buffer's schema has no type named 'Post'. The query below is "
              "what was asked:\n" + INTROSPECT, file=sys.stderr)
        return 1

    fields = node.get("fields") or []
    print(f"Post exposes {len(fields)} fields. Requests used: "
          f"{publisher.request_count}\n")

    hits = [
        f for f in fields
        if any(word in f["name"].lower() for word in INTERESTING)
    ]
    if not hits:
        print("No per-post metric field exists on Post.\n")
        print("Clip- and caption-level performance cannot be derived through\n"
              "Buffer at any budget. The remaining route is each network's own\n"
              "API — YouTube Data API is free and generous; Instagram and\n"
              "TikTok need their own app registrations.")
        print("\nEvery field, for the record:")
        print("  " + ", ".join(sorted(f["name"] for f in fields)))
        return 0

    print("Candidate per-post metric fields:\n")
    for field in hits:
        type_info = field.get("type") or {}
        name = type_info.get("name") or (type_info.get("ofType") or {}).get("name")
        print(f"  {field['name']}: {name or type_info.get('kind')}")
        if field.get("description"):
            print(f"      {field['description']}")
    print(
        "\nA per-post metric field exists, so this is now a budget question\n"
        "rather than a feasibility one: roughly 1,080 posts a month against\n"
        "what the dashboard's quota strip reports as spare."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
