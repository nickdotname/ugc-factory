"""Editing a campaign's config from the dashboard, without losing the file.

Responsibility: change one setting in ``config.yaml`` and leave everything else
byte-identical.

Why not load-and-dump: a campaign config is roughly a third comments, and they
carry the reasoning — why the cadence is what it is, what ``start == end``
means, why ``dry_run`` was flipped. ``yaml.safe_dump`` discards every one of
them and reorders the keys for good measure. A settings panel that quietly
strips a file's documentation is worse than no settings panel.

So this edits the one line it means to and touches nothing else, then proves
it: the file is re-parsed through the real loader, and if that fails for any
reason the original text goes back. A config the dashboard cannot parse would
stop the nightly render, which is far worse than a setting not sticking.

Only an allowlist of keys is editable. The rest of the schema is either
credentials, or values whose consequences are not obvious enough to hand to a
toggle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from src.errors import ConfigError, ValidationError


@dataclass(frozen=True)
class Setting:
    """One editable knob, and how to render it into YAML."""

    path: str          # dotted, e.g. "variation.enabled"
    kind: str          # bool | int | int_or_null | float | str | str_list | choice
    label: str
    help: str
    #: Extra guard beyond the type, raising ValueError with a usable message.
    #: Keep this field ahead of any new one: three settings pass it
    #: positionally, so inserting before it rebinds them to the wrong field.
    check: Callable[[Any], None] | None = None
    #: The allowed values, for ``kind == "choice"``. Empty otherwise.
    choices: tuple[str, ...] = ()

    @property
    def section(self) -> str:
        return self.path.split(".", 1)[0]

    @property
    def key(self) -> str:
        return self.path.split(".", 1)[1]


def _positive(value: Any) -> None:
    if int(value) < 1:
        raise ValueError("must be at least 1")


#: Everything the dashboard may change. Deliberately short.
EDITABLE: tuple[Setting, ...] = (
    Setting("posting.dry_run", "bool", "Paused",
            "When on, renders still run but nothing is pushed to Buffer."),
    Setting("posting.posts_per_day", "int", "Posts per day",
            "Drives slot spacing and the backlog target.", _positive),
    Setting("posting.slot_offset_min", "int_or_null", "Stagger (minutes)",
            "Shifts this campaign's slots. Campaigns sharing a cadence and "
            "start hour post on the same minute otherwise."),
    Setting("posting.max_backlog_days", "int", "Backlog days",
            "Render tops the queue up to posts per day x this, then stops.",
            _positive),
    Setting("composition.bodies_per_video", "int", "Body clips per video",
            "The floor. Raising it makes every cut longer.", _positive),
    Setting("composition.bodies_per_video_max", "int_or_null",
            "…up to (optional)",
            "Draw a range instead of a fixed count. More shapes and mixed "
            "lengths from the same clips."),
    Setting("selection.performance_weight", "float", "Favour winners (0-1)",
            "Weights selection toward clips that have performed. Costs "
            "variety, so it earns its place where there are many options."),
    Setting("selection.performance_statistic", "choice", "Rank winners by",
            "What 'performed' means. Median is steadier; mean favours clips "
            "that break out, which median hides when every post gets the same "
            "seed audience.",
            choices=("median", "mean")),
    Setting("variation.enabled", "bool", "Creative variation",
            "Per-variant punch-in, grade, grain and pace, seeded on the item "
            "id so a winner is reproducible."),
    Setting("variation.allow_mirror", "bool", "Allow mirroring",
            "Reverses on-screen text and flips a logo. Only for shots with "
            "neither."),
    Setting("buffer.first_comment", "str", "First comment",
            "Posted as the first comment on Instagram — where a link belongs, "
            "since one in the caption is not clickable."),
    Setting("buffer.notify_subscribers", "bool", "Notify subscribers",
            "YouTube only. Pushes each Short to subscribers. Leave off for a "
            "channel posting many times a day."),
    Setting("seo.keywords", "str_list", "Target keywords",
            "Linted against the field each platform searches — the caption on "
            "TikTok, the title on YouTube."),
)

BY_PATH: dict[str, Setting] = {s.path: s for s in EDITABLE}


def coerce(setting: Setting, raw: Any) -> Any:
    """Turn a JSON value from the browser into the typed value, or raise."""
    if setting.kind == "bool":
        if isinstance(raw, bool):
            return raw
        raise ValueError("expected true or false")
    if setting.kind in ("int", "int_or_null"):
        if raw in (None, "") and setting.kind == "int_or_null":
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError("expected a whole number") from None
        if setting.check:
            setting.check(value)
        return value
    if setting.kind == "float":
        try:
            fraction = float(raw)
        except (TypeError, ValueError):
            raise ValueError("expected a number") from None
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("must be between 0 and 1")
        return fraction
    if setting.kind == "str":
        text = "" if raw is None else str(raw).strip()
        if '"' in text or "\n" in text:
            raise ValueError("cannot contain quotes or newlines")
        return text
    if setting.kind == "choice":
        if isinstance(raw, Enum):
            raw = raw.value
        text = "" if raw is None else str(raw).strip()
        if text not in setting.choices:
            raise ValueError(f"expected one of {', '.join(setting.choices)}")
        return text
    if setting.kind == "str_list":
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",")]
        if not isinstance(raw, list):
            raise ValueError("expected a list")
        cleaned = [str(v).strip() for v in raw if str(v).strip()]
        if any('"' in v or "\n" in v for v in cleaned):
            raise ValueError("keywords cannot contain quotes or newlines")
        return cleaned
    raise ValueError(f"unsupported setting kind {setting.kind!r}")


def to_yaml(value: Any) -> str:
    """Render a value as the YAML scalar this file would have used."""
    if value is None:
        return "null"
    if isinstance(value, Enum):
        # Before the str branch, and load-bearing. A ``str``-mixin Enum still
        # formats as "Statistic.MEAN" rather than "mean", so falling through
        # would write a value the loader cannot read back.
        return to_yaml(value.value)
    if isinstance(value, bool):
        # Checked before int: bool is a subclass of int in Python, and `True`
        # would otherwise be written as `1`.
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Trim the trailing zero so 0.5 does not become 0.5000000001 on a
        # round trip through YAML.
        return f"{value:g}"
    if isinstance(value, list):
        # Flow style keeps a list on one line, so the surgical edit stays a
        # single-line replacement rather than a block rewrite.
        return "[" + ", ".join(f'"{v}"' for v in value) + "]"
    return f'"{value}"'


_SECTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$")


def _apply(text: str, setting: Setting, value: Any) -> str:
    """Return ``text`` with one key changed, everything else untouched."""
    rendered = to_yaml(value)
    lines = text.splitlines()

    start = None
    for index, line in enumerate(lines):
        match = _SECTION.match(line)
        if match and match.group(1) == setting.section:
            start = index
            break

    if start is None:
        # A section the file has never carried — every key in it is at its
        # default, so appending the whole section is correct.
        block = ["", f"{setting.section}:", f"  {setting.key}: {rendered}"]
        return "\n".join(lines + block) + "\n"

    # The section runs until the next line at column zero that is not blank or
    # a comment; comments indented inside the section belong to it.
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            end = index
            break

    key_pattern = re.compile(rf"^(\s+){re.escape(setting.key)}:\s*(.*?)\s*$")
    for index in range(start + 1, end):
        match = key_pattern.match(lines[index])
        if not match:
            continue
        indent, rest = match.group(1), match.group(2)
        # Keep any trailing comment: it usually explains the value.
        comment = ""
        if "#" in rest:
            hash_at = rest.index("#")
            comment = "  " + rest[hash_at:]
        lines[index] = f"{indent}{setting.key}: {rendered}{comment}"
        return "\n".join(lines) + "\n"

    # Present section, absent key: insert directly under the header, before any
    # existing keys, where it is easy to spot.
    lines.insert(start + 1, f"  {setting.key}: {rendered}")
    return "\n".join(lines) + "\n"


def write_setting(config_path: Path, path: str, raw: Any) -> Any:
    """Change one setting, or leave the file exactly as it was.

    Returns the typed value that was written. Raises ``ValidationError`` if the
    value is unusable, or ``ConfigError`` if the resulting file will not load —
    in which case the original file has already been restored.
    """
    setting = BY_PATH.get(path)
    if setting is None:
        raise ValidationError(f"{path} is not an editable setting")

    try:
        value = coerce(setting, raw)
    except ValueError as exc:
        raise ValidationError(f"{setting.label}: {exc}") from exc

    original = config_path.read_text(encoding="utf-8")
    updated = _apply(original, setting, value)
    config_path.write_text(updated, encoding="utf-8")

    # Prove it through the real loader rather than trusting the edit. A config
    # the pipeline cannot parse stops the nightly render.
    from src.config import load_config

    try:
        load_config(config_path)
    except Exception as exc:
        config_path.write_text(original, encoding="utf-8")
        raise ConfigError(
            f"{setting.label} was not changed — the edit produced a config "
            f"that will not load: {exc}"
        ) from exc
    return value
