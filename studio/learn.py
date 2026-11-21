#!/usr/bin/env python3
"""Work out which ingredients of the videos people actually watch, and write that down for the nightly job.

    python studio/learn.py            # reads campaigns/*/posts.json + history.json + recipes.json

For every campaign in studio/nightly.yaml it joins each published post's numbers to the recipe of the
video it used (song, section, look, opening line, lyric style, palette, length) and to when it went out.

A post is scored on three things, each as its rank among the campaign's own posts (0 = worst, 1 = best):

    views                       how far Instagram pushed it            counts for half
    average seconds watched     whether people stayed                  counts for 30%
    shares + saves per view     whether people wanted it               counts for 20%

Ranks are used rather than raw numbers because one runaway post would otherwise drown everything else.
Only posts at least MIN_AGE_H hours old are counted, so a video posted an hour ago is not compared with
one that has had two days. An option's weight is then

    1.0   performs like everything else, or not enough posts yet to say
    2.0   consistently the best                0.5   consistently the worst

and is pulled towards 1.0 until the option has several posts behind it. Weights go to studio/weights.json,
which nightly.py uses to make more of what works while still trying everything; the same thing in words,
with the real numbers beside it, goes to studio/LEARNED.md.

This never fails the nightly job: anything unreadable is skipped and reported.
"""
import datetime, json, os, statistics, sys
from zoneinfo import ZoneInfo

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MIN_AGE_H = float(os.environ.get('LEARN_MIN_AGE_H', 20))   # a post younger than this has not had its day yet
PRIOR = 5.0             # posts an option needs before its weight is taken at about half strength
MIX = (('views', 0.5), ('watch', 0.3), ('keep', 0.2))


def load(path, default):
    try:
        return json.load(open(path)) if os.path.exists(path) else default
    except (OSError, ValueError) as exc:
        print('::warning::could not read %s: %s' % (path, exc))
        return default


def numbers(post):
    """views, average seconds watched, shares+saves per view. None for a post with no figures at all."""
    m = {x.get('type'): x.get('value') for x in post.get('metrics') or []}
    if m.get('views') is None:
        return None
    views = float(m['views'] or 0)
    keep = (float(m.get('shares') or 0) + float(m.get('saves') or 0)) / max(views, 30.0)
    return dict(views=views, watch=m.get('averageTimeWatched'), keep=keep,
                shares=float(m.get('shares') or 0), saves=float(m.get('saves') or 0))


def recipes(rec):
    """(creative, clip name) -> what that video is made of."""
    out = {}

    def by_hand(creative, clip, r):
        w = r.get('window') or [0, 0]
        out[(creative, clip)] = dict(section=r.get('section'), look=r.get('background') or r.get('theme'), hook='',
                                     lyrics=None, palette=r.get('palette'), seconds=w[1] - w[0])

    for key, val in (rec.get('clips') or {}).items():
        if not isinstance(val, dict):
            continue
        if 'seed' in val or 'source' in val:                 # the first song was filed without a creative
            by_hand('notta_problem', key, val)
        else:
            for clip, r in val.items():
                if isinstance(r, dict):
                    by_hand(key, clip, r)
    for e in rec.get('nightly') or []:
        if not e.get('clip'):
            continue                                         # made before clip names were recorded
        p = e.get('plan') or {}
        w = e.get('window') or [0, 0]
        out[(e['creative'], e['clip'])] = dict(section=e.get('section'), look=p.get('field') or p.get('wall') or p.get('theme'),
                                               hook=p.get('hook') or '', lyrics=p.get('lyrics'), palette=p.get('pal'),
                                               seconds=w[1] - w[0])
    return out


def ranks(values):
    """Each value's rank among the others, 0..1, ties sharing the middle of their run."""
    order = sorted(values)
    n = len(order)
    if n < 2:
        return [0.5] * n
    return [(order.index(v) + (order.count(v) - 1) / 2) / (n - 1) for v in values]


