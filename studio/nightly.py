#!/usr/bin/env python3
"""Render tonight's new videos for every target in studio/nightly.yaml and add them to the libraries.

    python studio/nightly.py [--only CAMPAIGN] [--count N] [--no-ingest]

For each target it lists every (song, stretch of lyrics) the campaign can use, prefers the ones
with the fewest videos so far, gives each a seed nothing has used, renders it with that style's
renderer, and hands the files to `ugc ingest`, which checks them and uploads them to the song's
clip library. What each video is made of is appended to the campaign's recipes.json under
"nightly", which is also how the next night knows what already exists.

Choosing what each video looks like is where it improves itself. Every choice a renderer makes is a "knob"
(studio/knobs.py) with a menu of options; learn.py scores every option from the posts' numbers. For each
new video, each knob is set by Thompson sampling: every option draws a plausible score from what its posts
have shown so far (a wide guess when it has few, a narrow one when it has many) and the highest draw wins.
So what has worked is used most, what has hardly been tried still gets tried, and what keeps losing
(learn.py "retires" it) stops being chosen. One video in ten (EXPLORE) is left entirely to the renderer's
own dice, which keeps the comparison honest and lets new looks in.
"""
import argparse, datetime, json, os, random, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
import yaml

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
ap = argparse.ArgumentParser(); ap.add_argument('--only', default=''); ap.add_argument('--count', type=int, default=0); ap.add_argument('--no-ingest', action='store_true')
ap.add_argument('--set', default='', help='knobs every video of this run must use, e.g. "scene=bridge" or "topic=zeta,target=sun"')
a = ap.parse_args(); cfg = yaml.safe_load(open(os.path.join(HERE, 'nightly.yaml'))); today = datetime.date.today().isoformat()
MINC = cfg.get('min_confidence', 0.45); failed = False
LEARNED = (json.load(open(os.path.join(HERE, 'weights.json'))) if os.path.exists(os.path.join(HERE, 'weights.json')) else {}).get('campaigns', {})   # from learn.py

def stretches(song, join, floor=None, sync=None):
    """Each usable section on its own, plus neighbours glued together up to `join` seconds.
    A section is usable when its lyric timing scored at least `floor` (min_confidence unless given) and, when `sync` is
    given ({section id: passed}, studio/sync_check.py), its words measured as sung on time against the vocal stem."""
    floor = MINC if floor is None else floor
    good = [s for s in song.get('sections', []) if s.get('confidence', 1) >= floor and (sync is None or sync.get(s['id'], False))]; out = {s['id']: (s['start'], s['end']) for s in good}
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
VISUAL = {'psy': 'psy_video.py', 'liminal': 'liminal_video.py', 'math': 'math_video.py', 'glitch': 'glitch_video.py', 'physics': 'physics_video.py',
          'ascii': 'ascii_video.py', 'earth': 'earth_video.py'}
# Lyric styles with a renderer of their own (the rest are drawn by lyric_video.py): they set the proven lyrics, so
# they use only stretches whose lyric timing passed (like band and producer), never the picture styles' free ones.
LYRIC = {'type': 'type_video.py'}
LYRIC['lofi'] = 'lofi_video.py'      # the band's own dance footage, cut out, in a Y2K media player (studio/lofi/index.json says where there is footage)
LYRIC['cursor'] = 'cursor_video.py'  # the band rebuilt out of mouse cursors in a 3D Windows 98 world (any song: the dance clips loop where it has none)
LYRIC['cutout'] = 'cutout_video.py'  # the same dance footage, full screen and thrown around on the beat (dev_lemons-style), now and then trippy
NEEDS_PROJECT = {'physics'}             # styles whose hits come from the song's Ableton project (project_hits.json)
VISUAL['collage'] = 'collage_video.py'
WHOLE = {'math', 'race', 'tests8', 'stare', 'ebru', 'measure', 'hue'}      # styles choreographed to a fixed number of beats: never cut shorter
EXPLORE = 0.1         # share of videos whose look is left entirely to chance (0.2 until 2026-11-26: with retirement now automatic, less re-testing of known losers)
# Cosmetic knobs held at one value so the posts go to what can be learned at 2-5 posts a night: subject x cut x hook.
# Set 2026-11-26 for two weeks (the review found 1,565 option weights all within 0.87-1.13: a dozen knobs varying at once
# is not learnable at this volume); after FREEZE_UNTIL the learner gets them back. Values are the option that led, or the
# renderer's default, that day. A target's own `freeze: {knob: value}` in nightly.yaml adds to or overrides these.
FREEZE_UNTIL = '2026-12-10'
FROZEN = {'math': {'theme': 'chalk', 'font': 'montserrat', 'grid': 'none', 'shake': '0.6', 'glow': '1.0'},
          'tinycode': {'palette': 'neon', 'glow': '1.0'},
          'psy': {'pal': 'ice', 'sym': '8', 'feedback': 'false', 'mirror': 'true'},
          'physics': {'palette': 'neon', 'trail': 'ribbon'},
          'earth': {'palette': 'paper'},
          'glitch': {'tone': 'natural', 'label': 'none'},
          'vintage': {'tint': 'bw', 'crank': '1'},
          'cinema': {'look': 'phosphor', 'crt': 'on'}}

