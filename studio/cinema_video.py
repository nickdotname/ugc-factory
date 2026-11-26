#!/usr/bin/env python3
"""ascii.cinema.tty: public-domain films played back as type in a terminal, cut on the beat of one song.

    python studio/cinema_video.py SONG_DIR SEED OUT.mp4 [--frames a,b,c [--full]]     (CQ_WINDOW="t0,t1")

How the clips are chosen (this matters more than the look):
  - only the footage library (studio/footage.py), and only clips footage.blocked() lets through (title, query and
    key checked here as well, so a clip the block list now rules out never gets in even if it is still cached), less
    SKIP below: films that do not read as type (dark, mostly titles, landscapes) or that this account does not want
  - a reel is one kind of film: comedy (Keaton, Chaplin, Lloyd: stunts and chases, strong silhouettes), dream
    (Méliès, Nosferatu, The Lost World, Metropolis, The Crowd, and the abstract films: Ballet Mécanique, Emak-Bakia,
    Rhythmus 21, Lichtspiel Opus) or launch (rockets, roller coasters, trains)
  - every clip is surveyed once at low size (cached beside it as .cinema.json): movement, contrast, how much of
    the picture is clear outline at letter size, where across the frame the movement is (the crop follows it),
    which frames are unusable (an intertitle, black, a fade), and the black bars baked into a copy
  - the opener is picked for its first half-second (movement x contrast x outline), so frame 0 is mid-action, never
    a card or black; films alternate, no clip twice, each cut uses its clip's liveliest clean stretch, and the last
    cut runs into the opening frame, so the video loops
  - cuts land on the beat grid, every bar (two beats at slow tempos), about 1.2-2.6 s apart

How it looks: each frame is cut into letter cells (12 or 14 px wide, bold mono). A cell's brightness picks a letter
by its measured ink ( . : - = + * o x O 0 # % @ ); where a clear outline crosses the cell (difference-of-Gaussians
edges, their direction from the structure tensor) it becomes a stroke along it ( | / - \\ ), so a figure keeps its
outline at phone size. Behind the letters, a dim wash of the same picture, so the image still reads at arm's
length; up close it is all type. On a cut the new shot "types in" (a few frames of scrambled letters settling).
The kick pushes in, the snare flashes the brightest letters white. Text: the play command with the film's title and
year (from the footage index: sourced) and the song credit, both under the picture, inside Instagram's safe area.
Knobs: reel (comedy, dream, launch), cell (12, 14), look (paper, phosphor, amber; colour films keep their own
colour under paper), crt (scanlines on/off).
"""
import json, os, random, re, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage

W, H, FPS = 1080, 1920, 30
PIC_Y0, PIC_Y1 = 130, 1424                       # the picture (it may run under the top bar: it is not text); the text sits under it, above Instagram's bottom 420 px
TONE = (1.35, -0.04, 0.14)                       # contrast, offset, black point
EDGE = (0.35, 0.7, 90)                           # outline share of a cell, one-way-ness, strength percentile
INK = (0.3, 1.2)                                 # letter brightness floor and curve
WASH = 0.24                                      # the picture behind the letters
SUB = 4                                          # picture pixels per letter cell, each way, when a cell is analysed


def _font(*names):
    for n in names:
        for r in (os.path.join(REPO, 'fonts'), '/usr/share/fonts/truetype/dejavu', '/usr/share/fonts'):
            p = os.path.join(r, n)
            if os.path.exists(p): return p
            for d, _, fs in (os.walk(r) if os.path.isdir(r) else ()):
                if n in fs: return os.path.join(d, n)
    raise SystemExit('no font: %s' % (names,))


BOLD = _font('DejaVuSansMono-Bold.ttf', 'DejaVuSansMono.ttf')
MONO = _font('DejaVuSansMono.ttf', 'DejaVuSansMono-Bold.ttf')
FILL = " .:-=+*oxO0#%@"                          # sorted by measured ink below
STROKES = "|\\-/"
LOOKS = {'paper': [(70, 66, 58), (214, 206, 188), (255, 250, 236)],
         'phosphor': [(20, 70, 40), (90, 235, 140), (215, 255, 225)],
         'amber': [(80, 40, 0), (255, 170, 40), (255, 238, 196)]}

