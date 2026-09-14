"""Phase 2 — the repo-level Buffer account registry.

Pure: no network, no ffmpeg, no clock.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.accounts import AccountsConfig, accounts_for, load_accounts
from src.config import AccountFilter
from src.errors import ConfigError
from src.platforms import Service

REPO_ROOT = Path(__file__).resolve().parents[1]

TWO = """
accounts:
  - name: brand_ig
    network: instagram
    api_key_secret: BUFFER_API_KEY
    channel_id: aaa111
    post_type: reel
  - name: brand_yt
    network: youtube
    api_key_secret: BUFFER_API_KEY
    channel_id: bbb222
    post_type: short
"""


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "accounts.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


class TestLoading:
    def test_a_missing_file_is_not_an_error(self, tmp_path: Path) -> None:
        """A repo that has not adopted fan-out has no registry, and every
        campaign keeps posting through its own buffer block."""
        assert load_accounts(tmp_path / "nope.yaml").accounts == ()

    def test_an_empty_file_is_not_an_error(self, tmp_path: Path) -> None:
        assert load_accounts(write(tmp_path, "")).accounts == ()

    def test_it_loads_accounts(self, tmp_path: Path) -> None:
        cfg = load_accounts(write(tmp_path, TWO))
        assert [a.name for a in cfg.accounts] == ["brand_ig", "brand_yt"]
        assert cfg.accounts[0].network is Service.INSTAGRAM
        assert cfg.accounts[0].max_buffer_queue == 10

    def test_unknown_keys_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            load_accounts(write(tmp_path, TWO + """
  - name: typo
    network: tiktok
    api_key_secret: BUFFER_API_KEY
    channel_id: ccc
    post_type: post
    psots_per_day: 4
"""))

    def test_a_yaml_list_at_the_top_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError):
            load_accounts(write(tmp_path, "- name: loose\n"))


class TestValidation:
    def test_duplicate_names_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="duplicate names"):
            load_accounts(write(tmp_path, """
accounts:
  - name: same
    network: instagram
    api_key_secret: BUFFER_API_KEY
    channel_id: aaa
    post_type: reel
  - name: same
    network: tiktok
    api_key_secret: BUFFER_API_KEY
    channel_id: bbb
    post_type: post
"""))

    def test_two_accounts_on_one_channel_are_rejected(self, tmp_path: Path) -> None:
        """That channel would receive every post twice."""
        with pytest.raises(ConfigError, match="every post twice"):
            load_accounts(write(tmp_path, """
accounts:
  - name: one
    network: instagram
    api_key_secret: BUFFER_API_KEY
    channel_id: shared
    post_type: reel
  - name: two
    network: instagram
    api_key_secret: BUFFER_API_KEY_2
    channel_id: shared
    post_type: reel
"""))

    def test_a_post_type_the_network_refuses_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not valid for youtube"):
            load_accounts(write(tmp_path, """
accounts:
  - name: wrong
    network: youtube
    api_key_secret: BUFFER_API_KEY
    channel_id: aaa
    post_type: reel
"""))

    def test_a_key_slot_the_workflows_do_not_pass_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """It would load fine and then fail at 05:00 with 'not set'."""
        with pytest.raises(ConfigError, match="api_key_secret must be one of"):
            load_accounts(write(tmp_path, """
accounts:
  - name: bad
    network: instagram
    api_key_secret: BUFFER_API_KEY_MYBRAND
    channel_id: aaa
    post_type: reel
"""))

    def test_a_pasted_token_where_a_secret_name_belongs_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """The failure mode that leaks a credential into a public repo."""
        with pytest.raises(ConfigError):
            load_accounts(write(tmp_path, """
accounts:
  - name: leaky
    network: instagram
    api_key_secret: BUFFER_API_KEY
    channel_id_secret: 1/abc-NOT-a-name
    post_type: reel
"""))

    def test_both_or_neither_channel_source_is_rejected(self, tmp_path: Path) -> None:
        for block in (
            "    channel_id: aaa\n    channel_id_secret: BUFFER_CHANNEL_X\n",
            "",
        ):
            with pytest.raises(ConfigError, match="exactly one"):
                load_accounts(write(tmp_path, f"""
