#!/usr/bin/env python3
"""glitch.archive: NASA's own footage and ours (Rocket League, Nick's New York), clean shots with a datamosh on the cut.

    python studio/glitch_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)

The nightly job's renderer for the "glitch" style (studio/nightly.py). Clips come from the footage library
(studio/footage.py, theme space), our Rocket League library (studio/rocket_lib.py) and our own New York clips (footage
theme nyc, source own; never the archive films, never the band), are surveyed once (motion, contrast, colour, and which
frames are unusable: black, fades, a title card on a plain ground), and are cut on the song's bar lines, no shot under
2 s and the first one at least 3 s, so a launch is seen leaving the pad before the cut. The opener is the liveliest,
most colourful clip, and what it is ("Antares launch, NASA") is written large at the top for its first 2 s
(docs/brain/reviews/2026-11-26: 84% skipped a melting grey crowd nobody could name; space and named things got tested).

The knob `mode` says how much of the video is broken. `transition` (3 in 4): the footage plays clean and only the cut
melts, for half a second, the way a datamosh transition is used everywhere else. `bed` (the old look): every cut is a
datamosh melt, the way a video file breaks when a key frame is lost: the old picture is not replaced
but dragged along the new clip's motion, block by block (16 px macroblocks, as a codec moves them), with the new
picture seeping through, until the next beat, where the clean frame snaps back (the key frame arrives). The video's
last beat melts into its first frame, so frame 0 is already mid-melt and the end runs seamlessly into the start.

In `bed` one main treatment runs over it, picked per video:
  mosh    the melts last two beats, and on kicks the picture "blooms": one frame's motion repeated, so the pixels
          stream on in the direction they were moving, until the next beat
  track   blob tracking: whatever moves gets a box, a crosshair, an ID and coordinates, joined to its neighbour
  sort    pixel sorting: runs of bright pixels sorted down each column into drips of varied length, spreading on
          the snare
  slit    slit-scan: each band of rows shows a different moment (a wave of delays the kick pushes along)
  points  a point cloud: brightness taken as depth, the picture turned in 3D and drawn as dots
accents: rgb (the colour channels drift apart), blocks (macroblock smears on the snare), none;
tones: natural, thermal, mono, duotone, xray, night (duotone, which made a launch mud, only when forced). All are knobs (studio/knobs.py), so the learner finds out which
looks people watch. Text stays out of Instagram's interface (top 250 px, bottom 420 px, right 150 px).
"""
import json, math, os, random, re, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage
import rocket_lib

W, H, FPS = 1080, 1920, 30
# What a video is made of (knob `source`): NASA's footage, our Rocket League clips, or our own New York clips. The
# creeks, forests, cities and Prelinger films went 2026-11-26 (review: 26-72 views against space 83; vintage and cinema
# have the old films). A source with too few clips on this checkout is not offered.
THEMES = ['space', 'rocket', 'nyc']
SOURCE_ODDS = {'space': 3, 'rocket': 2, 'nyc': 2}
MIN_CLIPS = {'space': 6, 'rocket': 4, 'nyc': 4}
OWN = ('space',)                                           # the footage library's themes this account may use (nyc: our own clips only)
MAINS = ['mosh', 'track', 'sort', 'slit', 'points']
ACCENTS = ['rgb', 'blocks', 'none']
TONES = ['natural', 'thermal', 'mono', 'duotone', 'xray', 'night']
TONE_ODDS = [6, 1, 1, 0, 1, 2]                             # natural first; duotone only when nightly forces it
MODES = ['transition', 'bed']
TRANSITION = 15                                            # frames a cut melts for in mode `transition` (0.5 s)
MIN_SHOT, FIRST_SHOT = 60, 90                              # frames: no shot under 2 s, the first at least 3 s
TITLE_FRAMES = 60                                          # the opener's name is up for the first 2 s
# What each clip is, said the way a person would (the index's titles are file names). First match wins; a space clip
# matching none is named from its title.
NAMES = [(r'artemis ii', 'Artemis II launch, NASA'), (r'antares', 'Antares launch, NASA'),
         (r'titan ii', 'NOAA-M on a Titan II, NASA'), (r'galileo flyby', 'Earth seen by Galileo, 1990'),
         (r'earth views from the international space station|earth day 2017', 'Earth from the space station, NASA'),
         (r'earth from orbit', 'Earth from orbit, NASA'), (r'aurora time lapse', 'Aurora over Alaska, NASA')]
# Films in the library that are not material for this account, found by looking at every clip (2026-11-24): presenters
# and talking heads, explainer graphics with captions, sponsor films (brand logos, a car-company cartoon mascot), a
# slaughterhouse, ribbon-cuttings with officials, the escalator of a living politician's tower, broadcaster logos.
SKIP_TITLE = re.compile(r'space station live|space to ground|space zinnias|asked a nasa expert|what is space weather|'
                        r'uncovering winter|airborne cold weather|forest dynamics|forest fires or game|golden escalator|'
                        r'beef rings the bell|coach for cinderella|achievement usa|roll-oh|wood chopping|radio transmitter|'
                        r'inauguration|dedication|highway 101 opening|cargo ship backup|earth at night seen from space|'
                        r'marine snow|nexans|shortest escalators|your fire department|aurora 7|earth from outer space|sounding rocket', re.I)
