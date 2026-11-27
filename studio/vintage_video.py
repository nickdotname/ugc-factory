#!/usr/bin/env python3
"""vintage.media.archive: public-domain films from before 1931, cut on the beat and shown as an old print.

    python studio/vintage_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/vintage_video.py SONG_DIR SEED SHEET.png --frames 0,20,140 [--full]   (a contact sheet instead)

The nightly job's renderer for the "vintage" style (studio/nightly.py). Clips come from the footage library
(studio/footage.py, theme "silent": films made before 1931, which are in the US public domain).

How the clips are chosen (this matters more than the look):
  - every clip is read once at low size: frames that are an intertitle card from the film itself, black, or a fade
    are never used, and black bars baked into a copy (a 4:3 film inside a 16:9 file) are cropped away
  - each cut uses the liveliest stretch of its clip (the most movement), not a random one
  - the opening shot is chosen for its first half-second: movement and contrast right away, so the first frame is
    never black, still, a card or a closed iris
  - films alternate (no two cuts from the same film in a row, no clip twice) and the last cut runs into the
    opening frame, so the video loops
  - cuts land on the beat grid: every two beats or every bar (pace), never more than ~2.2 s apart

How it looks:
  layout  strip: the film runs down the phone as a 35 mm strip on a light box, sprocket holes lit, the frames above
          and below the gate showing; the whole frame is seen (a 4:3 film is not cropped to a sliver), and on
          every other cut the strip rolls the next shot up into the gate on the beat
          fill: the frame cropped to fill the screen, behind a projector gate (rounded / iris / full)
  tint    the dye: sepia, amber, night blue, rose, green, or plain black and white
  crank   every frame (smooth) or every other frame held (the 1920s stutter)
  cards   the lyrics as intertitles: full cards (in the strip, a card frame on the film), a title box, none
  trip    now and then the print misbehaves: it melts on the bass, burns through, or two reels play at once
  slate   the film's title and year as an archive label (title and year from the footage index: sourced)
Every one is a knob (studio/knobs.py), so the learner finds out which looks people watch. Grain, flicker, gate
weave, dust, hairs, scratches and a bright splice frame on hard cuts are always there; the kick nudges flicker
and weave.
"""
import json, math, os, random, re, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage

W, H, FPS = 1080, 1920, 30
# Instagram's interface covers the top ~250 px, the bottom ~420 px and the right ~150 px: text stays out of them.
SAFE_TOP, SAFE_BOTTOM = 250, H - 420

# dark and light ends of each dye, RGB
TINTS = {'sepia': ((26, 17, 10), (236, 221, 190)), 'amber': ((30, 16, 4), (255, 214, 140)), 'night': ((6, 12, 30), (150, 190, 235)),
         'rose': ((28, 8, 14), (240, 190, 200)), 'green': ((8, 22, 12), (190, 230, 190)), 'bw': ((10, 10, 10), (238, 236, 230))}
TRIPS = ['none', 'melt', 'burn', 'double']

# The 35 mm strip: two perforated margins and the picture between them; four perforations to a frame.
MARGIN = 92; PW = W - 2 * MARGIN; PH = int(round(PW * 3 / 4)); GAP = 30; PITCH = PH + GAP; CY = 880   # CY: centre of the gate
ROLL = 5                                                                                         # frames a roll takes

# Clean titles for the films in the library (the archive's own titles are file names); the year comes from the index.
TITLES = {'silent:The_Haunted_Castle_1896': 'The Haunted Castle', 'silent:The_Impossible_Voyage': 'The Impossible Voyage',
          'silent:LeMonstre': 'Le Monstre', 'silent:ATripToTheMoonGeorgeMelies': 'A Trip to the Moon',
          'silent:Nosferatu_DVD_quality': 'Nosferatu', 'silent:CEP177': 'Nosferatu', 'silent:NosferatuSilent': 'Nosferatu'}


