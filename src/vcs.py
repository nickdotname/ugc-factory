"""Version control as an injected boundary.

Responsibility: let the top-up job persist a ``claimed`` state to the repository
*before* it calls the publisher (SPEC §11).

Why this module exists at all: GitHub Actions runners are ephemeral. Writing
``queue.json`` to the runner's disk does not survive the job. If a job wrote
``claimed`` locally, pushed to Buffer, and then died before committing, the next
run would read ``pending`` from git and push the same video a second time. The
commit *is* the durable claim, so it has to happen between the two.

Kept behind an ABC for the same reason as every other boundary (SPEC §2.2): so
tests can assert the ordering of claim-commit-publish without a git repository.
"""

from __future__ import annotations

import random
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Sequence

from src.errors import UgcError
from src.logging import StructuredLogger


class VcsError(UgcError):
    """A git operation failed."""

    retryable = False


class Vcs(ABC):
    """Somewhere durable to record state between steps of a job."""

    @abstractmethod
    def commit(self, paths: Sequence[Path], message: str) -> bool:
        """Stage, commit and publish the given paths.

        Returns False when there was nothing to commit, which is a normal
        outcome and not an error.
        """


class GitVcs(Vcs):
    """The real implementation, shelling out to git."""

    def __init__(
        self,
        repo_root: Path,
        log: StructuredLogger,
        *,
        author_name: str = "ugc-factory",
        author_email: str = "ugc-factory@users.noreply.github.com",
        push: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._root = repo_root
        self._log = log
        self._author_name = author_name
        self._author_email = author_email
        self._push = push
        self._sleep = sleep

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(self._root),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if check and proc.returncode != 0:
            raise VcsError(
                f"git {' '.join(args)} failed (exit {proc.returncode}): "
                f"{(proc.stderr or proc.stdout)[-500:]}"
            )
        return proc

    def commit(self, paths: Sequence[Path], message: str) -> bool:
        if not paths:
            return False
        self._git("add", "--", *[str(p) for p in paths])

        # `diff --cached --quiet` exits 1 when there *are* staged changes, so a
        # non-zero return here is the signal to proceed, not a failure.
        staged = self._git("diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            self._log.debug("vcs_nothing_to_commit", message=message)
            return False

        # SPEC §12: bot commits carry [skip ci] so the nightly queue commit does
        # not retrigger the workflows.
        self._git(
            "-c", f"user.name={self._author_name}",
            "-c", f"user.email={self._author_email}",
            "commit", "-m", f"{message} [skip ci]",
        )
        if self._push:
            self._push_with_rebase(message)
        self._log.info("vcs_committed", message=message, files=len(paths))
        return True

    def _push_with_rebase(self, message: str, attempts: int = 8) -> None:
        """Push, rebasing onto whatever landed first if the push is rejected.

        With one campaign this never mattered. With several running as parallel
        matrix jobs they all commit to the same branch, and every one but the
        winner gets a non-fast-forward rejection. Since each job only ever
        touches files under its own ``campaigns/<slug>/``, a rebase cannot
        conflict — it is purely a serialisation problem.

        Never force-pushes: that would discard another campaign's claim commit,
        which is exactly the record that stops a duplicate post (SPEC §11).
        """
        for attempt in range(1, attempts + 1):
            if self._git("push", check=False).returncode == 0:
                return
            if attempt == attempts:
                raise VcsError(
                    f"push rejected {attempts}x for {message!r}; another job may "
                    f"be stuck holding the branch"
                )
            self._log.warning("vcs_push_rejected", attempt=attempt, message=message)
            # Brief jittered backoff: two jobs retrying in lockstep would keep
            # colliding on the same rebase-then-push cycle indefinitely.
            self._sleep(0.4 * attempt + random.random() * 0.6)
            rebase = self._git("pull", "--rebase", check=False)
            if rebase.returncode != 0:
                # A genuine conflict means two jobs touched one file, which
                # should be impossible given the per-campaign split. Abort the
                # rebase so the working tree is left clean for the next run.
                self._git("rebase", "--abort", check=False)
                raise VcsError(
                    f"rebase conflict while pushing {message!r}: "
                    f"{(rebase.stderr or rebase.stdout)[-300:]}"
                )


class NullVcs(Vcs):
    """Records commits without touching git — for dry runs and tests."""

    def __init__(self, log: StructuredLogger | None = None) -> None:
        self._log = log
        self.commits: list[tuple[tuple[Path, ...], str]] = []

    def commit(self, paths: Sequence[Path], message: str) -> bool:
        self.commits.append((tuple(paths), message))
        if self._log:
            self._log.info("vcs_commit_skipped", message=message)
        return bool(paths)


def detect_repo(repo_root: Path) -> str | None:
    """Read ``owner/name`` from the git remote.

    A local convenience so the web UI works without the operator exporting
    GITHUB_REPOSITORY by hand. Returns None rather than raising — a missing
    remote is a normal state for a fresh clone, not an error.
    """
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_root), capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    if url.endswith(".git"):
        url = url[: -len(".git")]
    for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return None


def detect_token() -> str | None:
    """Borrow the GitHub CLI's token for local runs.

    Only ever used by the local web UI and CLI on a developer machine; CI gets
    GITHUB_TOKEN injected by Actions and never reaches this.
    """
    proc = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def list_secret_names(repo: str) -> list[str] | None:
    """Names of repository secrets already set. Never values.

    ``gh`` cannot read a secret's value back and neither can anything else —
    only the name list is available, which is exactly what a readiness check
    needs. Returns None when gh is unavailable or unauthorised.
    """
    proc = subprocess.run(
        ["gh", "secret", "list", "--repo", repo, "--json", "name"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        return None
    import json

    try:
        return [str(entry["name"]) for entry in json.loads(proc.stdout or "[]")]
    except (ValueError, KeyError, TypeError):
        return None
