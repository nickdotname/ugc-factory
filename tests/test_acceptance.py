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

    # vcs.py may use `random` only for retry jitter. The rule protects the
    # determinism of *output* — given a seed, the selector must pick the same
    # combinations — and how long a rejected git push waits before retrying has
    # no bearing on that. Anything that influences what gets rendered or posted
    # must still take an injected Rng.
    # keys.py shells out to the GitHub CLI to store an Actions secret. Doing it
    # over the API instead would mean sealing the value with libsodium, i.e. a
    # crypto dependency in the cron path to save one subprocess in an operator
    # tool — so this is a boundary module by the same logic as vcs.py, and is
    # listed rather than exempted case-by-case.
    FORBIDDEN = {
        "requests": {"assets.py", "notify.py", "buffer.py"},
        "subprocess": {"render.py", "vcs.py", "keys.py"},
        "random": {"ports.py", "vcs.py"},
    }

    def test_vcs_uses_random_only_for_backoff(self) -> None:
        """Guards the exemption above from being quietly widened."""
        text = (REPO_ROOT / "src" / "vcs.py").read_text(encoding="utf-8")
        uses = [
            line.strip()
            for line in text.splitlines()
            if "random." in line and not line.strip().startswith("#")
        ]
        assert uses, "exemption is now unused — remove vcs.py from the allowlist"
        for line in uses:
            assert "self._sleep" in line, (
                f"random used outside backoff in vcs.py: {line}"
            )

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

    def test_campaign_matrices_are_discovered_not_hardcoded(self) -> None:
        """A hardcoded matrix means a new campaign silently never runs.

        Replaces an older test that asserted every slug appeared literally in
        every workflow. That was the right check while the list was static, but
        it is precisely the coupling that stopped the dashboard from creating a
        campaign that works — so now the requirement is the opposite.
        """
        import yaml

        for name in ("render.yml", "topup.yml", "preflight.yml", "cleanup.yml",
                     "metrics.yml", "diagnose.yml"):
            doc = yaml.safe_load(self._wf(name))
            jobs = doc["jobs"]
            assert "discover" in jobs, f"{name} has no discover job"

            matrixed = [
                (n, j) for n, j in jobs.items()
                if isinstance((j.get("strategy") or {}).get("matrix"), dict)
                and "campaign" in j["strategy"]["matrix"]
            ]
            assert matrixed, f"{name} has no campaign matrix"
            for job_name, job in matrixed:
                spec = str(job["strategy"]["matrix"]["campaign"])
                assert "fromJson" in spec and "discover" in spec, (
                    f"{name}:{job_name} still hardcodes its campaigns: {spec}"
                )
                assert "discover" in str(job.get("needs")), (
                    f"{name}:{job_name} uses discover output without needing it"
                )

    def test_no_workflow_hardcodes_a_campaign_slug(self) -> None:
        """Slugs in a workflow are the coupling dynamic discovery removed."""
        slugs = [
            d.name for d in (REPO_ROOT / "campaigns").iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ]
        for name in ("render.yml", "topup.yml", "preflight.yml", "cleanup.yml",
                     "metrics.yml", "diagnose.yml"):
            text = self._wf(name)
            for slug in slugs:
                assert slug not in text, f"{name} still names {slug}"

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

    def test_every_campaign_targets_a_distinct_channel(self) -> None:
        """Two campaigns pointing at one channel would double-post that account.

        Compares the resolved identity — a literal id or the name of the secret
        holding one — since either may carry it.
        """
        from src.campaigns import list_campaigns

        identities: dict[str, str] = {}
        for summary in list_campaigns(REPO_ROOT / "campaigns"):
            cfg = load_campaign(REPO_ROOT / "campaigns", summary.slug)
            identity = cfg.buffer.channel_id or f"secret:{cfg.buffer.channel_id_secret}"
            assert identity not in identities, (
                f"{summary.slug} and {identities[identity]} both target {identity}"
            )
            identities[identity] = summary.slug
        assert len(identities) >= 3

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