def frozen_for(style, target, today=None):
    """The knobs nightly holds fixed for one target tonight: FROZEN[style] plus the target's own `freeze:`, none after FREEZE_UNTIL."""
    today = today or datetime.date.today().isoformat()
    if today > FREEZE_UNTIL: return {}
    return {str(k): str(v) for k, v in dict(FROZEN.get(style) or {}, **(target.get('freeze') or {})).items()}
VISUAL['rocket'] = 'rocket_video.py'
# What we want an option to start from before any post has scored it ([_, posts, mean score], as learn.py writes):
# an option with real results uses those instead. The ASCII account is about the code, so most videos show it.
PRIOR = {'ascii': {'layout': {'code': [0, 3, 0.7], 'clean': [0, 3, 0.35]}}}
sys.path.insert(0, HERE); import hook as _hook
import sync_check as _sync          # the lyric sync gate: a stretch carries lyrics only where its words measure as on time
VISUAL['retro'] = 'retro_video.py'
VISUAL['fluid'] = 'fluid_video.py'    # wind-tunnel sims for the physics account (lattice Boltzmann; every gust a kick)
VISUAL['vintage'] = 'vintage_video.py'   # vintage.media.archive: films from before 1931 as old prints (footage theme silent)
VISUAL['nyc'] = 'nyc_video.py'           # nyc.daily.aesthetic: New York footage as a meme or a fact (footage theme nyc)
VISUAL['tinycode'] = 'tinycode_video.py' # tiny.code.loops: a few lines of numpy in an editor, and what they draw
VISUAL['cinema'] = 'cinema_video.py'     # ascii.cinema.tty: a public-domain film clip played back as coloured ASCII in a terminal
VISUAL['stopit'] = 'stopit_video.py'    # physics.bounce.lab: 'can you stop this?' (pause it inside the red line)
VISUAL['alife'] = 'alife_video.py'       # digital.petri.dish: a slime-mould simulation, the music as its weather
VISUAL['illusion'] = 'illusion_video.py' # rotation.illusions: dot shapes whose turning direction is up to your eyes
VISUAL['race'] = 'race_video.py'       # algorithm.races: sorting and pathfinding algorithms racing on the same problem
VISUAL['tests8'] = 'tests8_video.py'   # 8bit.tests: pixel-art tests you take along with the song
VISUAL['notes'] = 'text_video.py'      # moth.ate.my.notes: one thought on a gradient, like a text post
VISUAL['notes_her'] = 'text_her_video.py'   # crying.in.trader.joes: the same card in a girl's voice
VISUAL['notes_him'] = 'text_him_video.py'   # grip.tape.thoughts: the same card in a skater guy's voice
VISUAL['notes_date'] = 'text_date_video.py'       # situationship page: the same card, talking stages and mixed signals
VISUAL['notes_college'] = 'text_college_video.py' # broke-college-kid page: the same card, dorms, deadlines and the dining hall
VISUAL['lowpoly'] = 'lowpoly_video.py'  # low-poly story page: a "what if" story in big words over a blocky town (Blender, studio/lowpoly/)
VISUAL['toon'] = 'toon_video.py'       # rubber-hose page: cartoons from before 1931 cut as a modern edit (footage theme toons)
VISUAL['stare'] = 'stare_video.py'    # stare.lab (planned): afterimages, a spiral's aftereffect, the lilac chaser
VISUAL['measure'] = 'measure_video.py'  # ruler.says.no (planned): classic size/straightness/grey illusions, asked, then measured on the beat
VISUAL['ebru'] = 'ebru_video.py'      # marbled.by.math (planned): paper marbling by exact equations, drops on the beat, then a comb
VISUAL['hue'] = 'hue_video.py'        # colour.lies (planned): one colour that looks like two; an eyedropper reads both hex codes off the frame
VISUAL['reveal'] = 'reveal_video.py'  # circle.atlas (planned): a country's outline drawn by Fourier circles, the name at the end
VISUAL['zoom'] = 'zoom_video.py'       # museum-zoom page: a public-domain painting, then a dive into one detail on the drop (studio/art.py)

