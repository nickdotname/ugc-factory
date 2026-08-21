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
    SEARCH_FIELD,
    config_conflicts,
    effective_video_limits,
    keyword_advice,
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


class TestDeriveTitle:
    """Titles derived from a description's first line."""

    def test_short_first_line_is_used_whole(self) -> None:
        from src.descriptions import derive_title

        assert derive_title("A punchy hook line\nmore body", 100) == "A punchy hook line"

    def test_only_the_first_line_is_used(self) -> None:
        """Hashtag blocks and CTAs live below the hook and must not appear."""
        from src.descriptions import derive_title

        body = "The hook line\n\nComment 'x' for the link\n#one #two #three"
        assert derive_title(body, 100) == "The hook line"

    def test_long_line_is_cut_at_a_word_boundary(self) -> None:
        from src.descriptions import derive_title

        body = " ".join(["word"] * 40)  # 199 chars
        title = derive_title(body, 100)
        assert len(title) <= 100
        assert not title.endswith("wor"), "must not cut mid-word"
        assert title.split()[-1] == "word"

    def test_no_ellipsis_is_added(self) -> None:
        from src.descriptions import derive_title

        assert "..." not in derive_title(" ".join(["word"] * 40), 100)
        assert "…" not in derive_title(" ".join(["word"] * 40), 100)

    def test_trailing_punctuation_is_trimmed(self) -> None:
        from src.descriptions import derive_title

        body = ("x" * 90) + ", and then some more words here"
        assert not derive_title(body, 100).endswith(",")

    def test_single_giant_word_is_hard_cut(self) -> None:
        from src.descriptions import derive_title

        assert len(derive_title("x" * 300, 100)) == 100

    def test_leading_blank_lines_are_skipped(self) -> None:
        from src.descriptions import derive_title

        assert derive_title("\n\n  real first line\nrest", 100) == "real first line"

    def test_empty_body_gives_empty_title(self) -> None:
        from src.descriptions import derive_title

        assert derive_title("   \n\n  ", 100) == ""


class TestTitleStrategy:
    def test_derive_fills_missing_titles_for_youtube(self) -> None:
        from src.config import TitleStrategy
        from src.descriptions import Description, resolve_titles

        out = resolve_titles(
            [Description(body="My hook line\n#tags")], Service.YOUTUBE,
            TitleStrategy.DERIVE,
        )
        assert out[0].title == "My hook line"

    def test_derive_never_overwrites_an_explicit_title(self) -> None:
        from src.config import TitleStrategy
        from src.descriptions import Description, resolve_titles

        out = resolve_titles(
            [Description(body="hook", title="Hand Written")], Service.YOUTUBE,
            TitleStrategy.DERIVE,
        )
        assert out[0].title == "Hand Written"

    def test_require_leaves_titles_missing_so_validation_fails(self) -> None:
        from src.config import TitleStrategy
        from src.descriptions import Description, resolve_titles, validate_bank

        out = resolve_titles(
            [Description(body="hook")], Service.YOUTUBE, TitleStrategy.REQUIRE
        )
        assert out[0].title is None
        assert validate_bank(out, Service.YOUTUBE)[0] != []

    def test_derive_is_a_noop_for_instagram(self) -> None:
        """Instagram has no title field, so nothing is invented for it."""
        from src.config import TitleStrategy
        from src.descriptions import Description, resolve_titles

        out = resolve_titles(
            [Description(body="hook")], Service.INSTAGRAM, TitleStrategy.DERIVE
        )
        assert out[0].title is None

    def test_derived_titles_always_pass_validation(self) -> None:
        """Derivation is bounded by the platform limit by construction."""
        from src.config import TitleStrategy
        from src.descriptions import Description, resolve_titles, validate_bank

        bank = [Description(body=" ".join(["word"] * 80))]
        out = resolve_titles(bank, Service.YOUTUBE, TitleStrategy.DERIVE)
        assert validate_bank(out, Service.YOUTUBE)[0] == []

    def test_load_bank_derives_end_to_end(self) -> None:
        from src.descriptions import load_bank

        bank = load_bank(
            "First hook line\nbody text\n\nSecond hook line\nmore body",
            Service.YOUTUBE, source="captions.txt",
        )
        assert [d.title for d in bank] == ["First hook line", "Second hook line"]

    def test_load_bank_under_require_rejects_missing_titles(self) -> None:
        from src.config import TitleStrategy
        from src.descriptions import load_bank
        from src.errors import ConfigError

        with pytest.raises(ConfigError, match="requires a title"):
            load_bank("no title here", Service.YOUTUBE, source="x",
                      strategy=TitleStrategy.REQUIRE)


