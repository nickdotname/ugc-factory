"""A local drop-and-upload interface (``./ugc web``).

Responsibility: give a human a browser window where they can drag clips into the
right bucket, write descriptions, see whether the library is big enough, and
upload — without touching a terminal or learning the naming convention.

Deliberately built on ``http.server`` from the standard library. This is a local
convenience tool, and the unattended pipeline is the thing that has to run for
years; adding a web framework to ``requirements.txt`` would put a dependency
with its own CVE cadence into the cron path for the sake of a tool that only
ever runs on one laptop.

**Binds to 127.0.0.1 only.** It writes files and can upload to GitHub with the
operator's own credentials, so it must never be reachable from the network.
There is no authentication, because there is no remote access to authenticate.

Uploads arrive as raw request bodies with the filename in the query string
rather than as multipart form data — the stdlib's multipart support is
deprecated, and a single file per request streams to disk without buffering a
2 GB video in memory.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from src.assets import GitHubReleasesStore, LocalLibrary, MediaStore
from src.campaigns import create_campaign, list_campaigns, slug_error
from src.clips import ClipRoster, kind_of, load_roster, roster_path, save_roster
from src.config import CampaignConfig, load_campaign
from src.descriptions import Description, load_bank, parse_bank, validate_bank
from src.errors import UgcError
from src.keys import (
    delete_env_value,
    clean_value,
    check_name,
    list_github_secrets,
    mask,
    read_env,
    set_github_secret,
    write_env_value,
)
from src.ingest import (
    ARCHIVE_DIR,
    INBOX_DIRS,
    Verdict,
    apply_plan,
    build_plan,
    combinations,
    ensure_inbox,
    library_health,
)
from src.logging import StructuredLogger
from src.metrics import Scope, load_metrics
from src.models import PartKind
from src.platforms import Service
from src.revenue import (
    RevenueEntry,
    RevenueLedger,
    ledger_path,
    load_ledger,
    per_thousand,
    save_ledger,
)
from src.ports import Clock
from src.render import FfmpegRenderer

#: Filenames are attacker-controlled only in the sense that a browser sends
#: them, but a path separator or `..` would still escape the inbox.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._()\[\]#&+,'-]{1,180}$")

#: Refuse absurd uploads outright rather than filling the disk.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def _safe_name(raw: str) -> str | None:
    """Reduce a browser-supplied filename to something safe to join."""
    name = Path(raw).name.strip()  # strips any directory component
    # A whitespace-only name survives the character class below (space is legal
    # inside a filename) but is not a filename.
    if not name or name.startswith("."):
        return None
    return name if _SAFE_NAME.match(name) else None


def _kind_from(raw: str) -> PartKind | None:
    for kind, dirname in INBOX_DIRS.items():
        if raw == dirname:
            return kind
    return None


class WebApp:
    """State and operations behind the HTTP endpoints.

    Kept separate from the request handler so every operation is callable — and
    testable — without a socket.
    """

    def __init__(
        self,
        config: CampaignConfig,
        repo_root: Path,
        inbox: Path,
        bank_path: Path,
        log: StructuredLogger,
        clock: Clock,
        *,
        store_factory: Callable[[], MediaStore] | None = None,
    ) -> None:
        self.config = config
        self.repo_root = repo_root
        self.inbox = inbox
        self.bank_path = bank_path
        self.log = log
        self.clock = clock
        self._store_factory = store_factory
        # The campaigns directory is the unit the dashboard operates over; a
        # single campaign is just the one currently selected.
        self.campaigns_dir = bank_path.parent.parent
        # Probed once and cached: the state endpoint is polled every few
        # seconds, and ffprobing every track on each poll would be absurd.
        self._music_beds: int | None = None
        # Buffer channels change rarely and every fetch costs one of the
        # 3,000 monthly requests, so they are pulled once per session rather
        # than on each page load.
        # Keyed by slot: each Buffer account has its own channels, and mixing
        # them would offer a channel the campaign's key cannot post to.
        self._channels: dict[str, list[dict[str, Any]]] | None = None
        # Names in the assets Release. Fetched once per campaign rather than on
        # every state poll — the archive below answers the same question for
        # free, and this only adds the clips ingested from another machine.
        self._remote_clips: list[str] | None = None
        ensure_inbox(inbox)

    # ------------------------------------------------------------------ state

    def _staged(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for kind, dirname in INBOX_DIRS.items():
            folder = self.inbox / dirname
            files = []
            if folder.is_dir():
                for path in sorted(folder.iterdir()):
                    if path.is_file() and not path.name.startswith("."):
                        files.append({"name": path.name, "size": path.stat().st_size})
            out[dirname] = files
        return out

    def _sharing_campaigns(self) -> list[str]:
        """Every campaign fed by this library, the selected one included.

        Campaigns posting the same content to different networks point at one
        assets Release (``assets_release`` in their config), so a clip dropped
        in once is live in all of them. The dashboard has to say so — otherwise
        the obvious reading of a per-campaign page is that you upload three
        times.
        """
        try:
            summaries = list_campaigns(self.campaigns_dir)
        except UgcError:
            return [self.config.slug]
        shared = [
            c.slug for c in summaries
            if c.valid and c.assets_tag == self.config.assets_tag
        ]
        return shared or [self.config.slug]

    def library_scope(self) -> dict[str, Any]:
        return {
            "tag": self.config.assets_tag,
            "inbox": self.config.library_key,
            "campaigns": self._sharing_campaigns(),
        }

    # -------------------------------------------------------------- the roster

    @property
    def roster_file(self) -> Path:
        """Where this campaign's mute list lives — beside its history."""
        return roster_path(self.bank_path.parent)

    def _roster(self) -> ClipRoster:
        # Read per call rather than cached: it is a few hundred bytes, and the
        # CLI can rewrite it under a running dashboard.
        return load_roster(self.roster_file)

    def _archive_paths(self) -> dict[str, Path]:
        """Local copies of ingested clips, by Release name.

        These are what ``ingest`` moved aside after uploading, so they are the
        same bytes the randomizer will use — which is what makes an honest
        in-page preview possible without downloading from the Release.
        """
        archive = self.inbox / ARCHIVE_DIR
        if not archive.is_dir():
            return {}
        return {
            path.name: path
            for path in sorted(archive.iterdir())
            if path.is_file() and not path.name.startswith(".")
        }

    def _library_names(self, refresh: bool = False) -> list[str]:
        """Every clip the randomizer could draw from, whatever its source.

        Union of the local archive, the Release listing (once per session), and
        anything named in the roster — so a clip muted on another machine is
        still shown as muted rather than disappearing from the list.
        """
        names: set[str] = set(self._archive_paths())
        names.update(self._roster().disabled)
        if refresh:
            self._remote_clips = None
        if self._remote_clips is None:
            store = self._store()
            if store is not None:
                try:
                    self._remote_clips = store.list_assets(
                        self.config.assets_tag
                    )
                except UgcError as exc:
                    self.log.warning("clip_listing_failed", error=str(exc))
                    self._remote_clips = []
        names.update(self._remote_clips or [])
        return sorted(n for n in names if kind_of(n) is not None)

    def _uploaded_counts(self) -> dict[str, int]:
        """Clips in the assets Release *and* in rotation, by role.

        Muted clips are excluded on purpose: every number downstream of this —
        combinations, runway, the cooldown warnings — is a claim about what
        tonight's render can actually pick, and counting a muted clip would
        overstate all of them.
        """
        roster = self._roster()
        counts = {kind.value: 0 for kind in PartKind}
        for name in self._library_names():
            kind = kind_of(name)
            if kind is not None and roster.is_enabled(name):
                counts[kind.value] += 1
        return counts

    def _muted_counts(self) -> dict[str, int]:
        roster = self._roster()
        counts = {kind.value: 0 for kind in PartKind}
        for name in roster.disabled:
            kind = kind_of(name)
            if kind is not None:
                counts[kind.value] += 1
        return counts

    def select(self, slug: str) -> dict[str, Any]:
        """Switch the dashboard to another campaign.

        Rebinds the per-campaign paths and drops the cached probe, because bed
        counts belong to whichever asset library the new campaign points at.
        """
        config = load_campaign(self.campaigns_dir, slug)
        self.config = config
        self.bank_path = self.campaigns_dir / slug / "captions.txt"
        self.inbox = self.repo_root / "inbox" / config.library_key
        self._music_beds = None
        self._remote_clips = None
        ensure_inbox(self.inbox)
        self.log = self.log.bind(campaign=slug)
        return {"ok": True, "campaign": slug}

    def campaigns(self) -> dict[str, Any]:
        """Every campaign, plus which one the dashboard is showing."""
        return {
            "selected": self.config.slug,
            "campaigns": [
                {
                    "slug": c.slug, "service": c.service, "post_type": c.post_type,
                    "posts_per_day": c.posts_per_day, "dry_run": c.dry_run,
                    "timezone": c.timezone, "assets_tag": c.assets_tag,
                    "valid": c.valid, "error": c.error,
                }
                for c in list_campaigns(self.campaigns_dir)
            ],
        }

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a campaign and report what the operator must still do.

        The two steps deliberately left to a human are the credential ones:
        connecting the channel in Buffer, and setting the secrets. Everything
        that is just files happens here.
        """
        slug = str(payload.get("slug", "")).strip().lower()
        existing = [c.slug for c in list_campaigns(self.campaigns_dir)]
        problem = slug_error(slug, existing)
        if problem:
            return {"ok": False, "error": problem}

        try:
            service = Service(str(payload.get("service", "instagram")))
        except ValueError:
            return {"ok": False, "error": "unknown service"}

        try:
            created = create_campaign(
                self.campaigns_dir,
                slug,
                service,
                timezone=str(payload.get("timezone") or self.config.timezone),
                posts_per_day=int(payload.get("posts_per_day") or 12),
                start_hour=int(payload.get("start_hour") or 15),
                # Default to sharing this campaign's library: a new campaign for
                # the same brand on another network should not need the clips
                # uploaded a second time.
                assets_release=(
                    str(payload.get("assets_release"))
                    if payload.get("assets_release")
                    else self.config.assets_tag
                ),
                organization_id=(
                    self.config.buffer.organization_id
                    if str(payload.get("api_key_secret") or "BUFFER_API_KEY")
                    == self.config.buffer.api_key_secret
                    else None
                ),
                channel_id=(
                    str(payload.get("channel_id"))
                    if payload.get("channel_id") else None
                ),
                api_key_secret=str(
                    payload.get("api_key_secret") or "BUFFER_API_KEY"
                ),
                descriptions=(
                    self.bank_path.read_text(encoding="utf-8")
                    if payload.get("copy_descriptions") and self.bank_path.is_file()
                    else None
                ),
            )
        except UgcError as exc:
            return {"ok": False, "error": str(exc)}

        self.log.info("campaign_created", slug=slug, service=service.value)
        return {
            "ok": True,
            "slug": created.slug,
            "required_secrets": list(created.required_secrets),
            "files": [str(p.relative_to(self.repo_root)) for p in created.paths],
        }

    # ----------------------------------------------------------------- sample

    def sample(self) -> dict[str, Any]:
        """Render one video from the current library, and publish nothing.

        Deliberately writes to neither ``queue.json`` nor ``history.json``. A
        sample must not consume a combination: doing so would mean looking at
        your own library cost you a unique tuple of runway, and the dedupe
        record would claim a video was used that nobody ever saw.

        History is still *read*, so the sample avoids combinations already
        spent — it shows what tonight would actually produce, not a repeat.
        """
        import uuid

        from src.assets import LocalLibrary
        from src.clips import filter_library
        from src.descriptions import load_bank
        from src.models import RenderRequest
        from src.ports import SeededRng
        from src.queue import load_history
        from src.selector import Selector

        work = self.repo_root / "work" / self.config.slug
        assets = work / "assets"
        if not assets.is_dir() or not any(assets.iterdir()):
            store = self._store()
            if store is None:
                return {
                    "ok": False,
                    "error": "No clips cached locally and no GitHub credentials "
                             "to fetch them. Run `gh auth login`, or render once "
                             "from the CLI to populate work/.",
                }
            store.download_assets(self.config.assets_tag, assets)

        if not assets.is_dir() or not any(assets.iterdir()):
            # download_assets succeeding with nothing to download is normal for
            # a campaign whose Release is empty; iterating a missing directory
            # below would crash instead of saying so.
            return {
                "ok": False,
                "error": "No clips in the library yet — upload some in Assets "
                         "first.",
            }

        paths = filter_library(
            LocalLibrary.from_directory(assets), self._roster(), self.log
        )
        try:
            descriptions = load_bank(
                self.bank_path.read_text(encoding="utf-8"),
                self.config.buffer.service,
                source=str(self.bank_path),
                strategy=self.config.buffer.title_strategy,
            )
        except UgcError as exc:
            return {"ok": False, "error": f"descriptions: {exc}"}
        if not descriptions:
            return {"ok": False, "error": "no descriptions written yet"}

        renderer = FfmpegRenderer(self.config, self.log)
        durations: dict[str, float] = {}
        if self.config.composition.music_random_start:
            for track in paths.music:
                try:
                    durations[track.name] = renderer.probe(track).duration_sec
                except UgcError:
                    continue

        from src.selector import AssetLibrary

        composition = self.config.composition
        library = AssetLibrary(
            hooks=tuple(p.name for p in paths.hooks),
            bodies=tuple(p.name for p in paths.bodies),
            music=tuple(p.name for p in paths.music),
            captions=tuple(d.body for d in descriptions),
            music_durations=durations,
            music_segment_sec=(
                composition.music_segment_sec
                if composition.music_random_start else 0.0
            ),
            music_skip_intro_sec=composition.music_skip_intro_sec,
        )

        history = load_history(self.bank_path.parent / "history.json")
        # Seeded from the clock rather than fixed: two clicks in a row should
        # show two different combinations, which is the point of the button.
        rng = SeededRng(int(self.clock.now().timestamp() * 1000) % (2**32))
        selector = Selector(self.config.selection, self.clock, rng, self.log)
        try:
            outcome = selector.select_one(
                library, history, composition.bodies_per_video
            )
        except UgcError as exc:
            return {"ok": False, "error": str(exc)}

        by_name = paths.by_name()
        selection = outcome.selection
        missing = [
            n for n in (selection.hook, *selection.bodies)
            if n not in by_name
        ]
        if missing:
            return {"ok": False,
                    "error": f"library is missing {', '.join(missing)}"}
        samples = work / "samples"
        samples.mkdir(parents=True, exist_ok=True)
        # One file, reused: samples are disposable and an unbounded pile of
        # 100 MB videos in work/ is not.
        output = samples / "sample.mp4"
        try:
            renderer.render(RenderRequest(
                item_id=f"sample-{uuid.uuid4().hex[:8]}",
                hook_path=by_name[selection.hook],
                body_paths=tuple(by_name[b] for b in selection.bodies),
                music_path=by_name[selection.music] if selection.music else None,
                music_offset_sec=selection.music_offset_sec,
                output_path=output,
            ))
        except UgcError as exc:
            return {"ok": False, "error": f"render failed: {exc}"}

        titles = {d.body: d.title for d in descriptions}
        self.log.info("sample_rendered", campaign=self.config.slug)
        return {
            "ok": True,
            # Cache-busted so the player does not show the previous sample.
            "url": f"/api/sample.mp4?v={uuid.uuid4().hex[:8]}",
            "hook": selection.hook,
            "bodies": list(selection.bodies),
            "music": selection.music,
            "music_offset_sec": selection.music_offset_sec,
            "caption": selection.caption,
            "title": titles.get(selection.caption),
            "relaxation": outcome.relaxation.value,
            "size": output.stat().st_size,
        }

    def sample_file(self) -> Path | None:
        path = self.repo_root / "work" / self.config.slug / "samples" / "sample.mp4"
        return path if path.is_file() else None

    # --------------------------------------------------------------- insights

    def insights(self) -> dict[str, Any]:
        """Cross-campaign findings from data already on disk. No API calls."""
        from src.insights import CampaignFacts, build
        from src.queue import load_history

        facts: list[CampaignFacts] = []
        for summary in list_campaigns(self.campaigns_dir):
            if not summary.valid:
                continue
            directory = self.campaigns_dir / summary.slug
            try:
                config = load_campaign(self.campaigns_dir, summary.slug)
            except UgcError:
                continue

            rendered = 0
            history_path = directory / "history.json"
            if history_path.is_file():
                try:
                    rendered = len(load_history(history_path).entries)
                except UgcError:
                    rendered = 0

            metrics_path = directory / "metrics.json"
            if not metrics_path.is_file():
                continue
            try:
                history = load_metrics(metrics_path)
            except UgcError:
                continue

            # Lifetime is the right scope for a yield question: a 30-day
            # rolling window would compare all-time renders against a month of
            # posts and invent a shortfall that is really just the window.
            lifetime = [s for s in history.snapshots if s.scope is Scope.LIFETIME]
            rolling = [s for s in history.snapshots if s.scope is Scope.ROLLING]
            if not lifetime:
                continue
            latest = lifetime[-1]
            values = {m.type: m.value for m in latest.metrics}

            facts.append(CampaignFacts(
                slug=summary.slug,
                service=latest.service or config.buffer.service.value,
                rendered=rendered,
                published=values.get("postCount", 0.0),
                views=values.get("views", 0.0),
                reach=values.get("reach", 0.0),
                post_count=values.get("postCount", 0.0),
                engagement_rate=values.get("engagementRate", 0.0),
                reactions=values.get("reactions", 0.0),
                comments=values.get("comments", 0.0),
                shares=values.get("shares", 0.0),
                saves=values.get("saves", 0.0),
                snapshots=len(rolling),
                # Which metrics the network reports at all. A missing metric is
                # not a zero, and the difference changes every rate below it.
                reported=frozenset(values),
            ))

        return {
            "findings": [f.as_dict() for f in build(facts)],
            "campaigns": len(facts),
        }

    # ------------------------------------------------------------------ queue

    def queue(self) -> dict[str, Any]:
        """What is scheduled, newest slot last, with everything needed to judge it.

        The video URL is a public Release asset — the same one Buffer fetches —
        so the panel plays exactly the file that will be published, with no
        extra hosting and no proxying through this server.
        """
        from src.queue import CANCELLABLE, load_queue

        path = self.bank_path.parent / "queue.json"
        if not path.is_file():
            return {"campaign": self.config.slug, "items": [], "counts": {}}

        try:
            queue = load_queue(path)
        except UgcError as exc:
            return {"campaign": self.config.slug, "items": [], "counts": {},
                    "error": str(exc)}

        now = self.clock.now()
        counts: dict[str, int] = {}
        items = []
        for item in sorted(queue.items, key=lambda i: i.scheduled_for):
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
            items.append({
                "id": item.id,
                "scheduled_for": item.scheduled_for.astimezone(
                    self.config.zone
                ).isoformat(),
                "past_due": item.scheduled_for <= now,
                "status": item.status.value,
                "caption": item.caption,
                "title": item.title,
                "parts": item.parts,
                "video_url": item.video_url,
                "buffer_post_id": item.buffer_post_id,
                "last_error": item.last_error,
                "attempts": item.attempts,
                # Whether the button should be live, decided by the same
                # frozenset the state machine enforces — so the UI cannot offer
                # an action the model will refuse.
                "cancellable": item.status in CANCELLABLE,
            })
        return {
            "campaign": self.config.slug,
            "timezone": self.config.timezone,
            "generated_at": queue.generated_at.isoformat(),
            "items": items,
            "counts": counts,
        }

    def quota(self) -> dict[str, Any]:
        """Buffer requests spent over the rolling window, for the shared key.

        Summed across every campaign on the same key, because that is the unit
        the allowance is granted in.
        """
        from src.quota import (
            MONTHLY_ALLOWANCE,
            WINDOW_DAYS,
            load_quota,
            quota_path,
            rolling_total,
        )

        slot = self.config.buffer.api_key_secret
        sharing: list[str] = []
        ledgers = []
        for summary in list_campaigns(self.campaigns_dir):
            if not summary.valid:
                continue
            try:
                other = load_campaign(self.campaigns_dir, summary.slug)
            except UgcError:
                continue
            if other.buffer.api_key_secret != slot:
                continue
            sharing.append(other.slug)
            ledgers.append(load_quota(quota_path(self.campaigns_dir / other.slug)))

        today = self.clock.now().astimezone(self.config.zone).date()
        used = rolling_total(ledgers, today)
        recorded = any(l.days for l in ledgers)
        return {
            "slot": slot,
            "used": used,
            "allowance": MONTHLY_ALLOWANCE,
            "window_days": WINDOW_DAYS,
            "campaigns": sorted(sharing),
            # Nothing has been counted until a posting job has run since this
            # started tracking; showing 0/3000 then would read as "barely used"
            # when it means "not yet measured".
            "measured": recorded,
        }

    def pull_item(self, item_id: str) -> dict[str, Any]:
        """Stop one video going out, and tell Buffer too if it already has it.

        Two genuinely different situations behind one button:

        * not yet pushed — nothing exists remotely, so recording the decision is
          the whole job and the top-up run simply skips it;
        * already pushed — Buffer is holding it, and it has to be told, because
          a queue file saying "cancelled" does not stop Buffer publishing.

        Once a network has actually published, nothing here can help; that is
        reported plainly rather than dressed up as success.
        """
        from src.queue import cancel, load_queue, save_queue

        path = self.bank_path.parent / "queue.json"
        try:
            queue = load_queue(path)
        except UgcError as exc:
            return {"ok": False, "error": str(exc)}

        item = next((i for i in queue.items if i.id == item_id), None)
        if item is None:
            return {"ok": False, "error": "no such queued item"}

        removed_remotely = False
        warning = ""
        if item.buffer_post_id:
            key = self.buffer_key()
            if not key:
                return {
                    "ok": False,
                    "error": f"This post is already in Buffer, and removing it "
                             f"needs the {self.config.buffer.api_key_secret} key. "
                             f"Paste it in the Keys panel first — cancelling "
                             f"here alone would not stop Buffer publishing it.",
                }
            from src.publishers.buffer import BufferPublisher

            publisher = BufferPublisher(
                key, self.log,
                organization_id=self.config.buffer.organization_id,
            )
            try:
                publisher.delete_post(item.buffer_post_id)
                removed_remotely = True
            except UgcError as exc:
                # Most often: the network already published it, so Buffer no
                # longer has a post to delete. Recording the cancellation is
                # still right — it stops any retry — but the operator must know
                # the video is live.
                warning = (
                    f"Buffer would not remove it: {exc}. If it has already "
                    f"published, take it down on the network itself."
                )

        try:
            cancel(item, log=self.log)
        except UgcError as exc:
            return {"ok": False, "error": str(exc)}
        save_queue(path, queue)

        self.log.info(
            "queue_item_pulled", item_id=item_id, campaign=self.config.slug,
            from_buffer=removed_remotely,
        )
        return {
            "ok": True, "id": item_id, "from_buffer": removed_remotely,
            "warning": warning,
        }

    # ---------------------------------------------------------------- revenue

    @property
    def ledger_file(self) -> Path:
        return ledger_path(self.bank_path.parent)

    def _ledger(self, slug: str | None = None) -> RevenueLedger:
        # The selected campaign resolves through ``ledger_file`` rather than by
        # rebuilding the path from the slug: the two must not be able to drift,
        # and writing to one while reading the other loses money silently.
        if slug is None or slug == self.config.slug:
            return load_ledger(self.ledger_file)
        return load_ledger(ledger_path(self.campaigns_dir / slug))

    def _views_windows(self, slug: str) -> list[dict[str, Any]]:
        """Each rolling snapshot's window and the views inside it.

        Uses the snapshot's own window rather than its date, because a snapshot
        is a trailing aggregate: pairing 30 days of views with one week of
        revenue would understate the ratio roughly fourfold.
        """
        path = self.campaigns_dir / slug / "metrics.json"
        if not path.is_file():
            return []
        try:
            history = load_metrics(path)
        except UgcError:
            return []
        out: list[dict[str, Any]] = []
        for snap in history.snapshots:
            if snap.scope is not Scope.ROLLING:
                continue
            views = next(
                (m.value for m in snap.metrics if m.type == "views"), None
            )
            if views is None:
                continue
            out.append({
                "date": snap.date,
                "service": snap.service,
                "start": snap.window_start.date(),
                "end": snap.window_end.date(),
                "views": views,
            })
        return sorted(out, key=lambda w: w["date"])

    def revenue(self) -> dict[str, Any]:
        """The ledger, plus every ratio worth plotting against reach."""
        ledger = self._ledger()
        span = ledger.span()

        # Revenue per 1k views, one point per snapshot, revenue taken from that
        # snapshot's own window.
        rpm: list[list[Any]] = []
        paired: list[dict[str, Any]] = []
        for window in self._views_windows(self.config.slug):
            money = ledger.total_in(window["start"], window["end"])
            ratio = per_thousand(money, window["views"])
            if ratio is None:
                continue
            rpm.append([window["date"], round(ratio, 4)])
            paired.append({
                "date": window["date"],
                "views": window["views"],
                "revenue": round(money, 2),
                "rpm": round(ratio, 4),
            })

        # Every campaign's ledger, so one business posting to three networks can
        # see the whole number rather than a third of it.
        totals = []
        combined_revenue = 0.0
        combined_views = 0.0
        for summary in list_campaigns(self.campaigns_dir):
            if not summary.valid:
                continue
            other = self._ledger(summary.slug)
            windows = self._views_windows(summary.slug)
            latest = windows[-1] if windows else None
            money = other.total()
            combined_revenue += money
            if latest:
                combined_views += latest["views"]
            totals.append({
                "campaign": summary.slug,
                "service": summary.service,
                "revenue": round(money, 2),
                "views": latest["views"] if latest else None,
                "rpm": (
                    round(per_thousand(
                        other.total_in(latest["start"], latest["end"]), latest["views"]
                    ) or 0.0, 4)
                    if latest else None
                ),
            })

        currencies = sorted(ledger.currencies)
        return {
            "campaign": self.config.slug,
            "currency": currencies[0] if currencies else "USD",
            "mixed_currencies": currencies[1:],
            "entries": [
                {
                    "id": e.id,
                    "period_start": e.period_start.isoformat(),
                    "period_end": e.period_end.isoformat(),
                    "days": e.days,
                    "amount": e.amount,
                    "currency": e.currency,
                    "source": e.source,
                    "note": e.note,
                }
                for e in reversed(ledger.entries)
            ],
            "total": round(ledger.total(), 2),
            "span": [span[0].isoformat(), span[1].isoformat()] if span else None,
            "by_source": [[k, round(v, 2)] for k, v in ledger.by_source()],
            "daily": ledger.daily(),
            "rpm_series": rpm,
            "paired": paired,
            "warnings": ledger.double_counting(),
            "overall": {
                "campaigns": totals,
                "revenue": round(combined_revenue, 2),
                "rpm": (
                    round(per_thousand(combined_revenue, combined_views) or 0.0, 4)
                    if combined_views else None
                ),
            },
        }

    def add_revenue(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record one payment. Validation lives in the model, not here."""
        try:
            entry = RevenueEntry(
                period_start=str(payload.get("period_start", "")),  # type: ignore[arg-type]
                period_end=str(
                    payload.get("period_end") or payload.get("period_start") or ""
                ),  # type: ignore[arg-type]
                amount=float(payload.get("amount") or 0),
                currency=str(payload.get("currency") or "USD"),
                source=str(payload.get("source") or "manual").strip() or "manual",
                note=(str(payload.get("note")).strip() or None
                      if payload.get("note") else None),
                entered_at=self.clock.now(),
            )
        except (ValueError, TypeError) as exc:
            # Pydantic's message names the field and the reason, which is more
            # use to whoever is typing than a generic "bad input".
            first = str(exc).splitlines()
            return {"ok": False, "error": " ".join(first[-2:]).strip() or str(exc)}
        if entry.amount <= 0:
            return {"ok": False, "error": "amount must be more than zero"}

        save_ledger(self.ledger_file, self._ledger().with_entry(entry))
        self.log.info(
            "revenue_recorded", campaign=self.config.slug, source=entry.source,
            days=entry.days, currency=entry.currency,
        )
        return {"ok": True, "id": entry.id}

    def remove_revenue(self, entry_id: str) -> dict[str, Any]:
        ledger = self._ledger()
        trimmed = ledger.without(entry_id)
        if len(trimmed.entries) == len(ledger.entries):
            return {"ok": False, "error": "no such entry"}
        save_ledger(self.ledger_file, trimmed)
        self.log.info("revenue_removed", campaign=self.config.slug, id=entry_id)
        return {"ok": True}

    # ---------------------------------------------------------------- secrets

    @property
    def env_file(self) -> Path:
        return self.repo_root / ".env"

    def _required_secrets(self) -> dict[str, list[str]]:
        """Secret name -> the campaigns that need it.

        Read from the configs rather than a fixed list, so a campaign pointing
        at BUFFER_API_KEY_3 shows that slot and a campaign with its channel id
        written inline does not ask for a channel secret it never reads.
        """
        needed: dict[str, list[str]] = {}
        for summary in list_campaigns(self.campaigns_dir):
            if not summary.valid:
                continue
            try:
                config = load_campaign(self.campaigns_dir, summary.slug)
            except UgcError:
                continue
            for name in (
                config.buffer.api_key_secret,
                config.buffer.channel_id_secret,
                config.notify.webhook_secret,
            ):
                if name:
                    needed.setdefault(name, []).append(config.slug)
        return needed

    def secrets(self) -> dict[str, Any]:
        """What each campaign needs, and which of the two stores has it.

        Values are never returned — only whether one is present and its last
        four characters, which is enough to tell two keys apart and useless to
        anyone who intercepts it.
        """
        local = read_env(self.env_file)
        remote = {g.name: g.updated_at for g in list_github_secrets(self.repo_root)}
        env = os.environ

        items = []
        for name, slugs in sorted(self._required_secrets().items()):
            value = local.get(name) or env.get(name) or ""
            items.append({
                "name": name,
                "kind": "buffer" if name.startswith("BUFFER_API_KEY")
                        else "channel" if name.startswith("BUFFER_CHANNEL")
                        else "webhook",
                "campaigns": sorted(slugs),
                "local": bool(value),
                "hint": mask(value) if value else "",
                "from_environment": not local.get(name) and bool(env.get(name)),
                "github": name in remote,
                "github_updated": remote.get(name, ""),
            })
        return {
            "secrets": items,
            "env_file": str(self.env_file.relative_to(self.repo_root)),
            "github_ready": bool(remote),
        }

    def save_secret(
        self, name: str, value: str, to_github: bool = True
    ) -> dict[str, Any]:
        """Store a pasted credential locally, and optionally on the repo.

        Both stores by default, because storing only one is the thing that
        produced the confusing half-working state this panel exists to fix:
        local-only means the workflows still cannot post, and GitHub-only means
        the dashboard still cannot list channels.
        """
        check_name(name)
        if name not in self._required_secrets():
            # Refuse names no campaign asks for: a typo would otherwise write a
            # credential to a key nothing reads and report success.
            return {"ok": False, "error": f"no campaign uses a secret named {name}"}
        cleaned = clean_value(value)

        write_env_value(self.env_file, name, cleaned)
        # Make it live for this process too, so the channel list works on the
        # very next click rather than after a restart.
        os.environ[name] = cleaned
        self._channels = None

        pushed, problem = False, ""
        if to_github:
            try:
                set_github_secret(self.repo_root, name, cleaned)
                pushed = True
            except UgcError as exc:
                problem = str(exc)

        # Deliberately logs the name and never the value.
        self.log.info("secret_saved", name=name, to_github=pushed)
        return {
            "ok": True, "name": name, "local": True, "github": pushed,
            "github_error": problem,
        }

    def forget_secret(self, name: str) -> dict[str, Any]:
        """Remove the local copy only.

        The GitHub copy is what posts; deleting that from a settings panel is
        a way to silently stop a campaign, so it is not offered here.
        """
        check_name(name)
        removed = delete_env_value(self.env_file, name)
        os.environ.pop(name, None)
        self._channels = None
        self.log.info("secret_forgotten", name=name, existed=removed)
        return {"ok": True, "name": name, "removed": removed}

    def key_slots(self) -> dict[str, Any]:
        """Which Buffer accounts are reachable from this machine.

        One campaign per Buffer account means one key per account. The slots
        are fixed because the workflows must name them statically — a dynamic
        campaign list cannot discover secret names (GitHub blocks dumping the
        secrets context).
        """
        from src.config import BUFFER_KEY_SLOTS

        return {
            "slots": [
                {
                    "name": name,
                    "available": self.buffer_key(name) is not None,
                    "used_by": [
                        c.slug for c in list_campaigns(self.campaigns_dir)
                        if self._key_of(c.slug) == name
                    ],
                }
                for name in BUFFER_KEY_SLOTS
            ]
        }

    def _key_of(self, slug: str) -> str | None:
        try:
            return load_campaign(self.campaigns_dir, slug).buffer.api_key_secret
        except UgcError:
            return None

    def buffer_key(self, slot: str | None = None) -> str | None:
        """The Buffer API key, from the environment or a local .env.

        A local .env is a convenience for this tool only — it is gitignored and
        never read by the workflows, which get the key from GitHub Secrets.
        """
        name = slot or self.config.buffer.api_key_secret
        # Only fall back to the generic names when no specific slot was asked
        # for; otherwise a campaign on account 2 would silently authenticate as
        # account 1 and post to the wrong place.
        candidates = (name,) if slot else (name, "BUFFER_API_KEY", "BUFFER_ACCESS_TOKEN")
        for key in candidates:
            if os.environ.get(key):
                return os.environ[key]

        env_file = self.repo_root / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                k, _, v = line.partition("=")
                if k.strip() in candidates:
                    return v.strip().strip("'\"")
        return None

    def channels(self, refresh: bool = False, slot: str | None = None
                 ) -> dict[str, Any]:
        """Buffer channels available to connect, and which are already taken.

        Marks channels that default to reminder-based publishing: those cannot
        post unattended (SPEC §0), so offering one without saying so would set
        up a campaign that silently never publishes.
        """
        from src.campaigns import list_campaigns
        from src.publishers.buffer import BufferPublisher

        slot = slot or self.config.buffer.api_key_secret
        key = self.buffer_key(slot)
        if not key:
            return {
                "ok": False,
                "error": f"No key for {slot} available locally.",
                "hint": f"add {slot}=... to a .env file at the repo root "
                        f"(gitignored), then reopen this panel.",
                "channels": [],
            }

        cached = (self._channels or {}).get(slot) if isinstance(self._channels, dict) else None
        if cached is None or refresh:
            publisher = BufferPublisher(
                key, self.log,
                organization_id=self.config.buffer.organization_id,
            )
            query = """
            query UgcFactoryWebChannels($input: ChannelsInput!) {
              channels(input: $input) {
                id name service type isDisconnected isLocked
                metadata {
                  __typename
                  ... on InstagramMetadata { defaultToReminders }
                  ... on TiktokMetadata { defaultToReminders }
                  ... on YoutubeMetadata { defaultToReminders }
                }
              }
            }
            """
            try:
                data = publisher._gql(
                    query, {"input": {"organizationId": publisher._org_id()}}
                )
            except UgcError as exc:
                return {"ok": False, "error": str(exc), "channels": []}
            if not isinstance(self._channels, dict):
                self._channels = {}
            self._channels[slot] = list(data.get("channels") or [])
            cached = self._channels[slot]

        # Which channels a campaign already points at.
        taken: dict[str, str] = {}
        for summary in list_campaigns(self.campaigns_dir):
            try:
                cfg = load_campaign(self.campaigns_dir, summary.slug)
            except UgcError:
                continue
            if cfg.buffer.channel_id:
                taken[cfg.buffer.channel_id] = summary.slug

        out = []
        for channel in (cached or []):
            meta = channel.get("metadata") or {}
            reminders = (
                meta.get("defaultToReminders") if isinstance(meta, dict) else None
            )
            out.append({
                "id": channel["id"],
                "name": channel.get("name"),
                "service": channel.get("service"),
                "taken_by": taken.get(str(channel["id"])),
                "reminders": bool(reminders),
                "disconnected": bool(channel.get("isDisconnected")),
                "locked": bool(channel.get("isLocked")),
            })
        return {"ok": True, "channels": out}

    def charts(self) -> dict[str, Any]:
        """Every series the analytics section plots, read from disk only.

        Two sources, deliberately: metrics.json for what the networks report,
        and history.json for what this system did. The second is complete and
        free — it records every render ever — so posting volume, asset usage
        and time-of-day come from it rather than from an API window.
        """
        from collections import Counter

        from src.campaigns import list_campaigns
        from src.metrics import Scope
        from src.queue import load_history, load_queue

        series: dict[str, dict[str, list[list[Any]]]] = {}
        share: dict[str, list[dict[str, Any]]] = {}
        volume: dict[str, list[list[Any]]] = {}
        hours: dict[str, list[int]] = {}
        assets: dict[str, list[list[Any]]] = {}
        services: list[str] = []
        asset_counts: dict[str, Counter[str]] = {
            "hooks": Counter(), "bodies": Counter(), "music": Counter()
        }
        hour_counts: Counter[int] = Counter()

        for summary in list_campaigns(self.campaigns_dir):
            directory = self.campaigns_dir / summary.slug
            try:
                config = load_campaign(self.campaigns_dir, summary.slug)
            except UgcError:
                continue
            service = config.buffer.service.value
            if service not in services:
                services.append(service)

            history = load_metrics(directory / "metrics.json")
            for snapshot in history.of(Scope.ROLLING):
                for metric in snapshot.metrics:
                    if metric.type == "postCount":
                        continue
                    series.setdefault(metric.type, {}).setdefault(
                        service, []
                    ).append([snapshot.date, metric.value])

            life = history.lifetime()
            if life:
                for metric in life.metrics:
                    if metric.unit == "percentage" or metric.type == "postCount":
                        continue
                    share.setdefault(metric.type, []).append(
                        {"service": service, "value": metric.value}
                    )

            # history.json is append-only and complete — no API window to miss.
            posted = load_history(directory / "history.json")
            per_day: Counter[str] = Counter()
            for entry in posted.entries:
                # entry.timestamp is when the video was RENDERED, not when it
                # published — the nightly job stamps them all within a minute
                # of each other. Fine for volume-per-day, meaningless for
                # time-of-day, which comes from the queue's slots below.
                local = entry.timestamp.astimezone(config.zone)
                per_day[local.strftime("%Y-%m-%d")] += 1
                asset_counts["hooks"][entry.hook] += 1
                for body in entry.bodies:
                    asset_counts["bodies"][body] += 1
                if entry.music:
                    asset_counts["music"][entry.music] += 1
            volume[service] = [[d, n] for d, n in sorted(per_day.items())]

            # Publish times come from the queue, which carries the real slots.
            # History has no publish timestamp, so an all-time distribution is
            # not available — this is the schedule as it currently stands.
            for item in load_queue(directory / "queue.json").items:
                hour_counts[item.scheduled_for.astimezone(config.zone).hour] += 1

        hours["all"] = [hour_counts.get(h, 0) for h in range(24)]
        for kind, counter in asset_counts.items():
            assets[kind] = [[name, n] for name, n in counter.most_common(12)]

        # Metrics worth offering in the selector, most complete first, so the
        # default view is one every platform actually reports.
        ranked = sorted(
            series.keys(),
            key=lambda t: (-len(series[t]), -sum(len(v) for v in series[t].values())),
        )
        return {
            "services": services,
            "metrics": ranked,
            "series": series,
            "share": share,
            "volume": volume,
            "hours": hours["all"],
            "assets": assets,
        }

    def pending_changes(self) -> dict[str, Any]:
        """Campaign files changed locally but not yet on GitHub.

        The dashboard writes to disk; the workflows read from the repo. Until a
        change is pushed it has no effect on anything that actually posts, and
        that gap is invisible without saying so.
        """
        from src.vcs import GitVcs

        vcs = GitVcs(self.repo_root, self.log, push=False)
        proc = vcs._git("status", "--porcelain", "--", "campaigns", check=False)
        changed = [
            line[3:].strip()
            for line in (proc.stdout or "").splitlines()
            if line.strip()
        ]
        ahead = vcs._git(
            "rev-list", "--count", "@{upstream}..HEAD", check=False
        )
        try:
            unpushed = int((ahead.stdout or "0").strip() or 0)
        except ValueError:
            unpushed = 0
        return {"changed": changed, "unpushed_commits": unpushed}

    def publish(self, message: str = "") -> dict[str, Any]:
        """Commit and push campaign changes so the workflows can see them."""
        from src.vcs import GitVcs, VcsError

        state = self.pending_changes()
        if not state["changed"] and not state["unpushed_commits"]:
            return {"ok": True, "nothing_to_do": True}

        vcs = GitVcs(self.repo_root, self.log)
        try:
            if state["changed"]:
                vcs.commit(
                    [self.campaigns_dir],
                    message or f"dashboard: update {self.config.slug}",
                )
            else:
                # Already committed, just never pushed.
                vcs._push_with_rebase("dashboard publish")
        except VcsError as exc:
            return {"ok": False, "error": str(exc)}

        self.log.info("dashboard_published", campaign=self.config.slug)
        return {"ok": True, "pushed": state["changed"] or ["(existing commits)"]}

    def _music_bed_count(self) -> int | None:
        """How many distinct beds the uploaded music yields.

        Counting tracks instead of beds is what made the library panel report a
        75-day runway while preflight — which probes durations — reported 825.
        Returns None when the archive has no tracks to probe.
        """
        if self._music_beds is not None:
            return self._music_beds
        if not self.config.composition.music_random_start:
            return None

        roster = self._roster()
        tracks = [
            path for name, path in self._archive_paths().items()
            if kind_of(name) is PartKind.MUSIC and roster.is_enabled(name)
        ]
        if not tracks:
            return None

        renderer = FfmpegRenderer(self.config, self.log)
        durations: dict[str, float] = {}
        for track in tracks:
            try:
                durations[track.name] = renderer.probe(track).duration_sec
            except UgcError:
                continue

        from src.selector import AssetLibrary

        library = AssetLibrary(
            hooks=("h",), bodies=("b",), captions=("c",),
            music=tuple(durations),
            music_durations=durations,
            music_segment_sec=self.config.composition.music_segment_sec,
            music_skip_intro_sec=self.config.composition.music_skip_intro_sec,
        )
        self._music_beds = library.total_music_options()
        return self._music_beds

    def metrics(self) -> dict[str, Any]:
        """Cached metrics for every campaign, read from disk.

        Never calls Buffer. The cache is filled by the scheduled metrics job;
        querying live here would spend the API budget that posting needs.
        """
        campaigns_dir = self.bank_path.parent.parent
        out: list[dict[str, Any]] = []
        for directory in sorted(campaigns_dir.iterdir()):
            if not directory.is_dir() or directory.name.startswith("_"):
                continue
            history = load_metrics(directory / "metrics.json")
            latest = history.latest()
            life = history.lifetime()
            # Posts ever published, straight from the append-only history —
            # true all-time regardless of what any metrics window covers.
            try:
                from src.queue import load_history, load_queue

                ever_posted = len(load_history(directory / "history.json").entries)
            except UgcError:
                ever_posted = 0
            if latest is None:
                out.append({
                    "campaign": directory.name, "service": None,
                    "has_data": False, "metrics": [], "series": {},
                    "lifetime": None, "ever_posted": ever_posted,
                })
                continue
            out.append({
                "campaign": directory.name,
                "service": latest.service,
                "has_data": True,
                "date": latest.date,
                "updated_at": latest.metrics_updated_at,
                "post_count": latest.post_count,
                "metrics": [
                    {
                        "type": m.type, "name": m.name, "value": m.value,
                        "unit": m.unit,
                        "change": history.change(m.type, days=7),
                    }
                    for m in latest.metrics
                ],
                "series": {
                    m.type: history.series(m.type) for m in latest.metrics
                },
                "ever_posted": ever_posted,
                "lifetime": None if life is None else {
                    "since": life.window_start,
                    "post_count": life.post_count,
                    "metrics": [
                        {"type": m.type, "name": m.name, "value": m.value,
                         "unit": m.unit}
                        for m in life.metrics
                    ],
                    "series": {
                        m.type: history.series(m.type, Scope.LIFETIME)
                        for m in life.metrics
                    },
                },
            })

        # Totals across every campaign. Percentages are deliberately excluded:
        # an engagement RATE cannot be summed, and averaging rates weighted by
        # nothing would be a different lie.
        totals: dict[str, dict[str, Any]] = {}
        for card in out:
            life = card.get("lifetime")
            if not life:
                continue
            for m in life["metrics"]:
                if m["unit"] == "percentage":
                    continue
                slot = totals.setdefault(
                    m["type"], {"name": m["name"], "value": 0.0}
                )
                slot["value"] += m["value"]
        return {
            "campaigns": out,
            "overall": {
                "metrics": [
                    {"type": k, "name": v["name"], "value": v["value"]}
                    for k, v in sorted(
                        totals.items(), key=lambda kv: -kv[1]["value"]
                    )
                ],
                "ever_posted": sum(c.get("ever_posted", 0) for c in out),
            },
        }

    def state(self) -> dict[str, Any]:
        bank_text = (
            self.bank_path.read_text(encoding="utf-8")
            if self.bank_path.is_file()
            else ""
        )
        try:
            descriptions = parse_bank(bank_text)
            errors, notes = validate_bank(descriptions, self.config.buffer.service)
        except UgcError as exc:
            descriptions, errors, notes = [], [str(exc)], []

        counts = self._uploaded_counts()
        muted = self._muted_counts()
        hooks = counts["hook"]
        bodies = counts["body"]
        music = counts["music"]
        captions = len(descriptions)
        per_video = self.config.composition.bodies_per_video
        ppd = self.config.posting.posts_per_day
        beds = self._music_bed_count()
        total = combinations(
            hooks, bodies, music, captions, per_video, music_options=beds
        )

        return {
            "campaign": self.config.slug,
            "service": self.config.buffer.service.value,
            "posts_per_day": ppd,
            "dry_run": self.config.posting.dry_run,
            "staged": self._staged(),
            "library": self.library_scope(),
            "uploaded": counts,
            "muted": muted,
            "descriptions": {
                "text": bank_text,
                "count": captions,
                "errors": errors,
                "notes": notes,
            },
            "health": {
                "combinations": total,
                # How often a viewer sees the same body clip. This is the
                # number that actually bounds how varied the output looks:
                # unique tuple hashes do not make two videos built from the
                # same body clip look different to a person.
                "body_repeats_per_day": (
                    round(ppd / bodies, 1) if bodies else None
                ),
                "music_beds": beds,
                "runway_days": round(total / max(1, ppd), 1),
                "min_runway_days": self.config.selection.min_runway_days,
                "warnings": library_health(
                    hooks, bodies, music, captions, per_video, ppd,
                    self.config.selection.hook_cooldown_days,
                    self.config.selection.caption_cooldown_days,
                ),
            },
        }

    # ------------------------------------------------------------- operations

    def save_file(self, kind: PartKind, name: str, data: bytes) -> dict[str, Any]:
        target = self.inbox / INBOX_DIRS[kind] / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.log.info("web_file_staged", kind=kind.value, name=name, bytes=len(data))
        return {"ok": True, "name": name, "size": len(data)}

    def delete_file(self, kind: PartKind, name: str) -> dict[str, Any]:
        target = self.inbox / INBOX_DIRS[kind] / name
        if target.is_file():
            target.unlink()
            self.log.info("web_file_removed", kind=kind.value, name=name)
        return {"ok": True}

    # ------------------------------------------------------------------ clips

    #: Copy shown above each group in the dashboard.
    CLIP_GROUPS: tuple[tuple[PartKind, str, str], ...] = (
        (PartKind.HOOK, "Hooks", "the first 1–2s that stop the scroll"),
        (PartKind.BODY, "Bodies", "your main videos"),
        (PartKind.MUSIC, "Music", "beds, cut into segments automatically"),
    )

    def clips(self, refresh: bool = False) -> dict[str, Any]:
        """The randomizer roster: every clip, grouped, with its on/off state.

        Also carries what the current selection *costs* — combinations and
        runway — so muting a clip shows its consequence in the same view
        instead of sending someone to a different panel to find out.
        """
        roster = self._roster()
        names = self._library_names(refresh=refresh)
        local = self._archive_paths()

        groups: list[dict[str, Any]] = []
        for kind, label, sub in self.CLIP_GROUPS:
            items = []
            for name in names:
                if kind_of(name) is not kind:
                    continue
                path = local.get(name)
                items.append({
                    "name": name,
                    "enabled": roster.is_enabled(name),
                    "size": path.stat().st_size if path else None,
                    # Preview streams the local copy; a clip ingested from
                    # another machine has none, and the card says so rather
                    # than showing a broken player.
                    "preview": path is not None,
                })
            groups.append({
                "kind": kind.value,
                "label": label,
                "sub": sub,
                "clips": items,
                "enabled": sum(1 for c in items if c["enabled"]),
                "total": len(items),
            })

        counts = self._uploaded_counts()
        captions = len(self._descriptions())
        total = combinations(
            counts["hook"], counts["body"], counts["music"], captions,
            self.config.composition.bodies_per_video,
            music_options=self._music_bed_count(),
        )
        ppd = self.config.posting.posts_per_day
        # Switching a whole role off is one click away, and the render only
        # fails at 05:00 the next morning. Name it here instead.
        blocking = [
            g["label"] for g in groups
            if g["kind"] != PartKind.MUSIC.value and g["total"] and not g["enabled"]
        ]
        return {
            "groups": groups,
            # Named here rather than read from the state poll: the two
            # endpoints load independently, and the panel must not render
            # "applies to <blank>" whenever it wins the race.
            "campaign": self.config.slug,
            "library": self.library_scope(),
            "blocking": blocking,
            "muted": len(roster.disabled),
            "combinations": total,
            "runway_days": round(total / max(1, ppd), 1),
            "min_runway_days": self.config.selection.min_runway_days,
        }

    def set_clips(self, names: list[str], enabled: bool) -> dict[str, Any]:
        """Mute or unmute clips. Nothing is deleted and nothing is uploaded."""
        clean = [n for n in (_safe_name(raw) or "" for raw in names) if n]
        if not clean:
            return {"ok": False, "error": "no valid clip names given"}
        save_roster(self.roster_file, self._roster().with_(clean, enabled))
        # A muted track must stop contributing beds, and that number is cached.
        self._music_beds = None
        self.log.info(
            "clips_toggled", enabled=enabled, count=len(clean), names=clean
        )
        return {"ok": True, "changed": clean, "enabled": enabled}

    def delete_clip(self, name: str) -> dict[str, Any]:
        """Remove a clip from the Release for good, plus its local copy.

        Separate from muting on purpose, and the irreversible one of the two:
        the file is gone from the media store, and a re-upload comes back under
        the next free number rather than the old one. The dashboard asks before
        calling this; muting is what the toggle does.
        """
        store = self._store()
        if store is None:
            return {
                "ok": False,
                "error": "No GitHub credentials, so the Release copy cannot be "
                         "removed. Mute the clip instead — it has the same "
                         "effect on the randomizer.",
            }
        removed = store.delete_assets(self.config.assets_tag, [name])
        local = self._archive_paths().get(name)
        if local is not None:
            local.unlink()
        # The roster entry goes too, so a future clip cannot inherit a mute
        # from a name that was recycled.
        save_roster(self.roster_file, self._roster().with_([name], True))
        self._remote_clips = None
        self._music_beds = None
        self.log.info("clip_deleted", name=name, from_release=bool(removed))
        return {"ok": True, "name": name, "from_release": bool(removed)}

    def clip_file(self, name: str) -> Path | None:
        """Local path for an in-page preview, or None if this machine has none."""
        return self._archive_paths().get(name)

    def _descriptions(self) -> list[Description]:
        """Parsed description bank, or empty when it does not yet validate."""
        if not self.bank_path.is_file():
            return []
        try:
            return parse_bank(self.bank_path.read_text(encoding="utf-8"))
        except UgcError:
            return []

    def save_descriptions(self, text: str) -> dict[str, Any]:
        """Write the bank, reporting problems without refusing to save.

        Saving a draft that does not yet validate is normal while writing; the
        render job is where an invalid bank is actually blocking.
        """
        self.bank_path.parent.mkdir(parents=True, exist_ok=True)
        self.bank_path.write_text(text, encoding="utf-8")
        try:
            descriptions = parse_bank(text)
            errors, notes = validate_bank(descriptions, self.config.buffer.service)
        except UgcError as exc:
            return {"ok": True, "count": 0, "errors": [str(exc)], "notes": []}
        return {
            "ok": True, "count": len(descriptions), "errors": errors, "notes": notes,
        }

    def plan(self) -> dict[str, Any]:
        renderer = FfmpegRenderer(self.config, self.log)
        store = self._store()
        existing = store.list_assets(self.config.assets_tag) if store else []
        plan = build_plan(self.inbox, existing, renderer, self.log)
        return {
            "ok": True,
            "connected": store is not None,
            "items": [
                {
                    "source": c.source.name,
                    "kind": c.kind.value,
                    "target": c.target_name,
                    "verdict": c.verdict.value,
                    "notes": c.notes,
                }
                for c in plan.candidates
            ],
            "uploadable": len(plan.uploadable),
            "rejected": len(plan.rejected),
        }

    def upload(self) -> dict[str, Any]:
        store = self._store()
        if store is None:
            return {
                "ok": False,
                "error": "No GitHub credentials. Run `gh auth login`, or set "
                         "GITHUB_TOKEN and GITHUB_REPOSITORY.",
            }
        renderer = FfmpegRenderer(self.config, self.log)
        tag = self.config.assets_tag
        plan = build_plan(self.inbox, store.list_assets(tag), renderer, self.log)
        if not plan.uploadable:
            return {"ok": False, "error": "Nothing uploadable in the inbox."}

        uploaded = apply_plan(
            plan, self.inbox, store, tag, self.log,
            staging=self.repo_root / "work" / self.config.slug / "staging",
        )
        return {"ok": True, "uploaded": uploaded, "skipped": len(plan.rejected)}

    def _store(self) -> MediaStore | None:
        if self._store_factory is not None:
            return self._store_factory()
        # Local convenience: fall back to the gh CLI's token and the git remote
        # so the operator does not have to export anything to use this.
        from src.vcs import detect_repo, detect_token

        repo = os.environ.get("GITHUB_REPOSITORY") or detect_repo(self.repo_root)
        token = os.environ.get("GITHUB_TOKEN") or detect_token()
        if not repo or not token:
            return None
        return GitHubReleasesStore(repo, token, self.log, self.clock)


