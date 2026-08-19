"""Readiness check: what is wired up, what is missing, what to do next.

Responsibility: answer "is this thing ready to run, and if not, exactly what do
I type" in one command.

Standing up this pipeline touches four separate systems — a git repo, GitHub
Secrets, a Buffer channel, and an assets Release — and a gap in any one of them
surfaces as a different confusing failure at 05:00. This module checks all four
up front and prints the specific command that fixes each gap.

It never handles secret *values*: it reports which secret names exist (all
GitHub will disclose) and prints the command for the operator to set the rest
themselves.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from src.config import CampaignConfig
from src.descriptions import parse_bank, validate_bank
from src.errors import UgcError
from src.ingest import combinations, library_health
from src.platforms import Service


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    MISSING = "missing"


@dataclass
class Check:
    """One readiness item and, when it fails, how to fix it."""

    name: str
    status: Status
    detail: str = ""
    fix: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: Status, detail: str = "", fix: str = "") -> None:
        self.checks.append(Check(name, status, detail, fix))

    @property
    def blocking(self) -> list[Check]:
        return [c for c in self.checks if c.status is Status.MISSING]

    @property
    def ready(self) -> bool:
        return not self.blocking

    def render(self) -> str:
        mark = {Status.OK: "OK  ", Status.WARN: " !  ", Status.MISSING: " x  "}
        width = max(len(c.name) for c in self.checks) if self.checks else 0
        lines = []
        for check in self.checks:
            lines.append(f"  {mark[check.status]}{check.name:<{width}}  {check.detail}")
        return "\n".join(lines)

    def next_steps(self) -> str:
        steps = [c for c in self.checks if c.fix and c.status is not Status.OK]
        if not steps:
            return ""
        out = ["", "Next:"]
        for index, check in enumerate(steps, 1):
            out.append(f"  {index}. {check.name} — {check.fix}")
        return "\n".join(out)


def check_repo(repo: str | None) -> Check:
    if repo:
        return Check("github repo", Status.OK, repo)
    return Check(
        "github repo", Status.MISSING, "no origin remote",
        "gh repo create ugc-factory --public --source=. --remote=origin --push",
    )


def check_secrets(
    config: CampaignConfig, repo: str | None, names: list[str] | None
) -> list[Check]:
    """Verify the three secrets a campaign needs are present by name."""
    # A channel id kept in config is not a secret and has nothing to check.
    required = [
        pair for pair in (
            (config.buffer.api_key_secret, "Buffer personal API key"),
            (config.buffer.channel_id_secret, "Buffer channel id"),
            (config.notify.webhook_secret, "Discord webhook for alerts"),
        )
        if pair[0]
    ]
    if names is None:
        return [
            Check(
                "github secrets", Status.MISSING,
                "could not read (gh not authenticated?)",
                "gh auth login",
            )
        ]

    checks: list[Check] = []
    present = set(names)
    for secret, what in required:
        if secret in present:
            checks.append(Check(f"secret {secret}", Status.OK, "set"))
        else:
            # `gh secret set` prompts for the value, so the operator types it
            # and it never passes through this process.
            checks.append(
                Check(
                    f"secret {secret}", Status.MISSING, f"not set — {what}",
                    f"gh secret set {secret}"
                    + (f" --repo {repo}" if repo else ""),
                )
            )
    return checks


def check_buffer_channel(
    config: CampaignConfig, channels: list[dict[str, object]] | None
) -> Check:
    """Confirm a channel of the right service exists and publishes automatically.

    ``defaultToReminders`` is the whole ballgame (SPEC §0): a channel in reminder
    mode sends a push notification for a human to tap, which is not automation.
    """
    if channels is None:
        return Check(
            "buffer channel", Status.WARN,
            "not checked (set BUFFER_API_KEY locally to verify)",
            "export BUFFER_API_KEY=... && ./ugc setup "
            f"--campaign {config.slug}",
        )

    want = config.buffer.service.value
    matching = [c for c in channels if c.get("service") == want]
    if not matching:
        found = ", ".join(sorted({str(c.get("service")) for c in channels})) or "none"
        return Check(
            "buffer channel", Status.MISSING,
            f"no {want} channel connected (found: {found})",
            f"connect a {want} channel in Buffer, then re-run",
        )

    channel = matching[0]
    metadata = channel.get("metadata") or {}
    reminders = (
        metadata.get("defaultToReminders") if isinstance(metadata, dict) else None
    )
    channel_id = str(channel.get("id", ""))

    if reminders is True:
        return Check(
            "buffer channel", Status.MISSING,
            f"{want} channel defaults to REMINDERS — nothing will publish "
            f"unattended",
            "turn reminders off in Buffer, or confirm the account is "
            "Business/Creator",
        )
    return Check(
        "buffer channel", Status.OK,
        f"{want} · {channel.get('name')} · automatic · id {channel_id}",
    )


def check_assets(counts: dict[str, int] | None, config: CampaignConfig) -> list[Check]:
    if counts is None:
        return [Check("assets release", Status.WARN, "not checked")]
    total = sum(counts.values())
    if total == 0:
        return [
            Check(
                "assets release", Status.MISSING, "empty",
                f"./ugc web --campaign {config.slug}  (drop clips in, hit Upload)",
            )
        ]
    detail = (
        f"{counts.get('hook', 0)} hooks · {counts.get('body', 0)} bodies · "
        f"{counts.get('music', 0)} music"
    )
    missing = [k for k in ("hook", "body") if counts.get(k, 0) == 0]
    if missing:
        return [
            Check(
                "assets release", Status.MISSING, f"{detail} — no {', '.join(missing)}",
                f"./ugc web --campaign {config.slug}",
            )
        ]
    return [Check("assets release", Status.OK, detail)]


def check_descriptions(bank_path: Path, config: CampaignConfig) -> list[Check]:
    if not bank_path.is_file():
        return [
            Check("descriptions", Status.MISSING, "no bank file",
                  f"./ugc web --campaign {config.slug}")
        ]
    text = bank_path.read_text(encoding="utf-8")
    try:
        records = parse_bank(text)
    except UgcError as exc:
        return [Check("descriptions", Status.MISSING, str(exc)[:80],
                      "fix the bank file")]

    if not records:
        return [
            Check("descriptions", Status.MISSING, "bank is empty",
                  f"./ugc web --campaign {config.slug}")
        ]

    errors, _ = validate_bank(records, config.buffer.service)
    # Template text shipping to a real account is the failure this catches, and
    # it is reported as part of the one descriptions check rather than as a
    # second contradictory line.
    template = any("description goes here" in r.body for r in records)

    if errors:
        return [Check("descriptions", Status.MISSING,
                      f"{len(records)} records · {len(errors)} invalid",
                      "fix the reported records")]
    if template:
        return [Check("descriptions", Status.MISSING,
                      f"{len(records)} records · still template text",
                      f"./ugc web --campaign {config.slug}")]
    return [Check("descriptions", Status.OK, f"{len(records)} records")]


def check_library(
    counts: dict[str, int] | None, descriptions: int, config: CampaignConfig
) -> list[Check]:
    if counts is None:
        return []
    hooks, bodies, music = (
        counts.get("hook", 0), counts.get("body", 0), counts.get("music", 0)
    )
    per_video = config.composition.bodies_per_video
    ppd = config.posting.posts_per_day
    total = combinations(hooks, bodies, music, descriptions, per_video)
    runway = total / max(1, ppd)

    checks = []
    status = Status.OK if runway >= config.selection.min_runway_days else Status.WARN
    checks.append(
        Check("library runway", status,
              f"{total} combinations = {runway:.0f} days at {ppd}/day "
              f"(target {config.selection.min_runway_days})",
              "add hooks, bodies or descriptions" if status is Status.WARN else "")
    )
    for warning in library_health(
        hooks, bodies, music, descriptions, per_video, ppd,
        config.selection.hook_cooldown_days, config.selection.caption_cooldown_days,
    ):
        checks.append(Check("cooldown headroom", Status.WARN, warning[:110]))
    return checks


def check_mode(config: CampaignConfig) -> Check:
    if config.posting.dry_run:
        return Check(
            "posting mode", Status.WARN, "dry run — nothing will reach Buffer",
            f"set posting.dry_run: false in campaigns/{config.slug}/config.yaml "
            f"once a dry run looks right",
        )
    return Check("posting mode", Status.OK, "LIVE — posts will publish")


def check_local_buffer_key(config: CampaignConfig) -> Check | None:
    """Whether a key is available locally, only to explain a skipped check."""
    if os.environ.get(config.buffer.api_key_secret) or os.environ.get("BUFFER_API_KEY"):
        return None
    return Check(
        "local buffer key", Status.WARN,
        "not in this shell — channel check skipped",
        f"export {config.buffer.api_key_secret}=... to verify the channel here",
    )