def serif(size):
    for p in (os.path.join(REPO, 'fonts', 'Fraunces.ttf'), '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def condensed(size):
    for p in (os.path.join(REPO, 'fonts', 'BarlowCondensed-Medium.ttf'), '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return serif(size)


ABSTRACT = re.compile(r'ballet m[eé]canique|emak|rhythmus|lichtspiel', re.I)   # shapes, not people: never the opener, never in the first bar (review 2026-11-26)


def abstract(e):
    return ABSTRACT.search('%s %s %s' % (e.get('title', ''), e.get('query', ''), e.get('key', ''))) is not None


def film_label(e):
    """('Nosferatu', '1922') for a library entry: a clean title and the year the index records it was published."""
    t = TITLES.get(e.get('key'))
    if not t:
        t = re.sub(r'_+', ' ', e.get('title') or '')
        t = re.sub(r'\b(DVD|quality|silent|HD|1080p|720p)\b|\(\s*(1[89]\d\d)?\s*\)?\s*$|\s+-\s+.*$|\s+George M[ée]li[èe]s|\s+by\s+.*$|^charlie chaplin\'s\s*', '', t, flags=re.I)
        t = re.sub(r'\s+', ' ', t).strip(' -()"\'') or 'Untitled'                    # 'Charlie Chaplin\'s "The Adventurer" (1917' -> 'The Adventurer'
    m = re.search(r'(18[89]\d|19[0-3]\d)', e.get('licence') or '')
    return t, (m.group(1) if m else '')


def lyric_lines(song_dir, t0, t1):
    """(start, end, text) of each sung line that starts inside the window, in seconds from the window's start."""
    if os.environ.get('CQ_LYRICS') == 'none': return []          # nightly: this stretch's words do not measure as in sync
    import sync_check
    rows = sync_check.load_lines(song_dir)
    out = []
    for end, words in rows:
        if not words: continue
        s = words[0][1]
        if t0 <= s < t1 - 0.4: out.append((s - t0, min(end, t1) - t0, ' '.join(w for w, _ in words)))
    return out


# ---------------------------------------------------------------- reading the library
def survey(e):
    """Per-frame facts about one clip, read once at low size: movement, contrast, which frames are unusable (an
    intertitle card from the film, black, a fade), and the crop that removes black bars baked into the copy."""
    memo = os.path.join(footage.CACHE, e['asset'] + '.survey.json')                  # the cache is per runner, so a night reads each clip once
    try:
        s = json.load(open(memo))
        return dict(s, mot=np.array(s['mot']), con=np.array(s['con']), bad=np.array(s['bad'], bool), crop=tuple(s['crop']))
    except (OSError, ValueError, KeyError): pass
    cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset'])); prev = None; mot, con, bad = [], [], []; acc = None; size = None
    while True:
        ok, f = cap.read()
        if not ok: break
        size = f.shape[:2]
        g = cv2.cvtColor(cv2.resize(f, (320, 240), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        acc = g.copy() if acc is None else np.maximum(acc, g)
        mot.append(0.0 if prev is None else float(np.abs(g - prev).mean())); prev = g
        con.append(float(g.std()))
        card = False
        if len(mot) % 4 == 1:                                                     # cards last seconds: every 4th frame is enough
            bg = cv2.medianBlur((g * 255).astype(np.uint8), 21).astype(np.float32) / 255
            card = bg[30:-30, 30:-30].std() < 0.12 and (((bg - g) > 0.25).mean() > 0.035 or ((g - bg) > 0.25).mean() > 0.035)   # text on a plain ground
        bad.append(bool(card or g.mean() < 0.07 or g.std() < 0.05))
    cap.release()
    n = len(mot)
    if n < 10: return None
    mot = np.array(mot); mot[0] = mot[1]
    bad = np.convolve(np.array(bad, float), np.ones(13), 'same') > 0         # and a few frames either side (the fade into a card)
    cols = np.where(acc.max(0) > 0.12)[0]; rows = np.where(acc.max(1) > 0.12)[0]   # black bars never get bright
    h, w = size
    if len(cols) > 40 and len(rows) > 40:
        pad = 0.012 * w
        crop = (int(cols[0] / 320 * w + pad), int(rows[0] / 240 * h + pad), int((cols[-1] + 1) / 320 * w - pad), int((rows[-1] + 1) / 240 * h - pad))
    else: crop = (0, 0, w, h)
    out = dict(n=n, mot=mot, con=np.array(con), bad=bad, crop=crop, res=min(crop[3] - crop[1], crop[2] - crop[0]))
    try: json.dump(dict(out, mot=[round(float(x), 5) for x in mot], con=[round(float(x), 4) for x in out['con']], bad=[bool(x) for x in bad], crop=list(crop)), open(memo, 'w'))
    except OSError: pass
    return out


def best_window(s, L, rng):
    """The start of one of the liveliest L-frame stretches with no unusable frame in it (None if there is none)."""
    n = s['n']; L = min(L, n)
    cs = np.concatenate([[0], np.cumsum(s['mot'])]); bs = np.concatenate([[0], np.cumsum(s['bad'])])
    starts = np.arange(0, n - L + 1)
    ok = (bs[starts + L] - bs[starts]) == 0
    if not ok.any(): return None
    score = np.where(ok, (cs[starts + L] - cs[starts]) / L, -1)
    top = [int(t) for t in np.argsort(score)[::-1][:3] if score[t] >= 0]
    return int(starts[rng.choice(top)])


class Plan:
    """Which clip plays when, from which frame, cut on the beat grid."""
    def __init__(self, lib, n, cuts, rng, stats=None, bar=2 * FPS):
        self.cache = {}; self.n = n
        if stats is None:
            stats = {}
            for e in lib:
                s = survey(e)
                if s and s['bad'].mean() < 0.85 and s['mot'].mean() > 0.003: stats[e['asset']] = s
        self.stats = stats
        lib = [e for e in lib if e['asset'] in stats]
        if not lib: sys.exit('no usable clips in the footage library')
        sharp = lambda s: 0.6 + 0.4 * min(1.0, s['res'] / 400)                      # 240-line copies count for less
        segs = [(c, (cuts[k + 1] if k + 1 < len(cuts) else n) - c) for k, c in enumerate(cuts)]
        quality = {e['asset']: float(np.median(stats[e['asset']]['mot'])) * sharp(stats[e['asset']]) for e in lib}
        # the opener: movement and contrast in the first half-second of its best stretch, one candidate per film
        hooks = []
        film = lambda x: film_label(x)[0]
        for e in lib:
            if abstract(e): continue
            s = stats[e['asset']]; off = best_window(s, segs[0][1], random.Random(1))
            if off is not None: hooks.append((float(s['mot'][off:off + 15].mean()) * float(s['con'][off:off + 15].mean()) * sharp(s), e, off))
        hooks.sort(key=lambda h: -h[0]); best = []
        for h in hooks:
            if film(h[1]) not in [film(b[1]) for b in best]: best.append(h)
        if not best: sys.exit('no clip has a clean opening stretch')
        _, first, off0 = rng.choice(best[:3])
        # one or two films a video (six films in ten seconds was the old plan: nothing stayed long enough to be seen)
        films = {film(first)}; others = sorted({film(e) for e in lib} - films)
        if others and rng.random() < 0.6:
            films.add(rng.choices(others, weights=[max(quality[e['asset']] for e in lib if film(e) == f) + 1e-6 for f in others])[0])
        cast = [e for e in lib if film(e) in films]
        self.plan = [(0, first, off0)]; used = {first['asset']}; last_key = film(first)
        for k, (c, L) in enumerate(segs[1:], 1):
            if k == len(segs) - 1 and len(segs) > 2 and off0 >= L and not stats[first['asset']]['bad'][off0 - L:off0].any():
                self.plan.append((c, first, off0 - L)); break                         # the last shot runs into the first frame: a loop
            ok = [e for e in cast if c >= bar or not abstract(e)]
            pool = [e for e in ok if film(e) != last_key and e['asset'] not in used] or [e for e in ok if e['asset'] not in used] or ok or [first]
            e, off = first, None
            for _ in range(6):
                e = rng.choices(pool, weights=[quality[x['asset']] + 1e-4 for x in pool])[0]; off = best_window(stats[e['asset']], L, rng)
                if off is not None: break
            if off is None: e, off = first, off0
            self.plan.append((c, e, off)); used.add(e['asset']); last_key = film(e)

    def segment(self, i):
        k = max(j for j, (c, *_r) in enumerate(self.plan) if c <= i); return k, self.plan[k]

    def frames(self, k):
        if k not in self.cache:
            for old in [j for j in self.cache if j < k - 1]: del self.cache[old]
            c, e, off = self.plan[k]
            seg = (self.plan[k + 1][0] if k + 1 < len(self.plan) else self.n) - c
            x0, y0, x1, y1 = self.stats[e['asset']]['crop']
            cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset'])); cap.set(cv2.CAP_PROP_POS_FRAMES, off); fr = []
            while len(fr) < min(seg + 1, 400):
                ok, f = cap.read()
                if not ok:
                    if not fr: break
                    fr += fr[::-1]; continue                                          # a short clip plays forward then back
                fr.append(cv2.cvtColor(f[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY))
            cap.release(); self.cache[k] = fr or [np.zeros((10, 10), np.uint8)]
        return self.cache[k]

    def picture(self, i, w, h):
        """Frame i of the video as a w x h grey picture (0..1), cropped to fill, with a slow push-in."""
        k, (c, e, off) = self.segment(i); fr = self.frames(k); f = fr[min(i - c, len(fr) - 1)]
        fh, fw = f.shape[:2]; s = max(w / fw, h / fh) * (1 + 0.035 * (i - c) / max(1, len(fr)))
        M = np.float32([[s, 0, -(fw - w / s) / 2 * s], [0, s, -(fh - h / s) / 2 * s]])
        return cv2.warpAffine(f, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT).astype(np.float32) / 255, k, e


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.layout = K.pick('layout', ['strip', 'fill'], r, weights=[2, 3])   # 4:1 until 2026-11-25: the strip opens on three small frames; skip was 82%
        self.tint = K.pick('tint', list(TINTS), r, weights=[3, 2, 2, 1, 1, 3])
        self.hold = int(K.pick('crank', [1, 2], r))
        self.gate = K.pick('gate', ['rounded', 'iris', 'full'], r)
        self.cards = K.pick('cards', ['full', 'lower', 'none'], r)
        self.trip = K.pick('trip', TRIPS, r, weights=[6, 2, 2, 1])
        self.pace = K.pick('pace', ['beat2', 'bar'], r)
        self.slate = K.pick('slate', ['on', 'off'], r, weights=[3, 1])
        # 2026-11-25: Instagram flagged the account for originality: a tint and a gate on a famous film still match the
        # copies already uploaded. Every frame is now redrawn as ink line art (lines, hatching, paper), so no frame
        # is the film's own picture any more. 'print' (the old look) stays in the code but is not chosen.
        self.look = K.pick('look', ['ink'], r)
        if self.look == 'ink':
            self.layout = 'fill'; K.CHOSEN['layout'] = 'fill'
            if self.tint in ('green', 'night'):         # dark scenes go blotchy on the cold papers: warm paper only
                self.tint = r.choice(['sepia', 'amber', 'bw', 'rose']); K.CHOSEN['tint'] = self.tint
            self.trip = 'none' if self.trip in ('burn', 'double') else self.trip; K.CHOSEN['trip'] = self.trip
            self.ink_pen = K.pick('pen', ['fine', 'brush'], r)
            if self.gate == 'iris': self.gate = 'rounded'; K.CHOSEN['gate'] = 'rounded'
        lib = [e for e in footage.pull(('silent',)) if not footage.BLOCK.search('%s %s' % (e.get('title', ''), e.get('key', '')))]
        self.source = 'silent'
        if len(lib) < 3: lib = footage.pull(('archive',)); self.source = 'archive'     # until the silent films are fetched
        K.MENU['source'] = ['silent', 'archive']; K.CHOSEN['source'] = self.source
        if not lib: sys.exit('the footage library is empty: run the footage workflow first')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 6.0)
        self.bass = np.convolve(a['bass'], np.ones(7) / 7, 'same')
        # cuts on the beat grid: every two beats or every bar, and every shot at least 2 s (review 2026-11-26: six films in
        # ten seconds, nothing on screen long enough to be seen), so on a fast song 'beat2' is really a bar
        per = 2 if self.pace == 'beat2' else 4
        while per * self.spb < 2.0: per *= 2
        beats = [(int(b), int(round(fr))) for b, fr in a['beats'] if 0 <= fr < n]
        cuts = [0]
        for b, fr in beats:
            if b % per == 0 and FPS * 2.0 <= fr <= n - FPS * 1.2 and fr - cuts[-1] >= FPS * 2.0: cuts.append(fr)
        if len(cuts) < 2 and n > FPS * 4: cuts = list(range(0, n - int(FPS * 1.2), int(FPS * 2)))
        bar = int(4 * self.spb * FPS)
        self.clips = Plan(lib, n, cuts, r, bar=bar)
        self.ghost = Plan(lib, n, cuts[::2], random.Random(seed + 7), self.clips.stats, bar=bar) if self.trip == 'double' else None
        # in the strip every other cut rolls the next frame up into the gate; the rest are hard cuts with a splice flash
        self.rolls = {c for j, (c, *_r) in enumerate(self.clips.plan) if j and j % 2 == 0} if self.layout == 'strip' else set()
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.lines = [(int(s * FPS), int(e * FPS), txt) for s, e, txt in lyric_lines(song_dir, t0, t1)]
        self.full = []
        if self.cards == 'full':                        # two cards at most, short, seconds apart, never in the opening
            last = -10 ** 9
            for s, e, txt in self.lines:
                if s >= int(2.5 * FPS) and s - last > 4 * FPS and len(self.full) < 2 and s + FPS < n:
                    self.full.append((s, min(e, s + int(1.4 * FPS)), txt)); last = s
        self.f_card = serif(78 if self.layout == 'fill' else 58); self.f_low = serif(46)
        self.f_title, self.f_year = serif(66), condensed(42)
        sans = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/Library/Fonts/Arial Unicode.ttf') if os.path.exists(p)), None)
        self.f_credit = ImageFont.truetype(sans, 30) if sans else serif(30)       # the serif has no note sign
        lo, hi = TINTS[self.tint]; self.lo = np.array(lo, np.float32); self.hi = np.array(hi, np.float32)   # RGB
        if self.look == 'ink':                          # ink on paper: the tint picks the paper and the ink
            paper = {'sepia': (240, 228, 205), 'amber': (246, 232, 200), 'night': (226, 232, 240), 'green': (232, 238, 222),
                     'rose': (244, 228, 226)}.get(self.tint, (242, 236, 222))
            self.lo = np.array({'night': (20, 30, 60), 'rose': (70, 20, 30)}.get(self.tint, (24, 20, 18)), np.float32); self.hi = np.array(paper, np.float32)
        self.ink = tuple(int(c) for c in hi)
        # the picture's own size, and its vignette / grain at that size
        self.pw, self.ph = (PW, PH) if self.layout == 'strip' else (W, H)
        yy, xx = np.mgrid[0:self.ph, 0:self.pw].astype(np.float32)
        d = np.sqrt(((xx - self.pw / 2) / (self.pw * 0.62)) ** 2 + ((yy - self.ph / 2) / (self.ph * 0.62)) ** 2)
        self.vig = np.clip(1.12 - d ** 2 * 0.6, 0.3, 1).astype(np.float32)
        self.rr = np.sqrt(((xx - self.pw / 2) / (self.pw / 2)) ** 2 + ((yy - self.ph / 2) / (self.pw / 2)) ** 2).astype(np.float32)
        gr = np.random.default_rng(seed)
        self.grain = [cv2.resize(gr.normal(0, 1, (self.ph // 2, self.pw // 2)).astype(np.float32), (self.pw, self.ph), interpolation=cv2.INTER_LINEAR) for _ in range(8)]
        if self.layout == 'fill':
            m = Image.new('L', (W, H), 0); ImageDraw.Draw(m).rounded_rectangle([38, 60, W - 38, H - 60], radius=110, fill=255)
            self.round = cv2.GaussianBlur(np.asarray(m, np.float32) / 255, (0, 0), 9)
        else:
            m = Image.new('L', (PW, PH), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, PW - 1, PH - 1], radius=22, fill=255)
            self.round = cv2.GaussianBlur(np.asarray(m, np.float32) / 255, (0, 0), 1.2)
            self.strip = self.make_strip()
            ys = np.arange(H, dtype=np.float32)[:, None]
            self.glow = np.clip(1.0 - ((ys - CY) / (H * 0.62)) ** 2, 0.45, 1.0).astype(np.float32)   # the light box is brightest under the gate
        self.scratches = []; self.weave = np.zeros(2, np.float32)
        self.burn_at = None; self.burn_rim = None
        if self.trip == 'burn':                         # one burn, on a bar line in the back half
            bars = [fr for b, fr in beats if b % 4 == 0 and n * 0.45 < fr < n - FPS * 1.2]
            self.burn_at = r.choice(bars) if bars else int(n * 0.7)
            bn = cv2.GaussianBlur(gr.random((self.ph // 8, self.pw // 8)).astype(np.float32), (0, 0), 3)
            bn = cv2.resize((bn - bn.min()) / (np.ptp(bn) + 1e-6), (self.pw, self.ph))
            cy, cx = gr.integers(self.ph // 4, 3 * self.ph // 4), gr.integers(self.pw // 4, 3 * self.pw // 4)
            self.burn_noise = bn * 0.55 + np.sqrt(((xx - cx) / self.pw) ** 2 + ((yy - cy) / self.pw) ** 2) * 0.9
        self.melt_x = xx; self.melt_y = yy
        self.prev_pic = None; self._k = None; self.cut_at = 0; self.flash = 0

    # ---------------------------------------------------------------- the strip
    def make_strip(self):
        """The film base with its perforations, three pitches taller than the screen so it can roll, as density 0..1."""
        hh = H + 3 * PITCH
        im = Image.new('L', (W, hh), 26); d = ImageDraw.Draw(im)
        pw, ph, step = 50, 36, PITCH / 4
        for j in range(int(hh / step) + 2):
            y = j * step + step / 2 - ph / 2
            for x in (MARGIN / 2 - pw / 2, W - MARGIN / 2 - pw / 2):
                d.rounded_rectangle([x, y, x + pw, y + ph], radius=7, fill=235)        # light shows through the holes
        s = cv2.GaussianBlur(np.asarray(im, np.float32) / 255, (0, 0), 1.0)
        streak = cv2.GaussianBlur(np.random.default_rng(3).normal(0, 1, (1, W)).astype(np.float32), (0, 0), 6) * 0.02
        return np.clip(s + streak, 0, 1)

    def compose_strip(self, i, g, jump):
        """The strip on the light box: the gate frame in the middle, the frames above and below it dimmed."""
        since = i - self.cut_at
        rolling = self.cut_at in self.rolls and since < ROLL and self.prev_pic is not None
        u = 1.0 - (1 - since / ROLL) ** 3 if rolling else 1.0                     # ease out: it lands on the beat and settles
        shift = (1 - u) * PITCH                                                      # how far the new frame still has to come up
        off = int(PITCH * 1.5) - int(round(shift))
        dens = self.strip[off:off + H].copy(); rects = []
        for j in (-2, -1, 0, 1, 2):
            y0 = int(round(CY + j * PITCH + shift - PH / 2)); y1 = y0 + PH
            if y1 <= 0 or y0 >= H: continue
            centre = j == 0
            pic = self.prev_pic if (rolling and j < 0) else g                        # rolling: the old shot is still above
            p = pic * self.round if centre else pic * self.round * 0.4 + 0.02 * self.round   # frames off the gate are dimmer
            a0, a1 = max(0, y0), min(H, y1)
            seg = dens[a0:a1, MARGIN:MARGIN + PW]
            dens[a0:a1, MARGIN:MARGIN + PW] = seg * (1 - self.round[a0 - y0:a1 - y0]) + p[a0 - y0:a1 - y0]
            if centre: rects.append((MARGIN, y0, MARGIN + PW, y1))
        dens = dens * self.glow
        if rolling: dens = cv2.blur(dens, (1, 11))                                   # motion blur while it rolls
        M = np.float32([[1, 0, self.weave[0]], [0, 1, self.weave[1] + jump]])
        return cv2.warpAffine(dens, M, (W, H), borderMode=cv2.BORDER_REPLICATE), rects

    # ---------------------------------------------------------------- the print
    def grade(self, g):
        lo, hi = np.percentile(g[::6, ::6], 2), np.percentile(g[::6, ::6], 98.5)
        g = np.clip((g - lo) / max(0.18, hi - lo), 0, 1)                            # old prints are contrasty
        return g * g * (3 - 2 * g) * 0.8 + g * 0.2                                    # an S curve

    def picture(self, i, src):
        """The print at picture size, as density 0..1, with the defects a projected print has."""
        g, k, e = self.clips.picture(src, self.pw, self.ph)
        if self.look == 'ink':
            lo, hi = np.percentile(g[::6, ::6], 3), np.percentile(g[::6, ::6], 97)
            return self.inked(np.clip((g - lo) / max(0.15, hi - lo), 0, 1), src), k, e
        g = self.grade(g)
        if self.ghost is not None:
            gg, *_ = self.ghost.picture(src, self.pw, self.ph); g = np.clip(g * 0.72 + self.grade(gg) * 0.4, 0, 1)
        rng = np.random.default_rng(i * 7919 + 13)
        if self.trip == 'melt':
            amp = (4 + 46 * float(self.bass[i]) ** 2 + 30 * self.kick[i]) * self.pw / W
            t = i / FPS
            dy = np.sin(self.melt_x / 140.0 + t * 2.1) * amp + np.sin(self.melt_y / 310.0 + t) * amp * 0.4
            dx = np.sin(self.melt_y / 180.0 + t * 1.3) * amp * 0.35
            g = cv2.remap(g, (self.melt_x + dx).astype(np.float32), (self.melt_y - np.abs(dy)).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        g = g * (1 + 0.04 * rng.normal() + 0.08 * self.kick[i])                        # flicker
        if self.flash: g = g * 0.5 + 0.55; self.flash -= 1                             # the splice: one frame near white
        g = g + self.grain[i % len(self.grain)] * 0.05
        g = g * self.vig
        for _ in range(rng.poisson(4)):                                               # dust: specks and the odd hair
            x, y = int(rng.integers(0, self.pw)), int(rng.integers(0, self.ph)); v = float(rng.choice([0.02, 0.95]))
            if rng.random() < 0.12:
                a = rng.uniform(0, math.pi); L = int(rng.integers(20, 70))
                cv2.line(g, (x, y), (x + int(L * math.cos(a)), y + int(L * math.sin(a))), v, 1, cv2.LINE_AA)
            else: cv2.circle(g, (x, y), int(rng.integers(1, 5)), v, -1, cv2.LINE_AA)
        if rng.random() < 0.08: self.scratches.append([float(rng.integers(40, self.pw - 40)), int(rng.integers(4, 16)), float(rng.choice([-0.2, 0.28]))])
        for sc in self.scratches:                                                     # a scratch lightens or darkens; it does not paint a line
            x = int(sc[0]); g[:, max(0, x - 1):x + 1] += min(1.0, sc[1] / 8) * sc[2]
            sc[0] += rng.normal(0, 0.8); sc[1] -= 1
        self.scratches = [sc for sc in self.scratches if sc[1] > 0]
        g = np.clip(g, 0, 1)
        self.burn_rim = None
        if self.burn_at is not None and self.burn_at <= i < self.burn_at + int(1.1 * FPS):
            p = (i - self.burn_at) / (1.1 * FPS); edge = self.burn_noise - p * 1.6
            rim = (edge >= 0) & (edge < 0.07)
            g = np.where(edge < 0, 1.0, np.where(rim, g * 0.15, g)).astype(np.float32)
            self.burn_rim = rim
        return g, k, e

    def inked(self, g, src):
        """The picture redrawn in ink, as density 0..1 (1 = bare paper): outlines from a difference of Gaussians, the
        darks filled with hatching (one direction, then cross-hatched, then solid), all of it re-drawn a little
        differently every other frame ('boiling' lines, as hand-drawn animation does)."""
        h, w = g.shape; j = src // 2
        rng = np.random.default_rng(j * 104729 + 7)
        nx = cv2.resize(rng.normal(0, 1, (h // 40 + 2, w // 40 + 2)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        ny = cv2.resize(rng.normal(0, 1, (h // 40 + 2, w // 40 + 2)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        g = cv2.remap(g, xx + nx * 2.2, yy + ny * 2.2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        s1 = 1.2 if self.ink_pen == 'fine' else 2.0
        a, b = cv2.GaussianBlur(g, (0, 0), s1), cv2.GaussianBlur(g, (0, 0), s1 * 1.6)
        dog = a - 0.985 * b
        line = 1 - np.clip(-dog * (140 if self.ink_pen == 'fine' else 95) - 0.15, 0, 1)                 # 0 where there is a line
        tone = cv2.GaussianBlur(g, (0, 0), 3)
        def hatch(angle, gap, width):
            u = xx * math.cos(angle) + yy * math.sin(angle) + nx * 1.5
            return (np.abs(((u / gap) % 1) - 0.5) * gap > width / 2).astype(np.float32)
        th = rng.uniform(-0.05, 0.05)
        h1, h2 = hatch(0.78 + th, 11, 2.2), hatch(-0.78 + th, 11, 2.2)
        fill = np.where(tone < 0.1, 0.0, np.where(tone < 0.28, h1 * h2, np.where(tone < 0.48, h1, 1.0)))
        line = cv2.erode(line, np.ones((2, 2), np.uint8)) if self.ink_pen == 'brush' else line
        d = np.minimum(line, fill)
        d = cv2.GaussianBlur(d, (0, 0), 0.6)
        paper = cv2.resize(np.random.default_rng(11).normal(0, 1, (h // 3, w // 3)).astype(np.float32), (w, h)) * 0.025
        return np.clip(d + paper, 0, 1) * self.round + (1 - self.round)

    def frame(self, i):
        src = i - (i % self.hold)
        k = self.clips.segment(src)[0]
        if self._k is not None and k != self._k:
            self.cut_at = i
            if self.clips.plan[k][0] not in self.rolls: self.flash = 1
        self._k = k
        g, k, e = self.picture(i, src)
        card = next((txt for s, e2, txt in self.full if s <= i < e2), None)
        rng = np.random.default_rng(i * 31 + 5)
        self.weave = self.weave * 0.7 + rng.normal(0, [1.0, 1.6]).astype(np.float32) * 0.6
        jump = 7 * self.kick[i] if self.kick[i] > 0.7 else 0
        if self.layout == 'fill':
            if self.gate == 'rounded': g = g * self.round
            elif self.gate == 'iris' and self.cut_at > 0:                             # opens at each cut, never on the first frame
                rad = 0.8 + 1.4 * min(1.0, (i - self.cut_at) / 5)                          # a quick open, five frames: a picture, never a dot on black
                g = g * np.clip((rad - self.rr) / 0.08, 0, 1)
            M = np.float32([[1, 0, self.weave[0]], [0, 1, self.weave[1] + jump]])
            dens = cv2.warpAffine(g, M, (W, H), borderMode=cv2.BORDER_REFLECT); rects = []
        else:
            dens, rects = self.compose_strip(i, g, jump)
        img = self.lo + (self.hi - self.lo) * dens[..., None]                         # the dye
        if self.burn_rim is not None and self.layout == 'fill':
            img[self.burn_rim] = img[self.burn_rim] * 0.2 + np.array([255, 140, 40], np.float32) * 0.8
        out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(out)
        if card: self.draw_card(d, card, rects)
        elif self.cards == 'lower':
            txt = next((txt for s, e2, txt in self.lines if s <= i < e2), None)
            if txt: self.draw_lower(d, txt)
        if (self.slate == 'on' or i < 2 * FPS) and not (card and self.layout == 'fill'): self.draw_slate(d, e)   # title and year for the first 2 s of every video, all through with slate on
        d.text((W / 2, SAFE_BOTTOM - 24), self.credit, font=self.f_credit, fill=self.ink, anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        self.prev_pic = g
        return np.asarray(out)

    # ---------------------------------------------------------------- text
    def wrap(self, txt, font, width):
        words, rows, cur = txt.split(), [], ''
        for w in words:
            t = (cur + ' ' + w).strip()
            if font.getlength(t) <= width or not cur: cur = t
            else: rows.append(cur); cur = w
        return rows + ([cur] if cur else [])

    def draw_slate(self, d, e):
        """The film's title and year, as an archive label above the gate."""
        title, year = film_label(e)
        f = self.f_title
        while f.getlength(title) > W - 320 and f.size > 40: f = serif(f.size - 4)     # a long title gets smaller, not cut
        y = 400 if self.layout == 'strip' else 340
        d.text((W / 2, y), title, font=f, fill=self.ink, anchor='ms', stroke_width=4, stroke_fill=(0, 0, 0))
        if year: d.text((W / 2, y + 54), '  '.join(year), font=self.f_year, fill=self.ink, anchor='ms', stroke_width=3, stroke_fill=(0, 0, 0))

    def draw_card(self, d, txt, rects):
        ink = self.ink
        if self.layout == 'strip' and rects:                                          # the card is a frame of the film
            x0, y0, x1, y1 = rects[0]
            d.rounded_rectangle([x0, y0, x1, y1], radius=22, fill=(12, 11, 10))
            d.rectangle([x0 + 40, y0 + 40, x1 - 40, y1 - 40], outline=ink, width=3)
            d.rectangle([x0 + 54, y0 + 54, x1 - 54, y1 - 54], outline=ink, width=1)
            rows = self.wrap(txt.strip(' ,'), self.f_card, PW - 200)[:4]
            y = (y0 + y1) / 2 - (len(rows) - 1) * 38
            for row in rows: d.text((W / 2, y), row, font=self.f_card, fill=ink, anchor='mm'); y += 76
            return
        d.rectangle([0, 0, W, H], fill=(10, 9, 8))
        top, bot = SAFE_TOP + 120, SAFE_BOTTOM - 80
        for m, wdt in ((120, 4), (140, 2)):                                           # a double rule, as the title cards had
            d.rectangle([m, top + (m - 120), W - m, bot - (m - 120)], outline=ink, width=wdt)
        for cx, cy in ((120, top), (W - 120, top), (120, bot), (W - 120, bot)):
            d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=ink, width=3)
        rows = self.wrap(txt.strip(' ,'), self.f_card, W - 340)
        y = (top + bot) / 2 - (len(rows) - 1) * 52
        for row in rows: d.text((W / 2, y), row, font=self.f_card, fill=ink, anchor='mm'); y += 104

    def draw_lower(self, d, txt):
        rows = self.wrap(txt.strip(' ,'), self.f_low, W - 320)[:3]
        h = 62 * len(rows) + 40; y0 = SAFE_BOTTOM - 80 - h
        if self.layout == 'strip': y0 = min(y0, CY + PH // 2 + 44)
        d.rectangle([110, y0, W - 150, y0 + h], fill=(8, 8, 8), outline=self.ink, width=3)
        y = y0 + 20 + 31
        for row in rows: d.text(((110 + W - 150) / 2, y), row, font=self.f_low, fill=self.ink, anchor='mm'); y += 62

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            want = set(fs); ims = []; full = '--full' in sys.argv
            for i in range(max(fs) + 1):
                fr = self.frame(i)
                if i in want:
                    ims.append(Image.fromarray(fr).resize((360, 640)))
                    if full: Image.fromarray(fr).save(out[:-4] + '_f%d.png' % i)
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out)
            print('sheet', out, K.record()['knobs'], [(c, film_label(e)[0], off) for c, e, off in self.clips.plan]); return
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
        used = sorted({e['key'] for _, e, _o in self.clips.plan})
        json.dump(dict(K.record(), footage=used), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
