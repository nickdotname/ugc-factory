"""Per-platform text limits and the description bank (title vs description).

The distinction under test: Instagram and TikTok have one long free-text field;
YouTube has a **separate title capped at 100 characters** on top of its
description. Limits verified August 2026 — see README.
"""

from __future__ import annotations

import pytest

from src.config import PostType
from src.descriptions import Description, load_bank, parse_bank, validate_bank
from src.errors import ConfigError
from src.platforms import (
    LIMITS,
    Service,
    advice,
    check_description,
    check_title,
    limits_for,
)


class TestLimitsTable:
    def test_every_service_has_limits(self) -> None:
        for service in Service:
            assert limits_for(service).description_max > 0

    def test_instagram_allows_2200(self) -> None:
        assert limits_for(Service.INSTAGRAM).description_max == 2_200

    def test_tiktok_allows_4000(self) -> None:
        """Raised from 2,200 in 2024 — the value most likely to be stale."""
        assert limits_for(Service.TIKTOK).description_max == 4_000

    def test_youtube_title_is_capped_at_100_and_required(self) -> None:
        y = limits_for(Service.YOUTUBE)
        assert y.title_max == 100
        assert y.title_required is True
        assert y.description_max == 5_000

    def test_only_youtube_has_a_separate_title(self) -> None:
        assert limits_for(Service.YOUTUBE).has_title
        assert not limits_for(Service.INSTAGRAM).has_title
        assert not limits_for(Service.TIKTOK).has_title


class TestDescriptionChecks:
    def test_normal_description_passes_everywhere(self) -> None:
        for service in Service:
            assert check_description("a normal description", service) == []

    def test_empty_description_is_rejected(self) -> None:
        assert check_description("   ", Service.INSTAGRAM)

    def test_over_instagram_limit_is_rejected(self) -> None:
        problems = check_description("x" * 2_201, Service.INSTAGRAM)
        assert problems and "2200 limit" in problems[0].replace(",", "")

    def test_same_text_is_fine_on_tiktok(self) -> None:
        """2,201 chars breaks Instagram but is well inside TikTok's 4,000."""
        assert check_description("x" * 2_201, Service.INSTAGRAM)
        assert check_description("x" * 2_201, Service.TIKTOK) == []

    def test_over_tiktok_limit_is_rejected(self) -> None:
        assert check_description("x" * 4_001, Service.TIKTOK)

    def test_youtube_description_allows_5000(self) -> None:
        assert check_description("x" * 5_000, Service.YOUTUBE) == []
        assert check_description("x" * 5_001, Service.YOUTUBE)


class TestTitleChecks:
    def test_title_is_ignored_where_the_platform_has_none(self) -> None:
        """The same bank feeds every campaign; Instagram just ignores a title."""
        assert check_title("a title", Service.INSTAGRAM) == []
        assert check_title(None, Service.INSTAGRAM) == []
        assert check_title("x" * 500, Service.TIKTOK) == []

    def test_youtube_requires_a_title(self) -> None:
        problems = check_title(None, Service.YOUTUBE)
        assert problems and "requires a title" in problems[0]

    def test_youtube_rejects_a_blank_title(self) -> None:
        assert check_title("   ", Service.YOUTUBE)

    def test_youtube_title_over_100_is_rejected(self) -> None:
        problems = check_title("x" * 101, Service.YOUTUBE)
        assert problems and "over youtube's 100 limit" in problems[0]

    def test_youtube_title_of_exactly_100_passes(self) -> None:
        assert check_title("x" * 100, Service.YOUTUBE) == []


class TestAdvice:
    def test_long_first_line_is_flagged_but_not_an_error(self) -> None:
        notes = advice("x" * 300, None, Service.INSTAGRAM)
        assert notes and "before 'more'" in notes[0]
        assert check_description("x" * 300, Service.INSTAGRAM) == []

    def test_short_first_line_gets_no_note(self) -> None:
        assert advice("a punchy hook line", None, Service.INSTAGRAM) == []

    def test_youtube_flags_a_title_longer_than_the_display_width(self) -> None:
        notes = advice("body", "x" * 80, Service.YOUTUBE)
        assert any("displays about 40" in n for n in notes)


