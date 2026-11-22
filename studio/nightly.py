#!/usr/bin/env python3
"""Render tonight's new videos for every target in studio/nightly.yaml and add them to the libraries.

    python studio/nightly.py [--only CAMPAIGN] [--count N] [--no-ingest]

For each target it lists every (song, stretch of lyrics) the campaign can use, prefers the ones
with the fewest videos so far, gives each a seed nothing has used, renders it with that style's
renderer, and hands the files to `ugc ingest`, which checks them and uploads them to the song's
clip library. What each video is made of is appended to the campaign's recipes.json under
"nightly", which is also how the next night knows what already exists.
"""
import argparse, datetime, json, os, random, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
ap = argparse.ArgumentParser(); ap.add_argument('--only', default=''); ap.add_argument('--count', type=int, default=0); ap.add_argument('--no-ingest', action='store_true')
a = ap.parse_args(); cfg = yaml.safe_load(open(os.path.join(HERE, 'nightly.yaml'))); today = datetime.date.today().isoformat()
MINC = cfg.get('min_confidence', 0.45); failed = False
LEARNED = (json.load(open(os.path.join(HERE, 'weights.json'))) if os.path.exists(os.path.join(HERE, 'weights.json')) else {}).get('campaigns', {})   # from learn.py

def stretches(song, join, floor=None):
    """Each usable section on its own, plus neighbours glued together up to `join` seconds.
    A section is usable when its lyric timing scored at least `floor` (min_confidence unless given)."""
    floor = MINC if floor is None else floor
    good = [s for s in song.get('sections', []) if s.get('confidence', 1) >= floor]; out = {s['id']: (s['start'], s['end']) for s in good}
    cur = None
    for s in good:
        if cur and s['start'] - cur[2] < 4 and s['end'] - cur[1] <= join: cur = [cur[0].split('-')[0] + '-' + s['id'], cur[1], s['end']]
        else:
            if cur: out[cur[0]] = (cur[1], cur[2])
            cur = [s['id'], s['start'], s['end']]
    if cur: out[cur[0]] = (cur[1], cur[2])
    return {k: v for k, v in out.items() if v[1] - v[0] >= 11}

def levels(song_dir):
    """How loud each stem is, second by second, as a share of its own loud passages (0..1+). -> {stem: array}"""
    import numpy as np, soundfile as sf
    out = {}
    for stem in ('Vocals', 'Drums', 'Bass', 'Other'):
        p = next((os.path.join(song_dir, 'stems', stem + e) for e in ('.ogg', '.flac', '.wav') if os.path.exists(os.path.join(song_dir, 'stems', stem + e))), None)
        if not p: continue
        y, sr = sf.read(p, always_2d=True, dtype='float32'); y = y.mean(1); n = len(y) // sr
        env = np.sqrt((y[:n * sr].reshape(n, sr) ** 2).mean(1)) if n else np.zeros(1)
        out[stem.lower()] = env / (np.percentile(env, 95) + 1e-9)
    return out

def playing(lv, win):
    """Share of full level each stem averages over a window. A stem under PLAYS is not really in that stretch."""
    a, b = int(win[0]), max(int(win[0]) + 1, int(win[1])); return {k: round(float(v[a:b].mean()) if len(v[a:b]) else 0.0, 2) for k, v in lv.items()}

PLAYS = 0.25
# Styles that are pictures to the music, with no lyrics on screen, and the script that draws each.
VISUAL = {'psy': 'psy_video.py', 'liminal': 'liminal_video.py'}

def suits(style, lv):
    """Whether a stretch has what a style shows. A drumless spoken intro makes an empty stems view and a still visualiser,
    and it is where a caption about the drums would be a lie."""
    on = {k for k, v in lv.items() if v >= PLAYS}
    if not lv: return True
    if style in VISUAL: return bool(on & {'drums', 'bass'})
    if style == 'producer': return len(on) >= 3
    return 'vocals' in on

TIGHT = 0.75          # share of videos cut short, hook first; the rest keep the whole stretch so the two can be compared
SHORT = 0.35          # of those, for the picture styles: a 6-9 second loop, which people watch through and replay (completion is Instagram's first signal)