class TestSeparatorFormat:
    """Captions need internal blank lines; `---` makes that possible."""

    def test_dashes_separate_records_and_blank_lines_survive(self) -> None:
        from src.descriptions import parse_bank

        bank = (
            "hook line\n\ncomment \"create\"\n\n[a, b]\n"
            "---\n"
            "second hook\n\nsecond cta\n\n[c, d]\n"
        )
        records = parse_bank(bank)
        assert len(records) == 2, "blank lines must not split records here"
        assert records[0].body.count("\n\n") == 2
        assert "[a, b]" in records[0].body
        assert records[1].body.startswith("second hook")

    def test_blank_line_format_still_works_without_dashes(self) -> None:
        from src.descriptions import parse_bank

        assert len(parse_bank("one\n\ntwo\n\nthree")) == 3

    def test_longer_dash_runs_are_accepted(self) -> None:
        from src.descriptions import parse_bank

        assert len(parse_bank("a\n-----\nb")) == 2

    def test_dashes_inside_a_line_are_not_a_separator(self) -> None:
        from src.descriptions import parse_bank

        records = parse_bank("a caption -- with dashes -- inline")
        assert len(records) == 1

    def test_trailing_separator_does_not_make_an_empty_record(self) -> None:
        from src.descriptions import parse_bank

        assert len(parse_bank("only one\n---\n")) == 1

    def test_titles_still_work_with_the_separator_form(self) -> None:
        from src.descriptions import parse_bank

        records = parse_bank("title: T1\nbody one\n\nmore\n---\ntitle: T2\nbody two")
        assert [r.title for r in records] == ["T1", "T2"]


class TestKeywordAdvice:
    """Search is the traffic that does not decay, and it is the part of a
    caption people write last. These are notes, never errors."""

    KW = ("creative collaborators", "film students")

    def test_no_keywords_configured_says_nothing(self) -> None:
        assert keyword_advice("anything at all", None, Service.TIKTOK, ()) == []

    def test_a_caption_with_no_keyword_is_flagged(self) -> None:
        notes = keyword_advice("a lovely day out", None, Service.TIKTOK, self.KW)
        assert notes and "no target keyword" in notes[0]

    def test_a_front_loaded_keyword_passes_clean(self) -> None:
        notes = keyword_advice(
            "film students in new york, this is for you", None,
            Service.TIKTOK, self.KW,
        )
        assert notes == []

    def test_a_buried_keyword_is_flagged_for_position(self) -> None:
        notes = keyword_advice(
            "honestly the best thing I have found all year for film students",
            None, Service.TIKTOK, self.KW,
        )
        assert len(notes) == 1 and "first 4 words" in notes[0]

    def test_the_front_load_window_is_configurable(self) -> None:
        text = "one two three four five film students"
        assert keyword_advice(text, None, Service.TIKTOK, self.KW, 4) != []
        assert keyword_advice(text, None, Service.TIKTOK, self.KW, 7) == []

    def test_matching_is_case_insensitive(self) -> None:
        assert keyword_advice(
            "Film Students, listen up", None, Service.TIKTOK, self.KW
        ) == []

    def test_matching_respects_word_boundaries(self) -> None:
        """'nyu' inside 'denyung' is not a mention, and counting it would
        report a keyword as covered when it is absent."""
        notes = keyword_advice("denyung and other words", None,
                               Service.TIKTOK, ("nyu",))
        assert notes and "no target keyword" in notes[0]

    def test_a_multi_word_phrase_tolerates_extra_spacing(self) -> None:
        assert keyword_advice(
            "film  students are welcome", None, Service.TIKTOK,
            ("film students",),
        ) == []