def lofi_cover(slug, win):
    """How much of a stretch the band's dance footage covers (0..1)."""
    try: clips = json.load(open(os.path.join(HERE, 'lofi', 'index.json')))['clips']
    except (OSError, ValueError): return 0.0
    runs = [(c['offset'], c['offset'] + c['frames'] / c['fps']) for c in clips if c['song'] == slug]
    ts = [win[0] + k * 0.5 for k in range(int((win[1] - win[0]) / 0.5) + 1)]
    return sum(any(a <= t <= b for a, b in runs) for t in ts) / max(1, len(ts))

FOOTAGE = {'lofi', 'cutout', 'scene'}   # styles built on the band's own dance footage (studio/lofi/index.json)

def footage_windows(slug, length=16.0, step=8.0):
    """Stretches inside the band's footage of a song, whether or not the song's lyric timing covers them: the footage
    has its own lyrics (studio/lofi/lines/), and Notta Problem's clip starts where song.json's sections end, so
    sections alone never offered it."""
    try: clips = json.load(open(os.path.join(HERE, 'lofi', 'index.json')))['clips']
    except (OSError, ValueError): return {}
    out = {}
    for c in clips:
        if c['song'] != slug: continue
        a, b = c['offset'] + 0.3, c['offset'] + c['frames'] / c['fps'] - 0.3; t = a; k = 0
        while t + 11 <= b:
            out['%s-%d' % (c['id'], k)] = (round(t, 2), round(min(b, t + length), 2)); t += step; k += 1
    return out

def thompson(options, stats, r, retired=()):
    """One option: each draws from Beta(1 + wins, 1 + losses), where a post's score (0..1) counts as that much of
    a win, recent posts counting more (learn.py); untried options draw from Beta(1, 1)."""
    live = [o for o in options if o not in retired] or list(options)
    best, top = None, -1.0
    for o in live:
        n, m = (stats.get(o) or [0, 0, .5])[1:3]
        v = r.betavariate(1 + m * n, 1 + (1 - m) * n)
        if v > top: best, top = o, v
    return best

# The knob that says what a video is about, for each style. The learner would happily show a winning subject night
# after night (math posted Fourier four times running), so whatever the knobs come out as, a video's subject is never
# one the account showed in its last REPEAT_NIGHTS nights (see freshen).
SUBJECT = {'math': 'topic', 'physics': 'scene', 'ascii': 'scene', 'psy': 'field', 'liminal': 'place', 'earth': 'scene',
           'glitch': 'source', 'retro': 'theme', 'cursor': 'world', 'fluid': 'obstacle', 'growth': 'look', 'rocket': 'format',
           'type': 'layout', 'band': 'wall', 'lofi': 'theme', 'collage': 'palette', 'vintage': 'tint', 'nyc': 'kind', 'tinycode': 'program', 'cinema': 'look', 'alife': 'start', 'scene': 'place', 'illusion': 'shape', 'race': 'topic', 'tests8': 'test', 'notes': 'line', 'notes_her': 'line', 'notes_him': 'line', 'toon': 'wash', 'zoom': 'work', 'notes_date': 'line', 'notes_college': 'line', 'lowpoly': 'story', 'reveal': 'country', 'stopit': 'thing', 'stare': 'scene', 'ebru': 'pattern', 'measure': 'kind', 'hue': 'kind'}
REPEAT_NIGHTS = 3                                     # a subject is not shown again on an account for this many nights

# Text pages: a line is never posted twice until the whole bank has been. The renderer alone cannot promise that
# (videos of one night render side by side, before any of them is in recipes.json; 2026-11-24 moth.ate.my.notes
# posted the same line twice), so the line is chosen here, off everything already posted AND everything picked tonight.
BANKED = {'notes': ('lines.txt', 'n'), 'notes_her': ('her.txt', 'h'), 'notes_him': ('him.txt', 'm'), 'notes_date': ('date.txt', 'd'), 'notes_college': ('college.txt', 'c')}   # bank file, id letter