def tighten(song_dir, win, rng, short=False):
    """A 10-20 second (short: 6-9 second) piece of `win` that starts on its strongest line and lasts a whole number of bars, so it
    loops cleanly. A line is strong when it recurs in the song (a hook) and the music under it is loud."""
    import numpy as np, soundfile as sf, re
    try:
        lines = json.load(open(os.path.join(song_dir, 'lines.json'))); song = json.load(open(os.path.join(song_dir, 'song.json')))
    except (OSError, ValueError):
        return win
    key = lambda ws: re.sub(r'[^a-z ]', '', ' '.join(w for w, _ in ws).lower()).strip()
    count = {}
    for _, ws in lines: count[key(ws)] = count.get(key(ws), 0) + 1
    m = next((os.path.join(song_dir, 'master' + e) for e in ('.ogg', '.flac', '.wav') if os.path.exists(os.path.join(song_dir, 'master' + e))), None)
    y, sr = sf.read(m, always_2d=True, dtype='float32') if m else (np.zeros((1, 1)), 1)
    loud = lambda t: float(np.sqrt(np.mean(y[int(t * sr):int((t + 4) * sr)] ** 2))) if m else 0.0
    bar = 4 * 60.0 / (song.get('tempo') or 120.0)
    while bar < 1.5: bar *= 2
    while bar > 4.0: bar /= 2
    t0, t1 = win; opts = []
    for _, ws in lines:
        st = ws[0][1] - 0.06
        if st < t0 - 0.05 or st + (6 if short else 10) > t1: continue
        opts.append((count[key(ws)] + 4 * loud(st), st))
    if not opts: return win
    opts.sort(reverse=True); st = rng.choice(opts[:3])[1]
    want = rng.uniform(6, 9) if short else rng.uniform(10, 20)
    dur = max(bar * round(want / bar), bar * (2 if short else 5))
    while short and dur < 5.5: dur += bar
    while st + dur > t1 + 0.05 and dur - bar >= (5.5 if short else 9.5): dur -= bar
    return (round(max(0.0, st), 2), round(min(t1, st + dur), 2))

def render(job):
    song_dir, style, seed, out, (t0, t1) = job[:5]
    # Moving colour fields fall apart into blocks at a low bitrate, and Instagram re-encodes whatever it is given,
    # so they get the most room; the flat-colour desktop and waveform styles need less.
    crf, cap, buf = ('23', '6M', '12M') if style in VISUAL else ('24', '4M', '8M')
    env = dict(os.environ, CQ_WINDOW='%s,%s' % (t0, t1), CQ_CRF=os.environ.get('CQ_CRF', crf), CQ_PRESET=os.environ.get('CQ_PRESET', 'medium'),
               CQ_MAXRATE=os.environ.get('CQ_MAXRATE', cap), CQ_BUFSIZE=os.environ.get('CQ_BUFSIZE', buf))
    if len(job) > 6 and not job[6]: env['CQ_LYRICS'] = 'none'
    for var, dim in (('CQ_HOOK_ANGLE', 'hook angle'), ('CQ_HOOK_MODE', 'hook style'), ('CQ_FACES', 'faces'), ('CQ_HOOK', 'hook'), ('CQ_FIELD', 'look')):          # half the time, lean towards what has been watched; the other half stays a free draw
        opts = {o: w for o, w in (job[5].get(dim) or {}).items() if o not in ('(none)', 'none', 'other') and (dim != 'look' or style == 'psy') and (dim not in ('hook angle', 'hook style', 'faces') or style in ('band', 'producer'))} if len(job) > 5 else {}
        r = random.Random(seed * 31 + len(var))
        if opts and r.random() < 0.5:
            env[var] = r.choices(list(opts), weights=[w ** 2 for w in opts.values()])[0]
            if var == 'CQ_FACES': env[var] = '1' if env[var] == 'with' else '0'
    cmd = [sys.executable, os.path.join(HERE, VISUAL[style]), song_dir, str(seed), out] if style in VISUAL else [sys.executable, os.path.join(HERE, 'lyric_video.py'), song_dir, style, str(seed), out]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True); ok = r.returncode == 0 and os.path.exists(out)
    if os.path.exists(out[:-4] + '.wav'): os.remove(out[:-4] + '.wav')
    print(('ok   ' if ok else 'FAIL ') + os.path.basename(out) + ('' if ok else '\n' + r.stderr[-500:]), flush=True)
    return ok

