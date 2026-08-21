"""Creating and listing campaigns (SPEC §15).

Responsibility: turn "I want another campaign" into a working campaign folder,
without a code change and without hand-editing YAML.

SPEC §15 lists seven manual steps and ends with "If any step requires touching
``src/``, the abstraction failed." This module automates the file-creating ones.
The two it deliberately does not automate are the two that involve credentials:
connecting the channel in Buffer, and setting the secrets. Those stay with the
operator.

Step 6 — "add ``<slug>`` to the matrix" — no longer exists: the workflows
discover campaigns from this directory, so creating the folder is what makes a
campaign run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.config import CampaignConfig, PostType, load_campaign
from src.errors import ConfigError
from src.platforms import Service

#: Post type each network expects. Mirrors the validation in BufferConfig, so a
#: campaign created here cannot be born with a combination config would reject.
DEFAULT_POST_TYPE: dict[Service, PostType] = {
    Service.INSTAGRAM: PostType.REEL,
    Service.TIKTOK: PostType.POST,
    Service.YOUTUBE: PostType.SHORT,
}

_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


@dataclass(frozen=True)
class CampaignSummary:
    """What the dashboard needs to list a campaign without loading everything."""

    slug: str
    service: str
    post_type: str
    posts_per_day: int
    dry_run: bool
    timezone: str
    assets_tag: str
    valid: bool
    #: Needed to tell whether two campaigns share a posting grid.
    start_hour: int = 0
    slot_offset_min: int = 0
    error: str = ""


def slug_error(slug: str, existing: list[str]) -> str | None:
    """Why this slug cannot be used, or None.

    Stricter than the config schema: a slug becomes a directory name *and* the
    tail of an environment variable (``BUFFER_CHANNEL_<SLUG>``), so it is held
    to what is safe in both. Hyphens are rejected for exactly that reason —
    they are legal in a path and illegal in a shell variable name.
    """
    if not slug:
        return "slug is required"
    if not _SLUG.match(slug):
        return (
            "use lowercase letters, digits and underscores, starting with a "
            "letter (hyphens are not valid in the secret names derived from it)"
        )
    if slug in existing:
        return f"campaign {slug!r} already exists"
    return None


def list_campaigns(campaigns_dir: Path) -> list[CampaignSummary]:
    """Every campaign on disk, including ones whose config is broken.

    A campaign with an unparseable config is reported rather than skipped —
    hiding it would leave the operator wondering why it never posts.
    """
    out: list[CampaignSummary] = []
    if not campaigns_dir.is_dir():
        return out

    for directory in sorted(campaigns_dir.iterdir()):
        if not directory.is_dir() or directory.name.startswith("_"):
            continue
        try:
            config = load_campaign(campaigns_dir, directory.name)
        except ConfigError as exc:
            out.append(CampaignSummary(
                slug=directory.name, service="?", post_type="?", posts_per_day=0,
                dry_run=True, timezone="?", assets_tag="?",
                valid=False, error=str(exc)[:200],
            ))
            continue
        out.append(CampaignSummary(
            slug=config.slug,
            service=config.buffer.service.value,
            post_type=config.buffer.post_type.value,
            posts_per_day=config.posting.posts_per_day,
            start_hour=config.posting.start_hour,
            slot_offset_min=config.posting.slot_offset_min,
            dry_run=config.posting.dry_run,
            timezone=config.timezone,
            assets_tag=config.assets_tag,
            valid=True,
        ))
    return out


def render_config(
    slug: str,
    service: Service,
    *,
    timezone: str = "America/Denver",
    posts_per_day: int = 12,
    start_hour: int = 15,
    assets_release: str | None = None,
    organization_id: str | None = None,
    channel_id: str | None = None,
    api_key_secret: str = "BUFFER_API_KEY",
    slot_offset_min: int = 0,
) -> str:
    """Build a campaign's config.yaml.

    Generated rather than copied-and-patched so a new campaign cannot inherit a
    stale comment describing numbers it does not use.
    """
    post_type = DEFAULT_POST_TYPE[service]
    upper = slug.upper()
    shared = (
        f"assets_release: {assets_release}\n" if assets_release else ""
    )
    org = (
        f"  organization_id: {organization_id}\n" if organization_id else ""
    )
    channel = (
        f"  channel_id: {channel_id}\n" if channel_id
        else f"  channel_id_secret: BUFFER_CHANNEL_{upper}\n"
    )
    return f"""slug: {slug}
timezone: {timezone}
{shared}
posting:
  # {posts_per_day}/day spread across a 24-hour window starting {start_hour:02d}:00 local.
  # start_hour == end_hour means a full day from that hour, wrapping midnight.
  posts_per_day: {posts_per_day}
  start_hour: {start_hour}
  end_hour: {start_hour}
  max_buffer_queue: 10        # SPEC §4.1 — Buffer free-plan queue-depth cap
  # Chosen to avoid the slots the existing campaigns already occupy: same
  # cadence and start hour means an identical grid, and every network firing
  # on the same minute.
  slot_offset_min: {slot_offset_min}
  # Render tops the backlog up to posts_per_day x this, then stops. It is what
  # keeps rendering from outrunning what the channel actually publishes.
  max_backlog_days: 2
  dry_run: true               # flip to false once a dispatch run looks right

