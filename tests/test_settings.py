"""Editing config.yaml from the dashboard.

A campaign config is roughly a third comments, and they carry the reasoning
behind the numbers. The whole point of this module is that a settings panel
does not silently strip a file's documentation — so most of these tests are
about what did *not* change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import load_config
from src.errors import ConfigError, ValidationError
from src.settings import BY_PATH, EDITABLE, coerce, to_yaml, write_setting

CONFIG = """slug: demo
timezone: UTC

posting:
  # Why the cadence is what it is. This comment is load-bearing.
  posts_per_day: 6
  start_hour: 9
  end_hour: 21
  max_buffer_queue: 10        # trailing note
  dry_run: true

composition:
  bodies_per_video: 1

buffer:
  api_key_secret: BUFFER_API_KEY
  channel_id: c1
  service: tiktok
  post_type: post

notify:
  webhook_secret: DISCORD_WEBHOOK
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


class TestPreservesTheFile:
    def test_comments_survive_an_edit(self, config_file: Path) -> None:
        write_setting(config_file, "posting.posts_per_day", 12)
        text = config_file.read_text()
        assert "This comment is load-bearing" in text

    def test_a_trailing_comment_survives_its_own_line_changing(
        self, config_file: Path
    ) -> None:
        write_setting(config_file, "posting.max_buffer_queue", 8) \
            if "posting.max_buffer_queue" in BY_PATH else None
        # Not editable, so edit a neighbour and check the comment is intact.
        write_setting(config_file, "posting.posts_per_day", 12)
        assert "# trailing note" in config_file.read_text()

    def test_only_the_target_line_changes(self, config_file: Path) -> None:
        before = CONFIG.splitlines()
        write_setting(config_file, "posting.posts_per_day", 12)
        after = config_file.read_text().splitlines()
        differing = [
            (a, b) for a, b in zip(before, after) if a != b
        ]
        assert len(differing) == 1
        assert "posts_per_day" in differing[0][1]

    def test_unrelated_sections_are_untouched(self, config_file: Path) -> None:
        write_setting(config_file, "variation.enabled", True)
        text = config_file.read_text()
        assert "api_key_secret: BUFFER_API_KEY" in text
        assert "webhook_secret: DISCORD_WEBHOOK" in text


class TestWritingValues:
    def test_an_existing_key_is_replaced(self, config_file: Path) -> None:
        write_setting(config_file, "posting.posts_per_day", 12)
        assert load_config(config_file).posting.posts_per_day == 12

    def test_a_missing_key_is_added_to_its_section(self, config_file: Path) -> None:
        write_setting(config_file, "composition.bodies_per_video_max", 3)
        assert load_config(config_file).composition.bodies_per_video_max == 3

    def test_a_missing_section_is_created(self, config_file: Path) -> None:
        write_setting(config_file, "variation.enabled", True)
        assert load_config(config_file).variation.enabled is True

    def test_booleans_are_written_as_yaml_not_python(
        self, config_file: Path
    ) -> None:
        """`True` would be read back as a string by a stricter loader, and
        `1` by a looser one."""
        write_setting(config_file, "posting.dry_run", False)
        assert "dry_run: false" in config_file.read_text()

    def test_a_bool_is_not_written_as_a_number(self) -> None:
        # bool subclasses int in Python, so order matters in to_yaml.
        assert to_yaml(True) == "true"
        assert to_yaml(1) == "1"

    def test_clearing_an_optional_writes_null(self, config_file: Path) -> None:
        write_setting(config_file, "composition.bodies_per_video_max", 3)
        write_setting(config_file, "composition.bodies_per_video_max", "")
        assert load_config(config_file).composition.bodies_per_video_max is None

    def test_a_keyword_list_round_trips(self, config_file: Path) -> None:
        write_setting(config_file, "seo.keywords", "film students, nyu")
        assert load_config(config_file).seo.keywords == ("film students", "nyu")

    def test_an_empty_keyword_list_is_allowed(self, config_file: Path) -> None:
        write_setting(config_file, "seo.keywords", "")
        assert load_config(config_file).seo.keywords == ()


class TestRefusal:
    def test_a_key_outside_the_allowlist_is_refused(
        self, config_file: Path
    ) -> None:
        before = config_file.read_text()
        with pytest.raises(ValidationError, match="not an editable setting"):
            write_setting(config_file, "buffer.api_key_secret", "SNEAKY")
        assert config_file.read_text() == before

    def test_credentials_are_not_editable(self) -> None:
        paths = {s.path for s in EDITABLE}
        assert not any("secret" in p or "channel_id" in p for p in paths)

    def test_a_value_the_schema_rejects_restores_the_file(
        self, config_file: Path
    ) -> None:
        """The load-bearing safety property: a config the pipeline cannot
        parse would stop the nightly render."""
        before = config_file.read_text()
        with pytest.raises(ConfigError, match="will not load"):
            write_setting(config_file, "posting.posts_per_day", 999)
        assert config_file.read_text() == before

    def test_a_non_numeric_value_is_refused(self, config_file: Path) -> None:
        before = config_file.read_text()
        with pytest.raises(ValidationError, match="whole number"):
            write_setting(config_file, "posting.posts_per_day", "lots")
        assert config_file.read_text() == before

    def test_a_zero_cadence_is_refused(self, config_file: Path) -> None:
        with pytest.raises(ValidationError, match="at least 1"):
            write_setting(config_file, "posting.posts_per_day", 0)

    def test_a_quote_in_a_keyword_is_refused(self, config_file: Path) -> None:
        """It would break out of the flow-style list and corrupt the file."""
        with pytest.raises(ValidationError, match="quotes"):
            write_setting(config_file, "seo.keywords", ['bad " keyword'])

    def test_a_bool_setting_rejects_a_number(self, config_file: Path) -> None:
        with pytest.raises(ValidationError):
            write_setting(config_file, "variation.enabled", 1)


class TestCoercion:
    def test_a_comma_string_becomes_a_list(self) -> None:
        assert coerce(BY_PATH["seo.keywords"], "a, b ,c") == ["a", "b", "c"]

    def test_blank_entries_are_dropped(self) -> None:
        assert coerce(BY_PATH["seo.keywords"], "a, , b") == ["a", "b"]

    def test_a_numeric_string_becomes_an_int(self) -> None:
        assert coerce(BY_PATH["posting.posts_per_day"], "12") == 12
