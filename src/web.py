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
from src.config import CampaignConfig, load_campaign
from src.descriptions import load_bank, parse_bank, validate_bank
from src.errors import UgcError
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
from src.metrics import load_metrics
from src.models import PartKind
from src.platforms import Service
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

    def _uploaded_counts(self) -> dict[str, int]:
        """What is already in the assets Release, by role."""
        archive = self.inbox / ARCHIVE_DIR
        counts = {kind.value: 0 for kind in PartKind}
        if archive.is_dir():
            for path in archive.iterdir():
                for kind in PartKind:
                    if path.name.lower().startswith(kind.value):
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
        self.inbox = self.repo_root / "inbox" / slug
        self._music_beds = None
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
        import os

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

        archive = self.inbox / ARCHIVE_DIR
        tracks = [
            p for p in (archive.iterdir() if archive.is_dir() else [])
            if p.is_file() and p.name.lower().startswith("music")
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
            if latest is None:
                out.append({
                    "campaign": directory.name, "service": None,
                    "has_data": False, "metrics": [], "series": {},
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
            })
        return {"campaigns": out}

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
            "uploaded": counts,
            "descriptions": {
                "text": bank_text,
                "count": captions,
                "errors": errors,
                "notes": notes,
            },
            "health": {
                "combinations": total,
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
        existing = store.list_assets(f"assets-{self.config.slug}") if store else []
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
        tag = f"assets-{self.config.slug}"
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
        import os

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
            elif route == "/api/keys":
                self._json(app.key_slots())
            elif route == "/api/pending":
                self._json(app.pending_changes())
            elif route == "/api/metrics":
                self._json(app.metrics())
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

                elif route == "/api/ingest":
                    self._json(app.upload())

                else:
                    self._json({"error": "not found"}, 404)
            except UgcError as exc:
                self._json({"ok": False, "error": str(exc)}, 200)
            except (ValueError, OSError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)

        def do_DELETE(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/inbox":
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
<style>
  :root {
    --bg:#0e0f12; --panel:#16181d; --line:#262a33; --text:#e6e8ee;
    --dim:#8b93a5; --accent:#5b8cff; --ok:#3fb950; --warn:#d29922; --bad:#f85149;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg:#f6f7f9; --panel:#fff; --line:#e2e5ea; --text:#14171f;
      --dim:#666e7d; --accent:#2f6bff; --ok:#1a7f37; --warn:#9a6700; --bad:#cf222e;
    }
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--text);
    font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif;
  }
  header {
    padding:18px 24px; border-bottom:1px solid var(--line);
    display:flex; align-items:baseline; gap:12px; flex-wrap:wrap;
  }
  h1 { font-size:15px; margin:0; font-weight:600; letter-spacing:-.01em; }
  .tag {
    font-size:11px; color:var(--dim); border:1px solid var(--line);
    padding:2px 8px; border-radius:99px;
  }
  main { padding:24px; max-width:1100px; margin:0 auto; }
  .zones { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
  @media (max-width:820px) { .zones { grid-template-columns:1fr; } }
  .zone {
    background:var(--panel); border:1.5px dashed var(--line); border-radius:12px;
    padding:18px; min-height:190px; transition:border-color .15s,background .15s;
  }
  .zone.over { border-color:var(--accent); background:color-mix(in srgb,var(--accent) 8%,var(--panel)); }
  .zone h2 { font-size:13px; margin:0 0 2px; font-weight:600; }
  .zone .sub { font-size:11px; color:var(--dim); margin-bottom:12px; }
  .files { list-style:none; margin:0; padding:0; font-size:12px; }
  .files li {
    display:flex; justify-content:space-between; gap:8px; align-items:center;
    padding:5px 0; border-top:1px solid var(--line);
  }
  .files .nm { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .files button {
    background:none; border:none; color:var(--dim); cursor:pointer;
    font-size:14px; padding:0 2px;
  }
  .files button:hover { color:var(--bad); }
  .empty { font-size:12px; color:var(--dim); font-style:italic; }
  section { margin-top:26px; }
  h3 { font-size:12px; text-transform:uppercase; letter-spacing:.06em;
       color:var(--dim); margin:0 0 10px; font-weight:600; }
  textarea {
    width:100%; min-height:230px; background:var(--panel); color:var(--text);
    border:1px solid var(--line); border-radius:10px; padding:14px;
    font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace; resize:vertical;
  }
  textarea:focus { outline:none; border-color:var(--accent); }
  .row { display:flex; gap:10px; align-items:center; margin-top:10px; flex-wrap:wrap; }
  button.act {
    background:var(--accent); color:#fff; border:none; padding:9px 16px;
    border-radius:8px; font-size:13px; font-weight:500; cursor:pointer;
  }
  button.act:hover { filter:brightness(1.08); }
  button.act:disabled { opacity:.5; cursor:default; }
  button.ghost { background:none; border:1px solid var(--line); color:var(--text); }
  .stats {
    background:var(--panel); border:1px solid var(--line); border-radius:12px;
    padding:16px 18px;
  }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:14px; }
  .stat .n { font-size:21px; font-weight:600; letter-spacing:-.02em; }
  .stat .l { font-size:11px; color:var(--dim); }
  .msg { font-size:12px; padding:9px 12px; border-radius:8px; margin-top:9px; }
  .msg.ok  { color:var(--ok);   background:color-mix(in srgb,var(--ok) 12%,transparent); }
  .msg.warn{ color:var(--warn); background:color-mix(in srgb,var(--warn) 12%,transparent); }
  .msg.bad { color:var(--bad);  background:color-mix(in srgb,var(--bad) 12%,transparent); }
  .plan { font:12px/1.6 ui-monospace,Menlo,monospace; white-space:pre-wrap;
          background:var(--panel); border:1px solid var(--line);
          border-radius:10px; padding:14px; margin-top:12px; }
  .hint { font-size:12px; color:var(--dim); margin-top:6px; }
  header select {
    background:var(--panel); color:var(--text); border:1px solid var(--line);
    border-radius:8px; padding:5px 9px; font-size:13px; font-weight:600;
  }
  .newc {
    background:var(--panel); border:1px solid var(--line); border-radius:12px;
    padding:18px; margin:0 24px 4px;
  }
  .newc h3 { margin-top:0; }
  .frow { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
          gap:12px; margin-bottom:10px; }
  .frow label { display:flex; flex-direction:column; gap:4px;
                font-size:11px; color:var(--dim); }
  .frow input, .frow select {
    background:var(--bg); color:var(--text); border:1px solid var(--line);
    border-radius:8px; padding:7px 9px; font-size:13px;
  }
  .chk { display:flex; align-items:center; gap:7px; font-size:12px;
         color:var(--dim); margin-bottom:6px; }
  .dead { color:var(--bad); }
  .sync {
    margin:0 24px 4px; padding:11px 16px; border-radius:10px;
    background:color-mix(in srgb,var(--warn) 14%,var(--panel));
    border:1px solid color-mix(in srgb,var(--warn) 35%,var(--line));
    display:flex; align-items:center; gap:14px; font-size:13px;
  }
  .sync span { flex:1; }
  .perf-card {
    background:var(--panel); border:1px solid var(--line); border-radius:12px;
    padding:16px 18px; margin-bottom:12px;
  }
  .perf-head { display:flex; align-items:baseline; gap:10px; margin-bottom:14px; }
  .perf-head .who { font-size:13px; font-weight:600; }
  .perf-head .when { font-size:11px; color:var(--dim); }
  .mrow { display:grid; grid-template-columns:repeat(auto-fit,minmax(108px,1fr)); gap:14px; }
  .m .v { font-size:19px; font-weight:600; letter-spacing:-.02em; }
  .m .k { font-size:11px; color:var(--dim); }
  .m .d { font-size:11px; margin-left:5px; font-weight:500; }
  .up   { color:var(--ok); }
  .down { color:var(--bad); }
  .flat { color:var(--dim); }
  .spark { display:block; margin-top:6px; }
</style>
</head>
<body>
<header>
  <h1>ugc-factory</h1>
  <select id="switcher" title="switch campaign"></select>
  <span class="tag" id="t-service">…</span>
  <span class="tag" id="t-cadence">…</span>
  <span class="tag" id="t-dry">…</span>
  <button class="act ghost" id="new-btn" style="margin-left:auto">+ New campaign</button>
</header>

<div id="sync-bar" style="display:none">
  <div class="sync">
    <span id="sync-text"></span>
    <button class="act" id="publish-btn">Publish to GitHub</button>
  </div>
</div>

<div id="new-panel" style="display:none">
  <div class="newc">
    <h3>New campaign</h3>
    <div class="frow">
      <label>Buffer account<select id="f-key"></select></label>
      <label>Channel<select id="f-channel"><option value="">loading…</option></select></label>
      <label>Slug<input id="f-slug" placeholder="brand_tiktok" autocomplete="off"></label>
      <label>Posts/day<input id="f-ppd" type="number" min="1" max="24" value="12"></label>
      <label>Start hour<input id="f-start" type="number" min="0" max="23" value="15"></label>
    </div>
    <label class="chk"><input type="checkbox" id="f-share" checked>
      Share this campaign's asset library (no re-uploading clips)</label>
    <label class="chk"><input type="checkbox" id="f-copy" checked>
      Copy the current descriptions</label>
    <div class="row">
      <button class="act" id="create-btn">Create</button>
      <button class="act ghost" id="cancel-btn">Cancel</button>
    </div>
    <div id="new-msgs"></div>
  </div>
</div>

<main>
  <div class="zones" id="zones"></div>
  <div class="hint">Drag files in, or click a zone to browse. Names don't matter — correct ones are generated on upload.</div>

  <section>
    <h3>Descriptions <span style="text-transform:none;font-weight:400">— the text each video is posted with</span></h3>
    <textarea id="bank" spellcheck="false" placeholder="One description per block, blank line between blocks."></textarea>
    <div class="row">
      <button class="act ghost" id="save">Save descriptions</button>
      <span id="bank-count" style="font-size:12px;color:var(--dim)"></span>
    </div>
    <div id="bank-msgs"></div>
  </section>

  <section>
    <h3>Library</h3>
    <div class="stats">
      <div class="grid" id="stats"></div>
      <div id="health"></div>
    </div>
  </section>

  <section>
    <h3>Performance <span style="text-transform:none;font-weight:400" id="perf-note"></span></h3>
    <div id="perf"></div>
  </section>

  <section>
    <h3>Upload</h3>
    <div class="row">
      <button class="act ghost" id="preview">Preview plan</button>
      <button class="act" id="upload">Upload to GitHub</button>
    </div>
    <div id="up-msgs"></div>
    <div class="plan" id="plan" style="display:none"></div>
  </section>
</main>

<script>
const KINDS = [
  ["hooks",  "Hooks",  "the first 1–2s that stop the scroll", "video/*"],
  ["bodies", "Bodies", "your main videos",                    "video/*"],
  ["music",  "Music",  "royalty-free tracks only",            "audio/*"],
];
const $ = s => document.querySelector(s);
let STATE = null;

function bytes(n){ return n > 1e6 ? (n/1e6).toFixed(1)+" MB" : Math.max(1,Math.round(n/1e3))+" KB"; }

function buildZones(){
  $("#zones").innerHTML = KINDS.map(([k,label,sub,accept]) => `
    <div class="zone" data-kind="${k}">
      <h2>${label}</h2>
      <div class="sub">${sub}</div>
      <ul class="files" id="f-${k}"></ul>
      <input type="file" multiple accept="${accept}" id="i-${k}" style="display:none">
    </div>`).join("");

  KINDS.forEach(([k]) => {
    const zone = document.querySelector(`.zone[data-kind="${k}"]`);
    const input = $(`#i-${k}`);
    zone.addEventListener("click", e => { if (e.target.tagName !== "BUTTON") input.click(); });
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

function msg(el, cls, text){
  el.innerHTML += `<div class="msg ${cls}">${text}</div>`;
}

function render(s){
  STATE = s;
  $("#t-service").textContent  = s.service;
  $("#t-cadence").textContent  = s.posts_per_day + "/day";
  $("#t-dry").textContent      = s.dry_run ? "dry run" : "LIVE";
  $("#t-dry").style.color      = s.dry_run ? "" : "var(--warn)";

  KINDS.forEach(([k]) => {
    const list = s.staged[k] || [];
    $(`#f-${k}`).innerHTML = list.length
      ? list.map(f => `<li><span class="nm">${f.name}</span>
          <span style="color:var(--dim);font-size:11px">${bytes(f.size)}</span>
          <button title="remove" onclick="event.stopPropagation();remove('${k}','${
            f.name.replace(/'/g,"\\\\'")}')">×</button></li>`).join("")
      : `<li style="border:none"><span class="empty">nothing staged</span></li>`;
  });

  const h = s.health, u = s.uploaded;
  $("#stats").innerHTML = `
    <div class="stat"><div class="n">${u.hook}</div><div class="l">hooks uploaded</div></div>
    <div class="stat"><div class="n">${u.body}</div><div class="l">bodies uploaded</div></div>
    <div class="stat"><div class="n">${u.music}</div><div class="l">music uploaded</div></div>
    <div class="stat"><div class="n">${s.descriptions.count}</div><div class="l">descriptions</div></div>
    <div class="stat"><div class="n">${h.combinations}</div><div class="l">combinations</div></div>
    <div class="stat"><div class="n">${h.runway_days}</div><div class="l">days runway</div></div>`;

  const hv = $("#health"); hv.innerHTML = "";
  if (h.runway_days < h.min_runway_days)
    msg(hv,"warn",`Runway ${h.runway_days}d is under the ${h.min_runway_days}d target — preflight will fail.`);
  h.warnings.forEach(w => msg(hv,"warn",w));
  if (!h.warnings.length && h.runway_days >= h.min_runway_days && h.combinations > 0)
    msg(hv,"ok","Library supports the configured cadence with no relaxation.");

  if (document.activeElement !== $("#bank")) $("#bank").value = s.descriptions.text;
  $("#bank-count").textContent = s.descriptions.count + " descriptions";
  const bm = $("#bank-msgs"); bm.innerHTML = "";
  s.descriptions.errors.forEach(e => msg(bm,"bad",e));
  s.descriptions.notes.slice(0,5).forEach(n => msg(bm,"warn",n));
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
  const r = await (await fetch("/api/publish", {method:"POST",
    body: JSON.stringify({})})).json();
  e.target.disabled = false; e.target.textContent = "Publish to GitHub";
  if (!r.ok){ $("#sync-text").innerHTML = `<b class="dead">${r.error}</b>`; return; }
  await loadPending();
};

async function loadCampaigns(){
  const r = await (await fetch("/api/campaigns")).json();
  const sel = $("#switcher");
  sel.innerHTML = r.campaigns.map(c =>
    `<option value="${c.slug}" ${c.slug===r.selected?"selected":""}>` +
    `${c.slug}${c.valid?"":" (broken)"}</option>`).join("");
  const broken = r.campaigns.filter(c => !c.valid);
  if (broken.length){
    const el = $("#perf");
    broken.forEach(c => msg(el, "bad", `${c.slug}: ${c.error}`));
  }
}

$("#switcher").onchange = async (e) => {
  await fetch("/api/select", {method:"POST",
    body: JSON.stringify({slug: e.target.value})});
  await refresh(); await loadMetrics();
};

let CHANNELS = [];

async function loadKeys(){
  const r = await (await fetch("/api/keys")).json();
  const sel = $("#f-key");
  sel.innerHTML = r.slots.map(s => {
    const note = s.used_by.length ? ` — ${s.used_by.join(", ")}`
               : s.available ? " — ready" : " — no key set";
    return `<option value="${s.name}" ${s.available?"":"data-missing=1"}>` +
           `${s.name}${note}</option>`;
  }).join("");
  // Default to an account that actually has a key on this machine.
  const firstReady = r.slots.find(s => s.available);
  if (firstReady) sel.value = firstReady.name;
}
$("#f-key").onchange = () => { loadChannels(); };

async function loadChannels(){
  const sel = $("#f-channel");
  const slot = $("#f-key").value || "BUFFER_API_KEY";
  const r = await (await fetch("/api/channels?slot=" + encodeURIComponent(slot))).json();
  if (!r.ok){
    sel.innerHTML = `<option value="">unavailable</option>`;
    msg($("#new-msgs"), "warn",
        `${r.error}<br><span style="opacity:.8">${r.hint||""}</span>`);
    return;
  }
  CHANNELS = r.channels;
  const usable = CHANNELS.filter(c => !c.taken_by && !c.disconnected && !c.locked);
  sel.innerHTML =
    (usable.length ? "" : `<option value="">no free channels</option>`) +
    usable.map(c =>
      `<option value="${c.id}" data-service="${c.service}">` +
      `${c.service} · ${c.name}${c.reminders?"  (reminder mode)":""}</option>`).join("") +
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
  // The slug is a suggestion, not a lock — it stays editable.
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
  const opt = $("#f-channel").selectedOptions[0];
  const chan = CHANNELS.find(x => x.id === (opt && opt.value));
  if (!chan){
    msg(nm, "bad", "Pick a Buffer channel first.");
    e.target.disabled = false; return;
  }
  const body = {
    slug: $("#f-slug").value.trim().toLowerCase(),
    service: chan.service,
    channel_id: chan.id,
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
  await loadCampaigns(); await loadPending(); await loadChannels();
};

$("#save").onclick = async () => {
  const r = await (await fetch("/api/descriptions",{method:"POST",
    body: JSON.stringify({text: $("#bank").value})})).json();
  const bm = $("#bank-msgs"); bm.innerHTML = "";
  msg(bm,"ok",`Saved — ${r.count} descriptions.`);
  r.errors.forEach(e => msg(bm,"bad",e));
  refresh();
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
      msg(um,"ok",`Uploaded ${r.uploaded.length}: ${r.uploaded.join(", ")}` +
                  (r.skipped ? ` · ${r.skipped} skipped` : ""));
    } else msg(um,"bad",r.error);
  } catch(err){ msg(um,"bad",String(err)); }
  e.target.disabled = false; e.target.textContent = "Upload to GitHub";
  refresh();
};

function sparkline(points, w, h){
  if (points.length < 2) return "";
  const vals = points.map(p => p[1]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = (max - min) || 1;
  const step = w / (points.length - 1);
  const d = vals.map((v,i) => `${i===0?"M":"L"}${(i*step).toFixed(1)},${(h - ((v-min)/span)*h).toFixed(1)}`).join("");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" fill="none">
    <path d="${d}" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
}

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

async function loadMetrics(){
  const r = await (await fetch("/api/metrics")).json();
  const el = $("#perf");
  const withData = r.campaigns.filter(c => c.has_data);

  if (!withData.length){
    el.innerHTML = `<div class="msg warn">No metrics cached yet. They are fetched
      once a day by the <code>metrics</code> workflow — networks also report
      engagement on a lag, so expect the first numbers a day after your first
      posts go live.</div>`;
    $("#perf-note").textContent = "";
    return;
  }

  $("#perf-note").textContent = "— cached daily, not live";
  el.innerHTML = withData.map(c => {
    const stale = c.updated_at ? new Date(c.updated_at).toLocaleString() : "unknown";
    return `<div class="perf-card">
      <div class="perf-head">
        <span class="who">${c.service || c.campaign}</span>
        <span class="when">${c.post_count} posts · snapshot ${c.date} · network data as of ${stale}</span>
      </div>
      <div class="mrow">
        ${c.metrics.map(m => `
          <div class="m">
            <div class="v">${fmt(m.value, m.unit)}${delta(m.change)}</div>
            <div class="k">${m.name}</div>
            ${sparkline(c.series[m.type] || [], 96, 22)}
          </div>`).join("")}
      </div>
    </div>`;
  }).join("");
}

buildZones(); loadCampaigns(); refresh(); loadMetrics(); loadPending();
setInterval(() => { refresh(); loadPending(); }, 5000);
// Metrics only change once a day; polling them like the inbox would be waste.
setInterval(loadMetrics, 300000);
</script>
</body>
</html>
"""
