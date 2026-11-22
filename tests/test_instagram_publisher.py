

class TestHashtagCap:
    """Instagram allows five hashtags; a sixth must never get a post refused."""

    def test_keeps_the_first_five(self) -> None:
        from src.publishers.instagram import cap_hashtags
        assert cap_hashtags("hi #a #b #c #d #e #f #g\nline #h") == "hi #a #b #c #d #e\nline"

    def test_leaves_a_short_caption_alone(self) -> None:
        from src.publishers.instagram import cap_hashtags
        text = "price is #1  in C#minor #a"
        assert cap_hashtags(text) == text