class TestSearchSurface:
    """The platforms index different fields, and getting it backwards means
    posting something unsearchable to one of them."""

    def test_youtube_searches_the_title(self) -> None:
        assert SEARCH_FIELD[Service.YOUTUBE] == "title"

    def test_tiktok_and_instagram_search_the_caption(self) -> None:
        assert SEARCH_FIELD[Service.TIKTOK] == "caption"
        assert SEARCH_FIELD[Service.INSTAGRAM] == "caption"

    def test_youtube_checks_the_title_not_the_description(self) -> None:
        notes = keyword_advice(
            "a description absolutely stuffed with film students",
            "an unrelated title", Service.YOUTUBE, ("film students",),
        )
        assert notes and "title" in notes[0]

    def test_youtube_passes_when_the_title_carries_it(self) -> None:
        assert keyword_advice(
            "any description", "film students in new york",
            Service.YOUTUBE, ("film students",),
        ) == []

    def test_a_missing_youtube_title_is_an_empty_search_surface(self) -> None:
        notes = keyword_advice("body text", None, Service.YOUTUBE,
                               ("film students",))
        assert notes and "search surface" in notes[0]

    def test_tiktok_ignores_the_title_entirely(self) -> None:
        """TikTok has no title field; only the caption is indexed."""
        notes = keyword_advice(
            "nothing relevant here", "film students",
            Service.TIKTOK, ("film students",),
        )
        assert notes and "no target keyword" in notes[0]


class TestVideoLimits:
    """Text was already per-platform; video was not, and the difference bites
    hardest exactly where it is least visible."""

    def test_the_tighter_limit_wins(self) -> None:
        _, ceiling, _ = effective_video_limits(Service.YOUTUBE, 5, 90, 100)
        assert ceiling == 60.0

    def test_a_stricter_config_is_still_honoured(self) -> None:
        """The platform's number is a fact; the config is preference. Neither
        one gets to loosen the other."""
        _, ceiling, _ = effective_video_limits(Service.TIKTOK, 5, 30, 100)
        assert ceiling == 30.0

    def test_the_floor_takes_the_higher_of_the_two(self) -> None:
        floor, _, _ = effective_video_limits(Service.INSTAGRAM, 5, 90, 100)
        assert floor == 5.0
        floor, _, _ = effective_video_limits(Service.INSTAGRAM, 1, 90, 100)
        assert floor == 3.0

    def test_file_size_is_clamped_the_same_way(self) -> None:
        _, _, mb = effective_video_limits(Service.INSTAGRAM, 5, 90, 900)
        assert mb == 100.0

    def test_shorts_are_capped_below_the_other_two(self) -> None:
        """A Short is a Short because of its length. Over the boundary it is
        not rejected — it becomes an ordinary video and loses the entire
        Shorts surface, with no error to explain the drop."""
        yt = effective_video_limits(Service.YOUTUBE, 5, 600, 100)[1]
        ig = effective_video_limits(Service.INSTAGRAM, 5, 600, 100)[1]
        tt = effective_video_limits(Service.TIKTOK, 5, 600, 100)[1]
        assert yt < ig < tt


class TestConfigConflicts:
    def test_a_looser_config_is_reported(self) -> None:
        notes = config_conflicts(Service.YOUTUBE, 90.0, 100.0)
        assert notes and "clamped to 60s" in notes[0]

    def test_a_config_inside_the_platform_says_nothing(self) -> None:
        assert config_conflicts(Service.YOUTUBE, 45.0, 100.0) == []

    def test_an_oversized_file_cap_is_reported(self) -> None:
        notes = config_conflicts(Service.INSTAGRAM, 60.0, 900.0)
        assert any("max_file_mb" in n for n in notes)

    def test_instagram_does_not_inherit_the_shorts_ceiling(self) -> None:
        """The bug this replaces: one config, one hardcoded set of limits, and
        every validation message saying 'Reels' wherever it was going."""
        assert config_conflicts(Service.INSTAGRAM, 90.0, 100.0) == []
