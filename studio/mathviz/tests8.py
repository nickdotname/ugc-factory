"""8-Bit Tests (8bit.tests): play-along pixel-art tests built from the song itself.

Every test is made of the song's own hits (the beat map and the drum hits from its stems, studio/mathviz/beat.py), so
the answer is exact and every move lands on the music. Each has the instruction on screen from the first frame, a
tense middle and a reveal:

  pause   PAUSE WHEN IT FITS: a shape hops around a stone tablet with a hole its shape in it, landing on the hits.
          It sits exactly in the hole only once a round (on a snare where the round has one, else on a hit), for 4,
          then 2, then 1 frame; near misses (a few pixels off, or mirrored) come just before. A frame counter runs so a paused viewer can check,
          and a stamp over the tablet says what a paused frame shows: FIT on the fit frames only, MISSED BY N PX (art
          pixels, measured from the shape to the hole) or MIRRORED on a near miss. Reveal: the frozen fit and how many
          frames each round fit for.
  cups    FOLLOW THE GEM: three identical pots, a gem under one, swapped on the song's hits (slow, then on every
          hit). WHICH POT? with a three-beat countdown, then they lift.
  memory  WATCH THE ORDER: six crystals light one at a time on the hits; then one question (WHICH LIT 4TH?) and the
          whole order replayed with numbers.
  count   COUNT THE FIREWORKS: one bursts on every snare of the stretch (each rocket launched so it bursts exactly on
          the snare), high in the sky only; while you count, the world's small lights (window lights, string lights,
          antenna blinks, dust) are turned down so nothing else looks like a burst. HOW MANY? then a replay that tallies them.
  beat    EARLY OR LATE? a creature bounces on a drum, landing exactly on every hit; the last landing is moved 3-4
          frames early or late, or left on time. Reveal: a slow-motion timeline of the hit and the landing, in ms.

The pictures are pixel worlds drawn in code (studio/mathviz/pix8.py: a rooftop city, a moonlit forest, a crystal
cave), on a 270 x 480 canvas blown up 4x, with a light bloom and optional scanlines. No game's characters, interface or
fonts: the font is our own 5x7 one. Knobs: test, world, crt.
Every test runs 14-26 s: where 28 of the song's beats take less than 14 s (a fast song) the test counts in half
time (HalfClock); where neither fits (Talk's 13.8 s, a stretch too near the song's end) it is not rendered (exit 3)."""
import sys, os, math, random
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *
from pix8 import (World, LW, LH, GY, INK, BY, ramp, solid, glow, title, tmask, disc_mask, poly_mask, roll, bayer)

SLUG, B0, SEED = conf('talk', 96)
_r = random.Random(SEED)
TEST = K.pick('test', ['pause', 'cups', 'memory', 'count', 'beat'], _r, weights=[3, 3, 3, 2, 2])
WORLD_NAME = K.pick('world', ['city', 'forest', 'cave'], _r)
if TEST == 'count' and WORLD_NAME == 'cave':            # fireworks need a sky: the cave gets the city instead
    WORLD_NAME = 'city'; K.CHOSEN['world'] = 'city'
CRT = K.flag('crt', 0.6, _r)
BEATS = {'pause': 26, 'cups': 25, 'memory': 28, 'count': 28, 'beat': 25}[TEST]


class HalfClock(Clock):
    """A Clock whose beat is `mult` of the song's: on a fast song a test counts in half time (one test beat = two of
    the song's), so it is not over in 9-12 s; every move still lands on the song's own beats and hits."""
    def __init__(self, slug, b0, beats, mult):
        self.mult = mult; super().__init__(slug, b0, beats * mult); self.beats = beats; self.spb *= mult
    def beat(self, i): return super().beat(i) / self.mult


def _tempo_mult():
    """1 if 28 of the song's beats from B0 take 14-26 s, 2 if 28 of its half-time beats do and the song lasts that
    long, else None. Review 2026-11-26: the tests are meant to run 14-26 s."""
    import json as _json
    s = _json.load(open(os.path.join(audio.SONGS, SLUG, 'song.json')))
    master = next((os.path.join(audio.SONGS, SLUG, 'master' + e) for e in ('.ogg', '.flac', '.wav') if os.path.exists(os.path.join(audio.SONGS, SLUG, 'master' + e))), None)
    end = sf.info(master).duration if master else float('inf')
    for m in (1, 2):
        d = audio.time_of_beat(s, B0 + 28 * m) - audio.time_of_beat(s, B0)
        if 14 <= d <= 26 and audio.time_of_beat(s, B0 + BEATS * m) <= end: return m
    print('not rendered: 28 beats take %.1f s here (%.1f s in half time), outside 14-26 s (%s)' % (
        audio.time_of_beat(s, B0 + 28) - audio.time_of_beat(s, B0), audio.time_of_beat(s, B0 + 56) - audio.time_of_beat(s, B0), SLUG))
    sys.exit(3)


import soundfile as sf
MULT = _tempo_mult()
CL = HalfClock(SLUG, B0, BEATS, MULT)
CREDIT = credit(SLUG)
WORLD = World(WORLD_NAME, SEED)
# The hits: from the song's Ableton project where it has one (exact, and each kept only if it is heard in the
# released mix, beat.project), else from the drum stem (onsets sorted into kick / snare by where their energy sits)
_PJ = audio.project(SLUG, CL.t0, CL.t1)
EXACT = bool(_PJ) and len(_PJ['snare']) >= 4 and len(_PJ['kick']) >= 4
if EXACT:
    CL.kick_frames = sorted({int(round(t * FPS)) for t, _ in _PJ['kick'] if 0 <= t * FPS < CL.n})
    CL.snare_frames = sorted({int(round(t * FPS)) for t, _ in _PJ['snare'] if 0 <= t * FPS < CL.n})
XC = 130                                                # text centre: clear of Instagram's buttons on the right
GOLD, WHITE, MINT, ROSE = (255, 206, 84), (255, 255, 255), (120, 255, 170), (255, 110, 150)


def fr(b):
    """The video frame (float) at beat b of the clip."""
    return (audio.time_of_beat(CL.song, CL.b0 + CL.mult * b) - CL.t0) * FPS


