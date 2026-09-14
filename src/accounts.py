"""The Buffer accounts every campaign fans out to (HANDOFF phase 2).

Responsibility: turn the repo-level ``accounts.yaml`` into a typed, validated
list of Buffer channel connections. This module knows which channels exist and
what each one expects to be posted; it knows nothing about which campaign is
posting, or what.

**Why this is repo-level rather than per campaign.** An account is a place
content goes, not a property of any one content source. Hanging the channel
binding off a campaign is precisely what forces one brand to exist as three
campaigns — the same clips, the same captions and the same cadence, split one
per network purely because SPEC §9 put ``buffer:`` inside the campaign
(CONTEXT §1). Pulling the binding out here is what lets a set like that
collapse back into one.

**What lives on an account rather than a campaign.** Everything the *channel*
determines: which network it is, what a post is called there (a Reel, a
Short), whether it has a separate title field, whether to notify subscribers,
how deep its queue may go. A campaign cannot carry these once it posts to six
channels at once — YouTube wants a required title and a ``short``, Instagram
wants a derived one and a ``reel``, and one campaign now needs both.

Secret *names* only, never values (SPEC §3): this file is committed to a
public repo. Channel and organization ids are not secrets — they identify a
channel but grant nothing without the key — so they sit here in the open,
which is what keeps the workflows naming a fixed set of secrets no matter how
many accounts exist (see ``BUFFER_KEY_SLOTS``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator, model_validator

from src.config import (
    BUFFER_KEY_SLOTS,
    PostType,
    StrictModel,
    TitleStrategy,
    Yaml12Loader,
    check_post_type,
)
from src.errors import ConfigError
from src.platforms import Service

#: Where the registry lives, relative to the repo root.
ACCOUNTS_FILE = "accounts.yaml"


class AccountConfig(StrictModel):
    """One connected Buffer channel."""

    #: Stable identity. Becomes part of the (campaign, creative, account,
    #: network) key that every post and metric is filed under, so renaming one
    #: orphans its history — pick a name you can live with.
    name: str = Field(min_length=1, max_length=64)
    network: Service
    #: Which key slot opens this account. Several accounts under one Buffer
    #: login share a slot; a separate login needs its own.
    api_key_secret: str = Field(min_length=1)
    #: Not a secret (identifies a channel, grants nothing without the key), so
    #: it may sit in the file. Exactly one of these two must be set, same rule
    #: as ``BufferConfig``.
    channel_id: str | None = None
    channel_id_secret: str | None = None
    #: Saves one discovery request per run against the 3,000/30-day budget.
    organization_id: str | None = None

    # ---- what the channel expects to be posted -------------------------
    post_type: PostType
    #: Ignored by networks with no separate title field (Instagram, TikTok).
    title_strategy: TitleStrategy = TitleStrategy.DERIVE
    #: Posted as the first comment, where a link belongs on Instagram.
    first_comment: str = ""
    #: YouTube: push each Short to subscribers. Off by default — notifying a
    #: subscriber list several times a day is a good way to lose it.
    notify_subscribers: bool = False
    #: Shifts this account's publish times this many minutes past the item's
    #: own slot. Fan-out sends one video to every channel, so without a
    #: stagger two accounts on the same network publish it on the same minute
    #: — nothing collides, but anyone following both sees a double, which is
    #: the same failure ``posting.slot_offset_min`` exists to prevent between
    #: campaigns.
    slot_offset_min: int = Field(default=0, ge=0, le=1439)
    #: SPEC §4.1 — Buffer's free plan holds 10 queued posts per channel. A
    #: per-account figure because it is a property of the channel's plan, not
    #: of whatever campaign happens to be filling it.
    max_buffer_queue: int = Field(default=10, ge=1, le=100)
    #: Disconnect an account without deleting its history or its entry.
    enabled: bool = True

    @field_validator("api_key_secret")
    @classmethod
    def _key_slot_is_wired(cls, v: str) -> str:
        if v not in BUFFER_KEY_SLOTS:
            raise ValueError(
                f"api_key_secret must be one of {list(BUFFER_KEY_SLOTS)} — "
                f"these are the slots the workflows pass through. Got {v!r}."
            )
        return v

    @field_validator("api_key_secret", "channel_id_secret")
    @classmethod
    def _looks_like_a_secret_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # A value that looks like an actual token rather than an env var name
        # is the failure mode that leaks credentials into a public repo.
        if not v.replace("_", "").isalnum() or not v.isupper():
            raise ValueError(
                f"{v!r} must be the NAME of an environment variable "
                f"(UPPER_SNAKE_CASE), not a secret value"
            )
        return v

    @model_validator(mode="after")
    def _exactly_one_channel_source(self) -> "AccountConfig":
        if bool(self.channel_id) == bool(self.channel_id_secret):
            raise ValueError(
                f"account {self.name!r}: set exactly one of channel_id (the id "
                f"itself) or channel_id_secret (the name of an env var holding it)"
            )
        return self

    @model_validator(mode="after")
    def _post_type_suits_network(self) -> "AccountConfig":
        check_post_type(self.network, self.post_type)
        return self

    @property
    def identity(self) -> str:
        """What this account resolves to, for spotting two entries on one channel."""
        return self.channel_id or f"secret:{self.channel_id_secret}"


class AccountsConfig(StrictModel):
    """Every Buffer connection this repo can post to."""

    accounts: tuple[AccountConfig, ...] = ()

    @field_validator("accounts")
    @classmethod
    def _names_and_channels_are_distinct(
        cls, v: tuple[AccountConfig, ...]
    ) -> tuple[AccountConfig, ...]:
        names = [a.name for a in v]
        if len(set(names)) != len(names):
            raise ValueError(f"accounts have duplicate names: {sorted(names)}")

        # Two accounts on one channel would double-post that channel — the
        # same guarantee the acceptance tests hold campaigns to today.
        seen: dict[str, str] = {}
        for account in v:
            if account.identity in seen:
                raise ValueError(
                    f"accounts {seen[account.identity]!r} and {account.name!r} "
                    f"both target channel {account.identity} — that channel "
                    f"would get every post twice"
                )
            seen[account.identity] = account.name
        return v

    @property
    def live(self) -> tuple[AccountConfig, ...]:
        """The connected accounts, skipping any switched off."""
        return tuple(a for a in self.accounts if a.enabled)

    def by_name(self, name: str) -> AccountConfig | None:
        return next((a for a in self.accounts if a.name == name), None)

    def key_slots(self) -> tuple[str, ...]:
        """Every distinct key slot in use, in first-seen order.

        One ``BufferPublisher`` is built per slot rather than per account:
        accounts under one Buffer login share a key, and they must also share
        the request tally that ``_report_quota`` sums against the
        3,000/30-day allowance.
        """
        slots: list[str] = []
        for account in self.live:
            if account.api_key_secret not in slots:
                slots.append(account.api_key_secret)
        return tuple(slots)


def load_accounts(path: Path) -> AccountsConfig:
    """Load and validate ``accounts.yaml``, or raise ``ConfigError``.

    A missing file is not an error: a repo that has not adopted fan-out yet
    has no accounts registry, and every campaign keeps posting through its own
    ``buffer:`` block exactly as before.
    """
    if not path.is_file():
        return AccountsConfig()

    try:
        raw: Any = yaml.load(path.read_text(encoding="utf-8"), Loader=Yaml12Loader)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if raw is None:
        return AccountsConfig()
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path} must contain a YAML mapping, got {type(raw).__name__}"
        )

    try:
        return AccountsConfig.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"{path} failed validation:\n{exc}") from exc


def accounts_for(
    registry: AccountsConfig, allowed: Any
) -> tuple[AccountConfig, ...]:
    """The live accounts one campaign reaches, honouring its filter.

    ``allowed`` is a ``config.AccountFilter``; taken loosely typed to keep
    this module from importing a campaign concept it otherwise has no use for.
    """
    return tuple(a for a in registry.live if allowed.allows(a.name))
