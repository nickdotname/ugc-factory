"""studio/replies.py: which comments get an answer, what it says, and the caps."""
import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("replies", Path(__file__).resolve().parent.parent / "studio" / "replies.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


@pytest.mark.parametrize("text", [
    "what song is this", "What's the song?", "song?", "Song name pls", "track id", "id?", "sauce?",
    "omg what song is this", "whats this song called", "who made this beat", "who sings this",
    "what's the name of this song", "need this song", "shazam couldn't find it", "which track is this?",
    "who is the artist?", "como se llama la cancion", "qual o nome da música?", "quelle chanson ?",
    "where can i find this song", "this goes hard what's the song",
])
def test_song_questions(text):
    assert R.is_song_question(text)


@pytest.mark.parametrize("text", [
    "", "this song is fire 🔥", "love this song", "what a song", "what a beat!!", "who asked", "who cares",
    "the music in this slaps", "🔥🔥🔥", "this is so cool", "first", "what is this garbage song?",
    "follow me", "beautiful edit", "nice", "who is this?", "link?", "I love the band",
])
def test_not_song_questions(text):
    assert not R.is_song_question(text)


def test_reply_wording():
    a = R.reply_for("math_ig", "Talk", "123")
    assert "Talk" in a and "@close__quarters" in a
    assert R.reply_for("math_ig", "Talk", "123") == a                      # the same comment, the same words
    assert len({R.reply_for("math_ig", "Talk", str(i)) for i in range(50)}) > 2
    assert "@close__quarters" in R.reply_for("math_ig", None, "9")
    own = R.reply_for("close_quarters_ig", "Talk", "5")
    assert "Talk" in own and "@close__quarters" not in own                 # the band doesn't tag itself
    for i in range(30):
        for acc in ("math_ig", "close_quarters_ig"):
            t = R.reply_for(acc, "Talk", str(i)).lower()
            assert "comment" not in t and "tag" not in t and "follow" not in t   # no engagement bait


class FakeGraph:
    def __init__(self, comments, now):
        self.comments, self.now, self.posted = comments, now, []

    def __call__(self, method, path, token, **params):
        if method == "GET" and path.endswith("/media"):
            uid = path.split("/")[0]
            if uid != R.ACCOUNTS["math_ig"][0]:
                return {"data": []}
            return {"data": [{"id": "m1", "comments_count": len(self.comments), "timestamp": self.now.isoformat()}]}
        if method == "GET" and path.endswith("/comments"):
            return {"data": self.comments}
        if method == "POST" and path.endswith("/replies"):
            self.posted.append((path.split("/")[0], params["message"]))
            return {"id": "r"}
        raise AssertionError(path)


def test_run_answers_questions_only_within_caps(tmp_path, monkeypatch):
    now = dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.timezone.utc)
    ts = (now - dt.timedelta(minutes=30)).isoformat()
    comments = [
        {"id": "c1", "text": "what song is this", "username": "someone", "timestamp": ts},
        {"id": "c2", "text": "🎧 Talk – @close__quarters", "username": "math.explainers", "timestamp": ts},  # our own first comment
        {"id": "c3", "text": "this is fire", "username": "someone2", "timestamp": ts},
        {"id": "c4", "text": "song?", "username": "someone3", "timestamp": ts,
         "replies": {"data": [{"username": "math.explainers"}]}},                                         # answered already
        {"id": "c5", "text": "song name?", "username": "a", "timestamp": ts},
        {"id": "c6", "text": "track id", "username": "b", "timestamp": ts},
        {"id": "c7", "text": "who made this beat", "username": "c", "timestamp": ts},                     # over PER_RUN
        {"id": "c8", "text": "what song", "username": "d", "timestamp": (now - dt.timedelta(days=5)).isoformat()},  # too old
    ]
    fake = FakeGraph(comments, now)
    monkeypatch.setattr(R, "graph", fake)
    monkeypatch.setattr(R, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(R, "song_titles", lambda: {"m1": "Talk"})
    monkeypatch.setenv("IG_TOKEN", "x")

    assert R.run(now=now) == R.PER_RUN
    assert [c for c, _ in fake.posted] == ["c1", "c5", "c6"]
    assert all("Talk" in m for _, m in fake.posted)

    state = json.loads((tmp_path / "state.json").read_text())
    raw = json.dumps(state)
    assert "someone" not in raw and "what song" not in raw                  # no usernames or comment text kept
    assert "m1" not in state["seen"]                                         # c7 is held, so the post is read again

    fake.posted.clear()
    assert R.run(now=now + dt.timedelta(minutes=15)) == 1                    # the held question, nothing twice
    assert [c for c, _ in fake.posted] == ["c7"]
    fake.posted.clear()
    assert R.run(now=now + dt.timedelta(minutes=30)) == 0


def test_hourly_cap(tmp_path, monkeypatch):
    now = dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.timezone.utc)
    ts = (now - dt.timedelta(minutes=5)).isoformat()
    fake = FakeGraph([{"id": "c%d" % i, "text": "song?", "username": "u%d" % i, "timestamp": ts} for i in range(20)], now)
    monkeypatch.setattr(R, "graph", fake)
    monkeypatch.setattr(R, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(R, "song_titles", lambda: {})
    monkeypatch.setenv("IG_TOKEN", "x")
    total = sum(R.run(now=now + dt.timedelta(minutes=5 * k)) for k in range(6))
    assert total == R.PER_HOUR


def test_no_permission_stops_quietly(tmp_path, monkeypatch):
    def denied(*a, **k):
        raise R.NoPermission("needs instagram_manage_comments")
    monkeypatch.setattr(R, "graph", denied)
    monkeypatch.setattr(R, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("IG_TOKEN", "x")
    assert R.run() == 0


def test_every_account_with_its_own_token_is_read_with_it():
    """accounts.yaml is the source of truth for which slot opens which account; replies.py must agree, or the
    shared IG_TOKEN is tried on an account it cannot read (toon, zoom, date, lowpoly, college until 2026-11-26)."""
    import yaml
    accounts = {a["name"]: a for a in yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "accounts.yaml").read_text(encoding="utf-8"))["accounts"]}
    for name, (uid, handle) in R.ACCOUNTS.items():
        assert name in accounts, name
        assert accounts[name]["channel_id"] == uid, name
        slot = accounts[name]["api_key_secret"]
        if slot == "IG_TOKEN":
            assert name not in R.TOKENS, name
        elif slot.startswith("IG_TOKEN"):
            assert R.TOKENS.get(name) == slot, (name, slot)