def make_handler(app: WebApp) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one app instance."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "ugc-factory"

        def log_message(self, format: str, *args: Any) -> None:
            # Silence the default stderr access log; the app logs structurally.
            return

        # ------------------------------------------------------------ helpers

        def _json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _query(self) -> dict[str, list[str]]:
            return parse_qs(urlparse(self.path).query)

        def _serve_clip(self, raw_name: str) -> None:
            """Stream a local clip so the dashboard can show what it is.

            Honours Range because <video> asks for one when the user scrubs;
            answering 200 to a range request makes seeking silently fail in
            Safari. The name goes through the same sanitiser as uploads, and
            the path is then looked up in a dictionary of real files rather
            than joined — so nothing outside the archive is reachable.
            """
            name = _safe_name(raw_name)
            path = app.clip_file(name) if name else None
            if path is None or not path.is_file():
                self._json({"error": "no local copy of that clip"}, 404)
                return
            self._serve_path(path)

        def _serve_path(self, path: Path | None) -> None:
            """Stream a file the app has already resolved to a real path.

            Takes a path rather than a name on purpose: resolution — and the
            sanitising that goes with it — belongs to whichever caller knows
            what it is looking up, so nothing here joins user input onto a
            directory.
            """
            if path is None or not path.is_file():
                self._json({"error": "not found"}, 404)
                return

            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            start, end = 0, size - 1
            status = 200
            match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            if match and size:
                if match.group(1):
                    start = min(int(match.group(1)), size - 1)
                    if match.group(2):
                        end = min(int(match.group(2)), size - 1)
                else:  # suffix range: the last N bytes
                    start = max(0, size - int(match.group(2) or 0))
                status = 206

            length = max(0, end - start + 1)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(1024 * 256, remaining))
                    if not chunk:
                        break
                    # A closed player socket is normal (the user navigated
                    # away); it is not worth a traceback in the log.
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    remaining -= len(chunk)

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD_BYTES:
                raise ValueError(f"upload of {length} bytes is too large")
            return self.rfile.read(length) if length else b""

        # ------------------------------------------------------------- routes

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            route = urlparse(self.path).path
            if route == "/":
                self._html(PAGE)
            elif route == "/api/state":
                self._json(app.state())
            elif route == "/api/campaigns":
                self._json(app.campaigns())
            elif route == "/api/channels":
                query = self._query()
                slots = query.get("slot") or []
                self._json(app.channels(
                    refresh="refresh" in query,
                    slot=slots[0] if slots else None,
                ))
            elif route == "/api/queue":
                self._json(app.queue())
            elif route == "/api/quota":
                self._json(app.quota())
            elif route == "/api/insights":
                self._json(app.insights())
            elif route == "/api/sample.mp4":
                self._serve_path(app.sample_file())
            elif route == "/api/revenue":
                self._json(app.revenue())
            elif route == "/api/secrets":
                self._json(app.secrets())
            elif route == "/api/keys":
                self._json(app.key_slots())
            elif route == "/api/charts":
                self._json(app.charts())
            elif route == "/api/pending":
                self._json(app.pending_changes())
            elif route == "/api/metrics":
                self._json(app.metrics())
            elif route == "/api/clips":
                self._json(app.clips(refresh="refresh" in self._query()))
            elif route == "/api/clip":
                self._serve_clip((self._query().get("name") or [""])[0])
            elif route == "/api/plan":
                try:
                    self._json(app.plan())
                except UgcError as exc:
                    self._json({"ok": False, "error": str(exc)}, 200)
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            try:
                if route == "/api/upload":
                    query = self._query()
                    kind = _kind_from((query.get("kind") or [""])[0])
                    name = _safe_name((query.get("name") or [""])[0])
                    if kind is None or name is None:
                        self._json({"ok": False, "error": "bad kind or filename"}, 400)
                        return
                    self._json(app.save_file(kind, name, self._body()))

                elif route == "/api/descriptions":
                    payload = json.loads(self._body() or b"{}")
                    self._json(app.save_descriptions(str(payload.get("text", ""))))

                elif route == "/api/select":
                    payload = json.loads(self._body() or b"{}")
                    self._json(app.select(str(payload.get("slug", ""))))

                elif route == "/api/campaigns":
                    self._json(app.create(json.loads(self._body() or b"{}")))

                elif route == "/api/publish":
                    payload = json.loads(self._body() or b"{}")
                    self._json(app.publish(str(payload.get("message", ""))))

                elif route == "/api/sample":
                    self._json(app.sample())

                elif route == "/api/queue/pull":
                    payload = json.loads(self._body() or b"{}")
                    self._json(app.pull_item(str(payload.get("id", ""))))

                elif route == "/api/revenue":
                    self._json(app.add_revenue(json.loads(self._body() or b"{}")))

                elif route == "/api/secrets":
                    payload = json.loads(self._body() or b"{}")
                    self._json(app.save_secret(
                        str(payload.get("name", "")),
                        str(payload.get("value", "")),
                        to_github=bool(payload.get("to_github", True)),
                    ))

                elif route == "/api/clips":
                    payload = json.loads(self._body() or b"{}")
                    names = payload.get("names") or []
                    if not isinstance(names, list):
                        self._json({"ok": False, "error": "names must be a list"}, 400)
                        return
                    self._json(app.set_clips(
                        [str(n) for n in names], bool(payload.get("enabled"))
                    ))

                elif route == "/api/ingest":
                    self._json(app.upload())

                else:
                    self._json({"error": "not found"}, 404)
            except UgcError as exc:
                self._json({"ok": False, "error": str(exc)}, 200)
            except (ValueError, OSError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)

        def do_DELETE(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route == "/api/revenue":
                self._json(app.remove_revenue(
                    (self._query().get("id") or [""])[0]
                ))
                return
            if route == "/api/secrets":
                try:
                    self._json(app.forget_secret(
                        (self._query().get("name") or [""])[0]
                    ))
                except UgcError as exc:
                    self._json({"ok": False, "error": str(exc)}, 200)
                return
            if route == "/api/clips":
                name = _safe_name((self._query().get("name") or [""])[0])
                if name is None:
                    self._json({"ok": False, "error": "bad filename"}, 400)
                    return
                try:
                    self._json(app.delete_clip(name))
                except UgcError as exc:
                    self._json({"ok": False, "error": str(exc)}, 200)
                return
            if route != "/api/inbox":
                self._json({"error": "not found"}, 404)
                return
            query = self._query()
            kind = _kind_from((query.get("kind") or [""])[0])
            name = _safe_name((query.get("name") or [""])[0])
            if kind is None or name is None:
                self._json({"ok": False, "error": "bad kind or filename"}, 400)
                return
            self._json(app.delete_file(kind, name))

    return Handler


def serve(app: WebApp, port: int, *, open_browser: bool = True) -> None:
    """Run the local server until interrupted."""
    # 127.0.0.1, never 0.0.0.0: this writes files and holds the operator's
    # GitHub token, and has no authentication of its own.
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{port}"
    print(f"\n  ugc-factory · {app.config.slug}")
    print(f"  {url}\n")
    print("  Drop clips into the three zones, write descriptions, hit Upload.")
    print("  Ctrl-C to stop.\n")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped\n")
    finally:
        server.server_close()


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ugc-factory</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* ── Palette ────────────────────────────────────────────────────────────
     Warm charcoal + terracotta. Deliberately not the default SaaS blue on
     white: the neutrals carry a warm cast so the single saturated accent
     reads as intentional rather than decorative. Mint marks growth, rose
     marks loss — never the accent, which is reserved for actions.          */
  /* Every foreground/background pair here clears WCAG AA (4.5:1) for normal
     text — including the 11px dim labels and the button text, which is 13px
     semibold and therefore does NOT qualify for the 3:1 large-text
     allowance. Values were solved for, not eyeballed; nudging them lighter
     will quietly drop below the line. */
  :root {
    --bg:#100f0e; --panel:#191715; --panel-2:#201d1b;
    --line:#2b2724; --line-2:#3a3531;
    --ink:#f4efe9; --ink-2:#b3a99f; --ink-3:#897f76;
    --accent:#ce491f; --accent-ink:#fff;
    --up:#5fce9f; --down:#e2647a; --warn:#e0a44a;
    --radius:14px; --radius-sm:9px;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg:#faf7f4; --panel:#fff; --panel-2:#f6f2ee;
      --line:#e8e0d8; --line-2:#d9cfc4;
      --ink:#1b1815; --ink-2:#6b625a; --ink-3:#7f746a;
      --accent:#c9502a; --accent-ink:#fff;
      --up:#1e855f; --down:#c2374f; --warn:#9a6a12;
      --shadow:0 1px 2px rgba(60,40,25,.06), 0 10px 30px -18px rgba(60,40,25,.35);
    }
  }
  :root[data-theme="light"] {
    --bg:#faf7f4; --panel:#fff; --panel-2:#f6f2ee;
    --line:#e8e0d8; --line-2:#d9cfc4;
    --ink:#1b1815; --ink-2:#6b625a; --ink-3:#7f746a;
    --accent:#c9502a; --up:#1e855f; --down:#c2374f; --warn:#9a6a12;
  }
  :root[data-theme="dark"] {
    --bg:#100f0e; --panel:#191715; --panel-2:#201d1b;
    --line:#2b2724; --line-2:#3a3531;
    --ink:#f4efe9; --ink-2:#b3a99f; --ink-3:#897f76;
    --accent:#ce491f; --up:#5fce9f; --down:#e2647a; --warn:#e0a44a;
  }

  /* ── Depth layer ────────────────────────────────────────────────────────
     Every gradient is derived from the palette above with color-mix rather
     than hand-picked per theme, so light and dark stay in step and there is
     one place to change the character of the whole page.

     The rule they all obey: gradients carry *depth*, never meaning, and no
     surface holding text varies by more than a few percent of luminance.
     Contrast was solved for above and a decorative wash must not spend it. */
  :root {
    /* Accent fill for actions. It may only ever go DARKER than --accent.
       The accent was solved to land at exactly 4.50:1 against white, which
       is the floor for the 13px semibold text on these buttons — so any
       stop lighter than it fails AA. A first attempt here brightened the
       near stop by 14% toward peach and took the button to 4.00:1, which
       looks like nothing and is a real regression. Darkening is free:
       white text only gains contrast. */
    --grad-accent: linear-gradient(135deg,
      var(--accent) 0%,
      color-mix(in srgb, var(--accent) 93%, #000) 45%,
      color-mix(in srgb, var(--accent) 84%, #000) 100%);
    /* Card surfaces: a few percent of ink at the top, which reads as a light
       source above the page rather than as a colour. */
    --grad-panel: linear-gradient(180deg,
      color-mix(in srgb, var(--panel) 96%, var(--ink)) 0%,
      var(--panel) 62%);
    --grad-sunk: linear-gradient(180deg,
      var(--panel-2) 0%,
      color-mix(in srgb, var(--panel-2) 96%, var(--bg)) 100%);
    /* The hairline that sells the light source — brighter than the border,
       one pixel, top edge only. */
    --edge: inset 0 1px 0 color-mix(in srgb, var(--ink) 7%, transparent);
    --glow: 0 0 0 1px color-mix(in srgb, var(--accent) 26%, transparent),
            0 8px 30px -10px color-mix(in srgb, var(--accent) 40%, transparent);
    --grad-up: linear-gradient(90deg,
      color-mix(in srgb, var(--up) 78%, var(--accent)) 0%, var(--up) 100%);
  }

  /* Motion is decoration here: a card lifting on hover, the toggle knob
     sliding, the quota bar easing to its width. None of it carries meaning,
     so for anyone who has asked their system to reduce motion it can all go.
     Colour and shadow still change — those are state, not movement. */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      transition-duration:.01ms !important;
      animation-duration:.01ms !important;
      animation-iteration-count:1 !important;
      scroll-behavior:auto !important;
    }
    /* The lifts would otherwise still jump, just instantly. */
    .zone.over, .card:hover, button:active { transform:none !important; }
  }

  * { box-sizing:border-box; }
  html { -webkit-text-size-adjust:100%; }
  body {
    margin:0; background:var(--bg); color:var(--ink);
    font-family:"Instrument Sans", ui-sans-serif, -apple-system, sans-serif;
    font-size:15px; line-height:1.5;
    -webkit-font-smoothing:antialiased;
    /* Faint grain keeps the large flat panels from looking plastic. */
    background-image:
      radial-gradient(1200px 600px at 12% -8%, color-mix(in srgb,var(--accent) 7%,transparent), transparent 60%),
      radial-gradient(900px 500px at 92% 0%, color-mix(in srgb,var(--up) 5%,transparent), transparent 55%);
    background-attachment:fixed;
  }
  .num { font-family:"IBM Plex Mono", ui-monospace, monospace; font-variant-numeric:tabular-nums; }

  /* ── Shell ─────────────────────────────────────────────────────────── */
  header {
    position:sticky; top:0; z-index:20;
    background:color-mix(in srgb,var(--bg) 88%, transparent);
    backdrop-filter:blur(12px);
    border-bottom:1px solid transparent;
    border-image:linear-gradient(90deg,
      color-mix(in srgb,var(--accent) 55%,transparent) 0%,
      var(--line) 38%, var(--line) 100%) 1;
    padding:0 28px; height:60px;
    display:flex; align-items:center; gap:14px;
  }
  .brand {
    font-size:14px; font-weight:700; letter-spacing:-.02em;
    display:flex; align-items:center; gap:9px; margin-right:4px;
  }
  .dot {
    width:9px; height:9px; border-radius:50%;
    background:radial-gradient(circle at 30% 30%,
      color-mix(in srgb,var(--accent) 70%,#fff) 0%, var(--accent) 70%);
    box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent),
               0 0 14px color-mix(in srgb,var(--accent) 55%,transparent);
  }
  main { padding:28px; max-width:1220px; margin:0 auto 80px; }
  section { margin-top:34px; }
  section:first-of-type { margin-top:4px; }
  h2 {
    font-size:12px; font-weight:600; letter-spacing:.09em; text-transform:uppercase;
    color:var(--ink-3); margin:0 0 14px;
    display:flex; align-items:baseline; gap:10px;
  }
  h2 small { font-size:12px; letter-spacing:0; text-transform:none;
             font-weight:400; color:var(--ink-3); }

  /* ── Controls ──────────────────────────────────────────────────────── */
  select, input[type=text], input[type=number], textarea {
    background:var(--panel); color:var(--ink);
    border:1px solid var(--line-2); border-radius:var(--radius-sm);
    padding:8px 11px; font:inherit; font-size:14px;
    transition:border-color .15s, box-shadow .15s;
  }
  select:focus, input:focus, textarea:focus {
    outline:none; border-color:var(--accent);
    box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 18%,transparent);
  }
  #switcher { font-weight:600; padding-right:26px; }
  button {
    font:inherit; font-size:13px; font-weight:600; cursor:pointer;
    border-radius:var(--radius-sm); padding:8px 15px;
    border:1px solid transparent; background:var(--grad-accent);
    color:var(--accent-ink); box-shadow:var(--edge);
    transition:transform .12s cubic-bezier(.2,.8,.3,1), filter .15s,
               box-shadow .2s ease;
  }
  button:hover { filter:brightness(1.07); box-shadow:var(--glow), var(--edge); }
  button:active { transform:translateY(1px); }
  button:disabled { opacity:.45; cursor:default; transform:none; filter:none; }
  button.ghost {
    background:transparent; color:var(--ink); border-color:var(--line-2);
    box-shadow:none;
  }
  button.ghost:hover {
    background:var(--grad-sunk); filter:none;
    border-color:color-mix(in srgb,var(--accent) 45%,var(--line-2));
    box-shadow:none;
  }
  button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .spacer { flex:1; }

  .pill {
    font-size:11px; font-weight:500; color:var(--ink-2);
    border:1px solid var(--line); border-radius:999px; padding:3px 10px;
    white-space:nowrap;
  }
  .pill.live { color:var(--up); border-color:color-mix(in srgb,var(--up) 40%,transparent);
               background:color-mix(in srgb,var(--up) 10%,transparent); }
  .pill.paused { color:var(--warn); border-color:color-mix(in srgb,var(--warn) 40%,transparent);
                 background:color-mix(in srgb,var(--warn) 10%,transparent); }

  /* ── Campaign switcher ─────────────────────────────────────────────────
     A native <select> was the wrong control here: macOS drops the popup
     with the *current* item under the cursor, so the campaign you are on
     is hidden behind the button and only the others look selectable. This
     lists every campaign with the one you are on marked.               */
  .switch { position:relative; }
  .switch-btn {
    background:var(--grad-panel); color:var(--ink); border:1px solid var(--line-2);
    font-weight:650; font-size:14px; padding:7px 12px;
    display:flex; align-items:center; gap:8px;
  }
  .switch-btn:hover { background:var(--panel-2); filter:none; }
  .switch-btn .chev { color:var(--ink-3); font-size:10px; }
  .switch-menu {
    position:absolute; top:calc(100% + 6px); left:0; z-index:40;
    min-width:270px; padding:5px;
    background:var(--grad-panel); border:1px solid var(--line-2);
    border-radius:var(--radius); box-shadow:var(--shadow), var(--edge);
  }
  .switch-menu[hidden] { display:none; }
  .sw-item {
    display:flex; align-items:center; gap:10px; width:100%;
    padding:9px 10px; border-radius:var(--radius-sm);
    background:transparent; border:none; color:var(--ink);
    font-size:13px; font-weight:500; text-align:left;
  }
  .sw-item:hover { background:var(--panel-2); filter:none; }
  .sw-item[aria-selected="true"] { background:var(--panel-2); }
  .sw-item .tick { color:var(--accent); width:12px; flex:none; font-size:11px; }
  .sw-item .slug { flex:1; font-weight:600; }
  .sw-item .meta { font-size:11px; color:var(--ink-3); white-space:nowrap; }
  .sw-item.broken .slug { color:var(--down); }
  .sw-new {
    border-top:1px solid var(--line); margin-top:5px; padding-top:5px;
  }
  .sw-new .sw-item { color:var(--accent); font-weight:600; }

  /* ── Cards ─────────────────────────────────────────────────────────── */
  .card {
    background:var(--grad-panel); border:1px solid var(--line);
    border-radius:var(--radius); box-shadow:var(--shadow), var(--edge);
    transition:box-shadow .22s ease, border-color .22s ease;
    /* Clips the metric grid's trailing cell borders at the rounded edge. */
    overflow:hidden;
  }
  /* Platform cards sit in a grid and are stretched to the tallest, so the
     footer is pushed down rather than stranded mid-card when a network
     reports fewer metrics than its neighbours. */
  .grid .card { display:flex; flex-direction:column; }
  .grid .metrics { flex:1; align-content:start; }
  .grid .foot { margin-top:auto; }
  .pad { padding:20px 22px; }

  /* Hero stat strip — the one place with real typographic scale. */
  .hero { display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr)); }
  .hero .stat { padding:18px 22px; border-right:1px solid var(--line); }
  .hero .stat:last-child { border-right:none; }
  @media (max-width:900px){ .hero .stat { border-right:none; border-bottom:1px solid var(--line); } }
  .stat .v {
    font-size:29px; font-weight:600; letter-spacing:-.035em; line-height:1.1;
  }
  .stat .k {
    font-size:11px; color:var(--ink-3); margin-top:5px;
    letter-spacing:.03em;
  }
  .stat.lead .v {
    background:var(--grad-accent);
    -webkit-background-clip:text; background-clip:text;
    -webkit-text-fill-color:transparent; color:var(--accent);
  }
  /* Printing and forced-colours both lose background-clip, which would leave
     the number invisible. Give it back a solid colour there. */
  @media (forced-colors: active), print {
    .stat.lead .v { -webkit-text-fill-color:currentColor; color:var(--accent); }
  }
  .foot {
    padding:12px 22px; border-top:1px solid var(--line);
    font-size:12px; color:var(--ink-3);
  }

  /* Platform grid */
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); gap:16px; }
  .plat-head {
    display:flex; align-items:center; gap:10px;
    padding:16px 20px; border-bottom:1px solid var(--line);
  }
  .plat-name { font-size:14px; font-weight:650; letter-spacing:-.01em; text-transform:capitalize; }
  .plat-sub { font-size:11px; color:var(--ink-3); }
  .metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(96px,1fr)); }
  .m { padding:14px 20px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }
  .m .v { font-size:18px; font-weight:600; letter-spacing:-.02em; display:flex; align-items:baseline; gap:6px; }
  .m .k { font-size:11px; color:var(--ink-3); margin-top:2px; }
  .d { font-size:11px; font-weight:600; }
  .up { color:var(--up); } .down { color:var(--down); } .flat { color:var(--ink-3); }
  .spark { display:block; margin-top:8px; opacity:.9; }

  /* ── Drop zones ────────────────────────────────────────────────────── */
  .zones { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
  @media (max-width:860px){ .zones { grid-template-columns:1fr; } }
  .zone {
    background:var(--panel); border:1.5px dashed var(--line-2);
    border-radius:var(--radius); padding:18px 20px; min-height:184px;
    cursor:pointer; transition:border-color .16s, background .16s, transform .16s;
  }
  .zone:hover { border-color:var(--ink-3); }
  .zone.over {
    border-color:var(--accent); border-style:solid;
    background:color-mix(in srgb,var(--accent) 7%,var(--panel));
    transform:translateY(-2px);
  }
  .zone h3 { margin:0; font-size:13px; font-weight:650; letter-spacing:-.01em; }
  .zone .sub { font-size:11px; color:var(--ink-3); margin:3px 0 13px; }
  .files { list-style:none; margin:0; padding:0; font-size:12px; }
  .files li {
    display:flex; align-items:center; gap:9px; padding:6px 0;
    border-top:1px solid var(--line);
  }
  .files .nm { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .files .sz { color:var(--ink-3); font-size:11px; }
  .files button {
    background:none; border:none; color:var(--ink-3); padding:0 2px;
    font-size:15px; line-height:1;
  }
  .files button:hover { color:var(--down); filter:none; }
  .empty { color:var(--ink-3); font-style:italic; font-size:12px; }

  /* ── Randomizer ────────────────────────────────────────────────────────
     One card per clip, because a filename like hook_04.mov tells nobody
     which clip it is. The thumbnail is the identifier; the switch is the
     only control that matters, so it is the only one always visible.     */
  .mixhead {
    display:flex; align-items:center; gap:12px; margin:0 0 11px;
  }
  .mixhead .t { font-size:13px; font-weight:650; letter-spacing:-.01em; }
  .mixhead .n {
    font-size:11px; color:var(--ink-3); font-variant-numeric:tabular-nums;
  }
  .mixgroup { margin-bottom:26px; }
  .mixgroup:last-child { margin-bottom:0; }
  .mixgrid {
    display:grid; grid-template-columns:repeat(auto-fill,minmax(132px,1fr));
    gap:13px;
  }
  .clip {
    background:var(--panel); border:1px solid var(--line);
    border-radius:var(--radius); overflow:hidden; position:relative;
    transition:border-color .16s, opacity .18s, transform .16s;
  }
  .clip:hover { border-color:var(--line-2); }
  /* Muted clips stay in place and stay legible — they are coming back. A
     removed-looking card would suggest the file is gone, which it is not. */
  .clip.off { opacity:.44; }
  .clip.off:hover { opacity:.7; }
  .clip .thumb {
    position:relative; aspect-ratio:9/16; background:var(--panel-2);
    display:flex; align-items:center; justify-content:center; cursor:pointer;
  }
  .clip .thumb video { width:100%; height:100%; object-fit:cover; display:block; }
  .clip .thumb:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
  .clip.off .thumb video { filter:grayscale(1); }
  .clip .glyph { font-size:26px; opacity:.5; }
  .clip .nolocal {
    font-size:10.5px; color:var(--ink-3); text-align:center; padding:0 10px;
    line-height:1.45;
  }
  .clip .play {
    position:absolute; inset:0; display:flex; align-items:center;
    justify-content:center; opacity:0; transition:opacity .16s;
    background:color-mix(in srgb,#000 34%,transparent); color:#fff;
    font-size:20px; pointer-events:none;
  }
  .clip .thumb:hover .play { opacity:1; }
  .clip .bar {
    display:flex; align-items:center; gap:8px; padding:9px 10px;
    border-top:1px solid var(--line);
  }
  .clip .nm {
    flex:1; font-size:11.5px; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; font-family:"IBM Plex Mono", monospace;
  }
  .clip .sz {
    position:absolute; top:7px; left:7px; font-size:10px; color:#fff;
    background:color-mix(in srgb,#000 55%,transparent); padding:2px 6px;
    border-radius:999px; font-variant-numeric:tabular-nums;
  }
  .clip .kill {
    position:absolute; top:6px; right:6px; opacity:0; transition:opacity .14s;
    background:color-mix(in srgb,#000 55%,transparent); color:#fff;
    border:none; border-radius:50%; width:22px; height:22px; padding:0;
    font-size:14px; line-height:1;
  }
  .clip:hover .kill, .clip .kill:focus-visible { opacity:1; }
  .clip .kill:hover { background:var(--down); filter:none; }

  /* Switch: the whole feature in one control, so it gets a real one.
     Named .tgl, not .sw — the charts already own .sw for legend swatches. */
  .tgl {
    position:relative; flex:none; width:32px; height:18px; padding:0;
    border:none; border-radius:999px; background:var(--line-2);
    transition:background .16s;
  }
  .tgl::after {
    content:""; position:absolute; top:2px; left:2px; width:14px; height:14px;
    border-radius:50%; background:var(--ink-2);
    transition:transform .16s cubic-bezier(.2,.8,.3,1), background .16s;
  }
  .tgl[aria-checked="true"] {
    background:var(--grad-accent);
    box-shadow:0 0 10px -2px color-mix(in srgb,var(--accent) 60%,transparent);
  }
  .tgl[aria-checked="true"]::after { transform:translateX(14px); background:#fff; }
  .tgl:hover { filter:none; }
  .tgl:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }

  /* One clip library can feed several campaigns; this is where that is said. */
  .shared {
    display:flex; align-items:center; gap:9px; flex-wrap:wrap;
    font-size:12.5px; color:var(--ink-2); margin:0 0 13px;
  }
  .shared b { color:var(--ink); font-weight:600; }
  .shared .pill { font-family:"IBM Plex Mono", monospace; font-size:10.5px; }

  /* A sample render, shown at a size you can actually judge a hook by. */
  .sample { display:flex; gap:18px; margin-top:14px; flex-wrap:wrap; }
  .sample video {
    width:200px; aspect-ratio:9/16; border-radius:8px; background:#000;
    border:1px solid var(--line-2); flex:none;
  }
  .sample .smeta { flex:1; min-width:220px; font-size:12.5px; line-height:1.6; }
  .sample .smeta b { font-size:11px; letter-spacing:.06em; text-transform:uppercase;
                     color:var(--ink-3); display:block; margin-bottom:3px; }
  .sample .scap {
    white-space:pre-wrap; margin-top:11px; padding-top:11px;
    border-top:1px solid var(--line); color:var(--ink-2);
  }
  .sample .sparts { font-family:"IBM Plex Mono", monospace; font-size:11.5px; }

  /* ── Findings ──────────────────────────────────────────────────────────
     Severity is carried by a stripe as well as by words, so the one that
     matters is visible before anything is read.                          */
  .find { border-left:3px solid var(--line-2); position:relative; overflow:hidden; }
  /* The severity stripe fades out down the card instead of ruling a hard bar
     the full height of a long table. */
  .find::before {
    content:""; position:absolute; inset:0 auto 0 -3px; width:3px;
    background:linear-gradient(180deg, var(--stripe) 0%,
               color-mix(in srgb, var(--stripe) 15%, transparent) 100%);
  }
  /* A custom property, not `color` — setting the text colour on the card
     would tint every word inside it, not just the stripe. */
  .find.critical { --stripe:var(--down); }
  .find.warn     { --stripe:var(--warn); }
  .find.info     { --stripe:var(--accent); }
  .find + .find { margin-top:14px; }
  .find.critical { border-left-color:var(--down); }
  .find.warn     { border-left-color:var(--warn); }
  .find.info     { border-left-color:var(--accent); }
  .find .fhead { padding:16px 20px 0; }
  .find h3 {
    margin:0 0 7px; font-size:16px; font-weight:650; letter-spacing:-.015em;
    line-height:1.3;
  }
  .find.critical h3 { color:var(--down); }
  .find .fdetail { font-size:13px; line-height:1.6; color:var(--ink-2); margin:0; }
  .find table {
    width:100%; border-collapse:collapse; font-size:12.5px; margin-top:14px;
  }
  .find th {
    text-align:left; font-size:10px; letter-spacing:.07em; text-transform:uppercase;
    color:var(--ink-3); font-weight:600; padding:0 16px 7px;
    border-bottom:1px solid var(--line);
  }
  .find th:first-child, .find td:first-child { padding-left:20px; }
  .find td {
    padding:8px 16px; border-bottom:1px solid var(--line); vertical-align:top;
  }
  .find tr:last-child td { border-bottom:none; }
  .find td.n { font-variant-numeric:tabular-nums; font-family:"IBM Plex Mono",monospace; }
  .find.limits td:last-child { color:var(--ink-3); font-size:12px; }
  .fscroll { overflow-x:auto; }

  /* ── Queue ─────────────────────────────────────────────────────────────
     Scanned, not read: the slot time leads, state is a colour as well as a
     word, and the video is right there so "is this any good" is answerable
     without leaving the row.                                            */
  .qrow {
    display:grid; grid-template-columns:74px 62px 1fr auto;
    gap:14px; align-items:start;
    padding:13px 18px; border-bottom:1px solid var(--line);
  }
  .qrow:last-child { border-bottom:none; }
  .qrow.done { opacity:.5; }
  @media (max-width:720px){
    .qrow { grid-template-columns:62px 1fr; }
    .qrow .qvid { display:none; }
  }
  .qtime {
    font-family:"IBM Plex Mono", monospace; font-size:12.5px; font-weight:500;
    font-variant-numeric:tabular-nums; padding-top:2px;
  }
  .qtime .d { display:block; font-size:10.5px; color:var(--ink-3); margin-top:2px; }
  .qvid {
    width:62px; aspect-ratio:9/16; border-radius:5px; overflow:hidden;
    background:var(--panel-2); cursor:pointer; border:1px solid var(--line);
  }
  .qvid video { width:100%; height:100%; object-fit:cover; display:block; }
  .qcap { font-size:12.5px; line-height:1.5; }
  .qcap .parts {
    font-family:"IBM Plex Mono", monospace; font-size:10.5px; color:var(--ink-3);
    margin-top:5px; display:block;
  }
  .qstate {
    font-size:10px; font-weight:600; letter-spacing:.07em; text-transform:uppercase;
    padding:3px 8px; border-radius:3px; white-space:nowrap;
  }
  .qstate.pending   { background:color-mix(in srgb,var(--accent) 15%,transparent); color:var(--accent); }
  .qstate.pushed    { background:color-mix(in srgb,var(--up) 15%,transparent); color:var(--up); }
  .qstate.claimed   { background:color-mix(in srgb,var(--warn) 15%,transparent); color:var(--warn); }
  .qstate.failed    { background:color-mix(in srgb,var(--down) 15%,transparent); color:var(--down); }
  .qstate.cancelled { background:var(--panel-2); color:var(--ink-3); }
  .qact { display:flex; align-items:center; gap:9px; }

  /* Buffer's allowance, spent. A bar because "2,790 of 3,000" only lands
     once you can see how little is left. */
  .quota { display:flex; align-items:center; gap:14px; padding:14px 18px; }
  .quota .qfig {
    font-size:15px; font-weight:600; font-variant-numeric:tabular-nums;
    white-space:nowrap;
  }
  .quota .qbar {
    flex:1; height:8px; border-radius:99px; background:var(--panel-2);
    overflow:hidden; min-width:90px;
  }
  .quota .qbar i {
    display:block; height:100%; background:var(--grad-up);
    transition:width .5s cubic-bezier(.2,.8,.3,1);
  }
  .quota.warn .qbar i { background:linear-gradient(90deg,
    color-mix(in srgb,var(--warn) 75%,var(--up)) 0%, var(--warn) 100%); }
  .quota.over .qbar i { background:linear-gradient(90deg,
    var(--warn) 0%, var(--down) 100%); }
  .quota .qsub { font-size:11.5px; color:var(--ink-3); white-space:nowrap; }

  /* ── Revenue ───────────────────────────────────────────────────────── */
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:900px){ .grid2 { grid-template-columns:1fr; } }
  .ledger { width:100%; border-collapse:collapse; margin-top:14px; font-size:12.5px; }
  .ledger th {
    text-align:left; font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;
    color:var(--ink-3); font-weight:600; padding:0 10px 7px 0;
  }
  .ledger td { padding:7px 10px 7px 0; border-top:1px solid var(--line); }
  .ledger td.num, .ledger th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .ledger .src {
    font-size:11px; color:var(--ink-2); border:1px solid var(--line-2);
    border-radius:999px; padding:2px 9px; white-space:nowrap;
  }
  .ledger button {
    background:none; border:none; color:var(--ink-3); padding:0 2px; font-size:15px;
  }
  .ledger button:hover { color:var(--down); filter:none; }

  /* ── Keys ──────────────────────────────────────────────────────────────
     Two stores per secret and no way to read either back, so the row is
     mostly status: who needs it, and where it currently exists.          */
  .sec { border-bottom:1px solid var(--line); padding:15px 20px; }
  .sec:last-child { border-bottom:none; }
  .sec-top { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .sec-name {
    font-family:"IBM Plex Mono", monospace; font-size:12.5px; font-weight:500;
  }
  .sec-for { font-size:11px; color:var(--ink-3); }
  .sec-row { display:flex; gap:9px; margin-top:11px; flex-wrap:wrap; }
  .sec-row input {
    flex:1; min-width:210px;
    font-family:"IBM Plex Mono", monospace; font-size:12.5px;
  }
  .tick { color:var(--up); }
  .cross { color:var(--ink-3); }

  /* ── Messages ──────────────────────────────────────────────────────── */
  .msg {
    font-size:12.5px; line-height:1.5; padding:10px 13px;
    border-radius:var(--radius-sm); margin-top:9px;
    border:1px solid transparent;
  }
  .msg.ok   { color:var(--up);   background:color-mix(in srgb,var(--up) 11%,transparent);
              border-color:color-mix(in srgb,var(--up) 26%,transparent); }
  .msg.warn { color:var(--warn); background:color-mix(in srgb,var(--warn) 11%,transparent);
              border-color:color-mix(in srgb,var(--warn) 26%,transparent); }
  .msg.bad  { color:var(--down); background:color-mix(in srgb,var(--down) 11%,transparent);
              border-color:color-mix(in srgb,var(--down) 26%,transparent); }
  .msg code {
    font-family:"IBM Plex Mono", monospace; font-size:11.5px;
    background:color-mix(in srgb,var(--ink) 9%,transparent);
    padding:1px 5px; border-radius:4px;
  }

  /* ── Sync bar ──────────────────────────────────────────────────────── */
  .sync {
    display:flex; align-items:center; gap:16px;
    padding:13px 18px; border-radius:var(--radius); margin-bottom:16px;
    background:color-mix(in srgb,var(--warn) 10%,var(--panel));
    border:1px solid color-mix(in srgb,var(--warn) 30%,var(--line));
    font-size:13px;
  }
  .sync span { flex:1; }

  /* ── New campaign ──────────────────────────────────────────────────── */
  .frow { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:13px; }
  .frow label { display:flex; flex-direction:column; gap:5px;
                font-size:11px; color:var(--ink-3); letter-spacing:.03em; }
  .chk { display:flex; align-items:center; gap:8px; font-size:12.5px;
         color:var(--ink-2); margin-top:11px; cursor:pointer; }
  .chk input { accent-color:var(--accent); width:15px; height:15px; }
  .row { display:flex; gap:10px; align-items:center; margin-top:15px; flex-wrap:wrap; }

  textarea {
    width:100%; min-height:230px; resize:vertical;
    font-family:"IBM Plex Mono", monospace; font-size:12.5px; line-height:1.65;
  }
  .hint { font-size:12px; color:var(--ink-3); margin-top:9px; }
  .dead { color:var(--down); }

  /* ── Charts ────────────────────────────────────────────────────────────
     Palette validated with the data-viz checker against both surfaces:
     0 failures on all pairs, worst CVD ΔE 10.7 dark / 8.4 light. Gold was
     the obvious warm third hue and had to be dropped — terracotta↔gold is
     ΔE 2.6 under deutan, i.e. one colour to a red-green colourblind reader. */
  :root { --s1:#dd5f3c; --s2:#2f9e83; --s3:#a878e6; }
  /* Bars that are NOT a platform series (totals, schedule, asset counts) wear
     a neutral, never a series hue — terracotta has to keep meaning Instagram
     and nothing else. */
  :root { --bar:#6f655d; }
  @media (prefers-color-scheme: light) { :root { --bar:#9c9088; } }
  :root[data-theme="light"] { --bar:#9c9088; }
  :root[data-theme="dark"]  { --bar:#6f655d; }
  @media (prefers-color-scheme: light) {
    :root { --s1:#c9502a; --s2:#1e855f; --s3:#8a5cd6; }
  }
  :root[data-theme="light"] { --s1:#c9502a; --s2:#1e855f; --s3:#8a5cd6; }
  :root[data-theme="dark"]  { --s1:#dd5f3c; --s2:#2f9e83; --s3:#a878e6; }

  .grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
           gap:16px; margin-top:16px; }
  .chead { font-size:13px; font-weight:650; margin-bottom:14px;
           display:flex; align-items:baseline; gap:8px; }
  .chead small { font-weight:400; color:var(--ink-3); font-size:11px; }
  .chartbar { display:flex; align-items:center; gap:12px; margin-bottom:14px;
              flex-wrap:wrap; }
  button.sm { padding:5px 11px; font-size:12px; }
  .legend { display:flex; gap:14px; flex-wrap:wrap; }
  .lg { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--ink-2); }
  .sw { width:9px; height:9px; border-radius:2px; flex:none; }
  .segs { display:inline-flex; border:1px solid var(--line-2);
          border-radius:var(--radius-sm); overflow:hidden; }
  .segs button { background:transparent; color:var(--ink-2); border:none;
                 border-radius:0; padding:5px 12px; font-size:12px; }
  .segs button[aria-pressed="true"] { background:var(--panel-2); color:var(--ink); }
  svg.chart { display:block; width:100%; overflow:visible; }
  .axis { font-size:10px; fill:var(--ink-3); font-family:"IBM Plex Mono",monospace; }
  .gridline { stroke:var(--line); stroke-width:1; opacity:.7; }
  rect.bar { transition:opacity .14s; }
  rect.bar:hover { opacity:.82; }
  .tip {
    position:fixed; pointer-events:none; z-index:60; opacity:0;
    background:var(--panel); border:1px solid var(--line-2);
    border-radius:8px; padding:8px 11px; font-size:12px;
    box-shadow:var(--shadow); transition:opacity .1s;
  }
  .tip .tr { display:flex; align-items:center; gap:7px; white-space:nowrap; }
  .tip .tt { font-weight:650; margin-bottom:5px; font-size:11px; color:var(--ink-3); }
  table.dv { width:100%; border-collapse:collapse; font-size:12px; }
  table.dv th, table.dv td { padding:6px 10px; text-align:right;
    border-bottom:1px solid var(--line); }
  table.dv th:first-child, table.dv td:first-child { text-align:left; }
  table.dv th { color:var(--ink-3); font-weight:600; font-size:11px; }
</style>
</head>
<body>
<header>
  <span class="brand"><span class="dot"></span>ugc-factory</span>
  <div class="switch">
    <button id="switch-btn" class="switch-btn" aria-haspopup="listbox"
            aria-expanded="false">
      <span id="switch-name">—</span><span class="chev">&#9662;</span>
    </button>
    <div id="switch-menu" class="switch-menu" role="listbox" hidden></div>
  </div>
  <span class="pill" id="t-service">—</span>
  <span class="pill" id="t-cadence">—</span>
  <span class="pill" id="t-dry">—</span>
  <span class="spacer"></span>
  <button class="ghost" id="new-btn">New campaign</button>
</header>

<main>
  <div id="sync-bar" style="display:none">
    <div class="sync">
      <span id="sync-text"></span>
      <button id="publish-btn">Publish to GitHub</button>
    </div>
  </div>

  <div id="new-panel" style="display:none">
    <div class="card pad" style="margin-bottom:16px">
      <h2 style="margin-bottom:15px">New campaign</h2>
      <div class="frow">
        <label>Buffer account<select id="f-key"></select></label>
        <label>Channel<select id="f-channel"><option value="">loading…</option></select></label>
      </div>
      <div class="frow" id="manual-row" style="display:none;margin-top:13px">
        <label>Network<select id="f-service">
          <option value="instagram">instagram</option>
          <option value="tiktok">tiktok</option>
          <option value="youtube">youtube</option>
        </select></label>
        <label>Buffer channel ID<input type="text" id="f-channel-id"
          placeholder="paste from Buffer" autocomplete="off"></label>
        <label>Slug<input type="text" id="f-slug" placeholder="brand_tiktok" autocomplete="off"></label>
        <label>Posts / day<input type="number" id="f-ppd" min="1" max="24" value="12"></label>
        <label>Start hour<input type="number" id="f-start" min="0" max="23" value="15"></label>
      </div>
      <label class="chk"><input type="checkbox" id="f-share" checked>
        Share this campaign's asset library — no re-uploading clips</label>
      <label class="chk"><input type="checkbox" id="f-copy" checked>
        Copy the current descriptions</label>
      <div class="row">
        <button id="create-btn">Create campaign</button>
        <button class="ghost" id="cancel-btn">Cancel</button>
      </div>
      <div id="new-msgs"></div>
    </div>
  </div>

  <section>
    <h2>All time <small>every campaign, since the first post</small></h2>
    <div id="overall"></div>
  </section>

  <section>
    <h2>Trend
      <small>validated palette · terracotta Instagram · teal TikTok · violet YouTube</small>
    </h2>
    <div class="card pad">
      <div class="chartbar">
        <select id="c-metric" aria-label="Metric to plot"></select>
        <div class="legend" id="c-legend"></div>
        <span class="spacer"></span>
        <button class="ghost sm" id="c-table" aria-pressed="false">Table</button>
      </div>
      <div id="c-main"></div>
      <div id="c-tablewrap" style="display:none"></div>
    </div>

    <div class="grid2">
      <div class="card pad">
        <div class="chead">Share of <span id="c-share-metric">views</span>
          <small>all time</small></div>
        <div id="c-share"></div>
      </div>
      <div class="card pad">
        <div class="chead">Videos rendered <small>per day, from history</small></div>
        <div id="c-volume"></div>
      </div>
      <div class="card pad">
        <div class="chead">Publish schedule <small>slots in the current queue</small></div>
        <div id="c-hours"></div>
      </div>
      <div class="card pad">
        <div class="chead">Asset usage <small>times each clip has been used</small></div>
        <div class="chartbar" style="margin-bottom:8px">
          <div class="segs" id="c-asset-kind"></div>
        </div>
        <div id="c-assets"></div>
      </div>
    </div>
  </section>

  <section>
    <h2>By platform <small id="perf-note"></small></h2>
    <div id="perf"></div>
  </section>

  <section>
    <h2>Findings <small>what the data on disk already says</small></h2>
    <div id="insights"></div>
  </section>

  <section>
    <h2>Queue <small>what goes out next — pull anything before it publishes</small></h2>
    <div id="quota"></div>
    <div id="queue"></div>
  </section>

  <section>
    <h2>Assets <small>drag files in — names don't matter</small></h2>
    <div id="shared-note"></div>
    <div class="zones" id="zones"></div>
    <div class="row">
      <button class="ghost" id="preview">Preview plan</button>
      <button id="upload">Upload to GitHub</button>
    </div>
    <div id="up-msgs"></div>
    <div class="card pad" id="plan" style="display:none;margin-top:12px;
      font-family:'IBM Plex Mono',monospace;font-size:12px;white-space:pre-wrap"></div>
  </section>

  <section>
    <h2>Revenue <small>what it earned, against what it reached</small></h2>
    <div id="rev-top"></div>
    <div class="grid2" style="margin-top:16px">
      <div class="card pad">
        <div class="chead">Revenue per 1,000 views
          <small>each point pairs money with the same 30 days of reach</small></div>
        <div id="rev-rpm"></div>
      </div>
      <div class="card pad">
        <div class="chead">Revenue over time <small>payouts spread across the days they cover</small></div>
        <div id="rev-daily"></div>
      </div>
    </div>
    <div class="card pad" style="margin-top:16px">
      <div class="chead">Record a payment</div>
      <div class="frow" style="margin-top:12px">
        <label>From<input type="date" id="r-start"></label>
        <label>To<input type="date" id="r-end"></label>
        <label>Amount<input type="number" id="r-amount" min="0" step="0.01"
          placeholder="0.00"></label>
        <label>Source<input type="text" id="r-source" list="r-sources"
          placeholder="brand deal" autocomplete="off"></label>
        <label>Note<input type="text" id="r-note" placeholder="optional"
          autocomplete="off"></label>
      </div>
      <datalist id="r-sources">
        <option value="brand deal"><option value="affiliate">
        <option value="creator fund"><option value="app revenue">
      </datalist>
      <div class="row">
        <button id="r-add">Add</button>
        <span class="hint" style="margin:0">A single date? Put the same day in
          both boxes.</span>
      </div>
      <div id="rev-msgs"></div>
      <div id="rev-list"></div>
    </div>
  </section>

  <section>
    <h2>Keys <small>paste once — stored on this laptop and on GitHub</small></h2>
    <div id="secrets"></div>
  </section>

  <section>
    <h2>Randomizer <small>switch a clip off to hold it back — nothing is deleted</small></h2>
    <div class="card pad" style="margin-bottom:14px">
      <div class="row" style="margin:0;align-items:baseline">
        <div id="mix-summary" style="font-size:13px;color:var(--ink-2)">loading…</div>
        <span class="spacer"></span>
        <button class="ghost sm" id="mix-refresh" title="Re-read the assets Release">Refresh</button>
      </div>
      <div id="mix-scope" class="hint"></div>
      <div class="row" style="margin-top:12px">
        <button class="ghost" id="sample-btn">Render a sample</button>
        <span class="hint" style="margin:0">Builds one video from the clips
          switched on. Queues nothing, posts nothing.</span>
      </div>
      <div id="sample"></div>
      <div id="mix-note"></div>
    </div>
    <div id="mix"></div>
  </section>

  <section>
    <h2>Descriptions <small>the text each video is posted with</small></h2>
    <textarea id="bank" spellcheck="false"
      placeholder="One description per record, separated by a line of ---"></textarea>
    <div class="row">
      <button class="ghost" id="save">Save descriptions</button>
      <span class="hint" id="bank-count" style="margin:0"></span>
    </div>
    <div id="bank-msgs"></div>
  </section>

  <section>
    <h2>Library</h2>
    <div class="card">
      <div class="hero" id="stats"></div>
      <div id="health"></div>
    </div>
  </section>
</main>

<script>
const KINDS = [
  ["hooks",  "Hooks",  "the first 1–2s that stop the scroll", "video/*"],
  ["bodies", "Bodies", "your main videos",                    "video/*"],
  ["music",  "Music",  "whole songs, royalty-free",           "audio/*"],
];
const $ = s => document.querySelector(s);
let STATE = null, CHANNELS = [], MANUAL = false;

function bytes(n){ return n > 1e6 ? (n/1e6).toFixed(1)+" MB" : Math.max(1,Math.round(n/1e3))+" KB"; }
function fmt(v, unit){
  if (unit === "percentage") return v.toFixed(1) + "%";
  if (v >= 1e6) return (v/1e6).toFixed(1) + "M";
  if (v >= 1e3) return (v/1e3).toFixed(1) + "k";
  return Math.round(v).toLocaleString();
}
function delta(change){
  if (change === null || change === undefined) return "";
  const cls = change > 1 ? "up" : change < -1 ? "down" : "flat";
  const sign = change > 0 ? "+" : "";
  return `<span class="d ${cls}">${sign}${change.toFixed(0)}%</span>`;
}
function msg(el, cls, text){ el.innerHTML += `<div class="msg ${cls}">${text}</div>`; }

/* Area sparkline: the fill is what makes a 90px chart readable at a glance. */
function sparkline(points, w, h){
  if (points.length < 2) return "";
  const vals = points.map(p => p[1]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = (max - min) || 1;
  const step = w / (points.length - 1);
  const xy = vals.map((v,i) => [i*step, h - ((v-min)/span)*(h-3) - 1.5]);
  const line = xy.map(([x,y],i) => `${i?"L":"M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const id = "g" + Math.random().toString(36).slice(2,8);
  const rising = vals[vals.length-1] >= vals[0];
  const c = rising ? "var(--up)" : "var(--down)";
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" fill="none">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${c}" stop-opacity=".28"/>
      <stop offset="100%" stop-color="${c}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${line}L${w},${h}L0,${h}Z" fill="url(#${id})"/>
    <path d="${line}" stroke="${c}" stroke-width="1.6"
          stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

function buildZones(){
  $("#zones").innerHTML = KINDS.map(([k,label,sub,accept]) => `
    <div class="zone" data-kind="${k}" tabindex="0" role="button"
         aria-label="Add ${label}">
      <h3>${label}</h3>
      <div class="sub">${sub}</div>
      <ul class="files" id="f-${k}"></ul>
      <input type="file" multiple accept="${accept}" id="i-${k}" hidden>
    </div>`).join("");

  KINDS.forEach(([k]) => {
    const zone = document.querySelector(`.zone[data-kind="${k}"]`);
    const input = $(`#i-${k}`);
    const open = e => { if (e.target.tagName !== "BUTTON") input.click(); };
    zone.addEventListener("click", open);
    zone.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
    input.addEventListener("change", () => { send(k, input.files); input.value = ""; });
    ["dragenter","dragover"].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.classList.add("over");
    }));
    ["dragleave","drop"].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.classList.remove("over");
    }));
    zone.addEventListener("drop", e => send(k, e.dataTransfer.files));
  });
}

async function send(kind, files){
  for (const f of files){
    await fetch(`/api/upload?kind=${kind}&name=${encodeURIComponent(f.name)}`,
                {method:"POST", body:f});
  }
  refresh();
}
async function remove(kind, name){
  await fetch(`/api/inbox?kind=${kind}&name=${encodeURIComponent(name)}`, {method:"DELETE"});
  refresh();
}

function render(s){
  STATE = s;
  $("#t-service").textContent = s.service;
  $("#t-cadence").textContent = s.posts_per_day + "/day";
  const dry = $("#t-dry");
  dry.textContent = s.dry_run ? "paused" : "live";
  dry.className = "pill " + (s.dry_run ? "paused" : "live");

  const lib = s.library || {campaigns: [s.campaign]};
  $("#shared-note").innerHTML = lib.campaigns.length > 1
    ? `<div class="shared">One library, <b>${lib.campaigns.length} campaigns</b> —
         drop a clip in once and it is live in all of them:
         ${lib.campaigns.map(c => `<span class="pill">${c}</span>`).join("")}</div>`
    : "";

  KINDS.forEach(([k]) => {
    const list = s.staged[k] || [];
    $(`#f-${k}`).innerHTML = list.length
      ? list.map(f => `<li><span class="nm">${f.name}</span>
          <span class="sz num">${bytes(f.size)}</span>
          <button title="Remove" aria-label="Remove ${f.name}"
            onclick="event.stopPropagation();remove('${k}','${
              f.name.replace(/'/g,"\\\\'")}')">×</button></li>`).join("")
      : `<li style="border:none"><span class="empty">nothing staged</span></li>`;
  });

  const h = s.health, u = s.uploaded;
  // The repeat rate leads because it is the one that constrains how varied
  // the output looks. Runway is the reassuring number and the least useful:
  // thousands of days of unique tuples says nothing about whether a viewer
  // can tell two of them apart.
  const cells = [
    [u.hook, "hooks"], [u.body, "bodies"], [u.music, "tracks"],
    [s.descriptions.count, "descriptions"],
    [h.combinations.toLocaleString(), "combinations"],
  ].map(([v,k]) => `<div class="stat"><div class="v num">${v}</div>
       <div class="k">${k}</div></div>`);
  if (h.body_repeats_per_day)
    cells.unshift(`<div class="stat lead">
      <div class="v num">${h.body_repeats_per_day}x</div>
      <div class="k">each body clip, per day</div></div>`);
  $("#stats").innerHTML = cells.join("");

  const hv = $("#health"); hv.innerHTML = "";
  const notes = [];
  if (h.runway_days < h.min_runway_days)
    notes.push(["warn", `Runway ${Math.round(h.runway_days)}d is under the ${h.min_runway_days}d target — preflight will fail.`]);
  const held = Object.values(s.muted || {}).reduce((a,b) => a+b, 0);
  if (held)
    notes.push(["ok", `${held} clip${held>1?"s":""} switched off in the ` +
      `randomizer — not counted above.`]);
  h.warnings.forEach(w => notes.push(["warn", w]));
  if (!notes.length && h.combinations > 0)
    notes.push(["ok", "Library supports the configured cadence with no relaxation."]);
  const runway = `${Math.round(h.runway_days).toLocaleString()} days before the
    first exact repeat, at ${s.posts_per_day}/day. That is a count of unique
    tuples, not a measure of variety.`;
  hv.innerHTML = `<div class="foot" style="padding:14px 22px">` +
    notes.map(([c,t]) =>
      `<div class="msg ${c}" style="margin-top:0;margin-bottom:8px">${t}</div>`
    ).join("") +
    `<div style="color:var(--ink-3)">${runway}</div></div>`;

  if (document.activeElement !== $("#bank")) $("#bank").value = s.descriptions.text;
  $("#bank-count").textContent = s.descriptions.count + " descriptions";
  const bm = $("#bank-msgs"); bm.innerHTML = "";
  s.descriptions.errors.forEach(e => msg(bm,"bad",e));
  s.descriptions.notes.slice(0,5).forEach(n => msg(bm,"warn",n));
}

/* ── Queue ────────────────────────────────────────────────────────────────
   The video in each row is the exact file Buffer will fetch, straight from
   its public Release URL — so what you preview is what publishes.       */
let QUEUE = null;

function slotTime(iso){
  const d = new Date(iso);
  return {
    t: d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"}),
    d: d.toLocaleDateString([], {month:"short", day:"numeric"}),
  };
}

/* ── Sample render ────────────────────────────────────────────────────────
   Reads history so it never shows a combination already spent, and writes
   neither history nor the queue — looking at your library must not cost a
   tuple of runway.                                                       */
$("#sample-btn").onclick = async (e) => {
  const out = $("#sample");
  out.innerHTML = "";
  e.target.disabled = true; e.target.textContent = "Rendering…";
  let r;
  try {
    r = await (await fetch("/api/sample", {method:"POST"})).json();
  } catch (err) { r = {ok:false, error:String(err)}; }
  e.target.disabled = false; e.target.textContent = "Render another";

  if (!r.ok){ msg(out, "bad", r.error); return; }
  const music = r.music
    ? `${esc(r.music)} from ${Math.round(r.music_offset_sec)}s`
    : "no music";
  out.innerHTML = `<div class="sample">
    <video src="${r.url}" controls playsinline preload="metadata"></video>
    <div class="smeta">
      <b>Built from</b>
      <span class="sparts">${esc(r.hook)}<br>${
        r.bodies.map(esc).join("<br>")}<br>${esc(music)}</span>
      ${r.title ? `<div class="scap"><b>Title</b>${esc(r.title)}</div>` : ""}
      <div class="scap">${esc(r.caption)}</div>
    </div>
  </div>`;
  if (r.relaxation !== "none")
    msg(out, "warn", `This one needed relaxed dedupe (${r.relaxation}) — the
      library is small for the configured cadence.`);
};

/* ── Findings ─────────────────────────────────────────────────────────────
   Derived entirely from files already on disk — no API calls, so this is
   free to recompute whenever the page loads.                            */
async function loadInsights(){
  const r = await (await fetch("/api/insights")).json();
  const el = $("#insights");
  if (!r.findings.length){
    el.innerHTML = `<div class="card pad"><span class="empty">Nothing to
      compare yet — findings appear once the metrics job has cached a
      snapshot.</span></div>`;
    return;
  }
  el.innerHTML = r.findings.map(f => {
    // The first column is a label; the rest are figures and get tabular
    // numerals so columns of digits line up.
    const body = f.rows.map(row => `<tr>${row.map((cell,i) =>
      `<td class="${i && f.id !== "limits" ? "n" : ""}">${esc(cell)}</td>`
    ).join("")}</tr>`).join("");
    return `<div class="card find ${f.severity} ${f.id === "limits" ? "limits" : ""}">
      <div class="fhead">
        <h3>${esc(f.headline)}</h3>
        <p class="fdetail">${esc(f.detail)}</p>
      </div>
      <div class="fscroll"><table>
        <thead><tr>${f.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${body}</tbody>
      </table></div>
    </div>`;
  }).join("");
}

async function loadQuota(){
  const q = await (await fetch("/api/quota")).json();
  const el = $("#quota");
  const pct = Math.min(100, Math.round(q.used / q.allowance * 100));
  const cls = pct >= 90 ? "over" : pct >= 75 ? "warn" : "";
  el.innerHTML = `<div class="card" style="margin-bottom:14px">
    <div class="quota ${cls}">
      <span class="qfig">${q.used.toLocaleString()} <span class="qsub">of ${
        q.allowance.toLocaleString()}</span></span>
      <span class="qbar"><i style="width:${pct}%"></i></span>
      <span class="qsub">${q.measured
        ? `Buffer requests · last ${q.window_days} days · ${
            q.campaigns.join(", ")}`
        : `not measured yet — counting starts at the next posting run`}</span>
    </div>
  </div>`;
}

async function loadQueue(){
  QUEUE = await (await fetch("/api/queue")).json();
  renderQueue();
}

function renderQueue(){
  const q = QUEUE, el = $("#queue");
  if (!q) return;
  if (q.error){
    el.innerHTML = `<div class="card pad"><div class="msg bad" style="margin:0">
      ${q.error}</div></div>`;
    return;
  }
  if (!q.items.length){
    el.innerHTML = `<div class="card pad"><span class="empty">Nothing queued.
      The nightly render fills this at 05:00 UTC.</span></div>`;
    return;
  }

  const live = q.items.filter(i => i.status === "pending" || i.status === "claimed");
  const order = {claimed:0, pending:1, failed:2, pushed:3, cancelled:4};
  const counts = Object.entries(q.counts)
    .sort((a,b) => (order[a[0]] ?? 9) - (order[b[0]] ?? 9))
    .map(([k,n]) => `${n} ${k}`).join(" · ");

  el.innerHTML = `<div class="card">
    <div class="plat-head">
      <span class="plat-name">${live.length} still to go</span>
      <span class="plat-sub">${counts}</span>
      <span class="spacer"></span>
      <span class="plat-sub">times in ${q.timezone}</span>
    </div>
    ${q.items.map(i => {
      const s = slotTime(i.scheduled_for);
      const done = i.status === "pushed" || i.status === "cancelled";
      // Only the media, in composition order. parts also carries the music
      // offset, which is a number of seconds and not a clip.
      const parts = ["hook", "bodies", "music"]
        .map(k => (i.parts || {})[k]).filter(Boolean).join(" + ");
      return `<div class="qrow ${done ? "done" : ""}" data-id="${i.id}">
        <div class="qtime">${s.t}<span class="d">${s.d}</span></div>
        <div class="qvid" onclick="peek(this)" tabindex="0" role="button"
             aria-label="Play the video scheduled for ${s.d} ${s.t}"
             onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();peek(this)}">
          <video preload="none" muted playsinline
                 poster="" src="${i.video_url}#t=0.1"></video>
        </div>
        <div class="qcap">
          ${i.title ? `<b>${esc(i.title)}</b><br>` : ""}
          ${esc((i.caption || "").replace(/\\s+/g, " ").slice(0, 160))}${
            (i.caption || "").length > 160 ? "…" : ""}
          <span class="parts">${esc(parts)}</span>
          ${i.last_error
            ? `<span class="parts dead">${esc(i.last_error.slice(0,140))}</span>`
            : ""}
        </div>
        <div class="qact">
          <span class="qstate ${i.status}">${i.status}</span>
          ${i.cancellable
            ? `<button class="ghost sm" onclick="pullItem('${i.id}')">Pull</button>`
            : ""}
        </div>
      </div>`;
    }).join("")}
  </div>
  <div id="queue-msgs"></div>`;
}

async function pullItem(id){
  const row = document.querySelector(`.qrow[data-id="${id}"]`);
  const item = QUEUE.items.find(i => i.id === id);
  const sent = item && item.buffer_post_id;
  if (!confirm(sent
      ? `This one is already in Buffer.\n\nPulling it asks Buffer to delete the ` +
        `post. That works while Buffer is still holding it — if the network has ` +
        `already published, you will have to take it down there yourself.\n\nPull it?`
      : `Stop this video going out?\n\nIt has not been sent to Buffer yet, so ` +
        `nothing is published. The top-up job will skip it from now on.`)) return;

  const btn = row && row.querySelector("button");
  if (btn){ btn.disabled = true; btn.textContent = "Pulling…"; }
  const r = await (await fetch("/api/queue/pull", {method:"POST",
    body: JSON.stringify({id})})).json();
  await loadQueue();

  const out = $("#queue-msgs");
  if (out){
    if (!r.ok) msg(out, "bad", r.error);
    else if (r.warning) msg(out, "warn", r.warning);
    else msg(out, "ok", r.from_buffer
      ? "Pulled, and removed from Buffer."
      : "Pulled — it had not been sent to Buffer, so nothing was published.");
  }
  loadPending();
}

/* ── Revenue ──────────────────────────────────────────────────────────────
   Every ratio here pairs money with the reach from the SAME window, which
   the server does — the client only draws what it is handed.            */
let REV = null;

function money(v, cur){
  const c = cur === "USD" ? "$" : "";
  const n = Math.abs(v) >= 1000 ? v.toLocaleString(undefined,{maximumFractionDigits:0})
                                : v.toFixed(2);
  return c + n + (c ? "" : " " + (cur||""));
}

async function loadRevenue(){
  REV = await (await fetch("/api/revenue")).json();
  renderRevenue();
}

function renderRevenue(){
  const r = REV; if (!r) return;
  const cur = r.currency;
  const latest = r.rpm_series.length ? r.rpm_series[r.rpm_series.length-1][1] : null;
  const o = r.overall;

  $("#rev-top").innerHTML = `<div class="card"><div class="hero">
    <div class="stat lead"><div class="v num">${money(r.total, cur)}</div>
      <div class="k">${r.campaign} · all time</div></div>
    <div class="stat"><div class="v num">${
      latest === null ? "—" : money(latest, cur)}</div>
      <div class="k">per 1,000 views</div></div>
    <div class="stat"><div class="v num">${money(o.revenue, cur)}</div>
      <div class="k">every campaign</div></div>
    <div class="stat"><div class="v num">${
      o.rpm === null ? "—" : money(o.rpm, cur)}</div>
      <div class="k">blended per 1,000</div></div>
  </div>${
    o.campaigns.length > 1 ? `<div class="foot">` + o.campaigns.map(c =>
      `${c.campaign} ${money(c.revenue, cur)}${
        c.rpm !== null && c.rpm !== undefined ? ` · ${money(c.rpm, cur)}/1k` : ""}`
    ).join(" &nbsp;·&nbsp; ") + `</div>` : ""
  }</div>`;

  const notes = [];
  if (r.mixed_currencies.length)
    notes.push(["warn", `This ledger mixes ${cur} with ${
      r.mixed_currencies.join(", ")}. The totals above add them as if they were
      the same currency — they are not.`]);
  r.warnings.forEach(w => notes.push(["bad", w]));
  if (!r.entries.length)
    notes.push(["ok", `No revenue recorded yet. Add a payment below and the
      ratios fill in against the views already cached.`]);
  const nm = $("#rev-msgs"); nm.innerHTML = "";
  notes.forEach(([c,t]) => msg(nm, c, t));

  if (r.rpm_series.length)
    lineChart($("#rev-rpm"), {[cur + " / 1k views"]: r.rpm_series}, {h:200});
  else
    $("#rev-rpm").innerHTML = `<div class="hint">Needs both a recorded payment
      and a cached metrics snapshot. Metrics land daily at 06:30 UTC.</div>`;

  barsV($("#rev-daily"), r.daily.slice(-60).map(([d,v],i,a) => ({
    value: v, tick: (i === 0 || i === a.length-1) ? d.slice(5) : "",
    label: `${d} · ${money(v, cur)}`,
  })), {h:200});

  $("#rev-list").innerHTML = !r.entries.length ? "" :
    `<table class="ledger"><thead><tr>
      <th>Period</th><th>Source</th><th class="num">Amount</th>
      <th class="num">Per day</th><th></th></tr></thead><tbody>` +
    r.entries.map(e => `<tr>
      <td>${e.period_start}${e.period_end !== e.period_start
             ? ` → ${e.period_end}` : ""}
          <span class="sec-for">${e.days}d</span></td>
      <td><span class="src">${esc(e.source)}</span>${
        e.note ? ` <span class="sec-for">${esc(e.note)}</span>` : ""}</td>
      <td class="num">${money(e.amount, e.currency)}</td>
      <td class="num sec-for">${money(e.amount / e.days, e.currency)}</td>
      <td class="num"><button title="Remove" aria-label="Remove entry"
        onclick="dropRevenue('${e.id}')">×</button></td>
    </tr>`).join("") + `</tbody></table>`;
}

$("#r-add").onclick = async (e) => {
  const nm = $("#rev-msgs");
  const body = {
    period_start: $("#r-start").value,
    period_end: $("#r-end").value || $("#r-start").value,
    amount: $("#r-amount").value,
    source: $("#r-source").value.trim() || "manual",
    note: $("#r-note").value.trim(),
  };
  if (!body.period_start){ nm.innerHTML=""; msg(nm,"bad","Pick a start date."); return; }
  e.target.disabled = true;
  const r = await (await fetch("/api/revenue", {method:"POST",
    body: JSON.stringify(body)})).json();
  e.target.disabled = false;
  if (!r.ok){ nm.innerHTML=""; msg(nm,"bad",r.error); return; }
  $("#r-amount").value = ""; $("#r-note").value = "";
  await loadRevenue(); loadPending();
};

async function dropRevenue(id){
  if (!confirm("Remove this revenue entry?")) return;
  await fetch(`/api/revenue?id=${encodeURIComponent(id)}`, {method:"DELETE"});
  await loadRevenue(); loadPending();
}

/* ── Keys ─────────────────────────────────────────────────────────────────
   Neither store can be read back — GitHub never returns a secret value, and
   the local file is deliberately write-only from here — so this panel deals
   in presence, not content. The input is emptied the moment it is sent.   */
async function loadSecrets(){
  const r = await (await fetch("/api/secrets")).json();
  const el = $("#secrets");
  if (!r.secrets.length){ el.innerHTML = ""; return; }

  el.innerHTML = `<div class="card">` + r.secrets.map(sx => {
    const here = sx.local
      ? `<span class="tick">● on this laptop</span> <span class="sec-for">${sx.hint}${
           sx.from_environment ? " (from your shell)" : ""}</span>`
      : `<span class="cross">○ not on this laptop</span>`;
    const gh = sx.github
      ? `<span class="tick">● on GitHub</span>`
      : `<span class="cross">○ not on GitHub</span>`;
    return `<div class="sec" data-name="${sx.name}">
      <div class="sec-top">
        <span class="sec-name">${sx.name}</span>
        <span class="sec-for">${sx.campaigns.join(", ")}</span>
        <span class="spacer"></span>
        <span class="sec-for">${here} &nbsp; ${gh}</span>
      </div>
      <div class="sec-row">
        <input type="password" autocomplete="off" spellcheck="false"
          placeholder="${sx.local || sx.github ? "paste a new value to replace it" : "paste the value"}"
          aria-label="New value for ${sx.name}">
        <button onclick="saveSecret('${sx.name}', this)">Save</button>
        ${sx.local ? `<button class="ghost" onclick="forgetSecret('${sx.name}')"
          title="Remove the copy on this laptop. The GitHub copy, which is what
                 posts, is left alone.">Forget locally</button>` : ""}
      </div>
      <div class="msgs"></div>
    </div>`;
  }).join("") + `</div>
  <div class="hint">Saved to <code>${r.env_file}</code> (gitignored, this laptop
    only) and to the repository's Actions secrets, which is what the posting
    workflows read. Neither copy can be read back — replace a value by pasting
    a new one.</div>`;
}

async function saveSecret(name, btn){
  const row = btn.closest(".sec");
  const input = row.querySelector("input");
  const out = row.querySelector(".msgs");
  out.innerHTML = "";
  const value = input.value;
  if (!value.trim()){ msg(out, "bad", "Nothing pasted."); return; }

  btn.disabled = true; btn.textContent = "Saving…";
  let r;
  try {
    r = await (await fetch("/api/secrets", {method:"POST",
      body: JSON.stringify({name, value, to_github: true})})).json();
  } catch (err) { r = {ok:false, error:String(err)}; }
  // Cleared whatever happened, so a failed save does not leave the credential
  // sitting in a DOM node for the rest of the session.
  input.value = "";
  btn.disabled = false; btn.textContent = "Save";

  if (!r.ok){ msg(out, "bad", r.error); return; }
  if (r.github) msg(out, "ok", "Saved here and on GitHub.");
  else msg(out, "warn", `Saved on this laptop. GitHub was not updated: ${
    r.github_error || "unknown reason"} — set it in the repository's
    Settings → Secrets and variables → Actions.`);
  await loadSecrets(); await loadChannels().catch(() => {});
}

async function forgetSecret(name){
  if (!confirm(`Remove the local copy of ${name}?\n\n` +
               `The GitHub copy — the one the posting workflows use — is left ` +
               `alone. The dashboard will stop being able to list your Buffer ` +
               `channels until you paste it again.`)) return;
  await fetch(`/api/secrets?name=${encodeURIComponent(name)}`, {method:"DELETE"});
  await loadSecrets();
}

/* ── Randomizer ───────────────────────────────────────────────────────────
   The roster is rendered from a single fetch and mutated optimistically: a
   toggle repaints instantly and the POST catches up, because a switch that
   waits on a round trip before moving feels broken even when it is not.    */
let CLIPS = null;

function clipCard(c, kind){
  const q = encodeURIComponent(c.name);
  // Named for its job, not "esc": there is a global esc() for HTML escaping,
  // and shadowing it here made every escaped interpolation below a call on a
  // string. This one quotes a name for a JS string literal in an onclick.
  const jsName = c.name.replace(/'/g, "\\'");
  const thumb = !c.preview
    ? `<div class="nolocal">uploaded from another machine — no preview here</div>`
    : kind === "music"
      ? `<span class="glyph">♪</span><audio preload="none" src="/api/clip?name=${q}"></audio>
         <span class="play">▶</span>`
      : `<video preload="metadata" muted playsinline
                src="/api/clip?name=${q}#t=0.1"></video><span class="play">▶</span>`;
  const shown = esc(c.name);
  return `<div class="clip ${c.enabled ? "" : "off"}" data-name="${shown}">
    <div class="thumb" onclick="peek(this)" tabindex="0" role="button"
         aria-label="Play ${shown}"
         onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();peek(this)}">${thumb}
      ${c.size ? `<span class="sz num">${bytes(c.size)}</span>` : ""}
    </div>
    <button class="kill" title="Delete ${shown} for good"
      aria-label="Delete ${shown} permanently"
      onclick="killClip('${jsName}')">×</button>
    <div class="bar">
      <span class="nm" title="${shown}">${shown}</span>
      <button class="tgl" role="switch" aria-checked="${c.enabled}"
        aria-label="${shown} in the randomizer"
        onclick="flip('${jsName}')"></button>
    </div>
  </div>`;
}

/* Everything above the grid: counts, warnings, and which bulk buttons apply. */
function paintMixHeader(){
  const r = CLIPS;
  const live = r.groups.reduce((n,g) => n + g.enabled, 0);
  const all  = r.groups.reduce((n,g) => n + g.total, 0);
  $("#mix-summary").innerHTML = all
    ? `<b>${live}</b> of ${all} clips in the mix · <b>${
         r.combinations.toLocaleString()}</b> combinations · <b>${
         Math.round(r.runway_days).toLocaleString()}</b> days runway`
    : `Nothing uploaded yet.`;

  const scope = $("#mix-scope");
  const fed = (r.library && r.library.campaigns) || [];
  // The clips are shared; the switches are not. That distinction is the one
  // thing about this panel that is not self-evident.
  scope.innerHTML = fed.length > 1
    ? `Clips are shared across ${fed.join(", ")}. These switches apply to
       <b>${r.campaign}</b> only — a clip can run on one
       network and sit out on another.`
    : "";

  const note = $("#mix-note"); note.innerHTML = "";
  (r.blocking || []).forEach(label => msg(note, "bad",
    `Every clip under <b>${label}</b> is switched off — the next render will ` +
    `fail. Switch at least one back on.`));
  if (all && !(r.blocking || []).length && r.runway_days < r.min_runway_days)
    msg(note, "warn", `Runway is under the ${r.min_runway_days}-day target — ` +
        `switch some clips back on, or add more.`);
  if (r.muted)
    msg(note, "ok", `${r.muted} clip${r.muted>1?"s":""} held back. They stay ` +
        `uploaded and come straight back when you switch them on.`);

  r.groups.forEach(g => {
    const head = document.querySelector(`.mixgroup[data-kind="${g.kind}"] .mixhead`);
    if (!head) return;
    head.querySelector(".n").textContent = `${g.enabled}/${g.total} on`;
    const [on, off] = head.querySelectorAll("button");
    on.disabled = g.enabled === g.total;
    off.disabled = g.enabled === 0;
  });
}

/* Flip the switches without touching the cards themselves — rebuilding the
   grid would tear down every <video> and restart the one that is playing. */
function paintMixStates(){
  CLIPS.groups.forEach(g => g.clips.forEach(c => {
    const card = document.querySelector(`.clip[data-name="${CSS.escape(c.name)}"]`);
    if (!card) return;
    card.classList.toggle("off", !c.enabled);
    card.querySelector(".tgl").setAttribute("aria-checked", String(c.enabled));
  }));
  paintMixHeader();
}

function mixSignature(r){
  return r.groups.map(g => g.clips.map(c => c.name).join(",")).join("|");
}

function renderClips(){
  const r = CLIPS;
  if (!r) return;
  const all = r.groups.reduce((n,g) => n + g.total, 0);

  // Same cards as are already on screen: patch, do not rebuild.
  if ($("#mix").dataset.sig === mixSignature(r) && all){ paintMixStates(); return; }
  $("#mix").dataset.sig = mixSignature(r);

  $("#mix").innerHTML = all ? r.groups.map(g => `
    <div class="mixgroup" data-kind="${g.kind}">
      <div class="mixhead">
        <span class="t">${g.label}</span>
        <span class="n"></span>
        <span class="spacer"></span>
        <button class="ghost sm" onclick="flipGroup('${g.kind}', true)">All on</button>
        <button class="ghost sm" onclick="flipGroup('${g.kind}', false)">All off</button>
      </div>
      ${g.total
        ? `<div class="mixgrid">${g.clips.map(c => clipCard(c, g.kind)).join("")}</div>`
        : `<div class="empty">no ${g.label.toLowerCase()} uploaded yet</div>`}
    </div>`).join("")
    : `<div class="card pad"><span class="empty">Drop clips into the zones above
         and hit Upload — they appear here, switched on.</span></div>`;
  paintMixHeader();
}

/* Click a thumbnail to check which clip it actually is. */
function peek(thumb){
  const media = thumb.querySelector("video, audio");
  if (!media) return;
  document.querySelectorAll("#mix video, #mix audio").forEach(m => {
    if (m !== media) m.pause();
  });
  if (media.paused){ media.currentTime = media.currentTime || 0; media.play(); }
  else media.pause();
}

async function push(names, enabled){
  await fetch("/api/clips", {method:"POST",
    body: JSON.stringify({names, enabled})});
  await loadClips();
  await refresh();
}

async function flip(name){
  // Reads the live state rather than taking it as an argument. The card is
  // patched in place rather than rebuilt, so an argument baked into the
  // onclick when the card was created would still hold the original value and
  // every later click would repeat the first one.
  const current = CLIPS.groups
    .flatMap(g => g.clips).find(c => c.name === name);
  if (!current) return;
  const enabled = !current.enabled;
  for (const g of CLIPS.groups)
    for (const c of g.clips)
      if (c.name === name) c.enabled = enabled;
  CLIPS.groups.forEach(g => g.enabled = g.clips.filter(c => c.enabled).length);
  CLIPS.muted = CLIPS.groups.reduce((n,g) => n + (g.total - g.enabled), 0);
  paintMixStates();
  await push([name], enabled);
}

async function flipGroup(kind, enabled){
  const g = CLIPS.groups.find(g => g.kind === kind);
  const names = g.clips.filter(c => c.enabled !== enabled).map(c => c.name);
  if (!names.length) return;
  g.clips.forEach(c => c.enabled = enabled);
  g.enabled = enabled ? g.total : 0;
  CLIPS.muted = CLIPS.groups.reduce((n,g) => n + (g.total - g.enabled), 0);
  paintMixStates();
  await push(names, enabled);
}

/* Deletion is the irreversible half, so it asks — and says what the reversible
   alternative is, because muting is what people usually mean. */
async function killClip(name){
  if (!confirm(`Delete ${name} from GitHub permanently?\n\n` +
               `This cannot be undone. To take it out of the randomizer ` +
               `without losing it, switch it off instead.`)) return;
  const r = await (await fetch(`/api/clips?name=${encodeURIComponent(name)}`,
                               {method:"DELETE"})).json();
  if (!r.ok){ msg($("#mix-note"), "bad", r.error); return; }
  await loadClips();
  await refresh();
}

async function loadClips(refresh){
  CLIPS = await (await fetch("/api/clips" + (refresh ? "?refresh=1" : ""))).json();
  renderClips();
}

$("#mix-refresh").onclick = async (e) => {
  e.target.disabled = true;
  await loadClips(true);
  e.target.disabled = false;
};

function renderOverall(r){
  const el = $("#overall");
  const o = r.overall || {metrics: [], ever_posted: 0};
  const haveLifetime = r.campaigns.some(c => c.lifetime);

  if (!haveLifetime){
    el.innerHTML = `<div class="card">
      <div class="hero"><div class="stat lead"><div class="v num">${o.ever_posted||0}</div>
        <div class="k">videos published</div></div></div>
      <div class="foot">All-time engagement totals appear after the next metrics run —
        a separate query from the rolling window, so the first lands at 06:30 UTC.</div>
    </div>`;
    return;
  }

  const cells = [`<div class="stat lead"><div class="v num">${o.ever_posted}</div>
      <div class="k">videos published</div></div>`]
    .concat(o.metrics.slice(0, 6).map(m =>
      `<div class="stat"><div class="v num">${fmt(m.value,"count")}</div>
        <div class="k">${m.name.toLowerCase()}</div></div>`));

  const since = r.campaigns.map(c => c.lifetime && c.lifetime.since)
                  .filter(Boolean).sort()[0];
  const n = r.campaigns.filter(c=>c.lifetime).length;
  el.innerHTML = `<div class="card">
    <div class="hero">${cells.join("")}</div>
    <div class="foot">Summed across ${n} campaign${n>1?"s":""}${
      since ? ` since ${new Date(since).toLocaleDateString()}` : ""}.
      Rates are excluded — an engagement rate cannot be added up.</div>
  </div>`;
}

async function loadMetrics(){
  const r = await (await fetch("/api/metrics")).json();
  renderOverall(r);
  const el = $("#perf");
  const withData = r.campaigns.filter(c => c.has_data);

  if (!withData.length){
    el.innerHTML = `<div class="card pad"><div class="msg warn" style="margin:0">
      No metrics cached yet. They are fetched once a day by the metrics workflow —
      networks also report on a lag, so expect the first numbers a day after your
      first posts go live.</div></div>`;
    $("#perf-note").textContent = "";
    return;
  }
  $("#perf-note").textContent = "cached daily, not live";
  el.innerHTML = `<div class="grid">` + withData.map(c => {
    const stale = c.updated_at ? new Date(c.updated_at).toLocaleString() : "unknown";
    return `<div class="card">
      <div class="plat-head">
        <span class="plat-name">${c.service || c.campaign}</span>
        <span class="spacer"></span>
        <span class="plat-sub">${c.ever_posted} all time · ${c.post_count} in 30d</span>
      </div>
      <div class="metrics">
        ${c.metrics.filter(m => m.type !== "postCount").map(m => `
          <div class="m">
            <div class="v num">${fmt(m.value, m.unit)}${delta(m.change)}</div>
            <div class="k">${m.name.toLowerCase()}</div>
            ${sparkline(c.series[m.type] || [], 92, 20)}
          </div>`).join("")}
      </div>
      <div class="foot">network data as of ${stale}</div>
    </div>`;
  }).join("") + `</div>`;
}

async function refresh(){ render(await (await fetch("/api/state")).json()); }

async function loadPending(){
  const r = await (await fetch("/api/pending")).json();
  const bar = $("#sync-bar");
  const n = r.changed.length, c = r.unpushed_commits;
  if (!n && !c){ bar.style.display = "none"; return; }
  bar.style.display = "block";
  $("#sync-text").innerHTML = n
    ? `<b>${n} local change${n>1?"s":""}</b> not on GitHub yet — the workflows read from the repo, so nothing here affects posting until you publish.`
    : `<b>${c} commit${c>1?"s":""}</b> not pushed yet.`;
}

$("#publish-btn").onclick = async (e) => {
  e.target.disabled = true; e.target.textContent = "Publishing…";
  const r = await (await fetch("/api/publish", {method:"POST", body:"{}"})).json();
  e.target.disabled = false; e.target.textContent = "Publish to GitHub";
  if (!r.ok){ $("#sync-text").innerHTML = `<b class="dead">${r.error}</b>`; return; }
  await loadPending();
};

async function loadCampaigns(){
  const r = await (await fetch("/api/campaigns")).json();
  $("#switch-name").textContent = r.selected;
  $("#switch-menu").innerHTML = r.campaigns.map(c => `
    <button class="sw-item ${c.valid ? "" : "broken"}" role="option"
            aria-selected="${c.slug === r.selected}"
            onclick="pickCampaign('${c.slug}')">
      <span class="tick">${c.slug === r.selected ? "&#10003;" : ""}</span>
      <span class="slug">${esc(c.slug)}</span>
      <span class="meta">${c.valid
        ? `${esc(c.service)} · ${c.posts_per_day}/day · ${c.dry_run ? "paused" : "live"}`
        : "broken"}</span>
    </button>`).join("") + `
    <div class="sw-new"><button class="sw-item" onclick="newCampaign()">
      <span class="tick">+</span><span class="slug">New campaign</span>
    </button></div>`;

  const broken = r.campaigns.filter(c => !c.valid);
  if (broken.length){
    const el = $("#perf");
    broken.forEach(c => msg(el, "bad", `${c.slug}: ${c.error}`));
  }
}

function toggleSwitch(open){
  const menu = $("#switch-menu");
  const show = open === undefined ? menu.hidden : open;
  menu.hidden = !show;
  $("#switch-btn").setAttribute("aria-expanded", String(show));
  if (show){
    // Land on the campaign you are already on, not the top of the list.
    const current = menu.querySelector('.sw-item[aria-selected="true"]');
    (current || menu.querySelector(".sw-item"))?.focus();
  } else if (document.activeElement && menu.contains(document.activeElement)){
    // Closing with Escape must not strand focus on a hidden button.
    $("#switch-btn").focus();
  }
}
$("#switch-btn").onclick = (e) => { e.stopPropagation(); toggleSwitch(); };

/* role="listbox" is a promise that arrow keys work. Tab alone would walk out
   of the menu and on through the page, which is not what a dropdown does. */
$("#switch-menu").addEventListener("keydown", (e) => {
  const items = [...$("#switch-menu").querySelectorAll(".sw-item")];
  const at = items.indexOf(document.activeElement);
  if (e.key === "ArrowDown" || e.key === "ArrowUp"){
    e.preventDefault();
    const step = e.key === "ArrowDown" ? 1 : -1;
    items[(at + step + items.length) % items.length].focus();
  } else if (e.key === "Home" || e.key === "End"){
    e.preventDefault();
    items[e.key === "Home" ? 0 : items.length - 1].focus();
  }
});
document.addEventListener("click", () => toggleSwitch(false));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") toggleSwitch(false);
});

/* Every panel, so nothing from the previous campaign survives the switch.
   The old handler refreshed six of them and left findings, keys and charts
   showing the campaign you had just navigated away from. */
async function refreshAll(){
  await Promise.all([
    refresh(), loadClips(), loadQueue(), loadQuota(), loadInsights(),
    loadRevenue(), loadSecrets(), loadMetrics(), loadCharts(), loadPending(),
  ]);
}

async function pickCampaign(slug){
  toggleSwitch(false);
  $("#switch-name").textContent = slug;
  await fetch("/api/select", {method:"POST", body: JSON.stringify({slug})});
  await loadCampaigns();
  await refreshAll();
}

function newCampaign(){
  toggleSwitch(false);
  $("#new-btn").click();
}

async function loadKeys(){
  const r = await (await fetch("/api/keys")).json();
  const sel = $("#f-key");
  sel.innerHTML = r.slots.map(s => {
    const note = s.used_by.length ? ` — ${s.used_by.join(", ")}`
               : s.available ? " — ready" : " — no key set";
    return `<option value="${s.name}">${s.name}${note}</option>`;
  }).join("");
  const firstReady = r.slots.find(s => s.available);
  if (firstReady) sel.value = firstReady.name;
}
$("#f-key").onchange = () => { loadChannels(); };

async function loadChannels(){
  const sel = $("#f-channel");
  // Reopening the panel or switching key slot re-runs this, so drop the
  // warning from the previous run — but only that one. Clearing the whole
  // panel here would wipe the "Created <slug>" confirmation, since creating
  // reloads the channel list on its way out.
  $("#new-msgs").querySelectorAll(".chan-msg").forEach(n => n.remove());
  const slot = $("#f-key").value || "BUFFER_API_KEY";
  const r = await (await fetch("/api/channels?slot=" + encodeURIComponent(slot))).json();
  if (!r.ok){
    // No key on this machine is the normal case — the workflows read it from
    // GitHub Secrets, not from here. Say what to do, and leave a path that
    // does not need Buffer at all rather than a dead Create button.
    sel.innerHTML = `<option value="">unavailable</option>`;
    $("#f-channel").closest("label").style.display = "none";
    $("#manual-row").style.display = "";
    MANUAL = true;
    msg($("#new-msgs"), "warn chan-msg",
        `Can't list your Buffer channels: ${r.error}<br>
         <span style="opacity:.85">${r.hint||""}</span><br>
         Until then, pick the network and paste the channel ID from Buffer's
         URL — everything else works the same.`);
    return;
  }
  MANUAL = false;
  $("#f-channel").closest("label").style.display = "";
  $("#manual-row").style.display = "none";
  CHANNELS = r.channels;
  const usable = CHANNELS.filter(c => !c.taken_by && !c.disconnected && !c.locked);
  sel.innerHTML =
    (usable.length ? "" : `<option value="">no free channels</option>`) +
    usable.map(c =>
      `<option value="${c.id}">${c.service} · ${c.name}${
        c.reminders?"  (reminder mode)":""}</option>`).join("") +
    CHANNELS.filter(c => c.taken_by).map(c =>
      `<option value="" disabled>${c.service} · ${c.name} — used by ${c.taken_by}</option>`
    ).join("");
  syncChannel();
}

function syncChannel(){
  const opt = $("#f-channel").selectedOptions[0];
  if (!opt || !opt.value) return;
  const c = CHANNELS.find(x => x.id === opt.value);
  if (!c) return;
  if (!$("#f-slug").value) $("#f-slug").value =
    (c.name || "campaign").toLowerCase().replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "").slice(0, 20) + "_" + c.service.slice(0, 2);
  const nm = $("#new-msgs"); nm.innerHTML = "";
  if (c.reminders){
    msg(nm, "bad",
      "This channel defaults to <b>reminder mode</b> — Buffer will only send a " +
      "push notification instead of publishing. Turn reminders off in Buffer, " +
      "or it will never post unattended.");
  }
}
$("#f-channel").onchange = syncChannel;

$("#new-btn").onclick = () => {
  const p = $("#new-panel");
  const opening = p.style.display === "none";
  p.style.display = opening ? "block" : "none";
  if (opening) loadKeys().then(loadChannels);
};
$("#cancel-btn").onclick = () => { $("#new-panel").style.display = "none"; };

$("#create-btn").onclick = async (e) => {
  const nm = $("#new-msgs"); nm.innerHTML = "";
  e.target.disabled = true;
  let service, channelId;
  if (MANUAL){
    service = $("#f-service").value;
    channelId = $("#f-channel-id").value.trim();
    if (!channelId){
      msg(nm, "bad", "Paste the Buffer channel ID, or add your Buffer key to " +
                     "<code>.env</code> to pick from a list.");
      e.target.disabled = false; return;
    }
  } else {
    const opt = $("#f-channel").selectedOptions[0];
    const chan = CHANNELS.find(x => x.id === (opt && opt.value));
    if (!chan){
      msg(nm, "bad", "Pick a Buffer channel first.");
      e.target.disabled = false; return;
    }
    service = chan.service; channelId = chan.id;
  }
  const body = {
    slug: $("#f-slug").value.trim().toLowerCase(),
    service: service,
    channel_id: channelId,
    api_key_secret: $("#f-key").value || "BUFFER_API_KEY",
    posts_per_day: +$("#f-ppd").value,
    start_hour: +$("#f-start").value,
    copy_descriptions: $("#f-copy").checked,
  };
  if (!$("#f-share").checked) body.assets_release = "";
  const r = await (await fetch("/api/campaigns", {method:"POST",
    body: JSON.stringify(body)})).json();
  e.target.disabled = false;

  if (!r.ok){ msg(nm, "bad", r.error); return; }
  msg(nm, "ok", `Created <b>${r.slug}</b> — ${r.files.length} files written.`);
  if (r.required_secrets.length){
    msg(nm, "warn", "Still needs: " + r.required_secrets.map(s =>
      `<code>${s}</code>`).join(", "));
  }
  msg(nm, "warn", "It starts paused (<code>dry_run</code>). " +
      "Hit <b>Publish to GitHub</b> above so the workflows can see it.");

  // Land on the campaign that was just created. Staying on the old one meant
  // filling in a form, being told it worked, and seeing nothing change.
  await pickCampaign(r.slug);
  await loadChannels();
  $("#new-panel").style.display = "none";
  const done = $("#up-msgs"); done.innerHTML = "";
  msg(done, "ok", `Now showing <b>${esc(r.slug)}</b>. Drop its clips in below —
    or if it shares a library, they are already here.`);
};

$("#save").onclick = async () => {
  const r = await (await fetch("/api/descriptions",{method:"POST",
    body: JSON.stringify({text: $("#bank").value})})).json();
  const bm = $("#bank-msgs"); bm.innerHTML = "";
  msg(bm,"ok",`Saved — ${r.count} descriptions.`);
  r.errors.forEach(e => msg(bm,"bad",e));
  refresh(); loadPending();
};

$("#preview").onclick = async () => {
  const r = await (await fetch("/api/plan")).json();
  const el = $("#plan"); el.style.display = "block";
  if (!r.ok){ el.textContent = r.error; return; }
  el.textContent = r.items.length
    ? r.items.map(i => {
        const mark = {ok:"OK ", warned:" ! ", rejected:" x "}[i.verdict];
        const arrow = i.verdict === "rejected" ? "skipped" : i.target;
        return `${mark} ${i.source}\\n      -> ${arrow}` +
               (i.notes.length ? "\\n      " + i.notes.join("\\n      ") : "");
      }).join("\\n")
    : "inbox is empty";
};

$("#upload").onclick = async (e) => {
  e.target.disabled = true; e.target.textContent = "Uploading…";
  const um = $("#up-msgs"); um.innerHTML = "";
  try {
    const r = await (await fetch("/api/ingest",{method:"POST"})).json();
    if (r.ok){
      const fed = (STATE && STATE.library && STATE.library.campaigns) || [];
      msg(um,"ok",`Uploaded ${r.uploaded.length}: ${r.uploaded.join(", ")}` +
                  (r.skipped ? ` · ${r.skipped} skipped` : "") +
                  (fed.length > 1
                    ? ` — now in the mix for ${fed.join(", ")}.`
                    : ` — now in the mix.`));
    } else msg(um,"bad",r.error);
  } catch(err){ msg(um,"bad",String(err)); }
  e.target.disabled = false; e.target.textContent = "Upload to GitHub";
  // Refresh past the cached Release listing: the clips that just landed are
  // the ones the operator wants to see in the mix.
  refresh(); loadClips(true); loadPending();
};


/* ── Charts ───────────────────────────────────────────────────────────────
   Inline SVG, no libraries. Colour is assigned by ENTITY (platform), fixed
   order, never by rank — a filter that drops a series must not repaint the
   survivors. Text always wears ink tokens; the swatch beside it carries
   identity, never the text itself.                                        */
let CHARTS = null, CMETRIC = null, CASSET = "hooks";
const SERIES_VAR = {instagram:"--s1", tiktok:"--s2", youtube:"--s3"};
const svar = s => getComputedStyle(document.documentElement)
                    .getPropertyValue(SERIES_VAR[s] || "--s1").trim() || "#888";
const esc = t => String(t).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const TIP = document.createElement("div"); TIP.className = "tip"; document.body.appendChild(TIP);
function tipShow(x, y, html){
  TIP.innerHTML = html; TIP.style.opacity = "1";
  const r = TIP.getBoundingClientRect();
  TIP.style.left = Math.min(x + 14, innerWidth - r.width - 10) + "px";
  TIP.style.top  = Math.max(8, y - r.height - 12) + "px";
}
function tipHide(){ TIP.style.opacity = "0"; }

function niceMax(v){
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / mag * 2) / 2 * mag;
}
const shortDate = d => d.slice(5).replace("-", "/");

/* Monotone cubic interpolation (Fritsch–Carlson).

   A plain cubic bezier through data points OVERSHOOTS between them — it draws
   peaks and dips that are not in the data, which on an analytics chart is a
   lie rather than a flourish. Monotone cubic constrains the tangents so the
   curve can never leave the interval between two adjacent values: it is smooth
   AND it only ever shows numbers that exist. */
function monotonePath(pts){
  const n = pts.length;
  if (n < 2) return "";
  if (n === 2) return `M${pts[0][0]},${pts[0][1]}L${pts[1][0]},${pts[1][1]}`;

  const dx = [], dy = [], slope = [];
  for (let i = 0; i < n-1; i++){
    dx[i] = pts[i+1][0] - pts[i][0];
    dy[i] = pts[i+1][1] - pts[i][1];
    slope[i] = dy[i] / (dx[i] || 1);
  }
  const m = [slope[0]];
  for (let i = 1; i < n-1; i++){
    // A sign change means a local extremum: flatten the tangent so the curve
    // turns exactly at the data point instead of sailing past it.
    m[i] = slope[i-1] * slope[i] <= 0 ? 0 : (slope[i-1] + slope[i]) / 2;
  }
  m[n-1] = slope[n-2];
  for (let i = 0; i < n-1; i++){
    if (slope[i] === 0){ m[i] = m[i+1] = 0; continue; }
    const a = m[i]/slope[i], b = m[i+1]/slope[i], h = Math.hypot(a,b);
    if (h > 3){ m[i] = 3*a/h*slope[i]; m[i+1] = 3*b/h*slope[i]; }
  }

  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n-1; i++){
    const t = dx[i] / 3;
    d += `C${(pts[i][0]+t).toFixed(1)},${(pts[i][1]+m[i]*t).toFixed(1)}` +
         ` ${(pts[i+1][0]-t).toFixed(1)},${(pts[i+1][1]-m[i+1]*t).toFixed(1)}` +
         ` ${pts[i+1][0].toFixed(1)},${pts[i+1][1].toFixed(1)}`;
  }
  return d;
}

let GID = 0;
/* Vertical fade from a mark's own colour to nothing. Kept low-opacity so three
   overlapping series stay individually readable — a heavy fill would turn the
   topmost series into a mask over the others. */
function fadeDef(color, from, to){
  const id = "fade" + (++GID);
  return [id, `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="${color}" stop-opacity="${from}"/>
    <stop offset="100%" stop-color="${color}" stop-opacity="${to}"/>
  </linearGradient>`];
}

/* Multi-series line. 2px strokes, 8px hover markers, crosshair + shared
   tooltip — the default interaction for a time series. */
function lineChart(el, seriesMap, opts){
  const names = Object.keys(seriesMap).filter(n => seriesMap[n].length);
  if (!names.length){ el.innerHTML = `<div class="hint">No data yet.</div>`; return; }
  const dates = [...new Set(names.flatMap(n => seriesMap[n].map(p => p[0])))].sort();
  if (dates.length < 2){
    el.innerHTML = `<div class="hint">Only one snapshot so far — the line
      appears once the metrics job has run twice (daily at 06:30 UTC).</div>`;
    return;
  }
  const W = el.clientWidth || 900, H = opts.h || 240;
  const P = {t:12, r:14, b:26, l:46};
  const max = niceMax(Math.max(...names.flatMap(n => seriesMap[n].map(p => p[1]))));
  const x = i => P.l + (i / (dates.length - 1)) * (W - P.l - P.r);
  const y = v => H - P.b - (v / max) * (H - P.t - P.b);

  let g = "";
  for (let t = 0; t <= 4; t++){
    const v = max * t / 4, yy = y(v);
    g += `<line class="gridline" x1="${P.l}" y1="${yy}" x2="${W-P.r}" y2="${yy}"/>
          <text class="axis" x="${P.l-8}" y="${yy+3.5}" text-anchor="end">${fmt(v,"count")}</text>`;
  }
  dates.forEach((d,i) => {
    if (dates.length > 8 && i % 2) return;
    g += `<text class="axis" x="${x(i)}" y="${H-8}" text-anchor="middle">${shortDate(d)}</text>`;
  });

  let defs = "";
  names.forEach(n => {
    const byDate = Object.fromEntries(seriesMap[n]);
    const pts = dates.map((d,i) => byDate[d] === undefined ? null : [x(i), y(byDate[d])])
                     .filter(Boolean);
    if (pts.length < 2) return;
    const col = svar(n);
    const path = monotonePath(pts);
    const [fid, fdef] = fadeDef(col, 0.22, 0);
    defs += fdef;
    // Area first, line over it, so the stroke stays crisp against the fill.
    g += `<path d="${path}L${pts[pts.length-1][0].toFixed(1)},${H-P.b}L${
            pts[0][0].toFixed(1)},${H-P.b}Z" fill="url(#${fid})"/>`;
    g += `<path d="${path}" fill="none" stroke="${col}" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round"/>`;
    const last = pts[pts.length-1];
    // Halo then dot: reads as a lit endpoint without adding a second mark.
    g += `<circle cx="${last[0]}" cy="${last[1]}" r="7" fill="${col}" opacity=".18"/>
          <circle cx="${last[0]}" cy="${last[1]}" r="3.5" fill="${col}"
            stroke="var(--panel)" stroke-width="2"/>`;
  });
  g = `<defs>${defs}</defs>` + g;

  g += `<line id="cross" y1="${P.t}" y2="${H-P.b}" stroke="var(--line-2)"
          stroke-width="1" style="opacity:0"/><g id="dots"></g>`;
  el.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(opts.label||"time series")}">${g}
      <rect x="${P.l}" y="0" width="${W-P.l-P.r}" height="${H}" fill="transparent"/></svg>`;

  const svg = el.querySelector("svg");
  const cross = svg.querySelector("#cross"), dots = svg.querySelector("#dots");
  svg.addEventListener("mousemove", ev => {
    const bb = svg.getBoundingClientRect();
    const px = (ev.clientX - bb.left) / bb.width * W;
    let i = Math.round((px - P.l) / ((W-P.l-P.r) / (dates.length-1)));
    i = Math.max(0, Math.min(dates.length-1, i));
    const d = dates[i];
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
    cross.style.opacity = "1";
    dots.innerHTML = names.map(n => {
      const v = Object.fromEntries(seriesMap[n])[d];
      return v === undefined ? "" :
        `<circle cx="${x(i)}" cy="${y(v)}" r="4.5" fill="${svar(n)}"
           stroke="var(--panel)" stroke-width="2"/>`;
    }).join("");
    tipShow(ev.clientX, ev.clientY,
      `<div class="tt">${d}</div>` + names.map(n => {
        const v = Object.fromEntries(seriesMap[n])[d];
        return v === undefined ? "" :
          `<div class="tr"><span class="sw" style="background:${svar(n)}"></span>
             ${n} <b class="num">${fmt(v, opts.unit)}</b></div>`;
      }).join(""));
  });
  svg.addEventListener("mouseleave", () => {
    cross.style.opacity = "0"; dots.innerHTML = ""; tipHide();
  });
}

/* Horizontal bars: magnitude across identity. 4px rounded data-end, 2px gap. */
function barsH(el, rows, opts){
  if (!rows.length){ el.innerHTML = `<div class="hint">No data yet.</div>`; return; }
  const W = el.clientWidth || 420, rowH = opts.rowH || 26, L = opts.labelW || 108;
  const H = rows.length * rowH;
  const max = Math.max(...rows.map(r => r.value)) || 1;
  let hdefs = "";
  const g = rows.map((r,i) => {
    const w = Math.max(2, (r.value / max) * (W - L - 56));
    const yy = i * rowH;
    const base = r.color || "var(--bar)";
    const hid = "hb" + (++GID);
    // Horizontal fade: full strength at the axis, softening toward the tip, so
    // the eye lands on the baseline the bars are actually measured from.
    hdefs += `<linearGradient id="${hid}" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="${base}" stop-opacity="1"/>
      <stop offset="100%" stop-color="${base}" stop-opacity=".62"/></linearGradient>`;
    const col = `url(#${hid})`;
    return `<text class="axis" x="0" y="${yy + rowH/2 + 3.5}"
              style="font-size:11px;fill:var(--ink-2)">${esc(r.label)}</text>
      <rect class="bar" x="${L}" y="${yy + 4}" width="${w}" height="${rowH - 10}"
        rx="4" fill="${col}" data-i="${i}"/>
      <text class="axis" x="${L + w + 8}" y="${yy + rowH/2 + 3.5}"
        style="fill:var(--ink-2)">${fmt(r.value, opts.unit)}</text>`;
  }).join("");
  el.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(opts.label||"bars")}"><defs>${hdefs}</defs>${g}</svg>`;
  el.querySelectorAll("rect.bar").forEach(rect => {
    rect.addEventListener("mousemove", ev => {
      const r = rows[+rect.dataset.i];
      tipShow(ev.clientX, ev.clientY,
        `<div class="tr"><span class="sw" style="background:${r.color||"var(--bar)"}"></span>
           ${esc(r.label)} <b class="num">${fmt(r.value, opts.unit)}</b></div>` +
        (r.note ? `<div class="tt" style="margin:5px 0 0">${esc(r.note)}</div>` : ""));
    });
    rect.addEventListener("mouseleave", tipHide);
  });
}

/* Vertical bars: magnitude over an ordered domain (days, hours). */
function barsV(el, rows, opts){
  if (!rows.length){ el.innerHTML = `<div class="hint">No data yet.</div>`; return; }
  const W = el.clientWidth || 420, H = opts.h || 150, P = {t:10,r:6,b:22,l:30};
  const max = niceMax(Math.max(...rows.map(r => r.value)));
  const bw = (W - P.l - P.r) / rows.length;
  let g = "";
  for (let t = 0; t <= 2; t++){
    const v = max*t/2, yy = H - P.b - (v/max)*(H-P.t-P.b);
    g += `<line class="gridline" x1="${P.l}" y1="${yy}" x2="${W-P.r}" y2="${yy}"/>
          <text class="axis" x="${P.l-6}" y="${yy+3.5}" text-anchor="end">${fmt(v,"count")}</text>`;
  }
  let vdefs = "";
  g += rows.map((r,i) => {
    const h = (r.value/max) * (H-P.t-P.b);
    const xx = P.l + i*bw, yy = H - P.b - h;
    const base = r.color || "var(--bar)";
    const vid = "vb" + (++GID);
    vdefs += `<linearGradient id="${vid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${base}" stop-opacity="1"/>
      <stop offset="100%" stop-color="${base}" stop-opacity=".55"/></linearGradient>`;
    return `<rect class="bar" x="${xx+1}" y="${yy}" width="${Math.max(1,bw-2)}"
        height="${Math.max(r.value?2:0,h)}" rx="3"
        fill="url(#${vid})" data-i="${i}"/>` +
      (r.tick ? `<text class="axis" x="${xx+bw/2}" y="${H-7}"
        text-anchor="middle">${esc(r.tick)}</text>` : "");
  }).join("");
  el.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(opts.label||"bars")}"><defs>${vdefs}</defs>${g}</svg>`;
  el.querySelectorAll("rect.bar").forEach(rect => {
    rect.addEventListener("mousemove", ev => {
      const r = rows[+rect.dataset.i];
      tipShow(ev.clientX, ev.clientY,
        `<div class="tt">${esc(r.label)}</div>
         <div class="tr"><b class="num">${fmt(r.value,"count")}</b> ${esc(opts.noun||"")}</div>`);
    });
    rect.addEventListener("mouseleave", tipHide);
  });
}

