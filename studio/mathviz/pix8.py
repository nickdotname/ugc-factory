"""Detailed 2D pixel-art worlds for the 8-bit tests (studio/mathviz/tests8.py), drawn entirely in code.

A world is a stack of layers on a 270 x 480 canvas (blown up 4x with hard edges): a dithered sky, a far layer, a
middle layer and the ground, then a foreground in front of the test. Layers are wider than the screen and slide at
different speeds as the camera drifts (parallax). The music lights the world: windows, lanterns, crystals and string
lights pulse with the kick and the bass, stars twinkle on the hats, and particles (dust, fireflies, spores) drift
through. Everything is drawn in a few flat colours per material with ordered (Bayer) dithering between them.

Worlds: city (a rooftop at night), forest (a moonlit clearing under an aurora), cave (a crystal cave).
Helpers used by the tests: ramp (dithered palette fills), solid (an outlined, lit pixel shape from a mask),
glow (a banded pixel light), tmask / title (our own 5x7 pixel font, outlined and gradient-filled)."""
import math, random
import numpy as np, cv2

LW, LH = 270, 480
PAD = 26                                   # overscan on each side for parallax
WX = LW + 2 * PAD
GY = 352                                   # the ground line, where props stand
INK = (14, 10, 24)
_BAY = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16
K3 = np.ones((3, 3), np.uint8)