SKIP_ASSET = {'78c9f9f1aa71d547.mp4', 'b746123e96794085.mp4',      # Artemis II: the crew with their names on screen
              '1720051a1fa6d2a8.mp4'}                              # NASA Earth from Orbit 2012: ozone map with dates
QW, QH = W // 4, H // 4                                            # motion is measured at quarter size
HW, HH = W // 2, H // 2                                            # the moshed picture lives at half size
SAFE_TOP, SAFE_BOTTOM, SAFE_RIGHT = 250, 420, 150


def font(size):
    for p in (os.path.join(REPO, 'fonts', 'DejaVuSansMono-Bold.ttf'), '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class Clips:
    """The footage, cut on bar lines: which clip plays when, and its frames, cropped to the vertical frame.
    (Kept as it was for nyc_video.py and cutout_video.py; glitch itself uses Plan below.)"""
    def __init__(self, entries, n, spb, bars_per_cut, rng):
        self.rng = rng; self.cache = {}
        step = max(1, int(round(bars_per_cut * 4 * spb * FPS)))
        self.cuts = list(range(0, n, step))
        pool = entries[:]; rng.shuffle(pool)
        self.plan = []
        for k, c in enumerate(self.cuts):
            e = pool[k % len(pool)]; cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset']))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 300; cap.release()
            seg = (self.cuts[k + 1] if k + 1 < len(self.cuts) else n) - c
            self.plan.append((c, e, rng.randrange(0, max(1, total - seg)), rng.uniform(1.0, 1.12), rng.uniform(-0.15, 0.15)))

    def segment(self, i):
        k = max(j for j, (c, *_r) in enumerate(self.plan) if c <= i); return k, self.plan[k]

    def frame(self, i):
        k, (c, e, off, zoom, pan) = self.segment(i)
        if k not in self.cache:                                   # read a segment's frames once
            for old in [j for j in self.cache if j < k - 1]: del self.cache[old]
            cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset'])); cap.set(cv2.CAP_PROP_POS_FRAMES, off); fr = []
            seg = (self.plan[k + 1][0] if k + 1 < len(self.plan) else c + 10 ** 6) - c
            while len(fr) < min(seg, 400):
                ok, f = cap.read()
                if not ok:
                    if not fr: break
                    fr += fr[::-1]; continue                       # a short clip plays forward then back
                fr.append(f)
            cap.release(); self.cache[k] = fr or [np.zeros((H, W, 3), np.uint8)]
        fr = self.cache[k]; f = fr[min(i - c, len(fr) - 1)]
        h, w = f.shape[:2]; s = max(W / w, H / h) * zoom * (1 + 0.04 * (i - c) / max(1, len(fr)))   # slow push-in
        f = cv2.resize(f, (int(w * s) + 1, int(h * s) + 1), interpolation=cv2.INTER_LINEAR)
        x0 = int((f.shape[1] - W) * (0.5 + pan)); y0 = (f.shape[0] - H) // 2
        return np.ascontiguousarray(f[y0:y0 + H, max(0, min(x0, f.shape[1] - W)):][:, :W]), k, e


# ------------------------------------------------------------------------------------------------ the footage
def usable(e):
    """A clip this account may show: not ruled out by footage.BLOCK (checked here too, so a blocked clip still in the
    index or the cache never gets in), not one of the films above, and NASA's (theme space) or our own New York clips."""
    words = '%s %s %s' % (e.get('title', ''), e.get('key', ''), e.get('query', ''))
    ours = e.get('theme') == 'nyc' and e.get('source') == 'own'
    return ((e.get('theme') in OWN or ours) and not footage.BLOCK.search(words) and not SKIP_TITLE.search(words)
            and e.get('asset') not in SKIP_ASSET)


def path_of(e):
    return e.get('path') or os.path.join(footage.CACHE, e['asset'])


def _places():
    try: return json.load(open(os.path.join(HERE, 'nyc', 'places.json')))['clips']
    except (OSError, ValueError, KeyError): return {}


def own_nyc():
    """The library's own New York clips (Nick's, theme nyc, source own) that places.json does not skip."""
    skip = {k for k, v in _places().items() if v.get('skip')}
    return [e for e in footage.index().get('clips', []) if e.get('theme') == 'nyc' and e.get('source') == 'own'
            and e['asset'] not in skip and usable(e)]


def library(theme):
    """The clips of one source on this machine (pulled from their release when missing)."""
    if theme == 'rocket':                                  # our Rocket League recordings (rocket.league.lit's library)
        try: clips = rocket_lib.pull()
        except Exception: clips = [c for c in rocket_lib.index()['clips'] if os.path.exists(os.path.join(rocket_lib.CACHE, c['asset']))]
        return [dict(c, theme='rocket', title='Rocket League', key='rocket:' + c['asset'], film=c['asset'],
                     path=os.path.join(rocket_lib.CACHE, c['asset'])) for c in clips]
    if theme == 'nyc':
        own = [e['asset'] for e in own_nyc()]
        if not own: return []
        try: got = footage.pull(('nyc',), assets=own)
        except Exception: got = [e for e in own_nyc() if os.path.exists(path_of(e))]
        return [dict(e, film=e['asset']) for e in got if e['asset'] in own]
    try: got = footage.pull(OWN)
    except Exception: got = [e for e in footage.index().get('clips', []) if e.get('theme') in OWN and os.path.exists(path_of(e))]
    return [e for e in got if usable(e)]


def name(e):
    """What a clip is, for the title line: 'Antares launch, NASA', 'Rocket League, our clip', 'Central Park'."""
    if e.get('theme') == 'rocket': return 'Rocket League, our clip'
    if e.get('theme') == 'nyc': return (_places().get(e['asset']) or {}).get('place') or 'New York, our own footage'
    t = e.get('title', '')
    for pat, nm in NAMES:
        if re.search(pat, t, re.I): return nm
    f = re.sub(r'\s*\(.*?\)|\b(4K|UHD|HD)\b', '', film(e)).strip(' -')
    f = f[:36].rsplit(' ', 1)[0] if len(f) > 36 else f
    return f + ('' if 'nasa' in f.lower() else ', NASA')


def survey(e):
    """Per-frame facts about one clip, read once at low size: movement, contrast, colour, which frames are unusable
    (black, a fade, a title card on a plain ground), and the crop that removes black bars baked into the copy."""
    memo = os.path.join(footage.CACHE, e['asset'] + '.glitch.json')       # every source's memo here: the footage cache is git-ignored
    try:
        s = json.load(open(memo))
        return dict(s, mot=np.array(s['mot']), con=np.array(s['con']), bad=np.array(s['bad'], bool), crop=tuple(s['crop']))
    except (OSError, ValueError, KeyError): pass
    cap = cv2.VideoCapture(path_of(e)); prev = None; mot, con, bad, sat = [], [], [], []
    acc = None; size = None
    while True:
        ok, f = cap.read()
        if not ok: break
        size = f.shape[:2]; sm = cv2.resize(f, (320, 180), interpolation=cv2.INTER_AREA)
        g = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        acc = g.copy() if acc is None else np.maximum(acc, g)
        mot.append(0.0 if prev is None else float(np.abs(g - prev).mean())); prev = g
        con.append(float(g.std()))
        if len(mot) % 4 == 1:
            sat.append(float(cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)[..., 1].mean() / 255))
        card = False
        if len(mot) % 4 == 1:                                     # cards last seconds: every 4th frame is enough
            bg = cv2.medianBlur((g * 255).astype(np.uint8), 21).astype(np.float32) / 255
            card = bg[20:-20, 20:-20].std() < 0.12 and (((bg - g) > 0.25).mean() > 0.02 or ((g - bg) > 0.25).mean() > 0.02)
        bad.append(bool(card or g.mean() < 0.07 or g.std() < 0.045))
    cap.release()
    n = len(mot)
    if n < 20: return None
    mot = np.array(mot); mot[0] = mot[1]
    bad = np.convolve(np.array(bad, float), np.ones(13), 'same') > 0        # and a few frames either side (the fade into a card)
    cols = np.where(acc.max(0) > 0.12)[0]; rows = np.where(acc.max(1) > 0.12)[0]
    h, w = size
    if len(cols) > 40 and len(rows) > 40:
        pad = 0.012 * w
        crop = (int(cols[0] / 320 * w + pad), int(rows[0] / 180 * h + pad), int((cols[-1] + 1) / 320 * w - pad), int((rows[-1] + 1) / 180 * h - pad))
    else: crop = (0, 0, w, h)
    out = dict(n=n, mot=mot, con=np.array(con), bad=bad, crop=crop, sat=float(np.mean(sat)) if sat else 0.0)
    try: os.makedirs(footage.CACHE, exist_ok=True); json.dump(dict(out, mot=[round(float(x), 5) for x in mot], con=[round(float(x), 4) for x in out['con']], bad=[bool(x) for x in bad], crop=list(crop)), open(memo, 'w'))
    except OSError: pass
    return out


