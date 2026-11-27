"""studio/learn.py: how a post is scored and what the learner writes down for nightly.py (2026-11-26 learner hygiene)."""
import datetime, json, os, sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'studio'))
import learn  # noqa: E402

NOW = datetime.datetime(2026, 11, 26, 12, tzinfo=datetime.timezone.utc)


def post(views, comments=1, watch=3.0, shares=0, saves=0, days=2.0):
    m = [dict(type='views', value=views), dict(type='reach', value=views), dict(type='comments', value=comments),
         dict(type='averageTimeWatched', value=watch), dict(type='shares', value=shares), dict(type='saves', value=saves)]
    return dict(metrics=m, sent_at=(NOW - datetime.timedelta(days=days)).isoformat())


def test_our_own_first_comment_is_not_talk():
    """Every post carries our song credit as its first comment: a post with only that has nobody talking."""
    assert learn.numbers(post(100, comments=1))['talk'] == 0.0
    assert learn.numbers(post(100, comments=0))['talk'] == 0.0            # never negative
    assert learn.numbers(post(100, comments=3))['talk'] == pytest.approx(2 / 100)
    assert learn.numbers(dict(metrics=[dict(type='views', value=100)], sent_at='x'))['talk'] is None


def test_no_campaign_scores_comments_per_reach():
    """cq_band and rocket_league used TALK, where 1 own comment / reach rewarded the least-reached posts."""
    assert learn.MIX_FOR == {}
    assert dict(learn.TALK)['talk'] > 0                                   # the mix itself is kept for later


def campaign(tmp_path, rows):
    """A campaign folder from (clip, knobs, post) rows: one video each, one post each."""
    cdir = tmp_path / 'campaigns' / 'c'; cdir.mkdir(parents=True)
    posts, entries, nightly = {}, [], []
    for k, (clip, knobs, p) in enumerate(rows):
        pid = 'p%d' % k
        posts[pid] = p
        hour = 10 + (k % 3)
        p['sent_at'] = (NOW - datetime.timedelta(days=2)).replace(hour=hour).isoformat()
        entries.append(dict(creative='talk', hook=clip, post_ids={'ig': pid}, timestamp=p['sent_at'], caption='a line'))
        nightly.append(dict(creative='talk', clip=clip, section='v1', window=[0, 8], style='psy', knobs=knobs, plan={}))
    json.dump(dict(posts=posts), open(cdir / 'posts.json', 'w'))
    json.dump(dict(entries=entries), open(cdir / 'history.json', 'w'))
    json.dump(dict(nightly=nightly), open(cdir / 'recipes.json', 'w'))
    return cdir


def test_hour_posted_is_shown_but_not_learned(tmp_path, monkeypatch):
    """nightly never chooses the hour (the publisher's slots do), so it gets a table and no weight."""
    monkeypatch.setattr(learn, 'REPO', str(tmp_path))
    rows = [('h%d' % k, {'pal': 'ice'}, post(10 * (k + 1))) for k in range(6)]
    campaign(tmp_path, rows)
    result, text = learn.learn('c', ZoneInfo('UTC'), NOW)
    assert result['posts'] == 6
    assert 'hour posted' not in result['weights'] and 'hour posted' not in result['stats']
    assert any(l.startswith('**hour posted**') and 'not learned' in l for l in text)
    assert 'song' in result['weights']                                     # the others are still learned


def test_a_knob_with_no_value_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(learn, 'REPO', str(tmp_path))
    rows = [('h0', {'pal': 'ice', 'shape': None}, post(10)), ('h1', {'pal': 'lava', 'shape': ''}, post(50)),
            ('h2', {'pal': 'ice', 'shape': 'ring'}, post(30))]
    campaign(tmp_path, rows)
    result, _ = learn.learn('c', ZoneInfo('UTC'), NOW)
    assert set(result['stats']['knob:pal']) == {'ice', 'lava'}
    assert set(result['stats']['knob:shape']) == {'ring'}                   # None and '' said nothing


def test_an_option_under_the_campaigns_25th_percentile_retires_after_four_posts(tmp_path, monkeypatch):
    """The old rule (8 posts, mean + 2 sd < 0.45) never fired at 2-5 posts a night; this one does, and only for a loser."""
    monkeypatch.setattr(learn, 'REPO', str(tmp_path))
    rows = [('g%d' % k, {'pal': 'good'}, post(100 + 10 * k, watch=6.0, shares=3)) for k in range(12)]
    rows += [('b%d' % k, {'pal': 'bad'}, post(5 + k, watch=0.5)) for k in range(4)]
    rows += [('m%d' % k, {'pal': 'meh'}, post(60 + k, watch=3.0)) for k in range(3)]       # under the bar, but only 3 posts
    campaign(tmp_path, rows)
    result, text = learn.learn('c', ZoneInfo('UTC'), NOW)
    assert result['retired'].get('knob:pal') == ['bad']
    assert result['stats']['knob:pal']['bad'][0] == 4
    assert any(l.startswith('**retired**') and '25th percentile' in l for l in text)
