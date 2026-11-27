"""`ugc metrics` goes red for a campaign whose account the token cannot read insights for.

The job's matrix runs fail-fast: false, so one red campaign does not stop the others; what it stops is the
week of 'metrics: []' with a green tick that the 2026-11-26 review found on ten accounts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import cli
from src.publishers.base import MetricRow, PostMetrics

CHANNEL = "17841400000000999"


@pytest.fixture
def campaign(tmp_path: Path, monkeypatch) -> Path:
    campaigns = tmp_path / "campaigns"
    slug_dir = campaigns / "alarm"
    slug_dir.mkdir(parents=True)
    (slug_dir / "config.yaml").write_text("""
slug: alarm
timezone: America/New_York
posting:
  posts_per_day: 2
  fan_out: true
  dry_run: false
accounts:
  mode: allow
  names: [blind_ig]
buffer:
  api_key_secret: BUFFER_API_KEY
  channel_id: aaa111
notify:
  webhook_secret: DISCORD_WEBHOOK_ALARM
""".strip(), encoding="utf-8")
    (slug_dir / "captions.txt").write_text("a caption", encoding="utf-8")
    (tmp_path / "accounts.yaml").write_text(f"""
accounts:
  - name: blind_ig
    network: instagram
    provider: instagram
    login: facebook
    api_key_secret: IG_TOKEN_2
    channel_id: "{CHANNEL}"
    post_type: reel
""".strip(), encoding="utf-8")
    monkeypatch.setattr(cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cli, "CAMPAIGNS_DIR", campaigns)
    return slug_dir


class _Source:
    """Stands in for InstagramPublisher: posts with no figures, and what it noticed about why."""

    def __init__(self, denied: bool) -> None:
        self.request_count = 0
        self.insights_denied = {CHANNEL: {
            "posts": 3, "error_class": "InvalidPostError", "graph_code": 10,
            "error": "(#10) Application does not have permission for this action",
        }} if denied else {}

    def fetch_post_metrics(self, channel, limit=200):
        return [PostMetrics(
            post_id=f"igo-{i}", service="instagram", sent_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
            metrics=() if self.insights_denied else (MetricRow(type="views", name="Views", value=9.0, unit="count"),),
        ) for i in range(3)]


def _run(monkeypatch, denied: bool, capsys) -> tuple[int, str]:
    monkeypatch.setattr(cli, "_real_publisher", lambda account, secret, log: _Source(denied))
    code = cli.cmd_metrics(
        argparse.Namespace(command="metrics", campaign="alarm", dry_run=False, days=30, instagram_only=True),
        {"IG_TOKEN_2": "tok"},
    )
    return code, capsys.readouterr().out


def test_an_account_denied_insights_turns_the_campaign_red(campaign: Path, monkeypatch, capsys) -> None:
    code, out = _run(monkeypatch, True, capsys)
    assert code == 1
    assert "::error::alarm: no insights permission on blind_ig" in out
    assert "InvalidPostError" in out and "code 10" in out
    # The per-post rows were still cached before the exit: nothing about the run is lost.
    assert (campaign / "posts.json").is_file()


def test_an_account_that_can_be_read_stays_green(campaign: Path, monkeypatch, capsys) -> None:
    code, out = _run(monkeypatch, False, capsys)
    assert code == 0 and "::error::" not in out