def learn(camp, zone, now):
    cdir = os.path.join(REPO, 'campaigns', camp)
    posts = load(os.path.join(cdir, 'posts.json'), {}).get('posts') or {}
    if isinstance(posts, list):                              # older caches were a list
        posts = {p.get('post_id'): p for p in posts if isinstance(p, dict)}
    made = recipes(load(os.path.join(cdir, 'recipes.json'), {}))
    rows, young = [], 0
    for h in load(os.path.join(cdir, 'history.json'), {}).get('entries') or []:
        ids = set((h.get('post_ids') or {}).values()) | {h.get('buffer_post_id')}
        for pid in sorted(i for i in ids if i and i in posts):
            n = numbers(posts[pid])
            sent = posts[pid].get('sent_at')
            if n is None or not sent:
                continue
            when = datetime.datetime.fromisoformat(str(sent).replace('Z', '+00:00'))
            if (now - when).total_seconds() < MIN_AGE_H * 3600:
                young += 1
                continue
            a = made.get((h.get('creative'), h.get('hook'))) or {}
            secs = a.get('seconds') or 0
            opts = {
                'song': h.get('creative'),
                'section': '%s/%s' % (h.get('creative'), a['section']) if a.get('section') else None,
                'look': a.get('look'),
                'opening line': ('with' if a.get('hook') else 'without') if a else None,
                'hook': a.get('hook') or None,
                'lyrics': a.get('lyrics'),
                'palette': a.get('palette'),
                'length': None if not secs else 'under 20s' if secs < 20 else '20-35s' if secs < 35 else 'over 35s',
                'hour posted': '%02d:00' % when.astimezone(zone).hour,
                'caption': (h.get('caption') or '').split('\n')[0] or None,
            }
            if isinstance(opts['palette'], (list, tuple)):       # a list of colours: name it by its first one
                first = opts['palette'][0] if opts['palette'] else None
                opts['palette'] = '#%02x%02x%02x' % tuple(first[:3]) if isinstance(first, (list, tuple)) and len(first) >= 3 else None
            rows.append((n, {k: str(v) for k, v in opts.items() if v not in (None, '')}))
    if not rows:
        return dict(posts=0, waiting=young, weights={}), ['%d posts are too new to count yet.' % young if young else 'No posts with numbers yet.', '']

    # one score per post: its rank on each measure, mixed
    score = [0.0] * len(rows)
    for key, share in MIX:
        have = [(i, r[0][key]) for i, r in enumerate(rows) if r[0].get(key) is not None]
        for (i, _), rk in zip(have, ranks([v for _, v in have])):
            score[i] += share * rk
        for i in set(range(len(rows))) - {i for i, _ in have}:
            score[i] += share * 0.5                          # no figure for this measure: neither good nor bad
    med = lambda xs: statistics.median(xs) if xs else 0
    text = ['%d posts counted%s. Typical post: %d views, %.1f seconds watched.' % (
        len(rows), ' (%d more are too new)' % young if young else '',
        med([r[0]['views'] for r in rows]), med([r[0]['watch'] for r in rows if r[0].get('watch') is not None])), '']
    weights = {}
    for dim in ('opening line', 'hook', 'song', 'section', 'look', 'lyrics', 'palette', 'length', 'hour posted', 'caption'):
        groups = {}
        for (n, opts), s in zip(rows, score):
            if dim in opts:
                groups.setdefault(opts[dim], []).append((s, n))
        if not groups:
            continue
        weights[dim] = {}
        table = []
        for opt, items in groups.items():
            k = len(items)
            lean = (statistics.mean(s for s, _ in items) - 0.5) * 2 * k / (k + PRIOR)     # -1..1, shrunk while k is small
            w = round(2 ** lean, 2)
            weights[dim][opt] = w
            views = med([n['views'] for _, n in items])
            watch = med([n['watch'] for _, n in items if n.get('watch') is not None])
            kept = 1000 * sum(n['shares'] + n['saves'] for _, n in items) / max(1.0, sum(n['views'] for _, n in items))
            table.append((w, opt, k, views, watch, kept))
        if len(table) > 1:
            text.append('**%s**' % dim)
            for w, opt, k, views, watch, kept in sorted(table, reverse=True)[:10]:
                text.append('- %s: weight %.2f — %d post%s, %d views, %.1fs watched, %.0f shares+saves per 1,000 views' % (
                    opt[:70], w, k, '' if k == 1 else 's', views, watch, kept))
            text.append('')
    return dict(posts=len(rows), waiting=young, typical_views=med([r[0]['views'] for r in rows]), weights=weights), text


def main():
    cfg = yaml.safe_load(open(os.path.join(HERE, 'nightly.yaml')))
    now = datetime.datetime.now(datetime.timezone.utc)
    out = {'updated': now.date().isoformat(), 'campaigns': {}}
    lines = ['# What the numbers say', '',
             'Updated %s by studio/learn.py. A weight of 1.0 is typical, 2.0 is consistently the best, 0.5 the worst.' % out['updated'],
             'Each post is ranked on views (half), seconds watched (30%) and shares + saves per view (20%).', '']
    for t in cfg['targets']:
        camp = t['campaign']
        try:
            zone = ZoneInfo((yaml.safe_load(open(os.path.join(REPO, 'campaigns', camp, 'config.yaml'))) or {}).get('timezone') or 'UTC')
            result, text = learn(camp, zone, now)
        except Exception as exc:                             # never let a surprise here stop the videos being made
            print('::warning::learning skipped for %s: %r' % (camp, exc))
            result, text = dict(posts=0, weights={}), ['Skipped: %r' % exc, '']
        out['campaigns'][camp] = result
        lines += ['## %s' % camp, ''] + text
    json.dump(out, open(os.path.join(HERE, 'weights.json'), 'w'), indent=1)
    open(os.path.join(HERE, 'LEARNED.md'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('::warning::learn.py failed and was skipped: %r' % exc)
    sys.exit(0)
