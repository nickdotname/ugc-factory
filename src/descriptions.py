"""The description bank: the text a video is posted with (SPEC §9).

Responsibility: parse ``captions.txt`` into validated post descriptions, each
with an optional title, and reject anything a target platform would refuse.

Terminology, because the word "caption" is overloaded and the file name is
historical: a **description** here is the text posted *alongside* the video —
Instagram's caption box, TikTok's caption, YouTube's description. It is never
drawn onto the video. On-screen subtitles are baked into the source clips before
they ever reach this pipeline; the renderer contains no text filters at all.

Format — records separated by a ``---`` line (preferred, because it lets a
caption contain its own blank lines) or by blank lines, with an optional
``title:`` first line for platforms that have a separate title field:

    title: How I built this in five minutes
    The long description body goes here.
    It may span multiple lines.

    A record with no title: line is description-only, which is all Instagram
    and TikTok need.

The title lives in the same file rather than a parallel ``titles.txt`` so a
description and its title cannot drift out of sync or out of order.
"""

from __future__ import annotations

from typing import Sequence

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.errors import ConfigError

if TYPE_CHECKING:
    from src.config import TitleStrategy
from src.platforms import (
    Service,
    advice,
    check_description,
    check_title,
    limits_for,
)

_TITLE_LINE = re.compile(r"^title:\s*(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class Description:
    """One post's text, with the title platforms like YouTube require."""

    body: str
    title: str | None = None

    @property
    def key(self) -> str:
        """Identity for dedupe and history.

        The body alone: two records differing only by title are the same thing
        to a viewer scrolling Instagram, and deduping on the pair would let the
        same description recycle immediately under a new title.
        """
        return self.body


#: An explicit record separator: a line of three or more dashes, alone.
_SEPARATOR = re.compile(r"^-{3,}\s*$", re.MULTILINE)


def split_records(text: str) -> list[str]:
    """Split a bank into raw record blocks.

    Two formats, because real captions need internal blank lines. A caption is
    routinely written as hook / blank / CTA / blank / keyword list, and if blank
    lines separated *records* that one caption would parse as three.

    So: if the file contains any ``---`` line, that is the separator and blank
    lines are ordinary caption content. Otherwise blank lines separate records,
    which keeps simple banks simple.
    """
    if _SEPARATOR.search(text):
        return _SEPARATOR.split(text)
    return text.split("\n\n")


def parse_bank(text: str) -> list[Description]:
    """Parse a description bank. Raises ``ConfigError`` on a malformed record."""
    records: list[Description] = []
    for block in split_records(text):
        stripped = block.strip()
        if not stripped:
            continue
        # A block that is entirely comment lines is a note, not a record.
        lines = [ln for ln in stripped.splitlines() if not ln.lstrip().startswith("#")]
        if not lines:
            continue

        title: str | None = None
        match = _TITLE_LINE.match(lines[0].strip())
        if match:
            title = match.group(1).strip()
            lines = lines[1:]
            if not title:
                raise ConfigError(
                    "a 'title:' line is present but empty; give it text or "
                    "remove the line"
                )

        # "\n".join keeps internal blank lines intact, which is the whole
        # point of the --- separator form.
        body = "\n".join(lines).strip()
        if not body:
            raise ConfigError(
                f"description record has a title ({title!r}) but no body text"
            )
        records.append(Description(body=body, title=title))
    return records


def derive_title(body: str, max_len: int) -> str:
    """Build a title from a description's first line.

    The first line is the right source: a description's opening line is already
    written to be the hook, and anything below it — hashtag blocks, CTAs, link
    text — is exactly what must not end up in a YouTube title.

    Trimmed at a word boundary rather than mid-word, and with no ellipsis: an
    ellipsis spends three of the hundred characters to tell the reader something
    the truncation already shows.
    """
    first_line = ""
    for line in body.splitlines():
        if line.strip():
            first_line = line.strip()
            break
    if not first_line:
        return ""

    if len(first_line) <= max_len:
        return first_line

    window = first_line[:max_len]
    cut = window.rfind(" ")
    # A single word longer than the whole limit has no boundary to cut on, so
    # a hard cut is the only option left.
    return (window[:cut] if cut > 0 else window).rstrip(" ,.;:-—")


def resolve_titles(
    descriptions: list[Description], service: Service, strategy: "TitleStrategy"
) -> list[Description]:
    """Fill in missing titles according to the strategy.

    Returns new records; nothing is mutated. For services with no title field
    this is a no-op, so the same bank can feed an Instagram and a YouTube
    campaign without either knowing about the other.
    """
    from src.config import TitleStrategy

    limits = limits_for(service)
    if not limits.has_title or strategy is TitleStrategy.REQUIRE:
        return list(descriptions)

    assert limits.title_max is not None
    resolved: list[Description] = []
    for description in descriptions:
        if description.title:
            resolved.append(description)
            continue
        resolved.append(
            Description(
                body=description.body,
                title=derive_title(description.body, limits.title_max),
            )
        )
    return resolved


def validate_bank(
    descriptions: list[Description],
    service: Service,
    keywords: Sequence[str] = (),
    front_load_words: int = 4,
) -> tuple[list[str], list[str]]:
    """Check every record against a platform. Returns (errors, advice).

    Errors block; advice does not. Both are returned together so preflight can
    show the whole picture in one pass rather than failing on the first record
    and hiding the other nine problems.
    """
    errors: list[str] = []
    notes: list[str] = []
    for index, description in enumerate(descriptions, 1):
        for problem in check_description(description.body, service):
            errors.append(f"description #{index}: {problem}")
        for problem in check_title(description.title, service):
            errors.append(f"description #{index}: {problem}")
        for note in advice(
            description.body, description.title, service,
            keywords, front_load_words,
        ):
            notes.append(f"description #{index}: {note}")
    return errors, notes


def load_bank(
    path_text: str,
    service: Service,
    *,
    source: str,
    strategy: "TitleStrategy | None" = None,
) -> list[Description]:
    """Parse and hard-validate a bank, or raise ``ConfigError``.

    Called at render time so a bank that would be rejected by the platform can
    never reach the queue — SPEC §2.2's "validate at boundaries, fail loud".
    """
    from src.config import TitleStrategy

    descriptions = parse_bank(path_text)
    if not descriptions:
        raise ConfigError(f"{source} contains no descriptions")

    descriptions = resolve_titles(
        descriptions, service, strategy or TitleStrategy.DERIVE
    )
    errors, _ = validate_bank(descriptions, service)
    if errors:
        raise ConfigError(
            f"{source} has {len(errors)} problem(s) for {service.value}:\n  "
            + "\n  ".join(errors)
        )
    return descriptions
