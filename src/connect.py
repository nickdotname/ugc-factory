"""Connecting a Buffer login: from an API key to entries in ``accounts.yaml``.

Responsibility: turn "here is the key for another Buffer login" into ready
account entries, without anyone copying channel ids out of a browser. Given
the channels a key can see, this decides what each account is called, what a
post is called on its network, and when it publishes relative to the others —
and writes the result as YAML appended to the registry, leaving every existing
line and comment alone.

Pure: it is handed the channel list rather than fetching it, so the naming
and staggering rules are testable without a network (SPEC §2.2). ``cli`` does
the fetching and the key storage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.accounts import AccountsConfig
from src.platforms import Service

#: What a post is called on each network, and the short tag an account name
#: ends in. One place, so the names this writes match the ones already there.
_NETWORK: dict[Service, tuple[str, str]] = {
    Service.INSTAGRAM: ("ig", "reel"),
    Service.TIKTOK: ("tt", "post"),
    Service.YOUTUBE: ("yt", "short"),
}

#: Minutes between two accounts publishing the same video.
STAGGER_MIN = 20


def slot_name(slot: int) -> str:
    """The secret name for a numbered Buffer login (1 is the unnumbered one)."""
    return "BUFFER_API_KEY" if slot == 1 else f"BUFFER_API_KEY_{slot}"


def safe_prefix(raw: str) -> str:
    """A login's name as a lowercase identifier: ``knick.creates`` -> ``knick_creates``."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    return cleaned or "account"


@dataclass(frozen=True)
class NewAccount:
    name: str
    network: Service
    channel_id: str
    channel_name: str
    slot_offset_min: int
    #: Buffer has this channel set to reminder-based publishing, so nothing
    #: would post unattended until that is switched off in Buffer.
    reminders: bool


@dataclass(frozen=True)
class ConnectPlan:
    new: tuple[NewAccount, ...]
    #: Channels already in the registry: (channel name, existing account name).
    already: tuple[tuple[str, str], ...]
    #: Channels on a network this pipeline does not post to.
    unsupported: tuple[tuple[str, str], ...]
    yaml: str


def plan_accounts(
    channels: Sequence[Mapping[str, Any]],
    organization_id: str,
    api_key_secret: str,
    prefix: str,
    existing: AccountsConfig,
) -> ConnectPlan:
    """Decide which accounts a login adds, and render them as YAML to append."""
    by_channel = {a.channel_id: a.name for a in existing.accounts if a.channel_id}
    names = {a.name for a in existing.accounts}
    used_offsets = {a.slot_offset_min for a in existing.accounts}

    new: list[NewAccount] = []
    already: list[tuple[str, str]] = []
    unsupported: list[tuple[str, str]] = []

    for channel in channels:
        channel_id = str(channel.get("id") or "")
        channel_name = str(channel.get("name") or "")
        try:
            network = Service(str(channel.get("service") or ""))
        except ValueError:
            unsupported.append((channel_name, str(channel.get("service") or "?")))
            continue
        if network not in _NETWORK:
            unsupported.append((channel_name, network.value))
            continue
        if channel_id in by_channel:
            already.append((channel_name, by_channel[channel_id]))
            continue

        tag = _NETWORK[network][0]
        name = f"{prefix}_{tag}"
        suffix = 2
        while name in names:
            name = f"{prefix}_{tag}{suffix}"
            suffix += 1
        names.add(name)

        # The first free stagger: fan-out sends one video to every account,
        # and two accounts publishing it on the same minute is a visible
        # double to anyone following both.
        offset = 0
        while offset in used_offsets and offset < 1439 - STAGGER_MIN:
            offset += STAGGER_MIN
        used_offsets.add(offset)

        metadata = channel.get("metadata") or {}
        new.append(
            NewAccount(
                name=name, network=network, channel_id=channel_id,
                channel_name=channel_name, slot_offset_min=offset,
                reminders=bool(metadata.get("defaultToReminders")),
            )
        )

    lines: list[str] = []
    if new:
        lines += ["", f"  # ── {prefix} ── {api_key_secret}"]
    for account in new:
        post_type = _NETWORK[account.network][1]
        lines += [
            f"  - name: {account.name}",
            f"    network: {account.network.value}",
            f"    api_key_secret: {api_key_secret}",
            f"    organization_id: {organization_id}",
            f"    channel_id: {account.channel_id}",
            f"    post_type: {post_type}",
            # YouTube is the one network with a separate, required title.
            "    title_strategy: "
            + ("require" if account.network is Service.YOUTUBE else "derive"),
        ]
        if account.slot_offset_min:
            lines.append(f"    slot_offset_min: {account.slot_offset_min}")
        lines.append("")

    return ConnectPlan(
        new=tuple(new),
        already=tuple(already),
        unsupported=tuple(unsupported),
        yaml="\n".join(lines),
    )
