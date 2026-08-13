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

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

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
    ) -> None:
        self._root = repo_root
        self._log = log
        self._author_name = author_name
        self._author_email = author_email
        self._push = push

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
            # A rejected push means someone else moved the branch; retrying
            # blindly could clobber it, so surface it rather than force-pushing.
            self._git("push")
        self._log.info("vcs_committed", message=message, files=len(paths))
        return True


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
