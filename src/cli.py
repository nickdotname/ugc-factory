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
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from src.assets import (
    GitHubReleasesStore,
    LocalLibrary,
    MediaStore,
    check_music_licenses,
    github_token_from_env,
)
from src.clips import filter_library, kind_of, load_roster, roster_path, save_roster
from src.config import CampaignConfig, NotifyEvent, TitleStrategy, load_campaign
from src.descriptions import Description, load_bank, parse_bank, validate_bank
from src.errors import AuthError, ConfigError, QuotaError, SelectionError, UgcError
from src.ingest import (
    ARCHIVE_DIR,
    INBOX_DIRS,
    apply_plan,
    build_plan,
    combinations,
    ensure_inbox,
    library_health,
)
from src.logging import StructuredLogger, get_logger
from src.models import (
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
from src.attribution import attribute, load_posts, posts_path, save_posts
from src.platforms import Service, config_conflicts, effective_video_limits
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
from src.queue import (
    append_history,
    backfill_post_id,
    carry_forward,
    claimable,
    depth_needed,
    load_history,
    load_queue,
    mark_failed,
    mark_pushed,
    reset_for_retry,
    save_queue,
    spread_schedule,
    stranded,
    upcoming_slots,
    transition,
)
from src.render import FfmpegRenderer, Renderer
from src.selector import (
    AssetLibrary,
    Relaxation,
    Selector,
    days_until_first_repeat,
    tuple_hash,
)
from src.vcs import GitVcs, NullVcs, Vcs

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
) -> AssetLibrary:
    composition = config.composition if config else None
    return AssetLibrary(
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


def _load_captions(
    path: Path, service: Service, strategy: TitleStrategy | None = None
) -> list[Description]:
    """Read and validate the description bank for the campaign's platform.

    Descriptions are the text a video is posted *with* — not anything drawn onto
    the frame. Validated here against the target platform's limits so an
    over-long description fails at preflight rather than at publish time, where
    it would cost API quota to discover.
    """
    if not path.is_file():
        raise ConfigError(f"description bank not found: {path}")
    return load_bank(
        path.read_text(encoding="utf-8"), service, source=str(path),
        strategy=strategy,
    )


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
    assets_dir = work / "assets"
    out_dir = work / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    store = _build_store(env, log, clock)
    store.download_assets(_assets_tag(config), assets_dir)
    # Muted clips are removed before anything downstream counts them, so the
    # ceiling logged below is the ceiling of what is actually in rotation.
    paths = filter_library(
        LocalLibrary.from_directory(assets_dir),
        load_roster(roster_path(campaign_dir)),
        log,
    )

    missing_licenses = check_music_licenses(
        paths.music, assets_dir / "LICENSES.md", log
    )
    if missing_licenses:
        notifier.notify(
            NotifyEvent.LICENSE_MISSING,
            f"⚠️ {config.slug}: music tracks with no LICENSES.md entry: "
            + ", ".join(missing_licenses[:20]),
        )

    descriptions = _load_captions(
        campaign_dir / "captions.txt", config.buffer.service,
        config.buffer.title_strategy,
    )
    renderer: Renderer = FfmpegRenderer(config, log)

    # Probing every track once up front is what lets the selector cut a long
    # song into segments; without durations it degrades to one bed per track
    # starting at 0:00.
    durations: dict[str, float] = {}
    if config.composition.music_random_start:
        for track in paths.music:
            try:
                durations[track.name] = renderer.probe(track).duration_sec
            except UgcError as exc:
                log.warning("music_probe_failed", track=track.name, error=str(exc))

    library = _library_from(paths, descriptions, config, durations)

    history = load_history(campaign_dir / "history.json")
    # Seeded from the render date so a given day is reproducible, while
    # successive days still differ (SPEC §2.2).
    today = clock.now()
    rng: Rng = SeededRng(int(today.strftime("%Y%m%d")))
    selector = Selector(config.selection, clock, rng, log)

    # Carry over whatever last night produced and the top-up has not pushed.
    # Replacing the queue here is what threw away most of the output.
    previous = load_queue(campaign_dir / "queue.json")
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
    count = args.count if args.count else max(0, target - len(carried))
    log.info(
        "render_demand",
        carried=len(carried), expired=len(expired), target=target,
        rendering=count, posts_per_day=config.posting.posts_per_day,
    )
    if getattr(args, "plan", False):
        # Everything above is read-only: the library is cached, the queue was
        # loaded, nothing has been rendered, uploaded or written. Stopping here
        # answers "what would tonight do" without doing it.
        print(f"\n  {config.slug} · render plan")
        print(f"    carried forward     {len(carried)}")
        print(f"    expired, dropped    {len(expired)}")
        print(f"    backlog target      {target}"
              f"  ({config.posting.posts_per_day}/day x "
              f"{config.posting.max_backlog_days} days)")
        print(f"    would render        {count}")
        if count == 0:
            print("\n  Backlog is full — tonight would render nothing.")
        else:
            ceiling = library.ceiling(
                config.composition.bodies_per_video,
                config.composition.bodies_per_video_max,
            )
            print(f"\n  {ceiling:,} combinations available, "
                  f"{len(history.entries):,} already used.")
        return 0

    if count == 0:
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
        log.info("render_skipped", reason="backlog already at target",
                 carried=len(carried))
        save_queue(
            campaign_dir / "queue.json",
            Queue(generated_at=today, items=carried),
        )
        print(
            f"OK {config.slug}: backlog already holds {len(carried)} unpublished "
            f"videos (target {target}); rendered nothing."
        )
        return 0

    # What has actually performed, from this campaign's own posts — which are
    # all one network, so no cross-network pooling is possible here.
    performance = _performance_medians(config, history, log)

    outcomes = selector.select_batch(
        library, history, count, config.composition.bodies_per_video,
        config.composition.bodies_per_video_max,
        performance=performance,
    )
    relaxed = [o for o in outcomes if o.relaxation is not Relaxation.NONE]
    if relaxed:
        notifier.notify(
            NotifyEvent.DEDUPE_RELAXED,
            f"⚠️ {config.slug}: {len(relaxed)}/{len(outcomes)} selections needed "
            f"relaxed dedupe ({relaxed[0].relaxation.value}). The library is too "
            f"small for {config.posting.posts_per_day} posts/day.",
        )

    by_name = paths.by_name()

    # Title lookup by description body: Selection carries only the body (that
    # is what dedupe keys on), so the title is re-attached here from the bank.
    titles = {d.body: d.title for d in descriptions}

    # Fill the next free slots rather than deferring the whole batch a day.
    # SPEC §4.2 wanted the render->push gap as a review window, but the review
    # window that actually matters is Buffer's own queue: a pushed post sits
    # there, visible and deletable, until its slot arrives.
    slots = upcoming_slots(
        today,
        len(outcomes),
        config.posting.start_hour,
        config.posting.end_hour,
        config.posting.posts_per_day,
        config.zone,
        # Carried items already hold slots; two videos in one slot would be
        # published minutes apart, which is the failure the schedule prevents.
        exclude={i.scheduled_for for i in carried},
    )
    if len(slots) < len(outcomes):
        raise ConfigError(
            f"only {len(slots)} slots available for {len(outcomes)} videos; "
            f"posts_per_day is {config.posting.posts_per_day}"
        )

    rendered: list[tuple[QueueItem, Selection]] = []
    for outcome, slot in zip(outcomes, slots):
        selection = outcome.selection
        item_id = str(uuid.uuid4())
        request = RenderRequest(
            item_id=item_id,
            hook_path=by_name[selection.hook],
            body_paths=tuple(by_name[b] for b in selection.bodies),
            music_path=by_name[selection.music] if selection.music else None,
            music_offset_sec=selection.music_offset_sec,
            output_path=out_dir / f"{item_id}.mp4",
        )
        result = renderer.render(request)
        rendered.append((
            QueueItem(
                id=item_id,
                scheduled_for=slot,
                rendered_at=today,
                video_url="",  # filled in after upload
                caption=selection.caption,
                title=titles.get(selection.caption),
                parts={
                    "hook": selection.hook,
                    "bodies": ",".join(selection.bodies),
                    "music": selection.music or "",
                    "music_offset_sec": f"{selection.music_offset_sec:.0f}",
                },
                treatment=result.treatment,
            ),
            selection,
        ))
        log.info("item_rendered", item_id=item_id, path=str(result.output_path))

    tag = _render_tag(config.slug, today)
    published = store.publish(tag, [out_dir / f"{i.id}.mp4" for i, _ in rendered])
    urls = {a.name: a.url for a in published}
    for item, _ in rendered:
        item.video_url = urls[f"{item.id}.mp4"]

    queue = Queue(
        generated_at=today,
        items=sorted(
            [*carried, *(i for i, _ in rendered)],
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
                treatment=item.treatment,
            )
            for item, sel in rendered
        ],
    )

    runway = days_until_first_repeat(
        library, history, config.composition.bodies_per_video,
        config.posting.posts_per_day,
    )
    log.info("render_complete", items=len(rendered), tag=tag, runway_days=runway)
    if runway < 7:
        notifier.notify(
            NotifyEvent.QUEUE_EMPTY,
            f"⚠️ {config.slug}: only {runway:.0f} days of unique combinations "
            f"remain. Add hooks, bodies or captions.",
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

    try:
        return _topup(args, env, config, log, notifier, clock)
    except UgcError as exc:
        log.exception("topup_failed", exc)
        notifier.failure("topup", exc, campaign=config.slug)
        return 1


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

    depth = publisher.queue_depth(channel)
    need = depth_needed(depth, config.posting.max_buffer_queue)
    ready = claimable(queue)
    to_push = ready[:need]

    log.info(
        "topup_plan",
        buffer_depth=depth,
        cap=config.posting.max_buffer_queue,
        need=need,
        available=len(ready),
        pushing=len(to_push),
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
                    video_url=item.video_url,
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
    count = getattr(publisher, "request_count", 0)
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
        try:
            store = _build_store(env, log, clock)
            work = REPO_ROOT / "work" / config.slug / "assets"
            store.download_assets(_assets_tag(config), work)
            paths = filter_library(
                LocalLibrary.from_directory(work),
                load_roster(roster_path(_campaign_dir(config.slug))),
                log,
            )

            # Probe music exactly as the render job does. Without durations the
            # library reports one bed per track and the runway comes out ~12x
            # short, failing a check the real render would pass.
            renderer: Renderer = FfmpegRenderer(config, log)
            durations: dict[str, float] = {}
            if config.composition.music_random_start:
                for track in paths.music:
                    try:
                        durations[track.name] = renderer.probe(track).duration_sec
                    except UgcError as exc:
                        log.warning(
                            "music_probe_failed", track=track.name, error=str(exc)
                        )

            # Duration is decided by which clips get picked, and the selector
            # cannot know that — it never probes the video parts. So the check
            # happens here, where the files are already downloaded, rather than
            # at 05:00 when an over-length cut fails validation after it has
            # been rendered.
            problems += _duration_headroom(paths, config, renderer, log)
            for note in config_conflicts(
                config.buffer.service,
                config.video.max_duration_sec,
                config.video.max_file_mb,
            ):
                print(f"WARN {note}", file=sys.stderr)

            library = _library_from(paths, descriptions, config, durations)
            library.validate()
            ceiling = library.ceiling(config.composition.bodies_per_video)
            runway = ceiling / max(1, config.posting.posts_per_day)
            log.info(
                "preflight_library_ok",
                hooks=len(library.hooks), bodies=len(library.bodies),
                music=len(library.music),
                music_beds=library.total_music_options(),
                captions=len(library.captions),
                combinations=ceiling, runway_days=runway,
            )
            if runway < config.selection.min_runway_days:
                problems.append(
                    f"library yields only {runway:.0f} days of unique combos at "
                    f"{config.posting.posts_per_day}/day; "
                    f"selection.min_runway_days is "
                    f"{config.selection.min_runway_days}"
                )
        except (UgcError, SelectionError) as exc:
            problems.append(f"library: {exc}")
    else:
        log.warning("preflight_library_skipped", reason="no GitHub credentials")

    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"OK preflight passed for {config.slug}")
    return 0


# ------------------------------------------------------------------ command: ingest


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
    for report in attribute(history.entries, posts):
        if not report.rankable:
            continue
        medians[report.dimension] = {
            option.option: option.median for option in report.options
        }
    if not medians:
        return None

    log.info(
        "performance_weighting",
        weight=config.selection.performance_weight,
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
    if not hooks or not bodies:
        return []

    composition = config.composition
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
    """Upload dropped files to the assets Release under correct names."""
    clock: Clock = SystemClock()
    log = get_logger(command="ingest", campaign=args.campaign)
    config = load_campaign(CAMPAIGNS_DIR, args.campaign)

    inbox = REPO_ROOT / INBOX_ROOT / config.library_key
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

    tag = _assets_tag(config)
    existing = store.list_assets(tag)
    renderer: Renderer = FfmpegRenderer(config, log)

    plan = build_plan(inbox, existing, renderer, log)
    print(f"\ninbox: {inbox}")
    print(plan.render_table())

    if plan.rejected:
        print(f"\n{len(plan.rejected)} file(s) will be skipped — see notes above.")
    if not plan.uploadable:
        print("\nNothing to upload.")
        return 1 if plan.rejected else 0

    if args.dry_run:
        print(f"\nDry run — nothing uploaded. Drop --dry-run to upload.")
        return 0

    uploaded = apply_plan(
        plan, inbox, store, tag, log,
        staging=REPO_ROOT / "work" / config.slug / "staging",
    )
    print(f"\nUploaded {len(uploaded)} file(s) to release {tag}.")

    _print_library_health(config, store, tag, log)
    return 0


def _print_library_health(
    config: CampaignConfig, store: MediaStore, tag: str, log: StructuredLogger
) -> None:
    """Tell the human, while they are still holding the files, if it is enough.

    The same shortfall would otherwise surface as a dedupe-relaxation alert at
    5 a.m., long after the moment when adding another clip was easy.
    """
    names = store.list_assets(tag)
    hooks = len([n for n in names if n.lower().startswith("hook")])
    bodies = len([n for n in names if n.lower().startswith("body")])
    music = len([n for n in names if n.lower().startswith("music")])
    try:
        captions = len(_load_captions(
            _campaign_dir(config.slug) / "captions.txt", config.buffer.service,
            config.buffer.title_strategy,
        ))
    except ConfigError:
        captions = 0

    per_video = config.composition.bodies_per_video
    total = combinations(hooks, bodies, music, captions, per_video)
    runway = total / max(1, config.posting.posts_per_day)

    print(
        f"\nlibrary: {hooks} hooks · {bodies} bodies · {music} music · "
        f"{captions} captions"
    )
    print(
        f"         {total} combinations = {runway:.0f} days at "
        f"{config.posting.posts_per_day}/day "
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

    api_key = _secret(config.buffer.api_key_secret, env)
    if not api_key:
        print(f"{config.buffer.api_key_secret} is not set", file=sys.stderr)
        return 1
    publisher = BufferPublisher(
        api_key, log, organization_id=config.buffer.organization_id
    )
    posts = publisher.diagnose_posts(_channel_id(config, env), limit=args.limit)
    # Diagnose is run by hand and rarely, but its requests come out of the same
    # allowance; a tally that only counts scheduled jobs drifts low over time.
    record_run(
        quota_path(_campaign_dir(config.slug)),
        clock.now().astimezone(config.zone).date(),
        getattr(publisher, "request_count", 0),
    )

    print(f"\n  {config.slug} · {config.buffer.service.value} · {len(posts)} posts\n")
    if not posts:
        print("  Buffer has no posts for this channel at all.")
        return 0

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
    return 0


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

        api_key = _secret(config.buffer.api_key_secret, env)
        if not api_key:
            raise ConfigError(f"{config.buffer.api_key_secret} is not set")
        publisher = BufferPublisher(
            api_key, log, organization_id=config.buffer.organization_id
        )
        channel = _channel_id(config, env)

        now = clock.now()
        local_date = now.astimezone(config.zone).strftime("%Y-%m-%d")
        path = _campaign_dir(config.slug) / "metrics.json"
        history = load_metrics(path)

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
        ]

        snapshots: list[Snapshot] = []
        for scope, start, end in windows:
            rows, updated_at = publisher.fetch_metrics(channel, start, end)
            snapshot = Snapshot(
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
            history.upsert(snapshot)
            snapshots.append(snapshot)
        save_metrics(path, history)
        snapshot = snapshots[0]

        # Per-post figures, in the same breath. `metrics` rides along inside
        # the posts query and takes no arguments, so this costs a handful of
        # paginated requests rather than one per post — which is what makes
        # attribution affordable at all.
        try:
            fresh = publisher.fetch_post_metrics(channel)
            cache_path = posts_path(_campaign_dir(config.slug))
            cache = load_posts(cache_path).merged_with(fresh)
            save_posts(cache_path, cache)
            log.info(
                "post_metrics_cached",
                fetched=len(fresh), total=len(cache.posts), campaign=config.slug,
            )
        except UgcError as exc:
            # Never fail the metrics run over attribution: the window snapshot
            # above is what preflight and the digest depend on.
            log.warning("post_metrics_failed", error=str(exc))

        log.info(
            "metrics_saved", campaign=config.slug, date=local_date,
            metrics=len(snapshot.metrics), snapshots=len(history.snapshots),
        )
        # Metrics runs daily per campaign and spends two requests each time.
        # Leaving it out understated the tally by ~90/month — the same silent
        # inaccuracy the rolling counter was added to remove.
        _report_quota(publisher, notifier, config, log, clock)
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
        return 0
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

    topup = sub.add_parser("topup", help="fill Buffer's queue to its cap")
    common(topup)
    topup.add_argument("--no-commit", action="store_true",
                       help="skip git commits (local testing only — removes the "
                            "crash-resume guarantee)")

    preflight = sub.add_parser("preflight", help="validate config, secrets, library")
    common(preflight)

    ingest = sub.add_parser(
        "ingest", help="upload files from inbox/ to the assets Release"
    )
    common(ingest)

    diagnose = sub.add_parser("diagnose", help="why did a queued post not publish")
    common(diagnose)
    diagnose.add_argument("--limit", type=int, default=20)

    metrics = sub.add_parser("metrics", help="fetch performance metrics into the cache")
    common(metrics)
    metrics.add_argument("--days", type=int, default=30,
                         help="aggregation window in days (default 30)")

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

    cleanup = sub.add_parser("cleanup", help="delete expired render Releases")
    common(cleanup)
    cleanup.add_argument("--digest", action="store_true",
                         help="also post the weekly digest")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = dict(os.environ)

    handlers = {
        "render": cmd_render,
        "topup": cmd_topup,
        "preflight": cmd_preflight,
        "ingest": cmd_ingest,
        "web": cmd_web,
        "clips": cmd_clips,
        "setup": cmd_setup,
        "metrics": cmd_metrics,
        "diagnose": cmd_diagnose,
        "cleanup": cmd_cleanup,
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
