"""Alerting and the weekly digest (SPEC §12).

Responsibility: get a human's attention when the pipeline needs it, and prove
weekly that it is alive when it does not.

SPEC §12: "Silence must never be ambiguous between 'healthy' and 'dead'." That
is the whole reason the digest exists even on a fully successful week.

A notification failure must never mask the error it was reporting, so
``notify()`` returns a bool rather than raising.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import requests

from src.config import CampaignConfig, NotifyEvent
from src.logging import StructuredLogger

REQUEST_TIMEOUT_SEC = 20

#: Any https URL inside a larger blob of text.
_URL_IN_TEXT = re.compile(r"https://\S+")


def extract_webhook_url(raw: str) -> str | None:
    """Pull a usable webhook URL out of whatever was pasted.

    Discord's API hands back a JSON object with the URL as one field, and its
    UI offers a "Copy Webhook URL" button — so the value that lands in a secret
    is reliably one of: the bare URL, that whole JSON object, or a fragment
    with stray whitespace or quotes. Accepting all three costs a few lines and
    removes an entire class of "alerting was silently off" incident.

    Returns None when nothing URL-shaped is present, so the caller can still
    say so plainly rather than posting into the void.
    """
    text = (raw or "").strip().strip("'\"")
    if not text:
        return None
    if text.startswith("https://"):
        return text.split()[0]

    # A pasted API response: {"id": ..., "url": "https://discord.com/..."}
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            candidate = parsed.get("url")
            if isinstance(candidate, str) and candidate.startswith("https://"):
                return candidate

    # Last resort: anything URL-shaped anywhere in the text.
    found = _URL_IN_TEXT.search(text)
    return found.group(0).rstrip('",') if found else None

#: Discord truncates at 2000 characters; anything longer is rejected outright.
MAX_MESSAGE_CHARS = 1900


@dataclass
class Digest:
    """The weekly health summary (SPEC §12)."""

    campaign: str
    posted: int = 0
    failed: int = 0
    queue_depth: int = 0
    queue_runway_hours: float = 0.0
    buffer_requests_30d: int = 0
    days_until_first_repeat: float = 0.0
    dedupe_relaxations: int = 0
    missing_licenses: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"**ugc-factory weekly digest — {self.campaign}**",
            f"posted: {self.posted}   failed: {self.failed}",
            f"queue depth: {self.queue_depth}   runway: {self.queue_runway_hours:.0f}h",
            f"buffer requests (30d): {self.buffer_requests_30d} / 3000",
            f"days until first repeat: {self.days_until_first_repeat:.0f}",
        ]
        if self.dedupe_relaxations:
            lines.append(
                f"⚠️ dedupe relaxed {self.dedupe_relaxations}× — library is too "
                f"small for the cadence"
            )
        if self.missing_licenses:
            shown = ", ".join(self.missing_licenses[:10])
            lines.append(f"⚠️ music missing LICENSES.md entries: {shown}")
        return "\n".join(lines)


class Notifier:
    """Posts messages to a campaign's webhook."""

    def __init__(
        self,
        webhook_url: str | None,
        enabled_events: tuple[NotifyEvent, ...],
        log: StructuredLogger,
        *,
        session: requests.Session | None = None,
    ) -> None:
        # Normalised once, here, so every caller benefits and the raw value is
        # never used by accident.
        self._url = extract_webhook_url(webhook_url or "")
        self._enabled = set(enabled_events)
        self._log = log
        self._session = session or requests.Session()

    def notify(self, event: NotifyEvent, message: str) -> bool:
        """Send a message if this event is enabled. Never raises.

        Returns whether it was delivered, so a caller can log the miss — but a
        failed alert must not become a second failure that hides the first.
        """
        if event not in self._enabled:
            self._log.debug("notify_skipped_disabled", for_event=event.value)
            return False
        if not self._url:
            # Not an error: a campaign may legitimately run without alerting,
            # and crashing the render over a missing webhook would be worse
            # than the missing alert.
            self._log.warning("notify_no_webhook", for_event=event.value)
            return False

        body = message if len(message) <= MAX_MESSAGE_CHARS else (
            message[: MAX_MESSAGE_CHARS - 3] + "..."
        )
        try:
            response = self._session.post(
                self._url,
                json={"content": body},
                timeout=REQUEST_TIMEOUT_SEC,
            )
        except requests.RequestException as exc:
            self._log.warning("notify_failed", for_event=event.value, error=str(exc))
            return False

        if not (200 <= response.status_code < 300):
            self._log.warning(
                "notify_rejected", for_event=event.value,
                status=response.status_code
            )
            return False
        self._log.info("notify_sent", for_event=event.value)
        return True

    def failure(self, stage: str, error: BaseException, **context: Any) -> bool:
        detail = json.dumps(context, default=str) if context else ""
        return self.notify(
            NotifyEvent.FAILURE,
            f"🔴 **ugc-factory failure** in `{stage}`\n"
            f"`{type(error).__name__}`: {str(error)[:800]}"
            + (f"\n```{detail[:500]}```" if detail else ""),
        )

    def digest(self, digest: Digest) -> bool:
        return self.notify(NotifyEvent.DIGEST, digest.render())


def notifier_for(
    config: CampaignConfig,
    log: StructuredLogger,
    env: dict[str, str] | None = None,
    *,
    session: requests.Session | None = None,
) -> Notifier:
    """Build a campaign's notifier by resolving its webhook secret name."""
    source = env if env is not None else dict(os.environ)
    return Notifier(
        source.get(config.notify.webhook_secret),
        config.notify.on,
        log,
        session=session,
    )
