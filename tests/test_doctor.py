"""The readiness check. Pure functions over supplied state — no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import CampaignConfig
from src.doctor import (
    Report,
    Status,
    check_assets,
    check_buffer_channel,
    check_descriptions,
    check_library,
    check_mode,
    check_repo,
    check_secrets,
)


def channel(service: str, reminders: bool | None = False, name: str = "acct") -> dict:
    meta: dict = {"__typename": f"{service.title()}Metadata"}
    if reminders is not None:
        meta["defaultToReminders"] = reminders
    return {"id": "chan-123", "name": name, "service": service, "metadata": meta}


class TestRepo:
    def test_present_repo_passes(self) -> None:
        assert check_repo("owner/name").status is Status.OK

    def test_missing_repo_gives_the_create_command(self) -> None:
        c = check_repo(None)
        assert c.status is Status.MISSING
        assert "gh repo create" in c.fix


class TestSecrets:
    def test_all_present_passes(self, config: CampaignConfig) -> None:
        names = [
            config.buffer.api_key_secret,
            config.buffer.channel_id_secret,
            config.notify.webhook_secret,
        ]
        assert all(c.status is Status.OK for c in check_secrets(config, "o/r", names))

    def test_missing_secret_gives_the_exact_command(self, config: CampaignConfig) -> None:
        checks = check_secrets(config, "o/r", [])
        missing = [c for c in checks if c.status is Status.MISSING]
        assert len(missing) == 3
        assert "gh secret set BUFFER_API_KEY --repo o/r" in missing[0].fix

    def test_fix_never_contains_a_secret_value(self, config: CampaignConfig) -> None:
        """`gh secret set` prompts, so the value never passes through here."""
        for c in check_secrets(config, "o/r", []):
            assert "=" not in c.fix, c.fix

    def test_unreadable_secrets_is_reported_not_assumed_ok(
        self, config: CampaignConfig
    ) -> None:
        checks = check_secrets(config, "o/r", None)
        assert checks[0].status is Status.MISSING
        assert "gh auth login" in checks[0].fix


class TestBufferChannel:
    def test_matching_automatic_channel_passes(self, config: CampaignConfig) -> None:
        c = check_buffer_channel(config, [channel("instagram", reminders=False)])
        assert c.status is Status.OK
        assert "automatic" in c.detail

    def test_reminder_mode_channel_blocks(self, config: CampaignConfig) -> None:
        """SPEC §0 — reminder mode is not automation."""
        c = check_buffer_channel(config, [channel("instagram", reminders=True)])
        assert c.status is Status.MISSING
        assert "REMINDERS" in c.detail

    def test_no_matching_service_blocks_and_lists_what_is_there(
        self, config: CampaignConfig
    ) -> None:
        c = check_buffer_channel(config, [channel("tiktok"), channel("youtube")])
        assert c.status is Status.MISSING
        assert "tiktok" in c.detail and "youtube" in c.detail

    def test_unchecked_is_a_warning_not_a_block(self, config: CampaignConfig) -> None:
        """No local key is a skipped check, not a failure."""
        assert check_buffer_channel(config, None).status is Status.WARN

    def test_missing_metadata_does_not_crash(self, config: CampaignConfig) -> None:
        c = check_buffer_channel(config, [{"id": "x", "name": "n",
                                           "service": "instagram"}])
        assert c.status is Status.OK


class TestAssets:
    def test_populated_library_passes(self, config: CampaignConfig) -> None:
        checks = check_assets({"hook": 6, "body": 3, "music": 5}, config)
        assert checks[0].status is Status.OK

    def test_empty_release_blocks(self, config: CampaignConfig) -> None:
        checks = check_assets({"hook": 0, "body": 0, "music": 0}, config)
        assert checks[0].status is Status.MISSING
        assert "src.cli web" in checks[0].fix

    def test_music_alone_is_not_enough(self, config: CampaignConfig) -> None:
        """Hooks and bodies are required; music is optional."""
        checks = check_assets({"hook": 0, "body": 0, "music": 5}, config)
        assert checks[0].status is Status.MISSING

    def test_no_music_is_acceptable(self, config: CampaignConfig) -> None:
        checks = check_assets({"hook": 2, "body": 2, "music": 0}, config)
        assert checks[0].status is Status.OK


class TestDescriptions:
    def test_real_descriptions_pass(self, tmp_path: Path, config: CampaignConfig) -> None:
        p = tmp_path / "b.txt"
        p.write_text("a real one\n\nanother real one", encoding="utf-8")
        checks = check_descriptions(p, config)
        assert len(checks) == 1 and checks[0].status is Status.OK

    def test_template_text_blocks(self, tmp_path: Path, config: CampaignConfig) -> None:
        """Shipping placeholder copy to a live account is the failure here."""
        p = tmp_path / "b.txt"
        p.write_text("first description goes here\n\nreal one", encoding="utf-8")
        checks = check_descriptions(p, config)
        assert len(checks) == 1, "must not report two contradictory lines"
        assert checks[0].status is Status.MISSING
        assert "template" in checks[0].detail

    def test_over_limit_description_blocks(
        self, tmp_path: Path, config: CampaignConfig
    ) -> None:
        p = tmp_path / "b.txt"
        p.write_text("x" * 3_000, encoding="utf-8")
        assert check_descriptions(p, config)[0].status is Status.MISSING

    def test_missing_file_blocks(self, tmp_path: Path, config: CampaignConfig) -> None:
        assert check_descriptions(tmp_path / "nope.txt", config)[0].status is Status.MISSING

    def test_empty_bank_blocks(self, tmp_path: Path, config: CampaignConfig) -> None:
        p = tmp_path / "b.txt"
        p.write_text("# only comments\n", encoding="utf-8")
        assert check_descriptions(p, config)[0].status is Status.MISSING


class TestLibrary:
    def test_healthy_library_passes(self, config: CampaignConfig) -> None:
        tight = config.model_copy(update={
            "posting": config.posting.model_copy(update={"posts_per_day": 2}),
            "selection": config.selection.model_copy(
                update={"hook_cooldown_days": 2, "caption_cooldown_days": 2}
            ),
        })
        checks = check_library({"hook": 6, "body": 3, "music": 5}, 5, tight)
        assert checks[0].status is Status.OK
        assert not [c for c in checks if c.status is Status.MISSING]

    def test_short_runway_warns_but_does_not_block(self, config: CampaignConfig) -> None:
        """A thin library is a judgement call, not a broken system."""
        checks = check_library({"hook": 1, "body": 1, "music": 1}, 1, config)
        assert checks[0].status is Status.WARN

    def test_cooldown_shortfall_is_reported(self, config: CampaignConfig) -> None:
        loose = config.model_copy(update={
            "posting": config.posting.model_copy(update={"posts_per_day": 6}),
            "selection": config.selection.model_copy(
                update={"caption_cooldown_days": 14}
            ),
        })
        checks = check_library({"hook": 6, "body": 3, "music": 5}, 5, loose)
        assert any("cooldown" in c.name for c in checks)

    def test_unknown_counts_produce_no_checks(self, config: CampaignConfig) -> None:
        assert check_library(None, 5, config) == []


class TestMode:
    def test_dry_run_warns(self, config: CampaignConfig) -> None:
        dry = config.model_copy(
            update={"posting": config.posting.model_copy(update={"dry_run": True})}
        )
        assert check_mode(dry).status is Status.WARN

    def test_live_is_reported_clearly(self, config: CampaignConfig) -> None:
        live = config.model_copy(
            update={"posting": config.posting.model_copy(update={"dry_run": False})}
        )
        c = check_mode(live)
        assert c.status is Status.OK and "LIVE" in c.detail


class TestReport:
    def test_ready_only_when_nothing_blocks(self) -> None:
        r = Report()
        r.add("a", Status.OK)
        r.add("b", Status.WARN)
        assert r.ready

    def test_a_missing_check_blocks(self) -> None:
        r = Report()
        r.add("a", Status.OK)
        r.add("b", Status.MISSING, fix="do the thing")
        assert not r.ready and len(r.blocking) == 1

    def test_next_steps_lists_only_actionable_items(self) -> None:
        r = Report()
        r.add("fine", Status.OK, fix="never shown")
        r.add("broken", Status.MISSING, fix="run this")
        steps = r.next_steps()
        assert "run this" in steps and "never shown" not in steps

    def test_next_steps_is_empty_when_all_clear(self) -> None:
        r = Report()
        r.add("fine", Status.OK)
        assert r.next_steps() == ""

    def test_render_aligns_and_marks_each_status(self) -> None:
        r = Report()
        r.add("short", Status.OK, "detail")
        r.add("a much longer name", Status.MISSING, "gone")
        out = r.render()
        assert "OK" in out and "x" in out
        assert len(out.splitlines()) == 2
