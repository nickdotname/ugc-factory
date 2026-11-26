#!/usr/bin/env python3
"""Fluid sims for the physics account: a wind tunnel where every gust is a kick drum.

    python studio/fluid_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/fluid_video.py SONG_DIR SEED SHEET.png --frames 0,90,200   (a contact sheet instead of a video)

Air pours down the screen past an obstacle: the song's title in block letters, a guitar, a music note, headphones,
a paper plane, a cassette, a cylinder (the textbook Karman vortex street) or a wing at a steep angle. The air is
solved with the lattice Boltzmann method (D2Q9, BGK collisions with a Smagorinsky eddy viscosity so it stays stable
when it turns turbulent), which reproduces the incompressible Navier-Stokes equations shown under it, so the wake
that peels off is real. The inflow speeds up on every kick of the song, so the gusts are the drums. Three ways to
look at it (a knob): speed (a colour map with flowing streaks drawn along the flow, line integral convolution),
vorticity (which way the air spins) or smoke (a rake of smoke lines upstream, and a band of smoke on every kick).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from numba import njit, prange
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish

W, H = 1080, 1920
FPS = int(os.environ.get('CQ_FPS', 30)); audio.FPS = FPS
NX, NY = 180, 320                     # the lattice: 6 output pixels a cell
VW, VH = 540, 960                     # where the streaks and smoke are drawn (then doubled)
U0 = 0.05                             # inflow speed in lattice units (the fastest jet past the obstacle stays well under the
                                      # lattice's speed of sound, 0.58, or the solver blows up)
STEPS = 56                            # lattice steps a video frame: the air crosses the screen in about 4 s
WARM = 14000                          # steps run before the first frame, so the wake is already there
EX = np.array([0, 1, 0, -1, 0, 1, -1, -1, 1], np.int64)
EY = np.array([0, 0, 1, 0, -1, 1, 1, -1, -1], np.int64)
WT = np.array([4 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 9, 1 / 36, 1 / 36, 1 / 36, 1 / 36], np.float32)
OPP = np.array([0, 3, 4, 1, 2, 7, 8, 5, 6], np.int64)


@njit(parallel=True, fastmath=True, cache=True)
def lbm_step(f, g, solid, uin, nu0, cs2):
    """One lattice Boltzmann step, f -> g. Streaming pulls each population from its upstream neighbour (bounced back
    off the obstacle, equilibrium inflow at the top, zero-gradient outflow at the bottom, periodic sides); collision
    relaxes towards equilibrium at a rate set by the molecular plus the Smagorinsky eddy viscosity."""
    nx, ny = solid.shape
    tau0 = 3.0 * nu0 + 0.5
    for x in prange(nx):
        for y in range(ny):
            if solid[x, y]:
                for i in range(9): g[i, x, y] = f[i, x, y]
                continue
            rho = 0.0; jx = 0.0; jy = 0.0
            for i in range(9):
                sx = x - EX[i]; sy = y - EY[i]
                if sx < 0: sx += nx
                elif sx >= nx: sx -= nx
                if sy < 0:
                    cu = EY[i] * uin
                    v = WT[i] * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * uin * uin)
                elif sy >= ny:
                    v = f[i, sx, ny - 1]
                elif solid[sx, sy]:
                    v = f[OPP[i], x, y]
                else:
                    v = f[i, sx, sy]
                g[i, x, y] = v; rho += v; jx += EX[i] * v; jy += EY[i] * v
            ux = jx / rho; uy = jy / rho; usq = ux * ux + uy * uy
            pxx = 0.0; pyy = 0.0; pxy = 0.0
            for i in range(9):
                cu = EX[i] * ux + EY[i] * uy
                fn = g[i, x, y] - WT[i] * rho * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq)
                pxx += EX[i] * EX[i] * fn; pyy += EY[i] * EY[i] * fn; pxy += EX[i] * EY[i] * fn
            q = math.sqrt(pxx * pxx + pyy * pyy + 2.0 * pxy * pxy)
            om = 1.0 / (0.5 * (tau0 + math.sqrt(tau0 * tau0 + 18.0 * 1.4142 * cs2 * q / rho)))
            for i in range(9):
                cu = EX[i] * ux + EY[i] * uy
                feq = WT[i] * rho * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq)
                g[i, x, y] = g[i, x, y] - om * (g[i, x, y] - feq)


def velocity(f, solid):
    rho = f.sum(0); ux = (f * EX[:, None, None]).sum(0) / rho; uy = (f * EY[:, None, None]).sum(0) / rho
    ux[solid] = 0; uy[solid] = 0
    return ux.T.astype(np.float32), uy.T.astype(np.float32)   # as images: rows down the screen


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def fraunces(size, weight=500):
    f = font('Fraunces.ttf', size)
    try: f.set_variation_by_axes([72, weight, 0, 0])
    except Exception: pass
    return f


def equation_png(scale=1.0):
    """The incompressible Navier-Stokes equations, typeset (matplotlib's mathtext in Computer Modern), white on clear."""
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['mathtext.fontset'] = 'cm'
    out = []
    for tex, fs in ((r'$\frac{\partial \mathbf{u}}{\partial t} + (\mathbf{u}\cdot\nabla)\,\mathbf{u} = -\frac{1}{\rho}\nabla p + \nu\nabla^2\mathbf{u}$', 30),
                    (r'$\nabla\cdot\mathbf{u} = 0$', 30)):
        fig = plt.figure(figsize=(9, 1.4), dpi=110 * scale); fig.patch.set_alpha(0)
        fig.text(0.5, 0.5, tex, color='white', fontsize=fs, ha='center', va='center')
        fig.canvas.draw(); a = np.asarray(fig.canvas.buffer_rgba()).copy(); plt.close(fig)
        ys, xs = np.nonzero(a[..., 3] > 8); out.append(a[ys.min() - 4:ys.max() + 5, xs.min() - 4:xs.max() + 5])
    return out


def cmap_lut(name):
    import matplotlib; matplotlib.use('Agg')
    from matplotlib import colormaps
    if name == 'spin':                                  # teal - near black - pink, for which way the air turns
        a = np.linspace(-1, 1, 256)[:, None]
        neg = np.array([60, 220, 230]); pos = np.array([255, 70, 160]); mid = np.array([14, 12, 26])
        return np.clip(np.where(a < 0, mid + (neg - mid) * np.abs(a) ** 0.8, mid + (pos - mid) * np.abs(a) ** 0.8), 0, 255).astype(np.uint8)
    c = colormaps[name](np.linspace(0, 1, 256))[:, :3]
    return (c * 255).astype(np.uint8)


# ---------------------------------------------------------------- the obstacles, drawn once at full size
def rot(pts, ang, cx, cy):
    ca, sa = math.cos(ang), math.sin(ang)
    return [(cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca) for x, y in pts]


def ellipse_pts(cx, cy, rx, ry, n=48):
    return [(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n)]


def naca(code, chord, n=80):
    """A NACA 4-digit wing section, leading edge at 0, as a closed outline."""
    m, p, t = int(code[0]) / 100, int(code[1]) / 10, int(code[2:]) / 100
    xs = (1 - np.cos(np.linspace(0, np.pi, n))) / 2
    yt = 5 * t * (0.2969 * np.sqrt(xs) - 0.126 * xs - 0.3516 * xs ** 2 + 0.2843 * xs ** 3 - 0.1036 * xs ** 4)
    yc = np.where(xs < p, m / max(p, 1e-6) ** 2 * (2 * p * xs - xs ** 2), m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * xs - xs ** 2))
    up = list(zip(xs * chord, (yc + yt) * chord)); lo = list(zip(xs * chord, (yc - yt) * chord))
    return up + lo[::-1]