class TestDigestIsActuallyEnabled:
    """SPEC §12 — silence must never be ambiguous between healthy and dead.

    A digest that is implemented but not enabled is worse than none: it looks
    like monitoring while reporting nothing. This was a real bug — `digest` was
    missing from every campaign's `on` list and from the schema default, so the
    weekly digest silently no-opped.
    """

    @pytest.mark.parametrize("slug", ["clubs", "clubs_tt", "clubs_yt"])
    def test_campaign_has_digest_enabled(self, slug: str) -> None:
        from src.config import NotifyEvent

        cfg = load_campaign(REPO_ROOT / "campaigns", slug)
        assert NotifyEvent.DIGEST in cfg.notify.on, (
            f"{slug} would never report that it is alive"
        )

    @pytest.mark.parametrize("slug", ["clubs", "clubs_tt", "clubs_yt"])
    def test_campaign_alerts_on_failure(self, slug: str) -> None:
        from src.config import NotifyEvent

        cfg = load_campaign(REPO_ROOT / "campaigns", slug)
        assert NotifyEvent.FAILURE in cfg.notify.on

    def test_schema_default_includes_digest(self) -> None:
        """A new campaign must not have to opt in to knowing it is alive."""
        from src.config import NotifyConfig, NotifyEvent

        default = NotifyConfig(webhook_secret="DISCORD_WEBHOOK_X")
        assert NotifyEvent.DIGEST in default.on
        assert NotifyEvent.FAILURE in default.on


def not_sent(stream) -> bool:
    return "notify_sent" not in stream.getvalue()


class TestWebhookValidation:
    """A partial paste must say so, not fail deep inside the HTTP client."""

    def _notifier(self, url):
        import io as _io

        from src.config import NotifyEvent
        from src.notify import Notifier

        stream = _io.StringIO()
        n = Notifier(url, (NotifyEvent.DIGEST,),
                     StructuredLogger({}, stream), session=FakeSession())
        return n, stream

    def test_a_pasted_json_blob_still_works(self) -> None:
        """Discord's API returns the webhook as JSON and its UI offers a copy
        button, so the secret reliably ends up as one shape or the other."""
        from src.config import NotifyEvent
        from src.notify import Notifier

        blob = ('{"id":"1","name":"Spidey Bot","token":"tok",'
                '"url":"https://discord.com/api/webhooks/1/tok"}')
        s = FakeSession()
        s.route("POST", "discord.com", FakeResponse(204))
        n = Notifier(blob, (NotifyEvent.DIGEST,), log(), session=s)
        assert n.notify(NotifyEvent.DIGEST, "hi") is True
        assert s.calls[0].url == "https://discord.com/api/webhooks/1/tok"

    def test_value_with_no_url_at_all_sends_nothing(self) -> None:
        from src.config import NotifyEvent

        n, stream = self._notifier("just-a-token-no-url")
        assert n.notify(NotifyEvent.DIGEST, "hi") is False
        assert not_sent(stream)

    def test_the_secret_value_is_never_logged(self) -> None:
        from src.config import NotifyEvent

        n, stream = self._notifier("nonsense-SECRETTOKEN")
        n.notify(NotifyEvent.DIGEST, "hi")
        assert "SECRETTOKEN" not in stream.getvalue()

    def test_surrounding_whitespace_and_quotes_are_tolerated(self) -> None:
        from src.config import NotifyEvent
        from src.notify import Notifier

        s = FakeSession()
        s.route("POST", "discord.com", FakeResponse(204))
        n = Notifier('  "https://discord.com/api/webhooks/1/t"  ',
                     (NotifyEvent.DIGEST,), log(), session=s)
        assert n.notify(NotifyEvent.DIGEST, "hi") is True

    def test_a_proper_url_is_sent(self) -> None:
        from src.config import NotifyEvent
        from src.notify import Notifier

        s = FakeSession()
        s.route("POST", "discord.com", FakeResponse(204))
        n = Notifier("https://discord.com/api/webhooks/1/x", (NotifyEvent.DIGEST,),
                     log(), session=s)
        assert n.notify(NotifyEvent.DIGEST, "hi") is True


class TestLogEventIdentity:
    """A field named `event` must not erase the log line's own event name."""

    def test_event_name_survives_a_colliding_field(self) -> None:
        import io as _io

        stream = _io.StringIO()
        StructuredLogger({}, stream).info("real_event_name", event="collision")
        record = __import__("json").loads(stream.getvalue())
        assert record["event"] == "real_event_name"
        assert record["event_field"] == "collision"

    def test_ordinary_fields_are_unaffected(self) -> None:
        import io as _io

        stream = _io.StringIO()
        StructuredLogger({}, stream).info("some_event", count=3)
        record = __import__("json").loads(stream.getvalue())
        assert record["event"] == "some_event" and record["count"] == 3
        assert "event_field" not in record