function drawTable(el, seriesMap){
  const names = Object.keys(seriesMap).filter(n => seriesMap[n].length);
  const dates = [...new Set(names.flatMap(n => seriesMap[n].map(p => p[0])))].sort();
  el.innerHTML = `<table class="dv"><thead><tr><th>date</th>` +
    names.map(n => `<th>${n}</th>`).join("") + `</tr></thead><tbody>` +
    dates.map(d => `<tr><td>${d}</td>` + names.map(n => {
      const v = Object.fromEntries(seriesMap[n])[d];
      return `<td class="num">${v === undefined ? "—" : fmt(v,"count")}</td>`;
    }).join("") + `</tr>`).join("") + `</tbody></table>`;
}

function drawCharts(){
  if (!CHARTS) return;
  const c = CHARTS;
  const isRate = CMETRIC === "engagementRate";

  $("#c-legend").innerHTML = c.services.map(s =>
    `<span class="lg"><span class="sw" style="background:${svar(s)}"></span>${s}</span>`
  ).join("");

  lineChart($("#c-main"), c.series[CMETRIC] || {},
            {h:250, unit:isRate?"percentage":"count", label:CMETRIC+" over time"});
  drawTable($("#c-tablewrap"), c.series[CMETRIC] || {});

  // Share: a rate cannot be shared out, so fall back to views.
  const shareMetric = isRate ? "views" : CMETRIC;
  $("#c-share-metric").textContent = shareMetric;
  const sh = (c.share[shareMetric] || []).slice().sort((a,b) => b.value - a.value);
  const tot = sh.reduce((a,b) => a + b.value, 0) || 1;
  barsH($("#c-share"), sh.map(r => ({
    label: r.service, value: r.value, color: svar(r.service),
    note: `${(r.value/tot*100).toFixed(0)}% of all ${shareMetric}`,
  })), {unit:"count", label:"share by platform"});

  const days = [...new Set(Object.values(c.volume).flat().map(p => p[0]))].sort();
  barsV($("#c-volume"), days.map(d => ({
    label: d, tick: shortDate(d), value: c.services.reduce((a,s) =>
      a + (Object.fromEntries(c.volume[s]||[])[d] || 0), 0),
  })), {h:150, noun:"videos", label:"videos rendered per day"});

  barsV($("#c-hours"), c.hours.map((n,h) => ({
    label: `${String(h).padStart(2,"0")}:00`,
    tick: h % 6 === 0 ? String(h).padStart(2,"0") : "", value: n,
  })), {h:150, noun:"posts scheduled", label:"publish hour distribution"});

  $("#c-asset-kind").innerHTML = ["hooks","bodies","music"].map(k =>
    `<button data-k="${k}" aria-pressed="${k===CASSET}">${k}</button>`).join("");
  $("#c-asset-kind").querySelectorAll("button").forEach(b =>
    b.onclick = () => { CASSET = b.dataset.k; drawCharts(); });
  barsH($("#c-assets"), (c.assets[CASSET]||[]).map(([n,v]) =>
    ({label:n, value:v})), {unit:"count", labelW:124, label:"asset usage"});
}