class TestBankParsing:
    def test_blank_lines_separate_records(self) -> None:
        bank = parse_bank("first one\n\nsecond one\n\nthird")
        assert [d.body for d in bank] == ["first one", "second one", "third"]

    def test_a_description_may_span_lines(self) -> None:
        bank = parse_bank("line one\nline two\n\nnext record")
        assert bank[0].body == "line one\nline two"
        assert len(bank) == 2

    def test_title_line_is_extracted(self) -> None:
        bank = parse_bank("title: My Short Title\nthe description body")
        assert bank[0].title == "My Short Title"
        assert bank[0].body == "the description body"

    def test_title_is_case_insensitive(self) -> None:
        assert parse_bank("TITLE: X\nbody")[0].title == "X"

    def test_records_without_a_title_are_fine(self) -> None:
        assert parse_bank("just a description")[0].title is None

    def test_comment_lines_are_ignored(self) -> None:
        bank = parse_bank("# a note\nreal description\n\n# whole block comment")
        assert [d.body for d in bank] == ["real description"]

    def test_empty_title_line_is_an_error(self) -> None:
        with pytest.raises(ConfigError, match="present but empty"):
            parse_bank("title:\nbody")

    def test_title_with_no_body_is_an_error(self) -> None:
        with pytest.raises(ConfigError, match="no body text"):
            parse_bank("title: orphan")

    def test_a_colon_in_the_body_is_not_a_title(self) -> None:
        """Only a leading `title:` line counts."""
        bank = parse_bank("here is a thing: and more")
        assert bank[0].title is None
        assert bank[0].body == "here is a thing: and more"


class TestBankValidation:
    def test_valid_instagram_bank_passes(self) -> None:
        errors, _ = validate_bank([Description(body="fine")], Service.INSTAGRAM)
        assert errors == []

    def test_reports_every_offending_record_not_just_the_first(self) -> None:
        bank = [Description(body="x" * 3_000), Description(body="ok"),
                Description(body="y" * 3_000)]
        errors, _ = validate_bank(bank, Service.INSTAGRAM)
        assert len(errors) == 2
        assert "#1" in errors[0] and "#3" in errors[1]

    def test_youtube_bank_without_titles_fails(self) -> None:
        errors, _ = validate_bank([Description(body="body")], Service.YOUTUBE)
        assert errors and "requires a title" in errors[0]

    def test_youtube_bank_with_titles_passes(self) -> None:
        errors, _ = validate_bank(
            [Description(body="body", title="A Title")], Service.YOUTUBE
        )
        assert errors == []

    def test_same_bank_passes_instagram_and_fails_youtube(self) -> None:
        """The point of per-platform validation, in one test."""
        bank = [Description(body="a description with no title")]
        assert validate_bank(bank, Service.INSTAGRAM)[0] == []
        assert validate_bank(bank, Service.YOUTUBE)[0] != []


class TestLoadBank:
    def test_load_rejects_an_over_limit_description(self) -> None:
        with pytest.raises(ConfigError, match="over instagram's"):
            load_bank("x" * 3_000, Service.INSTAGRAM, source="captions.txt")

    def test_load_rejects_an_empty_bank(self) -> None:
        with pytest.raises(ConfigError, match="no descriptions"):
            load_bank("# only comments\n", Service.INSTAGRAM, source="captions.txt")

    def test_load_names_the_source_file(self) -> None:
        with pytest.raises(ConfigError, match="mybank.txt"):
            load_bank("x" * 3_000, Service.INSTAGRAM, source="mybank.txt")

    def test_load_returns_parsed_records(self) -> None:
        bank = load_bank("one\n\ntwo", Service.INSTAGRAM, source="x")
        assert len(bank) == 2