# What each reel may use: (themes, a regex its title, query or key must match)
REELS = {
    'comedy': (('silent',), r'keaton|chaplin|lloyd|speedy|freshman|seven chances|sherlock|navigator|cameraman|steamboat|floorwalker|'
                            r'easy street|adventurer|immigrant|west of hot dog|2 a\.?m\.? in the subway|girl shy|safety last'),
    'dream': (('silent',), r'm[eé]li[eè]s|haunted castle|impossible voyage|le monstre|trip to the moon|nosferatu|lost world|metropolis|'
                           r'ballet m[eé]canique|emak|rhythmus|lichtspiel|the crowd'),
    'launch': (('space', 'archive'), r'rocket|roller coaster|coney island|big train|trains rolling'),
}
# Clips that do not read as type, or that this account does not want, whatever their query: a 1914 film with
# blackface scenes, a war epic, title-card travelogues, a dark night-street film, a mislabelled highway opening
# (crowds standing about), talking heads and explainers, a cable ship, an onboard rocket camera (a blur), and an
# office drama the 'Girl Shy' query found instead of Lloyd's film.
SKIP = re.compile(r'florida enchantment|four horsemen|rainbow trail|rien que les heures|iron mask|highway 101|'
                  r'we asked|expert|space weather|cable ship|space station live|replays|sounding rocket|girl who found herself', re.I)


def usable(e, reel):
    themes, rx = REELS[reel]
    words = '%s %s %s' % (e.get('title', ''), e.get('query', ''), e.get('key', ''))
    return (e.get('theme') in themes and not footage.blocked(words) and not footage.BLOCK.search(e.get('title', ''))
            and not SKIP.search(words) and re.search(rx, words, re.I) is not None)


def library(reel):
    return [e for e in footage.pull(REELS[reel][0]) if usable(e, reel)]


def film_name(e):
    """The film's title as a file name, from the footage index: 'steamboat_bill_jr_1928', 'ballet_mecanique_1924'."""
    t = e.get('title', '')
    q = re.search(r'"([^"]+)"', t)
    t = q.group(1) if q else t
    t = re.sub(r"^charlie chaplin's\s*|\s+george m[eé]li[eè]s$|\s+at camera speed\b.*$", '', t, flags=re.I)
    t = re.split(r'\s+(?:-|/|aka|by|starring)\s+|\s*\(|\.webm|\.ogv|_dvd', t, maxsplit=1, flags=re.I)[0]
    m = re.match(r'^(.*),\s*(the|a|an)$', t.strip(), re.I)
    if m: t = m.group(2) + ' ' + m.group(1)
    t = t.lower().translate(str.maketrans('éèêàâçü', 'eeeaacu'))
    t = re.sub(r'[^a-z0-9]+', '_', t).strip('_')[:34] or 'reel'
    year = e.get('year') or footage._yr(e.get('licence')) or footage._yr(e.get('title'))
    return t + ('_%d' % year if year and str(year) not in t else '')


