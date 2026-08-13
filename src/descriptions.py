"""The description bank: the text a video is posted with (SPEC §9).

Responsibility: parse ``captions.txt`` into validated post descriptions, each
with an optional title, and reject anything a target platform would refuse.

Terminology, because the word "caption" is overloaded and the file name is
historical: a **description** here is the text posted *alongside* the video —
Instagram's caption box, TikTok's caption, YouTube's description. It is never
drawn onto the video. On-screen subtitles are baked into the source clips before
they ever reach this pipeline; the renderer contains no text filters at all.

Format — records separated by blank lines, with an optional ``title:`` first
line for platforms that have a separate title field:

    title: How I built this in five minutes
    The long description body goes here.
    It may span multiple lines.

    A record with no title: line is description-only, which is all Instagram
    and TikTok need.

The title lives in the same file rather than a parallel ``titles.txt`` so a
description and its title cannot drift out of sync or out of order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.errors import ConfigError
from src.platforms import Service, advice, check_description, check_title

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


def parse_bank(text: str) -> list[Description]:
    """Parse a description bank. Raises ``ConfigError`` on a malformed record."""
    records: list[Description] = []
    for block in text.split("\n\n"):
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

        body = "\n".join(lines).strip()
        if not body:
            raise ConfigError(
                f"description record has a title ({title!r}) but no body text"
            )
        records.append(Description(body=body, title=title))
    return records


def validate_bank(
    descriptions: list[Description], service: Service
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
        for note in advice(description.body, description.title, service):
            notes.append(f"description #{index}: {note}")
    return errors, notes


def load_bank(path_text: str, service: Service, *, source: str) -> list[Description]:
    """Parse and hard-validate a bank, or raise ``ConfigError``.

    Called at render time so a bank that would be rejected by the platform can
    never reach the queue — SPEC §2.2's "validate at boundaries, fail loud".
    """
    descriptions = parse_bank(path_text)
    if not descriptions:
        raise ConfigError(f"{source} contains no descriptions")

    errors, _ = validate_bank(descriptions, service)
    if errors:
        raise ConfigError(
            f"{source} has {len(errors)} problem(s) for {service.value}:\n  "
            + "\n  ".join(errors)
        )
    return descriptions
