

class TestHashtagCap:
    """Instagram allows five hashtags; a sixth must never get a post refused."""

    def test_keeps_the_first_five(self) -> None:
        from src.publishers.instagram import cap_hashtags
        assert cap_hashtags("hi #a #b #c #d #e #f #g\nline #h") == "hi #a #b #c #d #e\nline"

    def test_leaves_a_short_caption_alone(self) -> None:
        from src.publishers.instagram import cap_hashtags
        text = "price is #1  in C#minor #a"
        assert cap_hashtags(text) == text


def test_page_token_is_used_for_its_account(monkeypatch, tmp_path):
    """IG_PAGE_TOKENS wins over the shared login token for the account it covers."""
    import json as _json
    from unittest import mock

    from src.publishers.instagram import InstagramPublisher
    monkeypatch.setenv("IG_PAGE_TOKENS", _json.dumps({"111": "page-tok"}))
    seen = []

    def request(method, url, **kw):
        seen.append(kw["headers"]["Authorization"])
        r = mock.Mock(status_code=200)
        r.json.return_value = {"data": [{"quota_usage": 1, "config": {"quota_total": 50}}]}
        return r

    session = mock.Mock(request=request)
    pub = InstagramPublisher("user-tok", mock.Mock(), outbox_dir=tmp_path, login="facebook", session=session)
    pub.publishing_allowance("111")
    pub.publishing_allowance("222")
    assert seen == ["Bearer page-tok", "Bearer user-tok"]