# ---------------------------------------------------------------- reading the library
def survey(e):
    """Per-frame facts about one clip, read once at low size: movement, contrast, outline (how much of the picture
    is clear edge at letter size), where the movement is (0..1 across), unusable frames (intertitle, black, fade),
    whether the copy is in colour, and the crop that removes black bars."""
    memo = os.path.join(footage.CACHE, e['asset'] + '.cinema.json')
    try:
        s = json.load(open(memo))
        return dict(s, **{k: np.array(s[k], bool if k == 'bad' else float) for k in ('mot', 'con', 'edge', 'cx', 'bad')}, crop=tuple(s['crop']))
    except (OSError, ValueError, KeyError): pass
    cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset'])); prev = None
    mot, con, edge, cx, bad, sat = [], [], [], [], [], []; acc = None; size = None
    xs = np.linspace(0, 1, 160)
    while True:
        ok, f = cap.read()
        if not ok: break
        size = f.shape[:2]
        sm = cv2.resize(f, (160, 120), interpolation=cv2.INTER_AREA)
        g = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        acc = g.copy() if acc is None else np.maximum(acc, g)
        d = np.abs(g - prev) if prev is not None else np.zeros_like(g)
        mot.append(float(d.mean())); prev = g
        col = d.sum(0); cx.append(float((col * xs).sum() / col.sum()) if col.sum() > 1e-3 else 0.5)
        con.append(float(g.std()))
        dog = cv2.GaussianBlur(g, (0, 0), 1.0) - cv2.GaussianBlur(g, (0, 0), 1.6)
        edge.append(float((np.abs(dog) > 0.025).mean()))
        sat.append(float(cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)[..., 1].mean()))
        card = False
        if len(mot) % 4 == 1:
            bg = cv2.medianBlur((g * 255).astype(np.uint8), 15).astype(np.float32) / 255
            card = bg[15:-15, 15:-15].std() < 0.12 and (((bg - g) > 0.25).mean() > 0.035 or ((g - bg) > 0.25).mean() > 0.035)
        bad.append(bool(card or g.mean() < 0.07 or g.std() < 0.05))
    cap.release()
    n = len(mot)
    if n < 10: return None
    mot = np.array(mot); mot[0] = mot[1]
    bad = np.convolve(np.array(bad, float), np.ones(13), 'same') > 0
    cx = np.convolve(np.pad(np.array(cx), 15, mode='edge'), np.ones(31) / 31, 'valid')
    cols = np.where(acc.max(0) > 0.12)[0]; rows = np.where(acc.max(1) > 0.12)[0]
    h, w = size
    if len(cols) > 20 and len(rows) > 20:
        pad = 0.012 * w
        crop = (int(cols[0] / 160 * w + pad), int(rows[0] / 120 * h + pad), int((cols[-1] + 1) / 160 * w - pad), int((rows[-1] + 1) / 120 * h - pad))
    else: crop = (0, 0, w, h)
    out = dict(n=n, mot=mot, con=np.array(con), edge=np.array(edge), cx=cx, bad=bad, crop=crop, colour=bool(np.median(sat) > 40))
    try: json.dump(dict(out, **{k: [round(float(x), 5) for x in out[k]] for k in ('mot', 'con', 'edge', 'cx')}, bad=[bool(x) for x in bad], crop=list(crop)), open(memo, 'w'))
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


def reads(s, a=0, b=None):
    """How well a stretch reads as type: movement x contrast x outline."""
    b = s['n'] if b is None else b
    return float(s['mot'][a:b].mean()) * float(s['con'][a:b].mean()) * (0.1 + float(s['edge'][a:b].mean()) * 6)


