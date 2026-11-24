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
