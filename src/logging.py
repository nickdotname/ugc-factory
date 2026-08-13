"""Structured JSON logging with a correlation ID per queue item.

Responsibility: emit one JSON object per line to stdout, carrying enough context
that a failure six weeks from now can be diagnosed without reproducing it.

SPEC §2.2: the log must answer *which item, which stage, which inputs, what came
back*. That is why ``bind()`` exists — a logger bound to an item id carries that
id through render and publish without every call site restating it.

GitHub Actions captures stdout verbatim, so plain ``print`` of a JSON line is
both the simplest and the most robust sink; no handler configuration to drift.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Mapping, TextIO


class StructuredLogger:
    """A logger that emits JSON lines and carries bound context.

    Not a wrapper over ``logging``: the stdlib module's global configuration is
    exactly the kind of action-at-a-distance that makes CI logs unreliable.
    """

    def __init__(
        self,
        context: Mapping[str, Any] | None = None,
        stream: TextIO | None = None,
    ) -> None:
        self._context: dict[str, Any] = dict(context or {})
        # Resolved lazily at write time so tests can swap sys.stdout.
        self._stream = stream

    def bind(self, **fields: Any) -> "StructuredLogger":
        """Return a new logger carrying additional context fields.

        Returns a copy rather than mutating, so a logger bound to one queue item
        cannot leak that item's id into a sibling's log lines.
        """
        merged = {**self._context, **fields}
        return StructuredLogger(merged, self._stream)

    def _emit(self, level: str, event: str, fields: Mapping[str, Any]) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": level,
            "event": event,
            **self._context,
            **fields,
        }
        # The event name is what every log query filters on, so it must not be
        # clobberable by a field that happens to be called "event" — a caller
        # logging event=<something> would otherwise silently erase the line's
        # identity and make the failure unsearchable. Reassert it last; a
        # colliding field is surfaced under a suffixed key rather than dropped.
        if "event" in fields and fields["event"] != event:
            record["event_field"] = fields["event"]
        record["event"] = event
        stream = self._stream if self._stream is not None else sys.stdout
        # default=str so a stray Path/datetime/enum never turns a log call into
        # a crash — losing type fidelity in a log beats losing the log.
        stream.write(json.dumps(record, default=str, sort_keys=False) + "\n")
        stream.flush()

    # `event` is positional-only so a caller may log a *field* named "event"
    # (notify.py does) without colliding with the parameter name.
    def debug(self, event: str, /, **fields: Any) -> None:
        self._emit("debug", event, fields)

    def info(self, event: str, /, **fields: Any) -> None:
        self._emit("info", event, fields)

    def warning(self, event: str, /, **fields: Any) -> None:
        self._emit("warning", event, fields)

    def error(self, event: str, /, **fields: Any) -> None:
        self._emit("error", event, fields)

    def exception(
        self, event: str, exc: BaseException, /, **fields: Any
    ) -> None:
        """Log an exception with its type, message, retryability and traceback.

        ``error_type`` is the class name specifically so that log queries filter
        on the type rather than on message text (SPEC §2.2).
        """
        self._emit(
            "error",
            event,
            {
                **fields,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "retryable": getattr(exc, "retryable", None),
                "traceback": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
            },
        )


def get_logger(**context: Any) -> StructuredLogger:
    """Create a root logger with the given permanent context."""
    return StructuredLogger(context)
