#!/usr/bin/env python3
"""Work out which ingredients of the videos people actually watch, and write that down for the nightly job.

    python studio/learn.py            # reads campaigns/*/posts.json + history.json + recipes.json

For every campaign in studio/nightly.yaml it joins each published post's views to the recipe of the
video it used (song, section, look, opening line, lyric style, palette), then compares each option's
median views with the campaign's overall median. The result is a weight per option:

    1.0  = performs like everything else (or not enough posts yet to say)
    2.0  = about twice the typical views        0.5 = about half

Weights are pulled towards 1.0 until an option has several posts behind it, and never leave 0.4-2.5,
so one lucky or unlucky post cannot take over. They are written to studio/weights.json, which
nightly.py uses to make more of what works while still trying everything, and to studio/LEARNED.md,
which is the same thing in words.
"""
import datetime, json, os, statistics
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
cfg = yaml.safe_load(open(os.path.join(HERE, 'nightly.yaml'))); out = {'updated': datetime.date.today().isoformat(), 'campaigns': {}}; lines = ['# What the numbers say', '', 'Updated %s by studio/learn.py. Weights: 1.0 is typical, 2.0 is about twice the views.' % out['updated'], '']
load = lambda p, d: json.load(open(p)) if os.path.exists(p) else d

def views(post):
    m = {x.get('type'): x.get('value') for x in post.get('metrics', [])}; return m.get('views')

for t in cfg['targets']:
    camp = t['campaign']; cdir = os.path.join(REPO, 'campaigns', camp)
    posts = {p['post_id']: p for p in load(os.path.join(cdir, 'posts.json'), {}).get('posts', [])}
    rec = load(os.path.join(cdir, 'recipes.json'), {}); attrs = {}
    for cr, clips in (rec.get('clips') or {}).items():                       # videos staged by hand: creative -> clip -> recipe
        if isinstance(clips, dict):
            for clip, r in clips.items():
                if isinstance(r, dict) and 'seed' in r: attrs[(cr, clip)] = dict(song=r.get('song'), section=r.get('section'), look=r.get('background') or r.get('theme'), hook='', lyrics=None, palette=r.get('palette'))
    for e in rec.get('nightly', []):                                         # videos the nightly job made
        if not e.get('clip'): continue
        p = e.get('plan') or {}
        attrs[(e['creative'], e['clip'])] = dict(song=e.get('song'), section=e.get('section'), look=p.get('field') or p.get('wall') or p.get('theme'), hook=p.get('hook', ''), lyrics=p.get('lyrics'), palette=p.get('pal'),
                                                 length='long' if (e.get('window') or [0, 0])[1] - (e.get('window') or [0, 0])[0] >= 30 else 'short')
    samples = {}; allv = []
    for h in load(os.path.join(cdir, 'history.json'), {}).get('entries', []):
        a = attrs.get((h.get('creative'), h.get('hook')))
        for pid in set(list((h.get('post_ids') or {}).values()) + [h.get('buffer_post_id')]):
            v = views(posts[pid]) if pid in posts else None
            if v is None: continue
            allv.append(v); samples.setdefault('song', {}).setdefault(h.get('creative'), []).append(v)
            cap = (h.get('caption') or '').split('\n')[0]
            if cap: samples.setdefault('caption', {}).setdefault(cap, []).append(v)
            for k, val in (a or {}).items():
                if k != 'song' and val not in (None,): samples.setdefault(k, {}).setdefault(str(val) if val != '' else '(none)', []).append(v)
    base = statistics.median(allv) if allv else 0; w = {}
    lines += ['## %s' % camp, '', '%d posts with numbers, typical views %s.' % (len(allv), int(base) if allv else 'n/a'), '']
    for dim, opts in sorted(samples.items()):
        w[dim] = {}
        rows = []
        for o, vs in opts.items():
            rel = (statistics.median(vs) / base) if base else 1.0; n = len(vs); wt = max(0.4, min(2.5, 1 + (rel - 1) * n / (n + 5.0))); w[dim][o] = round(wt, 2); rows.append((wt, o, n, int(statistics.median(vs))))
        if len(rows) > 1 and dim != 'caption' or len(rows) > 1:
            lines.append('**%s**' % dim)
            for wt, o, n, med in sorted(rows, reverse=True)[:8]: lines.append('- %s: weight %.2f (%d posts, median %d views)' % (o[:60], wt, n, med))
            lines.append('')
    out['campaigns'][camp] = dict(posts=len(allv), typical_views=base, weights=w)
json.dump(out, open(os.path.join(HERE, 'weights.json'), 'w'), indent=1); open(os.path.join(HERE, 'LEARNED.md'), 'w').write('\n'.join(lines) + '\n')
print('\n'.join(lines))
