"""A result that has already happened must reach the branch.

On 2026-11-24 a publishing run sent two posts, could not push the file that
said so (another job had changed one of them first), and exited. The next run
read both as unsent and sent them again.
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from src.logging import StructuredLogger
from src.vcs import GitVcs, VcsError


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout


def repos(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    clones = []
    for name in ("a", "b"):
        clone = tmp_path / name
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
        clones.append(clone)
    a, b = clones
    (a / "outbox").mkdir()
    (a / "outbox" / "one.json").write_text(json.dumps({"id": "one", "status": "queued"}, indent=2) + "\n")
    (a / "outbox" / "two.json").write_text(json.dumps({"id": "two", "status": "queued"}, indent=2) + "\n")
    git(a, "checkout", "-q", "-B", "main")
    git(a, "add", "."); git(a, "commit", "-q", "-m", "held"); git(a, "push", "-q", "-u", "origin", "main")
    git(b, "pull", "-q", "origin", "main")
    return a, b


def vcs(root: Path) -> GitVcs:
    return GitVcs(root, StructuredLogger({}, io.StringIO()), sleep=lambda _s: None)


def write(root: Path, name: str, **fields) -> Path:
    path = root / "outbox" / f"{name}.json"
    path.write_text(json.dumps({"id": name, **fields}, indent=2) + "\n")
    return path


def test_sync_reads_what_the_run_before_left(tmp_path):
    a, b = repos(tmp_path)
    vcs(a).commit([write(a, "one", status="published", media_id="m1")], "publish one")
    assert json.loads((b / "outbox" / "one.json").read_text())["status"] == "queued"
    vcs(b).sync()
    assert json.loads((b / "outbox" / "one.json").read_text())["status"] == "published"


def test_a_claim_is_refused_when_someone_else_changed_the_post(tmp_path):
    a, b = repos(tmp_path)
    vcs(a).commit([write(a, "one", status="published", media_id="m1")], "publish one")
    with pytest.raises(VcsError):
        vcs(b).commit([write(b, "one", status="publishing", container_id="c2")], "publishing one")


def test_a_result_lands_even_when_the_same_file_changed_first(tmp_path):
    a, b = repos(tmp_path)
    vcs(a).commit([write(a, "one", status="published", media_id="m1")], "publish one")
    # b was checked out before that, sent both posts, and now has to say so.
    one = write(b, "one", status="published", media_id="m2")
    two = write(b, "two", status="published", media_id="m3")
    assert vcs(b).record([one, two], "publish 2") is True

    git(a, "pull", "-q", "--rebase")
    assert json.loads((a / "outbox" / "two.json").read_text()) == {"id": "two", "status": "published", "media_id": "m3"}
    assert json.loads((a / "outbox" / "one.json").read_text())["status"] == "published"
    assert git(b, "status", "--porcelain").strip() == ""