def fresh_line(style, recent, r):
    name, pre = BANKED[style]
    blocks = open(os.path.join(HERE, 'notes', name), encoding='utf-8').read().split('\n---\n')[1:]
    ids = ['%s%03d' % (pre, k + 1) for k, b in enumerate(blocks) if b.strip()]   # the same ids text_video.bank() gives
    used = [x for x in recent if x]
    left = [i for i in ids if i not in used]
    if not left:                                                # every line out once: the longest-unused half again
        last = {i: k for k, i in enumerate(used)}
        left = sorted(ids, key=lambda i: last.get(i, -1))[:max(1, len(ids) // 2)]
        left = [i for i in left if i not in recent[-len(ids) // 2:]] or left
    return r.choice(left)


def freshen(style, menu, kn, recent, learned, r, first=True):
    """kn with its subject knob moved off everything the account showed in its recent videos (recent, oldest first:
    the last REPEAT_NIGHTS nights plus tonight). A subject the account showed in the last few days did half the views
    of a fresh one (median 61 vs 119, 2026-11-25). When every subject has been shown, the first video of the night
    takes the one shown longest ago; any further video that night is skipped (None): posting less beats repeating."""
    name = SUBJECT.get(style); opts = list(menu.get(name) or [])
    gone = set((learned.get('retired') or {}).get('knob:' + (name or ''), ()))
    opts = [o for o in opts if o not in gone] or opts      # a retired subject is not fresh either
    if not name or len(opts) < 2: return kn
    used = [v for v in recent if v in opts]
    fresh = [o for o in opts if o not in used]
    if not fresh:
        if not first: return None
        last = {v: k for k, v in enumerate(used)}
        fresh = [min(opts, key=lambda o: last.get(o, -1))]
    if kn.get(name) in fresh: return kn
    st, ret = learned.get('stats') or {}, learned.get('retired') or {}
    return dict(kn, **{name: thompson(fresh, st.get('knob:' + name) or {}, r, ret.get('knob:' + name) or ())})

def choose(style, menu, learned, seed, frozen=None):
    """The knobs and settings nightly fixes for one video, and whether it was left to chance. Frozen knobs are fixed either way."""
    r = random.Random(seed * 2654435761 % 2 ** 32)
    if r.random() < EXPLORE: return dict(frozen or {}), {}, 'free'
    st, ret = learned.get('stats') or {}, learned.get('retired') or {}
    kn = {name: thompson(opts, dict(PRIOR.get(style, {}).get(name, {}), **(st.get('knob:' + name) or {})), r, ret.get('knob:' + name) or ())
          for name, opts in sorted(menu.items()) if len(opts) > 1}
    kn.update(frozen or {})
    env = {}
    if style in _hook.ANGLES:                                   # the opening line: which angle (or none), and flashed or held
        ang = _hook.lead(style, seed) or thompson(sorted(_hook.ANGLES[style]) + ['none'], st.get('hook angle') or {}, r, ret.get('hook angle') or ())
        if ang == 'none': env['CQ_HOOK'] = 'none'
        else: env['CQ_HOOK_ANGLE'] = ang
        env['CQ_HOOK_MODE'] = thompson(['flash', 'hold'], st.get('hook style') or {}, r, ret.get('hook style') or ())
        env['CQ_FACES'] = '1' if thompson(['with', 'without'], st.get('faces') or {}, r, ret.get('faces') or ()) == 'with' else '0'
    elif thompson(['with', 'without'], st.get('opening line') or {}, r, ret.get('opening line') or ()) == 'without':
        env['CQ_HOOK'] = 'none'
    return kn, env, 'learned'

def suits(style, lv):
    """Whether a stretch has what a style shows. A drumless spoken intro makes an empty stems view and a still visualiser,
    and it is where a caption about the drums would be a lie."""
    on = {k for k, v in lv.items() if v >= PLAYS}
    if not lv: return True
    if style in VISUAL: return bool(on & {'drums', 'bass'})
    if style == 'producer': return len(on) >= 3
    return 'vocals' in on

TIGHT = 0.75          # share of lyric videos cut short, hook first; the rest keep the whole stretch so the two can be compared
# Where a picture style's cut starts from before its own posts say otherwise, as pseudo-posts in learn.py's [_, posts, mean]
# shape (like PRIOR): short 3 : tight 2 : full 1. Network-wide, completion was 0.46 under 10 s against 0.17 at 20-35 s
# (2026-11-26 review), so a 6-9 s loop is the default; real results on `knob:cut` replace these, so data can still say otherwise.
CUT_PRIOR = {'short': [0, 3, 0.7], 'tight': [0, 2, 0.5], 'full': [0, 1, 0.3]}

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

def cuts_for(style):
    """The lengths a style's video can have. The picture styles and the band's own footage styles (cutout, lofi) can be a
    6-9 s loop too (2026-11-26 review: on the band account completion was 0.29 under 12 s against 0.16 at 12-20 s, and
    the footage carries without words); the other lyric styles keep the whole stretch or its strongest 10-20 s; the
    WHOLE styles are choreographed in beats and never cut (math and race have their own `beats` knob for this)."""
    if style in WHOLE: return ['full']
    return ['full', 'tight', 'short'] if style in VISUAL or style in FOOTAGE else ['full', 'tight']

def choose_cut(style, how, learned, rng, seed):
    """How much of its stretch one video gets: 'full', 'tight' (10-20 s from its strongest line) or 'short' (a 6-9 s
    loop). Left to chance (`how` 'free') a style that offers short follows CUT_PRIOR's odds and the rest TIGHT; otherwise
    Thompson sampling on the account's own knob:cut results, over CUT_PRIOR where short is offered."""
    cuts = cuts_for(style)
    if len(cuts) == 1: return cuts[0]
    if how == 'free': return rng.choices(cuts, weights=[CUT_PRIOR[c][1] for c in cuts])[0] if 'short' in cuts else ('full' if rng.random() >= TIGHT else 'tight')
    stats = dict(CUT_PRIOR if 'short' in cuts else {}, **((learned.get('stats') or {}).get('knob:cut') or {}))
    return thompson(cuts, stats, random.Random(seed + 1), (learned.get('retired') or {}).get('knob:cut') or ())

SET = dict(x.split('=', 1) for x in a.set.replace(' ', '').split(',') if '=' in x)
SKIP = 3              # a renderer's exit code for "no video in this stretch" (studio/physics_video.py)
SOLO = {k: '1' for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS', 'OPENCV_FOR_THREADS_NUM')}

def render(job, solo=False):
    song_dir, style, seed, out, (t0, t1) = job[:5]
    # Moving colour fields fall apart into blocks at a low bitrate, and Instagram re-encodes whatever it is given,
    # so they get the most room; the flat-colour desktop and waveform styles need less.
    crf, cap, buf = ('23', '6M', '12M') if style in VISUAL else ('24', '4M', '8M')
    env = dict(os.environ, PYTHONFAULTHANDLER='1', CQ_WINDOW='%s,%s' % (t0, t1), CQ_CRF=os.environ.get('CQ_CRF', crf), CQ_PRESET=os.environ.get('CQ_PRESET', 'medium'),
               CQ_MAXRATE=os.environ.get('CQ_MAXRATE', cap), CQ_BUFSIZE=os.environ.get('CQ_BUFSIZE', buf))
    if len(job) > 6 and not job[6]: env['CQ_LYRICS'] = 'none'
    kn, extra = job[5]
    env.update(extra)
    if kn: env['CQ_KNOBS'] = json.dumps(kn)
    if solo: env.update(SOLO)
    own = VISUAL.get(style) or LYRIC.get(style)
    cmd = [sys.executable, os.path.join(HERE, own), song_dir, str(seed), out] if own else [sys.executable, os.path.join(HERE, 'lyric_video.py'), song_dir, style, str(seed), out]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True); ok = r.returncode == 0 and os.path.exists(out)
    if r.returncode == SKIP:                       # the renderer judged the stretch unusable (a ball with nothing to hit): not a failure
        print('skip ' + os.path.basename(out) + '  ' + (r.stdout.strip().splitlines() or [''])[-1], flush=True); return None
    if os.path.exists(out[:-4] + '.wav'): os.remove(out[:-4] + '.wav')
    sig = {-9: 'killed: out of memory?', -11: 'crashed: segmentation fault', -6: 'aborted'}.get(r.returncode, 'signal %d' % -r.returncode if r.returncode < 0 else '')
    why = '' if ok else '\n   exit %s%s  knobs %s %s\n%s' % (r.returncode, ' (%s)' % sig if sig else '', json.dumps(kn), json.dumps(extra), (r.stderr.strip()[:2000] if r.returncode < 0 else (r.stderr.strip() or r.stdout.strip())[-600:]))
    print(('ok   ' if ok else 'FAIL ') + os.path.basename(out) + why, flush=True)
    return ok

# librosa's compiled helpers are cached on disk the first time they run. Four renders starting together each wrote
# that cache at once and left it broken: every later render then died with a segmentation fault in peak_pick, alone
# or not (2026-11-23, the first run that began with four such renders). So it is built once here, by one process,
# in a folder of this run's own, before anything renders.
os.environ.setdefault('NUMBA_CACHE_DIR', os.path.join(tempfile.gettempdir(), 'cq-numba-%d' % os.getpid()))
warm = ("import numpy as np, librosa; y = np.random.default_rng(0).standard_normal(22050 * 4).astype('float32'); "
        "e = librosa.onset.onset_strength(y=y, sr=22050); librosa.util.peak_pick(e, pre_max=3, post_max=3, pre_avg=5, post_avg=5, delta=0.1, wait=5); "
        "librosa.onset.onset_detect(y=y, sr=22050); librosa.beat.beat_track(y=y, sr=22050); librosa.effects.hpss(y)")
r = subprocess.run([sys.executable, '-c', warm], capture_output=True, text=True)
if r.returncode: print('warm-up failed (%s): %s' % (r.returncode, r.stderr.strip()[-300:]), flush=True)

for t in cfg['targets']:
    camp, style = t['campaign'], t['style']
    if a.only and a.only != camp: continue
    if t.get('paused') and a.only != camp: print('skip', camp, '(paused: a ready page waiting for its account)'); continue
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
        if style in NEEDS_PROJECT and not os.path.exists(os.path.join(sd, 'project_hits.json')): continue
        lv = levels(sd)
        sure = stretches(song, t.get('join', 0), sync=_sync.sections_ok(sd)); every = dict(sure)     # lyrics only where they measure as in sync
        if style in VISUAL:                               # the visualiser can use any stretch: where the lyric timing is not proven it simply shows no lyrics
            for sid, win in stretches(song, t.get('join', 0), floor=0.0).items(): every.setdefault(sid, win)
        own = footage_windows(slug) if style in FOOTAGE else {}
        if style in FOOTAGE: every.update(own)
        own_lines = os.path.join(HERE, 'lofi', 'lines', slug + '.json')
        proven = {sid for sid, win in own.items() if _sync.window_ok(sd, win[0], win[1], own_lines if os.path.exists(own_lines) else None)}
        for sid, win in every.items():
            if style in FOOTAGE and lofi_cover(slug, win) < 0.7: continue          # only where the band filmed themselves
            past = sid in own and all(len(v) < (win[0] + win[1]) / 2 for v in lv.values())   # footage beyond where the stems reach (Notta Problem): they are performing, so it suits
            if past or suits(style, playing(lv, win)): cands.append((slug, cr, sid, win, sid in sure or sid in proven))
            else: print('   skip %s %s for %s: %s' % (slug, sid, style, playing(lv, win)))
        LV[slug] = lv
    L = LEARNED.get(camp) or {}
    if t.get('retire'):                                       # options ruled out by hand in nightly.yaml (retire: {knob: [options]})
        ret = {k: list(v) for k, v in (L.get('retired') or {}).items()}
        for knob, opts in t['retire'].items(): ret.setdefault('knob:' + knob, []).extend(opts)
        L = dict(L, retired=ret)
    W = L.get('weights', {}); wsong = W.get('song', {}); wsec = W.get('section', {})
    menu = (rec.get('menu') or {}).get(style) or {}            # every knob this style's renderer has offered so far
    # fewest videos first, but a song or section that gets watched counts as having fewer (so it gets more), and vice versa
    # ... and in the footage styles, where only a few songs have footage and every stretch is new, the song with the
    # fewest videos of this style goes first (Notta Problem lost the same coin toss in every style, every run of a day)
    of_song = {}
    for m in made:
        if m.get('style') == style: of_song[m.get('song')] = of_song.get(m.get('song'), 0) + 1
    rng = random.Random(today + camp + style); rng.shuffle(cands)
    cands.sort(key=lambda c: (of_song.get(c[0], 0) if style in FOOTAGE else 0, (uses.get((c[0], c[2]), 0) + 1) / (wsong.get(c[1], 1.0) * wsec.get('%s/%s' % (c[1], c[2]), 1.0))))
    have = len(rec.get('nightly', []))                       # what the current libraries hold
    want = a.count or max(t['per_night'], min(cfg.get('first_fill_cap', 16), t.get('first_fill', cfg.get('first_fill', 0)) - have) if t['style'] not in VISUAL else t['per_night'])
    picked, per_song = [], {}
    for lap in range(1, 6):                                   # go round the songs so one night is not all one track
        for c in cands:
            if len(picked) >= want: break
            if c not in picked and per_song.get(c[0], 0) < lap: picked.append(c); per_song[c[0]] = per_song.get(c[0], 0) + 1
    jobs, meta, tonight = [], [], []
    for slug, cr, sid, win, lyr in picked:
        seed = rng.randrange(1000, 10 ** 6)
        while seed in seeds: seed = rng.randrange(1000, 10 ** 6)
        kn, extra, how = choose(style, menu, L, seed, frozen_for(style, t, today))
        sub = SUBJECT.get(style)
        past = [(e.get('knobs') or {}).get(sub) for e in rec.get('nightly', []) if e.get('style') == style]
        recent = past[-max(1, t['per_night']) * REPEAT_NIGHTS:] + tonight
        kn = freshen(style, menu, kn, recent, L, random.Random(seed + 2), first=not tonight)
        if kn is None: continue                                 # nothing fresh left tonight: one video fewer, not a repeat
        if style in BANKED: kn = dict(kn, **{sub: fresh_line(style, recent, random.Random(seed + 3))})
        if sub in kn: tonight.append(kn[sub])
        if SET: kn, how = dict(kn, **SET), 'set'                  # a run asked for a particular look (a new format to see now)
        cut = choose_cut(style, how, L, rng, seed)              # how much of the stretch: the whole of it, 10-20s from its strongest line, or a 6-9s loop
        if cut != 'full': win = tighten(os.path.join(HERE, 'songs', slug), win, random.Random(seed), short=cut == 'short')
        if cut == 'short' and style in FOOTAGE: lyr, extra = False, dict(extra, CQ_LOOP='1')   # a 6-9 s loop of the band: no words on it (CQ_LYRICS=none), its last 9 frames fade into frame 0
        seeds.add(seed); inbox = os.path.join(REPO, 'inbox', folder.get(cr, '%s-%s' % (camp, cr)), 'hooks'); os.makedirs(inbox, exist_ok=True)
        out = os.path.join(inbox, '%s_%s_%s_%d.mp4' % (slug, sid, style, seed)); jobs.append((os.path.join(HERE, 'songs', slug), style, seed, out, win, (kn, extra), lyr)); meta.append((cr, slug, sid, cut, how))
    print('== %s: %d videos (%s)' % (camp, len(jobs), style), flush=True)
    with ThreadPoolExecutor(max(1, min(4, os.cpu_count() or 2))) as ex: oks = list(ex.map(render, jobs))
    # A render that crashed beside the others (numpy, OpenCV and ffmpeg each starting a thread per core, four
    # times over) gets one more go on its own, with one thread each, before it counts as a failure.
    for k, job in enumerate(jobs):
        if oks[k] is False:
            print('   retrying %s on its own' % os.path.basename(job[3]), flush=True)
            oks[k] = render(job, solo=True)
    done = set()
    for (cr, slug, sid, cut, how), job, ok in zip(meta, jobs, oks):
        out = job[3]
        if ok is None: continue                                            # skipped by its renderer
        if not ok: failed = True; continue
        r = json.load(open(out[:-4] + '.json')) if os.path.exists(out[:-4] + '.json') else {}
        if os.path.exists(out[:-4] + '.json'): os.remove(out[:-4] + '.json')
        kn = dict(r.get('knobs') or {}, cut=cut)
        for name, opts in (r.get('menu') or {}).items():                  # the menu grows as renderers offer new options
            have = rec.setdefault('menu', {}).setdefault(style, {}).setdefault(name, [])
            have += [o for o in opts if o not in have]
        rec.setdefault('nightly', []).append(dict(date=today, creative=cr, file=os.path.basename(out), song=slug, section=sid, style=style, seed=job[2], window=list(job[4]), plan=r.get('plan'), knobs=kn, chosen=how, playing=playing(LV.get(slug, {}), job[4]), lyrics_proven=bool(job[6]))); done.add(cr)
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