class TestPublishRequestEnforcesLimits:
    """The last line of defence before the network."""

    def _request(self, **kw):
        from datetime import datetime, timezone

        from src.publishers.base import PublishRequest

        base = dict(
            channel_id="c1234", text="a description",
            video_url="https://x/v.mp4",
            scheduled_for=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )
        base.update(kw)
        return PublishRequest(**base)

    def test_over_limit_description_cannot_be_constructed(self) -> None:
        with pytest.raises(Exception, match="over instagram's"):
            self._request(text="x" * 3_000)

    def test_youtube_request_without_a_title_is_refused(self) -> None:
        with pytest.raises(Exception, match="requires a title"):
            self._request(service=Service.YOUTUBE, post_type=PostType.SHORT)

    def test_youtube_request_with_a_long_title_is_refused(self) -> None:
        with pytest.raises(Exception, match="over youtube's 100"):
            self._request(
                service=Service.YOUTUBE, post_type=PostType.SHORT, title="x" * 200
            )

    def test_valid_youtube_request_is_accepted(self) -> None:
        r = self._request(
            service=Service.YOUTUBE, post_type=PostType.SHORT, title="Short Title"
        )
        assert r.title == "Short Title"

    def test_redacted_view_reports_lengths_not_content(self) -> None:
        r = self._request(text="secret sauce", title=None)
        assert "secret sauce" not in str(r.redacted())
        assert r.redacted()["text_chars"] == 12


class TestBufferMetadataPerService:
    """A YouTube post must not receive Instagram metadata."""

    def _meta(self, service: Service, post_type: PostType, title: str | None = None):
        from datetime import datetime, timezone

        from src.publishers.base import PublishRequest
        from src.publishers.buffer import _metadata_for

        return _metadata_for(PublishRequest(
            channel_id="c1234", text="body", title=title, service=service,
            video_url="https://x/v.mp4", post_type=post_type,
            scheduled_for=datetime(2026, 8, 13, tzinfo=timezone.utc),
        ))

    def test_instagram_gets_instagram_metadata(self) -> None:
        meta = self._meta(Service.INSTAGRAM, PostType.REEL)
        assert meta is not None and meta["instagram"]["type"] == "reel"

    def test_youtube_gets_youtube_metadata_with_the_title(self) -> None:
        meta = self._meta(Service.YOUTUBE, PostType.SHORT, title="My Title")
        assert meta is not None
        assert "instagram" not in meta
        assert meta["youtube"]["title"] == "My Title"
        assert meta["youtube"]["madeForKids"] is False

    def test_tiktok_needs_no_metadata_block(self) -> None:
        assert self._meta(Service.TIKTOK, PostType.POST) is None


class TestConfigServiceValidation:
    def test_youtube_channel_cannot_post_reels(self) -> None:
        from src.config import BufferConfig

        with pytest.raises(Exception, match="not valid for youtube"):
            BufferConfig(
                api_key_secret="BUFFER_API_KEY",
                channel_id_secret="BUFFER_CHANNEL_X",
                post_type=PostType.REEL,
                service=Service.YOUTUBE,
            )

    def test_instagram_channel_cannot_post_shorts(self) -> None:
        from src.config import BufferConfig

        with pytest.raises(Exception, match="not valid for instagram"):
            BufferConfig(
                api_key_secret="BUFFER_API_KEY",
                channel_id_secret="BUFFER_CHANNEL_X",
                post_type=PostType.SHORT,
                service=Service.INSTAGRAM,
            )

    def test_defaults_are_instagram_reel(self) -> None:
        from src.config import BufferConfig

        cfg = BufferConfig(
            api_key_secret="BUFFER_API_KEY", channel_id_secret="BUFFER_CHANNEL_X"
        )
        assert cfg.service is Service.INSTAGRAM
        assert cfg.post_type is PostType.REEL
