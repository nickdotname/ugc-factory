"""Command line entry point: ``render | topup | preflight | cleanup``.

Responsibility: the composition root. This is the one module that constructs
real clocks, real RNGs, real HTTP sessions and real subprocesses and injects
them into everything else (SPEC §2.2). Every other module takes its
dependencies as arguments and can therefore be tested without any of them.

The four commands map to the four workflows in SPEC §5/§12:

* ``render``   — nightly: pick, render, upload, write queue.json
* ``topup``    — every 4h: push enough items to fill Buffer's queue to its cap
* ``preflight``— validate config, secrets and library without changing anything
* ``cleanup``  — weekly: delete Releases past the retention window

plus ``ingest``, which is the only one a human runs by hand: it takes files from
the ``inbox/`` drop folders, checks and names them, and uploads them to the
campaign's assets Release.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, replace
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.keys import read_env
from src.accounts import (
    ACCOUNTS_FILE,
    AccountConfig,
    AccountsConfig,
    InstagramLogin,
    Provider,
    accounts_for,
    load_accounts,
)
from src.site import media_base, public_media_url
from src.assets import (
    assert_publicly_readable,
    GitHubReleasesStore,
    LocalLibrary,
    MediaStore,
    check_music_licenses,
    github_token_from_env,
    fetch_library,
)
from src.clips import filter_library, kind_of, load_roster, roster_path, save_roster
from src.config import (
    CampaignConfig,
    CreativeConfig,
    NotifyEvent,
    TitleStrategy,
    load_campaign,
)
from src.descriptions import (
    BANK_DIR,
    Description,
    bank_path_for,
    derive_title,
    load_network_banks,
    load_bank,
    parse_bank,
    validate_bank,
)
from src.errors import (
    AuthError, ConfigError, InvalidPostError, MediaStoreError, QuotaError, SelectionError,
    UgcError, ValidationError,
)
from src.ingest import (
    ARCHIVE_DIR,
    INBOX_DIRS,
    IngestPlan,
    apply_plan,
    build_plan,
    combinations,
    ensure_inbox,
    library_health,
)
from src.lineup import LineupEntry, due_entries, lineup_path, load_lineup, resolve_time
from src.logging import StructuredLogger, get_logger
from src.models import (
    DEFAULT_CREATIVE,
    Variant,
    History,
    HistoryEntry,
    PartKind,
    Queue,
    QueueItem,
    QueueStatus,
    RenderRequest,
    Selection,
)
from src.metrics import (
    Metric,
    MetricsHistory,
    Scope,
    Snapshot,
    default_window,
    lifetime_window,
    load_metrics,
    save_metrics,
)
from src.notify import Digest, Notifier, notifier_for
from src.campaigns import list_campaigns
from src.attribution import (
    attribute,
    distribution_lost,
    load_posts,
    posts_path,
    save_posts,
)
from src.platforms import (
    Service,
    check_description,
    check_title,
    config_conflicts,
    effective_video_limits,
    limits_for,
)
from src.quota import (
    MONTHLY_ALLOWANCE,
    WINDOW_DAYS,
    QuotaLedger,
    load_quota,
    quota_path,
    record_run,
    rolling_total,
)
from src.ports import Clock, Rng, SeededRng, SystemClock
from src.publishers.base import DryRunPublisher, PublishRequest, Publisher
from src.publishers.buffer import BufferPublisher
from src.publishers.instagram import OUTBOX_DIR, InstagramPublisher
from src.analytics import (
    cache_path as analytics_cache_path,
    correlate,
    load_cache as load_analytics_cache,
    range_from_clock,
    save_cache as save_analytics_cache,
    vocabulary_gap,
)
from src.analytics_api import HttpProductAnalytics
from src.queue import (
    CANCELLABLE,
    append_history,
    backfill_post_id,
    cancel,
    carry_forward,
    claimable,
    claimable_for,
    depth_needed,
    ensure_posts,
    load_history,
    load_queue,
    mark_failed,
    mark_post_failed,
    mark_post_pushed,
    mark_pushed,
    post_for,
    reset_for_retry,
    reset_post_for_retry,
    save_queue,
    spread_schedule,
    stranded,
    stranded_for,
    sync_status,
    upcoming_slots,
    transition,
    transition_post,
)
from src.render import FfmpegRenderer, Renderer
from src.selector import (
    AssetLibrary,
    pick_by_recency,
    Relaxation,
    Selector,
    days_until_first_repeat,
    entry_hooks,
    tuple_hash,
)
from src.vcs import GitVcs, NullVcs, Vcs, VcsError

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS_DIR = REPO_ROOT / "campaigns"

#: Retention for dated render Releases (SPEC §5). Must stay comfortably longer
#: than the deepest queue, or a video is deleted before Buffer publishes it.
RENDER_RETENTION_DAYS = 14

#: Drop folders live at the repo root so they are obvious to a human.
INBOX_ROOT = "inbox"

#: SPEC §3 — alert at 2,400 of the 3,000-request/30-day allowance.
BUFFER_QUOTA_ALERT_THRESHOLD = 2400


# ------------------------------------------------------------------- wiring


def _campaign_dir(slug: str) -> Path:
    return CAMPAIGNS_DIR / slug


def _assets_tag(config: CampaignConfig) -> str:
    """The Release holding a campaign's source library (SPEC §7)."""
    return config.assets_tag


def _render_tag(slug: str, day: datetime) -> str:
    return f"render-{slug}-{day.strftime('%Y-%m-%d')}"


def _secret(name: str, env: dict[str, str]) -> str | None:
    value = env.get(name)
    return value if value else None


def _build_publisher(
    config: CampaignConfig, env: dict[str, str], log: StructuredLogger
) -> Publisher:
    """Choose the real publisher or the dry-run recorder.

    ``dry_run`` is checked here, once, rather than at each call site — a branch
    further in would eventually be missed and post something real.
    """
    if config.posting.dry_run:
        log.info("dry_run_enabled", campaign=config.slug)
        return DryRunPublisher(log)

    api_key = _secret(config.buffer.api_key_secret, env)
    if not api_key:
        raise ConfigError(
            f"{config.buffer.api_key_secret} is not set — cannot publish. "
            f"Set the secret, or set posting.dry_run: true."
        )
    return BufferPublisher(
        api_key, log, organization_id=config.buffer.organization_id
    )


def _channel_id(config: CampaignConfig, env: dict[str, str]) -> str:
    """Resolve the channel id from config, or from a secret if one is named."""
    if config.buffer.channel_id:
        return config.buffer.channel_id
    assert config.buffer.channel_id_secret is not None  # enforced by config
    channel = _secret(config.buffer.channel_id_secret, env)
    if not channel:
        raise ConfigError(
            f"{config.buffer.channel_id_secret} is not set — the campaign has "
            f"no Buffer channel to post to"
        )
    return channel


def _build_store(env: dict[str, str], log: StructuredLogger, clock: Clock) -> MediaStore:
    repo = env.get("GITHUB_REPOSITORY")
    if not repo:
        raise ConfigError(
            "GITHUB_REPOSITORY is not set (expected 'owner/name'); the media "
            "store cannot tell which repo's Releases to use"
        )
    return GitHubReleasesStore(repo, github_token_from_env(env), log, clock)


def _library_from(
    paths: LocalLibrary,
    descriptions: list[Description],
    config: CampaignConfig | None = None,
    durations: dict[str, float] | None = None,
    creative: CreativeConfig | None = None,
) -> AssetLibrary:
    composition = config.composition if config else None
    return AssetLibrary(
        music_cues=dict(creative.music_cues) if creative else {},
        bodies_required=(
            composition.bodies_per_video > 0 if composition else True
        ),
        hooks=tuple(p.name for p in paths.hooks),
        bodies=tuple(p.name for p in paths.bodies),
        music=tuple(p.name for p in paths.music),
        # The selector dedupes on description *body*; the title rides along
        # via the lookup below and never affects combination identity.
        captions=tuple(d.body for d in descriptions),
        music_durations=durations or {},
        music_segment_sec=(
            composition.music_segment_sec if composition
            and composition.music_random_start else 0.0
        ),
        music_skip_intro_sec=(
            composition.music_skip_intro_sec if composition else 0.0
        ),
    )


def _creative_bank_path(
    config: CampaignConfig, creative: CreativeConfig, campaign_dir: Path,
    style: str | None = None,
) -> Path:
    """The description bank one creative draws from.

    A bank written for the clip's studio ``style`` first (the campaign's
    ``captions/<style>.txt``, when it has one: a wind-tunnel video and a
    bouncing ball share a song and an account but not a sentence), then the
    creative's own ``creatives/<name>/captions.txt`` when it has one, the
    campaign's shared bank otherwise. A creative is often a different
    *subject* — a different song, a different product angle — and copy
    written for one reads as nonsense under another, so the bank can follow
    the clips.
    """
    if style:
        styled = campaign_dir / BANK_DIR / f"{style}.txt"
        if styled.is_file():
            return styled
    own = config.creative_dir(campaign_dir, creative) / "captions.txt"
    return own if own.is_file() else campaign_dir / "captions.txt"


def _extra_network_banks(
    config: CampaignConfig, campaign_dir: Path, log: StructuredLogger
) -> dict[Service, list[Description]]:
    """Each network's own description bank, excluding the campaign's own.

    Only networks with a ``captions/<network>.txt`` of their own appear: one
    falling back to the shared bank needs no separate pick, because the
    shared bank is already what the item carries.
    """
    banks: dict[Service, list[Description]] = {}
    for service in Service:
        if service is config.buffer.service:
            continue
        if not bank_path_for(campaign_dir, service).is_file():
            continue
        banks[service] = load_network_banks(
            campaign_dir, [service], {service: TitleStrategy.DERIVE}
        )[service]
        log.info(
            "network_bank_loaded", network=service.value,
            descriptions=len(banks[service]),
        )
    return banks


def _caption_last_used(
    history: History, service: Service
) -> dict[str, datetime]:
    """When each of this network's descriptions was last posted to it."""
    seen: dict[str, datetime] = {}
    for entry in history.entries:
        text = entry.captions.get(service.value)
        if not text:
            continue
        prior = seen.get(text)
        if prior is None or entry.timestamp > prior:
            seen[text] = entry.timestamp
    return seen


def _resolve_creative(config: CampaignConfig, name: str | None) -> CreativeConfig:
    """The named creative, or the campaign's first one when none is given."""
    if name is None:
        return config.creatives[0]
    for creative in config.creatives:
        if creative.name == name:
            return creative
    known = ", ".join(c.name for c in config.creatives)
    raise ConfigError(
        f"{config.slug} has no creative named {name!r} — known: {known}"
    )


@dataclass(frozen=True)
class _CreativeResources:
    """One creative's downloaded library, ready to select from.

    ``history`` holds only this creative's own entries — HANDOFF phase 1:
    "clips never mix across creatives," so cooldowns, tuple dedupe and LRU
    weighting for this creative must never see what another creative did.
    """

    creative: CreativeConfig
    library: AssetLibrary
    history: History
    by_name: dict[str, Path]
    ceiling: int
    distinct_visuals: int
    #: The bank this creative posts with — its own, or the campaign's.
    descriptions: tuple[Description, ...] = ()
    #: This creative's own per-network banks (``creatives/<name>/captions/
    #: <network>.txt``), which win over the campaign-level ones.
    network_banks: tuple[tuple[Service, tuple[Description, ...]], ...] = ()

    def record_for(self, body: str) -> Description | None:
        return next((d for d in self.descriptions if d.body == body), None)


def _load_creative_resources(
    config: CampaignConfig,
    creative: CreativeConfig,
    campaign_dir: Path,
    work: Path,
    store: MediaStore,
    full_history: History,
    renderer: Renderer,
    log: StructuredLogger,
) -> tuple[_CreativeResources, list[str]]:
    """Download, filter and probe one creative's pool. Returns (resources, missing licences).

    Every creative gets its own subdirectory under ``work/`` so two creatives
    can never resolve a filename to the wrong file, even if they happen to
    reuse a number (``hook_01.mp4`` in creative A is a different file from
    ``hook_01.mp4`` in creative B once each lives in its own Release tag).
    """
    paths = filter_library(
        fetch_library(
            store, work / "assets", creative.name,
            config.creative_assets_tag(creative),
            config.creative_video_tag(creative),
        ),
        load_roster(roster_path(campaign_dir)),
        log,
    )

    # Music declared as the campaign's own needs no per-track paperwork: the
    # licence file exists to stop third-party tracks slipping in, and
    # ``music_cleared`` is the owner saying there are none.
    missing_licenses = [] if config.composition.music_cleared else check_music_licenses(
        paths.music, config.creative_licenses_path(campaign_dir, creative), log
    )

    durations: dict[str, float] = {}
    if config.composition.music_random_start:
        for track in paths.music:
            try:
                durations[track.name] = renderer.probe(track).duration_sec
            except UgcError as exc:
                log.warning(
                    "music_probe_failed", creative=creative.name,
                    track=track.name, error=str(exc),
                )

    descriptions = _load_captions(
        _creative_bank_path(config, creative, campaign_dir),
        config.buffer.service, config.buffer.title_strategy,
        _caption_names(config, creative),
    )
    creative_dir = config.creative_dir(campaign_dir, creative)
    network_banks = tuple(
        (service, tuple(bank))
        for service, bank in _extra_network_banks(config, creative_dir, log).items()
    )
    library = _library_from(paths, descriptions, config, durations, creative)
    history = History(
        entries=[e for e in full_history.entries if e.creative == creative.name]
    )
    bodies_per_video = config.composition.bodies_per_video
    bodies_max = config.composition.bodies_per_video_max
    ceiling = library.ceiling(bodies_per_video, bodies_max)
    log.info(
        "combinatorial_ceiling",
        creative=creative.name,
        hooks=len(library.hooks), bodies=len(library.bodies),
        music=len(library.music), captions=len(library.captions),
        bodies_per_video=bodies_per_video,
        total_combinations=ceiling,
        distinct_visuals=library.distinct_visuals(bodies_per_video, bodies_max),
        used_combinations=len(history.entries),
    )

    return (
        _CreativeResources(
            creative=creative,
            library=library,
            history=history,
            by_name=paths.by_name(),
            ceiling=ceiling,
            distinct_visuals=library.distinct_visuals(bodies_per_video, bodies_max),
            descriptions=tuple(descriptions),
            network_banks=network_banks,
        ),
        missing_licenses,
    )


def _caption_names(config: CampaignConfig, creative: CreativeConfig) -> dict[str, str]:
    """What ``{name}`` and ``{link}`` stand for in one creative's captions."""
    return {
        "{name}": creative.title or config.funnel.name,
        "{link}": creative.link or config.funnel.link,
    }


def _load_captions(
    path: Path, service: Service, strategy: TitleStrategy | None = None,
    names: dict[str, str] | None = None,
) -> list[Description]:
    """Read and validate the description bank for the campaign's platform.

    Descriptions are the text a video is posted *with* — not anything drawn onto
    the frame. Validated here against the target platform's limits so an
    over-long description fails at preflight rather than at publish time, where
    it would cost API quota to discover.
    """
    if not path.is_file():
        raise ConfigError(f"description bank not found: {path}")
    text = path.read_text(encoding="utf-8")
    # A caption can say {name} and be written once for every song: it is
    # filled with the song it is posted with, on the video and under it.
    # Left as written when there is nothing to fill it with.
    for token, value in (names or {}).items():
        if value:
            text = text.replace(token, value)
    return load_bank(text, service, source=str(path), strategy=strategy)


# ------------------------------------------------------------------ command: render


