"""The local drop-and-upload interface.

``WebApp`` holds every operation and takes no socket, so these run without
starting a server. The handler is a thin translation layer over it.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.assets import MediaStore, RemoteAsset
from src.config import CampaignConfig, load_campaign
from src.errors import UgcError
from src.keys import mask, read_env
from src.logging import StructuredLogger
from src.render import FfmpegRenderer
from src.models import PartKind
from src.ports import FrozenClock
from src.web import MAX_UPLOAD_BYTES, WebApp, _kind_from, _safe_name

from tests.conftest import needs_ffmpeg

NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


class FakeStore(MediaStore):
    def __init__(self) -> None:
        self.existing: list[str] = []
        self.published: list[str] = []
        self.deleted: list[str] = []

    def download_assets(self, tag: str, dest_dir: Path) -> list[Path]:
        return []

    def list_assets(self, tag: str) -> list[str]:
        return list(self.existing)

    def publish(self, tag: str, files: list[Path]) -> list[RemoteAsset]:
        for f in files:
            self.published.append(f.name)
            self.existing.append(f.name)
        return [RemoteAsset(name=f.name, url=f"https://x/{f.name}", size_bytes=1)
                for f in files]

    def delete_assets(self, tag: str, names: list[str]) -> list[str]:
        gone = [n for n in names if n in self.existing]
        self.existing = [n for n in self.existing if n not in names]
        self.deleted.extend(gone)
        return gone

    def cleanup(self, prefix: str, older_than_days: int) -> list[str]:
        return []


@pytest.fixture
def app(tmp_path: Path, config: CampaignConfig) -> WebApp:
    bank = tmp_path / "captions.txt"
    bank.write_text("first one\n\nsecond one\n", encoding="utf-8")
    return WebApp(
        config=config,
        repo_root=tmp_path,
        inbox=tmp_path / "inbox",
        bank_path=bank,
        log=StructuredLogger({}, io.StringIO()),
        clock=FrozenClock(NOW),
        store_factory=FakeStore,
    )


class TestFilenameSafety:
    """A browser-supplied name must never escape the inbox."""

    def test_traversal_is_reduced_to_a_basename(self) -> None:
        assert _safe_name("../../../../etc/passwd") == "passwd"
        assert _safe_name("/etc/shadow") == "shadow"

    def test_windows_separators_are_stripped(self) -> None:
        assert _safe_name("a/b/c.mp4") == "c.mp4"

    def test_dotfiles_are_refused(self) -> None:
        assert _safe_name(".bashrc") is None
        assert _safe_name("..") is None

    def test_empty_is_refused(self) -> None:
        assert _safe_name("") is None
        assert _safe_name("   /  ") is None

    def test_ordinary_names_with_spaces_survive(self) -> None:
        assert _safe_name("My Cool Hook v2 (final).mp4") == "My Cool Hook v2 (final).mp4"

    def test_absurdly_long_names_refused(self) -> None:
        assert _safe_name("x" * 500 + ".mp4") is None

    def test_shell_metacharacters_refused(self) -> None:
        for bad in ("a;rm -rf /.mp4", "a$(whoami).mp4", "a`id`.mp4", "a|b.mp4"):
            assert _safe_name(bad) is None, bad


class TestKindRouting:
    def test_known_folders_map_to_kinds(self) -> None:
        assert _kind_from("hooks") is PartKind.HOOK
        assert _kind_from("bodies") is PartKind.BODY
        assert _kind_from("music") is PartKind.MUSIC

    def test_unknown_folder_is_rejected(self) -> None:
        for bad in ("", "hook", "/etc", "..", "HOOKS"):
            assert _kind_from(bad) is None, bad


class TestStaging:
    def test_saved_file_lands_in_the_right_folder(self, app: WebApp) -> None:
        app.save_file(PartKind.HOOK, "clip.mp4", b"data")
        assert (app.inbox / "hooks" / "clip.mp4").read_bytes() == b"data"

    def test_state_lists_staged_files(self, app: WebApp) -> None:
        app.save_file(PartKind.BODY, "main.mp4", b"12345")
        staged = app.state()["staged"]["bodies"]
        assert staged == [{"name": "main.mp4", "size": 5}]

    def test_delete_removes_a_staged_file(self, app: WebApp) -> None:
        app.save_file(PartKind.MUSIC, "song.mp3", b"x")
        app.delete_file(PartKind.MUSIC, "song.mp3")
        assert app.state()["staged"]["music"] == []

    def test_deleting_a_missing_file_is_not_an_error(self, app: WebApp) -> None:
        assert app.delete_file(PartKind.HOOK, "ghost.mp4")["ok"] is True

    def test_hidden_files_are_not_listed(self, app: WebApp) -> None:
        (app.inbox / "hooks" / ".DS_Store").write_bytes(b"junk")
        assert app.state()["staged"]["hooks"] == []

    def test_inbox_folders_are_created_on_construction(self, app: WebApp) -> None:
        for folder in ("hooks", "bodies", "music"):
            assert (app.inbox / folder).is_dir()


class TestDescriptions:
    def test_state_reports_the_bank(self, app: WebApp) -> None:
        d = app.state()["descriptions"]
        assert d["count"] == 2
        assert "first one" in d["text"]
        assert d["errors"] == []

    def test_saving_rewrites_the_file(self, app: WebApp) -> None:
        app.save_descriptions("alpha\n\nbeta\n\ngamma")
        assert app.state()["descriptions"]["count"] == 3
        assert "gamma" in app.bank_path.read_text(encoding="utf-8")

    def test_an_invalid_draft_still_saves_but_reports(self, app: WebApp) -> None:
        """Saving work-in-progress must not be blocked; render is the gate."""
        result = app.save_descriptions("x" * 3_000)
        assert result["ok"] is True
        assert result["errors"]
        assert app.bank_path.read_text(encoding="utf-8").startswith("x")

    def test_malformed_record_is_reported_not_raised(self, app: WebApp) -> None:
        result = app.save_descriptions("title: orphan with no body")
        assert result["ok"] is True and result["errors"]

    def test_missing_bank_file_yields_empty_state(
        self, tmp_path: Path, config: CampaignConfig
    ) -> None:
        app = WebApp(
            config=config, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=tmp_path / "absent.txt",
            log=StructuredLogger({}, io.StringIO()), clock=FrozenClock(NOW),
            store_factory=FakeStore,
        )
        assert app.state()["descriptions"]["count"] == 0


class TestHealth:
    def test_health_reports_zero_for_an_empty_library(self, app: WebApp) -> None:
        assert app.state()["health"]["combinations"] == 0

    def test_health_warns_about_cooldown_shortfall(
        self, tmp_path: Path, config: CampaignConfig
    ) -> None:
        bank = tmp_path / "b.txt"
        bank.write_text("one\n\ntwo", encoding="utf-8")
        tight = config.model_copy(update={
            "posting": config.posting.model_copy(update={"posts_per_day": 6}),
            "selection": config.selection.model_copy(
                update={"caption_cooldown_days": 14}
            ),
        })
        app = WebApp(
            config=tight, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=bank, log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW), store_factory=FakeStore,
        )
        assert any("caption cooldown" in w for w in app.state()["health"]["warnings"])


@needs_ffmpeg
class TestPlanAndUpload:
    def test_plan_lists_candidates(self, app: WebApp, clips: dict[str, Path]) -> None:
        app.save_file(PartKind.HOOK, "a.mp4", clips["portrait"].read_bytes())
        plan = app.plan()
        assert plan["ok"] and plan["uploadable"] == 1
        assert plan["items"][0]["target"] == "hook_01.mp4"

    def test_plan_reports_rejects(self, app: WebApp) -> None:
        app.save_file(PartKind.HOOK, "junk.mp4", b"not a video")
        plan = app.plan()
        assert plan["rejected"] == 1
        assert plan["items"][0]["verdict"] == "rejected"

    def test_upload_publishes_and_clears_the_inbox(
        self, app: WebApp, clips: dict[str, Path]
    ) -> None:
        app.save_file(PartKind.HOOK, "a.mp4", clips["portrait"].read_bytes())
        result = app.upload()
        assert result["ok"] and result["uploaded"] == ["hook_01.mp4"]
        assert app.state()["staged"]["hooks"] == []

    def test_upload_with_nothing_staged_reports_cleanly(self, app: WebApp) -> None:
        result = app.upload()
        assert result["ok"] is False and "Nothing uploadable" in result["error"]

    def test_upload_without_credentials_explains_how_to_fix(
        self, tmp_path: Path, config: CampaignConfig, clips: dict[str, Path]
    ) -> None:
        bank = tmp_path / "b.txt"
        bank.write_text("one", encoding="utf-8")
        app = WebApp(
            config=config, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=bank, log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW), store_factory=lambda: None,  # type: ignore[arg-type,return-value]
        )
        app.save_file(PartKind.HOOK, "a.mp4", clips["portrait"].read_bytes())
        result = app.upload()
        assert result["ok"] is False and "gh auth login" in result["error"]

    def test_uploaded_counts_reflect_the_archive(
        self, app: WebApp, clips: dict[str, Path]
    ) -> None:
        app.save_file(PartKind.HOOK, "a.mp4", clips["portrait"].read_bytes())
        app.upload()
        assert app.state()["uploaded"]["hook"] == 1


class TestRandomizerRoster:
    """Switching a clip off must change what the pipeline can pick, not just
    what the page looks like."""

    def stage(self, app: WebApp, *names: str) -> None:
        """Put files where ``ingest`` leaves them after a successful upload."""
        archive = app.inbox / "_uploaded"
        archive.mkdir(parents=True, exist_ok=True)
        for name in names:
            (archive / name).write_bytes(b"x" * 32)

    def test_clips_are_grouped_by_role_and_start_enabled(self, app: WebApp) -> None:
        self.stage(app, "hook_01.mp4", "body_01.mp4", "music_01.mp3")
        groups = {g["kind"]: g for g in app.clips()["groups"]}
        assert [c["name"] for c in groups["hook"]["clips"]] == ["hook_01.mp4"]
        assert groups["body"]["enabled"] == 1
        assert all(c["enabled"] for g in groups.values() for c in g["clips"])

    def test_switching_a_clip_off_drops_it_from_the_counts(
        self, app: WebApp
    ) -> None:
        self.stage(app, "hook_01.mp4", "hook_02.mp4")
        app.set_clips(["hook_02.mp4"], False)
        assert app.state()["uploaded"]["hook"] == 1
        assert app.state()["muted"]["hook"] == 1

    def test_a_muted_clip_is_still_listed_so_it_can_be_switched_back(
        self, app: WebApp
    ) -> None:
        self.stage(app, "hook_01.mp4")
        app.set_clips(["hook_01.mp4"], False)
        group = app.clips()["groups"][0]
        assert group["total"] == 1 and group["enabled"] == 0
        assert group["clips"][0]["enabled"] is False

    def test_muting_lowers_the_reported_combinations(self, app: WebApp) -> None:
        self.stage(app, "hook_01.mp4", "hook_02.mp4", "body_01.mp4")
        before = app.clips()["combinations"]
        app.set_clips(["hook_02.mp4"], False)
        after = app.clips()["combinations"]
        assert 0 < after < before

    def test_switching_back_on_restores_it(self, app: WebApp) -> None:
        self.stage(app, "hook_01.mp4")
        app.set_clips(["hook_01.mp4"], False)
        app.set_clips(["hook_01.mp4"], True)
        assert app.state()["uploaded"]["hook"] == 1
        assert app.roster_file.exists()

    def test_the_roster_survives_a_restart(
        self, app: WebApp, tmp_path: Path, config: CampaignConfig
    ) -> None:
        self.stage(app, "hook_01.mp4")
        app.set_clips(["hook_01.mp4"], False)
        fresh = WebApp(
            config=config, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=app.bank_path, log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW), store_factory=FakeStore,
        )
        assert fresh.state()["uploaded"]["hook"] == 0

    def test_a_name_that_escapes_the_campaign_is_refused(self, app: WebApp) -> None:
        assert app.set_clips(["../../etc/passwd"], False)["ok"] is True
        # Reduced to a basename before it is written, never a path.
        assert app.roster_file.read_text().count("passwd") == 1
        assert ".." not in app.roster_file.read_text()

    def test_an_empty_request_changes_nothing(self, app: WebApp) -> None:
        assert app.set_clips([], False)["ok"] is False
        assert not app.roster_file.exists()

    def test_clips_from_the_release_appear_without_a_local_copy(
        self, app: WebApp
    ) -> None:
        store = FakeStore()
        store.existing = ["hook_09.mp4"]
        app._store_factory = lambda: store
        clip = app.clips()["groups"][0]["clips"][0]
        assert clip["name"] == "hook_09.mp4" and clip["preview"] is False

    def test_non_asset_files_are_not_listed_as_clips(self, app: WebApp) -> None:
        self.stage(app, "LICENSES.md", "hook_01.mp4")
        names = [c["name"] for g in app.clips()["groups"] for c in g["clips"]]
        assert names == ["hook_01.mp4"]

    def test_preview_is_served_only_for_clips_that_exist_locally(
        self, app: WebApp
    ) -> None:
        self.stage(app, "hook_01.mp4")
        assert app.clip_file("hook_01.mp4") is not None
        assert app.clip_file("hook_02.mp4") is None


    def test_the_library_scope_names_the_campaigns_it_feeds(
        self, app: WebApp
    ) -> None:
        # With no sibling campaigns on disk it must still name this one, so
        # the dashboard never renders "shared across (nothing)".
        scope = app.clips()["library"]
        assert scope["campaigns"] == [app.config.slug]
        assert scope["tag"] == app.config.assets_tag
        assert scope["inbox"] == app.config.library_key


    def test_a_shared_library_reads_the_shared_release_not_the_slug(
        self, tmp_path: Path, config: CampaignConfig
    ) -> None:
        """Deriving the tag from the slug sends a shared-library campaign at a
        Release nobody reads — and an upload there would silently strand the
        clips in a new one."""
        bank = tmp_path / "b.txt"
        bank.write_text("one", encoding="utf-8")
        shared = config.model_copy(update={"assets_release": "assets-brand"})
        asked: list[str] = []

        class Watcher(FakeStore):
            def list_assets(self, tag: str) -> list[str]:
                asked.append(tag)
                return []

        app = WebApp(
            config=shared, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=bank, log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW), store_factory=Watcher,
        )
        app.clips()
        assert asked == ["assets-brand"]
        assert shared.library_key == "brand"


class TestClipDeletion:
    """The irreversible half — it must reach the Release, not just the disk."""

    def test_delete_removes_the_release_asset_and_the_local_copy(
        self, app: WebApp
    ) -> None:
        store = FakeStore()
        store.existing = ["hook_01.mp4"]
        app._store_factory = lambda: store
        archive = app.inbox / "_uploaded"
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "hook_01.mp4").write_bytes(b"x")

        result = app.delete_clip("hook_01.mp4")
        assert result["ok"] and store.deleted == ["hook_01.mp4"]
        assert not (archive / "hook_01.mp4").exists()
        assert app.clips()["groups"][0]["clips"] == []

    def test_deleting_clears_any_mute_so_a_reused_name_is_not_born_muted(
        self, app: WebApp
    ) -> None:
        store = FakeStore()
        store.existing = ["hook_01.mp4"]
        app._store_factory = lambda: store
        app.set_clips(["hook_01.mp4"], False)
        app.delete_clip("hook_01.mp4")
        from src.clips import load_roster

        assert load_roster(app.roster_file).disabled == ()

    def test_delete_without_credentials_points_at_muting_instead(
        self, tmp_path: Path, config: CampaignConfig
    ) -> None:
        bank = tmp_path / "b.txt"
        bank.write_text("one", encoding="utf-8")
        app = WebApp(
            config=config, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=bank, log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW), store_factory=lambda: None,  # type: ignore[arg-type,return-value]
        )
        result = app.delete_clip("hook_01.mp4")
        assert result["ok"] is False and "Mute the clip instead" in result["error"]


class TestRevenuePanel:
    """The window pairing is the part that can be silently wrong."""

    def test_an_empty_ledger_reports_zero_without_failing(self, app: WebApp) -> None:
        r = app.revenue()
        assert r["total"] == 0 and r["entries"] == []

    def test_a_recorded_payment_comes_back(self, app: WebApp) -> None:
        result = app.add_revenue({
            "period_start": "2026-08-01", "period_end": "2026-08-31",
            "amount": "310", "source": "app revenue",
        })
        assert result["ok"]
        r = app.revenue()
        assert r["total"] == 310 and len(r["entries"]) == 1
        assert r["entries"][0]["days"] == 31

    def test_a_missing_end_date_means_a_single_day(self, app: WebApp) -> None:
        app.add_revenue({"period_start": "2026-08-05", "amount": "500"})
        assert app.revenue()["entries"][0]["days"] == 1

    def test_a_zero_amount_is_refused(self, app: WebApp) -> None:
        result = app.add_revenue({"period_start": "2026-08-01", "amount": "0"})
        assert result["ok"] is False and "more than zero" in result["error"]

    def test_a_malformed_date_is_reported_not_raised(self, app: WebApp) -> None:
        result = app.add_revenue({"period_start": "not-a-date", "amount": "10"})
        assert result["ok"] is False and result["error"]

    def test_removing_an_unknown_entry_is_reported(self, app: WebApp) -> None:
        assert app.remove_revenue("nope")["ok"] is False

    def test_removing_takes_the_row_out(self, app: WebApp) -> None:
        app.add_revenue({"period_start": "2026-08-01", "amount": "10"})
        entry_id = app.revenue()["entries"][0]["id"]
        assert app.remove_revenue(entry_id)["ok"]
        assert app.revenue()["total"] == 0

    def test_the_ledger_lands_beside_the_campaign_config(self, app: WebApp) -> None:
        app.add_revenue({"period_start": "2026-08-01", "amount": "10"})
        assert app.ledger_file.name == "revenue.json"
        assert app.ledger_file.parent == app.bank_path.parent

    def test_double_counting_is_surfaced(self, app: WebApp) -> None:
        for start, end in (("2026-08-01", "2026-08-31"), ("2026-08-15", "2026-09-05")):
            app.add_revenue({
                "period_start": start, "period_end": end,
                "amount": "100", "source": "app",
            })
        assert app.revenue()["warnings"]

    def test_a_mixed_currency_ledger_says_so(self, app: WebApp) -> None:
        app.add_revenue({"period_start": "2026-08-01", "amount": "10"})
        app.add_revenue({
            "period_start": "2026-08-02", "amount": "10", "currency": "eur",
        })
        assert app.revenue()["mixed_currencies"] == ["USD"]


class TestLibraryHeadline:
    """The panel must lead with the number that actually constrains variety."""

    def test_the_repeat_rate_is_reported(self, app: WebApp) -> None:
        health = app.state()["health"]
        # posts_per_day / bodies — how often a viewer sees the same clip.
        assert "body_repeats_per_day" in health

    def test_no_bodies_yields_no_rate_rather_than_a_division_error(
        self, app: WebApp
    ) -> None:
        assert app.state()["health"]["body_repeats_per_day"] is None

    def test_the_rate_matches_the_cadence(
        self, tmp_path: Path, config: CampaignConfig
    ) -> None:
        bank = tmp_path / "b.txt"
        bank.write_text("one\n", encoding="utf-8")
        posting = config.posting.model_copy(update={"posts_per_day": 12})
        app = WebApp(
            config=config.model_copy(update={"posting": posting}),
            repo_root=tmp_path, inbox=tmp_path / "inbox", bank_path=bank,
            log=StructuredLogger({}, io.StringIO()), clock=FrozenClock(NOW),
            store_factory=FakeStore,
        )
        archive = app.inbox / "_uploaded"
        archive.mkdir(parents=True, exist_ok=True)
        for i in range(4):
            (archive / f"body_{i:02d}.mp4").write_bytes(b"x")
        assert app.state()["health"]["body_repeats_per_day"] == 3.0


class TestQueuePanel:
    """Pulling a post. The dangerous half is the one that talks to Buffer."""

    @pytest.fixture
    def queued(self, app: WebApp, monkeypatch: pytest.MonkeyPatch):
        """A queue on disk plus a Buffer stand-in that records deletions."""
        from src.models import Queue, QueueItem, QueueStatus
        from src.queue import save_queue

        items = [
            QueueItem(
                id="pend-1", scheduled_for=NOW, video_url="https://x/1.mp4",
                caption="not sent yet", parts={"hook": "hook_01.mov"},
                status=QueueStatus.PENDING,
            ),
            QueueItem(
                id="sent-1", scheduled_for=NOW, video_url="https://x/2.mp4",
                caption="already in buffer", parts={"hook": "hook_02.mov"},
                status=QueueStatus.PUSHED, buffer_post_id="bp-99",
            ),
            QueueItem(
                id="mid-1", scheduled_for=NOW, video_url="https://x/3.mp4",
                caption="mid push", parts={"hook": "hook_03.mov"},
                status=QueueStatus.CLAIMED,
            ),
        ]
        save_queue(app.bank_path.parent / "queue.json",
                   Queue(generated_at=NOW, items=items))

        deleted: list[str] = []

        class FakePublisher:
            def __init__(self, key, log, organization_id=None):
                pass

            def delete_post(self, post_id: str) -> None:
                deleted.append(post_id)

        monkeypatch.setattr("src.publishers.buffer.BufferPublisher", FakePublisher)
        monkeypatch.setattr(app, "buffer_key", lambda slot=None: "a-key")
        self.deleted = deleted
        return app

    def test_the_queue_lists_every_item_with_its_state(self, queued: WebApp) -> None:
        q = queued.queue()
        assert len(q["items"]) == 3
        assert q["counts"] == {"pending": 1, "pushed": 1, "claimed": 1}

    def test_a_claimed_item_is_not_offered_a_pull_button(
        self, queued: WebApp
    ) -> None:
        # It may be mid-push; the UI must not offer what the model refuses.
        states = {i["id"]: i["cancellable"] for i in queued.queue()["items"]}
        assert states == {"pend-1": True, "sent-1": True, "mid-1": False}

    def test_pulling_an_unsent_item_never_calls_buffer(
        self, queued: WebApp
    ) -> None:
        result = queued.pull_item("pend-1")
        assert result["ok"] and result["from_buffer"] is False
        assert self.deleted == []

    def test_a_pulled_item_stops_being_claimable(self, queued: WebApp) -> None:
        from src.queue import claimable, load_queue

        queued.pull_item("pend-1")
        queue = load_queue(queued.bank_path.parent / "queue.json")
        assert [i.id for i in claimable(queue)] == []

    def test_pulling_a_sent_item_tells_buffer(self, queued: WebApp) -> None:
        result = queued.pull_item("sent-1")
        assert result["ok"] and result["from_buffer"] is True
        assert self.deleted == ["bp-99"]

    def test_a_claimed_item_is_refused(self, queued: WebApp) -> None:
        result = queued.pull_item("mid-1")
        assert result["ok"] is False and "reconciled" in result["error"]

    def test_an_unknown_id_is_reported(self, queued: WebApp) -> None:
        assert queued.pull_item("nope")["ok"] is False

    def test_a_buffer_refusal_still_records_the_cancellation_and_warns(
        self, queued: WebApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Most often this means the network already published it."""
        from src.errors import PublishError
        from src.models import QueueStatus
        from src.queue import load_queue

        class Exploding:
            def __init__(self, *a, **k): pass
            def delete_post(self, post_id: str) -> None:
                raise PublishError("post not found")

        monkeypatch.setattr("src.publishers.buffer.BufferPublisher", Exploding)
        result = queued.pull_item("sent-1")
        assert result["ok"] and "already published" in result["warning"]
        queue = load_queue(queued.bank_path.parent / "queue.json")
        item = next(i for i in queue.items if i.id == "sent-1")
        assert item.status is QueueStatus.CANCELLED

    def test_without_a_key_a_sent_item_is_not_silently_cancelled(
        self, queued: WebApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Marking it cancelled locally would not stop Buffer publishing it.

        Recording a cancellation we could not enact is the one outcome worse
        than refusing: the queue would say stopped while the post went out.
        """
        from src.models import QueueStatus
        from src.queue import load_queue

        monkeypatch.setattr(queued, "buffer_key", lambda slot=None: None)
        result = queued.pull_item("sent-1")
        assert result["ok"] is False and "Keys panel" in result["error"]
        queue = load_queue(queued.bank_path.parent / "queue.json")
        item = next(i for i in queue.items if i.id == "sent-1")
        assert item.status is QueueStatus.PUSHED

    def test_no_queue_file_is_an_empty_panel_not_an_error(self, app: WebApp) -> None:
        assert app.queue()["items"] == []


class TestSampleRender:
    """A sample must show the truth and cost nothing."""

    def stage_library(self, app: WebApp, clips: dict, count: int = 2) -> None:
        """Put real clips where the sample renderer looks for them."""
        import shutil

        assets = app.repo_root / "work" / app.config.slug / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            shutil.copy2(clips["portrait"], assets / f"hook_{i + 1:02d}.mp4")
            shutil.copy2(clips["portrait"], assets / f"body_{i + 1:02d}.mp4")

    def test_no_descriptions_is_reported_not_raised(
        self, app: WebApp, clips: dict
    ) -> None:
        self.stage_library(app, clips)
        app.bank_path.write_text("", encoding="utf-8")
        assert app.sample()["ok"] is False

    def test_an_empty_library_says_so_rather_than_crashing(
        self, app: WebApp
    ) -> None:
        # Iterating a directory that download_assets never created would
        # otherwise raise FileNotFoundError out of a button click.
        result = app.sample()
        assert result["ok"] is False and "upload some" in result["error"]

    def test_no_credentials_and_no_cache_explains_itself(
        self, tmp_path: Path, config: CampaignConfig
    ) -> None:
        bank = tmp_path / "captions.txt"
        bank.write_text("one\n", encoding="utf-8")
        app = WebApp(
            config=config, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=bank, log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW), store_factory=lambda: None,  # type: ignore[arg-type,return-value]
        )
        result = app.sample()
        assert result["ok"] is False and "gh auth login" in result["error"]

    @needs_ffmpeg
    def test_it_renders_without_touching_history_or_the_queue(
        self, app: WebApp, clips: dict
    ) -> None:
        """The load-bearing property.

        Recording a sample in history would mean looking at your own library
        cost a unique combination of runway, and the dedupe record would claim
        a video was used that nobody ever saw.
        """
        self.stage_library(app, clips)
        app.bank_path.write_text("first caption\n\nsecond caption\n", encoding="utf-8")

        result = app.sample()
        assert result["ok"], result.get("error")
        assert not (app.bank_path.parent / "history.json").exists()
        assert not (app.bank_path.parent / "queue.json").exists()

    @needs_ffmpeg
    def test_the_rendered_file_is_actually_playable(
        self, app: WebApp, clips: dict
    ) -> None:
        self.stage_library(app, clips)
        app.bank_path.write_text("a caption\n", encoding="utf-8")
        assert app.sample()["ok"]

        path = app.sample_file()
        assert path is not None and path.stat().st_size > 0
        probe = FfmpegRenderer(app.config, StructuredLogger({}, io.StringIO())).probe(path)
        assert probe.has_video and probe.duration_sec > 0

    @needs_ffmpeg
    def test_a_muted_clip_never_appears_in_a_sample(
        self, app: WebApp, clips: dict
    ) -> None:
        """Otherwise the preview would not be showing what the render does."""
        self.stage_library(app, clips, count=2)
        app.bank_path.write_text("a caption\n", encoding="utf-8")
        app.set_clips(["hook_02.mp4"], False)

        for _ in range(4):
            result = app.sample()
            assert result["ok"], result.get("error")
            assert result["hook"] == "hook_01.mp4"


class TestSecretsPanel:
    """Pasting a credential must reach both stores, and leak from neither."""

    @pytest.fixture
    def wired(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WebApp:
        """A dashboard over a real campaign directory, with gh stubbed out."""
        from src.campaigns import create_campaign
        from src.platforms import Service

        campaigns = tmp_path / "campaigns"
        campaigns.mkdir()
        create_campaign(campaigns, "demo", Service.TIKTOK, channel_id="c1")

        self.pushed: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "src.web.set_github_secret",
            lambda root, name, value: self.pushed.append((name, value)),
        )
        monkeypatch.setattr("src.web.list_github_secrets", lambda root: [])
        monkeypatch.delenv("DISCORD_WEBHOOK", raising=False)
        return WebApp(
            config=load_campaign(campaigns, "demo"),
            repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=campaigns / "demo" / "captions.txt",
            log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW), store_factory=FakeStore,
        )

    def test_it_lists_the_secrets_the_campaigns_actually_need(
        self, wired: WebApp
    ) -> None:
        names = {s["name"] for s in wired.secrets()["secrets"]}
        # The channel id is written inline for this campaign, so no channel
        # secret should be demanded.
        assert names == {"BUFFER_API_KEY", "DISCORD_WEBHOOK"}

    def test_each_secret_names_the_campaigns_waiting_on_it(
        self, wired: WebApp
    ) -> None:
        entry = next(s for s in wired.secrets()["secrets"]
                     if s["name"] == "BUFFER_API_KEY")
        assert entry["campaigns"] == ["demo"]
        assert entry["local"] is False and entry["github"] is False

    def test_saving_writes_locally_and_pushes_to_github(
        self, wired: WebApp
    ) -> None:
        result = wired.save_secret("BUFFER_API_KEY", "abc123xyz789")
        assert result["ok"] and result["local"] and result["github"]
        assert self.pushed == [("BUFFER_API_KEY", "abc123xyz789")]
        assert read_env(wired.env_file)["BUFFER_API_KEY"] == "abc123xyz789"

    def test_the_value_is_never_returned_to_the_browser(
        self, wired: WebApp
    ) -> None:
        wired.save_secret("BUFFER_API_KEY", "abc123xyz789")
        payload = wired.secrets()
        assert "abc123xyz789" not in json.dumps(payload)
        entry = next(x for x in payload["secrets"] if x["name"] == "BUFFER_API_KEY")
        assert entry["hint"] == mask("abc123xyz789")  # only the masked tail

    def test_the_value_is_never_logged(self, tmp_path: Path, wired: WebApp) -> None:
        stream = io.StringIO()
        wired.log = StructuredLogger({}, stream)
        wired.save_secret("BUFFER_API_KEY", "abc123xyz789")
        assert "abc123xyz789" not in stream.getvalue()
        assert "secret_saved" in stream.getvalue()

    def test_a_name_no_campaign_uses_is_refused(self, wired: WebApp) -> None:
        # A typo would otherwise write a credential to a key nothing reads
        # and report success.
        result = wired.save_secret("BUFFER_API_KEY_7", "abc123xyz789")
        assert result["ok"] is False and "no campaign" in result["error"]
        assert self.pushed == []

    def test_a_github_failure_still_keeps_the_local_copy(
        self, wired: WebApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.keys import SecretError

        def boom(root: Path, name: str, value: str) -> None:
            raise SecretError("gh exploded")

        monkeypatch.setattr("src.web.set_github_secret", boom)
        result = wired.save_secret("BUFFER_API_KEY", "abc123xyz789")
        assert result["ok"] and result["local"] and result["github"] is False
        assert "gh exploded" in result["github_error"]
        assert read_env(wired.env_file)["BUFFER_API_KEY"] == "abc123xyz789"

    def test_opting_out_of_github_writes_only_the_local_copy(
        self, wired: WebApp
    ) -> None:
        wired.save_secret("BUFFER_API_KEY", "abc123xyz789", to_github=False)
        assert self.pushed == []
        assert read_env(wired.env_file)["BUFFER_API_KEY"] == "abc123xyz789"

    def test_a_pasted_line_with_a_space_is_rejected_before_anything_is_written(
        self, wired: WebApp
    ) -> None:
        with pytest.raises(UgcError):
            wired.save_secret("BUFFER_API_KEY", "BUFFER_API_KEY = abc")
        assert not wired.env_file.exists()
        assert self.pushed == []

    def test_forgetting_drops_the_local_copy_only(self, wired: WebApp) -> None:
        wired.save_secret("BUFFER_API_KEY", "abc123xyz789")
        assert wired.forget_secret("BUFFER_API_KEY")["removed"] is True
        assert read_env(wired.env_file) == {}
        # Never touches GitHub: deleting the copy that posts, from a settings
        # panel, is a way to silently stop a campaign.
        assert self.pushed == [("BUFFER_API_KEY", "abc123xyz789")]

    def test_a_saved_key_is_visible_to_the_running_process(
        self, wired: WebApp
    ) -> None:
        # Otherwise the channel list stays broken until the server restarts.
        wired.save_secret("BUFFER_API_KEY", "abc123xyz789")
        assert wired.buffer_key("BUFFER_API_KEY") == "abc123xyz789"


class TestServerBinding:
    def test_upload_cap_is_bounded(self) -> None:
        """An unbounded body would let one request exhaust memory or disk."""
        assert 0 < MAX_UPLOAD_BYTES <= 2 * 1024 * 1024 * 1024

    def test_serve_binds_only_to_loopback(self) -> None:
        """It writes files and holds a GitHub token; it must not be reachable.

        Checks the bind call itself rather than the whole file — the prose
        explaining *why* it is not 0.0.0.0 naturally mentions 0.0.0.0.
        """
        source = Path("src/web.py").read_text(encoding="utf-8")
        bind_lines = [
            line for line in source.splitlines()
            if "ThreadingHTTPServer(" in line and not line.lstrip().startswith("#")
        ]
        assert bind_lines, "no bind call found"
        for line in bind_lines:
            assert '"127.0.0.1"' in line, line
            assert "0.0.0.0" not in line, line


class TestChannelPicker:
    """Connecting a new Buffer channel without hunting for its id."""

    def _app(self, tmp_path: Path, config: CampaignConfig) -> WebApp:
        campaigns = tmp_path / "campaigns" / "demo"
        campaigns.mkdir(parents=True)
        bank = campaigns / "captions.txt"
        bank.write_text("one", encoding="utf-8")
        return WebApp(
            config=config, repo_root=tmp_path, inbox=tmp_path / "inbox",
            bank_path=bank, log=StructuredLogger({}, io.StringIO()),
            clock=FrozenClock(NOW),
        )

    def test_missing_key_explains_how_to_supply_one(
        self, tmp_path: Path, config: CampaignConfig, monkeypatch
    ) -> None:
        for var in ("BUFFER_API_KEY", "BUFFER_ACCESS_TOKEN",
                    config.buffer.api_key_secret):
            monkeypatch.delenv(var, raising=False)
        result = self._app(tmp_path, config).channels()
        assert result["ok"] is False
        assert ".env" in result["hint"]
        assert result["channels"] == []

    def test_key_is_read_from_a_local_env_file(
        self, tmp_path: Path, config: CampaignConfig, monkeypatch
    ) -> None:
        for var in ("BUFFER_API_KEY", "BUFFER_ACCESS_TOKEN",
                    config.buffer.api_key_secret):
            monkeypatch.delenv(var, raising=False)
        (tmp_path / ".env").write_text(
            "# a comment\nBUFFER_API_KEY=from-dotenv\n", encoding="utf-8"
        )
        assert self._app(tmp_path, config).buffer_key() == "from-dotenv"

    def test_environment_takes_precedence_over_the_file(
        self, tmp_path: Path, config: CampaignConfig, monkeypatch
    ) -> None:
        (tmp_path / ".env").write_text("BUFFER_API_KEY=from-file\n", encoding="utf-8")
        monkeypatch.setenv("BUFFER_API_KEY", "from-env")
        assert self._app(tmp_path, config).buffer_key() == "from-env"

    def test_quotes_are_stripped_from_the_file_value(
        self, tmp_path: Path, config: CampaignConfig, monkeypatch
    ) -> None:
        for var in ("BUFFER_API_KEY", "BUFFER_ACCESS_TOKEN",
                    config.buffer.api_key_secret):
            monkeypatch.delenv(var, raising=False)
        (tmp_path / ".env").write_text('BUFFER_API_KEY="quoted"\n', encoding="utf-8")
        assert self._app(tmp_path, config).buffer_key() == "quoted"

    def test_a_local_env_file_is_gitignored(self) -> None:
        """It would hold a live API key; committing one is the failure mode."""
        root = Path(__file__).resolve().parents[1]
        assert ".env" in (root / ".gitignore").read_text(encoding="utf-8")
