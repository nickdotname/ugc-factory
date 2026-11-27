"""scripts/dash_data.py: what dashboard.closequarters.vip shows is what the repo says happened."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def dash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("dash_data", REPO_ROOT / "scripts" / "dash_data.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", str(tmp_path))
    for k in list(__import__("os").environ):
        if k.startswith("IG_TOKEN"):
            monkeypatch.delenv(k)
    (tmp_path / "accounts.yaml").write_text(
        "accounts:\n"
        "  - name: nyc_ig\n    network: instagram\n    provider: instagram\n    api_key_secret: IG_TOKEN\n"
        "    channel_id: '111'\n"
        "  - name: nickdotname_ig\n    network: instagram\n    api_key_secret: BUFFER_API_KEY\n"
        "    channel_id: '222'\n"
    )
    camp = tmp_path / "campaigns" / "nyc_daily"
    camp.mkdir(parents=True)
    (camp / "config.yaml").write_text(
        "creatives:\n  - name: talk\n    title: Talk\naccounts:\n  mode: allow\n  names: [nyc_ig]\n"
    )
    (tmp_path / "outbox").mkdir()
    return mod, tmp_path


def outbox(root: Path, pid: str, **fields) -> None:
    rec = dict(id=pid, channel_id="111", status="queued", scheduled_for="2099-01-01T15:00:00Z",
               caption="a caption", video_url="https://example.test/v.mp4")
    rec.update(fields)
    (root / "outbox" / f"{pid}.json").write_text(json.dumps(rec))


def build(mod, root: Path) -> dict:
    out = root / "data.json"
    mod.main(str(out))
    return json.loads(out.read_text())


def test_song_falls_back_to_the_sound_name(dash) -> None:
    mod, root = dash
    outbox(root, "igo-a", status="published", published_at="2026-11-23T15:00:00Z",
           scheduled_for="2026-11-23T15:00:00Z", audio_name="Full Ride – Close Quarters")
    (row,) = build(mod, root)["posts"]
    assert row["song"] == "Full Ride"
    assert row["status"] == "published"


def test_a_failed_post_keeps_its_reason(dash) -> None:
    mod, root = dash
    outbox(root, "igo-f", status="failed", scheduled_for="2026-11-23T15:00:00Z", error="video too long")
    (row,) = build(mod, root)["posts"]
    assert row["status"] == "failed"
    assert row["error"] == "video too long"


def test_numbers_carry_when_they_were_read(dash) -> None:
    mod, root = dash
    outbox(root, "igo-n", status="published", published_at="2026-11-23T15:00:00Z",
           scheduled_for="2026-11-23T15:00:00Z")
    (root / "campaigns" / "nyc_daily" / "posts.json").write_text(json.dumps({"posts": {"igo-n": {
        "post_id": "igo-n", "service": "instagram", "sent_at": "2026-11-23T15:00:00Z", "account": "nyc_ig",
        "fetched_at": "2026-11-23T18:00:00Z",
        "metrics": [{"type": "views", "name": "Views", "value": 120.0, "unit": "count"}]}}}))
    data = build(mod, root)
    (row,) = data["posts"]
    assert row["m"]["views"] == 120.0
    assert row["mt"] == "2026-11-23T18:00:00Z"
    nyc = next(a for a in data["accounts"] if a["name"] == "nyc_ig")
    assert nyc["numbers_at"] == "2026-11-23T18:00:00Z"


def test_a_carousel_shows_its_first_picture(dash) -> None:
    mod, root = dash
    outbox(root, "igo-c", video_url=None, image_urls=["https://example.test/s01.jpg", "https://example.test/s02.jpg"])
    (row,) = build(mod, root)["posts"]
    assert row["image"] == "https://example.test/s01.jpg"


def test_post_metrics_keep_their_read_time_through_the_cache(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from src.attribution import load_posts, save_posts, PostCache
    from src.publishers.base import PostMetrics

    when = datetime(2026, 11, 23, 18, 0, tzinfo=timezone.utc)
    cache = PostCache().merged_with([PostMetrics(post_id="igo-x", service="instagram", fetched_at=when)])
    save_posts(tmp_path / "posts.json", cache)
    assert load_posts(tmp_path / "posts.json").posts["igo-x"].fetched_at == when
    # and a cache written before the field existed still loads
    (tmp_path / "old.json").write_text(json.dumps({"posts": {"igo-y": {"post_id": "igo-y", "service": "instagram"}}}))
    assert load_posts(tmp_path / "old.json").posts["igo-y"].fetched_at is None


def graph(mod, monkeypatch, profile: dict, stats: dict | None = None):
    """Stand in for Instagram and the bio-link worker: what each URL dash_data fetches would answer."""
    calls: list[str] = []

    def fake_get(url, token=None):
        calls.append(url)
        if url.endswith("/stats"):
            if stats is None: raise OSError("no worker")
            return json.dumps(stats).encode()
        if "graph.facebook.com" in url:
            assert token, "Instagram is only asked with a token"
            if "business_discovery" in url: return json.dumps({"business_discovery": profile}).encode()
            return json.dumps(profile).encode()
        return b"\xff\xd8not really a jpeg"

    monkeypatch.setattr(mod, "_get", fake_get)
    return calls


def test_follower_counts_are_logged_once_a_day(dash, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date, timedelta

    mod, root = dash
    monkeypatch.setenv("IG_TOKEN", "x")
    prof = {"profile_picture_url": "https://example.test/p.jpg", "followers_count": 120, "follows_count": 7, "media_count": 31}
    calls = graph(mod, monkeypatch, prof)
    outbox(root, "igo-a")
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    long_ago = (date.today() - timedelta(days=120)).isoformat()
    (root / "followers.json").write_text(json.dumps({"accounts": {"nyc_ig": {
        week_ago: {"followers": 100, "follows": 7, "media": 20}, long_ago: {"followers": 1}}}}))
    data = build(mod, root)
    nyc = next(a for a in data["accounts"] if a["name"] == "nyc_ig")
    assert nyc["followers"] == 120 and nyc["media"] == 31 and nyc["follows"] == 7
    assert nyc["followers_7d"] == 20 and nyc["followers_since"] == week_ago
    assert nyc["followers_at"] == today and nyc["followers_log"] == {week_ago: 100, today: 120}
    assert nyc["pfp"].startswith("data:image/jpeg;base64,")
    log = json.loads((root / "followers.json").read_text())["accounts"]["nyc_ig"]
    assert set(log) == {week_ago, today}, "the row from 120 days ago is dropped; today's is added"
    assert log[today] == {"followers": 120, "follows": 7, "media": 31}
    # the Buffer-only account is looked up by handle through ours
    assert any("business_discovery.username%28the.loose.change%29" in u and "followers_count" in u for u in calls)
    # five minutes later nothing is fetched again and the numbers stand
    n = len(calls)
    data2 = build(mod, root)
    assert len(calls) == n, "Instagram is asked once a day"
    assert next(a for a in data2["accounts"] if a["name"] == "nyc_ig")["followers_7d"] == 20


def test_the_follower_log_is_rebuilt_from_data_json_when_the_file_is_missing(dash, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date, timedelta

    mod, root = dash
    monkeypatch.setenv("IG_TOKEN", "x")
    graph(mod, monkeypatch, {"profile_picture_url": "https://example.test/p.jpg", "followers_count": 130})
    outbox(root, "igo-a")
    y = (date.today() - timedelta(days=1)).isoformat()
    (root / "data.json").write_text(json.dumps({"accounts": [{"name": "nyc_ig", "followers_log": {y: 125}}], "posts": []}))
    nyc = next(a for a in build(mod, root)["accounts"] if a["name"] == "nyc_ig")
    assert nyc["followers"] == 130 and nyc["followers_7d"] == 5 and nyc["followers_since"] == y
    assert json.loads((root / "followers.json").read_text())["accounts"]["nyc_ig"][y] == {"followers": 125}


def test_bio_link_taps_per_account(dash, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date, timedelta

    mod, root = dash
    (root / "site.yaml").write_text("link_base: https://links.example.test\n")
    days = [(date.today() - timedelta(days=k)).isoformat() for k in range(6, -1, -1)]
    stats = {d: {} for d in days}
    stats[days[-1]] = {"nyc": 3, "other": 9}
    stats[days[0]] = {"nyc": 1}
    stats["week"] = {"nyc": 4, "other": 9}
    stats["last"] = {"nyc": {"at": "2026-11-26T12:00:00.000Z", "app": "instagram"}}
    graph(mod, monkeypatch, {}, stats)
    outbox(root, "igo-a")
    accs = {a["name"]: a for a in build(mod, root)["accounts"]}
    assert accs["nyc_ig"]["link"] == "/nyc" and accs["nyc_ig"]["taps7"] == 4
    assert accs["nyc_ig"]["taps"] == [1, 0, 0, 0, 0, 0, 3] and accs["nyc_ig"]["tap_last"] == "2026-11-26T12:00:00.000Z"
    assert accs["math_ig"]["taps7"] == 0 and accs["math_ig"]["tap_last"] is None
    # the worker unreachable: the last numbers stand rather than vanish
    graph(mod, monkeypatch, {}, None)
    outbox(root, "igo-b")
    accs = {a["name"]: a for a in build(mod, root)["accounts"]}
    assert accs["nyc_ig"]["taps7"] == 4 and accs["nyc_ig"]["link"] == "/nyc"


def test_every_handle_has_a_bio_link_path(dash) -> None:
    mod, _ = dash
    assert set(mod.LINKS.values()) == set(mod.HANDLES), "one tracked path per account (link/README.md, learn.py LINK_NAMES)"
    worker = (REPO_ROOT / "link" / "worker.js").read_text()
    for path in mod.LINKS:
        assert f'"{path}"' in worker, f"/{path} is not a source in link/worker.js"


def test_posts_waiting_in_buffer_are_shown(dash) -> None:
    """queue.json forgets a pushed item at the next render; Buffer still holds it."""
    mod, root = dash
    camp = root / "campaigns" / "closequarters"
    camp.mkdir(parents=True)
    (camp / "config.yaml").write_text(
        "creatives:\n  - name: talk\n    title: Talk\naccounts:\n  mode: allow\n  names: [nickdotname_ig]\n"
    )
    (camp / "history.json").write_text(json.dumps({"entries": [
        {"creative": "talk", "hook": "hook_01", "post_ids": {"nickdotname_ig": "buf-1"}, "caption": "c"}]}))
    (camp / "backend_queue.json").write_text(json.dumps({"posts": {
        "buf-1": {"account": "nickdotname_ig", "due": "2099-01-01T15:00:00+00:00"}}}))
    (camp / "queue.json").write_text(json.dumps({"items": [
        {"id": "it-2", "status": "pending", "creative": "talk", "scheduled_for": "2099-01-02T15:00:00Z", "posts": []}]}))
    rows = {r["id"]: r for r in build(mod, root)["posts"]}
    assert rows["buf-1"]["status"] == "scheduled" and rows["buf-1"]["song"] == "Talk"
    assert rows["buf-1"]["due"] == "2099-01-01T15:00:00Z" and rows["buf-1"]["via"] == "buffer"
    assert rows["q-it-2-nickdotname_ig"]["status"] == "pending", "rendered and waiting for room is shown too"