def best_window(s, L, rng, lead=0):
    """The start of one of the liveliest L-frame stretches with `lead` clean frames before it (None if there is none)."""
    n = s['n']; L = max(1, min(L, n - lead))
    cs = np.concatenate([[0], np.cumsum(s['mot'])]); bs = np.concatenate([[0], np.cumsum(s['bad'])])
    starts = np.arange(lead, n - L + 1)
    if not len(starts): return None
    ok = (bs[starts + L] - bs[starts - lead]) == 0
    if not ok.any(): return None
    score = np.where(ok, (cs[starts + L] - cs[starts]) / L, -1)
    top = [int(t) for t in np.argsort(score)[::-1][:3] if score[t] >= 0]
    return int(starts[rng.choice(top)])


def window(e, s, L, rng, lead=0):
    """best_window, except that a clip with known moments (our Rocket League clips) is placed so its biggest moment
    lands 60% of the way into the shot: the goal is seen, not cut away from."""
    for t, _score in (e.get('moments') or [])[:1]:
        n = s['n']; L2 = max(1, min(L, n - lead)); off = int(round(t * FPS - 0.6 * L2))
        off = max(lead, min(off, n - L2))
        if not s['bad'][max(0, off - lead):off + L2].any(): return off
    return best_window(s, L, rng, lead)


def film(e):
    if e.get('film'): return e['film']                                 # our own clips: each clip is its own "film"
    t = re.sub(r'\.(webm|ogv|ogg|mp4)$', '', e.get('title', ''), flags=re.I)
    t = re.sub(r'\s*\((\d{6,}|PIA\d+|SVS\d+)\)|\[|\]|\s*\(Part [IV]+\)', '', t)
    return re.sub(r'\s+', ' ', t).strip()