def hit_frames(b0, b1, gap_beats, kinds=('kick', 'snare'), min_frames=8):
    """The song's own hits (kick and/or snare) between beats b0 and b1, thinned so two are at least gap_beats apart,
    as integer frames. Where the drums are thin, the beat grid fills in."""
    fs = sorted(set((CL.kick_frames if 'kick' in kinds else []) + (CL.snare_frames if 'snare' in kinds else [])))
    f0, f1 = fr(b0), fr(b1); gap = max(min_frames, gap_beats * CL.spb * FPS)
    out = []
    for f in fs:
        if f0 <= f < f1 and (not out or f - out[-1] >= gap): out.append(f)
    need = int((b1 - b0) / max(gap_beats, 0.5) * 0.4)
    if len(out) < need:                                  # too few drum hits here: use the beats themselves
        out = sorted(set(out) | {int(round(fr(b))) for b in range(int(math.ceil(b0)), int(b1))})
        thin = []
        for f in out:
            if not thin or f - thin[-1] >= gap: thin.append(f)
        out = thin
    return [f for f in out if 0 <= f < CL.n]


def ordinal(n): return '%d%s' % (n, {1: 'ST', 2: 'ND', 3: 'RD'}.get(n, 'TH'))


def place(sm, x, y):
    """A small mask sm placed with its top-left at (x, y) on a full-canvas mask."""
    m = np.zeros((LH, LW), bool); h, w = sm.shape
    x0, y0 = int(x), int(y); X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(LW, x0 + w), min(LH, y0 + h)
    if X1 > X0 and Y1 > Y0: m[Y0:Y1, X0:X1] = sm[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
    return m


def tint(c, m, col, a):
    if a > 0 and m.any(): c[m] = c[m] * (1 - a) + np.array(col, np.float32) * a


def header(c, l1, l2=None, sub=None, col=GOLD, subcol=(220, 226, 255), y=66):
    title(c, l1, XC, y, 3, WHITE, col)
    if l2: title(c, l2, XC, y + 27, 3, WHITE, col)
    if sub: title(c, sub, XC, y + (56 if l2 else 30), 1, subcol)


def countdown(c, k, kq, y=132):
    """Three beats to answer: a bar that drains in three steps, with the number."""
    if not (kq <= k < kq + 3): return
    n = 3 - int(k - kq); f = 1 - (k - kq) / 3
    x0, x1 = XC - 70, XC + 70; wf = max(1, int((x1 - x0) * f))
    c[y - 1:y + 9, x0 - 2:x1 + 2] = INK; c[y:y + 8, x0:x1] = (40, 30, 70)
    c[y:y + 8, x0:x0 + wf] = ramp(np.tile(np.linspace(0, 1, wf)[None, :], (8, 1)), [ROSE, GOLD], bayer(8, wf))
    for j in (1, 2): c[y:y + 8, x0 + (x1 - x0) * j // 3] = INK
    pop = 1 if (k - kq - int(k - kq)) < 0.25 else 0
    title(c, str(n), XC, y + 14, 4 + pop, WHITE, ROSE)


def burst(c, x, y, dt, col, n=18, speed=2.2, life=18, seed=0, g=0.06):
    """Sparks flying out of (x, y), dt frames after the hit."""
    if dt < 0 or dt > life: return
    r = random.Random(seed); a = 1 - dt / life; col = np.array(col, np.float32)
    for j in range(n):
        ang = 2 * math.pi * (j + r.random() * 0.6) / n; v = speed * (0.6 + 0.6 * r.random())
        px = x + math.cos(ang) * v * dt; py = y + math.sin(ang) * v * dt + g * dt * dt
        if 0 <= px < LW and 0 <= py < LH and (dt < life * 0.6 or r.random() < 0.7):
            c[int(py), int(px)] = col * a + 255 * (1 - a) * 0.3


# ================================================================ PAUSE WHEN IT FITS
SHAPES = {   # our own chunky pixel shapes, drawn 5x
    'star': ["....#....", "...###...", "...###...", "#########", ".#######.", "..#####..", "..##.##..", ".##...##.", "##.....##"],
    'heart': [".##...##.", "####.####", "#########", "#########", ".#######.", "..#####..", "...###...", "....#...."],
    'bolt': ["...#####", "..#####.", "..####..", ".####...", ".#######", "...####.", "..####..", "..###...", ".##.....", ".#......"],
    'note': ["...#....", "...##...", "...###..", "...#.##.", "...#..#.", "...#....", "...#....", ".###....", "####....", "####....", ".##....."],
    'key': [".###........", "#####.......", "##.#########", "#####..#.##.", ".###...#.##."],
    'moon': ["..####..", ".###....", "###.....", "###.....", "###.....", "###.....", ".###....", "..####.."],
    'arrow': ["....#....", "...###...", "..#####..", ".#######.", "#########", "...###...", "...###...", "...###...", "...###..."],
    'crown': ["#...#...#", "##.###.##", "#########", "#########", "#.#.#.#.#", "#########"],
}
ASYM = {'bolt', 'note', 'key', 'moon'}
SHAPE_COL = {'star': (255, 210, 70), 'heart': (255, 90, 120), 'bolt': (120, 220, 255), 'note': (190, 140, 255),
             'key': (255, 190, 90), 'moon': (150, 255, 200), 'arrow': (255, 120, 220), 'crown': (255, 160, 60)}
SC5 = 5


def shape_mask(name, mir=False):
    a = np.array([[ch == '#' for ch in row] for row in SHAPES[name]])
    if mir: a = a[:, ::-1]
    return np.kron(a, np.ones((SC5, SC5), bool))


class Pause:
    HOLE = (XC, 258)
    DWELL = [4, 2, 1]

    def __init__(self):
        r = random.Random(SEED * 3 + 1)
        self.names = r.sample(sorted(SHAPES), 3)
        self.rounds = []
        for j in range(3):
            a, b = 6 * j, 6 * j + 6
            hs = hit_frames(a + 0.4, b + 0.3, 0.5, min_frames=9)
            sn = [f for f in CL.snare_frames if fr(a + 2.8) <= f < fr(b - 0.6)]
            pool = sn or [f for f in hs if fr(a + 2.8) <= f < fr(b - 0.6)] or [int(round(fr(a + 4)))]
            fit = min(pool, key=lambda f: abs(f - fr(a + 4.2)))
            D = self.DWELL[j]
            before = [f for f in hs if f <= fit - 9][-4:]
            if not before: before = [int(round(fr(a + 1)))]
            after = [f for f in hs if f >= fit + D + 6][:1] or [int(round(fit + D + 0.8 * CL.spb * FPS))]
            name = self.names[j]; sm = shape_mask(name); h, w = sm.shape
            hx, hy = self.HOLE[0] - w // 2, self.HOLE[1] - h // 2
            kf = []
            for q, f in enumerate(before):
                if q == len(before) - 1:                 # the near miss, just before the fit
                    if name in ASYM and r.random() < 0.5: kf.append((f, hx, hy, True))
                    else:
                        dx, dy = r.choice([(4, 0), (-4, 0), (0, 4), (0, -4), (3, 3), (-3, 3), (5, 0), (0, 5)])
                        kf.append((f, hx + dx, hy + dy, False))
                else:
                    while True:
                        x, y = r.randrange(28, 232 - w), r.randrange(150, GY - h - 4)
                        if abs(x - hx) + abs(y - hy) > 30: break
                    kf.append((f, x, y, False))
            kf.append((fit, hx, hy, False))
            ex = r.choice([-w - 20, LW + 20]); kf.append((after[0], ex, r.randrange(150, 260), False))
            start = 0 if j == 0 else int(round(fr(a)))
            from_ = (kf[0][1], kf[0][2] - 60) if j == 0 else (r.choice([-w - 20, LW + 20]), 200)
            self.rounds.append(dict(name=name, sm=sm, smm=shape_mask(name, True), kf=kf, fit=fit, D=D, start=start,
                                    from_=from_, hole=(hx, hy), col=SHAPE_COL[name]))
        self.fits = [(R['fit'], R['fit'] + R['D'] - 1) for R in self.rounds]

    def round_at(self, f):
        j = 0
        for q, R in enumerate(self.rounds):
            if f >= R['start']: j = q
        return j

    def pos(self, R, f):
        """Where the shape is at frame f (float) in round R: (x, y, mirrored, moving, squash)."""
        kf = R['kf']; D = R['D']
        def dwell(q): return D if kf[q][0] == R['fit'] else 3
        if f < kf[0][0]:
            (x0, y0), (F1, x1, y1, m1) = R['from_'], kf[0]
            s = R['start']; u = float(ease_out((f - s) / max(1, F1 - s)))
            return x0 + (x1 - x0) * u, y0 + (y1 - y0) * u - 26 * math.sin(math.pi * u), m1, True, 0
        for q in range(len(kf)):
            F, x, y, m = kf[q]
            if q + 1 < len(kf) and f >= kf[q + 1][0]: continue
            if f < F + dwell(q) or q + 1 == len(kf):
                return x, y, m, False, max(0.0, 1 - (f - F) / 3)
            F2, x2, y2, m2 = kf[q + 1]; s = F + dwell(q)
            u = float(ease_out((f - s) / max(1, F2 - s)))
            hop = 18 + 0.04 * math.hypot(x2 - x, y2 - y)
            return x + (x2 - x) * u, y + (y2 - y) * u - hop * math.sin(math.pi * u), m if u < 0.5 else m2, True, 0
        return kf[-1][1], kf[-1][2], False, False, 0

    def state(self, f):
        j = self.round_at(f); R = self.rounds[j]
        x, y, mir, moving, sq = self.pos(R, f)
        xi, yi = int(round(x)), int(round(y))
        fit = (xi, yi) == R['hole'] and not mir
        if fit and not (R['fit'] <= f < R['fit'] + R['D']): yi += 3; fit = False      # never fits by accident on the way
        return j, R, xi, yi, mir, moving, sq, fit

    def tablet(self, c, R, k, e, good=0.0):
        x0, x1, y0, y1 = XC - 62, XC + 62, 196, 322
        m = np.zeros((LH, LW), bool); m[y0:y1, x0:x1] = True
        m[y0:y0 + 3, x0:x0 + 3] = False; m[y0:y0 + 3, x1 - 3:x1] = False
        tex = BY[:LH, :LW] * 0.3 + 0.35 * ((np.arange(LH)[:, None] - y0) / (y1 - y0))
        stone = ramp(tex, [(126, 116, 150), (98, 88, 124), (72, 64, 98)])
        solid(c, m, (98, 88, 124)); sel = m & (tex > 0.45); c[sel] = stone[sel]
        yy, xx = np.mgrid[0:LH, 0:LW]
        mortar = m & ((((yy - y0) % 14) == 13) | ((((xx - x0) + ((yy - y0) // 14) * 11) % 22) == 21))
        c[mortar] = (60, 52, 84)
        c[y0 - 2:y0 + 2, x0 - 2:x1 + 2] = (88, 150, 96); c[y0 - 3, x0 + 6:x1 - 10] = (130, 200, 120)   # moss along the top
        for px in (x0 + 6, x1 - 10):                                                                   # runes lit by the bass
            col = np.array(R['col'], np.float32) * (0.35 + 0.65 * e['bass'])
            c[y0 + 8:y0 + 16, px:px + 4] = INK; c[y0 + 9:y0 + 15, px + 1:px + 3] = col
            glow(c, px + 2, y0 + 12, 6, R['col'], 0.25 + 0.4 * e['bass'])
        c[y1:GY, XC - 50:XC + 50] = (70, 62, 96); c[y1:y1 + 2, XC - 52:XC + 52] = (120, 112, 150)           # the plinth
        c[GY - 4:GY, XC - 58:XC + 58] = (60, 52, 84)
        hm = place(R['sm'], *R['hole'])                                                               # the hole, a recess
        c[hm] = (18, 12, 30); c[hm & ~roll(hm, 2, 0)] = (8, 6, 16); c[hm & ~roll(hm, -1, 0)] = (40, 34, 60)
        edge = cv2.dilate(hm.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~hm
        ants = ((xx + yy + int(k * 8)) % 6) < 3
        col = np.array(MINT if good > 0 else R['col'], np.float32)
        c[edge & ants] = np.minimum(255, col * (0.9 + 0.3 * e['kick']) + 40 * good); c[edge & ~ants] = col * 0.45
        glow(c, R['hole'][0] + R['sm'].shape[1] / 2, R['hole'][1] + R['sm'].shape[0] / 2, 30, R['col'], 0.18 + 0.15 * e['kick'] + 0.5 * good)

    def draw_shape(self, c, R, x, y, mir, sq, f, moving):
        sm = R['smm'] if mir else R['sm']
        if moving:
            for back, a in ((2, 0.3), (4, 0.15)):
                _, R2, gx, gy, gm, _, _, _ = self.state(f - back)
                if R2 is R: tint(c, place(R['smm'] if gm else R['sm'], gx, gy), R['col'], a)
        m = place(sm, x, y + (1 if sq > 0.5 else 0))
        solid(c, m, R['col'], grad=0.6)
        glint = m & ((np.arange(LW)[None, :] - x) + (np.arange(LH)[:, None] - y) == 8); c[glint] = (255, 255, 255)
        if sq > 0: burst(c, x + sm.shape[1] / 2, y + sm.shape[0], 3 - 3 * sq, (220, 210, 240), n=10, speed=1.6, life=6, seed=int(f), g=0)

    def stage(self, c, i, k, e):
        f = float(i); reveal = k >= 18
        if reveal: f = float(self.fits[2][0])
        j, R, x, y, mir, moving, sq, fit = self.state(f)
        good = max(0.0, 1 - (k - 18) / 2) if reveal else 0.0
        self.tablet(c, R, k, e, 1.0 if reveal else 0.0)
        self.draw_shape(c, R, x, y, mir, sq if not reveal else 0, f, moving and not reveal)
        if reveal:
            cx, cy = R['hole'][0] + R['sm'].shape[1] / 2, R['hole'][1] + R['sm'].shape[0] / 2
            dt = (k - 18) * CL.spb * FPS
            burst(c, cx, cy, dt, MINT, n=40, speed=3.2, life=24, seed=7, g=0.04)
            burst(c, cx, cy, dt - 4, GOLD, n=30, speed=2.2, life=24, seed=8, g=0.04)
            glow(c, cx, cy, 40, MINT, 0.6 * good)

    def stamp(self, i):
        """What a viewer paused on frame i would be told: FIT on a fit frame, MISSED BY N PX or MIRRORED while the
        shape rests near the hole, else nothing. Read off the same state the frame is drawn from."""
        j, R, x, y, mir, moving, sq, fit = self.state(float(i))
        if fit: return 'FIT', MINT
        if moving: return None
        d = int(round(math.hypot(x - R['hole'][0], y - R['hole'][1])))
        if mir and d == 0: return 'MIRRORED', ROSE
        if 0 < d <= 12: return 'MISSED BY %d PX' % d, ROSE
        return None

    def hud(self, c, i, k):
        if k < 18:
            j = self.round_at(i)
            header(c, 'PAUSE WHEN', 'IT FITS')
            title(c, 'ROUND %d OF 3' % (j + 1), XC, 128, 2, (220, 226, 255))
            for q in range(3):
                px = XC - 18 + q * 14; c[148:154, px:px + 8] = INK
                c[149:153, px + 1:px + 7] = GOLD if q < j else (255, 255, 255) if q == j else (70, 60, 100)
            title(c, 'FRAME %04d' % i, XC, 162, 1, (170, 176, 210))
            st = self.stamp(i)
            if st: title(c, st[0], XC, 176, 2, WHITE, st[1], plate=(20, 14, 34))
        else:
            D = self.rounds[2]['D']
            header(c, 'IT FIT FOR', '1 FRAME' if D == 1 else '%d FRAMES' % D, col=MINT)
            for q in range(3):
                if k >= 19 + q * 0.75:
                    Dq = self.rounds[q]['D']
                    title(c, 'R%d  %d FRAME%s' % (q + 1, Dq, '' if Dq == 1 else 'S'), XC, 128 + q * 17, 2, WHITE if q == 2 else (200, 206, 240))
            if k >= 21.5:
                a, b = self.fits[2]
                title(c, 'FRAME %04d' % a if a == b else 'FRAMES %04d-%04d' % (a, b), XC, 182, 1, MINT)


# ================================================================ FOLLOW THE GEM
class Cups:
    SLOTS = [XC - 62, XC, XC + 62]
    TABLE = 300

    def __init__(self):
        r = random.Random(SEED * 5 + 2)
        early = hit_frames(2.6, 8.6, 1.0, min_frames=12)
        late = hit_frames(8.6, 15.6, 0.5, min_frames=8)
        if early and late and late[0] - early[-1] < 8: late = late[1:]
        self.swaps = []                                    # (start frame, end frame, slot a, slot b)
        self.gem_pot = r.randrange(3); slots = [0, 1, 2]; prev = fr(2.2)
        for f in early + late:
            dur = min(f - prev, CL.spb * FPS) * 0.88
            if dur < 5: continue
            gs = slots[self.gem_pot]
            a = gs if r.random() < 0.65 else r.randrange(3)
            b = r.choice([s for s in range(3) if s != a])
            self.swaps.append((f - dur, f, a, b)); prev = f
            slots = [b if x == a else a if x == b else x for x in slots]
        self.end_slots = slots
        self.kq = math.ceil(CL.beat(int(self.swaps[-1][1])) + 0.6) if self.swaps else 12
        self.kr = self.kq + 3

    def layout(self, f):
        """Each pot's slot after the swaps finished by frame f, and the swap in progress (or None)."""
        slots = [0, 1, 2]
        for s in self.swaps:
            if f >= s[1]:
                a, b = s[2], s[3]; slots = [b if x == a else a if x == b else x for x in slots]
            elif f >= s[0]: return slots, s
            else: break
        return slots, None

    def pot(self, c, cx, by, shade=1.0):
        Y = np.arange(LH)[:, None]; X = np.arange(LW)[None, :]
        m = (((X - cx) / 23.0) ** 2 + ((Y - (by - 28)) / 22.0) ** 2 <= 1) & (Y <= by - 28)       # a glazed bell
        m |= (np.abs(X - cx) <= 23) & (Y > by - 29) & (Y < by - 8)
        m |= (np.abs(X - cx) <= 27) & (Y >= by - 9) & (Y < by)
        m |= disc_mask(cx, by - 51, 5)
        solid(c, m, np.array((52, 116, 170), np.float32) * shade, np.array((130, 200, 240), np.float32) * shade, np.array((28, 60, 110), np.float32) * shade, grad=0.7)
        band = m & (Y >= by - 25) & (Y < by - 19)
        c[band] = np.array((240, 200, 90), np.float32) * shade
        c[band & (((X - cx) % 6) < 2) & (Y == by - 22)] = np.array((150, 60, 50), np.float32) * shade
        c[m & (Y == by - 9)] = np.array((150, 210, 240), np.float32) * shade
        c[m & (np.abs(X - (cx - 12)) < 2) & (Y > by - 42) & (Y < by - 30)] = np.array((200, 235, 255), np.float32) * shade   # the shine

    def gem(self, c, cx, by, a=1.0, k=0):
        m = poly_mask([(cx - 8, by - 10), (cx + 8, by - 10), (cx + 11, by - 7), (cx, by), (cx - 11, by - 7)])
        solid(c, m, (80, 230, 255), (220, 255, 255), (30, 120, 200))
        c[m & (np.arange(LH)[:, None] < by - 7)] = (170, 250, 255)
        glow(c, cx, by - 6, 18, (80, 200, 255), 0.5 * a)
        if int(k * 4) % 2 == 0: c[by - 14:by - 11, cx + 6] = WHITE; c[by - 13, cx + 5:cx + 8] = WHITE

    def table(self, c):
        y = self.TABLE; x0, x1 = 18, 242
        m = np.zeros((LH, LW), bool); m[y:y + 7, x0:x1] = True
        solid(c, m, (120, 76, 50)); c[y + 1:y + 2, x0 + 2:x1 - 2] = (170, 110, 70)
        c[y + 3:y + 6, x0 + 4:x1 - 4:7] = (90, 56, 38)
        for lx in (x0 + 10, x1 - 16):
            lm = np.zeros((LH, LW), bool); lm[y + 8:GY, lx:lx + 6] = True; solid(c, lm, (96, 60, 40))

    def stage(self, c, i, k, e):
        self.table(c); f = float(i); by = self.TABLE
        lift = 0.0
        if k < 2: lift = 1.0 - float(ease_in_out((k - 1.4) / 0.6))
        if k >= self.kr: lift = float(ease_out((k - self.kr) / 0.6))
        slots, sw = self.layout(f)
        if k >= self.kr: slots, sw = self.end_slots, None
        a = b = None; u = 0.0
        if sw is not None: s0, s1, a, b = sw; u = float(ease_in_out((f - s0) / (s1 - s0)))
        gem_x = self.SLOTS[slots[self.gem_pot]]
        if lift > 0.02: self.gem(c, gem_x, by, lift, k)
        pots = []
        for p in range(3):
            s = slots[p]; x = float(self.SLOTS[s]); y = by - int(58 * lift); front = 0
            if a is not None and s in (a, b):
                t = b if s == a else a; x = self.SLOTS[s] + (self.SLOTS[t] - self.SLOTS[s]) * u
                if s == a: y -= int(round(16 * math.sin(math.pi * u))); front = -1
                else: y += int(round(4 * math.sin(math.pi * u))); front = 1
                if 0.1 < u < 0.9:                                                    # speed lines behind the moving pots
                    d = 1 if self.SLOTS[t] > self.SLOTS[s] else -1
                    for sl in range(3):
                        yy = y - 38 + sl * 12; xa = int(x) - d * (31 + 4 * sl)
                        c[yy, min(xa, xa - d * 10):max(xa, xa - d * 10)] = (230, 220, 250)
            pots.append((front, x, y, p))
        for front, x, y, p in sorted(pots):
            self.pot(c, int(round(x)), y, 0.8 if front < 0 else 1.0)
        for kb in (2.0, self.kr):
            dt = (k - kb) * CL.spb * FPS
            for s in range(3): burst(c, self.SLOTS[s], by - 2, dt, (220, 200, 180), n=10, speed=1.4, life=10, seed=s, g=0.02)
        if k >= self.kr:
            dt = (k - self.kr) * CL.spb * FPS
            burst(c, gem_x, by - 10, dt - 6, GOLD, n=36, speed=2.6, life=26, seed=3)
            burst(c, gem_x, by - 10, dt - 9, (80, 230, 255), n=24, speed=1.8, life=26, seed=4)
        if self.kq <= k < self.kr:
            for s in range(3):
                title(c, str(s + 1), self.SLOTS[s], by - 90, 3, WHITE, GOLD)

    def hud(self, c, i, k):
        n = sum(1 for s in self.swaps if i >= s[1])
        if k < self.kq:
            header(c, 'FOLLOW', 'THE GEM', sub=('SWAP %d' % n) if n else 'SOUND ON')
        elif k < self.kr:
            header(c, 'WHICH POT?'); countdown(c, k, self.kq, y=104)
        else:
            header(c, 'POT %d' % (self.end_slots[self.gem_pot] + 1), sub='%d SWAPS, ALL ON THE BEAT' % len(self.swaps), col=MINT)


# ================================================================ WATCH THE ORDER
CRYSTALS = [('RED', (255, 56, 64)), ('YELLOW', (255, 214, 50)), ('GREEN', (70, 226, 90)), ('CYAN', (60, 220, 255)),
            ('PURPLE', (170, 90, 255)), ('WHITE', (236, 236, 246))]      # six colours no one mixes up


class Memory:
    POS = [(XC - 66, 238), (XC, 228), (XC + 66, 238), (XC - 66, 334), (XC, 324), (XC + 66, 334)]   # base of each crystal

    def __init__(self):
        r = random.Random(SEED * 7 + 3)
        self.order = r.sample(range(6), 6)
        hs = hit_frames(2.5, 14.5, 0.9, min_frames=12)[:6]
        if len(hs) < 6: hs = [int(round(fr(2.5 + 1.5 * j))) for j in range(6)]
        self.flash = hs
        self.q = r.randrange(2, 7)                       # ask which lit 2nd .. 6th
        self.kq = math.ceil(CL.beat(hs[-1]) + 1.2); self.kr = self.kq + 3

    def crystal(self, c, j, lit, k, e, badge=None):
        x, by = self.POS[j]; name, col = CRYSTALS[j]
        pm = np.zeros((LH, LW), bool); pm[by - 6:by + 4, x - 16:x + 16] = True
        solid(c, pm, (84, 76, 110)); c[by - 6, x - 15:x + 15] = (140, 130, 170)
        c[by - 2:by + 1, x - 3:x + 3] = np.array(col, np.float32) * (0.3 + 0.7 * lit)            # the rune
        h, w = 40, 11
        m = poly_mask([(x - w, by - 6), (x - w, by - h + 8), (x, by - h - 2), (x + w, by - h + 8), (x + w, by - 6)])
        b = 0.42 + 0.06 * math.sin(k * 1.5 + j) + 0.58 * lit
        base = np.minimum(255, np.array(col, np.float32) * min(1.0, b) + 30 * lit * lit)
        solid(c, m, base, np.minimum(255, base * 1.25 + 50), base * 0.6)
        right = m & (np.arange(LW)[None, :] > x); c[right] = c[right] * 0.78
        c[m & (np.abs(np.arange(LW)[None, :] - (x - 4)) < 1) & (np.arange(LH)[:, None] < by - 14)] = np.minimum(255, base * 1.4 + 60)
        glow(c, x, by - 20, 16 + 10 * lit, col, 0.18 + 0.9 * lit)
        if lit > 0.3:                                          # a beam of light up out of it
            bw = int(3 + 4 * lit); y0 = 170
            c[y0:by - h, x - bw:x + bw] += np.array(col, np.float32) * 0.35 * lit * (BY[y0:by - h, x - bw:x + bw] > 0.4)[..., None]
        if badge is not None:
            title(c, str(badge), x, by - h - 22, 2, WHITE, GOLD, plate=(20, 14, 34))

    def stage(self, c, i, k, e):
        f = float(i)
        for j in range(6):
            lit = 0.0; badge = None
            if k < self.kr:
                for q, F in enumerate(self.flash):
                    if self.order[q] == j and f >= F: lit = max(lit, math.exp(-(f - F) / 7.0))
            else:
                for q in range(6):
                    kb = self.kr + 0.5 * q
                    if self.order[q] == j and k >= kb:
                        lit = max(0.35 if q + 1 != self.q or k < self.kr + 3 else 0.6 + 0.4 * abs(math.sin(k * 3)), math.exp(-(k - kb) * 3)); badge = q + 1
            self.crystal(c, j, lit, k, e, badge)
            for q, F in enumerate(self.flash):
                if self.order[q] == j and k < self.kr:
                    x, by = self.POS[j]; burst(c, x, by - 24, f - F, CRYSTALS[j][1], n=22, speed=2.4, life=16, seed=q, g=0.03)
        if k >= self.kr + 3:
            j = self.order[self.q - 1]; x, by = self.POS[j]
            dt = (k - self.kr - 3) * CL.spb * FPS; rr = 27 + 2 * math.sin(k * 6)
            ring = disc_mask(x, by - 22, rr) & ~disc_mask(x, by - 22, rr - 2)
            c[ring] = CRYSTALS[j][1]
            burst(c, x, by - 22, dt, GOLD, n=34, speed=2.6, life=24, seed=11)

    def hud(self, c, i, k):
        if k < self.kq:
            n = sum(1 for F in self.flash if i >= F)
            header(c, 'WATCH THE', 'ORDER', sub='ONE QUESTION AT THE END')
            for q in range(6):
                px = XC - 41 + q * 14; c[136:144, px:px + 10] = INK
                c[137:143, px + 1:px + 9] = (255, 255, 255) if q < n else (60, 52, 90)
        elif k < self.kr:
            header(c, 'WHICH LIT', ordinal(self.q) + '?'); countdown(c, k, self.kq, y=124)
        elif k >= self.kr + 3:
            name, col = CRYSTALS[self.order[self.q - 1]]
            header(c, ordinal(self.q) + ': ' + name, col=col)
        else:
            header(c, 'THE ORDER')


# ================================================================ COUNT THE FIREWORKS
FW_COLS = [((255, 90, 120), (255, 220, 120)), ((120, 220, 255), (255, 255, 255)), ((180, 120, 255), (255, 150, 230)),
           ((120, 255, 160), (255, 255, 160)), ((255, 170, 60), (255, 90, 60))]


class Count:
    def __init__(self):
        r = random.Random(SEED * 11 + 4)
        def thinned(fs):
            out = []
            for f in fs:
                if not out or f - out[-1] >= 4: out.append(f)
            return out
        thin = thinned([f for f in CL.snare_frames if fr(0.7) <= f < fr(17)])
        self.what = 'ONE ON EVERY SNARE' if EXACT else 'ALL ON THE DRUMS'
        if not 6 <= len(thin) <= 18:                     # too few snares to be a test (or too many to count): use the hits
            thin = thinned(hit_frames(0.7, 17, 0.9)); self.what = 'ALL ON THE DRUMS'
        self.bursts = []
        for q, f in enumerate(thin):
            rise = int(min(16, 0.75 * CL.spb * FPS))
            best = None
            for _ in range(120):                                  # spread out, so the tally's numbers never sit on each other
                x, y = r.randrange(40, 220), r.randrange(154, 226)    # the top 40 % of the sky under the header: clear of the skyline's lights
                gap = min([math.hypot(x - B['x'], y - B['y']) for B in self.bursts] or [99])
                if best is None or gap > best[0]: best = (gap, x, y)
                if gap > 34: break
            _, x, y = best                                        # crowded: the place farthest from the others
            self.bursts.append(dict(f=f, rise=rise, x0=r.randrange(40, 220), x=x, y=y,
                                    cols=FW_COLS[r.randrange(len(FW_COLS))], seed=q, kind=r.choice(['ring', 'peony', 'willow'])))
        self.n = len(self.bursts)
        self.kq = max(19, math.ceil(CL.beat(thin[-1]) + 1.0) if thin else 19)
        self.kr = self.kq + 3

    def firework(self, c, B, f, scale=1.0, flash=True):
        dt = f - B['f']
        if -B['rise'] <= dt < 0:                                  # the rocket climbing, with its trail
            u = (dt + B['rise']) / B['rise']
            def at(uu):
                u2 = 1 - (1 - max(0.0, uu)) ** 2
                return B['x0'] + (B['x'] - B['x0']) * u2, GY - 10 + (B['y'] - GY + 10) * u2
            for s in range(8):
                px, py = at(u - s * 0.03)
                if 0 <= px < LW and 0 <= py < LH: c[int(py), int(px)] = (255, 220 - 20 * s, 150 - 15 * s)
            x, y = at(u); c[int(y) - 1:int(y) + 1, int(x)] = WHITE
        if 0 <= dt < 34:
            a = 1 - dt / 34; (c1, c2) = B['cols']; r = random.Random(B['seed'])
            if flash and dt < 6: c[:GY] += np.array(c1, np.float32) * 0.10 * (1 - dt / 6)
            glow(c, B['x'], B['y'], 34 * scale, c1, 0.9 * a * a)
            if dt < 3: glow(c, B['x'], B['y'], 10 * scale, (255, 255, 255), 1.5)
            n = 56 if B['kind'] != 'willow' else 40
            g = 0.03 if B['kind'] != 'willow' else 0.07
            drag = (1 - math.exp(-dt / 9)) * 9
            for j in range(n):
                ang = 2 * math.pi * j / n + r.random() * 0.12
                v = (6.0 if B['kind'] == 'ring' else 6.0 * (0.45 + 0.55 * r.random())) * scale
                if B['kind'] == 'ring' and j % 2: v *= 0.55                                 # a ring inside the ring
                px = B['x'] + math.cos(ang) * v * drag; py = B['y'] + math.sin(ang) * v * drag + g * dt * dt * scale
                if dt > 22 and (j + int(dt)) % 3 == 0: continue                    # crackle at the end
                col = np.array(c1 if j % 2 else c2, np.float32) * (0.45 + 0.55 * a)
                for s in range(5 if B['kind'] == 'willow' else 4):
                    qx = int(px - math.cos(ang) * s * 1.6 * min(1, v / 4)); qy = int(py - math.sin(ang) * s * 1.6 * min(1, v / 4) - s * (0.8 if B['kind'] == 'willow' else 0))
                    if 0 <= qx < LW - 1 and 0 <= qy < GY - 1:
                        if s == 0 and scale > 0.8: c[qy:qy + 2, qx:qx + 2] = np.minimum(255, col * 1.2 + 40)
                        else: c[qy, qx] = col * (1 - 0.18 * s)

    def quiet(self, k): return 1.0 if k < self.kr else max(0.0, 1 - (k - self.kr))     # the small lights come back for the tally

    def stage(self, c, i, k, e):
        f = float(i)
        if k < self.kr:
            for B in self.bursts: self.firework(c, B, f)
        else:
            for q, B in enumerate(self.bursts):                   # the tally: each one again, fast, with its number
                kb = self.kr + 2.6 * q / max(1, self.n)
                if k >= kb:
                    dt = min((k - kb) * CL.spb * FPS, 12)
                    self.firework(c, dict(B, f=0), dt, 0.55, flash=False)
                    title(c, str(q + 1), B['x'], B['y'] - 4, 1, WHITE)

    def hud(self, c, i, k):
        if k < self.kq:
            header(c, 'COUNT THE', 'FIREWORKS', sub='NO PAUSING' if k > 2 else 'SOUND ON')
        elif k < self.kr:
            header(c, 'HOW MANY?'); countdown(c, k, self.kq, y=104)
        else:
            done = k >= self.kr + 3
            q = self.n if done else min(self.n, int((k - self.kr) / 2.6 * self.n) + 1)
            title(c, str(q), XC, 66, 8, WHITE, MINT if done else GOLD)
            if done: title(c, self.what, XC, 136, 2, WHITE, MINT)


# ================================================================ EARLY OR LATE
class Beat:
    PAD_Y = GY - 20

    def __init__(self):
        r = random.Random(SEED * 13 + 5)
        hs = hit_frames(1.0, 13.0, 0.75, min_frames=10)
        if len(hs) < 4: hs = [int(round(fr(b))) for b in range(1, 13)]
        self.off = r.choice([-4, -3, 0, 3, 4])
        self.hits = hs; self.lands = hs[:-1] + [hs[-1] + self.off]
        self.kq = math.ceil(CL.beat(max(hs[-1], self.lands[-1])) + 1.0); self.kr = self.kq + 3
        self.ms = int(round(abs(self.off) * 1000 / FPS))

    def y_at(self, f):
        """Height of the creature above the drum at frame f (float), and how squashed it is."""
        L = self.lands
        if f < L[0]:
            u = f / max(1, L[0]); return 70 * (1 - u * u), 0.0
        for a, b in zip(L, L[1:]):
            if a <= f < b:
                u = (f - a) / (b - a); H = min(150, 30 + 1.2 * (b - a))
                return H * 4 * u * (1 - u), max(0.0, 1 - (f - a) / 4)
        return 2 * abs(math.sin((f - L[-1]) / 12)), max(0.0, 1 - (f - L[-1]) / 4)

    def creature(self, c, x, y, sq):
        w = int(25 + 7 * sq); h = int(25 - 7 * sq)
        yy, xx = np.ogrid[0:LH, 0:LW]
        m = ((xx - x) / w) ** 2 + ((yy - (y - h)) / h) ** 2 <= 1
        m |= poly_mask([(x - w + 4, y - 2 * h + 9), (x - w + 8, y - 2 * h - 9), (x - w + 17, y - 2 * h + 4)])
        m |= poly_mask([(x + w - 4, y - 2 * h + 9), (x + w - 8, y - 2 * h - 9), (x + w - 17, y - 2 * h + 4)])
        solid(c, m, (255, 150, 90), (255, 210, 150), (200, 90, 70), grad=0.5)
        belly = ((xx - x) / (w * 0.6)) ** 2 + ((yy - (y - h * 0.7)) / (h * 0.55)) ** 2 <= 1; c[belly & m] = (255, 226, 180)
        for ex in (x - 9, x + 9):
            c[y - h - 9:y - h, ex - 3:ex + 3] = INK; c[y - h - 8:y - h - 6, ex - 2:ex] = WHITE
        c[y - h + 2, x - 3:x + 3] = INK; c[y - h + 3, x - 2:x + 2] = (200, 70, 80)
        c[y - h - 1:y - h + 1, x - 17:x - 13] = (255, 130, 130); c[y - h - 1:y - h + 1, x + 13:x + 17] = (255, 130, 130)

    def drum(self, c, hitglow):
        x0, x1, y = XC - 52, XC + 52, self.PAD_Y
        m = np.zeros((LH, LW), bool); m[y:GY, x0:x1] = True
        solid(c, m, (190, 40, 70), grad=0.6)
        for xx in range(x0 + 4, x1 - 2, 9): c[y + 3:GY - 2, xx] = (240, 200, 120)
        top = poly_mask([(x0 - 2, y - 2), (x1 + 2, y - 2), (x1 + 2, y + 3), (x0 - 2, y + 3)])
        solid(c, top, np.minimum(255, np.array((230, 230, 245)) + 25 * hitglow))
        glow(c, XC, y, 30, (255, 220, 150), 0.6 * hitglow)

    def stage(self, c, i, k, e):
        f = float(i)
        if k >= self.kr:                                     # slow motion of the last landing, four times slower
            span = 16; f = self.lands[-1] - span + ((k - self.kr) * CL.spb * FPS / 4) % (2 * span)
        hy, sq = self.y_at(f)
        since = min([f - L for L in self.lands if f >= L] or [99])
        self.drum(c, max(0.0, 1 - since / 6))
        for L in self.lands:
            dt = f - L
            if 0 <= dt < 12:
                rr = 20 + dt * 3; ring = ((np.arange(LW)[None, :] - XC) / rr) ** 2 + ((np.arange(LH)[:, None] - self.PAD_Y) / (rr * 0.3)) ** 2
                c[(ring <= 1) & (ring > 0.8)] = np.array((255, 230, 170), np.float32) * (1 - dt / 12)
        self.creature(c, XC, int(self.PAD_Y - hy), sq)
        if self.kq <= k < self.kr:
            for q, (s, col) in enumerate((('EARLY', ROSE), ('ON TIME', MINT), ('LATE', GOLD))):
                title(c, s, XC + (q - 1) * 70, 176, 1, col, plate=(20, 14, 34))
        if k >= self.kr:                                    # the timeline: where the hit is, where it landed
            y = 182; x0, x1 = XC - 90, XC + 90; F0 = self.hits[-1] - 16
            sx = lambda q: int(x0 + (q - F0) / 32 * (x1 - x0))
            c[y - 1:y + 2, x0:x1] = (90, 80, 130)
            for q in range(33): c[y - 3:y + 4, sx(F0 + q)] = (130, 120, 170) if q % 2 == 0 else (90, 80, 130)
            col = ROSE if self.off < 0 else GOLD if self.off > 0 else MINT
            hx = sx(self.hits[-1]); c[y - 10:y + 11, hx - 1:hx + 1] = WHITE; title(c, 'HIT', hx, y - 22, 1, WHITE)
            lx = sx(self.lands[-1]); c[y - 8:y + 9, lx - 1:lx + 1] = col; title(c, 'LANDED', lx, y + 14, 1, col)
            cur = sx(f); c[y - 5:y + 6, max(x0, min(x1 - 1, cur))] = (255, 255, 255)

    def hud(self, c, i, k):
        if k < self.kq:
            header(c, 'EARLY OR', 'LATE?', sub='WATCH THE LAST LANDING')
        elif k < self.kr:
            header(c, 'THE LAST', 'ONE WAS...'); countdown(c, k, self.kq, y=124)
        elif self.off == 0:
            header(c, 'ON TIME', sub='EXACTLY ON THE HIT', col=MINT)
        else:
            header(c, 'EARLY' if self.off < 0 else 'LATE', 'BY %d FRAMES' % abs(self.off),
                   sub='%d MS %s THE HIT' % (self.ms, 'BEFORE' if self.off < 0 else 'AFTER'), col=ROSE if self.off < 0 else GOLD)


T = {'pause': Pause, 'cups': Cups, 'memory': Memory, 'count': Count, 'beat': Beat}[TEST]()
VIG = np.clip(1.12 - 0.55 * (((np.arange(LW)[None, :] - LW / 2) / LW) ** 2 * 2 + ((np.arange(LH)[:, None] - LH / 2) / LH) ** 2 * 1.4), 0.6, 1.0)[..., None].astype(np.float32)
_yy, _xx = np.mgrid[0:LH, 0:LW]
_box = np.exp(-np.maximum(0, np.abs(_xx - XC) - 80) ** 2 / 300.0) * np.exp(-np.maximum(0, np.abs(_yy - 248) - 92) ** 2 / 300.0)
DIM = (1 - {'city': 0.42, 'forest': 0.28, 'cave': 0.22}[WORLD_NAME] * _box)[..., None].astype(np.float32)   # the stage is darker than the world around it, so the test reads
SCAN = np.ones((H, 1, 1), np.float32)
if CRT: SCAN[3::4] = 0.84


def frame(i):
    k = CL.beat(i); t = i / FPS
    e = dict(kick=float(CL.kick[i]), snare=float(CL.snare[i]), hat=float(CL.hat[i]), bass=float(min(1.2, CL.bass[i])), vox=float(min(1.2, CL.vox[i])))
    cam = 12 * math.sin(t * 0.33) + 4 * math.sin(t * 0.81 + 1)
    c = np.zeros((LH, LW, 3), np.float32)
    if hasattr(T, 'quiet'): WORLD.quiet = T.quiet(k)
    WORLD.back(c, t, k, e['kick'], e['snare'], e['hat'], e['bass'], cam)
    c *= DIM
    T.stage(c, i, k, e)
    WORLD.front(c, t, k, e['kick'], e['bass'], e['vox'], cam)
    if e['kick'] > 0.55: c = np.concatenate([c[:1], c[:-1]], 0)            # the world hops a pixel on the kick
    c *= VIG
    T.hud(c, i, k)
    c = np.clip(c, 0, 255)
    bloom = cv2.resize(cv2.GaussianBlur(np.clip(c - 150, 0, 255), (0, 0), 3.0), (W, H), interpolation=cv2.INTER_LINEAR)
    big = cv2.resize(c, (W, H), interpolation=cv2.INTER_NEAREST) * SCAN + bloom * 0.55
    paste(big, text(CREDIT, F(DEJAVU, 30), (236, 236, 246), stroke=3), W / 2, 1448)
    return np.clip(big, 0, 255).astype(np.uint8)


if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