async function loadCharts(){
  CHARTS = await (await fetch("/api/charts")).json();
  if (!CMETRIC || !CHARTS.series[CMETRIC]) CMETRIC = CHARTS.metrics[0] || null;
  $("#c-metric").innerHTML = CHARTS.metrics.map(m =>
    `<option value="${m}" ${m===CMETRIC?"selected":""}>${m}</option>`).join("");
  drawCharts();
}
$("#c-metric").onchange = e => { CMETRIC = e.target.value; drawCharts(); };
$("#c-table").onclick = e => {
  const showing = $("#c-tablewrap").style.display !== "none";
  $("#c-tablewrap").style.display = showing ? "none" : "block";
  $("#c-main").style.display = showing ? "block" : "none";
  e.target.setAttribute("aria-pressed", String(!showing));
};
addEventListener("resize", () => { clearTimeout(window._cr);
  window._cr = setTimeout(drawCharts, 180); });

buildZones(); loadCampaigns(); refresh(); loadClips(); loadInsights();
loadQueue(); loadQuota();
loadSecrets();
loadRevenue();
loadMetrics();
loadPending(); loadCharts();
setInterval(() => { refresh(); loadPending(); }, 5000);
setInterval(() => { loadMetrics(); loadCharts(); }, 300000);
</script>
</body>
</html>
"""