for t in cfg['targets']:
    camp, style = t['campaign'], t['style']
    if a.only and a.only != camp: continue
    cdir = os.path.join(REPO, 'campaigns', camp)
    if not os.path.exists(os.path.join(cdir, 'config.yaml')): print('skip', camp, '(no such campaign)'); continue
    ccfg = yaml.safe_load(open(os.path.join(cdir, 'config.yaml'))).get('creatives') or []
    creatives = {c['name'] for c in ccfg}
    # The drop folder `ugc ingest` reads for a creative is its library's name without "assets-"
    # (src/config.py creative_library_key): a fresh library (-v2) has a fresh folder.
    folder = {c['name']: (c.get('assets_release') or '').removeprefix('assets-') or '%s-%s' % (camp, c['name']) for c in ccfg}
    recp = os.path.join(cdir, 'recipes.json'); rec = json.load(open(recp)) if os.path.exists(recp) else {'clips': {}}
    if 'archive' in rec and not rec.get('since'):         # the libraries were started afresh: posts queued from now on are from the new ones
        rec['since'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    made = [v for c in rec.get('clips', {}).values() if isinstance(c, dict) for v in c.values() if isinstance(v, dict) and 'seed' in v] + rec.get('nightly', [])
    seeds = {m['seed'] for m in made}; uses = {}
    for m in made: uses[(m.get('song'), m.get('section'))] = uses.get((m.get('song'), m.get('section')), 0) + 1
    cands = []; LV = {}
    for slug in sorted(os.listdir(os.path.join(HERE, 'songs'))):
        sd = os.path.join(HERE, 'songs', slug); cr = slug.replace('-', '_')
        if cr not in creatives or not os.path.exists(os.path.join(sd, 'song.json')): continue
        song = json.load(open(os.path.join(sd, 'song.json')))
        if not any(os.path.exists(os.path.join(sd, 'master' + e)) for e in ('.wav', '.flac', '.ogg')): continue
        lv = levels(sd)
        sure = stretches(song, t.get('join', 0)); every = dict(sure)
        if style in VISUAL:                               # the visualiser can use any stretch: where the lyric timing is not proven it simply shows no lyrics
            for sid, win in stretches(song, t.get('join', 0), floor=0.0).items(): every.setdefault(sid, win)
        for sid, win in every.items():
            if suits(style, playing(lv, win)): cands.append((slug, cr, sid, win, sid in sure))
            else: print('   skip %s %s for %s: %s' % (slug, sid, style, playing(lv, win)))
        LV[slug] = lv
    W = (LEARNED.get(camp) or {}).get('weights', {}); wsong = W.get('song', {}); wsec = W.get('section', {})
    # fewest videos first, but a song or section that gets watched counts as having fewer (so it gets more), and vice versa
    rng = random.Random(today + camp); rng.shuffle(cands); cands.sort(key=lambda c: (uses.get((c[0], c[2]), 0) + 1) / (wsong.get(c[1], 1.0) * wsec.get('%s/%s' % (c[1], c[2]), 1.0)))
    have = len(rec.get('nightly', []))                       # what the current libraries hold
    want = a.count or max(t['per_night'], min(cfg.get('first_fill_cap', 16), cfg.get('first_fill', 0) - have) if t['style'] not in VISUAL else t['per_night'])
    picked, per_song = [], {}
    for lap in range(1, 6):                                   # go round the songs so one night is not all one track
        for c in cands:
            if len(picked) >= want: break
            if c not in picked and per_song.get(c[0], 0) < lap: picked.append(c); per_song[c[0]] = per_song.get(c[0], 0) + 1
    jobs, meta = [], []
    for slug, cr, sid, win, lyr in picked:
        seed = rng.randrange(1000, 10 ** 6)
        while seed in seeds: seed = rng.randrange(1000, 10 ** 6)
        if rng.random() < TIGHT: win = tighten(os.path.join(HERE, 'songs', slug), win, random.Random(seed), short=style in VISUAL and rng.random() < SHORT)
        seeds.add(seed); inbox = os.path.join(REPO, 'inbox', folder.get(cr, '%s-%s' % (camp, cr)), 'hooks'); os.makedirs(inbox, exist_ok=True)
        out = os.path.join(inbox, '%s_%s_%s_%d.mp4' % (slug, sid, style, seed)); jobs.append((os.path.join(HERE, 'songs', slug), style, seed, out, win, W, lyr)); meta.append((cr, slug, sid))
    print('== %s: %d videos (%s)' % (camp, len(jobs), style), flush=True)
    with ThreadPoolExecutor(max(1, min(4, os.cpu_count() or 2))) as ex: oks = list(ex.map(render, jobs))
    done = set()
    for (cr, slug, sid), job, ok in zip(meta, jobs, oks):
        out = job[3]
        if not ok: failed = True; continue
        r = json.load(open(out[:-4] + '.json')) if os.path.exists(out[:-4] + '.json') else {}
        if os.path.exists(out[:-4] + '.json'): os.remove(out[:-4] + '.json')
        rec.setdefault('nightly', []).append(dict(date=today, creative=cr, file=os.path.basename(out), song=slug, section=sid, style=style, seed=job[2], window=list(job[4]), plan=r.get('plan'), playing=playing(LV.get(slug, {}), job[4]), lyrics_proven=bool(job[6]))); done.add(cr)
    if not a.no_ingest:
        for cr in sorted(done):
            rep = os.path.join(REPO, 'work', 'ingest-%s-%s.json' % (camp, cr)); os.makedirs(os.path.dirname(rep), exist_ok=True)
            r = subprocess.run([sys.executable, '-m', 'src.cli', 'ingest', '--campaign', camp, '--creative', cr, '--report', rep], cwd=REPO)
            if r.returncode != 0: failed = True; print('::error::ingest failed for %s / %s' % (camp, cr))
            if os.path.exists(rep):                         # which library name each video was given: that name is what a post records
                named = {row['asset'].split('__', 1)[-1]: row.get('target') for row in json.load(open(rep))}
                for e in rec['nightly']:
                    if e.get('creative') == cr and e.get('date') == today and e.get('file') in named: e['clip'] = named[e['file']]
    json.dump(rec, open(recp, 'w'), indent=1)
sys.exit(1 if failed else 0)