class Plan:
    """Which clip plays when, from which frame, and where the crop sits, cut on the beat grid."""
    def __init__(self, lib, n, cuts, rng):
        self.n = n; self.cache = {}; stats = {}
        for e in lib:
            s = survey(e)
            if s and s['bad'].mean() < 0.7 and s['mot'].mean() > 0.004: stats[e['asset']] = s
        self.stats = stats
        lib = [e for e in lib if e['asset'] in stats]
        if not lib: sys.exit('no usable clips for this reel')
        segs = [(c, (cuts[k + 1] if k + 1 < len(cuts) else n) - c) for k, c in enumerate(cuts)]
        quality = {e['asset']: reads(stats[e['asset']]) for e in lib}
        hooks = []
        for e in lib:
            s = stats[e['asset']]; off = best_window(s, segs[0][1], random.Random(1))
            if off is not None: hooks.append((reads(s, off, off + 15), e, off))
        hooks.sort(key=lambda h: -h[0]); best = []
        for h in hooks:
            if film_name(h[1]) not in [film_name(b[1]) for b in best]: best.append(h)
        if not best: sys.exit('no clip has a clean opening stretch')
        _, first, off0 = rng.choice(best[:4])
        self.plan = [(0, first, off0)]; used = {first['asset']}; last = film_name(first)
        for k, (c, L) in enumerate(segs[1:], 1):
            if k == len(segs) - 1 and len(segs) > 2 and off0 >= L and not stats[first['asset']]['bad'][off0 - L:off0].any():
                self.plan.append((c, first, off0 - L)); break                     # the last shot runs into the first frame: a loop
            pool = [e for e in lib if film_name(e) != last and e['asset'] not in used] or [e for e in lib if film_name(e) != last] or lib
            e, off = first, None
            for _ in range(6):
                e = rng.choices(pool, weights=[quality[x['asset']] + 1e-6 for x in pool])[0]; off = best_window(stats[e['asset']], L, rng)
                if off is not None: break
            if off is None: e, off = first, off0
            self.plan.append((c, e, off)); used.add(e['asset']); last = film_name(e)

    def segment(self, i):
        k = max(j for j, (c, *_r) in enumerate(self.plan) if c <= i); return k, self.plan[k]

    def length(self, k):
        return (self.plan[k + 1][0] if k + 1 < len(self.plan) else self.n) - self.plan[k][0]

    def frames(self, k):
        if k not in self.cache:
            for old in [j for j in self.cache if j < k - 1]: del self.cache[old]
            c, e, off = self.plan[k]
            x0, y0, x1, y1 = self.stats[e['asset']]['crop']
            cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset'])); cap.set(cv2.CAP_PROP_POS_FRAMES, off); fr = []
            while len(fr) < min(self.length(k) + 1, 400):
                ok, f = cap.read()
                if not ok:
                    if not fr: break
                    fr += fr[::-1]; continue
                fr.append(np.ascontiguousarray(f[y0:y1, x0:x1, ::-1]))
            cap.release(); self.cache[k] = fr or [np.zeros((10, 10, 3), np.uint8)]
        return self.cache[k]

    def centre(self, k):
        """Where across the frame this shot's movement is (0..1), so the crop follows the action."""
        c, e, off = self.plan[k]; s = self.stats[e['asset']]
        return float(np.median(s['cx'][off:off + max(1, self.length(k))])) if off < s['n'] else 0.5


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed)
        self.reel = K.pick('reel', ['comedy', 'dream', 'launch'], r, weights=[4, 3, 2])
        self.cell = int(K.pick('cell', [12, 14], r, weights=[3, 2]))   # 10 px letters vanish into texture on a phone
        self.look = K.pick('look', ['paper', 'phosphor', 'amber'], r, weights=[4, 2, 1])
        self.crt = K.pick('crt', ['on', 'off'], r, weights=[1, 2]) == 'on'
        lib = library(self.reel)
        if len(lib) < 3: lib = library('comedy')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 5.0); self.snare = audio.hits(a['snares'], n, 9.0)
        self.bass = np.convolve(a['bass'], np.ones(5) / 5, 'same')
        per = 4
        while per > 1 and per * spb > 2.6: per //= 2
        if per * spb < 1.2: per *= 2
        beats = [(int(b), int(round(fr))) for b, fr in a['beats'] if 0 <= fr < n]
        cuts = [0]
        for b, fr in beats:
            if b % per == 0 and FPS * 0.8 <= fr <= n - FPS * 0.6 and fr - cuts[-1] >= FPS * 0.9: cuts.append(fr)
        if len(cuts) == 1: cuts += list(range(int(FPS * 2), n - int(FPS * 0.8), int(FPS * 2)))
        self.cuts = cuts
        self.plan = Plan(lib, n, cuts, r)
        # the letter atlas, sorted by measured ink
        self.cw = self.cell; self.ch = int(round(self.cell * 1.8))
        f = ImageFont.truetype(BOLD, int(round(self.cell * 1.62)))
        chars = sorted(set(FILL + STROKES))
        atlas = []
        for c in chars:
            im = Image.new('L', (self.cw, self.ch)); ImageDraw.Draw(im).text((self.cw / 2, self.ch / 2), c, font=f, fill=255, anchor='mm')
            atlas.append(np.asarray(im, np.float32) / 255)
        self.atlas = np.stack(atlas); self.idx = {c: k for k, c in enumerate(chars)}
        ink = {c: self.atlas[self.idx[c]].mean() for c in chars}
        self.fill = np.array([self.idx[c] for c in sorted(FILL, key=lambda c: ink[c])])
        self.stroke = np.array([self.idx[c] for c in STROKES])
        self.cols = W // self.cw; self.rows = (PIC_Y1 - PIC_Y0) // self.ch
        self.ox = (W - self.cols * self.cw) // 2; self.oy = PIC_Y0 + ((PIC_Y1 - PIC_Y0) - self.rows * self.ch) // 2
        self.lohi = None; self.prev_k = -1
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — close quarters' % song.get('title', self.slug).lower()
        self.f_ui = ImageFont.truetype(MONO, 27); self.f_small = ImageFont.truetype(MONO, 23)
        K.MENU['film'] = sorted({film_name(e) for e in lib}); K.CHOSEN['film'] = film_name(self.plan.plan[0][1])

    # ------------------------------------------------------------ the picture
    def grab(self, i):
        """The film under frame i, cropped to the picture's shape around the action, as a (rows*SUB, cols*SUB) RGB."""
        k, (c, e, off) = self.plan.segment(i); fr = self.plan.frames(k); f = fr[min(i - c, len(fr) - 1)]
        h, w = f.shape[:2]; aspect = (self.cols * self.cw) / (self.rows * self.ch)
        zoom = (1.0 + 0.05 * self.kick[i]) * (1 + 0.03 * (i - c) / max(1, self.plan.length(k)))
        cw_, ch_ = (h * aspect, h) if w / h > aspect else (w, w / aspect)
        cw_, ch_ = cw_ / zoom, ch_ / zoom
        x0 = int(np.clip(self.plan.centre(k) * w - cw_ / 2, 0, w - cw_)); y0 = int((h - ch_) / 2)
        crop = f[y0:y0 + int(ch_), x0:x0 + int(cw_)]
        return cv2.resize(crop, (self.cols * SUB, self.rows * SUB), interpolation=cv2.INTER_AREA), k, e

    def cells(self, v):
        return v.reshape(self.rows, SUB, self.cols, SUB, *v.shape[2:]).mean((1, 3))

    def letters(self, i):
        rgb, k, e = self.grab(i); R, C = self.rows, self.cols
        if k != self.prev_k: self.lohi = None
        cut_age = i - self.plan.plan[k][0]; self.prev_k = k
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
        g = cv2.GaussianBlur(g, (0, 0), 0.8)
        Lc = self.cells(g)
        lo, hi = np.percentile(Lc, 1), np.percentile(Lc, 99.5)
        self.lohi = (lo, hi) if self.lohi is None else (0.85 * self.lohi[0] + 0.15 * lo, 0.85 * self.lohi[1] + 0.15 * hi)
        lo, hi = self.lohi
        L = np.clip((Lc - lo) / max(hi - lo, 0.12), 0, 1)
        L = np.clip((L - 0.5) * TONE[0] + 0.5 + TONE[1], 0, 1)                   # an S of contrast: a figure stands off its ground
        L = np.where(L < TONE[2], 0, L)                                       # shadow is empty page, not noise
        ch = self.fill[np.clip(np.rint(L ** 0.9 * (len(self.fill) - 1)).astype(int), 0, len(self.fill) - 1)]
        # outlines: difference of Gaussians, direction from the structure tensor, only where one direction rules
        dog = cv2.GaussianBlur(g, (0, 0), 1.2) - cv2.GaussianBlur(g, (0, 0), 2.2)
        sm = cv2.GaussianBlur(g, (0, 0), 1.0)
        gx = cv2.Sobel(sm, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(sm, cv2.CV_32F, 0, 1, ksize=3)
        jxx, jyy, jxy = self.cells(gx * gx), self.cells(gy * gy), self.cells(gx * gy)
        one_way = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
        ang = (np.degrees(0.5 * np.arctan2(2 * jxy, jxx - jyy)) + 180) % 180         # the gradient's direction
        line = (ang + 90) % 180                                                          # the outline runs across it
        dg = self.cells((np.abs(dog) > 0.03).astype(np.float32))
        strength = np.sqrt(jxx + jyy)
        edge = (dg > EDGE[0]) & (one_way > EDGE[1]) & (strength > max(0.08, np.percentile(strength, EDGE[2]))) & (L > 0.05)
        # array y runs down, so a line at 45 degrees here falls to the right on screen: '\'
        sid = np.where((line < 22.5) | (line >= 157.5), 2, np.where(line < 67.5, 1, np.where(line < 112.5, 0, 3)))
        ch = np.where(edge, self.stroke[sid], ch)
        Ls = np.where(edge, np.maximum(L, 0.55), L)
        s = self.plan.stats[e['asset']]
        if s['colour'] and self.look == 'paper':                              # a colour film keeps its colour
            c = self.cells(rgb.astype(np.float32))
            hsv = cv2.cvtColor(c / 255, cv2.COLOR_RGB2HSV); hsv[..., 1] = np.clip(hsv[..., 1] * 1.35, 0, 1)
            hsv[..., 2] = 0.38 + 0.62 * Ls ** 0.8; col = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB) * 255
        else:
            p = np.array(LOOKS[self.look], np.float32); u = Ls[..., None]
            col = np.where(u < 0.5, p[0] + (p[1] - p[0]) * u * 2, p[1] + (p[2] - p[1]) * (u - 0.5) * 2)
        col = col * (INK[0] + (1 - INK[0]) * Ls[..., None] ** INK[1])            # a dim part is a light letter AND a dim one
        if self.snare[i] > 0.5: col = np.where((L > 0.86)[..., None], 255.0, col)
        blank = L <= 0
        if 0 < i and cut_age < 4:                                                 # a new shot types itself in
            rng = np.random.default_rng(i); frac = (0.55, 0.3, 0.14, 0.05)[cut_age]
            scr = (rng.random((R, C)) < frac) & ~blank
            ch = np.where(scr, self.fill[rng.integers(3, len(self.fill), (R, C))], ch)
        ch = np.where(blank, self.idx[' '], ch)
        mask = self.atlas[ch].transpose(0, 2, 1, 3).reshape(R * self.ch, C * self.cw)[..., None]
        big = np.repeat(np.repeat(col, self.ch, 0), self.cw, 1)
        wash = cv2.resize((col * (L ** 1.2)[..., None]).astype(np.float32), (C * self.cw, R * self.ch), interpolation=cv2.INTER_LINEAR) * WASH
        layer = mask * big
        small = cv2.resize(layer, (layer.shape[1] // 4, layer.shape[0] // 4), interpolation=cv2.INTER_AREA)
        glow = cv2.resize(cv2.GaussianBlur(small, (0, 0), 2.5), layer.shape[1::-1]) * (0.30 + 0.25 * self.bass[i])
        out = np.clip(np.maximum(layer, wash + glow * (1 - mask)), 0, 255)
        if self.crt: out[1::3] *= 0.8
        return out, e

    def frame(self, i):
        img = np.full((H, W, 3), (9, 9, 11), np.float32)
        a, e = self.letters(i)
        img[self.oy:self.oy + a.shape[0], self.ox:self.ox + a.shape[1]] = a
        im = Image.fromarray(img.astype(np.uint8)); d = ImageDraw.Draw(im)
        p = (i + 1) / self.n; t = i / FPS
        d.rectangle([self.ox, PIC_Y1 + 6, self.ox + int((W - 2 * self.ox) * p), PIC_Y1 + 9], fill=(120, 120, 128))
        d.text((40, PIC_Y1 + 38), '$ play %s.mp4' % film_name(e), font=self.f_ui, fill=(126, 231, 135), anchor='lm')
        d.text((40, PIC_Y1 + 76), '%s   %02d:%02d' % (self.credit, int(t) // 60, int(t) % 60), font=self.f_small, fill=(205, 205, 212), anchor='lm')
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            frames = {}
            for f in fs:                                                          # the exposure eases in: warm up a few frames first
                for j in range(max(0, f - 6), f + 1): fr = self.frame(j)
                frames[f] = fr
            ims = [Image.fromarray(frames[f]).resize((360, 640), Image.LANCZOS) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out)
            if '--full' in sys.argv:
                for f in fs: Image.fromarray(frames[f]).save(out[:-4] + '_f%d.png' % f)
            print('sheet', out, K.record()['knobs'], [film_name(e) for _, e, _ in self.plan.plan]); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                              '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n): p.stdin.write(self.frame(i).tobytes())
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        keys = list(dict.fromkeys(e['key'] for _, e, _ in self.plan.plan))
        json.dump(dict(K.record(), footage=keys), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


import polish as _polish
Video.frame = _polish.wrap(Video.frame, 'ascii')      # phosphor glow, grain, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
