"""Creating and listing campaigns from the dashboard (SPEC §15)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.campaigns import (
    create_campaign,
    list_campaigns,
    render_config,
    slug_error,
)
from src.config import PostType, load_campaign
from src.errors import ConfigError
from src.platforms import Service


class TestSlugRules:
    def test_accepts_a_normal_slug(self) -> None:
        assert slug_error("brand_tiktok", []) is None

    def test_rejects_empty(self) -> None:
        assert slug_error("", []) == "slug is required"

    def test_rejects_a_duplicate(self) -> None:
        assert "already exists" in (slug_error("taken", ["taken"]) or "")

    @pytest.mark.parametrize("bad", [
        "Brand",        # uppercase
        "1brand",       # leading digit
        "brand-tiktok", # hyphen: legal in a path, illegal in a shell variable
        "brand tiktok", # space
        "../escape",
        "b" * 40,
    ])
    def test_rejects_unsafe_slugs(self, bad: str) -> None:
        assert slug_error(bad, []) is not None, bad

    def test_hyphen_rejection_is_about_secret_names(self) -> None:
        """BUFFER_CHANNEL_BRAND-TIKTOK is not a legal env var name."""
        assert "secret names" in (slug_error("brand-tiktok", []) or "")


class TestRenderConfig:
    def test_post_type_matches_the_service(self) -> None:
        for service, expected in (
            (Service.INSTAGRAM, "reel"),
            (Service.TIKTOK, "post"),
            (Service.YOUTUBE, "short"),
        ):
            assert f"post_type: {expected}" in render_config("x", service)

    def test_channel_secret_name_derives_from_the_slug(self) -> None:
        """Only when the id is not supplied directly."""
        text = render_config("brand_yt", Service.YOUTUBE)
        assert "BUFFER_CHANNEL_BRAND_YT" in text

    def test_a_supplied_channel_id_goes_in_config_not_secrets(self) -> None:
        """Channel ids are identifiers, and keeping them out of Secrets is what
        lets the workflows name a fixed secret set for any number of campaigns."""
        text = render_config("brand_yt", Service.YOUTUBE, channel_id="abc123")
        assert "channel_id: abc123" in text
        assert "BUFFER_CHANNEL_BRAND_YT" not in text

    def test_webhook_secret_is_shared(self) -> None:
        """A per-campaign webhook name would be a new secret per campaign."""
        assert "webhook_secret: DISCORD_WEBHOOK\n" in render_config(
            "brand_yt", Service.YOUTUBE
        )

    def test_starts_in_dry_run(self) -> None:
        assert "dry_run: true" in render_config("x", Service.INSTAGRAM)

    def test_shared_asset_release_is_emitted_when_given(self) -> None:
        assert "assets_release: assets-clubs" in render_config(
            "x", Service.TIKTOK, assets_release="assets-clubs"
        )

    def test_no_assets_release_line_when_not_shared(self) -> None:
        assert "assets_release:" not in render_config("x", Service.TIKTOK)

    def test_wrapping_window_is_expressed_as_equal_hours(self) -> None:
        text = render_config("x", Service.INSTAGRAM, start_hour=15)
        assert "start_hour: 15" in text and "end_hour: 15" in text


class TestCreateCampaign:
    def test_creates_a_loadable_campaign(self, tmp_path: Path) -> None:
        created = create_campaign(tmp_path, "brand_ig", Service.INSTAGRAM)
        config = load_campaign(tmp_path, "brand_ig")
        assert config.slug == "brand_ig"
        assert config.buffer.post_type is PostType.REEL
        assert created.slug == "brand_ig"

    def test_writes_all_four_files(self, tmp_path: Path) -> None:
        created = create_campaign(tmp_path, "brand_ig", Service.INSTAGRAM)
        names = {p.name for p in created.paths}
        assert names == {"config.yaml", "captions.txt", "queue.json", "history.json"}
        for path in created.paths:
            assert path.is_file()

    def test_reports_the_secrets_the_operator_must_set(self, tmp_path: Path) -> None:
        created = create_campaign(tmp_path, "brand_tt", Service.TIKTOK)
        assert created.required_secrets == (
            "BUFFER_CHANNEL_BRAND_TT", "DISCORD_WEBHOOK"
        )

    def test_a_supplied_channel_id_removes_that_secret(self, tmp_path: Path) -> None:
        created = create_campaign(tmp_path, "brand_tt", Service.TIKTOK,
                                  channel_id="chan-123")
        assert "BUFFER_CHANNEL_BRAND_TT" not in created.required_secrets

    def test_new_campaign_starts_paused(self, tmp_path: Path) -> None:
        """SPEC §15 step 7 — look at a dispatch run before anything goes live."""
        create_campaign(tmp_path, "brand_ig", Service.INSTAGRAM)
        assert load_campaign(tmp_path, "brand_ig").posting.dry_run is True

    def test_youtube_campaign_is_valid_end_to_end(self, tmp_path: Path) -> None:
        """post_type/service mismatches are rejected by config; creation must
        not produce one."""
        create_campaign(tmp_path, "brand_yt", Service.YOUTUBE)
        config = load_campaign(tmp_path, "brand_yt")
        assert config.buffer.service is Service.YOUTUBE
        assert config.buffer.post_type is PostType.SHORT

    def test_duplicate_slug_is_refused(self, tmp_path: Path) -> None:
        create_campaign(tmp_path, "brand_ig", Service.INSTAGRAM)
        with pytest.raises(ConfigError, match="already exists"):
            create_campaign(tmp_path, "brand_ig", Service.TIKTOK)

    def test_unsafe_slug_is_refused_before_writing(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            create_campaign(tmp_path, "../escape", Service.INSTAGRAM)
        assert not (tmp_path / "..").joinpath("escape").exists()

    def test_shared_library_means_no_duplicate_upload(self, tmp_path: Path) -> None:
        create_campaign(tmp_path, "a_ig", Service.INSTAGRAM)
        create_campaign(tmp_path, "a_tt", Service.TIKTOK,
                        assets_release="assets-a_ig")
        assert load_campaign(tmp_path, "a_tt").assets_tag == "assets-a_ig"

    def test_descriptions_can_be_copied(self, tmp_path: Path) -> None:
        create_campaign(tmp_path, "a_tt", Service.TIKTOK,
                        descriptions="shared copy\n---\nsecond one\n")
        text = (tmp_path / "a_tt" / "captions.txt").read_text(encoding="utf-8")
        assert "shared copy" in text

    def test_cadence_is_configurable(self, tmp_path: Path) -> None:
        create_campaign(tmp_path, "a_ig", Service.INSTAGRAM,
                        posts_per_day=6, start_hour=9)
        c = load_campaign(tmp_path, "a_ig")
        assert c.posting.posts_per_day == 6 and c.posting.start_hour == 9


class TestListCampaigns:
    def test_lists_created_campaigns(self, tmp_path: Path) -> None:
        create_campaign(tmp_path, "a_ig", Service.INSTAGRAM)
        create_campaign(tmp_path, "b_tt", Service.TIKTOK)
        assert [c.slug for c in list_campaigns(tmp_path)] == ["a_ig", "b_tt"]

    def test_template_directories_are_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "_template").mkdir()
        create_campaign(tmp_path, "a_ig", Service.INSTAGRAM)
        assert [c.slug for c in list_campaigns(tmp_path)] == ["a_ig"]

    def test_a_broken_campaign_is_reported_not_hidden(self, tmp_path: Path) -> None:
        """Silently skipping it leaves the operator wondering why it never posts."""
        broken = tmp_path / "oops"
        broken.mkdir()
        (broken / "config.yaml").write_text("slug: [unclosed\n", encoding="utf-8")
        summaries = list_campaigns(tmp_path)
        assert len(summaries) == 1
        assert summaries[0].valid is False and summaries[0].error

    def test_missing_directory_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert list_campaigns(tmp_path / "absent") == []


class TestShippedRepoStillWorks:
    def test_real_campaigns_all_load(self) -> None:
        root = Path(__file__).resolve().parents[1] / "campaigns"
        summaries = list_campaigns(root)
        assert len(summaries) >= 3
        for s in summaries:
            assert s.valid, f"{s.slug}: {s.error}"


class TestMultipleBufferAccounts:
    """One Buffer account per campaign means one API key per campaign."""

    def test_campaign_can_target_a_second_account(self, tmp_path: Path) -> None:
        create_campaign(tmp_path, "brand_ig", Service.INSTAGRAM,
                        api_key_secret="BUFFER_API_KEY_2")
        cfg = load_campaign(tmp_path, "brand_ig")
        assert cfg.buffer.api_key_secret == "BUFFER_API_KEY_2"

    def test_default_is_the_first_account(self, tmp_path: Path) -> None:
        create_campaign(tmp_path, "brand_ig", Service.INSTAGRAM)
        assert load_campaign(tmp_path, "brand_ig").buffer.api_key_secret == \
            "BUFFER_API_KEY"

    def test_campaigns_on_different_accounts_coexist(self, tmp_path: Path) -> None:
        create_campaign(tmp_path, "a_ig", Service.INSTAGRAM,
                        api_key_secret="BUFFER_API_KEY")
        create_campaign(tmp_path, "b_ig", Service.INSTAGRAM,
                        api_key_secret="BUFFER_API_KEY_3", channel_id="chan-b")
        keys = {
            c.slug: load_campaign(tmp_path, c.slug).buffer.api_key_secret
            for c in list_campaigns(tmp_path)
        }
        assert keys == {"a_ig": "BUFFER_API_KEY", "b_ig": "BUFFER_API_KEY_3"}

    def test_an_unwired_slot_cannot_be_created(self, tmp_path: Path) -> None:
        """Creation must not produce a config that fails at 05:00."""
        with pytest.raises(ConfigError, match="must be one of"):
            create_campaign(tmp_path, "brand_ig", Service.INSTAGRAM,
                            api_key_secret="BUFFER_API_KEY_MYBRAND")

    def test_every_slot_is_passed_by_every_workflow(self) -> None:
        """A slot config accepts but no workflow exports is a 5am failure."""
        import yaml

        from src.config import BUFFER_KEY_SLOTS

        root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        for name in ("render.yml", "topup.yml", "metrics.yml", "cleanup.yml",
                     "diagnose.yml", "preflight.yml"):
            doc = yaml.safe_load((root / name).read_text(encoding="utf-8"))
            exported: set[str] = set()
            for job in doc["jobs"].values():
                for step in (job.get("steps") or []):
                    if "src.cli" in str(step.get("run", "")):
                        exported |= set((step.get("env") or {}).keys())
            missing = set(BUFFER_KEY_SLOTS) - exported
            assert not missing, f"{name} does not pass {sorted(missing)}"