def cmd_render(args: argparse.Namespace, env: dict[str, str]) -> int:
    clock: Clock = SystemClock()
    log = get_logger(command="render", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    if args.dry_run:
        config = config.model_copy(
            update={"posting": config.posting.model_copy(update={"dry_run": True})}
        )
    notifier = notifier_for(config, log, env)
    if config.posting.paused:
        log.info("campaign_paused", campaign=config.slug)
        print(f"{config.slug} is paused (posting.paused) — rendered nothing.")
        return 0

    try:
        return _render(args, env, config, log, notifier, clock)
    except UgcError as exc:
        log.exception("render_failed", exc)
        notifier.failure("render", exc, campaign=config.slug)
        return 1


def _render(
    args: argparse.Namespace,
    env: dict[str, str],
    config: CampaignConfig,
    log: StructuredLogger,
    notifier: Notifier,
    clock: Clock,
) -> int:
    campaign_dir = _campaign_dir(config.slug)
    work = REPO_ROOT / "work" / config.slug
    out_dir = work / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    store = _build_store(env, log, clock)
    # Which accounts exist — for checking the names a creative or a lineup
    # entry asks for, and for knowing every network a file must be valid on.
    registry = (
        load_accounts(REPO_ROOT / ACCOUNTS_FILE)
        if config.posting.fan_out else AccountsConfig()
    )
    reachable = accounts_for(registry, config.accounts)
    renderer: Renderer = FfmpegRenderer(
        config, log,
        services=sorted({a.network for a in reachable}, key=lambda s: s.value)
        or None,
    )
    full_history = load_history(campaign_dir / "history.json")

    # Every creative is its own self-contained pool (HANDOFF phase 1): its own
    # download, its own licence check, its own combination ceiling. A campaign
    # with the default single creative resolves this to exactly what it did
    # before creatives existed — same tag, same files, same numbers.
    resources: dict[str, _CreativeResources] = {}
    missing_by_creative: dict[str, list[str]] = {}
    skipped: list[str] = []
    for creative in config.creatives:
        try:
            res, missing = _load_creative_resources(
                config, creative, campaign_dir, work, store, full_history,
                renderer, log,
            )
        except MediaStoreError as exc:
            # A song whose library has not been made yet (a fresh -v2 library
            # fills over a few nights) sits this night out; the rest still post.
            if "not found" not in str(exc) or len(skipped) + 1 >= len(config.creatives):
                raise
            log.warning("creative_library_missing", creative=creative.name, error=str(exc)[:200])
            skipped.append(creative.name)
            continue
        resources[creative.name] = res
        if missing:
            missing_by_creative[creative.name] = missing
    if skipped:
        config = config.model_copy(update={
            "creatives": [c for c in config.creatives if c.name not in skipped]
        })

    if missing_by_creative:
        parts = [
            f"{name} ({', '.join(tracks[:20])})"
            for name, tracks in missing_by_creative.items()
        ]
        notifier.notify(
            NotifyEvent.LICENSE_MISSING,
            f"⚠️ {config.slug}: music tracks with no LICENSES.md entry — "
            + "; ".join(parts),
        )

    # Seeded from the render date so a given day is reproducible, while
    # successive days still differ (SPEC §2.2).
    today = clock.now()
    rng: Rng = SeededRng(int(today.strftime("%Y%m%d")))
    selector = Selector(config.selection, clock, rng, log)

    # Carry over whatever last night produced and the top-up has not pushed.
    # Replacing the queue here is what threw away most of the output.
    previous = load_queue(campaign_dir / "queue.json")
    # An account taken off this campaign leaves its records pending for ever. Left
    # in, they made each video look unfinished, so render counted it as still to
    # post and made that many fewer new ones (nickdotname got 2 a day, not 8).
    if config.posting.fan_out:
        live = {a.name for a in reachable}
        dropped_posts = 0
        for item in previous.items:
            if item.posts and any(p.account not in live for p in item.posts):
                kept_posts = [p for p in item.posts if p.account in live]
                dropped_posts += len(item.posts) - len(kept_posts)
                item.posts = kept_posts
                if kept_posts:
                    sync_status(item)
                else:
                    item.status = QueueStatus.CANCELLED
        if dropped_posts:
            log.info("queue_records_for_removed_accounts_dropped", count=dropped_posts)
    carried, expired = carry_forward(previous, today, RENDER_RETENTION_DAYS)
    if expired:
        log.warning(
            "queue_items_expired",
            count=len(expired),
            oldest=min(i.scheduled_for for i in expired).isoformat(),
            reason="media Release deleted past retention",
        )
        notifier.notify(
            NotifyEvent.QUEUE_STALE,
            f"⚠️ {config.slug}: {len(expired)} queued video(s) aged out before "
            f"they could publish. The channel is not draining the queue as fast "
            f"as it is being filled — consider lowering posts_per_day.",
        )

    # Demand-driven: top the backlog up to the configured depth rather than
    # adding a fixed batch every night regardless of what is still waiting.
    target = config.posting.posts_per_day * config.posting.max_backlog_days
    room = max(0, target - len(carried))

    # Hand-picked posts go first. Timed entries always render once their
    # moment is inside the window being filled — they asked for a time, so
    # the cadence does not get a vote — while untimed ones queue up in file
    # order and take whatever room the backlog has.
    lineup = load_lineup(lineup_path(campaign_dir))
    done_ids = {e.lineup_id for e in full_history.entries if e.lineup_id}
    done_ids |= {i.lineup_id for i in carried if i.lineup_id}
    horizon = today + timedelta(days=config.posting.max_backlog_days + 1)
    due, missed = due_entries(lineup, done_ids, today, horizon, config.zone)
    timed = [e for e in due if e.at is not None]
    untimed = [e for e in due if e.at is None][: max(0, room - len(timed))]
    waiting = sum(1 for e in due if e.at is None) - len(untimed)
    if missed:
        log.warning("lineup_entries_missed", ids=[e.id for e in missed])
        notifier.notify(
            NotifyEvent.QUEUE_STALE,
            f"⚠️ {config.slug}: {len(missed)} lineup post(s) were timed for a "
            f"moment that passed before they rendered and were NOT posted: "
            f"{', '.join(e.id for e in missed[:10])}. Give them a new `at:` "
            f"(or remove it) to send them.",
        )

    if args.count:
        count = args.count if config.selection.auto_fill else 0
    elif config.selection.auto_fill:
        count = max(0, room - len(timed) - len(untimed))
    else:
        count = 0
    log.info(
        "render_demand",
        carried=len(carried), expired=len(expired), target=target,
        rendering=count, lineup=len(timed) + len(untimed),
        lineup_waiting=waiting, auto_fill=config.selection.auto_fill,
        posts_per_day=config.posting.posts_per_day,
    )
    total_weight = sum(c.weight for c in config.creatives)
    if getattr(args, "plan", False):
        # Everything above is read-only: every library is cached, the queue
        # was loaded, nothing has been rendered, uploaded or written. Stopping
        # here answers "what would tonight do" without doing it.
        carried_by_creative = Counter(i.creative for i in carried)
        print(f"\n  {config.slug} · render plan")
        print(f"    carried forward     {len(carried)}")
        print(f"    expired, dropped    {len(expired)}")
        print(f"    backlog target      {target}"
              f"  ({config.posting.posts_per_day}/day x "
              f"{config.posting.max_backlog_days} days)")
        print(f"    from the lineup     {len(timed) + len(untimed)}"
              + (f"  ({waiting} more waiting for room)" if waiting else ""))
        for entry in (*timed, *untimed):
            when = (
                resolve_time(entry.at, config.zone).strftime("%a %d %b %H:%M")
                if entry.at else "next free slot"
            )
            print(f"      {entry.id:<28} {when}")
        for entry in missed:
            print(f"      {entry.id:<28} MISSED its time — will not post")
        print(f"    randomizer fills    {count}"
              + ("" if config.selection.auto_fill else "  (auto_fill is off)"))
        for creative in config.creatives:
            res = resources[creative.name]
            share = creative.weight / total_weight
            print(
                f"\n    {creative.name} (weight {creative.weight:g}, "
                f"~{share:.0%} of slots)"
            )
            print(f"      carried forward       {carried_by_creative.get(creative.name, 0)}")
            print(f"      expected tonight      ~{count * share:.1f}")
            print(f"      combinations, used    {res.ceiling:,}, {len(res.history.entries):,}")
            print(f"      distinct visuals      {res.distinct_visuals:,}")
        if count == 0 and not timed and not untimed:
            print("\n  Nothing to render tonight.")
        return 0

    if count == 0 and not timed and not untimed:
        # Still rewrite the queue: terminal and expired items were pruned above,
        # and leaving them in place would re-report yesterday's finished work
        # as pending.
        #
        # This write must also always *change* the file, and ``generated_at``
        # is what guarantees it. GitHub disables a cron schedule after 60 days
        # with no commits, and render.yml's nightly commit is what keeps it
        # alive (SPEC §12). A no-op night that wrote a byte-identical queue
        # would commit nothing; sixty of them in a row and the whole pipeline
        # stops on a timer nobody is watching.
        log.info("render_skipped", reason="nothing due",
                 carried=len(carried))
        save_queue(
            campaign_dir / "queue.json",
            Queue(generated_at=today, items=carried),
        )
        print(
            f"OK {config.slug}: backlog holds {len(carried)} unpublished "
            f"videos (target {target}) and no lineup post is due; rendered "
            f"nothing."
        )
        return 0

    # A typo in an account name would otherwise render a video that no
    # account ever claims, and it would sit in the queue until it aged out.
    def _targets(names: Sequence[str], what: str) -> list[str] | None:
        if not names:
            return None
        if not config.posting.fan_out:
            raise ConfigError(
                f"{what} names accounts {list(names)} but posting.fan_out is "
                f"off, so this campaign posts to its own single channel"
            )
        known = {a.name for a in reachable}
        unknown = [n for n in names if n not in known]
        if unknown:
            raise ConfigError(
                f"{what} names account(s) {unknown} that this campaign does "
                f"not reach — it reaches: {sorted(known) or 'none'}"
            )
        return list(names)

    creative_accounts = {
        c.name: _targets(c.accounts, f"creative {c.name!r}")
        for c in config.creatives
    }

    def _networks(names: list[str] | None) -> set[Service]:
        if not config.posting.fan_out:
            return {config.buffer.service}
        return {
            a.network for a in reachable if names is None or a.name in names
        }

    # A plan is (creative, selection, lineup entry or None).
    planned: list[tuple[str, Selection, LineupEntry | None]] = []
    for entry in (*timed, *untimed):
        creative = _resolve_creative(config, entry.creative)
        by_name = resources[creative.name].by_name
        wanted = [entry.hook, *entry.bodies, *([entry.music] if entry.music else [])]
        absent = [n for n in wanted if n not in by_name]
        if absent:
            raise ConfigError(
                f"lineup {entry.id!r}: {absent} not in creative "
                f"{creative.name!r}'s library (or muted). It has: "
                f"{sorted(by_name)}"
            )
        names = _targets(entry.accounts, f"lineup {entry.id!r}")
        if names is None:
            names = creative_accounts[creative.name]
        for service in _networks(names):
            text = entry.captions.get(service, entry.caption)
            problems = check_description(text, service)
            problems += check_title(entry.title, service) if entry.title else []
            if problems:
                raise ConfigError(
                    f"lineup {entry.id!r} cannot post to {service.value}: "
                    + "; ".join(problems)
                )
        planned.append((
            creative.name,
            Selection(
                hook=entry.hook, bodies=entry.bodies, music=entry.music,
                caption=entry.caption, title=entry.title,
                music_offset_sec=entry.music_start if entry.music else 0.0,
            ),
            entry,
        ))

    # What has actually performed, from this campaign's own posts. Computed
    # per creative from that creative's own history slice: two creatives can
    # legitimately reuse a filename (each has its own Release tag), so
    # ranking off the whole campaign's history would risk crediting one
    # creative's views to a same-named clip in another.
    picks: list[tuple[str, Any]] = []
    if count:
        performance = {
            name: medians
            for name, res in resources.items()
            if (medians := _performance_medians(config, res.history, log)) is not None
        }
        pools = {name: (res.library, res.history) for name, res in resources.items()}
        weights = {c.name: c.weight for c in config.creatives}
        boost = _style_boost(config)
        # A song with favoured clips it has not posted yet comes up that much more often too: otherwise the
        # band's footage of one song waits its turn behind every other song (a few days on close__quarters).
        for name, clips in (boost or {}).items():
            if name in resources and name in weights:
                posted = {e.hook for e in resources[name].history.entries}
                if any(clip not in posted for clip in clips):
                    weights[name] *= max(clips.values())
        # The quota's slots first (selection.style_quota), then the ordinary
        # selector fills what is left against pools that already hold them.
        if config.selection.style_quota:
            picks, pools = _quota_picks(
                config, selector, pools, weights, count, _clip_styles(config), today, log,
                performance=performance, visual_pools=_visual_pools(config, resources),
            )
        if len(picks) < count:
            picks += selector.select_batch_multi(
                pools, weights, count - len(picks), config.composition.bodies_per_video,
                config.composition.bodies_per_video_max,
                performance=performance,
                boost=boost,
                visual_pools=_visual_pools(config, resources),
            )
    relaxed = [(name, o) for name, o in picks if o.relaxation is not Relaxation.NONE]
    if relaxed and not config.selection.repeats:
        # No repeats on this account: a relaxed pick would put up a video it
        # has already posted (or two of the same in one night). Leave the slot.
        log.warning("repeat_dropped", dropped=len(relaxed), kept=len(picks) - len(relaxed))
        picks = [(name, o) for name, o in picks if o.relaxation is Relaxation.NONE]
        relaxed = []
    if relaxed:
        by_creative = Counter(name for name, _ in relaxed)
        detail = ", ".join(f"{name}: {n}" for name, n in by_creative.items())
        notifier.notify(
            NotifyEvent.DEDUPE_RELAXED,
            f"⚠️ {config.slug}: {len(relaxed)}/{len(picks)} selections needed "
            f"relaxed dedupe ({relaxed[0][1].relaxation.value}) — {detail}. "
            f"The library is too small for {config.posting.posts_per_day} "
            f"posts/day.",
        )
    planned += [(name, outcome.selection, None) for name, outcome in picks]

    # Under fan-out one video reaches several networks, and their copy is
    # genuinely different rather than one caption rephrased — so each network
    # with a bank of its own gets its own pick here, where the recency
    # weighting and cooldowns already live. Push time only looks them up.
    # A creative's own per-network bank wins over the campaign's.
    campaign_banks = _extra_network_banks(config, campaign_dir, log)
    banks_by_creative: dict[str, dict[Service, list[Description]]] = {}
    for name, res in resources.items():
        merged = dict(campaign_banks)
        merged.update({svc: list(bank) for svc, bank in res.network_banks})
        banks_by_creative[name] = merged
    network_last_used = {
        service: _caption_last_used(full_history, service) for service in Service
    }
    # Banks written for a studio style (captions/<style>.txt), loaded per song
    # so {name} is the song's; the style of a clip comes from recipes.json.
    # Campaign-wide recency: the same line should not open two posts of the
    # style on one account whichever songs they are.
    clip_styles = _clip_styles(config)
    style_banks: dict[tuple[str, str], list[Description]] = {}
    for name, res in resources.items():
        for style in sorted(set(clip_styles.get(name, {}).values())):
            path = _creative_bank_path(config, res.creative, campaign_dir, style=style)
            if path.parent.name == BANK_DIR and path.stem == style:
                style_banks[(name, style)] = _load_captions(
                    path, config.buffer.service, config.buffer.title_strategy,
                    _caption_names(config, res.creative),
                )
    style_last_used: dict[str, datetime] = {}
    for e in full_history.entries:
        if e.caption and (e.caption not in style_last_used or e.timestamp > style_last_used[e.caption]):
            style_last_used[e.caption] = e.timestamp

    # Fill the next free slots rather than deferring the whole batch a day.
    # SPEC §4.2 wanted the render->push gap as a review window, but the review
    # window that actually matters is Buffer's own queue: a pushed post sits
    # there, visible and deletable, until its slot arrives.
    timed_slots = {
        e.id: resolve_time(e.at, config.zone) for e in timed if e.at is not None
    }
    floating = sum(1 for _, _, e in planned if e is None or e.at is None)
    slots = upcoming_slots(
        today,
        floating,
        config.posting.start_hour,
        config.posting.end_hour,
        config.posting.posts_per_day,
        config.zone,
        # Carried items already hold slots; two videos in one slot would be
        # published minutes apart, which is the failure the schedule prevents.
        exclude={i.scheduled_for for i in carried} | set(timed_slots.values()),
        # Two campaigns posting to the same accounts on the same grid would
        # land on the same minute; this is what keeps them apart. It used to
        # be read only when a stale slot was reassigned, so a campaign's
        # offset never reached the slots render handed out.
        offset_min=config.posting.slot_offset_min,
    )
    if len(slots) < floating:
        raise ConfigError(
            f"only {len(slots)} slots available for {floating} videos; "
            f"posts_per_day is {config.posting.posts_per_day}"
        )
    free = iter(slots)

    funnel = config.funnel
    bodies_by_variant: dict[tuple[str, str], str] = {}
    by_account = {a.name: a for a in reachable}
    per_account = (
        config.posting.fan_out and config.variation.enabled
        and config.variation.per_account
    )
    vary = set(config.variation.per_account_vary)
    # Clips no account version may use: anything under the hook cooldown in
    # any creative sharing the clip's pool (every account's version counts),
    # and anything already going out tonight. Keyed (pool, clip).
    pools_by_creative = _visual_pools(config, resources)
    clip_cutoff = today - timedelta(days=config.selection.hook_cooldown_days)
    clips_taken: set[tuple[str, str]] = set()
    for name, res in resources.items():
        pool = pools_by_creative.get(name, f"creative:{name}")
        for e in res.history.entries:
            if e.timestamp > clip_cutoff:
                clips_taken.update((pool, h) for h in entry_hooks(e))
    for name, sel, _ in planned:
        clips_taken.add((pools_by_creative.get(name, f"creative:{name}"), sel.hook))

    def _fill(text: str, creative: CreativeConfig) -> str:
        """Funnel text with this creative's own name and link filled in.

        Empty when the text asks for a link or a name nobody has supplied:
        "listen here: " with nothing after it is worse than no ask at all.
        """
        link = creative.link or funnel.link
        name = creative.title or funnel.name
        if ("{link}" in text and not link) or ("{name}" in text and not name):
            return ""
        return text.replace("{link}", link).replace("{name}", name).strip()

    def _with_cta(
        text: str, service: Service, creative: CreativeConfig, turn: int
    ) -> str:
        """The caption with this post's ask appended, if it is due one."""
        if turn % funnel.cta_every:
            return text
        # A network's own lines first; the shared ones if none of those can
        # be filled in (a link nobody has set yet).
        ask = ""
        for lines in (funnel.cta_by_network.get(service, ()), funnel.cta):
            usable = [line for line in (_fill(l, creative) for l in lines) if line]
            if usable:
                ask = usable[(turn // funnel.cta_every) % len(usable)]
                break
        if not ask or ask.lower() in text.lower():
            return text
        joined = f"{text.rstrip()}\n\n{ask}"
        if check_description(joined, service):
            # Too long with the ask on: the caption someone wrote wins.
            log.warning("cta_dropped_too_long", network=service.value)
            return text
        return joined

    # (item, base selection, creative, [(account or None, file, variant)])
    rendered: list[
        tuple[QueueItem, Selection, str, list[tuple[str | None, Path, Variant]]]
    ] = []
    # A slot handed to a video that then failed validation goes back here for
    # the next one, so one bad clip leaves no hole in the day.
    freed_slots: list[datetime] = []
    for index, (creative_name, selection, pinned) in enumerate(planned):
        res = resources[creative_name]
        creative = res.creative
        by_name = res.by_name
        # Counts every post this campaign has ever made, so the rotation of
        # asks carries on across nights instead of restarting at the first.
        turn = len(full_history.entries) + index
        slot = (
            timed_slots[pinned.id] if pinned is not None and pinned.at is not None
            else (freed_slots.pop(0) if freed_slots else next(free))
        )
        # A bank written for the clip's style beats the song's or the
        # campaign's: on physics_sims "count the bounces" went out under
        # wind-tunnel videos and the wind-tunnel lines under balls (11-26).
        style = clip_styles.get(creative_name, {}).get(selection.hook)
        style_bank = style_banks.get((creative_name, style or "")) if pinned is None else None
        if style_bank:
            chosen = pick_by_recency(
                [d.body for d in style_bank], style_last_used, today, rng,
                config.selection.caption_cooldown_days,
            )
            style_last_used[chosen] = today + timedelta(microseconds=index + 1)
            selection = selection.model_copy(update={"caption": chosen})
            log.info("caption_by_style", creative=creative_name, clip=selection.hook, style=style)
        record = (
            next((d for d in style_bank if d.body == selection.caption), None) if style_bank
            else res.record_for(selection.caption)
        ) if pinned is None else None
        overlay = pinned.overlay if pinned is not None else (
            record.overlay if record else None
        )
        title = selection.title if pinned is not None else (
            record.title if record else None
        )
        use_funnel = pinned is None or pinned.funnel
        item_id = str(uuid.uuid4())

        net_captions: dict[str, str] = {}
        net_titles: dict[str, str] = {}
        if pinned is not None:
            # Hand-written: the entry's own per-network text, nothing drawn
            # from a bank.
            net_captions = {svc.value: text for svc, text in pinned.captions.items()}
        else:
            # One pick per network with copy of its own, each against that
            # network's own recency — so TikTok repeating a caption says
            # nothing about when Instagram last used one of its own.
            for service, bank in banks_by_creative[creative_name].items():
                bodies = [d.body for d in bank]
                chosen = pick_by_recency(
                    bodies, network_last_used[service], today, rng,
                    config.selection.caption_cooldown_days,
                )
                net_captions[service.value] = chosen
                net_title = next((d.title for d in bank if d.body == chosen), None)
                if net_title:
                    net_titles[service.value] = net_title
                # Within this batch too: without it a night's videos could
                # hand one network the same caption several times over.
                network_last_used[service][chosen] = today + timedelta(
                    microseconds=len(rendered) + 1
                )

        accounts = (
            _targets(pinned.accounts, f"lineup {pinned.id!r}")
            if pinned is not None else None
        ) or creative_accounts[creative_name]
        going_to = [
            a.name for a in reachable if accounts is None or a.name in accounts
        ]

        # One version per account when asked for, otherwise one for everyone.
        # The first account keeps the pick as made; each later one is varied
        # in whatever ways the library has room for. A hand-picked post is
        # never re-picked — its versions differ only by treatment.
        versions: list[tuple[str | None, Selection, str | None, str | None]] = []
        if per_account and len(going_to) > 1:
            used_hooks = {selection.hook}
            used_captions = {selection.caption}
            used_offsets = {selection.music_offset_sec}
            for position, dest_account in enumerate(going_to):
                if position == 0 or pinned is not None:
                    versions.append((dest_account, selection, overlay, title))
                    continue
                hook, caption, offset = (
                    selection.hook, selection.caption, selection.music_offset_sec
                )
                v_overlay, v_title = overlay, title
                if "clip" in vary:
                    pool = pools_by_creative.get(creative_name, f"creative:{creative_name}")
                    spare = tuple(
                        h for h in res.library.hooks
                        if h not in used_hooks and (pool, h) not in clips_taken
                    )
                    if not spare and config.selection.repeats:
                        # Repeats allowed: a clip that is cooling down (or out
                        # tonight on another post) still beats this account
                        # getting the very same video as the first one.
                        spare = tuple(h for h in res.library.hooks if h not in used_hooks)
                    if spare:
                        hook = rng.choice(spare)
                        used_hooks.add(hook)
                        clips_taken.add((pool, hook))
                    elif not config.selection.repeats:
                        # No clip this account has not had lately: it sits this
                        # post out rather than getting the same video as the
                        # first account (the same meme on two accounts).
                        log.warning(
                            "variant_dropped", creative=creative_name,
                            account=dest_account, hook=selection.hook,
                        )
                        continue
                if "caption" in vary:
                    fresh = tuple(
                        d for d in res.descriptions if d.body not in used_captions
                    )
                    if fresh:
                        other = rng.choice(fresh)
                        caption, v_overlay, v_title = other.body, other.overlay, other.title
                        used_captions.add(caption)
                if "cue" in vary and selection.music:
                    cues = tuple(
                        o for o in (
                            res.library.offset_for(selection.music, n)
                            for n in range(res.library.segments_for(selection.music))
                        )
                        if o not in used_offsets
                    )
                    if cues:
                        offset = rng.choice(cues)
                        used_offsets.add(offset)
                versions.append((
                    dest_account,
                    selection.model_copy(update={
                        "hook": hook, "caption": caption,
                        "music_offset_sec": offset,
                    }),
                    v_overlay, v_title,
                ))
            if len(versions) < len(going_to):
                # An account that sat out must not get the item's own video at
                # push time either (an account without a version gets that).
                accounts = [name for name, _, _, _ in versions if name is not None]
        else:
            versions.append((None, selection, overlay, title))

        end_card = _fill(funnel.end_card, creative) if use_funnel else ""
        files: list[tuple[str | None, Path, Variant]] = []
        version_account: str | None
        rejected: str | None = None
        for version_account, version, v_overlay, v_title in versions:
            account_name = version_account
            render_id = item_id if account_name is None else f"{item_id}-{account_name}"
            try:
                result = renderer.render(RenderRequest(
                    item_id=render_id,
                    hook_path=by_name[version.hook],
                    body_paths=tuple(by_name[b] for b in version.bodies),
                    music_path=by_name[version.music] if version.music else None,
                    music_offset_sec=version.music_offset_sec,
                    output_path=out_dir / f"{render_id}.mp4",
                    overlay_text=v_overlay,
                    end_card_text=end_card or None,
                ))
            except ValidationError as exc:
                # One clip that comes out too short (or too long, or the wrong
                # size) used to fail the whole account's render. Skip it.
                rejected = str(exc)
                break
            # What this account posts with: its own varied caption if it got
            # one, else its network's, else the shared one — then the ask.
            text = version.caption
            if account_name is not None:
                bodies_by_variant[(item_id, account_name)] = version.caption
                network = by_account[account_name].network
                if version.caption == selection.caption:
                    text = net_captions.get(network.value, version.caption)
                    v_title = net_titles.get(network.value, v_title)
                if use_funnel:
                    text = _with_cta(text, network, creative, turn)
            files.append((
                account_name,
                result.output_path,
                Variant(
                    caption=text, title=v_title, overlay=v_overlay,
                    parts={
                        "hook": version.hook,
                        "bodies": ",".join(version.bodies),
                        "music": version.music or "",
                        "music_offset_sec": f"{version.music_offset_sec:g}",
                    },
                    treatment=result.treatment,
                ),
            ))

        if rejected is not None:
            log.warning(
                "item_rejected", creative=creative_name, hook=selection.hook,
                reason=rejected[:200],
            )
            if pinned is not None:
                raise ValidationError(rejected)     # a hand-picked post must not vanish quietly
            freed_slots.insert(0, slot)
            continue

        first = files[0][2]
        caption = selection.caption
        if use_funnel:
            # The shared texts carry the ask too, for any account that has no
            # version of its own.
            networks = {a.network for a in reachable} or {config.buffer.service}
            for service in networks:
                base = net_captions.get(service.value, selection.caption)
                asked = _with_cta(base, service, creative, turn)
                if asked != base:
                    net_captions[service.value] = asked
            if not config.posting.fan_out:
                caption = _with_cta(caption, config.buffer.service, creative, turn)
        comments = [
            line for line in (_fill(c, creative) for c in funnel.first_comment)
            if line
        ] if use_funnel else []
        first_comment = comments[turn % len(comments)] if comments else None
        rendered.append((
            QueueItem(
                id=item_id,
                scheduled_for=slot,
                rendered_at=today,
                video_url="",  # filled in after upload
                caption=caption,
                title=title,
                captions=net_captions,
                titles=net_titles,
                parts=first.parts,
                treatment=first.treatment,
                creative=creative_name,
                overlay=overlay,
                accounts=accounts,
                lineup_id=pinned.id if pinned is not None else None,
                first_comment=first_comment or None,
            ),
            selection,
            creative_name,
            files,
        ))
        log.info(
            "item_rendered", item_id=item_id, creative=creative_name,
            lineup_id=pinned.id if pinned is not None else None,
            versions=len(files),
        )

    tag = _render_tag(config.slug, today)
    published = store.publish(
        tag, [path for _, _, _, files in rendered for _, path, _ in files]
    )
    base = media_base(REPO_ROOT)
    urls = {a.name: public_media_url(a.url, base) for a in published}
    for item, _, _, files in rendered:
        item.video_url = urls[files[0][1].name]
        for owner, path, made in files:
            if owner is not None:
                item.variants[owner] = made.model_copy(
                    update={"video_url": urls[path.name]}
                )

    queue = Queue(
        generated_at=today,
        items=sorted(
            [*carried, *(i for i, _, _, _ in rendered)],
            key=lambda i: i.scheduled_for,
        ),
    )
    save_queue(campaign_dir / "queue.json", queue)
    append_history(
        campaign_dir / "history.json",
        [
            HistoryEntry(
                tuple_hash=tuple_hash(sel, config.selection.dedupe_on),
                timestamp=today,
                item_id=item.id,
                hook=sel.hook,
                bodies=sel.bodies,
                music=sel.music,
                music_offset_sec=sel.music_offset_sec,
                caption=sel.caption,
                title=item.title,
                # Carried from the queue item so history and queue cannot
                # disagree about what was actually rendered.
                captions=item.captions,
                treatment=item.treatment,
                creative=creative_name,
                overlay=item.overlay,
                lineup_id=item.lineup_id,
                variants={
                    name: {
                        "hook": v.parts.get("hook", ""),
                        # The bank record it was drawn from, before any ask
                        # was appended — that is what attribution ranks.
                        "caption": bodies_by_variant.get((item.id, name), ""),
                        "music_offset_sec": v.parts.get("music_offset_sec", "0"),
                    }
                    for name, v in item.variants.items()
                },
            )
            for item, sel, creative_name, _ in rendered
        ],
    )

    log.info("render_complete", items=len(rendered), tag=tag)
    for creative in config.creatives:
        res = resources[creative.name]
        # Per-creative rate estimate from its share of the weighted draw —
        # posts_per_day is campaign-wide, so a creative that only wins a
        # fraction of slots exhausts its own pool proportionally slower.
        share = creative.weight / total_weight
        creative_rate = config.posting.posts_per_day * share
        runway = days_until_first_repeat(
            res.library, res.history, config.composition.bodies_per_video,
            max(creative_rate, 1e-9),
        )
        log.info(
            "creative_runway", creative=creative.name, runway_days=runway,
            ceiling=res.ceiling, distinct_visuals=res.distinct_visuals,
        )
        if runway < 7:
            notifier.notify(
                NotifyEvent.QUEUE_EMPTY,
                f"⚠️ {config.slug}/{creative.name}: only {runway:.0f} days of "
                f"unique combinations remain. Add hooks, bodies or captions.",
            )
    return 0


# ------------------------------------------------------------------- command: topup


def cmd_topup(args: argparse.Namespace, env: dict[str, str]) -> int:
    clock: Clock = SystemClock()
    log = get_logger(command="topup", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    if args.dry_run:
        config = config.model_copy(
            update={"posting": config.posting.model_copy(update={"dry_run": True})}
        )
    notifier = notifier_for(config, log, env)
    if config.posting.paused:
        log.info("campaign_paused", campaign=config.slug)
        print(f"{config.slug} is paused (posting.paused) — pushed nothing.")
        return 0

    try:
        if config.posting.fan_out:
            registry = load_accounts(REPO_ROOT / ACCOUNTS_FILE)
            return _topup_fanout(args, env, config, log, notifier, clock, registry)
        return _topup(args, env, config, log, notifier, clock)
    except UgcError as exc:
        log.exception("topup_failed", exc)
        notifier.failure("topup", exc, campaign=config.slug)
        return 1


def _first_comment_refused(exc: Exception) -> bool:
    """Whether Buffer rejected a post only because it carried a first comment."""
    text = str(exc).lower()
    return "first comment" in text and ("paid plan" in text or "upgrade" in text)


#: Links already confirmed readable in this process, so a video going to six
#: accounts is asked for once.
_READABLE: set[str] = set()


def _postable_url(url: str, config: CampaignConfig) -> str:
    """The link to hand Buffer for one video, checked before anything is claimed.

    Raises before the item is touched if the link cannot be read without
    signing in — see ``assert_publicly_readable``. Only checked when the repo
    names a public media address and the post is real.
    """
    base = media_base(REPO_ROOT)
    public = public_media_url(url, base)
    if base and not config.posting.dry_run and public not in _READABLE:
        assert_publicly_readable(public)
        _READABLE.add(public)
    return public


def _account_channel(account: AccountConfig, env: dict[str, str]) -> str:
    """Resolve one account's channel id from config, or from its secret."""
    if account.channel_id:
        return account.channel_id
    assert account.channel_id_secret is not None  # enforced by the schema
    channel = _secret(account.channel_id_secret, env)
    if not channel:
        raise ConfigError(
            f"{account.channel_id_secret} is not set — account "
            f"{account.name!r} has no Buffer channel to post to"
        )
    return channel


def _account_publishers(
    accounts: Sequence[AccountConfig],
    config: CampaignConfig,
    env: dict[str, str],
    log: StructuredLogger,
) -> dict[str, Publisher]:
    """One publisher per key slot, not per account.

    Accounts under one Buffer login share a key, and must also share the
    request tally that ``_report_quota`` sums against the 3,000/30-day
    allowance — a publisher each would count the same budget several times
    over and never reach the alert.
    """
    publishers: dict[str, Publisher] = {}
    for account in accounts:
        slot = account.api_key_secret
        if slot in publishers:
            continue
        if config.posting.dry_run:
            log.info("dry_run_enabled", campaign=config.slug, slot=slot)
            publishers[slot] = DryRunPublisher(log)
            continue
        api_key = _secret(slot, env)
        if not api_key:
            raise ConfigError(
                f"{slot} is not set — cannot publish to {account.name}. "
                f"Set the secret, or set posting.dry_run: true."
            )
        publishers[slot] = _real_publisher(account, api_key, log)
    return publishers


def _real_publisher(
    account: AccountConfig, secret: str, log: StructuredLogger
) -> BufferPublisher | InstagramPublisher:
    """The publisher one account posts through. Never a dry-run stand-in.

    The one place that knows there is more than one kind: an account says
    which with ``provider:`` in the accounts file, and everything else holds
    a ``Publisher`` without caring.
    """
    if account.provider is Provider.INSTAGRAM:
        return InstagramPublisher(
            secret, log,
            outbox_dir=REPO_ROOT / OUTBOX_DIR,
            login=account.login.value,
        )
    return BufferPublisher(secret, log, organization_id=account.organization_id)


#: Volumes a Reel is posted with when its song's catalogue track is attached. The video keeps its own sound at
#: full volume: that sound IS the song, cut to the window the lyrics and beats on screen were made for, and
#: ``audio_configuration`` has no start offset, so letting the catalogue track play would start the song over
#: from 0:00 under every lyric video. The track rides along at the lowest volume Instagram takes, which is all it
#: needs to file the Reel under the song's audio page and credit the band instead of the niche account.
AUDIO_TAG_VOLUME = 1
AUDIO_TAG_VIDEO_VOLUME = 100
SONGS_DIR = Path("studio") / "songs"


def _song_audio(config: CampaignConfig, creative_name: str) -> dict[str, Any] | None:
    """``audio_id`` and volumes for a creative's song, or None while the song has no catalogue id.

    The creative's own ``ig_audio_id`` wins; otherwise ``studio/songs/<slug>/song.json`` (the slug is the creative
    name with hyphens), where ``ig_audio_id``, ``ig_audio_volume`` and ``ig_video_volume`` sit beside the song's
    other facts, so one file per song serves every campaign that posts it.
    """
    creative = next((c for c in config.creatives if c.name == creative_name), None)
    audio_id = creative.ig_audio_id if creative else None
    volume, video_volume = AUDIO_TAG_VOLUME, AUDIO_TAG_VIDEO_VOLUME
    try:
        song = json.loads(
            (REPO_ROOT / SONGS_DIR / creative_name.replace("_", "-") / "song.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        song = {}
    if isinstance(song, dict):
        audio_id = audio_id or (str(song.get("ig_audio_id") or "").strip() or None)
        volume = int(song.get("ig_audio_volume") or volume)
        video_volume = int(song.get("ig_video_volume") or video_volume)
    if not audio_id:
        return None
    return {"audio_id": audio_id, "audio_volume": volume, "video_volume": video_volume}


def _held_post_paths(publisher: Publisher) -> list[Path]:
    """Files a publisher wrote that must be committed with the queue.

    Buffer holds a scheduled post on its own servers. A direct Instagram
    account's are held in the repo, so a push that is not committed is a post
    that will never go out.
    """
    if isinstance(publisher, InstagramPublisher) and publisher.touched:
        return [REPO_ROOT / OUTBOX_DIR]
    return []


def _topup_fanout(
    args: argparse.Namespace,
    env: dict[str, str],
    config: CampaignConfig,
    log: StructuredLogger,
    notifier: Notifier,
    clock: Clock,
    registry: AccountsConfig,
) -> int:
    """Push each rendered video to every account this campaign reaches.

    The same video, once per channel, each channel tracked independently:
    one account rejecting a post leaves the other five untouched, and a
    channel that is behind catches up on its own without holding anyone back.

    Expansion happens here rather than at render time, which is what lets a
    video rendered before fan-out existed still reach every account, and keeps
    the render job entirely unaware that accounts exist.
    """
    campaign_dir = _campaign_dir(config.slug)
    queue_path = campaign_dir / "queue.json"
    history_path = campaign_dir / "history.json"

    targets = accounts_for(registry, config.accounts)
    if not targets:
        log.warning(
            "no_accounts_resolved", campaign=config.slug,
            registry_size=len(registry.accounts),
        )
        print(
            f"{config.slug}: fan_out is on but no account in "
            f"{ACCOUNTS_FILE} is both enabled and allowed by this campaign.",
            file=sys.stderr,
        )
        return 1

    queue = load_queue(queue_path)
    publishers = _account_publishers(targets, config, env, log)
    vcs: Vcs = (
        NullVcs(log)
        if config.posting.dry_run or args.no_commit
        else GitVcs(REPO_ROOT, log)
    )

    # Give every item still in flight a record per account. Items already
    # finished before fan-out existed keep their own terminal status and are
    # left alone — back-filling those would re-post a video that has already
    # been out for weeks.
    pairs = [(a.name, a.network) for a in targets]
    expanded = 0
    for item in queue.items:
        if not item.posts and item.status in (
            QueueStatus.PUSHED, QueueStatus.CANCELLED, QueueStatus.FAILED
        ):
            continue
        # An item may name its own accounts (a creative's, or a lineup
        # entry's). It gets a record only for those, so every other account
        # simply never sees it as claimable.
        wanted = [
            pair for pair in pairs
            if item.accounts is None or pair[0] in item.accounts
        ]
        if not wanted and not item.posts:
            log.warning(
                "item_reaches_no_account", item_id=item.id,
                accounts=item.accounts,
            )
        expanded += len(ensure_posts(item, wanted))
        sync_status(item)
    if expanded:
        log.info("fanout_expanded", campaign=config.slug, records=expanded,
                 accounts=[a.name for a in targets])
        save_queue(queue_path, queue)

    pushed_total = 0
    # Posts of this campaign's own already waiting at the backend, by account:
    # history records every post id a push returned.
    own_post_ids = {
        pid
        for entry in load_history(history_path).entries
        for pid in (entry.buffer_post_id, *entry.post_ids.values())
        if pid
    }
    held: dict[str, list[tuple[str, datetime | None]]] = {}
    for account in targets:
        publisher = publishers[account.api_key_secret]
        channel = (
            "dry-run-channel" if config.posting.dry_run
            else _account_channel(account, env)
        )
        alog = log.bind(account=account.name, network=account.network.value)

        # SPEC §11 — reconcile anything a previous run left mid-flight for
        # THIS account before considering new work for it.
        _reconcile_stranded_account(
            queue, account, publisher, channel, queue_path, history_path, alog, vcs
        )

        revived = 0
        for item in queue.items:
            post = post_for(item, account.name)
            if (
                post is not None
                and post.status is QueueStatus.FAILED
                and post.attempts < QueueItem.MAX_ATTEMPTS
            ):
                reset_post_for_retry(post, item.id, log=alog)
                sync_status(item)
                revived += 1
        if revived:
            alog.info("revived_failed_records", count=revived)
            save_queue(queue_path, queue)

        state = publisher.queue_state(channel)
        need = depth_needed(state.depth, account.max_buffer_queue)
        # A channel two campaigns feed: this one stops at its own share of the
        # queue, so the other is not left reading "full" on every run.
        share = config.posting.buffer_share
        own = sum(1 for pid, _ in state.scheduled if pid in own_post_ids)
        if share is not None:
            need = min(need, max(0, share - own))
        ready = claimable_for(queue, account.name)
        to_push = ready[:need]
        gap = state.gap_hours(clock.now())
        held[account.name] = [(pid, at) for pid, at in state.scheduled if pid in own_post_ids]

        alog.info(
            "topup_plan",
            buffer_depth=state.depth, cap=account.max_buffer_queue, need=need,
            own=own, share=share,
            available=len(ready), pushing=len(to_push),
            next_due_in_hours=None if gap is None else round(gap, 1),
        )

        limit = config.notify.max_schedule_gap_hours
        if gap is not None and gap > limit and not to_push:
            alog.warning(
                "schedule_gap", next_due_in_hours=round(gap, 1), limit=limit,
                depth=state.depth,
            )
            notifier.notify(
                NotifyEvent.SCHEDULE_GAP,
                f"{config.slug} → {account.name}: Buffer holds {state.depth} "
                f"post(s) but the next one is {gap:.0f}h away, over the "
                f"{limit:.0f}h limit. Nothing has failed — the slots are "
                f"simply too far out.",
            )
        if not to_push:
            if not ready and state.depth == 0:
                notifier.notify(
                    NotifyEvent.QUEUE_EMPTY,
                    f"⚠️ {config.slug} → {account.name}: Buffer queue is empty "
                    f"and nothing is pending. Nothing will publish to this "
                    f"account until the next render.",
                )
            continue

        pushed_total += _push_to_account(
            to_push, account, publisher, channel, config, queue, queue_path,
            history_path, clock, notifier, alog, vcs,
        )

    _record_backend_queue(campaign_dir, held, queue, clock, vcs, log)
    _report_quota_count(
        sum(getattr(p, "request_count", 0) for p in publishers.values()),
        notifier, config, log, clock, vcs,
    )
    log.info("topup_complete", pushed=pushed_total, accounts=len(targets))
    return 0


def _record_backend_queue(
    campaign_dir: Path,
    held: dict[str, list[tuple[str, datetime | None]]],
    queue: Queue,
    clock: Clock,
    vcs: Vcs,
    log: StructuredLogger,
) -> None:
    """Keep what a scheduling backend holds for this campaign, for the dashboard.

    queue.json forgets a pushed item at the next render, hours or days before
    the backend publishes it, and history.json never knew its time: half of
    what Buffer held was on no page anyone could look at. This file is the
    campaign's own posts waiting there, by account, as read at the start of
    this run plus what this run pushed. Nothing is written for a campaign whose
    backends cannot list their queue (direct posting keeps its own outbox).
    """
    if not any(held.values()):
        return
    posts: dict[str, dict[str, str | None]] = {}
    for name, rows in held.items():
        for pid, at in rows:
            posts[pid] = {"account": name, "due": at.isoformat() if at else None}
    for item in queue.items:                      # this run's pushes, and any still in the queue
        for post in item.posts:
            if post.buffer_post_id and post.status is QueueStatus.PUSHED and post.account in held:
                when = post.scheduled_for or item.scheduled_for
                if when and when > clock.now():
                    posts.setdefault(post.buffer_post_id, {"account": post.account, "due": when.isoformat()})
    path = campaign_dir / "backend_queue.json"
    body = json.dumps({"posts": dict(sorted(posts.items()))}, indent=1) + "\n"
    if path.exists() and path.read_text() == body:
        return
    path.write_text(body)
    vcs.commit([path], f"backend queue {campaign_dir.name}")
    log.info("backend_queue_recorded", posts=len(posts))


def _push_to_account(
    to_push: list[QueueItem],
    account: AccountConfig,
    publisher: Publisher,
    channel: str,
    config: CampaignConfig,
    queue: Queue,
    queue_path: Path,
    history_path: Path,
    clock: Clock,
    notifier: Notifier,
    log: StructuredLogger,
    vcs: Vcs,
) -> int:
    """Push a batch of items to one account, claiming each before it goes."""
    offset = timedelta(minutes=account.slot_offset_min)
    now = clock.now()
    lead = timedelta(minutes=10)

    # Buffer rejects a past-dated post outright and the rejection is not
    # retryable, so slots that have gone by are reassigned — but onto
    # *successive* free slots, never all onto one. Pinning every stale item to
    # "now plus a bit" would hand this channel three videos on the same
    # minute, which is the failure the schedule exists to prevent.
    taken = {
        p.scheduled_for
        for i in queue.items
        for p in i.posts
        if p.account == account.name and p.scheduled_for is not None
    }
    # And the minutes the network already holds a post for. A render drops pushed
    # items from queue.json, so after a late or an extra render its new batch can
    # be handed the very slots yesterday's pushes still occupy; without this both
    # posts went out on the same minute. A failed lookup only loses the guard.
    try:
        held = {
            d.replace(second=0, microsecond=0)
            for d in publisher.scheduled_slots(channel)
        }
    except Exception as exc:  # noqa: BLE001 - never let the guard stop the top-up
        log.warning("scheduled_slots_unavailable", error=str(exc)[:200])
        held = set()
    taken |= held
    # A day is full once the account holds posts_per_day posts on it. Slots were only ever checked minute by
    # minute, so a change of grid (an earlier window, more posts a day) put the new grid's posts on top of
    # everything the old grid had already booked. A campaign that shares its channel is limited by its
    # buffer_share instead: the other campaign's posts are not its own day.
    cap = None if config.posting.buffer_share is not None else config.posting.posts_per_day
    per_day = Counter(t.astimezone(config.zone).date() for t in taken)

    def full(when: datetime) -> bool:
        return cap is not None and per_day[when.astimezone(config.zone).date()] >= cap

    # Two campaigns on one account each keep their own grid, so their slots could land minutes apart; the
    # publisher then holds the second for an hour (MIN_GAP) and it shows as overdue. Keep every slot an hour
    # clear of the account's others instead.
    gap = timedelta(minutes=60)

    def near(when: datetime) -> bool:
        return any(abs(when - t) < gap for t in taken)

    fresh = [
        slot
        for slot in upcoming_slots(
            now,
            len(to_push) + len(held) + 8 + 5 * config.posting.posts_per_day,
            config.posting.start_hour,
            config.posting.end_hour,
            config.posting.posts_per_day,
            config.zone,
            offset_min=config.posting.slot_offset_min + account.slot_offset_min,
        )
        if slot not in taken
    ]

    pushed = 0
    for item in to_push:
        post = post_for(item, account.name)
        assert post is not None  # claimable_for only returns items with one

        due = item.scheduled_for + offset
        # A slot can need reassigning for two different reasons: it has aged
        # into the past, or — since this account's own natural due time is
        # computed independently per item — it happens to already match a
        # slot this same batch just handed to another item via the branch
        # below. Checking staleness alone missed the second case: a stale
        # item reslotted onto some fresh slot, and a separate item whose own
        # due was never stale could still land on that identical slot with
        # no check at all, and both went out on the same minute.
        # A hand-timed post keeps the time it was given, however full its day is.
        pinned = item.lineup_id is not None
        if due <= now + lead or due in taken or (not pinned and (full(due) or near(due))):
            while fresh and (full(fresh[0]) or near(fresh[0])):
                fresh.pop(0)
            if not fresh:
                log.warning("reslot_exhausted", item_id=item.id)
                break
            was, due = due, fresh.pop(0)
            log.info(
                "reslot_stale_record", item_id=item.id,
                was=was.isoformat(), now_at=due.isoformat(),
            )
        taken.add(due)
        per_day[due.astimezone(config.zone).date()] += 1
        post.scheduled_for = due

        # This account's own version if it has one; otherwise this network's
        # own copy if it has any, the shared bank otherwise.
        network = account.network.value
        variant = item.variants.get(account.name)
        text: str = (
            variant.caption if variant is not None and variant.caption
            else item.captions.get(network, item.caption)
        )
        title: str | None = (
            variant.title if variant is not None and variant.title
            else item.titles.get(network) or item.title
        )
        video_url = _postable_url(
            variant.video_url if variant is not None and variant.video_url
            else item.video_url,
            config,
        )

        # An item rendered for a network with no title field carries none,
        # and YouTube refuses a Short without one — so a missing title is
        # derived here rather than being baked in at render time, when the
        # destination was still a single channel.
        limits = limits_for(account.network)
        if title is None and limits.has_title:
            assert limits.title_max is not None
            title = derive_title(text, limits.title_max)

        transition_post(post, QueueStatus.CLAIMED, item.id, log=log)
        sync_status(item)
        save_queue(queue_path, queue)
        # The commit is the durable claim: a crash after this leaves the
        # record `claimed` in git, so the next run reconciles rather than
        # pushing this channel a second copy (SPEC §11).
        vcs.commit(
            [queue_path], f"claim {item.id[:8]} for {account.name}"
        )

        # Posting to Instagram directly, a Reel's sound can be given a name,
        # which is otherwise "Original audio" under the account's own. The
        # song is the creative's title, filled into the campaign's wording.
        audio_name: str | None = None
        if account.provider is Provider.INSTAGRAM and config.funnel.audio_name:
            song = next(
                (c.title for c in config.creatives if c.name == item.creative), ""
            ) or config.funnel.name
            if song or "{name}" not in config.funnel.audio_name:
                audio_name = (
                    config.funnel.audio_name.replace("{name}", song).strip() or None
                )
        # The song's own page: with its catalogue id attached the Reel is filed
        # under the song and credited to the band, instead of being one more
        # "Original audio" under the niche account. Only an account connected
        # through Facebook Login may attach one (accounts.yaml `login`); the
        # publisher posts the Reel with its named sound if Instagram refuses.
        audio = (
            _song_audio(config, item.creative)
            if account.provider is Provider.INSTAGRAM
            and account.login is InstagramLogin.FACEBOOK else None
        ) or {}

        try:
            request = PublishRequest(
                channel_id=channel,
                text=text,
                title=title,
                service=account.network,
                video_url=video_url,
                scheduled_for=due,
                audio_name=audio_name,
                audio_id=audio.get("audio_id"),
                audio_volume=audio.get("audio_volume"),
                video_volume=audio.get("video_volume"),
                first_comment=account.first_comment or item.first_comment or None,
                notify_subscribers=account.notify_subscribers,
                post_type=account.post_type,
                trial=account.trial_reels,
                trial_graduation=(
                    account.trial_graduation.value if account.trial_reels else None
                ),
                cover_at_ms=(
                    None if config.posting.cover_at_sec is None
                    else int(config.posting.cover_at_sec * 1000)
                ),
            )
            try:
                result = publisher.create_post(request)
            except InvalidPostError as exc:
                # Buffer's free plan refuses any post that carries a first
                # comment. The comment is a nicety; the post is the point —
                # send it without rather than lose the post.
                if not (request.first_comment and _first_comment_refused(exc)):
                    raise
                log.warning(
                    "first_comment_dropped", item_id=item.id,
                    account=account.name, reason=str(exc)[:160],
                )
                result = publisher.create_post(
                    request.model_copy(update={"first_comment": None})
                )
        except UgcError as exc:
            log.exception("push_failed", exc, item_id=item.id)
            mark_post_failed(post, str(exc), item.id, log=log)
            sync_status(item)
            save_queue(queue_path, queue)
            vcs.commit([queue_path], f"fail {item.id[:8]} for {account.name}")
            if isinstance(exc, (AuthError, QuotaError)):
                # Properties of the ACCOUNT, not of this item: a bad key or an
                # exhausted quota rejects everything behind it too. Stop this
                # account rather than marching its whole queue into `failed`.
                notifier.failure("topup.push", exc, item_id=item.id)
                raise
            notifier.failure("topup.push", exc, item_id=item.id)
            continue

        mark_post_pushed(post, result.post_id, item.id, log=log)
        sync_status(item)
        # History carries one Buffer id, and fan-out produces several. The
        # first success wins it, which keeps attribution joining exactly as it
        # did when this campaign had one channel; the per-account ids live on
        # the queue records. Keying metrics per account is its own step.
        backfill_post_id(
            history_path, item.id, result.post_id,
            account=account.name,
            primary=not any(
                p.buffer_post_id for p in item.posts
                if p.account != account.name
            ),
        )
        save_queue(queue_path, queue)
        vcs.commit(
            [queue_path, history_path, *_held_post_paths(publisher)],
            f"push {item.id[:8]} for {account.name}",
        )
        pushed += 1
    return pushed


def _reconcile_stranded_account(
    queue: Queue,
    account: AccountConfig,
    publisher: Publisher,
    channel: str,
    queue_path: Path,
    history_path: Path,
    log: StructuredLogger,
    vcs: Vcs,
) -> None:
    """Resolve records left ``claimed`` for one account (SPEC §11)."""
    for item in stranded_for(queue, account.name):
        post = post_for(item, account.name)
        assert post is not None
        log.warning("stranded_record_found", item_id=item.id)
        due = post.scheduled_for or item.scheduled_for
        existing = publisher.find_scheduled_post(channel, due)
        if existing is not None:
            # The previous run did reach Buffer. Record it rather than
            # pushing a duplicate that would then need deleting by hand.
            log.info(
                "stranded_record_already_published",
                item_id=item.id, post_id=existing.post_id,
            )
            mark_post_pushed(post, existing.post_id, item.id, log=log)
        else:
            log.info("stranded_record_released", item_id=item.id)
            transition_post(post, QueueStatus.PENDING, item.id, log=log)
        sync_status(item)
        save_queue(queue_path, queue)
        vcs.commit(
            [queue_path, history_path],
            f"reconcile {item.id[:8]} for {account.name}",
        )


def _topup(
    args: argparse.Namespace,
    env: dict[str, str],
    config: CampaignConfig,
    log: StructuredLogger,
    notifier: Notifier,
    clock: Clock,
) -> int:
    campaign_dir = _campaign_dir(config.slug)
    queue_path = campaign_dir / "queue.json"
    history_path = campaign_dir / "history.json"

    queue = load_queue(queue_path)
    publisher = _build_publisher(config, env, log)
    channel = (
        "dry-run-channel"
        if config.posting.dry_run
        else _channel_id(config, env)
    )
    vcs: Vcs = (
        NullVcs(log)
        if config.posting.dry_run or args.no_commit
        else GitVcs(REPO_ROOT, log)
    )

    # SPEC §11 — reconcile anything a previous run left mid-flight *before*
    # considering new work. Pushing first would risk duplicating exactly the
    # item we are unsure about.
    _reconcile_stranded(queue, publisher, channel, queue_path, history_path, log, vcs)

    # Items that failed with attempts left are eligible again. Without this a
    # transient failure parks a video forever, and a systemic one (a stale slot
    # rejected for every item) permanently drains a whole batch.
    revived = 0
    for item in queue.items:
        if item.status is QueueStatus.FAILED and item.attempts < QueueItem.MAX_ATTEMPTS:
            reset_for_retry(item, log=log)
            revived += 1
    if revived:
        log.info("revived_failed_items", count=revived, campaign=config.slug)
        save_queue(queue_path, queue)

    state = publisher.queue_state(channel)
    depth = state.depth
    need = depth_needed(depth, config.posting.max_buffer_queue)
    ready = claimable(queue)
    to_push = ready[:need]
    gap = state.gap_hours(clock.now())

    log.info(
        "topup_plan",
        buffer_depth=depth,
        cap=config.posting.max_buffer_queue,
        need=need,
        available=len(ready),
        pushing=len(to_push),
        next_due_in_hours=None if gap is None else round(gap, 1),
    )

    # A queue can be full by count and empty in time: the cap is satisfied,
    # nothing failed, every job reports success, and nothing publishes for
    # hours. No other alert covers it — they all fire on an error, and there
    # is no error here. Reported when the queue is genuinely full, because a
    # queue with room is about to be topped up anyway.
    limit = config.notify.max_schedule_gap_hours
    if gap is not None and gap > limit and not to_push:
        log.warning(
            "schedule_gap", campaign=config.slug,
            next_due_in_hours=round(gap, 1), limit=limit, depth=depth,
        )
        notifier.notify(
            NotifyEvent.SCHEDULE_GAP,
            f"{config.slug}: Buffer holds {depth} post(s) but the next one is "
            f"{gap:.0f}h away, over the {limit:.0f}h limit. The queue is full "
            f"by count and empty in time, so top-up will not add to it and "
            f"{len(ready)} rendered video(s) are waiting. Nothing has failed — "
            f"the slots are simply too far out.",
        )
    if not to_push:
        # SPEC §14 — queue already full: push nothing and exit clean.
        if not ready and depth == 0:
            notifier.notify(
                NotifyEvent.QUEUE_EMPTY,
                f"⚠️ {config.slug}: Buffer queue is empty and queue.json has no "
                f"pending items. Nothing will publish until the next render.",
            )
        save_queue(queue_path, queue)
        return 0

    # The slot chosen at render time may already have passed: a batch is laid
    # out at ~23:30 local covering the next 24 hours, but the top-up runs only
    # every four hours and can push at most `max_buffer_queue` at a time, so by
    # mid-morning the early slots are behind us. Buffer rejects any post dated
    # in the past, so the slot is reassigned at push time — it is a scheduling
    # detail, not part of the item's identity.
    _reslot_stale(to_push, queue, config, clock.now(), log)

    pushed = 0
    for item in to_push:
        video_url = _postable_url(item.video_url, config)
        transition(item, QueueStatus.CLAIMED, log=log)
        save_queue(queue_path, queue)
        # The commit is the durable claim. A crash after this point leaves the
        # item `claimed` in git, so the next run reconciles instead of
        # re-pushing (SPEC §11).
        vcs.commit([queue_path], f"claim {item.id[:8]} for {config.slug}")

        try:
            result = publisher.create_post(
                PublishRequest(
                    channel_id=channel,
                    text=item.caption,
                    title=item.title,
                    service=config.buffer.service,
                    video_url=video_url,
                    scheduled_for=item.scheduled_for,
                    first_comment=config.buffer.first_comment or None,
                    notify_subscribers=config.buffer.notify_subscribers,
                    post_type=config.buffer.post_type,
                )
            )
        except UgcError as exc:
            log.exception("push_failed", exc, item_id=item.id)
            mark_failed(item, str(exc), log=log)
            save_queue(queue_path, queue)
            vcs.commit([queue_path], f"fail {item.id[:8]} for {config.slug}")
            if isinstance(exc, (AuthError, QuotaError)):
                # These are properties of the ACCOUNT, not of this item: a bad
                # key or an exhausted quota will reject everything behind it
                # too. Stop rather than marching the whole queue into `failed`.
                notifier.failure("topup.push", exc, item_id=item.id)
                raise
            # Anything else — a malformed payload, a rejected schedule — is
            # specific to this item. Failing the batch on it would let one bad
            # post block every good one behind it, which is exactly what a
            # stale slot used to do.
            notifier.failure("topup.push", exc, item_id=item.id)
            continue

        mark_pushed(item, result.post_id, log=log)
        backfill_post_id(history_path, item.id, result.post_id)
        save_queue(queue_path, queue)
        vcs.commit(
            [queue_path, history_path], f"push {item.id[:8]} for {config.slug}"
        )
        pushed += 1

    _report_quota(publisher, notifier, config, log, clock, vcs)
    log.info("topup_complete", pushed=pushed)
    return 0


def _reslot_stale(
    items: list[QueueItem],
    queue: Queue,
    config: CampaignConfig,
    now: datetime,
    log: StructuredLogger,
) -> None:
    """Move items whose scheduled slot has passed onto the next free ones.

    Buffer rejects a post dated in the past outright, and that rejection is not
    retryable, so a stale slot is fatal to the item and — before this — to every
    item queued behind it.

    Slots already spoken for by pushed or claimed items are skipped so two posts
    never land on the same minute.
    """
    lead = timedelta(minutes=10)
    if not any(i.scheduled_for <= now + lead for i in items):
        return

    # Every OTHER item's slot is spoken for — not just the pushed ones. An
    # earlier version only excluded pushed/claimed slots, so a stale item could
    # be handed a time a still-pending item already held, and the two went out
    # on the same minute.
    moving = {id(i) for i in items if i.scheduled_for <= now + lead}
    taken = {
        i.scheduled_for for i in queue.items if id(i) not in moving
    }
    candidates = [
        slot
        for slot in upcoming_slots(
            now,
            len(items) + len(taken) + 8,
            config.posting.start_hour,
            config.posting.end_hour,
            config.posting.posts_per_day,
            config.zone,
            # Same grid as the render, or a re-slotted item lands between the
            # campaign's own slots and drifts out of the stagger.
            offset_min=config.posting.slot_offset_min,
        )
        if slot not in taken
    ]

    moved = 0
    for item in items:
        if item.scheduled_for > now + lead:
            continue
        if not candidates:
            log.warning("reslot_exhausted", item_id=item.id)
            break
        was = item.scheduled_for
        item.scheduled_for = candidates.pop(0)
        moved += 1
        log.info(
            "reslot_stale_item",
            item_id=item.id,
            was=was.isoformat(),
            now_at=item.scheduled_for.isoformat(),
        )
    if moved:
        log.info("reslot_complete", moved=moved, campaign=config.slug)


def _reconcile_stranded(
    queue: Queue,
    publisher: Publisher,
    channel: str,
    queue_path: Path,
    history_path: Path,
    log: StructuredLogger,
    vcs: Vcs,
) -> None:
    """Resolve items left ``claimed`` by a job that died mid-push (SPEC §11)."""
    for item in stranded(queue):
        log.warning("stranded_item_found", item_id=item.id)
        existing = publisher.find_scheduled_post(channel, item.scheduled_for)
        if existing is not None:
            # The previous run did reach Buffer. Record it rather than pushing
            # a duplicate that would then need deleting by hand.
            log.info(
                "stranded_item_already_published",
                item_id=item.id, post_id=existing.post_id,
            )
            mark_pushed(item, existing.post_id, log=log)
            backfill_post_id(history_path, item.id, existing.post_id)
        else:
            log.info("stranded_item_released", item_id=item.id)
            transition(item, QueueStatus.PENDING, log=log)
        save_queue(queue_path, queue)
        vcs.commit([queue_path, history_path], f"reconcile {item.id[:8]}")


def _report_quota(
    publisher: Publisher,
    notifier: Notifier,
    config: CampaignConfig,
    log: StructuredLogger,
    clock: Clock | None = None,
    vcs: Vcs | None = None,
) -> None:
    """Fold this run into the rolling tally and alert on the *30-day* total.

    Comparing one run against a 30-day threshold — which this used to do — made
    the alarm unreachable: a top-up run spends tens of requests and the
    threshold is 2,400. The tally has to persist across runs and add up every
    campaign sharing the key, because the allowance belongs to the Buffer
    account rather than to any one campaign.
    """
    _report_quota_count(
        getattr(publisher, "request_count", 0), notifier, config, log, clock, vcs
    )


def _report_quota_count(
    count: int,
    notifier: Notifier,
    config: CampaignConfig,
    log: StructuredLogger,
    clock: Clock | None = None,
    vcs: Vcs | None = None,
) -> None:
    """As ``_report_quota``, given a request count rather than a publisher.

    Fan-out spends its requests across one publisher per Buffer login, so the
    figure to record is their sum — asking any single one of them would
    undercount the run.
    """
    log.info("buffer_requests_this_run", count=count)

    today = (clock.now() if clock else SystemClock().now()).astimezone(
        config.zone
    ).date()
    ledger = quota_path(_campaign_dir(config.slug))
    record_run(ledger, today, count)
    # Runners are ephemeral: a ledger written and not committed is gone before
    # the next run reads it, and a rolling tally that resets every four hours
    # is not a tally. This was exactly the bug — the file was being written
    # faithfully and thrown away, so the counter sat at zero for ever.
    if vcs is not None and count > 0:
        vcs.commit([ledger], f"quota {config.slug}")

    slot = config.buffer.api_key_secret
    ledgers: list[QuotaLedger] = []
    for summary in list_campaigns(CAMPAIGNS_DIR):
        if not summary.valid:
            continue
        try:
            other = load_campaign(CAMPAIGNS_DIR, summary.slug)
        except UgcError:
            continue
        if other.buffer.api_key_secret != slot:
            continue
        ledgers.append(load_quota(quota_path(_campaign_dir(other.slug))))

    used = rolling_total(ledgers, today)
    log.info(
        "buffer_quota_rolling", slot=slot, used=used,
        allowance=MONTHLY_ALLOWANCE, campaigns=len(ledgers),
    )
    if used > BUFFER_QUOTA_ALERT_THRESHOLD:
        notifier.notify(
            NotifyEvent.QUOTA_HIGH,
            f"⚠️ {slot}: {used} of {MONTHLY_ALLOWANCE} Buffer requests used in "
            f"the last {WINDOW_DAYS} days, across {len(ledgers)} campaign(s) "
            f"sharing that key. "
            f"Posting stops when the allowance runs out.",
        )


# --------------------------------------------------------------- command: preflight


def cmd_preflight(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Validate everything without changing anything (SPEC §13 M8)."""
    log = get_logger(command="preflight", campaign=args.campaign)
    problems: list[str] = []
    clock: Clock = SystemClock()

    try:
        config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    except ConfigError as exc:
        log.exception("preflight_config_invalid", exc)
        print(f"FAIL config: {exc}", file=sys.stderr)
        return 1
    log.info("preflight_config_ok", slug=config.slug)

    if config.posting.paused:
        # A paused campaign renders and posts nothing, so there is no library
        # or secret to hold it to yet — only its config, which just loaded.
        print(f"OK {config.slug} is paused — config is valid, nothing else checked")
        return 0

    for name in (
        n for n in (
            config.buffer.api_key_secret,
            config.buffer.channel_id_secret,
            config.notify.webhook_secret,
        )
        if n
    ):
        if not _secret(name, env):
            problems.append(f"secret {name} is not set")

    try:
        descriptions = _load_captions(
            _campaign_dir(config.slug) / "captions.txt", config.buffer.service,
            config.buffer.title_strategy,
        )
        log.info("preflight_descriptions_ok", count=len(descriptions))
        _print_titles(config, descriptions)
    except ConfigError as exc:
        problems.append(str(exc))
        descriptions = []

    if env.get("GITHUB_REPOSITORY") and _secret("GITHUB_TOKEN", env):
        campaign_dir = _campaign_dir(config.slug)
        total_weight = sum(c.weight for c in config.creatives)
        fanout_targets = (
            accounts_for(load_accounts(REPO_ROOT / ACCOUNTS_FILE), config.accounts)
            if config.posting.fan_out
            else ()
        )
        for creative in config.creatives:
            prefix = f"{creative.name}: "
            try:
                store = _build_store(env, log, clock)
                paths = filter_library(
                    fetch_library(
                        store, REPO_ROOT / "work" / config.slug / "assets",
                        creative.name,
                        config.creative_assets_tag(creative),
                        config.creative_video_tag(creative),
                    ),
                    load_roster(roster_path(campaign_dir)),
                    log,
                )

                missing = [] if config.composition.music_cleared else check_music_licenses(
                    paths.music,
                    config.creative_licenses_path(campaign_dir, creative),
                    log,
                )
                if missing:
                    problems.append(
                        f"{prefix}music tracks with no LICENSES.md entry: "
                        + ", ".join(missing[:20])
                    )

                # Fan-out renders ONE file and sends it everywhere, so a music
                # bed is no longer a per-network choice. This campaign used to
                # keep music on Instagram and muted on the networks that
                # fingerprint it — the split that ended a TikTok outage
                # (CONTEXT §4). One file cannot do both, and the failure mode
                # is silent: everything publishes and the posts reach nobody.
                if (
                    config.posting.fan_out and paths.music
                    and not config.composition.music_cleared
                ):
                    networks = {a.network.value for a in fanout_targets}
                    at_risk = networks & {"tiktok", "youtube"}
                    if at_risk:
                        problems.append(
                            f"{prefix}fan_out is on and {len(paths.music)} music "
                            f"track(s) are still in rotation, but the same file "
                            f"goes to {', '.join(sorted(at_risk))}, which "
                            f"fingerprint audio. Either mute them "
                            f"(`ugc clips --off <track>`) or replace them with "
                            f"royalty-free tracks before going live. If the "
                            f"music is yours to post everywhere, say so with "
                            f"composition.music_cleared: true."
                        )

                # Probe music exactly as the render job does. Without
                # durations the library reports one bed per track and the
                # runway comes out ~12x short, failing a check the real
                # render would pass.
                renderer: Renderer = FfmpegRenderer(config, log)
                durations: dict[str, float] = {}
                if config.composition.music_random_start:
                    for track in paths.music:
                        try:
                            durations[track.name] = renderer.probe(track).duration_sec
                        except UgcError as exc:
                            log.warning(
                                "music_probe_failed", creative=creative.name,
                                track=track.name, error=str(exc),
                            )

                # Duration is decided by which clips get picked, and the
                # selector cannot know that — it never probes the video
                # parts. So the check happens here, where the files are
                # already downloaded, rather than at 05:00 when an
                # over-length cut fails validation after it has been
                # rendered.
                problems += [
                    prefix + p
                    for p in _duration_headroom(paths, config, renderer, log)
                ]
                for note in config_conflicts(
                    config.buffer.service,
                    config.video.max_duration_sec,
                    config.video.max_file_mb,
                ):
                    print(f"WARN {prefix}{note}", file=sys.stderr)

                creative_bank = _load_captions(
                    _creative_bank_path(config, creative, campaign_dir),
                    config.buffer.service, config.buffer.title_strategy,
                    _caption_names(config, creative),
                )
                unknown_cues = sorted(
                    set(creative.music_cues) - {p.name for p in paths.music}
                )
                if unknown_cues:
                    problems.append(
                        f"{prefix}music_cues names {unknown_cues}, which are "
                        f"not tracks in this creative's library"
                    )
                library = _library_from(
                    paths, creative_bank, config, durations, creative
                )
                library.validate()
                bodies_max = config.composition.bodies_per_video_max
                ceiling = library.ceiling(
                    config.composition.bodies_per_video, bodies_max
                )
                # Weighted, not flat: a creative that only wins a fraction of
                # slots exhausts its own pool proportionally slower than
                # posts_per_day alone would suggest (mirrors the render job's
                # own runway math).
                share = creative.weight / total_weight
                rate = max(config.posting.posts_per_day * share, 1e-9)
                runway = ceiling / rate
                log.info(
                    "preflight_library_ok",
                    creative=creative.name,
                    hooks=len(library.hooks), bodies=len(library.bodies),
                    music=len(library.music),
                    music_beds=library.total_music_options(),
                    captions=len(library.captions),
                    combinations=ceiling,
                    distinct_visuals=library.distinct_visuals(
                        config.composition.bodies_per_video, bodies_max
                    ),
                    runway_days=runway,
                )
                if runway < config.selection.min_runway_days:
                    problems.append(
                        f"{prefix}library yields only {runway:.0f} days of "
                        f"unique combos at ~{config.posting.posts_per_day * share:.1f}/day; "
                        f"selection.min_runway_days is "
                        f"{config.selection.min_runway_days}"
                    )
            except (UgcError, SelectionError) as exc:
                problems.append(f"{prefix}library: {exc}")
    else:
        log.warning("preflight_library_skipped", reason="no GitHub credentials")

    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"OK preflight passed for {config.slug}")
    return 0


# ------------------------------------------------------------------ command: ingest


def _visual_pools(config: CampaignConfig, resources: Mapping[str, Any]) -> dict[str, str]:
    """creative -> the clip pool (Release tag) its hooks come from, for creatives that share one.

    Only ``shared_videos`` creatives are listed: theirs is the one case where two
    songs' ``hook_05.mp4`` are the same picture, so a clip's cooldown has to be
    the pool's, not the song's (``Selector.select_batch_multi``)."""
    return {
        c.name: config.creative_video_tag(c)
        for c in config.creatives if c.shared_videos and c.name in resources
    }


def _clip_styles(config: CampaignConfig) -> dict[str, dict[str, str]]:
    """creative -> clip -> studio style, from the campaign's recipes.json (the studio job writes an entry as it
    ingests each video). Empty when there is no such file: a campaign that is not studio-made has no styles."""
    try:
        rec = json.loads((_campaign_dir(config.slug) / "recipes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, str]] = {}
    for entry in rec.get("nightly", []) if isinstance(rec, dict) else []:
        if entry.get("style") and entry.get("creative") and entry.get("clip"):
            out.setdefault(str(entry["creative"]), {})[str(entry["clip"])] = str(entry["style"])
    return out


def _style_boost(config: CampaignConfig) -> dict[str, dict[str, float]] | None:
    """creative -> clip -> factor, for clips whose studio style the campaign favours (selection.favour_styles)."""
    favour = config.selection.favour_styles
    if not favour:
        return None
    out: dict[str, dict[str, float]] = {}
    for name, clips in _clip_styles(config).items():
        for clip, style in clips.items():
            if favour.get(style):
                out.setdefault(name, {})[clip] = float(favour[style])
    return out or None


def _quota_picks(
    config: CampaignConfig,
    selector: Selector,
    pools: dict[str, tuple[AssetLibrary, History]],
    weights: Mapping[str, float],
    count: int,
    styles: Mapping[str, Mapping[str, str]],
    now: datetime,
    log: StructuredLogger,
    *,
    performance: Mapping[str, Mapping[str, Mapping[str, float]]] | None = None,
    visual_pools: Mapping[str, str] | None = None,
) -> tuple[list[tuple[str, Any]], dict[str, tuple[AssetLibrary, History]]]:
    """The style quota's share of tonight's picks (selection.style_quota), and the pools with those picks already
    written into their histories, so the ordinary selector that fills the remaining slots cannot pick them again.

    Styles are filled in the order the config lists them, each from the clips recipes.json says are that style
    across every song: the song's clips that have never posted first, then the rest of that style's clips. The
    selector does the picking either way, so song spread, cooldowns and dedupe hold inside the quota too. A style
    the libraries cannot fill is logged and its slots go to the ordinary selector.
    """
    picks: list[tuple[str, Any]] = []
    pools = dict(pools)
    bodies_per_video = config.composition.bodies_per_video
    bodies_max = config.composition.bodies_per_video_max
    for style, wanted in (config.selection.style_quota or {}).items():
        wanted = min(wanted, count - len(picks))
        if wanted <= 0:
            break
        got: list[tuple[str, Any]] = []
        for unused_only in (True, False):
            need = wanted - len(got)
            if need <= 0:
                break
            sub: dict[str, tuple[AssetLibrary, History]] = {}
            for name, (library, history) in pools.items():
                posted = {h for e in history.entries for h in entry_hooks(e)}
                hooks = tuple(
                    h for h in library.hooks
                    if styles.get(name, {}).get(h) == style and (not unused_only or h not in posted)
                )
                if hooks:
                    sub[name] = (replace(library, hooks=hooks), history)
            if not sub:
                continue
            batch = selector.select_batch_multi(
                sub, weights, need, bodies_per_video, bodies_max,
                performance=performance, visual_pools=visual_pools,
            )
            for name, outcome in batch:
                sel = outcome.selection
                library, history = pools[name]
                pools[name] = (library, History(entries=[
                    *history.entries,
                    HistoryEntry(
                        tuple_hash=tuple_hash(sel, config.selection.dedupe_on),
                        timestamp=now + timedelta(microseconds=len(picks) + len(got) + 1),
                        item_id="", hook=sel.hook, bodies=sel.bodies, music=sel.music,
                        music_offset_sec=sel.music_offset_sec, caption=sel.caption, creative=name,
                    ),
                ]))
            got += batch
        picks += got
        if len(got) < wanted:
            log.warning("style_quota_short", style=style, wanted=wanted, picked=len(got))
        else:
            log.info("style_quota_filled", style=style, picked=len(got))
    return picks, pools


def _performance_medians(
    config: CampaignConfig, history: History, log: StructuredLogger
) -> dict[str, dict[str, float]] | None:
    """Median views per option, for the selector to weight by.

    Returns None when weighting is off or there is nothing to weight with, so
    the selector's own code path stays untouched rather than being handed a
    map of ones.
    """
    if config.selection.performance_weight <= 0:
        return None

    cache_path = posts_path(_campaign_dir(config.slug))
    try:
        posts = load_posts(cache_path).posts
    except UgcError as exc:
        log.warning("performance_cache_unreadable", error=str(exc))
        return None
    if not posts:
        return None

    medians: dict[str, dict[str, float]] = {}
    statistic = config.selection.performance_statistic
    for report in attribute(history.entries, posts, statistic=statistic):
        if not report.rankable:
            continue
        medians[report.dimension] = {
            option.option: option.score for option in report.options
        }
    if not medians:
        return None

    log.info(
        "performance_weighting",
        weight=config.selection.performance_weight,
        statistic=statistic.value,
        dimensions={k: len(v) for k, v in medians.items()},
        posts=len(posts),
    )
    return medians


def _duration_headroom(
    paths: LocalLibrary,
    config: CampaignConfig,
    renderer: Renderer,
    log: StructuredLogger,
) -> list[str]:
    """Whether the longest possible cut still fits the platform.

    The worst case is the longest hook plus the longest N bodies. If that
    exceeds the ceiling, some combinations will fail validation after being
    rendered — wasted work, and a gap in the night's batch. If even the
    *shortest* possible cut exceeds it, nothing can render at all.

    Returned as problems only in that second case; the first is a warning,
    because a library where most combinations fit is still usable.
    """
    def durations(items: tuple[Path, ...]) -> list[float]:
        out: list[float] = []
        for path in items:
            try:
                out.append(renderer.probe(path).duration_sec)
            except UgcError as exc:
                log.warning("probe_failed", clip=path.name, error=str(exc))
        return out

    hooks = durations(paths.hooks)
    bodies = durations(paths.bodies)
    composition = config.composition
    if not hooks or (not bodies and composition.bodies_per_video > 0):
        return []

    most = min(
        composition.bodies_per_video_max or composition.bodies_per_video,
        len(bodies),
    )
    fewest = composition.bodies_per_video
    longest = max(hooks) + sum(sorted(bodies, reverse=True)[:most])
    shortest = min(hooks) + sum(sorted(bodies)[:fewest])

    _, ceiling, _ = effective_video_limits(
        config.buffer.service, config.video.min_duration_sec,
        config.video.max_duration_sec, config.video.max_file_mb,
    )
    log.info(
        "duration_headroom", shortest=round(shortest, 1),
        longest=round(longest, 1), ceiling=ceiling,
        service=config.buffer.service.value,
    )

    floor, _, _ = effective_video_limits(
        config.buffer.service, config.video.min_duration_sec,
        config.video.max_duration_sec, config.video.max_file_mb,
    )
    if longest < floor:
        return [
            f"even the longest possible cut is {longest:.1f}s, under the "
            f"{floor:.0f}s floor — no combination can render. Use longer "
            f"clips or raise composition.bodies_per_video."
        ]
    if shortest < floor:
        print(
            f"WARN shortest possible cut is {shortest:.1f}s against a "
            f"{floor:.0f}s floor; clips that short will fail when picked.",
            file=sys.stderr,
        )
    if shortest > ceiling:
        return [
            f"even the shortest possible cut is {shortest:.0f}s, over the "
            f"{ceiling:.0f}s ceiling for {config.buffer.service.value} — no "
            f"combination can render"
        ]
    if longest > ceiling:
        print(
            f"WARN longest possible cut is {longest:.0f}s against a "
            f"{ceiling:.0f}s ceiling for {config.buffer.service.value}; "
            f"some combinations will fail. Lower "
            f"composition.bodies_per_video_max or trim the longer clips.",
            file=sys.stderr,
        )
    return []


def cmd_ingest(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Upload dropped files to a creative's assets Release under correct names."""
    clock: Clock = SystemClock()
    log = get_logger(command="ingest", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    creative = _resolve_creative(config, getattr(args, "creative", None))

    inbox = REPO_ROOT / INBOX_ROOT / config.creative_library_key(creative)
    ensure_inbox(inbox)

    try:
        store = _build_store(env, log, clock)
    except UgcError as exc:
        print(f"{exc}", file=sys.stderr)
        print(
            "\nSet GITHUB_REPOSITORY=owner/name and GITHUB_TOKEN, or run "
            "`gh auth token` to get one.",
            file=sys.stderr,
        )
        return 1

    tag = config.creative_assets_tag(creative)
    video_tag = config.creative_video_tag(creative)
    renderer: Renderer = FfmpegRenderer(config, log)

    # A song that shares the campaign's videos has two destinations: videos
    # dropped for it join the pool every song cuts from, its track goes to
    # its own Release. Each has its own drop folder.
    jobs: list[tuple[Path, str, tuple[PartKind, ...], str]] = []
    if video_tag != tag:
        pool_inbox = REPO_ROOT / INBOX_ROOT / config.library_key
        ensure_inbox(pool_inbox)
        jobs.append((pool_inbox, video_tag, (PartKind.HOOK, PartKind.BODY), ""))
        jobs.append((inbox, tag, (PartKind.MUSIC,), creative.name))
    else:
        jobs.append((inbox, tag, tuple(PartKind), ""))

    print(f"\ncreative: {creative.name}")
    plans = []
    for folder, dest, kinds, label in jobs:
        plan = build_plan(
            folder, store.list_assets(dest), renderer, log,
            kinds=kinds, music_label=label,
        )
        print(f"inbox: {folder}  →  {dest}")
        print(plan.render_table())
        plans.append((plan, folder, dest))

    rejected = sum(len(plan.rejected) for plan, _, _ in plans)
    if rejected:
        print(f"\n{rejected} file(s) will be skipped — see notes above.")
    if not any(plan.uploadable for plan, _, _ in plans):
        print("\nNothing to upload.")
        if not args.dry_run:
            _write_ingest_report(args, plans)
        return 1 if rejected else 0

    if args.dry_run:
        print(f"\nDry run — nothing uploaded. Drop --dry-run to upload.")
        return 0

    for plan, folder, dest in plans:
        uploaded = apply_plan(
            plan, folder, store, dest, log,
            staging=REPO_ROOT / "work" / config.slug / "staging" / creative.name,
        )
        if uploaded:
            print(f"\nUploaded {len(uploaded)} file(s) to release {dest}.")

    _write_ingest_report(args, plans)
    _print_library_health(config, creative, store, tag, log)
    return 1 if rejected else 0


def _write_ingest_report(
    args: argparse.Namespace, plans: list[tuple[IngestPlan, Path, str]]
) -> None:
    """Record what happened to every dropped file, for whoever dropped it.

    The hosted dashboard has no terminal to read: without this, a refused file
    simply never appears and nobody is told why. Written only once the
    uploads have succeeded, so its absence means "nothing was settled, leave
    the files where they are".
    """
    path = getattr(args, "report", None)
    if not path:
        return
    rows = [
        {
            "inbox": folder.name,
            "asset": f"{c.kind.value}__{c.source.name}",
            "verdict": c.verdict.value,
            "target": c.target_name,
            "notes": c.notes,
        }
        for plan, folder, _ in plans
        for c in plan.candidates
    ]
    Path(path).write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def _print_library_health(
    config: CampaignConfig,
    creative: CreativeConfig,
    store: MediaStore,
    tag: str,
    log: StructuredLogger,
) -> None:
    """Tell the human, while they are still holding the files, if it is enough.

    The same shortfall would otherwise surface as a dedupe-relaxation alert at
    5 a.m., long after the moment when adding another clip was easy.
    """
    names = store.list_assets(tag)
    video_tag = config.creative_video_tag(creative)
    videos = names if video_tag == tag else store.list_assets(video_tag)
    hooks = len([n for n in videos if n.lower().startswith("hook")])
    bodies = len([n for n in videos if n.lower().startswith("body")])
    music = len([n for n in names if n.lower().startswith("music")])
    try:
        captions = len(_load_captions(
            _creative_bank_path(config, creative, _campaign_dir(config.slug)),
            config.buffer.service,
            config.buffer.title_strategy,
        ))
    except ConfigError:
        captions = 0

    per_video = config.composition.bodies_per_video
    total = combinations(hooks, bodies, music, captions, per_video)
    # Weighted, not flat: this creative only wins its own share of slots.
    total_weight = sum(c.weight for c in config.creatives)
    rate = max(config.posting.posts_per_day * (creative.weight / total_weight), 1e-9)
    runway = total / rate

    print(
        f"\nlibrary ({creative.name}): {hooks} hooks · {bodies} bodies · "
        f"{music} music · {captions} captions"
    )
    print(
        f"         {total} combinations = {runway:.0f} days at "
        f"~{rate:.1f}/day "
        f"(target {config.selection.min_runway_days})"
    )

    warnings = library_health(
        hooks, bodies, music, captions, per_video,
        config.posting.posts_per_day,
        config.selection.hook_cooldown_days,
        config.selection.caption_cooldown_days,
    )
    if runway < config.selection.min_runway_days:
        warnings.insert(
            0,
            f"runway is {runway:.0f} days, under the configured "
            f"{config.selection.min_runway_days}. Preflight will fail.",
        )
    for warning in warnings:
        print(f"\n  ! {warning}")
    if not warnings:
        print("\n  ✓ library supports the configured cadence with no relaxation")


def _print_titles(config: CampaignConfig, descriptions: list[Description]) -> None:
    """Show the title each description will post under.

    Only meaningful where the platform has a separate title field. Derived
    titles are printed rather than silently used: a title generated from a
    description is a guess, and the whole point is that the guess is visible
    before it goes live.
    """
    from src.platforms import limits_for

    limits = limits_for(config.buffer.service)
    if not limits.has_title:
        return

    explicit = {d.body for d in descriptions if d.title}
    print(f"\n{config.buffer.service.value} titles "
          f"(strategy: {config.buffer.title_strategy.value}, "
          f"max {limits.title_max}):")
    for index, description in enumerate(descriptions, 1):
        source = "given " if description.body in explicit else "derived"
        title = description.title or ""
        print(f"  {index:>2}. [{source}] {title}")
        if len(title) > limits.visible_chars:
            print(f"      ^ {len(title)} chars; only ~{limits.visible_chars} "
                  f"display on Shorts")


# --------------------------------------------------------------- command: diagnose


def cmd_diagnose(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Show what Buffer actually did with recent posts.

    Answers the question "it is in the queue but nothing published" by printing
    each post's status and, crucially, the ``error`` Buffer received back from
    the network.
    """
    log = get_logger(command="diagnose", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    clock: Clock = SystemClock()

    # Every account the campaign posts to, each through its own login. Under
    # fan-out the campaign's own channel is one of several, and the one that
    # has quietly stopped publishing is rarely the one anybody looks at.
    sources: list[tuple[str, str, str | None, str, str]] = []
    if config.posting.fan_out:
        registry = load_accounts(REPO_ROOT / ACCOUNTS_FILE)
        for account in accounts_for(registry, config.accounts):
            sources.append((
                account.name, account.api_key_secret, account.organization_id,
                _account_channel(account, env), account.network.value,
            ))
    else:
        sources.append((
            config.slug, config.buffer.api_key_secret,
            config.buffer.organization_id, _channel_id(config, env),
            config.buffer.service.value,
        ))

    publishers: dict[str, BufferPublisher] = {}
    spent = 0
    exit_code = 0
    for name, slot, org, channel, network in sources:
        api_key = _secret(slot, env)
        if not api_key:
            print(f"\n  {name}: {slot} is not set", file=sys.stderr)
            exit_code = 1
            continue
        if slot not in publishers:
            publishers[slot] = BufferPublisher(api_key, log, organization_id=org)
        try:
            posts = publishers[slot].diagnose_posts(channel, limit=args.limit)
        except UgcError as exc:
            print(f"\n  {name}: Buffer refused — {exc}", file=sys.stderr)
            exit_code = 1
            continue
        _print_diagnosis(name, network, posts)
    spent = sum(p.request_count for p in publishers.values())
    # Diagnose is run by hand and rarely, but its requests come out of the same
    # allowance; a tally that only counts scheduled jobs drifts low over time.
    record_run(
        quota_path(_campaign_dir(config.slug)),
        clock.now().astimezone(config.zone).date(),
        spent,
    )
    return exit_code


def _print_diagnosis(name: str, network: str, posts: list[dict[str, Any]]) -> None:
    """One channel's recent posts, with whatever the network said back."""
    print(f"\n  {name} · {network} · {len(posts)} posts\n")
    if not posts:
        print("  Buffer has no posts for this channel at all.")
        return

    counts: dict[str, int] = {}
    for post in posts:
        status = str(post.get("status"))
        counts[status] = counts.get(status, 0) + 1

    for post in sorted(posts, key=lambda p: str(p.get("dueAt") or "")):
        due = str(post.get("dueAt") or "")[:16].replace("T", " ")
        sent = str(post.get("sentAt") or "")[:16].replace("T", " ")
        print(f"  {due}  {str(post.get('status')):<10} "
              f"sent={sent or '-':<16} {post.get('schedulingType')}")
        err = post.get("error") or {}
        if err.get("message"):
            print(f"      ERROR: {err['message']}")
            if err.get("supportUrl"):
                print(f"      help:  {err['supportUrl']}")
        if post.get("externalLink"):
            print(f"      live:  {post['externalLink']}")

    print(f"\n  totals: {counts}")
    if counts.get("error"):
        print("\n  Posts in `error` carry the network's own refusal above.")
    if counts.get("scheduled") and not counts.get("sent"):
        print("\n  Nothing has published yet. If a due time has passed with no")
        print("  error, Buffer has accepted the post but not dispatched it —")
        print("  usually the channel needs reconnecting in Buffer.")


# ----------------------------------------------------------------- command: metrics


def cmd_metrics(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Fetch performance metrics and append today's snapshot to the cache.

    Deliberately a scheduled job rather than something the dashboard calls:
    Buffer's 3,000-request budget is nearly spent on posting, so metrics are
    fetched once a day and read from disk thereafter.
    """
    clock: Clock = SystemClock()
    log = get_logger(command="metrics", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    notifier = notifier_for(config, log, env)

    try:
        if config.posting.dry_run:
            log.info("metrics_skipped_dry_run", campaign=config.slug)
            print(f"{config.slug} is in dry run — no metrics to fetch")
            return 0

        # The accounts this campaign reaches. A campaign whose every account
        # posts to Instagram directly has nothing on Buffer to total: asking
        # Buffer for its campaign channel's windows only spent the Buffer
        # budget the one Buffer account (Loose Change) posts with. Its numbers
        # are the per-post figures below, straight from Instagram.
        reached = (
            list(accounts_for(load_accounts(REPO_ROOT / ACCOUNTS_FILE), config.accounts))
            if config.posting.fan_out else []
        )
        direct = bool(reached) and all(
            a.provider is Provider.INSTAGRAM for a in reached
        )
        instagram_only = bool(getattr(args, "instagram_only", False))
        if instagram_only and not any(
            a.provider is Provider.INSTAGRAM for a in reached
        ):
            print(f"{config.slug} posts to no Instagram account directly — nothing to fetch")
            return 0
        windows_wanted = not instagram_only and not direct

        now = clock.now()
        local_date = now.astimezone(config.zone).strftime("%Y-%m-%d")
        path = _campaign_dir(config.slug) / "metrics.json"
        history = load_metrics(path)
        publishers: dict[str, BufferPublisher | InstagramPublisher] = {}
        snapshots: list[Snapshot] = []
        lifetime_refused: tuple[datetime, datetime] | None = None
        channel = ""
        if windows_wanted:
            api_key = _secret(config.buffer.api_key_secret, env)
            if not api_key:
                raise ConfigError(f"{config.buffer.api_key_secret} is not set")
            publisher = BufferPublisher(
                api_key, log, organization_id=config.buffer.organization_id
            )
            publishers[config.buffer.api_key_secret] = publisher
            channel = _channel_id(config, env)
        else:
            log.info(
                "metrics_windows_skipped", campaign=config.slug,
                reason="instagram_only" if instagram_only else "all_accounts_post_directly",
            )

        # The first post ever recorded bounds the lifetime window. history.json
        # is append-only and never pruned, so it is the authoritative record of
        # when this campaign started — and reading it costs no API calls.
        posted = load_history(_campaign_dir(config.slug) / "history.json")
        first_post = min((e.timestamp for e in posted.entries), default=None)

        # Two windows, two requests. Rolling answers "how are we doing lately";
        # lifetime answers "what has this produced in total". Lifetime cannot be
        # summed from the rolling series — consecutive 30-day windows overlap by
        # 29 days, so adding them would count almost everything twice.
        windows = [
            (Scope.ROLLING, *default_window(now, args.days)),
            (Scope.LIFETIME, *lifetime_window(now, first_post)),
        ] if windows_wanted else []

        for scope, start, end in windows:
            try:
                rows, updated_at = publisher.fetch_metrics(channel, start, end)
            except UgcError as exc:
                if scope is not Scope.LIFETIME:
                    raise
                # Buffer's free plan answers only the last 31 days. Once a
                # campaign is older than that the lifetime window is refused
                # outright — and letting that refusal fail the run is what
                # silently froze every per-post figure for weeks, because
                # they are fetched below. The rolling window and the per-post
                # cache are what everything downstream actually reads.
                log.warning("lifetime_metrics_unavailable", error=str(exc)[:200])
                lifetime_refused = (start, end)
                continue
            taken = Snapshot(
                date=local_date,
                scope=scope,
                fetched_at=now,
                window_start=start,
                window_end=end,
                service=config.buffer.service.value,
                metrics=[
                    Metric(type=r.type, name=r.name, value=r.value, unit=r.unit)
                    for r in rows
                ],
                metrics_updated_at=updated_at,
            )
            history.upsert(taken)
            snapshots.append(taken)
        if snapshots:
            save_metrics(path, history)
        snapshot: Snapshot | None = snapshots[0] if snapshots else None  # rolling is first and never skipped

        # Per-post figures, in the same breath. `metrics` rides along inside
        # the posts query and takes no arguments, so this costs a handful of
        # paginated requests rather than one per post — which is what makes
        # attribution affordable at all.
        # Under fan-out the campaign's own channel is one account of several,
        # and reading only it leaves every other account unmeasured — so each
        # account the campaign reaches is fetched, through its own login, and
        # every figure is filed under the account it came from.
        sources: list[
            tuple[str | None, BufferPublisher | InstagramPublisher, str]
        ] = [(None, publishers[config.buffer.api_key_secret], channel)] if windows_wanted else []
        if config.posting.fan_out:
            sources = []
            for account in reached:
                if instagram_only and account.provider is not Provider.INSTAGRAM:
                    continue        # Buffer accounts are read once a day, in the full run
                slot = account.api_key_secret
                if slot not in publishers:
                    key = _secret(slot, env)
                    if not key:
                        log.warning(
                            "metrics_account_skipped", account=account.name,
                            reason=f"{slot} is not set",
                        )
                        continue
                    publishers[slot] = _real_publisher(account, key, log)
                sources.append(
                    (account.name, publishers[slot], _account_channel(account, env))
                )

        # Accounts whose every post came back without numbers because the
        # token may not read them. Logged, printed as a job error and the
        # command exits 1 for this campaign, so the job goes red: the matrix
        # runs fail-fast: false, so the other campaigns still get their turn.
        denied_accounts: list[str] = []
        try:
            fresh: list[Any] = []
            for account_name, source, source_channel in sources:
                try:
                    rows_ = source.fetch_post_metrics(source_channel)
                except UgcError as exc:
                    # One login failing must not cost the others their day.
                    log.warning(
                        "post_metrics_account_failed",
                        account=account_name, error=str(exc)[:200],
                    )
                    continue
                denied = getattr(source, "insights_denied", {}).get(source_channel)
                if denied:
                    log.warning(
                        "insights_denied", account=account_name, campaign=config.slug, **denied,
                    )
                    print(
                        f"::error::{config.slug}: no insights permission on {account_name} "
                        f"({denied['posts']} published posts, {denied['error_class']}, Graph code "
                        f"{denied['graph_code']}). The token in its slot lacks "
                        f"instagram_business_manage_insights / instagram_manage_insights, or the Page "
                        f"role lacks Insights: see docs/brain/traps.md and scripts/ig_check.py."
                    )
                    denied_accounts.append(str(account_name))
                # Stamped with when they were read, so the dashboard can say how
                # old a post's numbers are.
                fresh += [
                    r.model_copy(update=(
                        {"account": account_name, "fetched_at": now}
                        if account_name else {"fetched_at": now}
                    ))
                    for r in rows_
                ]
            cache_path = posts_path(_campaign_dir(config.slug))
            cache = load_posts(cache_path).merged_with(fresh)
            save_posts(cache_path, cache)
            log.info(
                "post_metrics_cached",
                fetched=len(fresh), total=len(cache.posts), campaign=config.slug,
                accounts=len(sources),
            )
            # An account can stop publishing with nothing failing: Buffer
            # accepts every post, the queue says "pushed", and the network
            # refuses each one afterwards. Only the absence shows — so an
            # account whose newest published post is days behind its
            # siblings' is reported.
            if len(sources) > 1:
                newest: dict[str, datetime] = {}
                for cached_post in cache.posts.values():
                    if cached_post.account and cached_post.sent_at:
                        seen = newest.get(cached_post.account)
                        if seen is None or cached_post.sent_at > seen:
                            newest[cached_post.account] = cached_post.sent_at
                if newest:
                    front = max(newest.values())
                    silent = sorted(
                        name for name, _, _ in sources
                        if name and (
                            name not in newest
                            or front - newest[name] > timedelta(days=3)
                        )
                    )
                    if silent:
                        log.warning("accounts_silent", accounts=silent)
                        notifier.notify(
                            NotifyEvent.FAILURE,
                            f"⚠️ {config.slug}: nothing has published on "
                            + ", ".join(
                                f"{n} since {newest[n]:%d %b}" if n in newest
                                else f"{n} (ever)" for n in silent
                            )
                            + ", while the other accounts are posting. Buffer "
                            "is accepting the posts and the network is "
                            "refusing them — run `ugc diagnose` for its "
                            "reason; usually the channel needs reconnecting "
                            "in Buffer.",
                        )
            if lifetime_refused is not None:
                # Buffer will not total the campaign's whole life, but the
                # per-post cache holds every post ever fetched and is never
                # pruned — so the all-time figures are summed from it. Only
                # the campaign's own channel is counted, which is what the
                # lifetime snapshots before this have always described.
                primary = next(
                    (name for name, _, ch in sources if ch == channel), None
                )
                totals: dict[str, float] = {}
                names: dict[str, str] = {}
                counted = 0
                for cached_post in cache.posts.values():
                    if cached_post.account not in (None, primary):
                        continue
                    counted += 1
                    for row in cached_post.metrics:
                        if row.unit != "count":
                            continue
                        totals[row.type] = totals.get(row.type, 0.0) + row.value
                        names[row.type] = row.name
                history.upsert(Snapshot(
                    date=local_date,
                    scope=Scope.LIFETIME,
                    fetched_at=now,
                    window_start=lifetime_refused[0],
                    window_end=lifetime_refused[1],
                    service=config.buffer.service.value,
                    metrics=[
                        Metric(type="postCount", name="Posts", value=float(counted), unit="count"),
                        *(
                            Metric(type=t, name=names[t], value=v, unit="count")
                            for t, v in sorted(totals.items())
                        ),
                    ],
                    metrics_updated_at=None,
                ))
                save_metrics(path, history)
            # The one failure nothing else reports. A render that succeeds
            # and a push that succeeds still leave the posts reaching nobody,
            # and every other alert here fires on an error that did not
            # happen. Checked here because this is where fresh per-post
            # figures land, and it costs no extra request.
            alert = distribution_lost(
                posted.entries, cache.posts, clock.now().date(),
                threshold=config.notify.distribution_dead_share,
                days=config.notify.distribution_days,
            )
            if alert is not None:
                log.warning(
                    "distribution_lost", campaign=config.slug,
                    since=alert.since.isoformat(),
                    worst_dead_share=round(alert.worst, 3),
                )
                notifier.notify(
                    NotifyEvent.DISTRIBUTION_LOST, alert.message(config.slug)
                )
        except UgcError as exc:
            # Never fail the metrics run over attribution: the window snapshot
            # above is what preflight and the digest depend on.
            log.warning("post_metrics_failed", error=str(exc))

        # Metrics runs daily per campaign and spends two requests each time.
        # Leaving it out understated the tally by ~90/month — the same silent
        # inaccuracy the rolling counter was added to remove. Only Buffer's
        # requests: Instagram's are not on Buffer's budget.
        buffer_requests = sum(
            p.request_count for p in publishers.values() if isinstance(p, BufferPublisher)
        )
        if buffer_requests or windows_wanted:
            _report_quota_count(buffer_requests, notifier, config, log, clock)
        if snapshot is None:
            log.info("metrics_saved", campaign=config.slug, date=local_date,
                     posts_only=True, accounts=len(sources))
            print(f"\n  {config.slug} · per-post figures from {len(sources)} "
                  f"Instagram account(s) · {local_date}")
            return 1 if denied_accounts else 0
        log.info(
            "metrics_saved", campaign=config.slug, date=local_date,
            metrics=len(snapshot.metrics), snapshots=len(history.snapshots),
        )
        lifetime = history.lifetime()
        print(f"\n  {config.slug} · {config.buffer.service.value} · {local_date}")
        if lifetime:
            print(f"  all time ({lifetime.window_start:%d %b} onwards): "
                  f"{lifetime.post_count} posts")
            for metric in lifetime.metrics:
                if metric.type == "postCount" or metric.unit == "percentage":
                    continue
                print(f"    {metric.name:<22} {metric.value:>10,.0f}")
            print(f"\n  last {args.days} days:")
        if not snapshot.metrics:
            print("  no metrics yet — networks report on a lag after publishing")
        for metric in snapshot.metrics:
            suffix = "%" if metric.unit == "percentage" else ""
            print(f"    {metric.name:<22} {metric.value:>10,.1f}{suffix}")
        return 1 if denied_accounts else 0
    except UgcError as exc:
        log.exception("metrics_failed", exc)
        notifier.failure("metrics", exc, campaign=config.slug)
        return 1


# ------------------------------------------------------------------- command: setup


def cmd_setup(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Report exactly what is wired up and what still needs doing."""
    from src import doctor
    from src.vcs import detect_repo, detect_token, list_secret_names

    clock: Clock = SystemClock()
    log = get_logger(command="setup", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    report = doctor.Report()

    report.add("config", doctor.Status.OK,
               f"{config.slug} · {config.buffer.service.value} · "
               f"{config.buffer.post_type.value} · {config.posting.posts_per_day}/day")

    repo = env.get("GITHUB_REPOSITORY") or detect_repo(REPO_ROOT)
    report.checks.append(doctor.check_repo(repo))

    names = list_secret_names(repo) if repo else None
    report.checks.extend(doctor.check_secrets(config, repo, names))

    # Buffer channel — only checkable with a key in this shell.
    channels = None
    api_key = _secret(config.buffer.api_key_secret, env) or env.get("BUFFER_API_KEY")
    if api_key:
        try:
            channels = _buffer_channels(
                api_key, log, config.buffer.organization_id
            )
        except UgcError as exc:
            log.exception("setup_buffer_check_failed", exc)
    report.checks.append(doctor.check_buffer_channel(config, channels))
    skipped = doctor.check_local_buffer_key(config)
    if skipped and channels is None:
        report.checks.append(skipped)

    # Assets and descriptions.
    counts = None
    token = env.get("GITHUB_TOKEN") or detect_token()
    if repo and token:
        try:
            store = GitHubReleasesStore(repo, token, log, clock)
            asset_names = store.list_assets(_assets_tag(config))
            # Muted clips are excluded, so this readiness report describes the
            # library the render will actually have rather than the one on the
            # Release. Counting both would make a half-muted library look fine.
            roster = load_roster(roster_path(_campaign_dir(config.slug)))
            live = [n for n in asset_names if roster.is_enabled(n)]
            counts = {
                kind: len([n for n in live if n.lower().startswith(kind)])
                for kind in ("hook", "body", "music")
            }
            held = len(asset_names) - len(live)
            if held:
                print(f"note: {held} clip(s) switched off in the randomizer "
                      f"(see `ugc clips --campaign {config.slug}`)")
        except UgcError as exc:
            log.exception("setup_assets_check_failed", exc)

    report.checks.extend(doctor.check_assets(counts, config))
    bank_path = _campaign_dir(config.slug) / "captions.txt"
    report.checks.extend(doctor.check_descriptions(bank_path, config))

    description_count = 0
    if bank_path.is_file():
        try:
            from src.descriptions import parse_bank

            description_count = len(parse_bank(bank_path.read_text(encoding="utf-8")))
        except UgcError:
            description_count = 0
    report.checks.extend(doctor.check_library(counts, description_count, config))
    report.checks.append(doctor.check_mode(config))

    print(f"\n  ugc-factory readiness · {config.slug}\n")
    print(report.render())
    print(report.next_steps())
    if report.ready:
        print("\n  Ready. Dry run:")
        print(f"    gh workflow run render.yml -f campaign={config.slug} "
              f"-f dry_run=true\n")
        return 0
    print(f"\n  {len(report.blocking)} blocking item(s).\n")
    return 1


def _buffer_channels(
    api_key: str, log: StructuredLogger, organization_id: str | None = None
) -> list[dict[str, Any]]:
    """Fetch channels with the metadata the reminder check needs."""
    publisher = BufferPublisher(api_key, log, organization_id=organization_id)
    query = """
    query UgcFactorySetupChannels($input: ChannelsInput!) {
      channels(input: $input) {
        id name service
        metadata {
          __typename
          ... on InstagramMetadata { defaultToReminders }
          ... on TiktokMetadata { defaultToReminders }
          ... on YoutubeMetadata { defaultToReminders }
        }
      }
    }
    """
    data = publisher._gql(query, {"input": {"organizationId": publisher._org_id()}})
    channels: list[dict[str, Any]] = data.get("channels") or []
    return channels


# ------------------------------------------------------------------ command: connect


def cmd_connect(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Connect a Buffer login: store its key, find its channels, register them.

    With no ``--slot`` this only reports — which logins have a key on this
    machine, and which accounts each one carries — and changes nothing.

    With one, it does the whole job a new login needs: takes the key (from the
    environment, or by asking — typed input is hidden and never echoed),
    saves it to ``.env`` and to the repo's GitHub secrets, asks Buffer which
    channels that key can see, and appends an entry per channel to
    ``accounts.yaml``. Channels already registered are left alone, so running
    it again after connecting one more network to the same login is safe.
    """
    import getpass

    from src import keys as keystore
    from src.config import BUFFER_KEY_SLOTS
    from src.connect import plan_accounts, safe_prefix, slot_name

    log = get_logger(command="connect")
    registry_path = REPO_ROOT / ACCOUNTS_FILE
    registry = load_accounts(registry_path)

    if args.slot is None:
        print("Buffer logins (key slots):\n")
        for slot in BUFFER_KEY_SLOTS:
            accounts = [a for a in registry.accounts if a.api_key_secret == slot]
            has_key = bool(_secret(slot, env))
            if not accounts and not has_key:
                continue
            print(f"  {slot:<18} key {'on this machine' if has_key else 'NOT on this machine'}")
            for account in accounts:
                state = "" if account.enabled else "  (disabled)"
                print(f"      {account.name:<26} {account.network.value}{state}")
        free = next(
            (i for i, slot in enumerate(BUFFER_KEY_SLOTS, 1)
             if not any(a.api_key_secret == slot for a in registry.accounts)),
            None,
        )
        if free:
            print(f"\nNext free slot: {free}.  ./ugc connect --slot {free} --name <login_name>")
        return 0

    if not 1 <= args.slot <= len(BUFFER_KEY_SLOTS):
        raise ConfigError(f"--slot must be 1 to {len(BUFFER_KEY_SLOTS)}")
    slot = slot_name(args.slot)

    api_key = _secret(slot, env)
    fresh_key = False
    if not api_key:
        if not sys.stdin.isatty():
            raise ConfigError(
                f"{slot} is not set and there is no terminal to ask on. "
                f"Export it, or run this in a terminal."
            )
        api_key = keystore.clean_value(
            getpass.getpass(f"Paste the Buffer API key for slot {args.slot} (hidden): ")
        )
        fresh_key = True

    publisher = BufferPublisher(api_key, log)
    organization_id = publisher._org_id()
    channels = _buffer_channels(api_key, log, organization_id)
    if not channels:
        print("That key works, but its Buffer login has no channels connected.")
        return 1

    prefix = safe_prefix(args.name or str(channels[0].get("name") or ""))
    plan = plan_accounts(channels, organization_id, slot, prefix, registry)

    for channel_name, existing_name in plan.already:
        print(f"  already registered   {channel_name} -> {existing_name}")
    for channel_name, service in plan.unsupported:
        print(f"  skipped              {channel_name} ({service} is not posted to)")
    for added in plan.new:
        print(f"  new                  {added.name:<26} {added.network.value} · {added.channel_name}")
        if added.reminders:
            print(
                f"    ! Buffer has {added.channel_name} set to reminders: nothing "
                f"posts unattended until 'publish automatically' is on for it."
            )

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    if fresh_key:
        keystore.write_env_value(REPO_ROOT / ".env", slot, api_key)
        print(f"\n  saved {slot} to .env")
        if keystore.gh_available():
            keystore.set_github_secret(REPO_ROOT, slot, api_key)
            print(f"  saved {slot} to GitHub secrets")
        else:
            print(
                f"  ! gh is not installed, so the workflows do not have the "
                f"key yet. Run:  gh secret set {slot}"
            )
    elif keystore.gh_available() and slot not in {
        s.name for s in keystore.list_github_secrets(REPO_ROOT)
    }:
        keystore.set_github_secret(REPO_ROOT, slot, api_key)
        print(f"\n  {slot} was only on this machine — saved it to GitHub secrets too")

    if plan.new:
        before = registry_path.read_text(encoding="utf-8") if registry_path.is_file() else "accounts:\n"
        registry_path.write_text(before.rstrip("\n") + "\n" + plan.yaml, encoding="utf-8")
        try:
            load_accounts(registry_path)
        except ConfigError:
            # Never leave the registry unreadable: every campaign loads it.
            registry_path.write_text(before, encoding="utf-8")
            raise
        print(
            f"\nAdded {len(plan.new)} account(s) to {ACCOUNTS_FILE}. Commit and "
            f"push it; campaigns that post everywhere pick them up on the next "
            f"top-up."
        )
    else:
        print("\nNothing new to add.")
    return 0


# --------------------------------------------------------------------- command: web


# ------------------------------------------------------------------ command: clips


def known_clip_names(
    config: CampaignConfig,
    repo_root: Path,
    store: MediaStore | None,
    roster_names: Sequence[str] = (),
) -> list[str]:
    """Every asset name this campaign knows about, best source first.

    The Release is the truth about what the randomizer can reach, but it costs
    an API call and credentials. The local ``_uploaded`` archive is a free
    mirror of everything ingested from this machine, so it stands in when
    offline. Roster names are folded in last so a clip muted from another
    machine still shows up instead of silently vanishing from the list.
    """
    names: set[str] = set(roster_names)
    if store is not None:
        names.update(store.list_assets(_assets_tag(config)))
    archive = repo_root / INBOX_ROOT / config.library_key / ARCHIVE_DIR
    if archive.is_dir():
        names.update(p.name for p in archive.iterdir() if p.is_file())
    return sorted(n for n in names if kind_of(n) is not None)


def cmd_clips(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Show the randomizer roster, and mute or unmute clips by name.

    The dashboard is the comfortable way to do this; this exists so the same
    operation is scriptable and works over SSH.
    """
    if args.all_on and args.all_off:
        raise ConfigError("--all-on and --all-off cannot both be given")
    log = get_logger(command="clips", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    path = roster_path(_campaign_dir(config.slug))
    roster = load_roster(path)

    changed = False
    for names, enabled in ((args.on, True), (args.off, False)):
        if names:
            roster = roster.with_(names, enabled)
            changed = True

    store: MediaStore | None = None
    if env.get("GITHUB_REPOSITORY") and env.get("GITHUB_TOKEN"):
        store = _build_store(env, log, SystemClock())
    known = known_clip_names(config, REPO_ROOT, store, roster.disabled)

    if args.all_on or args.all_off:
        targets = [
            n for n in known
            if args.kind is None or (kind_of(n) or PartKind.HOOK).value == args.kind
        ]
        roster = roster.with_(targets, args.all_on)
        changed = True

    if changed:
        # Muting a name that no longer exists is harmless and is kept: the clip
        # may live in a Release this machine cannot see, and dropping the entry
        # would quietly un-mute it the next time credentials are present.
        save_roster(path, roster)
        unknown = [n for n in roster.disabled if n not in known]
        print(f"Wrote {path.relative_to(REPO_ROOT)}")
        if unknown:
            print(f"  note: {', '.join(unknown)} not found in the library (kept anyway)")

    for kind in PartKind:
        group = [n for n in known if kind_of(n) is kind]
        if not group:
            continue
        live = sum(1 for n in group if roster.is_enabled(n))
        # INBOX_DIRS already holds the human plural for each role ("bodies",
        # not "bodys"), so the label and the drop folder stay in agreement.
        print(f"\n{INBOX_DIRS[kind]} — {live}/{len(group)} in the randomizer")
        for name in group:
            mark = "on " if roster.is_enabled(name) else "off"
            print(f"  [{mark}] {name}")

    if not known:
        print("No clips found. Upload some with `ugc ingest` or the dashboard.")
    elif changed:
        print("\nCommit and push campaigns/ for the change to reach the workflows.")
    return 0


def cmd_web(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Serve the local drop-and-upload interface (SPEC §2.1 said no UI; this is
    an operator tool that runs on one laptop, not part of the unattended path)."""
    from src.web import WebApp, serve

    clock: Clock = SystemClock()
    log = get_logger(command="web", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)

    app = WebApp(
        config=config,
        repo_root=REPO_ROOT,
        inbox=REPO_ROOT / INBOX_ROOT / config.library_key,
        bank_path=_campaign_dir(config.slug) / "captions.txt",
        log=log,
        clock=clock,
    )
    serve(app, args.port, open_browser=not args.no_open)
    return 0


# ----------------------------------------------------------------- command: cleanup


def _queue_lines(item: QueueItem, zone: Any) -> list[str]:
    """One queued video, as a human reads it: when, what is in it, where it goes."""
    when = item.scheduled_for.astimezone(zone).strftime("%a %d %b %H:%M")
    clips = "+".join(
        n for n in (item.parts.get("hook", ""), *item.parts.get("bodies", "").split(","))
        if n
    )
    music = item.parts.get("music") or "no music"
    if item.parts.get("music"):
        music += f" @{item.parts.get('music_offset_sec', '0')}s"
    tag = f" · lineup:{item.lineup_id}" if item.lineup_id else ""
    lines = [
        f"  {item.id[:8]}  {when}  {item.status.value:<9} "
        f"{item.creative} · {clips} · {music}{tag}"
    ]
    if item.overlay:
        lines.append(f"            on screen: {item.overlay}")
    first = next((ln for ln in item.caption.splitlines() if ln.strip()), "")
    lines.append(f"            caption:   {first[:90]}")
    for name, variant in item.variants.items():
        clip = variant.parts.get("hook", "")
        cue = variant.parts.get("music_offset_sec", "")
        lines.append(
            f"            {name}: {clip}"
            + (f" @{cue}s" if variant.parts.get("music") else "")
            + (f" · \"{variant.overlay}\"" if variant.overlay else "")
        )
    if item.first_comment:
        lines.append(f"            first comment: {item.first_comment[:80]}")
    if item.posts:
        lines.append(
            "            "
            + "  ".join(f"{p.account}={p.status.value}" for p in item.posts)
        )
    elif item.accounts:
        lines.append(f"            goes to:   {', '.join(item.accounts)}")
    return lines


def cmd_queue(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Show the queue, and withdraw videos from it — and from Buffer.

    Config changes only reach the *next* render. Everything already rendered
    carries the settings it was built with, so a campaign that has just had
    its captions rewritten or its music muted keeps publishing the old shape
    for as long as the queue is deep.

    Withdrawing is deliberately two-speed. A ``pending`` video exists only on
    disk and costs nothing to drop. A ``pushed`` one is already scheduled in
    Buffer and has to be deleted there too, which needs that account's API
    key and only works while it is still queued — once the network publishes
    it, it is out (SPEC §4.2).

    ``--id`` narrows any of this to one video (a prefix of its id is enough)
    and ``--account`` to one account, so a single post can be pulled from a
    single channel while the rest go ahead.
    """
    log = get_logger(command="queue", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    path = _campaign_dir(config.slug) / "queue.json"
    queue = load_queue(path)

    counts = Counter(i.status.value for i in queue.items)
    print(f"{config.slug} — {len(queue.items)} items")
    for status, n in sorted(counts.items()):
        print(f"  {status:10s} {n:3d}")

    selected = queue.items
    if args.id:
        selected = [i for i in queue.items if i.id.startswith(args.id)]
        if not selected:
            print(f"\nno queued video has an id starting {args.id!r}", file=sys.stderr)
            return 1

    if not args.discard:
        print()
        for item in sorted(selected, key=lambda i: i.scheduled_for):
            print("\n".join(_queue_lines(item, config.zone)))
        print(
            "\nWithdraw with --discard pending|pushed|all "
            "(narrow with --id <id> and/or --account <name>)."
        )
        return 0

    wanted = {
        "pending": {QueueStatus.PENDING},
        "pushed": {QueueStatus.PUSHED},
        "all": {QueueStatus.PENDING, QueueStatus.PUSHED, QueueStatus.FAILED},
    }[args.discard]

    registry = load_accounts(REPO_ROOT / ACCOUNTS_FILE)
    publishers: dict[str, Publisher] = {}

    def _publisher_for(
        slot: str,
        organization_id: str | None,
        account: AccountConfig | None = None,
    ) -> Publisher:
        # Built only when something actually has to be deleted remotely, so
        # the offline case never trips over a missing key it does not need.
        if slot not in publishers:
            if config.posting.dry_run:
                publishers[slot] = DryRunPublisher(log)
            else:
                key = _secret(slot, env)
                if not key:
                    raise ConfigError(
                        f"{slot} is not set — it is needed to remove a post "
                        f"that is already being held"
                    )
                publishers[slot] = (
                    _real_publisher(account, key, log)
                    if account is not None
                    else BufferPublisher(key, log, organization_id=organization_id)
                )
        return publishers[slot]

    # Every (item, record) to withdraw. An item with per-account records is
    # withdrawn record by record; one without (a single-channel campaign, or
    # a video not yet expanded) is withdrawn whole.
    plan: list[tuple[QueueItem, Any]] = []
    for item in selected:
        if item.posts:
            for record in item.posts:
                if args.account and record.account != args.account:
                    continue
                if record.status in wanted:
                    plan.append((item, record))
        elif not args.account and item.status in wanted:
            plan.append((item, None))
        elif args.account and item.status in wanted and item.status is QueueStatus.PENDING:
            # Not expanded yet: narrow the accounts it will be expanded to.
            plan.append((item, args.account))
    if not plan:
        print(f"\nnothing {args.discard} to discard")
        return 0

    if args.dry_run and not config.posting.dry_run:
        print(f"\nwould withdraw {len(plan)} post(s); --dry-run, nothing written")
        return 0

    cancelled, failed = 0, 0
    post: Any
    for item, post in plan:
        if isinstance(post, str):
            reach = [a.name for a in accounts_for(registry, config.accounts)]
            current = item.accounts if item.accounts is not None else reach
            item.accounts = [n for n in current if n != post]
            cancelled += 1
            continue
        post_id = post.buffer_post_id if post is not None else item.buffer_post_id
        status = post.status if post is not None else item.status
        if status is QueueStatus.PUSHED:
            if not post_id:
                log.warning("queue_discard_no_post_id", item=item.id)
                failed += 1
                continue
            account = registry.by_name(post.account) if post is not None else None
            slot = account.api_key_secret if account else config.buffer.api_key_secret
            org = account.organization_id if account else config.buffer.organization_id
            try:
                _publisher_for(slot, org, account).delete_post(post_id)
            except UgcError as exc:
                # Most likely already published, which is exactly the case
                # that cannot be undone. Leave the record alone so it keeps
                # saying what really happened.
                log.warning(
                    "queue_discard_remote_failed",
                    item=item.id, post_id=post_id, error=str(exc),
                )
                failed += 1
                continue
        if post is not None:
            transition_post(post, QueueStatus.CANCELLED, item.id, log=log)
            sync_status(item)
        else:
            cancel(item, log=log)  # mutates in place
        cancelled += 1

    save_queue(path, queue)
    print(
        f"\nwithdrew {cancelled} post(s)"
        + (f"; {failed} could not be removed (most likely already published)"
           if failed else "")
    )
    print("Commit and push campaigns/ for the change to reach the workflows.")
    return 0


def cmd_publish_due(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Send every held Instagram post whose slot has arrived.

    Accounts that post through Buffer need nothing like this: Buffer publishes
    on its own. An account that posts to Instagram directly has its posts held
    in ``outbox/`` (see ``src/publishers/instagram.py``), and this is what
    sends them. It runs on a short timer and is safe to run at any moment —
    a post not yet due is left alone, and one already sent is never sent
    twice.

    Not tied to a campaign: a held post already carries everything needed to
    publish it, and an account can be fed by several campaigns.
    """
    log = get_logger(command="publish-due")
    registry = load_accounts(REPO_ROOT / ACCOUNTS_FILE)
    direct = [
        a for a in registry.live
        if a.provider is Provider.INSTAGRAM
        and (not args.account or a.name == args.account)
    ]
    if not direct:
        print("no account posts to Instagram directly; nothing to do")
        return 0

    by_slot: dict[str, list[AccountConfig]] = {}
    for account in direct:
        by_slot.setdefault(account.api_key_secret, []).append(account)

    vcs: Vcs = (
        NullVcs(log) if args.dry_run or args.no_commit else GitVcs(REPO_ROOT, log)
    )
    # This run may have waited behind another sender, and was checked out at
    # the commit that started it. Read the outbox as it is now, or a post the
    # run before this one sent still looks unsent here and goes out twice.
    vcs.sync()

    def checkpoint(path: Path, what: str) -> None:
        if what == "claim":
            # Refused if anyone else changed this post first: then it is not ours.
            vcs.commit([path], f"publishing {path.stem[:12]}")
        else:
            vcs.record([path], f"published {path.stem[:12]}")

    exit_code = 0
    for slot, accounts in by_slot.items():
        names = {_account_channel(a, env): a.name for a in accounts}
        token = _secret(slot, env)
        if not token:
            print(f"{slot} is not set — cannot publish for "
                  f"{', '.join(names.values())}", file=sys.stderr)
            exit_code = 1
            continue
        publisher = _real_publisher(accounts[0], token, log)
        assert isinstance(publisher, InstagramPublisher)  # filtered above
        if args.dry_run:
            for channel, name in names.items():
                state = publisher.queue_state(channel)
                print(f"{name}: {state.depth} held, next due {state.next_due}")
            continue
        publisher.checkpoint = checkpoint
        try:
            changed = publisher.publish_due(
                channel_ids=set(names), send_next=bool(getattr(args, "now", False))
            )
        except VcsError as exc:
            # A claim was refused: another run holds that post. Everything sent
            # so far is already recorded; the rest goes out on the next run.
            print(f"stopped: {exc}", file=sys.stderr)
            return 1
        for item in changed:
            name = names.get(str(item.get("channel_id")), "?")
            status = item.get("status")
            print(f"{name}: {str(item.get('id'))[:12]} {status}"
                  + (f" — {item['error']}" if item.get("error") else ""))
            if item.get("error"):
                exit_code = 1
        if publisher.touched:
            vcs.record(
                sorted(set(publisher.touched)),
                f"publish {len(changed)} for {', '.join(sorted(names.values()))}",
            )
    return exit_code


def cmd_analytics(args: argparse.Namespace, env: dict[str, str]) -> int:
    """Fetch a product's signups and line them up against posting.

    The figure this repo never had. Everything else it collects is reach, and
    reach was only ever a proxy: a hook earning 1,400 views and no signups is
    worth less than one earning 200 that converts, and nothing could tell them
    apart.

    What comes back is a join by *day*, not an attribution by post. The signup
    series is product-wide and carries no per-post identifier, so it can say
    whether the days we posted differed from the days we did not, and cannot
    say which hook did it. Posting is summed across every campaign sharing this
    one's assets Release, because those campaigns are one brand driving one
    product — joining product-wide signups against a single network's posting
    would imply an attribution the data does not support.
    """
    log = get_logger(command="analytics", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    clock: Clock = SystemClock()

    if not config.analytics.configured:
        # Not an error. Most campaigns have no admin API behind them, and this
        # runs across every campaign in a matrix — failing the ones without a
        # product to measure would make the job red for a correct config.
        print(
            f"{config.slug} has no analytics.base_url and analytics.api_key_secret; "
            f"nothing to fetch. Add both to config.yaml to read acquisition figures."
        )
        return 0
    key = _secret(config.analytics.api_key_secret, env)
    if not key:
        raise ConfigError(
            f"{config.analytics.api_key_secret} is not set. Admin API keys are "
            f"typically shown once and stored only as a hash, so a lost key is "
            f"reissued rather than recovered."
        )

    source = HttpProductAnalytics(config.analytics.base_url, key, log)
    if args.scopes:
        print(json.dumps(source.scopes(), indent=2)[:4000])
        return 0

    since, until = range_from_clock(clock.now(), args.days)
    overview = source.overview(since, until)
    try:
        cohorts = source.cohorts(weeks=16)
    except UgcError as exc:
        # A missing cohort grid must not cost the overview that already
        # succeeded: it is one panel, not the point of the run.
        log.warning("analytics_cohorts_failed", error=str(exc))
        cohorts = None

    path = analytics_cache_path(_campaign_dir(config.slug))
    cache = load_analytics_cache(path)
    cache.fetches.append(overview)
    if cohorts is not None:
        # The cache model is frozen, so this is a rebuild rather than an
        # assignment; fetches is carried across by reference deliberately.
        cache = cache.model_copy(update={"cohorts": cohorts})
    save_analytics_cache(path, cache)
    log.info(
        "analytics_fetched", since=since.isoformat(), until=until.isoformat(),
        signups=overview.signups, users=overview.users,
        days=len(overview.signups_by_day),
    )

    posts_by_day: dict[date, int] = {}
    views_by_day: dict[date, float] = {}
    siblings = [
        s.slug for s in list_campaigns(CAMPAIGNS_DIR)
        if s.valid and s.assets_tag == config.assets_tag
    ]
    for slug in siblings:
        campaign_dir = _campaign_dir(slug)
        try:
            history = load_history(campaign_dir / "history.json")
            posts = load_posts(posts_path(campaign_dir)).posts
        except UgcError:
            continue
        for entry in history.entries:
            day = entry.timestamp.date()
            if not since <= day <= until:
                continue
            posts_by_day[day] = posts_by_day.get(day, 0) + 1
            post = posts.get(entry.buffer_post_id or "")
            if post is not None:
                views_by_day[day] = views_by_day.get(day, 0.0) + (
                    post.value("views") or 0.0
                )

    rows = correlate(posts_by_day, views_by_day, overview.by_day)
    print(f"{config.slug} — {since} to {until}")
    print(f"  posting summed over: {', '.join(siblings)}")
    print(f"  {overview.users} users total, {overview.signups} signups in range\n")
    print(f"  {'day':<12}{'posts':>6}{'views':>10}{'signups':>9}{'views/signup':>14}")
    for row in rows:
        ratio = row.views_per_signup
        shown = f"{ratio:,.0f}" if ratio is not None else "—"
        print(f"  {row.day.isoformat():<12}{row.posts:>6}{row.views:>10,.0f}"
              f"{row.signups:>9}{shown:>14}")

    # Whether the copy is aimed at the demand that exists — the one check
    # here that can be made before a post goes out rather than after. Uses the
    # same sibling set as the join above: one brand's banks against one
    # product's search log.
    corpus = ""
    for slug in siblings:
        directory = _campaign_dir(slug)
        # The shared bank plus every network's own: the copy a searcher might
        # meet is spread across all of them now.
        banks = [directory / "captions.txt"]
        banks += sorted((directory / "captions").glob("*.txt"))
        for captions in banks:
            if captions.is_file():
                corpus += "\n" + captions.read_text(
                    encoding="utf-8", errors="replace"
                )
    gap = vocabulary_gap(
        [(s.label, int(s.value)) for s in overview.top_searches], corpus,
        config.notify.demand_ignore,
    )
    floor = config.notify.demand_coverage_floor
    if gap.coverage is not None:
        print(f"\n  captions speak to {gap.coverage * 100:.0f}% of search volume")
        if gap.coverage < floor:
            worst = ", ".join(
                f"{t.query} ({t.searches})" for t in gap.worst(8)
            )
            log.warning(
                "demand_unmet", campaign=config.slug,
                coverage=round(gap.coverage, 3), floor=floor,
            )
            notifier_for(config, log, env).notify(
                NotifyEvent.DEMAND_UNMET,
                f"{config.slug}: captions speak to only "
                f"{gap.coverage * 100:.0f}% of search volume "
                f"(floor {floor * 100:.0f}%). Most-searched terms no caption "
                f"mentions — {worst}. Word overlap only: it catches a term "
                f"never mentioned, not whether a video was about it.",
            )

    posted = [r for r in rows if r.posts]
    quiet = [r for r in rows if not r.posts]
    if posted and quiet:
        busy = sum(r.signups for r in posted) / len(posted)
        idle = sum(r.signups for r in quiet) / len(quiet)
        print(f"\n  mean signups on the {len(posted)} day(s) with posts: {busy:.1f}")
        print(f"  mean signups on the {len(quiet)} day(s) without:    {idle:.1f}")
        print("  A correlation over few days, not an attribution — the signup "
              "figure is product-wide.")
    return 0


def cmd_cleanup(args: argparse.Namespace, env: dict[str, str]) -> int:
    clock: Clock = SystemClock()
    log = get_logger(command="cleanup", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)
    notifier = notifier_for(config, log, env)
    try:
        store = _build_store(env, log, clock)
        # Scoped to this campaign's render tags so a shared repo cannot delete
        # another campaign's videos — and never matches `assets-<slug>`.
        deleted = store.cleanup(f"render-{config.slug}-", RENDER_RETENTION_DAYS)
        log.info("cleanup_complete", deleted=len(deleted), tags=deleted)

        if args.digest:
            queue = load_queue(_campaign_dir(config.slug) / "queue.json")
            history = load_history(_campaign_dir(config.slug) / "history.json")
            notifier.digest(_build_digest(config, queue, history, clock))
        return 0
    except UgcError as exc:
        log.exception("cleanup_failed", exc)
        notifier.failure("cleanup", exc, campaign=config.slug)
        return 1


def _build_digest(
    config: CampaignConfig,
    queue: Queue,
    history: History,
    clock: Clock | None = None,
) -> Digest:
    """The weekly summary, carrying only figures it can actually compute.

    Everything here is derived from files on disk, so the digest costs no API
    calls — which matters, because it is the one thing that reaches a human
    without them opening anything.
    """
    pending = [i for i in queue.items if i.status is QueueStatus.PENDING]
    today = (clock.now() if clock else SystemClock().now()).astimezone(
        config.zone
    ).date()

    # Rolling request total, across every campaign sharing this key: the
    # allowance belongs to the Buffer account rather than to one campaign.
    slot = config.buffer.api_key_secret
    ledgers = []
    for summary in list_campaigns(CAMPAIGNS_DIR):
        if not summary.valid:
            continue
        try:
            other = load_campaign(CAMPAIGNS_DIR, summary.slug)
        except UgcError:
            continue
        if other.buffer.api_key_secret == slot:
            ledgers.append(load_quota(quota_path(_campaign_dir(other.slug))))
    requests = rolling_total(ledgers, today) if ledgers else None

    # Rendered against published, lifetime. The metrics cache is the only
    # record of what actually reached a network.
    delivery = None
    metrics_path = _campaign_dir(config.slug) / "metrics.json"
    if history.entries and metrics_path.is_file():
        try:
            snapshots = load_metrics(metrics_path).snapshots
            lifetime = [s for s in snapshots if s.scope is Scope.LIFETIME]
            if lifetime:
                published = next(
                    (m.value for m in lifetime[-1].metrics if m.type == "postCount"),
                    None,
                )
                if published is not None:
                    delivery = min(1.0, published / len(history.entries))
        except UgcError:
            delivery = None

    asks = None
    bank_path = _campaign_dir(config.slug) / "captions.txt"
    if bank_path.is_file():
        try:
            from src.insights import _ctas

            bodies = [d.body for d in parse_bank(bank_path.read_text(encoding="utf-8"))]
            if bodies:
                asks = (len({a for b in bodies for a in _ctas(b)}), len(bodies))
        except UgcError:
            asks = None

    # Which clip is actually working, from this campaign's own posts — all one
    # network, so the ranking is per network without doing anything.
    best = None
    try:
        cached = load_posts(posts_path(_campaign_dir(config.slug))).posts
        if cached:
            for report in attribute(history.entries, cached):
                if report.rankable and report.ratio:
                    top, bottom = report.options[0], report.options[-1]
                    best = (
                        report.dimension, top.option, bottom.option,
                        report.ratio,
                    )
                    break
    except UgcError:
        best = None

    return Digest(
        campaign=config.slug,
        posted=len([i for i in queue.items if i.status is QueueStatus.PUSHED]),
        failed=len([i for i in queue.items if i.status is QueueStatus.FAILED]),
        queue_depth=len(pending),
        queue_runway_hours=len(pending) * (24 / max(1, config.posting.posts_per_day)),
        buffer_requests_30d=requests,
        delivery_rate=delivery,
        caption_asks=asks,
        best_performer=best,
    )


# --------------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ugc-factory",
        description="Assemble and schedule short vertical videos.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--campaign", required=True, help="campaign slug")
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="never contact the publisher; overrides config",
        )

    render = sub.add_parser("render", help="render tonight's batch")
    common(render)
    render.add_argument("--count", type=int, default=None,
                        help="override posts_per_day for this run")
    render.add_argument("--plan", action="store_true",
                        help="show what would be rendered and exit, changing "
                             "nothing")

    publish_due = sub.add_parser(
        "publish-due",
        help="send held Instagram posts whose slot has arrived",
    )
    publish_due.add_argument("--account", default="",
                             help="only this account (default: all)")
    publish_due.add_argument("--dry-run", action="store_true",
                             help="show what is held and send nothing")
    publish_due.add_argument("--no-commit", action="store_true",
                             help="skip git commits (local testing only)")
    publish_due.add_argument("--now", action="store_true",
                             help="send each account's next held post now, "
                                  "whatever its slot")

    topup = sub.add_parser("topup", help="fill Buffer's queue to its cap")
    common(topup)
    topup.add_argument("--no-commit", action="store_true",
                       help="skip git commits (local testing only — removes the "
                            "crash-resume guarantee)")

    preflight = sub.add_parser("preflight", help="validate config, secrets, library")
    common(preflight)

    ingest = sub.add_parser(
        "ingest", help="upload files from inbox/ to a creative's assets Release"
    )
    common(ingest)
    ingest.add_argument(
        "--creative", default=None,
        help="which creative to upload into (default: the campaign's first)",
    )
    ingest.add_argument(
        "--report", default=None,
        help="write what happened to each file to this JSON path",
    )

    diagnose = sub.add_parser("diagnose", help="why did a queued post not publish")
    common(diagnose)
    diagnose.add_argument("--limit", type=int, default=20)

    metrics = sub.add_parser("metrics", help="fetch performance metrics into the cache")
    common(metrics)
    metrics.add_argument("--days", type=int, default=30,
                         help="aggregation window in days (default 30)")
    metrics.add_argument("--instagram-only", action="store_true",
                         help="only the per-post figures of accounts that post to Instagram "
                              "directly: no Buffer requests (run every few hours)")

    setup = sub.add_parser("setup", help="readiness check: what is missing and how to fix it")
    common(setup)

    web = sub.add_parser("web", help="local drop-and-upload interface")
    common(web)
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-open", action="store_true",
                     help="do not open a browser window")

    clips = sub.add_parser(
        "clips", help="list, mute or unmute the clips the randomizer draws from"
    )
    common(clips)
    clips.add_argument("--on", nargs="+", metavar="NAME", default=[],
                       help="put these clips back into the randomizer")
    clips.add_argument("--off", nargs="+", metavar="NAME", default=[],
                       help="hold these clips out of the randomizer")
    clips.add_argument("--all-on", action="store_true",
                       help="unmute everything (optionally narrowed by --kind)")
    clips.add_argument("--all-off", action="store_true",
                       help="mute everything (optionally narrowed by --kind)")
    clips.add_argument("--kind", choices=[k.value for k in PartKind],
                       help="limit --all-on/--all-off to one role")

    queue_cmd = sub.add_parser(
        "queue", help="show the queue, or withdraw items a config change has stranded"
    )
    common(queue_cmd)
    queue_cmd.add_argument(
        "--discard", choices=["pending", "pushed", "all"],
        help="withdraw items; 'pushed' and 'all' also delete them from Buffer",
    )
    queue_cmd.add_argument(
        "--id", default=None,
        help="only this video (a prefix of its id is enough)",
    )
    queue_cmd.add_argument(
        "--account", default=None,
        help="only this account's copy of each video",
    )

    analytics = sub.add_parser(
        "analytics", help="fetch product signups and compare them with posting"
    )
    common(analytics)
    analytics.add_argument("--days", type=int, default=30,
                           help="how many days back to fetch (default 30)")
    analytics.add_argument("--scopes", action="store_true",
                           help="print what this key can reach, and exit")

    connect = sub.add_parser(
        "connect",
        help="connect a Buffer login: store its key and register its channels",
    )
    connect.add_argument("--slot", type=int, default=None,
                         help="which login, 1-8 (omit to list what is connected)")
    connect.add_argument("--name", default=None,
                         help="what to call this login's accounts, e.g. "
                              "creatives_lets_create (default: its channel name)")
    connect.add_argument("--dry-run", action="store_true",
                         help="show what would be added and write nothing")

    cleanup = sub.add_parser("cleanup", help="delete expired render Releases")
    common(cleanup)
    cleanup.add_argument("--digest", action="store_true",
                         help="also post the weekly digest")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # The dashboard writes credentials to .env, and until now only the
    # dashboard read them back — so a key pasted into the panel built for
    # pasting keys left every CLI command insisting it was not set. Real
    # environment variables win, which keeps Actions (where there is no .env
    # and everything arrives as workflow env) behaving exactly as before, and
    # lets an explicit export override the file for a one-off.
    env = {**read_env(REPO_ROOT / ".env"), **os.environ}

    handlers = {
        "render": cmd_render,
        "topup": cmd_topup,
        "preflight": cmd_preflight,
        "ingest": cmd_ingest,
        "web": cmd_web,
        "clips": cmd_clips,
        "queue": cmd_queue,
        "analytics": cmd_analytics,
        "setup": cmd_setup,
        "metrics": cmd_metrics,
        "diagnose": cmd_diagnose,
        "cleanup": cmd_cleanup,
        "connect": cmd_connect,
        "publish-due": cmd_publish_due,
    }
    try:
        return handlers[args.command](args, env)
    except UgcError as exc:
        # Anything that escaped a command's own handling. Printed as well as
        # logged so a failed Actions run shows the reason in its summary.
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