def bayer(h, w, y0=0, x0=0):
    return np.tile(_BAY, (h // 4 + 3, w // 4 + 3))[y0 % 4:y0 % 4 + h, x0 % 4:x0 % 4 + w]


BY = bayer(LH, WX)


def ramp(t, pal, th=None):
    """Colours for values t (0..1) from a palette, dithered between neighbouring entries: flat pixel-art shading."""
    pal = np.asarray(pal, np.float32); n = len(pal)
    if th is None: th = BY[:t.shape[0], :t.shape[1]]
    p = np.clip(t, 0, 1) * (n - 1); i = np.floor(p).astype(int); f = p - i
    return pal[np.where(f > th, np.minimum(i + 1, n - 1), i)]


def noise(h, w, cell, seed):
    g = np.random.default_rng(seed).random((h // cell + 3, w // cell + 3)).astype(np.float32)
    return cv2.resize(g, (g.shape[1] * cell, g.shape[0] * cell), interpolation=cv2.INTER_CUBIC)[:h, :w]


def fbm(h, w, seed, cells=(48, 24, 12, 6, 3)):
    out = np.zeros((h, w), np.float32); a = 1.0; s = 0.0
    for j, cl in enumerate(cells): out += a * noise(h, w, cl, seed + 31 * j); s += a; a *= 0.55
    out /= s; return (out - out.min()) / (np.ptp(out) + 1e-6)


def roll(m, dy, dx):
    return np.roll(np.roll(m, dy, 0), dx, 1)


def solid(c, m, base, hi=None, lo=None, ink=INK, rim=True, grad=0.0):
    """Paint mask m as a lit pixel-art shape: a 1 px ink outline, a highlight on the top-left edges, a shadow on the
    bottom-right ones, and optionally a dithered darkening towards the bottom (grad 0..1)."""
    if not m.any(): return
    base = np.array(base, np.float32)
    hi = np.array(hi if hi is not None else np.minimum(255, base * 1.35 + 20), np.float32)
    lo = np.array(lo if lo is not None else base * 0.62, np.float32)
    if ink is not None:
        c[cv2.dilate(m.astype(np.uint8), K3).astype(bool) & ~m] = ink
    c[m] = base
    if grad > 0:
        ys = np.nonzero(m.any(1))[0]; y0, y1 = ys.min(), ys.max() + 1
        t = np.zeros(m.shape, np.float32); t[y0:y1] = np.linspace(0, 1, y1 - y0)[:, None] * grad
        sh = m & (t > BY[:m.shape[0], :m.shape[1]] + 0.35); c[sh] = lo
    if rim:
        c[m & ~roll(m, 1, 0)] = hi; c[m & ~roll(m, 0, 1) & ~roll(m, 1, 0) | (m & ~roll(m, 0, 1))] = hi
        c[m & (~roll(m, -1, 0) | ~roll(m, 0, -1))] = lo


def glow(c, x, y, r, col, a=1.0, bands=4):
    """A pixel light: an additive glow in a few dithered bands around (x, y)."""
    if a <= 0.01 or r < 1: return
    R = int(r * 2.2) + 1; x0, x1 = max(0, int(x) - R), min(c.shape[1], int(x) + R + 1); y0, y1 = max(0, int(y) - R), min(c.shape[0], int(y) + R + 1)
    if x1 <= x0 or y1 <= y0: return
    yy, xx = np.mgrid[y0:y1, x0:x1]; d2 = ((xx - x) ** 2 + (yy - y) ** 2) / (r * r)
    g = np.exp(-d2) * a
    g = np.floor(g * bands + BY[y0 % 4:y0 % 4 + (y1 - y0), x0 % 4:x0 % 4 + (x1 - x0)] * 0.999) / bands
    c[y0:y1, x0:x1] += g[..., None] * np.array(col, np.float32)


def disc_mask(cx, cy, r, h=LH, w=LW):
    yy, xx = np.ogrid[0:h, 0:w]; return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


def poly_mask(pts, h=LH, w=LW):
    m = np.zeros((h, w), np.uint8); cv2.fillPoly(m, [np.round(np.asarray(pts)).astype(np.int32)], 1); return m.astype(bool)


# ---------------------------------------------------------------- text: our own 5x7 font (studio/mathviz/pixel.py)
from pixel import G
_TM = {}


def tmask(s, sc):
    """The mask of a line of pixel text at sc canvas pixels per font pixel."""
    k = (s, sc)
    if k not in _TM:
        s = s.upper(); m = np.zeros((7, max(1, len(s) * 6 - 1)), bool)
        for j, ch in enumerate(s):
            g = G.get(ch, G[' '])
            m[:, j * 6:j * 6 + 5] = np.array([c == '#' for c in g]).reshape(7, 5)
        _TM[k] = np.kron(m, np.ones((sc, sc), bool))
    return _TM[k]


def title(c, s, x, y, sc, top=(255, 255, 255), bottom=None, align='c', ink=INK, plate=None):
    """Outlined pixel text with a hard drop shadow, filled with a vertical gradient (top -> bottom). (x, y) is the
    top-centre (align c), top-left (l) or top-right (r). Returns the text's width."""
    m = tmask(s, sc); h, w = m.shape
    if align == 'c': x = x - w // 2
    elif align == 'r': x = x - w
    o = max(1, sc // 2)
    H, W = h + 2 * o + 2, w + 2 * o + 2
    big = np.zeros((H, W), bool); big[o:o + h, o:o + w] = m
    out = cv2.dilate(big.astype(np.uint8), np.ones((2 * o + 1, 2 * o + 1), np.uint8)).astype(bool)
    shadow = roll(out, o, 0) | out
    X0, Y0 = x - o, y - o
    def put(mask, col):
        ys, xs = np.nonzero(mask); ys = ys + Y0; xs = xs + X0
        ok = (ys >= 0) & (ys < c.shape[0]) & (xs >= 0) & (xs < c.shape[1]); ys, xs = ys[ok], xs[ok]
        if isinstance(col, np.ndarray) and col.ndim == 3: c[ys, xs] = col[ys - Y0, xs - X0]
        else: c[ys, xs] = col
    if plate is not None:
        c[max(0, Y0 - 3):Y0 + H + 3, max(0, X0 - 4):X0 + W + 4] = c[max(0, Y0 - 3):Y0 + H + 3, max(0, X0 - 4):X0 + W + 4] * 0.35 + np.array(plate, np.float32) * 0.65
    put(shadow, tuple(np.array(ink) * 0.6)); put(out, ink)
    if bottom is None: put(big, top)
    else:
        t = np.clip((np.arange(H) - o) / max(1, h - 1), 0, 1)[:, None] * np.ones((1, W))
        cols = ramp(t, [top, bottom], bayer(H, W))
        put(big, cols)
    return w


# ---------------------------------------------------------------- the worlds
PALS = {
    'city': dict(sky=[(10, 8, 30), (22, 14, 52), (44, 22, 80), (86, 36, 104), (150, 62, 118), (214, 104, 120)],
                 far=(46, 30, 86), mid=(30, 22, 58), win=[(255, 214, 120), (255, 170, 90), (130, 220, 255), (255, 120, 170)],
                 ground=[(36, 30, 52), (52, 44, 72), (74, 62, 96), (98, 84, 120)], accent=(255, 92, 170)),
    'forest': dict(sky=[(4, 10, 28), (8, 22, 48), (14, 38, 72), (24, 58, 96), (40, 82, 116), (70, 110, 130)],
                   far=(38, 56, 96), mid=(14, 34, 46), ground=[(18, 40, 30), (30, 66, 44), (52, 100, 56), (96, 150, 70)],
                   dirt=[(26, 18, 22), (44, 30, 30), (66, 46, 40), (90, 66, 52)], accent=(120, 255, 200)),
    'cave': dict(sky=[(6, 4, 14), (12, 8, 26), (20, 14, 40), (30, 22, 54), (42, 30, 66)],
                 far=(34, 26, 60), mid=(22, 16, 40), ground=[(20, 16, 34), (34, 28, 54), (52, 44, 78), (76, 66, 104)],
                 crystal=[(80, 240, 255), (255, 110, 230), (150, 120, 255), (120, 255, 170)], accent=(80, 240, 255)),
}


class World:
    def __init__(self, theme, seed):
        self.theme = theme; self.P = PALS[theme]; self.seed = seed
        r = random.Random(seed); self.r = r
        self.sky = np.zeros((LH, LW, 3), np.float32)
        self.far = np.zeros((LH, WX, 4), np.float32); self.mid = np.zeros((LH, WX, 4), np.float32)
        self.ground = np.zeros((LH, WX, 4), np.float32); self.fg = np.zeros((LH, WX, 4), np.float32)
        self.stars, self.windows, self.blinks, self.lights, self.bulbs, self.crystals = [], [], [], [], [], []
        self.quiet = 0.0                       # 0..1: a test that needs the eye on the sky (count) turns the small lights down
        getattr(self, '_' + theme)(r)
        nr = random.Random(seed + 9)
        self.motes = [(nr.uniform(0, LW), nr.uniform(60, GY), nr.uniform(0, 6.28), nr.uniform(0.4, 1.0), nr.random()) for _ in range(46)]

    # ---- building helpers
    @staticmethod
    def _put(L, m, rgb):
        L[m, :3] = rgb if not isinstance(rgb, np.ndarray) or rgb.ndim == 1 else rgb[m]
        L[m, 3] = 1.0

    def _sky_grad(self, pal, y0=0, y1=GY + 20):
        t = np.clip((np.arange(LH)[:, None] - y0) / (y1 - y0), 0, 1) * np.ones((1, LW))
        self.sky[:] = ramp(t, pal, BY[:, :LW])

    def _starfield(self, r, n, ymax):
        for _ in range(n):
            self.stars.append((r.randrange(LW), r.randrange(0, ymax), r.random(), r.random() < 0.12))

    def _moon(self, cx, cy, rad, col=(244, 236, 206)):
        m = disc_mask(cx, cy, rad)
        self.sky[m] = col
        t = np.zeros((LH, LW), np.float32); yy, xx = np.mgrid[0:LH, 0:LW]
        t = ((xx - cx + rad * 0.55) ** 2 + (yy - cy + rad * 0.45) ** 2) / (rad * rad * 2.2)
        sh = m & (t > 0.5 + 0.4 * BY[:, :LW]); self.sky[sh] = np.array(col) * 0.78
        for dx, dy, cr in ((-4, -3, 3), (5, 2, 2), (-1, 6, 2), (3, -6, 1)):
            self.sky[disc_mask(cx + dx, cy + dy, cr) & m] = np.array(col) * 0.7
        self.lights.append(dict(x=cx, y=cy, r=rad * 2.6, col=(70, 66, 90), base=0.8, kick=0.0, bass=0.15, layer=None))

    def _ridge(self, L, base_y, amp, seed, col, cell=40, snow=None, rough=0.4):
        xs = np.arange(WX)
        h = fbm(1, WX, seed, cells=(cell, cell // 2, cell // 4, 4))[0]
        top = (base_y - amp * h).astype(int)
        yy = np.arange(LH)[:, None]
        m = yy >= top[None, :]
        self._put(L, m, np.array(col, np.float32))
        tex = fbm(LH, WX, seed + 1, cells=(16, 8, 4))
        dark = m & (tex > 0.62 + 0.3 * BY[:, :WX]); L[dark, :3] = np.array(col) * 0.82
        rimm = m & ~np.roll(m, 1, 0); L[rimm, :3] = np.minimum(255, np.array(col) * 1.4 + 12)
        if snow is not None:
            depth = yy - top[None, :]
            sm = m & (depth < 3 + 4 * BY[:, :WX]) & (top[None, :] < base_y - amp * 0.55)
            L[sm, :3] = snow
        return top

    # ---- city: a rooftop at night, a skyline behind
    def _city(self, r):
        P = self.P; self._sky_grad(P['sky'], 0, GY - 18)
        self._starfield(r, 110, 250); self._moon(222, 44, 13)
        # clouds: dithered bands, lit pink from below
        cl = fbm(LH, LW, self.seed + 5, cells=(60, 30, 12, 6))
        band = np.exp(-((np.arange(LH)[:, None] - 175) / 26.0) ** 2) + 0.7 * np.exp(-((np.arange(LH)[:, None] - 235) / 14.0) ** 2)
        cm = cl * band > 0.42 + 0.12 * BY[:, :LW]
        self.sky[cm] = self.sky[cm] * 0.55 + np.array((120, 60, 120), np.float32) * 0.45
        cm2 = cl * band > 0.56 + 0.12 * BY[:, :LW]; self.sky[cm2] = (170, 92, 140)
        # far skyline
        x = 0
        while x < WX:
            w = r.randrange(8, 20); h = r.randrange(30, 90)
            self._put(self.far, self._rect(GY - 86 - h, GY, x, x + w), np.array(P['far'], np.float32))
            for wy in range(GY - 86 - h + 4, GY - 4, 5):
                for wx in range(x + 2, x + w - 2, 4):
                    if r.random() < 0.18 and wx < WX: self.far[wy, wx, :3] = (150, 110, 160)
            if r.random() < 0.3 and x + w // 2 < WX: self.far[GY - 92 - h:GY - 86 - h, x + w // 2, :3] = P['far']; self.far[GY - 92 - h:GY - 86 - h, x + w // 2, 3] = 1
            x += w + r.randrange(0, 4)
        # middle skyline: big buildings with lit windows, water towers, antennas
        x = -2
        while x < WX:
            w = r.randrange(18, 40); h = r.randrange(40, 120); top = GY - 26 - h
            col = np.array(P['mid'], np.float32) * r.uniform(0.85, 1.2)
            self._put(self.mid, self._rect(top, GY + 2, x, x + w), col)
            self.mid[top, x:x + w, :3] = col * 1.6; self.mid[top:GY + 2, x, :3] = col * 1.3      # lit edges
            self.mid[top:GY + 2, min(WX - 1, x + w - 1), :3] = col * 0.7
            for wy in range(top + 5, GY - 18, 7):
                for wx in range(x + 3, x + w - 4, 6):
                    self.windows.append((wx, wy, r.randrange(4), r.random(), r.random()))
            if r.random() < 0.35 and w > 22:                                              # a water tower
                tx = x + r.randrange(4, w - 14)
                self._put(self.mid, self._rect(top - 14, top - 4, tx, tx + 10), col * 1.1)
                self._put(self.mid, self._rect(top - 17, top - 14, tx + 1, tx + 9), col * 1.4)
                for lx in (tx + 1, tx + 8): self._put(self.mid, self._rect(top - 4, top, lx, lx + 1), col)
            elif r.random() < 0.5:                                                          # an antenna with a red light
                ax = x + w // 2; ah = r.randrange(10, 24)
                self._put(self.mid, self._rect(top - ah, top, ax, ax + 1), col * 1.2)
                self.blinks.append((ax, top - ah - 1, r.random()))
            x += w + r.randrange(-2, 3)
        # a neon sign frame on one building (abstract bars, no words)
        nx = PAD + r.randrange(20, 60); self.neon = (nx, 222, 34, 16)
        # rooftop: a parapet ledge and the roof under it
        yy, xx = np.mgrid[0:LH, 0:WX]
        roof = yy >= GY
        tex = fbm(LH, WX, self.seed + 7, cells=(24, 12, 6, 3))
        self._put(self.ground, roof, ramp(0.25 + 0.55 * tex - 0.25 * np.clip((yy - GY) / 160, 0, 1), P['ground'], BY[:, :WX]))
        ledge = (yy >= GY) & (yy < GY + 8)
        self._put(self.ground, ledge, np.array((118, 104, 140), np.float32))
        self.ground[(yy == GY), :3] = (168, 152, 190); self.ground[(yy == GY + 7), :3] = (60, 50, 80)
        brick = (yy >= GY + 8) & (yy < GY + 40) & (((yy - GY - 8) % 6 == 0) | (((xx + ((yy - GY - 8) // 6) * 6) % 12) == 0))
        self.ground[brick, :3] = self.ground[brick, :3] * 0.7
        for k in range(6):                                                                  # roof vents and an AC box
            vx = r.randrange(0, WX - 30); vy = r.randrange(GY + 50, LH - 30)
            self._put(self.ground, self._rect(vy, vy + 18, vx, vx + 26), np.array((80, 74, 104), np.float32))
            self.ground[vy, vx:vx + 26, :3] = (130, 122, 160)
            for gy in range(vy + 4, vy + 16, 3): self.ground[gy, vx + 3:vx + 23, :3] = (50, 44, 70)
        for _ in range(5):                                                                  # puddles that hold the neon
            px, py, pw = r.randrange(0, WX), r.randrange(GY + 44, LH - 20), r.randrange(14, 34)
            pm = ((xx - px) / pw) ** 2 + ((yy - py) / 3.5) ** 2 <= 1
            self.ground[pm, :3] = (30, 24, 50); self.ground[pm & (BY[:, :WX] > 0.75), :3] = (200, 90, 170)
            self.ground[pm & ~np.roll(pm, 1, 0), :3] = (120, 100, 160)
        for _ in range(3):                                                                  # cables across the roof
            y0c, y1c = r.randrange(GY + 20, LH), r.randrange(GY + 20, LH)
            for x in range(WX):
                y = min(LH - 1, int(y0c + (y1c - y0c) * x / WX + 3 * math.sin(x * 0.04))); self.ground[y, x, :3] = (22, 18, 34)
        # string lights sagging across behind the stage
        for j in range(0, WX, 9):
            sy = GY - 22 - int(16 * math.sin(math.pi * j / WX)) + 4
            self.bulbs.append((j, sy, j // 9))
        # foreground: a railing at the bottom and a pipe at the left
        fm = (yy >= 446) & (yy < 451) | (yy >= 446) & ((xx % 22) < 3)
        self._put(self.fg, fm, np.array((24, 20, 36), np.float32)); self.fg[(yy == 446) & fm, :3] = (90, 80, 120)
        pm = (xx >= 6) & (xx < 16) & (yy >= 330)
        self._put(self.fg, pm, ramp(np.clip((xx - 6) / 10.0, 0, 1) * np.ones_like(yy, dtype=np.float32), [(40, 36, 60), (90, 84, 120), (52, 46, 76), (24, 20, 36)], BY[:, :WX]))

    def _rect(self, y0, y1, x0, x1):
        m = np.zeros((LH, WX), bool); m[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True; return m

    # ---- forest: a moonlit clearing under an aurora
    def _forest(self, r):
        P = self.P; self._sky_grad(P['sky'], 0, GY - 18)
        self._starfield(r, 150, 270); self._moon(44, 44, 11, (236, 240, 220))
        self._ridge(self.far, GY - 68, 110, self.seed + 2, P['far'], cell=60, snow=(190, 210, 230))
        self._ridge(self.far, GY - 46, 50, self.seed + 3, np.array(P['far']) * 0.75, cell=30)
        # two rows of pines
        for row, (yb, hmin, hmax, col) in enumerate(((GY - 18, 34, 70, np.array(P['mid']) * 1.25), (GY, 50, 100, np.array(P['mid'])))):
            x = -6
            while x < WX + 6:
                h = r.randrange(hmin, hmax); w = h // 3 + r.randrange(0, 5)
                pts = []
                tiers = 4
                for t in range(tiers):
                    ty = yb - h + t * h // tiers; by = ty + h // tiers + 6
                    tw = w * (t + 1) / tiers + 2
                    pts.append([(x, ty), (x - tw, by), (x + tw, by)])
                m = np.zeros((LH, WX), np.uint8)
                for p in pts: cv2.fillPoly(m, [np.array(p, np.int32)], 1)
                m = m.astype(bool); self._put(self.mid, m, col * r.uniform(0.9, 1.1))
                lit = m & ~np.roll(m, 1, 1) & (BY[:, :WX] > 0.3); self.mid[lit, :3] = col * 1.7 + 6            # moonlight on the left edges
                self.mid[yb - 4:yb + 8, x:x + 2, :3] = (30, 22, 24); self.mid[yb - 4:yb + 8, x:x + 2, 3] = 1
                x += r.randrange(10, 22) if row == 0 else r.randrange(16, 34)
        yy, xx = np.mgrid[0:LH, 0:WX]
        tex = fbm(LH, WX, self.seed + 7, cells=(20, 10, 5, 3))
        edge = GY + (2 * np.sin(xx * 0.21) + 2 * np.sin(xx * 0.057 + 1)).astype(int)
        grass = yy >= edge
        self._put(self.ground, grass, ramp(0.15 + 0.5 * tex + 0.0 * yy, P['ground'], BY[:, :WX]))
        dirt = yy >= edge + 10 + (3 * tex).astype(int)
        self._put(self.ground, dirt, ramp(0.2 + 0.6 * tex - 0.3 * np.clip((yy - GY) / 160, 0, 1), P['dirt'], BY[:, :WX]))
        for _ in range(90):                                                                 # grass blades on the edge
            bx = r.randrange(WX); bh = r.randrange(2, 7); by = int(GY + 2 * math.sin(bx * 0.21) + 2 * math.sin(bx * 0.057 + 1))
            self.ground[by - bh:by, bx, :3] = P['ground'][3] if r.random() < 0.5 else P['ground'][2]; self.ground[by - bh:by, bx, 3] = 1
        for j in range(5):                                                                  # darker strata
            sy = GY + 30 + j * 24 + r.randrange(-4, 4)
            band = (np.abs(yy - sy - 3 * np.sin(xx * 0.05 + j)) < 2 + 1.5 * BY[:, :WX]) & dirt
            self.ground[band, :3] *= 0.72
        for _ in range(9):                                                                  # roots
            x, y = float(r.randrange(WX)), float(GY + 6)
            for s_ in range(r.randrange(20, 60)):
                x += r.uniform(-1.2, 1.2); y += r.uniform(0.4, 1.0)
                if 0 <= int(x) < WX - 1 and y < LH: self.ground[int(y), int(x):int(x) + 2, :3] = (70, 46, 36); self.ground[int(y), int(x), :3] = (98, 70, 52)
        for _ in range(26):                                                                 # stones in the dirt
            sx, sy, sr = r.randrange(WX), r.randrange(GY + 20, LH), r.randrange(2, 6)
            m = (xx - sx) ** 2 + ((yy - sy) * 1.4) ** 2 <= sr * sr
            self.ground[m, :3] = (86, 80, 92); self.ground[m & ~np.roll(m, 1, 0), :3] = (130, 124, 136)
        for j in range(7):                                                                  # glowing mushrooms
            mx = r.randrange(10, WX - 10); my = int(GY + 2 * math.sin(mx * 0.21) + 2 * math.sin(mx * 0.057 + 1)) + r.randrange(0, 3)
            col = [(120, 255, 210), (180, 140, 255), (255, 170, 110)][j % 3]
            self.ground[my - 5:my, mx, :3] = (210, 210, 190); self.ground[my - 5:my, mx, 3] = 1
            cap = (xx - mx) ** 2 + ((yy - (my - 6)) * 1.8) ** 2 <= 12; cap &= yy <= my - 5
            self.ground[cap, :3] = col; self.ground[cap, 3] = 1
            self.lights.append(dict(x=mx, y=my - 6, r=9, col=col, base=0.35, kick=0.6, bass=0.2, layer=1.0))
        # foreground: big ferns at the corners
        for side in (0, 1):
            for j in range(7):
                ang = (0.25 + 0.11 * j) * math.pi * (1 if side == 0 else -1)
                bx = 6 if side == 0 else WX - 6; by = LH + 4; ln = r.randrange(80, 140)
                pts = [(bx + ln * t * math.sin(ang) * (1 if side == 0 else 1), by - ln * t * math.cos(ang) + 30 * t * t) for t in np.linspace(0, 1, 18)]
                for t, (px, py) in enumerate(pts):
                    wdt = max(1, int(6 * (1 - t / 18)))
                    self.fg[max(0, int(py) - 1):int(py) + 1, max(0, int(px) - wdt):int(px) + wdt, :3] = (10, 30, 22) if j % 2 else (16, 44, 30)
                    self.fg[max(0, int(py) - 1):int(py) + 1, max(0, int(px) - wdt):int(px) + wdt, 3] = 1
        self.aurora = True

    # ---- cave: crystal cave
    def _cave(self, r):
        P = self.P
        yy, xx = np.mgrid[0:LH, 0:LW]
        tex = fbm(LH, LW, self.seed + 1, cells=(40, 20, 10, 5, 3))
        self.sky[:] = ramp(0.15 + 0.7 * tex * (0.6 + 0.4 * np.clip(yy / (GY - 18), 0, 1)), P['sky'], BY[:, :LW])
        cr = fbm(LH, LW, self.seed + 4, cells=(30, 15, 7))                                      # crystal veins in the far wall
        self.veins = (np.abs(cr - 0.5) < 0.006 + 0.008 * BY[:, :LW]) & (yy > 60) & (fbm(LH, LW, self.seed + 6, cells=(60, 30)) > 0.55)
        Y, X = np.mgrid[0:LH, 0:WX]
        # stalactites hanging from the top, and pillars
        for L, n, col, ymax in ((self.far, 14, P['far'], 140), (self.mid, 9, P['mid'], 190)):
            for _ in range(n):
                sx = r.randrange(WX); w = r.randrange(5, 16); h = r.randrange(30, ymax)
                m = poly_mask([(sx - w, -2), (sx + w, -2), (sx + 1, h)], LH, WX)
                self._put(L, m, np.array(col, np.float32) * r.uniform(0.85, 1.15))
                L[m & ~np.roll(m, 1, 1), :3] = np.array(col) * 1.7
            for _ in range(n // 2):
                sx = r.randrange(WX); w = r.randrange(6, 14); h = r.randrange(30, 110)
                m = poly_mask([(sx - w, GY + 4), (sx + w, GY + 4), (sx + 2, GY - h)], LH, WX)
                self._put(L, m, np.array(col, np.float32) * 1.1); L[m & ~np.roll(m, 1, 1), :3] = np.array(col) * 1.7
        self._ridge(self.far, GY - 68, 60, self.seed + 3, np.array(P['far']) * 0.9, cell=24)
        # crystal clusters on the middle layer and the ground: each a light that pulses with the bass
        def cluster(L, cx, cy, s, col, light=True):
            for j in range(r.randrange(3, 6)):
                a = r.uniform(-0.6, 0.6); ln = s * r.uniform(0.6, 1.3); w = s * 0.22
                tip = (cx + ln * math.sin(a), cy - ln * math.cos(a))
                pts = [(cx - w * math.cos(a), cy - w * math.sin(a)), (cx + w * math.cos(a), cy + w * math.sin(a)),
                       (tip[0] + w * 0.5 * math.cos(a), tip[1] + w * 0.5 * math.sin(a)), tip]
                m = poly_mask(pts, LH, WX)
                self._put(L, m, np.array(col, np.float32) * 0.55)
                half = m & (X < cx + (Y - cy) * math.tan(a) + 0.5)
                L[half, :3] = np.array(col, np.float32) * 0.85
                L[m & ~np.roll(m, 1, 1), :3] = np.minimum(255, np.array(col, np.float32) * 1.2 + 40)
            if light: self.lights.append(dict(x=cx, y=cy - s * 0.6, r=s * 1.1, col=col, base=0.35, kick=0.25, bass=0.6, layer=1.0 if L is self.ground else 0.45))
        for j in range(5):
            cluster(self.mid, r.randrange(WX), r.randrange(GY - 68, GY - 18), r.randrange(10, 18), P['crystal'][j % 4])
        tex2 = fbm(LH, WX, self.seed + 7, cells=(20, 10, 5, 3))
        edge = GY + (3 * np.sin(X * 0.13) + 2 * np.sin(X * 0.041 + 2)).astype(int)
        floor = Y >= edge
        self._put(self.ground, floor, ramp(0.2 + 0.6 * tex2 - 0.35 * np.clip((Y - GY) / 160, 0, 1), P['ground'], BY[:, :WX]))
        self.ground[floor & ~np.roll(floor, 1, 0), :3] = (110, 98, 140)
        self.puddle = (Y > GY + 30) & (Y < GY + 44) & ((X - WX * 0.55) ** 2 / 3600 + (Y - GY - 37) ** 2 / 40 < 1)
        self.ground[self.puddle, :3] = (16, 14, 34)
        for j in range(6):
            cluster(self.ground, r.randrange(8, WX - 8), int(GY + r.randrange(2, 8)), r.randrange(12, 22), P['crystal'][(j + 1) % 4])
        # foreground: big dark stalactites at the top corners and rocks at the bottom
        for sx, w, h in ((PAD - 8, 26, 110), (WX - PAD + 6, 30, 140), (PAD + 40, 10, 60)):
            m = poly_mask([(sx - w, -2), (sx + w, -2), (sx + 3, h)], LH, WX)
            self._put(self.fg, m, np.array((14, 10, 24), np.float32)); self.fg[m & ~np.roll(m, 1, 1), :3] = (44, 36, 70)
        for sx, w in ((PAD + 4, 46), (WX - PAD - 6, 54)):
            m = ((X - sx) ** 2 / (w * w) + (Y - LH - 10) ** 2 / 2500) < 1
            self._put(self.fg, m, np.array((16, 12, 28), np.float32)); self.fg[m & ~np.roll(m, 1, 0), :3] = (54, 44, 84)

    # ---------------------------------------------------------------- per frame
    @staticmethod
    def _layer(c, L, off):
        sub = L[:, PAD + off:PAD + off + LW]; m = sub[..., 3] > 0
        c[m] = sub[..., :3][m]

    def back(self, c, t, beat, kick, snare, hat, bass, cam):
        """Everything behind the test: sky, far, middle and ground layers, their lights."""
        c[:] = self.sky
        P = self.P
        if getattr(self, 'aurora', False):                                                  # the aurora: two ribbons that drift
            yy, xx = np.mgrid[0:200, 0:LW]
            for j, (col, y0, a) in enumerate((((80, 255, 170), 70, 22), ((170, 110, 255), 105, 16))):
                mid = y0 + a * np.sin(xx * 0.03 + t * 0.35 + j * 2) + 8 * np.sin(xx * 0.09 - t * 0.6)
                d = np.abs(yy - mid); band = np.exp(-(d / (10 + 4 * j)) ** 2) * (0.55 + 0.35 * bass) * (0.6 + 0.4 * np.sin(xx * 0.05 + t))
                band = np.floor(band * 4 + BY[:200, :LW]) / 4
                c[:200] += band[..., None] * np.array(col, np.float32) * 0.45
        if hasattr(self, 'veins'):
            c[self.veins] = c[self.veins] * 0.5 + np.array(self.P['crystal'][0], np.float32) * (0.15 + 0.3 * bass)
        for x, y, b, big in self.stars:                                                     # stars, twinkling on the hats
            tw = b + 0.5 * hat * math.sin(x * 12.9 + y * 7.1) ** 2 + 0.15 * math.sin(t * 3 + x)
            if tw > 0.8:
                c[y, x] = (255, 255, 240)
                if big and tw > 1.0:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        if 0 <= y + dy < LH and 0 <= x + dx < LW: c[y + dy, x + dx] = (170, 170, 220)
            elif tw > 0.45: c[y, x] = np.maximum(c[y, x], (140, 140, 190))
        fo = int(round(cam * 0.15)); mo = int(round(cam * 0.45)); go = int(round(cam))
        self._layer(c, self.far, fo); self._layer(c, self.mid, mo)
        if self.theme == 'city':
            P = self.P
            for wx, wy, kind, ph, on in self.windows:                                        # windows: some go on and off, all swell with the bass
                sx = wx - PAD - mo
                if not (-2 < sx < LW + 2): continue
                lit = on < 0.42 + 0.08 * math.sin(t * 0.7 + ph * 40) + (0.25 if (int(beat) + int(ph * 7)) % 11 == 0 else 0)
                col = np.array(P['win'][kind], np.float32) * (0.75 + 0.35 * bass) * (1 - 0.55 * self.quiet) if lit else np.array((40, 32, 66), np.float32)
                x0, x1 = max(0, sx), min(LW, sx + 3)
                if x1 > x0: c[wy:wy + 3, x0:x1] = col
            for ax, ay, ph in self.blinks:
                sx = ax - PAD - mo
                if 0 <= sx < LW and (beat + ph * 4) % 2 < 1 and self.quiet < 0.5:      # a blinking red glow reads as a small burst
                    c[ay, sx] = (255, 60, 70); glow(c, sx, ay, 4, (160, 30, 40), 0.8)
            nx, ny, nw, nh = self.neon; sx = nx - PAD - mo                                   # the neon frame pulses with the kick
            col = np.array(P['accent'], np.float32) * (0.6 + 0.5 * kick)
            c[ny:ny + 1, max(0, sx):max(0, sx + nw)] = col; c[ny + nh:ny + nh + 1, max(0, sx):max(0, sx + nw)] = col
            if 0 <= sx < LW: c[ny:ny + nh + 1, sx] = col
            if 0 <= sx + nw < LW: c[ny:ny + nh + 1, sx + nw] = col
            for j in range(3):
                bx = sx + 5 + j * 10
                if 0 <= bx < LW - 6: c[ny + 4:ny + nh - 3, bx:bx + 6] = np.array((130, 220, 255), np.float32) * (0.5 + 0.6 * (j == int(beat) % 3))
            glow(c, sx + nw / 2, ny + nh / 2, 16, P['accent'], 0.35 + 0.4 * kick)
        self._layer(c, self.ground, go)
        if self.theme == 'cave':                                                             # the puddle reflects the crystals' glow
            pm = self.puddle[:, PAD + go:PAD + go + LW]
            c[pm] = c[pm] + np.array((30, 60, 90), np.float32) * (0.4 + 0.6 * bass) * (BY[:LH, :LW][pm] > 0.5)[:, None]
        for L in self.lights:
            if L['x'] is None: continue
            off = mo if L['layer'] == 0.45 else go if L['layer'] == 1.0 else 0
            a = (L['base'] + L['kick'] * kick + L['bass'] * bass) * (1 - 0.6 * self.quiet)
            glow(c, L['x'] - (PAD + off if L['layer'] else 0), L['y'], L['r'], L['col'], a * 0.6)
        if self.bulbs:                                                                       # string lights: a chase that steps on the beat
            pts = []
            for bx, by, j in self.bulbs:
                sx = bx - PAD - go
                if 0 <= sx < LW: pts.append((sx, by, j))
            for (x0, y0, _), (x1, y1, _) in zip(pts, pts[1:]):
                for s in range(x1 - x0): c[int(round(y0 + (y1 - y0) * s / max(1, x1 - x0))) - 2, x0 + s] = (30, 24, 40)
            for sx, by, j in pts:
                on = (j + int(beat * 2)) % 4 == 0
                col = [(255, 210, 120), (255, 120, 170), (130, 220, 255)][j % 3]
                c[by - 1:by + 2, sx] = np.array(col, np.float32) * (1.0 if on else 0.45) * (1 - 0.6 * self.quiet)
                if on and self.quiet < 0.5: glow(c, sx, by, 5, col, 0.35 + 0.4 * kick)

    def front(self, c, t, beat, kick, bass, vox, cam):
        """In front of the test: drifting particles and the foreground layer."""
        for x0, y0, ph, sp, kind in self.motes:
            x = (x0 + 6 * math.sin(t * sp + ph) + t * 4 * sp) % LW; y = (y0 - t * 6 * sp) % (GY - 50) + 50
            xi, yi = int(x), int(y)
            if self.theme == 'forest':                                                        # fireflies, lit by the voice and the bass
                a = 0.3 + 0.7 * max(vox, 0.5 * bass) * (0.5 + 0.5 * math.sin(t * 4 + ph * 3))
                if a > 0.35 and self.quiet < 0.5: c[yi, xi] = c[yi, xi] * (1 - a) + np.array((255, 240, 140)) * a; glow(c, xi, yi, 3, (120, 110, 40), a * 0.8)
            elif self.theme == 'cave':                                                        # spores
                col = self.P['crystal'][int(kind * 4) % 4]; a = 0.35 + 0.5 * bass
                c[yi, xi] = c[yi, xi] * (1 - a) + np.array(col) * a
            else:                                                                             # dust in the city light
                if kind < 0.6 and self.quiet < 0.5: c[yi, xi] = c[yi, xi] * 0.6 + np.array((220, 200, 255)) * 0.4 * (0.5 + kick)
        self._layer(c, self.fg, int(round(cam * 1.5)))
