"""The local drop-and-upload interface.

``WebApp`` holds every operation and takes no socket, so these run without
starting a server. The handler is a thin translation layer over it.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.assets import MediaStore, RemoteAsset
from src.config import CampaignConfig
from src.logging import StructuredLogger
from src.models import PartKind
from src.ports import FrozenClock
from src.web import MAX_UPLOAD_BYTES, WebApp, _kind_from, _safe_name

from tests.conftest import needs_ffmpeg

NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


class FakeStore(MediaStore):
    def __init__(self) -> None:
        self.existing: list[str] = []
        self.published: list[str] = []

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
