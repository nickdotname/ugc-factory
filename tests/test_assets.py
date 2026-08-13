"""M4 — GitHub Releases media store (SPEC §5). No network."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.assets import (
    GitHubReleasesStore,
    LocalLibrary,
    check_music_licenses,
    github_token_from_env,
)
from src.errors import AuthError, MediaStoreError
from src.logging import StructuredLogger
from src.ports import FrozenClock

from tests.fakes import FakeResponse, FakeSession

NOW = datetime(2026, 8, 13, 5, 0, tzinfo=timezone.utc)


def make_store(session: FakeSession) -> GitHubReleasesStore:
    return GitHubReleasesStore(
        "owner/repo",
        "ghp_faketoken",
        StructuredLogger({}, io.StringIO()),
        FrozenClock(NOW),
        session=session,
        sleep=lambda _seconds: None,
    )


def release_json(tag: str, assets=None, created: datetime | None = None) -> dict:
    return {
        "id": 999,
        "tag_name": tag,
        "created_at": (created or NOW).isoformat().replace("+00:00", "Z"),
        "upload_url": f"https://uploads.github.com/repos/owner/repo/releases/999/assets{{?name,label}}",
        "assets": assets or [],
    }


class TestConstruction:
    def test_bad_repo_format_rejected(self) -> None:
        with pytest.raises(MediaStoreError, match="owner/name"):
            GitHubReleasesStore(
                "justaname", "t", StructuredLogger({}, io.StringIO()), FrozenClock(NOW)
            )


class TestAuth:
    def test_401_raises_auth_error_and_is_not_retryable(self) -> None:
        s = FakeSession().route("GET", "/releases/tags/", FakeResponse(401))
        with pytest.raises(AuthError) as exc:
            make_store(s).download_assets("assets-demo", Path("/tmp/x"))
        assert exc.value.retryable is False

    def test_403_with_exhausted_rate_limit_is_not_an_auth_error(self) -> None:
        """SPEC §2.2 — classify by header, not by message text."""
        s = FakeSession().route(
            "GET", "/releases/tags/",
            FakeResponse(403, headers={"X-RateLimit-Remaining": "0",
                                       "X-RateLimit-Reset": "1760000000"}),
        )
        with pytest.raises(MediaStoreError, match="rate limit"):
            make_store(s).download_assets("assets-demo", Path("/tmp/x"))

    def test_403_without_rate_limit_header_is_an_auth_error(self) -> None:
        s = FakeSession().route(
            "GET", "/releases/tags/",
            FakeResponse(403, headers={"X-RateLimit-Remaining": "4999"}),
        )
        with pytest.raises(AuthError):
            make_store(s).download_assets("assets-demo", Path("/tmp/x"))

    def test_token_from_env_fails_loud_when_absent(self) -> None:
        with pytest.raises(AuthError, match="GITHUB_TOKEN"):
            github_token_from_env({})

    def test_token_from_env_accepts_gh_token_alias(self) -> None:
        assert github_token_from_env({"GH_TOKEN": "abc"}) == "abc"


class TestDownload:
    def test_missing_assets_release_fails_loud(self, tmp_path: Path) -> None:
        s = FakeSession().route("GET", "/releases/tags/", FakeResponse(404))
        with pytest.raises(MediaStoreError, match="not found"):
            make_store(s).download_assets("assets-demo", tmp_path)

    def test_downloads_each_asset(self, tmp_path: Path) -> None:
        payload = b"video-bytes"
        s = FakeSession()
        s.route("GET", "/releases/tags/", FakeResponse(
            200, release_json("assets-demo", assets=[
                {"id": 1, "name": "hook_01.mp4", "size": len(payload)},
                {"id": 2, "name": "body_01.mp4", "size": len(payload)},
            ])
        ))
        s.route("GET", "/releases/assets/", FakeResponse(200, content=payload))

        files = make_store(s).download_assets("assets-demo", tmp_path)
        assert sorted(p.name for p in files) == ["body_01.mp4", "hook_01.mp4"]
        assert (tmp_path / "hook_01.mp4").read_bytes() == payload

    def test_existing_file_of_matching_size_is_not_refetched(self, tmp_path: Path) -> None:
        payload = b"cached"
        (tmp_path / "hook_01.mp4").write_bytes(payload)
        s = FakeSession()
        s.route("GET", "/releases/tags/", FakeResponse(
            200, release_json("assets-demo", assets=[
                {"id": 1, "name": "hook_01.mp4", "size": len(payload)},
            ])
        ))
        make_store(s).download_assets("assets-demo", tmp_path)
        assert not s.calls_to("/releases/assets/")

    def test_truncated_download_does_not_leave_a_usable_file(self, tmp_path: Path) -> None:
        """A .part rename means an interrupted fetch cannot poison the cache."""
        s = FakeSession()
        s.route("GET", "/releases/tags/", FakeResponse(
            200, release_json("assets-demo", assets=[
                {"id": 1, "name": "hook_01.mp4", "size": 99},
            ])
        ))
        s.route("GET", "/releases/assets/", FakeResponse(500))
        with pytest.raises(MediaStoreError):
            make_store(s).download_assets("assets-demo", tmp_path)
        assert not (tmp_path / "hook_01.mp4").exists()


class TestPublish:
    def _publish_session(self, existing_assets=None) -> FakeSession:
        s = FakeSession()
        s.route("GET", "/releases/tags/", FakeResponse(
            200, release_json("render-2026-08-13", assets=existing_assets or [])
        ))
        s.route("POST", "uploads.github.com", lambda r: FakeResponse(
            201, {"browser_download_url":
                  "https://github.com/owner/repo/releases/download/render-2026-08-13/x.mp4"}
        ))
        s.route("DELETE", "/releases/assets/", FakeResponse(204))
        return s

    def test_uploads_and_returns_public_url(self, tmp_path: Path) -> None:
        video = tmp_path / "x.mp4"
        video.write_bytes(b"0" * 1024)
        s = self._publish_session()
        published = make_store(s).publish("render-2026-08-13", [video])
        assert len(published) == 1
        assert published[0].url.startswith("https://github.com/owner/repo/releases/download/")
        assert published[0].size_bytes == 1024

    def test_creates_release_when_absent(self, tmp_path: Path) -> None:
        video = tmp_path / "x.mp4"
        video.write_bytes(b"0" * 10)
        s = FakeSession()
        s.route("GET", "/releases/tags/", FakeResponse(404))
        s.route("POST", "/repos/owner/repo/releases", FakeResponse(
            201, release_json("render-2026-08-13")
        ))
        s.route("POST", "uploads.github.com", FakeResponse(
            201, {"browser_download_url": "https://github.com/x.mp4"}
        ))
        make_store(s).publish("render-2026-08-13", [video])
        created = [c for c in s.calls if c.method == "POST" and c.url.endswith("/releases")]
        assert created and created[0].json_body["draft"] is False, \
            "a draft release has no public asset URL for Buffer to fetch"

    def test_reupload_deletes_the_old_asset_first(self, tmp_path: Path) -> None:
        """Makes a re-run of a partially failed render idempotent."""
        video = tmp_path / "x.mp4"
        video.write_bytes(b"0" * 10)
        s = self._publish_session(existing_assets=[{"id": 55, "name": "x.mp4", "size": 5}])
        make_store(s).publish("render-2026-08-13", [video])
        assert s.calls_to("/releases/assets/55")

    def test_empty_file_is_refused(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.mp4"
        empty.touch()
        with pytest.raises(MediaStoreError, match="empty file"):
            make_store(self._publish_session()).publish("render-x", [empty])

    def test_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(MediaStoreError, match="missing file"):
            make_store(self._publish_session()).publish("render-x", [tmp_path / "no.mp4"])


class TestCleanup:
    def _cleanup_session(self, releases) -> FakeSession:
        s = FakeSession()
        s.route("GET", "/repos/owner/repo/releases", FakeResponse(200, releases))
        s.route("DELETE", "/repos/owner/repo/releases/", FakeResponse(204))
        return s

    def test_deletes_only_old_releases_with_the_prefix(self) -> None:
        releases = [
            {"id": 1, "tag_name": "render-2026-07-01",
             "created_at": (NOW - timedelta(days=40)).isoformat().replace("+00:00", "Z")},
            {"id": 2, "tag_name": "render-2026-08-12",
             "created_at": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z")},
            {"id": 3, "tag_name": "assets-demo",
             "created_at": (NOW - timedelta(days=400)).isoformat().replace("+00:00", "Z")},
        ]
        deleted = make_store(self._cleanup_session(releases)).cleanup("render-", 14)
        assert deleted == ["render-2026-07-01"], \
            "the assets release must never be swept up by render cleanup"

    def test_recent_release_is_kept(self) -> None:
        """Deleting a Release whose video Buffer has not published yet breaks it."""
        releases = [{"id": 1, "tag_name": "render-2026-08-10",
                     "created_at": (NOW - timedelta(days=3)).isoformat().replace("+00:00", "Z")}]
        assert make_store(self._cleanup_session(releases)).cleanup("render-", 14) == []

    def test_unparseable_date_is_skipped_not_fatal(self) -> None:
        releases = [{"id": 1, "tag_name": "render-bad", "created_at": "not-a-date"}]
        assert make_store(self._cleanup_session(releases)).cleanup("render-", 14) == []


class TestLocalLibrary:
    def test_groups_flat_directory_by_prefix(self, tmp_path: Path) -> None:
        """SPEC §7 — Release assets are a flat namespace, so prefix is the grouping."""
        for name in ("hook_01.mp4", "hook_02.mov", "body_01.mp4",
                     "music_lofi.mp3", "music_jazz.wav", "README.txt"):
            (tmp_path / name).write_bytes(b"x")
        lib = LocalLibrary.from_directory(tmp_path)
        assert [p.name for p in lib.hooks] == ["hook_01.mp4", "hook_02.mov"]
        assert [p.name for p in lib.bodies] == ["body_01.mp4"]
        assert [p.name for p in lib.music] == ["music_jazz.wav", "music_lofi.mp3"]

    def test_ignores_unknown_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "hook_01.txt").write_bytes(b"x")
        (tmp_path / "music_01.flac").write_bytes(b"x")
        lib = LocalLibrary.from_directory(tmp_path)
        assert lib.hooks == () and lib.music == ()

    def test_by_name_resolves_selection_to_paths(self, tmp_path: Path) -> None:
        (tmp_path / "hook_01.mp4").write_bytes(b"x")
        lib = LocalLibrary.from_directory(tmp_path)
        assert lib.by_name()["hook_01.mp4"].name == "hook_01.mp4"

    def test_new_file_appears_without_config_change(self, tmp_path: Path) -> None:
        """SPEC §14 — drop a new MP3 in, next render picks it up."""
        (tmp_path / "music_a.mp3").write_bytes(b"x")
        assert len(LocalLibrary.from_directory(tmp_path).music) == 1
        (tmp_path / "music_b.mp3").write_bytes(b"x")
        assert len(LocalLibrary.from_directory(tmp_path).music) == 2


class TestMusicLicenses:
    def test_missing_licenses_file_reports_every_track(self, tmp_path: Path) -> None:
        tracks = (tmp_path / "music_a.mp3", tmp_path / "music_b.mp3")
        for t in tracks:
            t.write_bytes(b"x")
        missing = check_music_licenses(
            tracks, tmp_path / "LICENSES.md", StructuredLogger({}, io.StringIO())
        )
        assert missing == ["music_a.mp3", "music_b.mp3"]

    def test_documented_track_is_not_reported(self, tmp_path: Path) -> None:
        track = tmp_path / "music_a.mp3"
        track.write_bytes(b"x")
        lic = tmp_path / "LICENSES.md"
        lic.write_text("| music_a.mp3 | Pixabay | CC0 |\n", encoding="utf-8")
        assert check_music_licenses((track,), lic, StructuredLogger({}, io.StringIO())) == []

    def test_undocumented_track_is_reported(self, tmp_path: Path) -> None:
        a, b = tmp_path / "music_a.mp3", tmp_path / "music_b.mp3"
        a.write_bytes(b"x"); b.write_bytes(b"x")
        lic = tmp_path / "LICENSES.md"
        lic.write_text("| music_a.mp3 | Pixabay | CC0 |\n", encoding="utf-8")
        assert check_music_licenses((a, b), lic, StructuredLogger({}, io.StringIO())) == \
            ["music_b.mp3"]

    def test_no_music_needs_no_licenses_file(self, tmp_path: Path) -> None:
        assert check_music_licenses((), tmp_path / "LICENSES.md",
                                    StructuredLogger({}, io.StringIO())) == []