class Plan:
    """Which clip plays when and from which frame, cut on the song's bar lines. The opener is the liveliest, most
    colourful clip (and has `lead` clean frames before its window, which the end of the video melts through)."""
    def __init__(self, lib, n, cuts, rng, lead, motion_first=False):
        self.n = n; self.cache = {}; pool = lib[:]; rng.shuffle(pool); stats = {}
        need = len(cuts) + 10
        for e in pool:
            s = survey(e)
            if s and s['bad'].mean() < 0.6 and float(np.median(s['mot'])) > 0.004: stats[e['asset']] = s
            if len(stats) >= need: break
        lib = [e for e in pool if e['asset'] in stats]
        if not lib: sys.exit('no usable clips in the footage library')
        self.stats = stats
        segs = [(c, (cuts[k + 1] if k + 1 < len(cuts) else n) - c) for k, c in enumerate(cuts)]
        mot = {e['asset']: float(np.median(stats[e['asset']]['mot'])) for e in lib}
        hooks = []
        for e in lib:
            s = stats[e['asset']]; off = window(e, s, segs[0][1], random.Random(1), lead)
            if off is None: continue
            score = float(s['mot'][off:off + 15].mean()) * float(s['con'][off:off + 15].mean()) * (0.5 + s['sat'])
            hooks.append((score, e, off))
        hooks.sort(key=lambda h: -h[0]); best = []
        for h in hooks:
            if film(h[1]) not in [film(b[1]) for b in best]: best.append(h)
        if not best: sys.exit('no clip can open the video')
        _, first, off0 = rng.choice(best[:3])
        self.plan = [(0, first, off0, rng.uniform(1.0, 1.1), rng.uniform(-0.2, 0.2))]; used = {first['asset']}; last = film(first)
        for k, (c, L) in enumerate(segs[1:], 1):
            others = [e for e in lib if film(e) != film(first)] if k == len(segs) - 1 else lib     # the end melts into the opener: not the same film
            pool = [e for e in others if film(e) != last and e['asset'] not in used] or [e for e in others if film(e) != last] or lib
            e, off = first, None
            for _ in range(6):
                w = [(mot[x['asset']] if motion_first else mot[x['asset']] ** 0.5) + 1e-4 for x in pool]
                e = rng.choices(pool, weights=w)[0]; off = window(e, stats[e['asset']], L, rng)
                if off is not None: break
            if off is None: e, off = first, off0
            self.plan.append((c, e, off, rng.uniform(1.0, 1.1), rng.uniform(-0.2, 0.2))); used.add(e['asset']); last = film(e)
        self.lead = lead; self.lead_frames = None

    def segment(self, i):
        k = max(j for j, p in enumerate(self.plan) if p[0] <= i); return k, self.plan[k]

    def _read(self, e, off, count, zoom, pan):
        """count frames from off, cropped to the 9:16 picture at the clip's own size (the bars cut off first)."""
        x0, y0, x1, y1 = self.stats[e['asset']]['crop']
        cap = cv2.VideoCapture(path_of(e)); cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, off)); fr = []
        while len(fr) < min(count, 400):
            ok, f = cap.read()
            if not ok or f is None or not f.size:
                if not fr: break
                fr += fr[::-1]; continue                                  # a short clip plays forward then back
            f = f[y0:y1, x0:x1] if f[y0:y1, x0:x1].size else f              # a crop surveyed on another copy: the whole frame
            h, w = f.shape[:2]
            ch, cw = h / zoom, min(w, h * 9 / 16) / zoom
            cx = (w - cw) * (0.5 + pan); cy = (h - ch) / 2
            fr.append(np.ascontiguousarray(f[int(cy):int(cy + ch), int(cx):int(cx + cw)]))
        cap.release()
        return fr or [np.zeros((160, 90, 3), np.uint8)]                    # an unreadable clip: black, never an empty array (cv2.remap crashed on one)

    def frames(self, k):
        if k not in self.cache:
            for old in [j for j in self.cache if j != k and j != k - 1]: del self.cache[old]
            c, e, off, zoom, pan = self.plan[k]
            seg = (self.plan[k + 1][0] if k + 1 < len(self.plan) else self.n) - c
            self.cache[k] = self._read(e, off, seg + 1, zoom, pan)
        return self.cache[k]

    @staticmethod
    def fill(f, push):
        h, w = f.shape[:2]; s = 1 + push
        ch, cw = h / s, w / s; y0, x0 = (h - ch) / 2, (w - cw) / 2
        f = f[int(y0):int(y0 + ch), int(x0):int(x0 + cw)]
        return cv2.resize(f, (W, H), interpolation=cv2.INTER_LINEAR)

    def raw(self, i):
        """Frame i of the footage, full size, with a slow push-in through each shot."""
        k, (c, *_r) = self.segment(i); fr = self.frames(k); j = min(i - c, len(fr) - 1)
        return self.fill(fr[j], 0.05 * j / max(1, len(fr))), k

    def leadin(self, j):
        """The opener's j-th frame of the `lead` frames before its window (the end of the video melts through these)."""
        if self.lead_frames is None:
            _c, e, off, zoom, pan = self.plan[0]
            self.lead_frames = self._read(e, off - self.lead, self.lead, zoom, pan)
        return self.fill(self.lead_frames[min(j, len(self.lead_frames) - 1)], 0.0)


# ------------------------------------------------------------------------------------------------ motion
GX, GY = np.meshgrid(np.arange(HW, dtype=np.float32), np.arange(HH, dtype=np.float32))