class Shape:
    """An obstacle: a list of (polygon or ellipse, fill, outline) parts in output pixels, plus its mask on the lattice."""
    def __init__(self, kind, r, title, cy):
        self.kind = kind; self.parts = []; cx = W / 2
        P = lambda pts, fill, line=(20, 14, 18): self.parts.append(('poly', pts, fill, line))
        if kind == 'title':
            words = title.upper().replace('’', "'").split(); lines = [title.upper()]
            if len(title) > 10:                       # two lines, split where they come out most even
                k = min(range(1, len(words)), key=lambda k: abs(len(' '.join(words[:k])) - len(' '.join(words[k:])))) if len(words) > 1 else 1
                lines = [' '.join(words[:k]), ' '.join(words[k:])]
            size = 230
            while True:
                fnt = font('Anton-Regular.ttf', size)
                wd = max(fnt.getbbox(l)[2] - fnt.getbbox(l)[0] for l in lines)
                if wd <= W * 0.54 or size < 60: break      # wider blocks the tunnel: the jets between letters go supersonic
                size -= 6
            self.parts.append(('text', lines, fnt, cy))
        elif kind == 'cylinder':
            self.parts.append(('ell', (cx, cy, 78, 78), (190, 196, 210), (20, 20, 30)))
        elif kind == 'airfoil':
            aoa = math.radians(r.choice([14, 16, 18, 22])); self.aoa = round(math.degrees(aoa))
            pts = [(cx - 200 + y, cy - 270 + x) for x, y in naca(r.choice(['2412', '4412', '0012']), 540)]   # leading edge up
            P(rot(pts, aoa, cx, cy - 30), (226, 230, 238))
        elif kind == 'guitar':
            a = math.radians(r.uniform(-28, -12))
            body = [ellipse_pts(cx + 90, cy + 10, 150, 120), ellipse_pts(cx - 40, cy + 10, 110, 92)]
            neck = [(cx - 130, cy - 6), (cx - 400, cy - 6), (cx - 400, cy + 26), (cx - 130, cy + 26)]
            head = [(cx - 400, cy - 18), (cx - 470, cy - 26), (cx - 470, cy + 46), (cx - 400, cy + 38)]
            for b in body: P(rot(b, a, cx, cy), (214, 120, 50))
            P(rot(neck, a, cx, cy), (110, 64, 36)); P(rot(head, a, cx, cy), (60, 36, 24))
            self.parts.append(('deco', rot(ellipse_pts(cx + 10, cy + 10, 44, 44), a, cx, cy), (40, 22, 14), None))
        elif kind == 'note':
            a = math.radians(-22)
            P(rot(ellipse_pts(cx - 60, cy + 120, 92, 64), a, cx - 60, cy + 120), (24, 22, 30), (250, 250, 255))
            P([(cx + 18, cy + 110), (cx + 18, cy - 210), (cx + 46, cy - 210), (cx + 46, cy + 110)], (24, 22, 30), (250, 250, 255))
            P([(cx + 46, cy - 210), (cx + 150, cy - 120), (cx + 140, cy - 50), (cx + 46, cy - 130)], (24, 22, 30), (250, 250, 255))
        elif kind == 'headphones':
            band = [(cx + 200 * math.cos(t), cy - 20 - 200 * math.sin(t)) for t in np.linspace(0.05, math.pi - 0.05, 40)]
            inner = [(cx + 160 * math.cos(t), cy - 20 - 160 * math.sin(t)) for t in np.linspace(math.pi - 0.05, 0.05, 40)]
            P(band + inner, (40, 40, 52), (240, 240, 250))
            for sx in (-1, 1):
                P(ellipse_pts(cx + sx * 180, cy + 40, 58, 92), (255, 70, 120), (240, 240, 250))
        elif kind == 'plane':
            a = math.radians(r.uniform(-20, 20))
            P(rot([(cx - 260, cy - 60), (cx + 250, cy + 10), (cx - 160, cy + 100)], a, cx, cy), (245, 245, 250))
            P(rot([(cx - 160, cy + 100), (cx + 250, cy + 10), (cx - 120, cy + 40)], a, cx, cy), (200, 205, 220))
        elif kind == 'cassette':
            a = math.radians(r.uniform(-25, 25))
            P(rot([(cx - 230, cy - 140), (cx + 230, cy - 140), (cx + 230, cy + 140), (cx - 230, cy + 140)], a, cx, cy), (36, 36, 44), (240, 240, 250))
            P(rot([(cx - 180, cy - 100), (cx + 180, cy - 100), (cx + 180, cy + 20), (cx - 180, cy + 20)], a, cx, cy), (250, 230, 120), None)
            for sx in (-1, 1):
                self.parts.append(('deco', rot(ellipse_pts(cx + sx * 90, cy - 40, 34, 34), a, cx, cy), (36, 36, 44), None))
        pts = [q for p in self.parts if p[0] in ('poly', 'deco') for q in p[1]]
        if pts:                                       # no wider than half the tunnel (see the title's limit)
            xs = [q[0] for q in pts]; k = min(1.0, W * 0.5 / (max(xs) - min(xs)))
            mid = (max(xs) + min(xs)) / 2
            self.parts = [(p[0], [(W / 2 + (x - mid) * k, cy + (y - cy) * k) for x, y in p[1]]) + tuple(p[2:]) if p[0] in ('poly', 'deco') else p
                          for p in self.parts]
        self.draw()

    def draw(self):
        im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        mk = Image.new('L', (W, H), 0); dm = ImageDraw.Draw(mk)
        for p in self.parts:
            if p[0] == 'text':
                _, lines, fnt, cy = p; lh = fnt.getbbox('A')[3] * 1.02; y0 = cy - lh * (len(lines) - 1) / 2
                for k, l in enumerate(lines):
                    d.text((W / 2, y0 + k * lh), l, font=fnt, fill=(255, 255, 255), anchor='mm', stroke_width=7, stroke_fill=(16, 10, 18))
                    dm.text((W / 2, y0 + k * lh), l, font=fnt, fill=255, anchor='mm', stroke_width=7, stroke_fill=255)
            elif p[0] == 'ell':
                cx, cy, rx, ry = p[1]
                d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=p[2], outline=p[3], width=6)
                d.ellipse((cx - rx * 0.55, cy - ry * 0.7, cx - rx * 0.1, cy - ry * 0.25), fill=(240, 242, 250))
                dm.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
            elif p[0] == 'poly':
                d.polygon(p[1], fill=p[2], outline=p[3], width=6 if p[3] else 0); dm.polygon(p[1], fill=255)
            elif p[0] == 'deco':
                d.polygon(p[1], fill=p[2])
        self.rgba = np.asarray(im).astype(np.float32)
        m = cv2.resize(np.asarray(mk, np.float32) / 255, (NX, NY), interpolation=cv2.INTER_AREA)
        self.solid = np.ascontiguousarray((m > 0.4).T)                 # [x, y] on the lattice
        self.bbox = np.nonzero(np.asarray(mk) > 0)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '%s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.kind = K.pick('obstacle', ['title', 'guitar', 'note', 'headphones', 'plane', 'cassette', 'cylinder', 'airfoil'], r,
                           weights=[4, 2, 1, 1, 1, 1, 1, 1])
        self.view = K.pick('view', ['speed', 'vorticity', 'smoke'], r, weights=[3, 1, 2])
        self.cmap = K.pick('palette', ['inferno', 'plasma', 'magma', 'turbo'], r, weights=[3, 2, 1, 1])
        self.gust = K.pick('gust', ['kick', 'drums'], r, weights=[3, 1])
        self.hookline = 'none' if os.environ.get('CQ_HOOK') == 'none' else K.pick('hook', ['gust', 'none'], r)
        a = audio.load(self.slug, t0, t1); self.n = a['n']
        frames = a['kicks'] if self.gust == 'kick' and len(a['kicks']) >= 4 else a['onsets']
        self.env = audio.hits(frames, self.n, decay=4.5)
        self.hit_frames = set(int(f) for f in frames)
        self.shape = Shape(self.kind, r, self.title, cy=H * 0.33)
        nice = {'title': '"%s" Wake Formation' % self.title, 'guitar': 'Guitar Wake Formation', 'note': 'Music Note Wake Formation',
                'headphones': 'Headphone Wake Formation', 'plane': 'Paper Plane Wake Formation', 'cassette': 'Cassette Wake Formation',
                'cylinder': 'Kármán Vortex Street', 'airfoil': 'Wing Stall at %d°' % getattr(self.shape, 'aoa', 16)}
        self.head = nice[self.kind]; self.sub = 'Navier–Stokes Simulation'
        self.f_head = fraunces(76 if len(self.head) < 24 else 62, 560); self.f_sub = fraunces(50, 420); self.f_lab = fraunces(40, 420)
        self.f_small = font('Montserrat-ExtraBold.ttf', 30)
        self.lut = cmap_lut('spin' if self.view == 'vorticity' else self.cmap)
        self.eqs = equation_png()
        # the lattice
        self.solid = self.shape.solid
        u = np.zeros((NX, NY), np.float32)
        u += np.float32(0.004) * np.random.default_rng(seed).standard_normal((NX, NY)).astype(np.float32)   # a nudge so the wake sheds
        f = np.empty((9, NX, NY), np.float32)
        for i in range(9):
            cu = EX[i] * u + EY[i] * U0
            f[i] = WT[i] * (1 + 3 * cu + 4.5 * cu * cu - 1.5 * (u * u + U0 * U0))
        self.f, self.g = f, np.empty_like(f)
        self.nu0, self.cs2 = 0.008, 0.2 ** 2
        for k in range(WARM): self.step(U0 * min(1.0, 0.2 + k / 1500))   # eased in: an impulsive start rings
        if not np.isfinite(self.f).all(): sys.exit('the flow blew up (%s, seed %d)' % (self.kind, seed))
        # what the streaks and smoke are drawn on
        rng = np.random.default_rng(seed + 1); self.rng = rng
        self.noise = rng.random((VH, VW)).astype(np.float32)
        self.smoke = np.zeros((VH, VW), np.float32)
        self.gx, self.gy = np.meshgrid(np.arange(VW, dtype=np.float32), np.arange(VH, dtype=np.float32))
        m = cv2.resize(self.solid.T.astype(np.float32), (VW, VH), interpolation=cv2.INTER_NEAREST); self.solid_v = m > 0.5
        self.rake = np.zeros(VW, bool); self.rake[(np.arange(VW) % 18) < 3] = True
        if self.view == 'smoke':                      # the smoke has filled the tunnel before the video starts
            for k in range(80): self.smoke_step(*self.flow()[2:], k % 16 == 0); [self.step(U0) for _ in range(STEPS)]

    def step(self, uin):
        lbm_step(self.f, self.g, self.solid, np.float32(uin), self.nu0, self.cs2); self.f, self.g = self.g, self.f

    def smoke_step(self, U, V, puff):
        """Carry the smoke one frame down the flow; the rake feeds its lines, and a kick (puff) a whole band."""
        px = STEPS * VW / NX
        s = cv2.remap(self.smoke, self.gx - U * px, self.gy - V * px, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0) * 0.992
        s[self.solid_v] = 0
        s[8:14, self.rake] = np.maximum(s[8:14, self.rake], 0.65)
        if puff: s[4:22, :] = np.maximum(s[4:22, :], 1.0)
        self.smoke = s

    def flow(self):
        ux, uy = velocity(self.f, self.solid)
        U = cv2.resize(ux, (VW, VH), interpolation=cv2.INTER_CUBIC); V = cv2.resize(uy, (VW, VH), interpolation=cv2.INTER_CUBIC)
        return ux, uy, U, V

    def frame(self, i):
        e = float(self.env[i]); uin = U0 * (1 + 0.55 * e)
        for _ in range(STEPS): self.step(uin)
        ux, uy, U, V = self.flow()
        if not np.isfinite(U).all(): sys.exit('the flow blew up at frame %d' % i)
        px = STEPS * VW / NX                                    # lattice speed -> view pixels a frame
        mx, my = self.gx - U * px, self.gy - V * px
        if self.view == 'smoke':
            self.smoke_step(U, V, i in self.hit_frames or (i - 1) in self.hit_frames); s = self.smoke
            sp = np.sqrt(U * U + V * V) / (U0 * 2.6)
            tint = self.lut[np.clip(sp * 255, 0, 255).astype(np.uint8)].astype(np.float32)
            a = np.clip(s, 0, 1)[..., None]
            glow = cv2.GaussianBlur(a, (0, 0), 6)[..., None] * 0.6
            bg = np.array([10, 9, 18], np.float32) + tint * 0.10
            col = 0.55 * np.array([255, 250, 245], np.float32) + 0.45 * tint
            img = bg * (1 - a) + col * a + col * glow
        else:
            t = cv2.remap(self.noise, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
            self.noise = t * 0.9 + self.rng.random((VH, VW)).astype(np.float32) * 0.1
            sp = np.sqrt(U * U + V * V) + 1e-6; dx, dy = U / sp * 1.6, V / sp * 1.6
            acc = self.noise.copy()
            for j in range(1, 8):
                acc += cv2.remap(self.noise, self.gx + dx * j, self.gy + dy * j, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                acc += cv2.remap(self.noise, self.gx - dx * j, self.gy - dy * j, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            lic = acc / 15
            lic = (lic - lic.mean()) / (lic.std() + 1e-6)
            if self.view == 'vorticity':
                w = (np.gradient(uy, axis=1) - np.gradient(ux, axis=0))
                w = cv2.resize(w, (VW, VH), interpolation=cv2.INTER_CUBIC) / 0.012
                idx = np.clip((np.tanh(w) * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8)
            else:
                idx = np.clip(sp / (U0 * 2.6) * 255, 0, 255).astype(np.uint8)          # the free stream sits mid-scale, jets run hot
            col = self.lut[idx].astype(np.float32)
            img = col * (0.86 + 0.16 * np.clip(lic, -2.5, 2.5))[..., None] * (1 + 0.10 * e)
        img = cv2.resize(np.clip(img, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        a = self.shape.rgba[..., 3:] / 255
        img = img * (1 - a) + self.shape.rgba[..., :3] * a
        return self.overlay(img.astype(np.uint8), e)

    def overlay(self, arr, e):
        im = Image.fromarray(arr); d = ImageDraw.Draw(im)
        sh = dict(stroke_width=3, stroke_fill=(20, 12, 24))
        d.text((W / 2, 300), self.head, font=self.f_head, fill=(255, 255, 255), anchor='mm', **sh)
        d.text((W / 2, 385), self.sub, font=self.f_sub, fill=(255, 255, 255), anchor='mm', **sh)
        if self.hookline == 'gust':
            d.text((W / 2, 452), 'sound on: every gust is a kick', font=self.f_small, fill=(255, 255, 255), anchor='mm', **sh)
        y = 1300
        if self.view == 'smoke':
            d.text((W / 2, y + 30), 'smoke pulse = kick drum', font=self.f_lab, fill=(255, 255, 255), anchor='mm', **sh)
        else:
            bar = self.lut[np.linspace(0, 255, 760).astype(int)][None].repeat(56, 0)
            im.paste(Image.fromarray(bar), (160, y))
            d.rectangle((160, y, 920, y + 56), outline=(255, 255, 255), width=2)
            lo, hi = ('clockwise', 'counter-clockwise') if self.view == 'vorticity' else ('low speed', 'high speed')
            d.text((160, y + 96), lo, font=self.f_lab, fill=(255, 255, 255), anchor='lm', **sh)
            d.text((920, y + 96), hi, font=self.f_lab, fill=(255, 255, 255), anchor='rm', **sh)
        y = 1480
        for eq in self.eqs:
            a = eq[..., 3].astype(np.float32)                    # a soft dark halo so the formula reads over any colour
            halo = cv2.GaussianBlur(cv2.dilate(a, np.ones((5, 5), np.uint8)), (0, 0), 6)
            eq = np.dstack([eq[..., :3], np.clip(np.maximum(a, halo * 0.55), 0, 255).astype(np.uint8)])
            eq[..., :3][a < 40] = 10
            e_im = Image.fromarray(eq)
            if e_im.width > 860: e_im = e_im.resize((860, int(e_im.height * 860 / e_im.width)), Image.LANCZOS)
            im.paste(e_im, (int(W / 2 - e_im.width / 2), int(y)), e_im); y += e_im.height + 22
        d.text((W / 2, H - 70), self.credit, font=self.f_small, fill=(235, 235, 240), anchor='mm', **sh)
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; want = set(fs); ims = []
            for i in range(max(fs) + 1):
                fr = self.frame(i)
                if i in want: ims.append(Image.fromarray(fr).resize((540, 960)))
            sheet = Image.new('RGB', (540 * len(ims), 960))
            for j, im in enumerate(ims): sheet.paste(im, (540 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
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
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'fluid')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (80.3, 95.3)
    Video(song_dir, seed, t0, t1).render(out)