variation:
  # Per-variant creative treatment: a different punch-in, grade, grain and
  # pace for every render, seeded on the item id so a winner is reproducible.
  # Off until you have looked at a few samples — it changes how every video
  # looks. `ugc sample --campaign {slug}` renders one without queueing it.
  enabled: false
  allow_mirror: false         # mirrors on-screen text and reverses a logo

video:
  width: 1080
  height: 1920
  fps: 30
  crf: 23
  preset: veryfast
  min_duration_sec: 5         # SPEC §4.3 — Reels-tab eligibility floor
  max_duration_sec: 90
  max_file_mb: 100

composition:
  bodies_per_video: 1
  music_volume: 0.10
  music_fade_out_sec: 1.5
  # Upload whole songs; each video takes its bed from a different point.
  music_random_start: true
  music_segment_sec: 15
  music_skip_intro_sec: 0
  music_fade_in_sec: 0.5

selection:
  dedupe_on: [hook, body, music, caption]
  # A cooldown of N days at P posts/day needs N x P distinct assets, or the
  # selector relaxes and alerts daily. Raise these as the library grows.
  caption_cooldown_days: 2
  hook_cooldown_days: 0
  min_runway_days: 90

buffer:
  api_key_secret: {api_key_secret}
{channel}  post_type: {post_type.value}
  service: {service.value}
{org}  title_strategy: derive

notify:
  webhook_secret: DISCORD_WEBHOOK
  on: [failure, queue_empty, quota_high, license_missing, dedupe_relaxed, digest]
"""


@dataclass(frozen=True)
class CreatedCampaign:
    """What was written, and what the operator still has to do themselves."""

    slug: str
    paths: tuple[Path, ...]
    required_secrets: tuple[str, ...]


def free_slot_offset(
    campaigns_dir: Path, posts_per_day: int, start_hour: int
) -> int:
    """A stagger that does not land on an existing campaign's slots.

    Campaigns sharing a cadence and a start hour generate *identical* slot
    times, so a new one created with the default offset fires on the same
    minute as every sibling — the whole content day collapsing into a few
    instants. That happened here and took a while to notice, because nothing
    collides in the sense the queue cares about: they are separate channels.

    Picks the midpoint of the largest unclaimed gap in the posting interval,
    so two campaigns end up half an interval apart, three at thirds, and so on
    without anyone choosing numbers.
    """
    interval = max(1, round(24 * 60 / max(1, posts_per_day)))
    taken = sorted(
        {
            c.slot_offset_min % interval
            for c in list_campaigns(campaigns_dir)
            if c.valid
            and c.posts_per_day == posts_per_day
            and c.start_hour == start_hour
        }
    )
    if not taken:
        return 0

    # Widest gap between consecutive claimed offsets, wrapping at the interval.
    best_gap, best_at = -1, 0
    for current, following in zip(taken, taken[1:] + [taken[0] + interval]):
        gap = following - current
        if gap > best_gap:
            best_gap, best_at = gap, current + gap // 2
    return best_at % interval


def create_campaign(
    campaigns_dir: Path,
    slug: str,
    service: Service,
    *,
    timezone: str = "America/Denver",
    posts_per_day: int = 12,
    start_hour: int = 15,
    assets_release: str | None = None,
    organization_id: str | None = None,
    channel_id: str | None = None,
    api_key_secret: str = "BUFFER_API_KEY",
    descriptions: str | None = None,
    slot_offset_min: int | None = None,
) -> CreatedCampaign:
    """Create a campaign folder, or raise ``ConfigError``.

    Starts in ``dry_run`` deliberately (SPEC §15 step 7): a brand-new channel
    should be looked at once before anything reaches it.
    """
    existing = [c.slug for c in list_campaigns(campaigns_dir)]
    problem = slug_error(slug, existing)
    if problem:
        raise ConfigError(problem)

    if slot_offset_min is None:
        slot_offset_min = free_slot_offset(campaigns_dir, posts_per_day, start_hour)

    directory = campaigns_dir / slug
    directory.mkdir(parents=True, exist_ok=False)

    config_path = directory / "config.yaml"
    config_path.write_text(
        render_config(
            slug, service,
            timezone=timezone, posts_per_day=posts_per_day,
            start_hour=start_hour, assets_release=assets_release,
            organization_id=organization_id, channel_id=channel_id,
            api_key_secret=api_key_secret,
            slot_offset_min=slot_offset_min,
        ),
        encoding="utf-8",
    )

    bank = directory / "captions.txt"
    bank.write_text(
        descriptions
        or "# Descriptions — the text each video is posted with.\n"
           "# Records separated by a line of ---\n\n"
           "first description goes here\n",
        encoding="utf-8",
    )

    queue = directory / "queue.json"
    queue.write_text('{\n  "generated_at": "1970-01-01T00:00:00Z",\n  "items": []\n}\n',
                     encoding="utf-8")
    history = directory / "history.json"
    history.write_text('{\n  "entries": []\n}\n', encoding="utf-8")

    # Validate what was written rather than trusting the template: a campaign
    # that cannot load is worse than one that was never created.
    config = load_campaign(campaigns_dir, slug)

    return CreatedCampaign(
        slug=slug,
        paths=(config_path, bank, queue, history),
        # Only names an actual secret. A channel id written straight into
        # config is not one, so it is not listed as something to go and set.
        required_secrets=tuple(
            name for name in (
                config.buffer.channel_id_secret,
                config.notify.webhook_secret,
            )
            if name
        ),
    )