def qgray(img):
    return cv2.cvtColor(cv2.resize(img, (QW, QH), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)


def block_flow(a, b):
    """The motion from a to b (quarter-size grey frames) as a codec would store it: one vector per 16 px macroblock,
    returned at half size in half-size pixels."""
    f = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    f = cv2.resize(f, (QW // 4, QH // 4), interpolation=cv2.INTER_AREA)
    return cv2.resize(f, (HW, HH), interpolation=cv2.INTER_NEAREST) * 2.0


def push(acc, fl):
    return cv2.remap(acc, GX - fl[..., 0], GY - fl[..., 1], cv2.INTER_NEAREST, borderMode=cv2.BORDER_REFLECT)   # nearest: pixels move whole, edges stay hard (a codec does not blur)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        libs = {t: library(t) for t in THEMES}
        have = [t for t in THEMES if len(libs[t]) >= MIN_CLIPS[t]] or [t for t in THEMES if libs[t]]
        if not have: sys.exit('the footage library is empty: run the footage workflow (and rocket_lib.py pull) first')
        self.theme = K.pick('source', have, r, weights=[SOURCE_ODDS[t] for t in have])
        # transition: clean shots, half a second of mosh on each cut; bed: the old 15 s of melt (the learner compares them)
        self.mode_kind = K.pick('mode', MODES, r, weights=[3, 1])
        self.main = K.pick('main', MAINS, r) if self.mode_kind == 'bed' else 'mosh'
        # the first frame: a clean, readable shot (the melt starts on the first cut) or mid-melt so the loop has no seam.
        # Glitch had the highest early skip on the network (85%, 2026-11-25) and every frame 0 was unreadable mush.
        self.opener = K.pick('opener', ['clean', 'melt'], r, weights=[3, 1]) if self.mode_kind == 'bed' else 'clean'
        self.accent = K.pick('accent', ACCENTS, r); self.tone = K.pick('tone', TONES, r, weights=TONE_ODDS)
        self.pace = int(K.pick('pace', [1, 2], r, weights=[1, 3])); self.label = K.pick('label', ['rec', 'none'], r)
        lib = libs[self.theme]
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        P = audio.project(self.slug, t0, t1)                                  # the song's own hits where it has a project
        kicks = [int(round(t * FPS)) for t, _s in (P or {}).get('kick', [])] or [int(k) for k in a['kicks']]
        snares = [int(round(t * FPS)) for t, _s in (P or {}).get('snare', [])] or [int(k) for k in a['snares']]
        self.kicks = set(k for k in kicks if 0 <= k < n)
        self.kick = audio.hits(sorted(self.kicks), n, 6.0); self.snare = audio.hits([s for s in snares if 0 <= s < n], n, 8.0)
        self.bass = np.convolve(a['bass'], np.ones(5) / 5, 'same')
        beats = [(b, int(round(f))) for b, f in a['beats'] if 0 <= f < n]
        self.beat_frames = sorted(f for _b, f in beats)
        # cuts on bar lines (every bar, or every other), no shot under MIN_SHOT and the first at least FIRST_SHOT: with
        # pace 1 the Antares rocket was cut away before it left the pad (review 2026-11-26)
        bar = 4 * self.pace
        cuts = [0]
        for b, f in beats:
            if b % bar == 0 and f >= cuts[-1] + (FIRST_SHOT if len(cuts) == 1 else MIN_SHOT) and f <= n - 24: cuts.append(f)
        # the seam: from the last beat (8-24 frames before the end) the picture melts into the opening frame
        last = [f for f in self.beat_frames if 8 <= n - f <= 24]
        self.seam = last[-1] if last else n - 12
        while len(cuts) > 1 and cuts[-1] > self.seam - MIN_SHOT: cuts.pop()
        self.lead = n - self.seam
        self.plan = Plan(lib, n, cuts, r, self.lead, motion_first=self.main in ('mosh', 'slit'))
        self.cuts = set(c for c, *_r in self.plan.plan)
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.f_rec, self.f_lab, self.f_box = font(34), font(27), font(28)
        sans = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/Library/Fonts/Arial Unicode.ttf') if os.path.exists(p)), None)
        self.f_credit = ImageFont.truetype(sans, 30) if sans else self.f_lab
        bold = next((p for p in (os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf'), '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf') if os.path.exists(p)), None)
        self.f_title = ImageFont.truetype(bold, 56) if bold else self.f_rec
        self.title = name(self.plan.plan[0][1])
        self.buf = []; self.tracks = {}; self.next_id = 1; self.dropped = 0
        self.mode = None; self.acc = None; self.until = 0; self.F = None
        self.preroll()

    # ---------------------------------------------------------------- the mosh engine
    def snap_after(self, i, beats_min):
        """The frame the clean picture comes back on: a beat at least beats_min beats after i, before the seam."""
        lo = i + max(4, int(beats_min * self.spb * FPS) - 2)
        f = next((b for b in self.beat_frames if b >= lo), lo + int(self.spb * FPS))
        return min(f, self.seam - 1) if i < self.seam else self.n

    def preroll(self):
        """Run the end-of-video melt once, so frame 0 starts where the last frame leaves off: mid-melt."""
        if self.opener == 'clean':                                     # open on the plain picture; the seam melts back into it
            self.mode = None; self.prev_g = qgray(self.plan.raw(0)[0]); self._clean_from = 0; return
        self.mode, self.acc = 'melt', cv2.resize(self.plan.raw(self.seam - 1)[0], (HW, HH), interpolation=cv2.INTER_AREA).astype(np.float32)
        prev = None
        for j in range(self.lead):
            cur = self.plan.leadin(j); g = qgray(cur)
            a, b = (g, qgray(self.plan.leadin(1))) if j == 0 else (prev, g)    # the first step borrows the next frame's motion
            self.melt_step(self.seam + j, cur, a, b); prev = g
        self.prev_g = prev
        self.until = self.snap_after(0, 0.5); self.dropped = 1

    def melt_step(self, i, cur, a, b):
        fl = block_flow(a, b); m = float(np.median(np.hypot(fl[..., 0], fl[..., 1])))
        fl *= min(6.0, max(float(1.6 + 1.2 * self.bass[i]), 1.8 / max(m, 1e-3)))   # slow shots still drag: a melt never reads as a dissolve
        half = cv2.resize(cur, (HW, HH), interpolation=cv2.INTER_AREA).astype(np.float32)
        # the new picture comes through only where it moves (a P-frame's residual), not everywhere at once
        seep = np.clip(np.hypot(fl[..., 0], fl[..., 1]) / 12.0, 0.0, 0.08)[..., None] + 0.006
        self.acc = push(self.acc, fl) * (1 - seep) + half * seep

    def base(self, i):
        """Frame i before treatment: the clean footage, or the datamosh while a melt or bloom is running."""
        seam = i >= self.seam
        cur, k = (self.plan.leadin(i - self.seam), None) if seam else self.plan.raw(i)
        g = qgray(cur)
        if i == self.seam:                                                 # the same melt the preroll ran: the loop closes
            self.mode = 'melt'; self.dropped += 1; self.until = self.n
            self.acc = cv2.resize(self.plan.raw(self.seam - 1)[0], (HW, HH), interpolation=cv2.INTER_AREA).astype(np.float32)
            self.melt_step(i, cur, g, qgray(self.plan.leadin(1))); self.prev_g = g
            return cv2.resize(self.acc, (W, H)), cur
        if i > 0 and not seam and i in self.cuts:                          # a cut: the key frame is lost
            if self.mode is None or self.acc is None:                      # the old picture is the last clean frame (it was None
                self.acc = cv2.resize(self.plan.raw(i - 1)[0], (HW, HH), interpolation=cv2.INTER_AREA).astype(np.float32)   # after a clean opener: the remap crash)
            self.mode = 'melt'; self.dropped += 1
            if self.mode_kind == 'transition':                             # half a second, back on a beat when one is near
                self.until = next((b for b in self.beat_frames if i + 10 <= b <= i + 20), i + TRANSITION)
            else: self.until = self.snap_after(i, 2 if self.main == 'mosh' else 1)
            nxt = qgray(self.plan.raw(i + 1)[0]) if i + 1 < self.seam else g
            self.melt_step(i, cur, g, nxt); self.prev_g = g
            return cv2.resize(self.acc, (W, H)), cur
        if self.mode and i >= self.until: self.mode = None; self._clean_from = i   # the key frame arrives, on the beat
        beat = self.spb * FPS
        if (self.main == 'mosh' and self.mode_kind == 'bed' and self.mode is None and i in self.kicks and not seam and i > 8
                and i - getattr(self, '_clean_from', 0) >= beat - 2 and getattr(self, '_bloomed', None) != k
                and self.r.random() < 0.6):                                # at most one bloom a shot, a beat after the snap
            nxt_cut = min([c for c in self.cuts if c > i] + [self.seam])
            if nxt_cut - i > beat - 2:
                self._bloomed = k                                           # a bloom: this frame's motion, again and again
                F = block_flow(self.prev_g, g); m = float(np.median(np.hypot(F[..., 0], F[..., 1])))
                self.F = F * min(4.0, max(1.0, 1.6 / max(m, 1e-3)))
                self.mode = 'bloom'; self.until = min(self.snap_after(i, 1), nxt_cut - 1)
                self.acc = cv2.resize(cur, (HW, HH), interpolation=cv2.INTER_AREA).astype(np.float32)
        if self.mode == 'melt': self.melt_step(i, cur, self.prev_g, g)
        elif self.mode == 'bloom':
            half = cv2.resize(cur, (HW, HH), interpolation=cv2.INTER_AREA).astype(np.float32)
            self.acc = push(self.acc, self.F) * 0.985 + half * 0.015
        self.prev_g = g
        if self.mode: return cv2.resize(self.acc, (W, H)), cur
        return cur.astype(np.float32), cur

    # ---------------------------------------------------------------- treatments
    def track(self, f, cur, i):
        self.boxes = {}
        g = cv2.cvtColor(cv2.resize(cur, (W // 6, H // 6)), cv2.COLOR_BGR2GRAY)
        pg = getattr(self, '_tg', None); self._tg = g
        if pg is None: return f
        m = cv2.GaussianBlur(cv2.absdiff(g, pg), (0, 0), 2.5); m = (m > max(7, np.percentile(m, 94))).astype(np.uint8)
        m = cv2.dilate(m, np.ones((7, 7), np.uint8))
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [b for b in (cv2.boundingRect(c) for c in cs) if b[2] * b[3] >= 60]
        boxes = sorted(boxes, key=lambda b: -b[2] * b[3])[:int(4 + 3 * self.snare[i])]
        new = {}
        for (x, y, w, h) in boxes:                                        # a box keeps the ID of the nearest box last frame
            cx, cy = (x + w / 2) * 6, (y + h / 2) * 6
            best = min(self.tracks.items(), key=lambda kv: (kv[1][0] - cx) ** 2 + (kv[1][1] - cy) ** 2, default=None)
            if best and (best[1][0] - cx) ** 2 + (best[1][1] - cy) ** 2 < 160 ** 2 and best[0] not in new: tid = best[0]
            else: tid = self.next_id; self.next_id += 1
            new[tid] = (cx, cy, x * 6, y * 6, w * 6, h * 6)
        self.tracks = new; self.boxes = new
        return f

    def draw_tracks(self, d, i):
        bs = getattr(self, 'boxes', {}) or {}
        flash = self.snare[i] > 0.5
        pts = list(bs.items())
        for tid, (cx, cy, *_r) in pts:                                     # each box to its nearest neighbour
            near = min((v for t, v in pts if t != tid), key=lambda v: (v[0] - cx) ** 2 + (v[1] - cy) ** 2, default=None)
            if near: d.line([(cx, cy), (near[0], near[1])], fill=(255, 255, 255), width=2)
        for tid, (cx, cy, x, y, w, h) in pts:
            col = (255, 60, 60) if flash and tid % 2 else (255, 255, 255)
            L = max(18, int(min(w, h) * 0.22))                                # corner brackets, not a full box
            for sx, sy, dx, dy in ((x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)):
                d.line([(sx, sy), (sx + dx * L, sy)], fill=col, width=4); d.line([(sx, sy), (sx, sy + dy * L)], fill=col, width=4)
            d.line([cx - 16, cy, cx + 16, cy], fill=col, width=3); d.line([cx, cy - 16, cx, cy + 16], fill=col, width=3)
            txt = 'ID%02d %.2f %.2f' % (tid % 100, cx / W, cy / H)
            tx, ty = min(max(x, 12), W - SAFE_RIGHT - 300), y - 36 if y > 60 else y + h + 6
            bb = d.textbbox((tx, ty), txt, font=self.f_box)
            d.rectangle([bb[0] - 4, bb[1] - 3, bb[2] + 4, bb[3] + 3], fill=(0, 0, 0)); d.text((tx, ty), txt, font=self.f_box, fill=col)

    def sort(self, f, i):
        amt = min(1.0, 0.3 + 0.55 * self.snare[i] + 0.3 * self.bass[i])
        s = cv2.resize(np.clip(f, 0, 255).astype(np.uint8), (HW, HH), interpolation=cv2.INTER_AREA)
        lum = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY).astype(np.float32)
        thr = np.percentile(lum, 80 - 45 * amt)                          # the bright part of the picture melts; more on the snare
        mask = lum > thr
        # runs are capped at varied lengths per column, so the drips are not all one length
        rng = np.random.default_rng(1234); cap = rng.integers(40, 260, HW)
        brk = (np.arange(HH)[:, None] + rng.integers(0, 260, HW)[None, :]) % cap[None, :] == 0
        run = np.cumsum(~mask | brk, axis=0)
        key = run * 512.0 + np.where(mask, lum, -1.0)
        order = np.argsort(key, axis=0, kind='stable')
        out = np.take_along_axis(s, order[..., None], axis=0)
        return cv2.resize(out, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32)

    def slit(self, f, i):
        self.buf.append(cv2.resize(np.clip(f, 0, 255).astype(np.uint8), (HW, HH), interpolation=cv2.INTER_AREA))
        depth = 40
        if len(self.buf) > depth: self.buf.pop(0)
        n = len(self.buf); rows = np.arange(HH)
        phase = getattr(self, '_ph', 0.0) + 0.04 + 0.5 * (i in self.kicks); self._ph = phase
        d = 0.5 + 0.5 * np.sin(rows / HH * 2 * math.pi * 1.3 + phase)        # a wave of delays down the frame
        idx = np.clip((n - 1) - (d * (n - 1) * (0.5 + 0.5 * min(1.0, self.bass[i]))).astype(int), 0, n - 1)
        out = np.stack(self.buf)[idx, rows]
        return cv2.resize(out, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32)

    def points(self, f, i):
        s = cv2.resize(np.clip(f, 0, 255).astype(np.uint8), (W // 6, H // 6)); lum = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        z = cv2.GaussianBlur(lum, (0, 0), 1.5) * (1.6 + 1.2 * self.bass[i])
        yy, xx = np.mgrid[0:s.shape[0], 0:s.shape[1]].astype(np.float32)
        X = (xx - s.shape[1] / 2) * 6; Y = (yy - s.shape[0] / 2) * 6; Z = (z - 0.5) * 520
        t = i / FPS; ay = 0.35 * math.sin(t * 0.5) + 0.12 * self.kick[i]; ax = 0.25 + 0.1 * math.sin(t * 0.3)
        X2 = X * math.cos(ay) + Z * math.sin(ay); Z2 = -X * math.sin(ay) + Z * math.cos(ay)
        Y2 = Y * math.cos(ax) - Z2 * math.sin(ax); Z3 = Y * math.sin(ax) + Z2 * math.cos(ax)
        p = 1400 / (1400 + Z3); u = (W / 2 + X2 * p).astype(int); v = (H / 2 + Y2 * p).astype(int)
        ok = (u >= 0) & (u < W - 2) & (v >= 0) & (v < H - 2) & (lum > 0.08)
        out = np.zeros((H, W, 3), np.float32); col = s.astype(np.float32)[ok] * 1.3
        for dy in (0, 1):
            for dx in (0, 1): out[v[ok] + dy, u[ok] + dx] = col
        return out + cv2.GaussianBlur(out, (0, 0), 6) * 0.6

    # ---------------------------------------------------------------- accents and tones
    def accent_fx(self, img, i):
        if self.accent == 'rgb':
            sh = int(6 + 22 * self.kick[i] + 10 * self.bass[i])
            img = img.copy(); img[..., 2] = np.roll(img[..., 2], sh, axis=1); img[..., 0] = np.roll(img[..., 0], -sh, axis=1)
        elif self.accent == 'blocks' and self.snare[i] > 0.35:
            r = np.random.default_rng(i); img = img.copy()
            for _ in range(int(30 * self.snare[i])):
                bw, bh = r.choice([32, 64, 128]), r.choice([16, 32, 64]); x, y = r.integers(0, W - bw), r.integers(0, H - bh)
                sx, sy = int(np.clip(x + r.integers(-120, 120), 0, W - bw)), int(np.clip(y + r.integers(-40, 40), 0, H - bh))
                img[y:y + bh, x:x + bw] = img[sy:sy + bh, sx:sx + bw] if r.random() < 0.6 else img[y:y + 1, x:x + bw]   # moved, or smeared down
        return img

    def tone_fx(self, img):
        u8 = np.clip(img, 0, 255).astype(np.uint8)
        if self.tone == 'natural': return img
        g = cv2.cvtColor(u8, cv2.COLOR_BGR2GRAY)
        if self.tone == 'thermal': return cv2.applyColorMap(g, cv2.COLORMAP_INFERNO).astype(np.float32)
        if self.tone == 'mono': return cv2.cvtColor(cv2.createCLAHE(2.5, (8, 8)).apply(g), cv2.COLOR_GRAY2BGR).astype(np.float32)
        if self.tone == 'xray': return cv2.cvtColor(255 - g, cv2.COLOR_GRAY2BGR).astype(np.float32) * np.array([1.0, 0.95, 0.85])
        if self.tone == 'night': return (np.stack([g * 0.25, g * 1.0, g * 0.35], -1) * 1.1).astype(np.float32)
        lo, hi = np.array([60, 20, 30], np.float32), np.array([120, 230, 255], np.float32)     # duotone: deep blue to warm white (BGR)
        x = (g.astype(np.float32) / 255)[..., None]; return lo * (1 - x) + hi * x

    def frame(self, i):
        f, cur = self.base(i)
        if self.main == 'track': img = self.track(f, cur, i)
        elif self.main in ('sort', 'slit', 'points'): img = getattr(self, self.main)(f, i)
        else: img = f
        img = self.tone_fx(self.accent_fx(img, i) if self.mode_kind == 'bed' or self.mode else img)   # transition: the accent is part of the cut
        img = img * (1 + 0.12 * self.kick[i])                              # a little lift on the kick
        g = np.random.default_rng(i).normal(0, 6, (H // 4, W // 4)).astype(np.float32)
        img = img + cv2.resize(g, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]   # grain
        out = Image.fromarray(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(out)
        if self.main == 'track': self.draw_tracks(d, i)
        if i < TITLE_FRAMES: self.draw_title(d, i)                         # what this is, for the first 2 s
        elif self.label == 'rec':                                          # below Instagram's top bar
            e = self.plan.plan[0][1] if i >= self.seam else self.plan.segment(i)[1][1]
            t = self.t0 + i / FPS; y = SAFE_TOP + 16
            if (i // 15) % 2 == 0: d.ellipse([96, y + 6, 122, y + 32], fill=(230, 40, 40))
            kw = dict(stroke_width=3, stroke_fill=(0, 0, 0))
            d.text((136, y), 'REC  %02d:%02d:%02d' % (t // 60, t % 60, (i % FPS)), font=self.f_rec, fill=(245, 245, 245), **kw)
            d.text((96, y + 50), ('SRC  ' + name(e))[:44], font=self.f_lab, fill=(225, 225, 225), **kw)
            d.text((96, y + 88), 'KEYFRAMES DROPPED  %02d' % self.dropped, font=self.f_lab, fill=(225, 225, 225), **kw)
        d.text((96, H - SAFE_BOTTOM - 24), self.credit, font=self.f_credit, fill=(240, 240, 240), anchor='ls', stroke_width=3, stroke_fill=(0, 0, 0))
        return np.asarray(out)

    def draw_title(self, d, i):
        """The opener's name, large, white on a heavy black outline, inside y 250-420 and x 96-924 (two lines at most)."""
        words, rows = self.title.split(), ['']
        for w in words:
            t = (rows[-1] + ' ' + w).strip()
            if d.textlength(t, font=self.f_title) <= 924 - 96 or not rows[-1]: rows[-1] = t
            else: rows.append(w)
        y = SAFE_TOP + 14
        for row in rows[:2]:
            d.text((96, y), row, font=self.f_title, fill=(255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0)); y += 70

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            want = set(fs); ims = []; full = '--full' in sys.argv
            for i in range(max(fs) + 1):
                fr = self.frame(i)
                if i in want:
                    ims.append(Image.fromarray(fr).resize((360, 640)))
                    if full: Image.fromarray(fr).save(out[:-4] + '_f%03d.png' % i)
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], [(p[0], name(p[1])) for p in self.plan.plan]); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 60 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        used = sorted({p[1]['key'] for p in self.plan.plan})
        json.dump(dict(K.record(), footage=used), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