accounts:
  - name: ambiguous
    network: instagram
    api_key_secret: BUFFER_API_KEY
    post_type: reel
{block}"""))


class TestSelection:
    def _two(self, tmp_path: Path) -> AccountsConfig:
        return load_accounts(write(tmp_path, TWO))

    def test_disabled_accounts_are_not_live(self, tmp_path: Path) -> None:
        cfg = load_accounts(write(tmp_path, TWO + """
  - name: parked
    network: tiktok
    api_key_secret: BUFFER_API_KEY
    channel_id: ccc333
    post_type: post
    enabled: false
"""))
        assert len(cfg.accounts) == 3
        assert [a.name for a in cfg.live] == ["brand_ig", "brand_yt"]

    def test_key_slots_are_deduplicated(self, tmp_path: Path) -> None:
        """One publisher per key, not per account — accounts under one login
        share a key and must share its request tally."""
        cfg = load_accounts(write(tmp_path, TWO + """
  - name: other_login
    network: tiktok
    api_key_secret: BUFFER_API_KEY_2
    channel_id: ccc333
    post_type: post
"""))
        assert cfg.key_slots() == ("BUFFER_API_KEY", "BUFFER_API_KEY_2")

    def test_the_default_filter_reaches_every_account(self, tmp_path: Path) -> None:
        cfg = self._two(tmp_path)
        reached = accounts_for(cfg, AccountFilter())
        assert [a.name for a in reached] == ["brand_ig", "brand_yt"]

    def test_a_blocked_account_is_skipped(self, tmp_path: Path) -> None:
        cfg = self._two(tmp_path)
        reached = accounts_for(cfg, AccountFilter(names=("brand_yt",)))
        assert [a.name for a in reached] == ["brand_ig"]

    def test_an_allow_list_reaches_only_what_it_names(self, tmp_path: Path) -> None:
        cfg = self._two(tmp_path)
        reached = accounts_for(
            cfg, AccountFilter(mode="allow", names=("brand_yt",))
        )
        assert [a.name for a in reached] == ["brand_yt"]

    def test_allow_with_no_names_is_rejected(self) -> None:
        """It reads as 'allow everything' and means the opposite — a campaign
        that renders nightly and posts nowhere, with nothing failing to say so."""
        with pytest.raises(ValueError, match="post to nothing"):
            AccountFilter(mode="allow")


class TestShippedRegistry:
    """The real accounts.yaml in this repo."""

    def test_it_loads(self) -> None:
        cfg = load_accounts(REPO_ROOT / "accounts.yaml")
        assert len(cfg.accounts) == 6

    def test_it_covers_both_logins_on_all_three_networks(self) -> None:
        cfg = load_accounts(REPO_ROOT / "accounts.yaml")
        by_slot: dict[str, set[Service]] = {}
        for account in cfg.live:
            by_slot.setdefault(account.api_key_secret, set()).add(account.network)
        assert by_slot == {
            "BUFFER_API_KEY": {Service.INSTAGRAM, Service.TIKTOK, Service.YOUTUBE},
            "BUFFER_API_KEY_2": {Service.INSTAGRAM, Service.TIKTOK, Service.YOUTUBE},
        }

    def test_every_shipped_campaign_channel_has_an_account(self) -> None:
        """The three clubs campaigns are the three nickdotname channels. If a
        channel id here drifts from the campaign still posting to it, fan-out
        would quietly post to a different channel than the one being measured.
        """
        from src.campaigns import list_campaigns
        from src.config import load_campaign

        registry = load_accounts(REPO_ROOT / "accounts.yaml")
        known = {a.channel_id for a in registry.accounts if a.channel_id}
        for summary in list_campaigns(REPO_ROOT / "campaigns"):
            config = load_campaign(REPO_ROOT / "campaigns", summary.slug)
            if config.buffer.channel_id:
                assert config.buffer.channel_id in known, (
                    f"{summary.slug} posts to {config.buffer.channel_id}, which "
                    f"no account in accounts.yaml names"
                )
