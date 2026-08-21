"""Properties of the source itself that fail silently until they fail loudly.

Both of these have bitten this project already, and neither shows up in normal
use — which is exactly why they are tests rather than habits.
"""

from __future__ import annotations

import py_compile
import warnings
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
MODULES = sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_no_invalid_escape_sequences(module: Path, tmp_path: Path) -> None:
    r"""An invalid escape like ``\.`` is a SyntaxWarning, not an error.

    ``web.py`` embeds a whole JavaScript program in a plain triple-quoted
    string, and JS regexes are full of ``\.``, ``\s`` and ``\d``. Python reads
    those as escape sequences it does not recognise.

    What makes it dangerous is bytecode caching: the warning fires at compile
    time, so an already-cached module stays silent and only a fresh checkout —
    CI — trips over it. It has reached main twice, both times found by pytest's
    filterwarnings=error rather than by anything anyone did deliberately.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        try:
            py_compile.compile(
                str(module),
                cfile=str(tmp_path / f"{module.stem}.pyc"),
                doraise=True,
            )
        except (py_compile.PyCompileError, SyntaxWarning) as exc:
            pytest.fail(
                f"{module.relative_to(SRC.parent)} does not compile cleanly: "
                f"{exc}\n\nIf this is a JavaScript regex inside PAGE, double "
                f"the backslash: /\\\\./ in the Python source becomes /\\./ in "
                f"the served page."
            )


def test_the_dashboard_javascript_parses() -> None:
    """A duplicate ``const`` kills the entire <script> with no console output.

    The page then renders as an empty shell and every panel silently vanishes.
    This has happened once here and cost a debugging cycle; node is not always
    available, so the check skips rather than failing when it is missing.
    """
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    from src.web import PAGE

    match = re.search(r"<script>(.*?)</script>", PAGE, re.S)
    assert match, "no inline script found in PAGE"

    proc = subprocess.run(
        [node, "--input-type=module", "--check"],
        input=match.group(1), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        # --check on stdin needs a module context; fall back to a temp file so
        # the failure message is about the JS rather than about how it was fed in.
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(match.group(1))
            path = fh.name
        proc = subprocess.run(
            [node, "--check", path], capture_output=True, text=True, timeout=60
        )
        Path(path).unlink(missing_ok=True)
    assert proc.returncode == 0, f"dashboard JS does not parse:\n{proc.stderr[:800]}"
