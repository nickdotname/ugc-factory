"""Acceptance tests (SPEC §14) and the abstraction guarantees (SPEC §2.2, §15).

These assert the properties the whole design exists to provide, rather than the
behaviour of any single module.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.config import DedupeDimension, PostType, SelectionConfig, load_campaign
from src.errors import AuthError, InvalidPostError
from src.logging import StructuredLogger
from src.models import History, Queue, QueueItem, QueueStatus
from src.notify import Digest, Notifier
from src.ports import FrozenClock, SeededRng
from src.publishers.base import DryRunPublisher, PublishRequest, Publisher
from src.queue import claimable, depth_needed, load_queue, save_queue, stranded, transition
from src.selector import AssetLibrary, Relaxation, Selector, tuple_hash

from tests.fakes import FakeResponse, FakeSession

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 13, 5, 0, tzinfo=timezone.utc)


def log() -> StructuredLogger:
    return StructuredLogger({}, io.StringIO())


class TestAbstractionBoundaries:
    """SPEC §2.2 — boundaries are interfaces, and only they touch the outside."""

    FORBIDDEN = {
        "requests": {"assets.py", "notify.py", "buffer.py"},
        "subprocess": {"render.py", "vcs.py"},
        "random": {"ports.py"},
    }

    @pytest.mark.parametrize("module", ["requests", "subprocess", "random"])
    def test_only_boundary_modules_import_it(self, module: str) -> None:
        offenders = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            imports = f"import {module}" in text
            if imports and path.name not in self.FORBIDDEN[module]:
                offenders.append(path.name)
        assert not offenders, (
            f"{module} imported outside its boundary module: {offenders}"
        )

    def test_datetime_now_is_only_called_in_ports_and_logging(self) -> None:
        """Everything else takes an injected Clock."""
        allowed = {"ports.py", "logging.py"}
        offenders = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "datetime.now(" in text and path.name not in allowed:
                offenders.append(path.name)
        assert not offenders, f"datetime.now() outside ports: {offenders}"

    def test_no_bare_except(self) -> None:
        """SPEC §2.2 — never a bare `except`."""
        offenders = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip() in ("except:", "except Exception:  # noqa"):
                    offenders.append(f"{path.name}:{n}")
        assert not offenders, f"bare except found: {offenders}"

    def test_publisher_abc_has_no_buffer_specifics(self) -> None:
        """SPEC §16 — the seam TikTok slots into must stay backend-neutral."""
        text = (REPO_ROOT / "src" / "publishers" / "base.py").read_text(encoding="utf-8")
        for term in ("graphql", "api.buffer.com", "createPost", "schedulingType"):
            assert term not in text, f"Buffer detail {term!r} leaked into the ABC"


class TestNoCampaignSpecificLogic:
    """SPEC §2.2/§15 — a grep for 'clubs' in src/ must return nothing."""

    def test_src_is_free_of_campaign_slugs(self) -> None:
        offenders = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            if "clubs" in path.read_text(encoding="utf-8").lower():
                offenders.append(path.name)
        assert not offenders, f"campaign slug in src/: {offenders}"

    def test_adding_a_campaign_needs_no_code_change(self, tmp_path: Path) -> None:
        """SPEC §14 — add a dummy campaign with zero edits to src/."""
        src = REPO_ROOT / "campaigns" / "_template"
        dst = tmp_path / "dummy"
        shutil.copytree(src, dst)

        text = (dst / "config.yaml").read_text(encoding="utf-8")
        text = text.replace("slug: CHANGEME", "slug: dummy")
        text = text.replace("BUFFER_CHANNEL_CHANGEME", "BUFFER_CHANNEL_DUMMY")
        text = text.replace("DISCORD_WEBHOOK_CHANGEME", "DISCORD_WEBHOOK_DUMMY")
        (dst / "config.yaml").write_text(text, encoding="utf-8")

        config = load_campaign(tmp_path, "dummy")
        assert config.slug == "dummy"
        assert config.buffer.post_type is PostType.REEL
        assert config.posting.dry_run is True, \
            "a new campaign must start in dry run (SPEC §15 step 7)"


class TestQueueAcceptance:
    def test_buffer_queue_at_cap_pushes_nothing(self) -> None:
        """SPEC §14 — queue already at 10: push nothing, exit clean."""
        assert depth_needed(10, 10) == 0

    def test_crash_between_claimed_and_pushed_does_not_double_push(
        self, tmp_path: Path
    ) -> None:
        """SPEC §14 — kill the top-up job mid-push; the next run must not repush."""
        path = tmp_path / "queue.json"
        item = QueueItem(
            id="a", scheduled_for=NOW, video_url="https://x/v.mp4",
            caption="c", parts={},
        )
        q = Queue(generated_at=NOW, items=[item])
        transition(q.items[0], QueueStatus.CLAIMED, log=log())
        save_queue(path, q)   # the durable claim

        resumed = load_queue(path)
        assert claimable(resumed) == [], "a claimed item must not look pushable"
        assert [i.id for i in stranded(resumed)] == ["a"]

    def test_reconciliation_finds_the_post_and_completes_it(self) -> None:
        """When Buffer already has the post, record it rather than repushing."""
        from src.publishers.buffer import BufferPublisher

        s = FakeSession().route("POST", "api.buffer.com", FakeResponse(200, {
            "data": {"posts": {"edges": [{"node": {
                "id": "already", "dueAt": NOW.isoformat(),
                "status": "scheduled", "schedulingType": "automatic",
            }}]}}
        }))
        p = BufferPublisher("k", log(), organization_id="org", session=s,
                            sleep=lambda _s: None)
        assert p.find_scheduled_post("c", NOW) is not None


class TestSelectionAcceptance:
    def test_thirty_videos_have_zero_duplicate_tuples(self) -> None:
        """SPEC §14 — render 30 videos, zero duplicate tuples."""
        lib = AssetLibrary(
            hooks=tuple(f"hook_{i:02d}.mp4" for i in range(6)),
            bodies=tuple(f"body_{i:02d}.mp4" for i in range(8)),
            music=tuple(f"music_{i:02d}.mp3" for i in range(4)),
            captions=tuple(f"caption {i}" for i in range(12)),
        )
        sel = Selector(SelectionConfig(), FrozenClock(NOW), SeededRng(42), log())
        outcomes = sel.select_batch(lib, History(), 30, 1)
        hashes = [tuple_hash(o.selection, list(DedupeDimension)) for o in outcomes]
        assert len(set(hashes)) == 30
        assert all(o.relaxation is Relaxation.NONE for o in outcomes)

    def test_exhausted_caption_bank_relaxes_in_order_and_reports(self) -> None:
        """SPEC §14 — empty the caption bank below cooldown viability."""
        stream = io.StringIO()
        sel = Selector(
            SelectionConfig(caption_cooldown_days=14, hook_cooldown_days=3),
            FrozenClock(NOW), SeededRng(1), StructuredLogger({}, stream),
        )
        lib = AssetLibrary(hooks=("h.mp4",), bodies=("b1.mp4", "b2.mp4"),
                           music=(), captions=("only",))
        from src.models import HistoryEntry, Selection

        used = Selection(hook="h.mp4", bodies=("b1.mp4",), music=None, caption="only")
        hist = History(entries=[HistoryEntry(
            tuple_hash=tuple_hash(used, list(DedupeDimension)),
            timestamp=NOW - timedelta(days=1), item_id="x",
            hook="h.mp4", bodies=("b1.mp4",), music=None, caption="only",
        )])
        outcome = sel.select_one(lib, hist, 1)
        assert outcome.relaxation is Relaxation.CAPTION_COOLDOWN
        assert "dedupe_relaxed" in stream.getvalue()


class TestFailureHandling:
    def test_auth_failure_stops_rather_than_draining_the_queue(self) -> None:
        """SPEC §14 — force an auth failure; alert and stop."""
        from src.publishers.buffer import BufferPublisher

        s = FakeSession().route("POST", "api.buffer.com", FakeResponse(401))
        p = BufferPublisher("k", log(), organization_id="org", session=s,
                            sleep=lambda _s: None)
        with pytest.raises(AuthError) as exc:
            p.create_post(PublishRequest(
                channel_id="c", text="t", video_url="https://x/v.mp4",
                scheduled_for=NOW,
            ))
        assert exc.value.retryable is False
        assert len(s.calls) == 1, "an auth failure must not be retried"

    def test_reminder_mode_is_reported_not_silently_accepted(self) -> None:
        """SPEC §0 — reminder mode is not automation."""
        from src.publishers.buffer import BufferPublisher

        s = FakeSession().route("POST", "api.buffer.com", FakeResponse(200, {
            "data": {"createPost": {
                "__typename": "PostActionSuccess",
                "post": {"id": "p1", "dueAt": NOW.isoformat(),
                         "status": "scheduled", "schedulingType": "notification"},
            }}
        }))
        p = BufferPublisher("k", log(), organization_id="org", session=s,
                            sleep=lambda _s: None)
        with pytest.raises(InvalidPostError, match="not 'automatic'"):
            p.create_post(PublishRequest(
                channel_id="c", text="t", video_url="https://x/v.mp4",
                scheduled_for=NOW,
            ))


class TestDryRun:
    def test_dry_run_contacts_nothing(self) -> None:
        p: Publisher = DryRunPublisher(log())
        result = p.create_post(PublishRequest(
            channel_id="c", text="t", video_url="https://x/v.mp4", scheduled_for=NOW,
        ))
        assert result.post_id.startswith("dry-run-")


class TestNotifications:
    def test_disabled_event_is_not_sent(self) -> None:
        from src.config import NotifyEvent

        s = FakeSession()
        n = Notifier("https://hook", (NotifyEvent.FAILURE,), log(), session=s)
        assert n.notify(NotifyEvent.QUOTA_HIGH, "x") is False
        assert not s.calls

    def test_missing_webhook_does_not_raise(self) -> None:
        from src.config import NotifyEvent

        n = Notifier(None, (NotifyEvent.FAILURE,), log())
        assert n.notify(NotifyEvent.FAILURE, "x") is False

    def test_digest_reports_health_even_on_success(self) -> None:
        """SPEC §12 — silence must never be ambiguous."""
        text = Digest(campaign="demo", posted=42, queue_depth=6,
                      buffer_requests_30d=400).render()
        assert "posted: 42" in text and "400 / 3000" in text

    def test_digest_flags_missing_licenses(self) -> None:
        text = Digest(campaign="demo", missing_licenses=["music_x.mp3"]).render()
        assert "music_x.mp3" in text


class TestShippedWorkflows:
    """The committed workflows must honour the invariants SPEC §12 names."""

    def _wf(self, name: str) -> str:
        return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_topup_has_a_non_cancelling_concurrency_group(self) -> None:
        text = self._wf("topup.yml")
        assert "group: topup-" in text
        assert "cancel-in-progress: false" in text

    def test_every_workflow_supports_dispatch(self) -> None:
        for name in ("render.yml", "topup.yml", "preflight.yml", "cleanup.yml"):
            assert "workflow_dispatch" in self._wf(name), name

    def test_render_and_topup_expose_a_dry_run_input(self) -> None:
        for name in ("render.yml", "topup.yml"):
            assert "dry_run" in self._wf(name), name

    def test_only_render_installs_ffmpeg(self) -> None:
        """SPEC §12 — the other jobs do not need it."""
        assert "ffmpeg" in self._wf("render.yml")
        for name in ("topup.yml", "cleanup.yml"):
            assert "ffmpeg" not in self._wf(name), name

    def test_bot_commits_skip_ci(self) -> None:
        assert "[skip ci]" in self._wf("render.yml")

    def test_render_commits_nightly_to_keep_cron_alive(self) -> None:
        """SPEC §12 — GitHub disables cron after 60 days with no commits."""
        text = self._wf("render.yml")
        assert "git commit" in text and "git push" in text

    def test_every_campaign_is_in_every_workflow_matrix(self) -> None:
        """A campaign missing from a matrix silently never runs."""
        campaigns = [
            d.name for d in (REPO_ROOT / "campaigns").iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ]
        for name in ("render.yml", "topup.yml", "preflight.yml", "cleanup.yml"):
            text = self._wf(name)
            assert "matrix:" in text, name
            for slug in campaigns:
                assert slug in text, f"{slug} missing from {name}"

    def test_ci_never_enables_the_live_buffer_test(self) -> None:
        """SPEC §2.2 — the live test is never part of CI."""
        for name in ("preflight.yml", "render.yml", "topup.yml", "cleanup.yml"):
            assert "UGC_LIVE_BUFFER" not in self._wf(name).replace(
                "# UGC_LIVE_BUFFER is deliberately unset", ""
            ), name


class TestShippedCampaign:
    def test_clubs_loads_and_is_reel_configured(self) -> None:
        cfg = load_campaign(REPO_ROOT / "campaigns", "clubs")
        assert cfg.buffer.post_type is PostType.REEL
        assert cfg.video.min_duration_sec == 5 and cfg.video.max_duration_sec == 90
        # SPEC §4.5 caps the schema at 24/day. The exact figure is an operator
        # decision about spam-classifier risk, not something a test should pin.
        assert 1 <= cfg.posting.posts_per_day <= 24

    @pytest.mark.parametrize("slug", ["clubs", "clubs_tt", "clubs_yt"])
    def test_cooldowns_are_satisfiable_by_the_real_bank(self, slug: str) -> None:
        """A cooldown of N days at P posts/day needs N×P distinct assets.

        Config that cannot be satisfied makes the selector relax and alert every
        single day, which is indistinguishable from being broken. Reads the
        committed description bank rather than assuming a count, so growing the
        bank and raising the cadence stay honest about each other.
        """
        from src.descriptions import parse_bank

        cfg = load_campaign(REPO_ROOT / "campaigns", slug)
        bank = parse_bank(
            (REPO_ROOT / "campaigns" / slug / "captions.txt").read_text(
                encoding="utf-8"
            )
        )
        ppd = cfg.posting.posts_per_day
        needed = ppd * cfg.selection.caption_cooldown_days
        assert needed <= len(bank), (
            f"{slug}: caption cooldown needs {needed} descriptions at "
            f"{ppd}/day, bank has {len(bank)}"
        )

    @pytest.mark.parametrize("slug", ["clubs", "clubs_tt", "clubs_yt"])
    def test_every_campaign_targets_a_distinct_channel_secret(
        self, slug: str
    ) -> None:
        """Two campaigns sharing a channel secret would double-post one account."""
        cfg = load_campaign(REPO_ROOT / "campaigns", slug)
        others = [
            load_campaign(REPO_ROOT / "campaigns", s)
            for s in ("clubs", "clubs_tt", "clubs_yt")
            if s != slug
        ]
        assert cfg.buffer.channel_id_secret not in {
            o.buffer.channel_id_secret for o in others
        }

    def test_queue_and_history_files_are_valid_json(self) -> None:
        """Parse, not emptiness — these files carry real state once live."""
        from src.queue import load_history

        d = REPO_ROOT / "campaigns" / "clubs"
        queue = load_queue(d / "queue.json")
        history = load_history(d / "history.json")
        # Every queued item must have somewhere to fetch the video from, or the
        # publisher would hand Buffer an empty URL.
        for item in queue.items:
            assert item.video_url.startswith("https://"), item.id
            assert item.caption.strip(), item.id
        # History hashes are what dedupe rests on; a blank one would collide
        # with every other blank one.
        for entry in history.entries:
            assert entry.tuple_hash

    def test_cli_help_lists_all_four_commands(self) -> None:
        # sys.executable, not "python": the ambient interpreter on a dev machine
        # is often a different environment without this project's dependencies.
        proc = subprocess.run(
            [sys.executable, "-m", "src.cli", "--help"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        for command in ("render", "topup", "preflight", "cleanup"):
            assert command in proc.stdout, command
