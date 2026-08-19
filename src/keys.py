"""Secret values: where they live locally, and how they reach GitHub.

Responsibility: let an operator paste a credential once and have it land in
both places that need it, without either copy leaking somewhere it should not.

There are two independent stores and they are easy to confuse:

* ``.env`` at the repo root — read **only** by the dashboard, so it can list
  Buffer channels and check a key works. Gitignored. Never read by a workflow.
* GitHub Actions secrets — read **only** by the workflows, which are what
  actually post. Nothing local can see their values, only their names.

A key present in one and absent from the other is the normal cause of "the
dashboard cannot see my channels but posting works" and its mirror image, so
this module reports on both and writes to both.

Values never travel back out: ``describe`` returns presence and a masked tail,
never the secret, and nothing here is passed to the logger.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.errors import UgcError, ValidationError

#: Secret names are used as shell-ish env keys and as GitHub secret names,
#: which permit only these characters and may not start with a digit.
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")

#: Refuse a value that cannot be a credential. Whitespace is the tell for a
#: paste that picked up a newline or a surrounding quote from a web page.
MAX_SECRET_BYTES = 8192


class SecretError(UgcError):
    """A secret could not be stored."""

    retryable = False


def check_name(name: str) -> str:
    if not _NAME.match(name):
        raise ValidationError(
            f"{name!r} is not a usable secret name — expected upper-case "
            f"letters, digits and underscores, starting with a letter"
        )
    return name


def clean_value(raw: str) -> str:
    """Normalise a pasted value, or explain why it cannot be one.

    Strips the surrounding whitespace and paired quotes that a copy from a
    dashboard or a shell snippet routinely carries. Interior whitespace is
    refused rather than stripped: that is a paste that grabbed two fields, and
    silently keeping half of it would authenticate as the wrong account.
    """
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    if not value:
        raise ValidationError("value is empty")
    if len(value.encode("utf-8")) > MAX_SECRET_BYTES:
        raise ValidationError("value is implausibly long for a credential")
    if any(ch.isspace() for ch in value):
        raise ValidationError(
            "value contains a space or newline — paste just the key itself, "
            "not the whole line it came from"
        )
    return value


def mask(value: str) -> str:
    """A recognisable stub, never enough to use.

    Four trailing characters is enough for a human to tell two keys apart and
    useless to anyone else; a short value shows nothing at all.
    """
    return "…" + value[-4:] if len(value) > 8 else "…"


# ------------------------------------------------------------------ local .env


def read_env(path: Path) -> dict[str, str]:
    """Parse the local .env, ignoring comments and malformed lines."""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, _, value = line.partition("=")
        out[name.strip()] = value.strip().strip("'\"")
    return out


def write_env_value(path: Path, name: str, value: str) -> None:
    """Upsert one name, leaving every other line — and any comments — alone.

    Rewriting the file wholesale would discard anything else the operator keeps
    in there, which is a rude thing for a settings panel to do.
    """
    check_name(name)
    lines = (
        path.read_text(encoding="utf-8", errors="replace").splitlines()
        if path.is_file() else []
    )
    replacement = f"{name}={value}"
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        if line.partition("=")[0].strip() == name:
            lines[index] = replacement
            break
    else:
        if not lines:
            lines = [
                "# Local credentials for the dashboard only. Gitignored.",
                "# The workflows read their own copies from GitHub Secrets.",
            ]
        lines.append(replacement)
    _write_private(path, "\n".join(lines) + "\n")


def delete_env_value(path: Path, name: str) -> bool:
    """Drop one name from the local file. Returns whether it was there."""
    check_name(name)
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    kept = [
        line for line in lines
        if line.lstrip().startswith("#")
        or "=" not in line
        or line.partition("=")[0].strip() != name
    ]
    if len(kept) == len(lines):
        return False
    _write_private(path, "\n".join(kept) + "\n")
    return True


def _write_private(path: Path, text: str) -> None:
    """Write owner-only, and never leave a readable temp copy behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    # Created 0600 from the outset rather than chmod'ed after: between the two
    # there would be a window where the file is world-readable.
    handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(temp, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


# --------------------------------------------------------------- GitHub secrets


@dataclass(frozen=True)
class GithubSecret:
    name: str
    updated_at: str


def gh_available() -> bool:
    return shutil.which("gh") is not None


def list_github_secrets(repo_root: Path) -> list[GithubSecret]:
    """Names and timestamps of the repo's Actions secrets — never values.

    GitHub does not expose secret values to anyone, including the owner, which
    is why this panel can say a secret *exists* but never whether it is right.
    """
    if not gh_available():
        return []
    proc = subprocess.run(
        ["gh", "secret", "list"],
        cwd=str(repo_root), capture_output=True, text=True, timeout=60, check=False,
    )
    if proc.returncode != 0:
        return []
    out: list[GithubSecret] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip():
            out.append(GithubSecret(parts[0].strip(),
                                    parts[1].strip() if len(parts) > 1 else ""))
    return out


def set_github_secret(repo_root: Path, name: str, value: str) -> None:
    """Store a secret on the repo, encrypting via the gh CLI.

    The value goes in on **stdin**, never as an argument: arguments are visible
    to every other process on the machine through the process list, and a
    credential has no business there. gh also handles the libsodium sealing
    GitHub requires, which is the reason this shells out rather than calling
    the API directly — the alternative is a crypto dependency in a repo that
    keeps its runtime dependencies to three.
    """
    check_name(name)
    if not gh_available():
        raise SecretError(
            "the GitHub CLI (gh) is not installed, so secrets cannot be set "
            "from here — add it in the repository's Settings → Secrets instead"
        )
    proc = subprocess.run(
        ["gh", "secret", "set", name, "--body-file", "-"],
        cwd=str(repo_root), input=value, capture_output=True, text=True,
        timeout=120, check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        # Never echo the command back — its argv is fine, but the operator
        # pasting a value into an error message is how secrets end up in logs.
        raise SecretError(f"gh could not set {name}: {detail[-300:]}")