def test_page_tokens_are_used_for_the_accounts_they_cover(tmp_path, monkeypatch, capsys):
    now = dt.datetime(2026, 11, 23, 16, 0, tzinfo=dt.timezone.utc)
    seen = {}

    def graph(method, path, token, **params):
        if method == "GET" and path.endswith("/media"):
            seen[path.split("/")[0]] = token
            return {"data": []}
        raise AssertionError(path)

    monkeypatch.setattr(R, "graph", graph)
    monkeypatch.setattr(R, "STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(R, "song_titles", lambda: {})
    monkeypatch.setenv("IG_TOKEN", "shared")
    monkeypatch.setenv("IG_TOKEN_7", "toon-tok")
    monkeypatch.setenv("IG_PAGE_TOKENS", json.dumps({R.ACCOUNTS["eyetrick_ig"][0]: "page-tok"}))
    for slot in ("IG_TOKEN_2", "IG_TOKEN_3", "IG_TOKEN_4", "IG_TOKEN_5", "IG_TOKEN_6", "IG_TOKEN_8",
                 "IG_TOKEN_9", "IG_TOKEN_10", "IG_TOKEN_11"):
        monkeypatch.delenv(slot, raising=False)
    assert R.run(now=now) == 0
    assert seen[R.ACCOUNTS["eyetrick_ig"][0]] == "page-tok"
    assert seen[R.ACCOUNTS["toon_ig"][0]] == "toon-tok"
    assert seen[R.ACCOUNTS["math_ig"][0]] == "shared"
    assert R.ACCOUNTS["zoom_ig"][0] not in seen                      # no IG_TOKEN_8: skipped, not tried with IG_TOKEN
    out = capsys.readouterr().out.splitlines()[-1]
    assert out.startswith("replies: read 0 posts on") and "skipped" in out and "zoom.into.art" in out
