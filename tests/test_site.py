"""The public address rendered videos are served from, and the check before posting."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from src import cli
from src.config import CampaignConfig
from src.errors import ConfigError, MediaStoreError
from src.assets import assert_publicly_readable
from src.site import media_base, public_media_url

GITHUB = (
    "https://github.com/nickdotname/ugc-factory/releases/download/"
    "render-clubs-2026-11-11/6142ecfd-051b-4c91-af34-c80363374915.mp4"
)
PUBLIC = (
    "https://factory.example/v/render-clubs-2026-11-11/"
    "6142ecfd-051b-4c91-af34-c80363374915.mp4"
)


class TestMediaBase:
    def test_no_file_means_githubs_own_links(self, tmp_path: Path) -> None:
        assert media_base(tmp_path) == ""

    def test_reads_the_address_without_a_trailing_slash(self, tmp_path: Path) -> None:
        (tmp_path / "site.yaml").write_text("media_base_url: https://factory.example/v/\n")
        assert media_base(tmp_path) == "https://factory.example/v"

    def test_an_empty_setting_is_off(self, tmp_path: Path) -> None:
        (tmp_path / "site.yaml").write_text("media_base_url:\n")
        assert media_base(tmp_path) == ""

    def test_plain_http_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "site.yaml").write_text("media_base_url: http://factory.example/v\n")
        with pytest.raises(ConfigError, match="https"):
            media_base(tmp_path)

    def test_the_repos_own_file_is_valid(self) -> None:
        assert media_base(Path(__file__).resolve().parent.parent).startswith("https://")


class TestPublicUrl:
    def test_a_release_link_moves_to_the_public_address(self) -> None:
        assert public_media_url(GITHUB, "https://factory.example/v") == PUBLIC

    def test_it_is_safe_to_apply_twice(self) -> None:
        assert public_media_url(PUBLIC, "https://factory.example/v") == PUBLIC

    def test_no_address_configured_changes_nothing(self) -> None:
        assert public_media_url(GITHUB, "") == GITHUB

    def test_other_links_are_left_alone(self) -> None:
        other = "https://cdn.example/video.mp4"
        assert public_media_url(other, "https://factory.example/v") == other


class _Response:
    def __init__(self, status: int) -> None:
        self.status_code = status

    def close(self) -> None:
        pass


class TestReadable:
    @pytest.mark.parametrize("status", [200, 206])
    def test_a_readable_link_passes(self, status: int) -> None:
        seen = {}

        def get(url: str, **kwargs: object) -> _Response:
            seen.update(kwargs, url=url)
            return _Response(status)

        assert_publicly_readable(PUBLIC, get=get)
        # Asked for one byte, and with no credentials of any kind.
        assert seen["headers"] == {"Range": "bytes=0-0"}

    @pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
    def test_an_unreadable_link_stops_the_run(self, status: int) -> None:
        with pytest.raises(MediaStoreError, match="not publicly readable"):
            assert_publicly_readable(PUBLIC, get=lambda url, **kw: _Response(status), sleep=lambda s: None)

    def test_a_site_that_is_down_stops_the_run(self) -> None:
        def get(url: str, **kwargs: object) -> _Response:
            raise requests.ConnectionError("no route")

        with pytest.raises(MediaStoreError, match="could not be reached"):
            assert_publicly_readable(PUBLIC, get=get, sleep=lambda s: None)

    def test_a_passing_hiccup_is_asked_again(self) -> None:
        # One 502 from the media site used to fail a campaign's whole topup.
        answers = [502, 503, 206]
        waited: list[float] = []
        assert_publicly_readable(
            PUBLIC, get=lambda url, **kw: _Response(answers.pop(0)), sleep=waited.append
        )
        assert answers == [] and len(waited) == 2

    def test_a_missing_video_is_not_asked_again(self) -> None:
        calls: list[str] = []

        def get(url: str, **kwargs: object) -> _Response:
            calls.append(url)
            return _Response(404)

        with pytest.raises(MediaStoreError, match="not publicly readable"):
            assert_publicly_readable(PUBLIC, get=get, sleep=lambda s: None)
        assert len(calls) == 1


class TestPostableUrl:
    @pytest.fixture(autouse=True)
    def _site(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "site.yaml").write_text("media_base_url: https://factory.example/v\n")
        monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cli, "_READABLE", set())

    def _live(self, config: CampaignConfig, dry_run: bool = False) -> CampaignConfig:
        return config.model_copy(
            update={"posting": config.posting.model_copy(update={"dry_run": dry_run})}
        )

    def test_an_old_queue_item_is_posted_from_the_public_address(
        self, config: CampaignConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[str] = []
        monkeypatch.setattr(cli, "assert_publicly_readable", asked.append)
        assert cli._postable_url(GITHUB, self._live(config)) == PUBLIC
        # Going to a second account, the same video is not asked for again.
        assert cli._postable_url(GITHUB, self._live(config)) == PUBLIC
        assert asked == [PUBLIC]

    def test_an_unreadable_video_raises_before_anything_is_sent(
        self, config: CampaignConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(url: str) -> None:
            raise MediaStoreError("not publicly readable")

        monkeypatch.setattr(cli, "assert_publicly_readable", refuse)
        with pytest.raises(MediaStoreError):
            cli._postable_url(GITHUB, self._live(config))

    def test_a_test_run_never_touches_the_network(
        self, config: CampaignConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(url: str) -> None:
            raise AssertionError("checked a link during a dry run")

        monkeypatch.setattr(cli, "assert_publicly_readable", boom)
        assert cli._postable_url(GITHUB, self._live(config, dry_run=True)) == PUBLIC


class TestFirstCommentOnFreePlan:
    def test_buffers_free_plan_refusal_is_recognised(self) -> None:
        from src.errors import InvalidPostError

        refused = InvalidPostError(
            "Buffer createPost failed (InvalidInputError): Invalid post: First "
            "comment requires a paid plan. Please upgrade to use this feature."
        )
        assert cli._first_comment_refused(refused)
        other = InvalidPostError("Invalid post: Video could not be read from its URL.")
        assert not cli._first_comment_refused(other)
