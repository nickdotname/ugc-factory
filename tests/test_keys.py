"""Storing pasted credentials.

Two properties matter more than the plumbing: a value must never come back out
of the API, and the file it lands in must not be readable by other users on the
machine. Everything else here guards the ways a paste goes wrong.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.errors import ValidationError
from src.keys import (
    SecretError,
    check_name,
    clean_value,
    delete_env_value,
    mask,
    read_env,
    set_github_secret,
    write_env_value,
)


class TestValueCleaning:
    def test_surrounding_whitespace_goes(self) -> None:
        assert clean_value("  abc123  \n") == "abc123"

    def test_paired_quotes_go(self) -> None:
        assert clean_value('"abc123"') == "abc123"
        assert clean_value("'abc123'") == "abc123"

    def test_interior_whitespace_is_refused_not_stripped(self) -> None:
        # A value with a space in it is a paste that grabbed two fields.
        # Silently keeping half would authenticate as the wrong account.
        with pytest.raises(ValidationError):
            clean_value("abc 123")

    def test_a_pasted_newline_between_values_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            clean_value("abc\n123")

    def test_empty_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            clean_value("   ")

    def test_absurdly_long_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            clean_value("x" * 9000)


class TestMasking:
    def test_only_the_tail_survives(self) -> None:
        assert mask("supersecretvalue1234") == "…1234"

    def test_a_short_value_shows_nothing(self) -> None:
        # Four of eight characters is a meaningful fraction of the secret.
        assert mask("short") == "…"

    def test_the_mask_never_contains_the_head(self) -> None:
        assert "super" not in mask("supersecretvalue1234")


class TestNames:
    def test_conventional_names_pass(self) -> None:
        assert check_name("BUFFER_API_KEY_3") == "BUFFER_API_KEY_3"

    @pytest.mark.parametrize(
        "bad", ["lower_case", "3LEADING_DIGIT", "HAS-DASH", "HAS SPACE", "", "A" * 200]
    )
    def test_unusable_names_are_refused(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            check_name(bad)


class TestEnvFile:
    def test_writes_and_reads_back(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        write_env_value(env, "BUFFER_API_KEY", "abc123")
        assert read_env(env)["BUFFER_API_KEY"] == "abc123"

    def test_the_file_is_owner_only(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        write_env_value(env, "BUFFER_API_KEY", "abc123")
        mode = stat.S_IMODE(env.stat().st_mode)
        assert mode == 0o600, f"credentials file is {oct(mode)}, not 0600"

    def test_replacing_a_value_leaves_the_others_alone(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        write_env_value(env, "BUFFER_API_KEY", "one")
        write_env_value(env, "DISCORD_WEBHOOK", "hook")
        write_env_value(env, "BUFFER_API_KEY", "two")
        values = read_env(env)
        assert values == {"BUFFER_API_KEY": "two", "DISCORD_WEBHOOK": "hook"}

    def test_replacing_does_not_append_a_duplicate(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        write_env_value(env, "BUFFER_API_KEY", "one")
        write_env_value(env, "BUFFER_API_KEY", "two")
        lines = [l for l in env.read_text().splitlines()
                 if l.startswith("BUFFER_API_KEY")]
        assert lines == ["BUFFER_API_KEY=two"]

    def test_hand_written_comments_survive(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("# my notes\nOTHER=keep\n", encoding="utf-8")
        write_env_value(env, "BUFFER_API_KEY", "abc")
        text = env.read_text()
        assert "# my notes" in text and "OTHER=keep" in text

    def test_forgetting_removes_only_that_name(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        write_env_value(env, "BUFFER_API_KEY", "one")
        write_env_value(env, "DISCORD_WEBHOOK", "hook")
        assert delete_env_value(env, "BUFFER_API_KEY") is True
        assert read_env(env) == {"DISCORD_WEBHOOK": "hook"}

    def test_forgetting_something_absent_is_not_an_error(self, tmp_path: Path) -> None:
        assert delete_env_value(tmp_path / ".env", "BUFFER_API_KEY") is False

    def test_no_readable_temp_file_is_left_behind(self, tmp_path: Path) -> None:
        write_env_value(tmp_path / ".env", "BUFFER_API_KEY", "abc")
        assert [p.name for p in tmp_path.iterdir()] == [".env"]

    def test_a_missing_file_reads_as_empty(self, tmp_path: Path) -> None:
        assert read_env(tmp_path / "nope") == {}


class TestGithubSecret:
    def test_the_value_never_appears_in_the_command_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Arguments are visible to every process on the machine; stdin is not."""
        seen: dict[str, object] = {}

        class Done:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            seen["cmd"] = cmd
            seen["input"] = kwargs.get("input")
            return Done()

        monkeypatch.setattr("src.keys.shutil.which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr("src.keys.subprocess.run", fake_run)
        set_github_secret(tmp_path, "BUFFER_API_KEY", "s3cr3t-value")

        assert "s3cr3t-value" not in " ".join(seen["cmd"])  # type: ignore[arg-type]
        assert seen["input"] == "s3cr3t-value"

    def test_a_gh_failure_is_reported_without_echoing_the_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Failed:
            returncode = 1
            stdout = ""
            stderr = "HTTP 403: Resource not accessible"

        monkeypatch.setattr("src.keys.shutil.which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr("src.keys.subprocess.run", lambda *a, **k: Failed())
        with pytest.raises(SecretError) as exc:
            set_github_secret(tmp_path, "BUFFER_API_KEY", "s3cr3t-value")
        assert "s3cr3t-value" not in str(exc.value)
        assert "403" in str(exc.value)

    def test_a_missing_gh_says_where_to_do_it_by_hand(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.keys.shutil.which", lambda _: None)
        with pytest.raises(SecretError) as exc:
            set_github_secret(tmp_path, "BUFFER_API_KEY", "x")
        assert "Settings" in str(exc.value)
