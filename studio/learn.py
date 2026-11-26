#!/usr/bin/env python3
"""Work out which ingredients of the videos people actually watch, and write that down for the nightly job.

    python studio/learn.py            # reads campaigns/*/posts.json + history.json + recipes.json

For every campaign in studio/nightly.yaml it joins each published post's numbers to the recipe of the
video it used (song, section, look, opening line, lyric style, palette, length) and to when it went out.

A post is scored on the signals Instagram says it ranks Reels by, each as its rank among the campaign's own
posts (0 = worst, 1 = best):

    watched, as a share of length   completion (over 1 = people looped it)     30%
    sends per reach                 people DMing it on: the strongest signal   30%
                                    for reaching people who don't follow you
    views                           how far Instagram pushed it                15%
    saves per reach                 people wanting it again                    10%
    not skipped                     1 - the share who swiped away in the first 15%
                                    3 seconds (Instagram's reels_skip_rate)

Ranks are used rather than raw numbers because one runaway post would otherwise drown everything else.
Only posts at least MIN_AGE_H hours old are counted, so a video posted an hour ago is not compared with
one that has had two days. An option's weight is then

    1.0   performs like everything else, or not enough posts yet to say
    2.0   consistently the best                0.5   consistently the worst

and is pulled towards 1.0 until the option has several posts behind it. Recent posts count more than old ones
(a post's say halves every HALF_LIFE days), so the weights follow Instagram as it changes.

Every knob a renderer turned (studio/knobs.py: the pattern, the palette, the window style, the place...)
is a dimension of its own, "knob:<name>", with no list to keep up to date here. For each option the stats
(posts, recency-weighted posts, mean score) go to weights.json for nightly.py's Thompson sampling, and an
option that has had its chances (MIN_RETIRE posts) and is still clearly below typical is "retired": nightly
stops choosing it, though a free draw can still bring it back. Weights go to studio/weights.json,
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
HALF_LIFE = 21.0        # days for a post's say in the stats to halve
MIN_RETIRE = 8          # posts an option needs before it can be retired
MIX = (('done', 0.3), ('sends', 0.3), ('views', 0.15), ('saved', 0.1), ('held', 0.15))
# A mix for campaigns that want people talking (comments per reach). Nobody uses it today: cq_band and rocket_league did
# until 2026-11-26, when the debate hook angles they were added for had been gone two days and every post carried exactly
# one comment, our own song credit, so `talk` was 1/reach and rewarded the least-reached posts. numbers() now takes that
# own comment off the count, so TALK is usable again when a campaign earns a second comment; put it back here then.
TALK = (('done', 0.25), ('sends', 0.25), ('talk', 0.15), ('views', 0.15), ('saved', 0.05), ('held', 0.15))
MIX_FOR = {}
OWN_COMMENTS = 1        # comments on every post that are ours (the first comment credits the song): not people talking
NAMES = {'done': 'completion', 'sends': 'sends per reach', 'talk': 'comments per reach', 'views': 'views',
         'saved': 'saves per reach', 'held': 'not being skipped'}


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
    reach = max(float(m.get('reach') or 0) or views, 30.0)            # floored: 2 sends from 5 people is luck
    keep = (float(m.get('shares') or 0) + float(m.get('saves') or 0)) / max(views, 30.0)
    skip = m.get('skipRate')
    return dict(views=views, watch=m.get('averageTimeWatched'), keep=keep,
                sends=float(m.get('shares') or 0) / reach, saved=float(m.get('saves') or 0) / reach,
                talk=None if m.get('comments') is None else max(float(m['comments'] or 0) - OWN_COMMENTS, 0.0) / reach,
                held=None if skip is None else 1 - float(skip) / (100.0 if float(skip) > 1 else 1.0),
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
                                               angle=p.get('hook_angle'), shown=p.get('hook_mode') if p.get('hook') else None,
                                               faces=None if 'faces' not in p else ('with' if p['faces'] else 'without'),
                                               knobs=e.get('knobs') or {}, style=e.get('style'), seconds=w[1] - w[0])
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
    rec = load(os.path.join(cdir, 'recipes.json'), {})
    made = recipes(rec)
    # When a campaign's libraries are started afresh the clip names start again too, so a post is read against
    # the videos its own library held: the archive before `since`, the current ones after.
    before = recipes(rec.get('archive') or {})
    since = rec.get('since') if rec.get('archive') else None
    since = datetime.datetime.fromisoformat(str(since).replace('Z', '+00:00')) if since else None
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
            queued = h.get('timestamp')
            queued = datetime.datetime.fromisoformat(str(queued).replace('Z', '+00:00')) if queued else when
            book = made if not rec.get('archive') or (since is not None and queued >= since) else before
            a = book.get((h.get('creative'), h.get('hook'))) or {}
            secs = a.get('seconds') or 0
            n['done'] = n['watch'] / secs if secs and n.get('watch') is not None else None   # a 7s loop watched 6s beats a 20s clip watched 8s
            opts = {
                'song': h.get('creative'),
                'section': '%s/%s' % (h.get('creative'), a['section']) if a.get('section') else None,
                'look': a.get('look'),
                'style': a.get('style'),
                'opening line': ('with' if a.get('hook') else 'without') if a else None,
                'hook': a.get('hook') or None,
                'hook angle': a.get('angle'),
                'hook style': a.get('shown'),
                'faces': a.get('faces'),
                'lyrics': a.get('lyrics'),
                'palette': a.get('palette'),
                'length': None if not secs else 'under 10s' if secs < 10 else 'under 20s' if secs < 20 else '20-35s' if secs < 35 else 'over 35s',
                'hour posted': '%02d:00' % when.astimezone(zone).hour,
                'caption': (h.get('caption') or '').split('\n')[0] or None,
            }
            if isinstance(opts['palette'], (list, tuple)):       # a list of colours: name it by its first one
                first = opts['palette'][0] if opts['palette'] else None
                opts['palette'] = '#%02x%02x%02x' % tuple(first[:3]) if isinstance(first, (list, tuple)) and len(first) >= 3 else None
            for name, val in (a.get('knobs') or {}).items():
                if val in (None, ''): continue                   # a knob the renderer dropped or never set says nothing
                opts['knob:' + name] = val
            n['age'] = (now - when).total_seconds() / 86400
            rows.append((n, {k: str(v) for k, v in opts.items() if v not in (None, '')}))
    if not rows:
        return dict(posts=0, waiting=young, weights={}), ['%d posts are too new to count yet.' % young if young else 'No posts with numbers yet.', '']

    # one score per post: its rank on each measure, mixed
    score = [0.0] * len(rows)
    for key, share in MIX_FOR.get(camp, MIX):
        have = [(i, r[0][key]) for i, r in enumerate(rows) if r[0].get(key) is not None]
        for (i, _), rk in zip(have, ranks([v for _, v in have])):
            score[i] += share * rk
        for i in set(range(len(rows))) - {i for i, _ in have}:
            score[i] += share * 0.5                          # no figure for this measure: neither good nor bad
    med = lambda xs: statistics.median(xs) if xs else 0
    text = ['%d posts counted%s. Typical post: %d views, %.1f seconds watched.' % (
        len(rows), ' (%d more are too new)' % young if young else '',
        med([r[0]['views'] for r in rows]), med([r[0]['watch'] for r in rows if r[0].get('watch') is not None])), '']
    weights, stats, retired = {}, {}, {}
    named = ('style', 'opening line', 'hook', 'hook angle', 'hook style', 'faces', 'song', 'section', 'look', 'lyrics', 'palette', 'length', 'hour posted', 'caption')
    for dim in named + tuple(sorted({d for _, o in rows for d in o if d.startswith('knob:')})):
        groups = {}
        for (n, opts), s in zip(rows, score):
            if dim in opts:
                groups.setdefault(opts[dim], []).append((s, n))
        if not groups:
            continue
        weights[dim] = {}; stats[dim] = {}
        table = []
        for opt, items in groups.items():
            k = len(items)
            wt = [0.5 ** (n['age'] / HALF_LIFE) for _, n in items]; keff = sum(wt)
            mean = sum(w_ * s for w_, (s, _) in zip(wt, items)) / keff
            stats[dim][opt] = [k, round(keff, 2), round(mean, 3)]
            lean = (mean - 0.5) * 2 * keff / (keff + PRIOR)     # -1..1, shrunk while there are few (recent) posts
            w = round(2 ** lean, 2)
            weights[dim][opt] = w
            sd = (max(mean * (1 - mean), 0.02) / (keff + 2)) ** 0.5
            if k >= MIN_RETIRE and mean + 2 * sd < 0.45 and len(groups) > 1:
                retired.setdefault(dim, []).append(opt)
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
    if retired:
        text.append('**retired** (no longer chosen, after at least %d posts clearly below typical)' % MIN_RETIRE)
        text += ['- %s: %s' % (d, ', '.join(o)) for d, o in sorted(retired.items())] + ['']
    return dict(posts=len(rows), waiting=young, typical_views=med([r[0]['views'] for r in rows]), weights=weights, stats=stats, retired=retired), text


LINK_NAMES = {'psy': 'psychedelic.station', 'nostalgia': 'nostalgia.hub.vhs', 'cq': 'close__quarters', 'dc': 'dylancantor23'}

def clicks(now):
    """Taps on each account's bio link (link/worker.js), last 7 days, kept in studio/clicks.json. This is the
    one number that says whether the videos send people to the music."""
    base = (yaml.safe_load(open(os.path.join(REPO, 'site.yaml'))) or {}).get('link_base') or ''
    path = os.path.join(HERE, 'clicks.json')
    if base:
        try:
            import urllib.request
            req = urllib.request.Request(base.rstrip('/') + '/stats', headers={'User-Agent': 'Mozilla/5.0 (ugc-factory stats)'})
            json.dump(json.loads(urllib.request.urlopen(req, timeout=20).read()), open(path, 'w'), indent=1, sort_keys=True)
        except Exception as exc:
            print('::warning::could not read bio link clicks: %r' % exc)
    data = load(path, {})
    if not data: return []
    days = [(now - datetime.timedelta(days=k)).date().isoformat() for k in range(6, -1, -1)]
    srcs = sorted({s for d in data.values() for s in d})
    out = ['## Bio link taps, last 7 days', '', '| account | ' + ' | '.join(d[5:] for d in days) + ' | total |', '|---|' + '---|' * (len(days) + 1)]
    for s in srcs:
        row = [int((data.get(d) or {}).get(s, 0)) for d in days]
        out.append('| %s | %s | %d |' % (LINK_NAMES.get(s, s), ' | '.join(str(x) for x in row), sum(row)))
    return out + ['']

def main():
    cfg = yaml.safe_load(open(os.path.join(HERE, 'nightly.yaml')))
    now = datetime.datetime.now(datetime.timezone.utc)
    out = {'updated': now.date().isoformat(), 'campaigns': {}}
    lines = ['# What the numbers say', '',
             'Updated %s by studio/learn.py. A weight of 1.0 is typical, 2.0 is consistently the best, 0.5 the worst.' % out['updated'],
             'Each post is ranked on completion (30%), sends per reach (30%), views (15%), saves per reach (10%) and not being skipped (15%).', '']
    for t in cfg['targets']:
        camp = t['campaign']
        try:
            zone = ZoneInfo((yaml.safe_load(open(os.path.join(REPO, 'campaigns', camp, 'config.yaml'))) or {}).get('timezone') or 'UTC')
            result, text = learn(camp, zone, now)
        except Exception as exc:                             # never let a surprise here stop the videos being made
            print('::warning::learning skipped for %s: %r' % (camp, exc))
            result, text = dict(posts=0, weights={}), ['Skipped: %r' % exc, '']
        out['campaigns'][camp] = result
        mix = MIX_FOR.get(camp)
        note = ['Ranked on %s.' % ', '.join('%s (%d%%)' % (NAMES[k], round(v * 100)) for k, v in mix), ''] if mix else []
        lines += ['## %s' % camp, ''] + note + text
    lines += clicks(now)
    json.dump(out, open(os.path.join(HERE, 'weights.json'), 'w'), indent=1)
    open(os.path.join(HERE, 'LEARNED.md'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('::warning::learn.py failed and was skipped: %r' % exc)
    sys.exit(0)
