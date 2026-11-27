#!/usr/bin/env python3
"""Can you stop this? A reflex game to a song: pause the video when the flying thing is inside the red line.

    python studio/stopit_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/stopit_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

A street drawn here from boxes (no game footage, no photos): a low-poly car, a bollard, a crate or a traffic cone is
thrown up off the road on a beat, tumbling, and passes through a hand-drawn red outline exactly once, on a later beat.
Then the next throw. People replay it to land the pause, which is the point. Nothing on screen asks for a comment.
Everything is drawn in numpy/OpenCV (no Blender), so it runs anywhere the other renderers run.
Knobs (studio/knobs.py): thing (what we hit), sky, ask (the line under the title).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
F = 1150.0                    # focal length in pixels
CAM = np.array([0.0, 1.7, 0.0])
HY = H * 0.60                 # horizon on screen
THINGS = ['car', 'bollard', 'crate', 'cone']
SKIES = {'noon': ((96, 160, 235), (190, 225, 250)), 'golden': ((120, 150, 220), (255, 205, 150)), 'overcast': ((150, 165, 180), (215, 220, 225))}
ASKS = {'stop': 'stop it inside the red line', 'pause': 'pause when it fits the line', 'timing': 'one frame. good luck'}
CARPAL = [(200, 40, 40), (40, 90, 200), (235, 235, 235), (30, 30, 35), (240, 180, 30), (60, 150, 90)]
SUN = np.array([0.45, 0.8, -0.4]); SUN /= np.linalg.norm(SUN)


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def proj(p, cz=0.0):
    """world (x across, y up, z down the street) -> screen, for the camera cz metres down the street"""
    q = p - (CAM + np.array([0.0, 0.0, cz])); z = np.maximum(q[..., 2], 0.2)
    return np.stack([W / 2 + F * q[..., 0] / z, HY - F * q[..., 1] / z], -1)


def boxq(lo, hi, col):
    """the six faces of an axis box, as (4 corners, colour)"""
    (a, b, c), (d, e, f) = lo, hi
    v = np.array([[a, b, c], [d, b, c], [d, e, c], [a, e, c], [a, b, f], [d, b, f], [d, e, f], [a, e, f]], float)
    idx = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5)]
    return [(v[list(i)], col) for i in idx]


def prism(r0, r1, y0, y1, n, col, stripes=None):
    """a many-sided upright prism (a cylinder or a cone if r1 is small), centred on the origin"""
    out = []
    for k in range(n):
        a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        segs = stripes or [(y0, y1, col)]
        for s0, s1, c in segs:
            t0, t1 = (s0 - y0) / (y1 - y0), (s1 - y0) / (y1 - y0)
            ra, rb = r0 + (r1 - r0) * t0, r0 + (r1 - r0) * t1
            out.append((np.array([[ra * math.cos(a0), s0, ra * math.sin(a0)], [ra * math.cos(a1), s0, ra * math.sin(a1)],
                                  [rb * math.cos(a1), s1, rb * math.sin(a1)], [rb * math.cos(a0), s1, rb * math.sin(a0)]]), c))
    top = np.array([[r1 * math.cos(2 * math.pi * k / n), y1, r1 * math.sin(2 * math.pi * k / n)] for k in range(n)])
    out.append((top[::-1], (segs[-1][2] if stripes else col)))
    return out


def thing(kind, rng):
    """a low-poly object of our own, centred near its middle, about 1-4 m across"""
    if kind == 'car':
        c = CARPAL[rng.integers(len(CARPAL))]; glass = (120, 160, 190); tyre = (30, 30, 34); under = (55, 55, 60)
        q = boxq((-0.9, -0.3, -2.0), (0.9, 0.25, 2.0), c)                                       # body
        q += boxq((-0.74, 0.25, -0.85), (0.74, 0.68, 0.85), glass)                              # windows all round
        q += boxq((-0.76, 0.68, -0.9), (0.76, 0.76, 0.9), c)                                    # roof
        q += boxq((-0.86, -0.42, -1.85), (0.86, -0.3, 1.85), under)                             # floor pan
        q += boxq((-0.7, 0.0, 1.99), (-0.35, 0.12, 2.02), (250, 245, 210)) + boxq((0.35, 0.0, 1.99), (0.7, 0.12, 2.02), (250, 245, 210))   # headlights
        q += boxq((-0.7, 0.0, -2.02), (-0.4, 0.1, -1.99), (200, 30, 30)) + boxq((0.4, 0.0, -2.02), (0.7, 0.1, -1.99), (200, 30, 30))      # tail lights
        for sx in (-1, 1):
            for sz in (-1.3, 1.3):
                w = prism(0.36, 0.36, -0.13, 0.13, 10, tyre)
                rot = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)        # lay the wheel on its side
                q += [((v @ rot.T) + np.array([0.78 * sx, -0.4, sz]), col) for v, col in w]
        return q
    if kind == 'bollard':
        st = [(-0.6, 0.2, (150, 150, 155)), (0.2, 0.32, (210, 40, 40)), (0.32, 0.42, (150, 150, 155)), (0.42, 0.54, (210, 40, 40)), (0.54, 0.6, (150, 150, 155))]
        return [(v * 1.5, col) for v, col in prism(0.18, 0.16, -0.6, 0.6, 12, (150, 150, 155), stripes=st)]
    if kind == 'cone':
        st = [(-0.5, -0.1, (245, 110, 20)), (-0.1, 0.1, (240, 240, 240)), (0.1, 0.5, (245, 110, 20))]
        return [(v * 2.0, col) for v, col in prism(0.34, 0.05, -0.5, 0.5, 10, (245, 110, 20), stripes=st)] + boxq((-0.7, -1.08, -0.7), (0.7, -1.0, 0.7), (245, 110, 20))
    c = (176, 128, 70)
    return boxq((-0.8, -0.8, -0.8), (0.8, 0.8, 0.8), c) + boxq((-0.82, -0.1, -0.82), (0.82, 0.1, 0.82), (140, 98, 52))


def rot(ax, ay, az):
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    return (np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
            @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]))


class Video:
    """One thing, one loop. The camera drives down the street; the thing stands on the road ahead; on a beat we hit
    it and it flips up into the air ahead of us, tumbling, crosses its own traced outline exactly once (on a later
    beat), and leaves over the top of the picture. The street repeats every loop, so the clip runs seamlessly."""
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.rng = np.random.default_rng(seed)
        self.kind = K.pick('thing', THINGS, r, weights=[4, 3, 3, 2])
        self.sky = K.pick('sky', sorted(SKIES), r, weights=[2, 3, 1])
        self.ask = K.pick('ask', sorted(ASKS), r)
        bars = 2                                                             # one loop: two bars (a 3-5 second clip that repeats)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 7.0)
        beat = self.spb * FPS
        reps = max(1, int(round(n / (4 * bars * beat)))); self.cyc = n // reps; self.n = n = self.cyc * reps   # whole loops, a few frames trimmed
        self.speed = 14.0                                                    # metres a second down the street
        self.P = self.speed * self.cyc / FPS                                 # the street repeats every P metres
        nb = self.cyc / beat                                                 # beats in a loop
        self.jl = int(round(beat * max(1, round(nb * 0.25))))                            # hit on a beat a quarter of the way in
        self.jh = int(round(self.jl + beat * max(1, round(nb * 0.35))))                  # crosses the line on a beat further on
        self.mesh = thing(self.kind, self.rng); lift = {'car': 0.75, 'bollard': 0.9, 'cone': 1.1, 'crate': 0.85}[self.kind]
        tl = self.jl / FPS; tau = (self.jh - self.jl) / FPS
        self.p0 = np.array([self.rng.uniform(-1.2, 1.2), lift, self.speed * tl + 6.0])   # where it stands: a few metres ahead when we reach it
        self.g = -9.8 * 0.35                                                 # floaty, like the game clips
        self.p0[2] = self.speed * tl + 2.6                                   # we reach it on the hit beat
        aimed = False
        for _ in range(3000):                                                 # aim: in frame and clear of the title when it
            self.vx = self.rng.uniform(-1.5, 1.5); self.p0[0] = self.rng.uniform(-1.2, 1.2)   # crosses the line, still rising,
            self.Dz, self.T, self.wz = self.rng.uniform(6, 22), self.rng.uniform(0.3, 0.8), self.rng.uniform(2.0, 10.0)   # and gone
            self.vy = -self.g * tau + self.rng.uniform(0.5, 4.5)            # (over the top or over us) well before the loop ends
            self.spin = self.rng.uniform(-1, 1, 3) * np.array([2.6, 1.6, 2.6]); self.a0 = np.zeros(3)
            ph, _R = self.pose(self.jh)
            if ph[2] - self.speed * self.jh / FPS < 4.0 or not self.gone(): continue
            self.loop = self.silhouette(self.jh); lo, hi = self.loop.min(0), self.loop.max(0)
            if lo[1] > 440 and hi[1] < HY - 20 and lo[0] > 50 and hi[0] < W - 50 and 120 < hi[1] - lo[1] < 700 and self.gone(): aimed = True; break
        if not aimed:                       # no throw crosses its line in frame on this stretch: no video (exit 3, nightly skips it).
            # 2026-11-27: it used to keep the last try, and physics.bounce.lab posted a car with its line drawn as a dot in the corner.
            print('no throw lands its line in frame on this stretch: skipped'); sys.exit(3)
        self.street_layout(seed)
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.f_title, self.f_sub = font('Anton-Regular.ttf', 118), font('Montserrat-ExtraBold.ttf', 40)
        sans = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',) if os.path.exists(p)), None)
        self.f_small = ImageFont.truetype(sans, 28) if sans else font('Poppins-Bold.ttf', 26)

    # ------------------------------------------------------------------ the street
    def street_layout(self, seed):
        r = np.random.default_rng(seed + 1); top, bot = SKIES[self.sky]
        yy = np.linspace(0, 1, H)[:, None, None]
        img = (np.array(top, np.float32) * (1 - yy) + np.array(bot, np.float32) * yy) * np.ones((1, W, 1), np.float32)
        cl = np.zeros((H, W), np.float32)
        for _ in range(26):
            cx, cy, rx = r.uniform(-100, W + 100), r.uniform(80, HY - 60), r.uniform(90, 260)
            cv2.ellipse(cl, (int(cx), int(cy)), (int(rx), int(rx * 0.38)), 0, 0, 360, float(r.uniform(0.35, 0.8)), -1)
        cl = cv2.GaussianBlur(cl, (0, 0), 38); img = img * (1 - cl[..., None] * 0.8) + 250 * cl[..., None] * 0.8
        self.sky_img = np.ascontiguousarray(np.clip(img, 0, 255).astype(np.uint8))
        self.blocks = []                                                     # one period of houses down each side
        for side in (-1, 1):
            z = 0.0
            while z < self.P - 3:
                d = min(r.uniform(5, 11), self.P - z); h = r.uniform(5, 16); x0 = 7.6 + r.uniform(0, 1.2); x1 = x0 + r.uniform(5, 9)
                hue = [(205, 90, 70), (70, 110, 190), (225, 215, 195), (150, 160, 170), (190, 150, 110), (95, 140, 120)][r.integers(6)]
                self.blocks.append((side, x0, x1, z, z + d - r.uniform(0.2, 1.5), h, hue)); z += d

    def street(self, cz):
        img = self.sky_img.copy()
        def poly(pts, col):
            pts = np.array(pts, float)
            if (pts[:, 2] - cz < 0.25).all(): return
            pts[:, 2] = np.maximum(pts[:, 2], cz + 0.25)
            cv2.fillPoly(img, [np.round(proj(pts, cz) * 8).astype(np.int32)], col, cv2.LINE_AA, 3)
        Z = cz + 400
        poly([(-60, 0, cz + .3), (60, 0, cz + .3), (60, 0, Z), (-60, 0, Z)], (110, 150, 95))
        poly([(-7, 0, cz + .3), (7, 0, cz + .3), (7, 0, Z), (-7, 0, Z)], (175, 172, 165))
        poly([(-4.6, 0.01, cz + .3), (4.6, 0.01, cz + .3), (4.6, 0.01, Z), (-4.6, 0.01, Z)], (92, 92, 96))
        for x in (-4.6, 4.6):
            poly([(x - 0.1, 0.02, cz + .3), (x + 0.1, 0.02, cz + .3), (x + 0.1, 0.02, Z), (x - 0.1, 0.02, Z)], (225, 225, 220))
        z = math.floor(cz / 5.5) * 5.5                                       # the dashes move past as we drive
        while z < cz + 160:
            if z + 2.2 > cz + 0.3: poly([(-0.09, 0.02, z), (0.09, 0.02, z), (0.09, 0.02, z + 2.2), (-0.09, 0.02, z + 2.2)], (235, 190, 40))
            z += 5.5
        k0 = int(math.floor(cz / self.P)); bl = []
        for k in range(k0 - 1, k0 + int(170 / self.P) + 2):
            for side, x0, x1, z0, z1, h, hue in self.blocks:
                a, b = z0 + k * self.P, z1 + k * self.P
                if b > cz + 0.3 and a < cz + 170: bl.append((a, side, x0, x1, a, b, h, hue))
        for _a, side, x0, x1, z0, z1, h, hue in sorted(bl, key=lambda b: -b[0]):
            xi, xo = side * x0, side * x1; lit = 0.82 if side > 0 else 1.0
            poly([(xi, 0, z0), (xi, 0, z1), (xi, h, z1), (xi, h, z0)], tuple(int(c * lit) for c in hue))
            if z0 > cz + 0.3: poly([(xi, 0, z0), (xo, 0, z0), (xo, h, z0), (xi, h, z0)], tuple(int(c * 0.62) for c in hue))
            for wy in np.arange(1.2, h - 1.0, 2.8):
                for wz in np.arange(z0 + 0.8, z1 - 0.8, 2.1):
                    poly([(xi - side * 0.01, wy, wz), (xi - side * 0.01, wy, wz + 1.0), (xi - side * 0.01, wy + 1.3, wz + 1.0), (xi - side * 0.01, wy + 1.3, wz)], (60, 70, 85))
        return img

    # ------------------------------------------------------------------ the thing
    def pose(self, j):
        """j: frames into the loop. Standing on the road until we hit it; then knocked up and ahead of us, slowed by the
        air so that we catch up and pass under it."""
        if j < self.jl: return self.p0.copy(), rot(*self.a0)
        t = (j - self.jl) / FPS; cz = self.speed * j / FPS
        rel = (self.p0[2] - self.speed * self.jl / FPS) + self.Dz * (1 - math.exp(-t / self.T)) - self.wz * t
        p = np.array([self.p0[0] + self.vx * t, self.p0[1] + self.vy * t + 0.5 * self.g * t * t, cz + rel])
        return p, rot(*(self.a0 + self.spin * t))

    def gone(self):
        """is the thing out of the picture (over the top, or behind us) for the last eighth of the loop? Then the
        loop restarts on an empty street with the next one standing far ahead, and nobody sees the jump."""
        for j in range(int(self.cyc * 0.875), self.cyc):
            cz = self.speed * j / FPS; p, _R = self.pose(j)
            if p[2] - cz > 0.6:
                sx, sy = proj(p, cz)
                if sy > -150 and -300 < sx < W + 300: return False
        return True

    def silhouette(self, j):
        """the outline of the thing exactly as it is on loop frame j, a few pixels outside its edge, as a pen would
        trace it: it fits the line on that frame and on no other."""
        cz = self.speed * j / FPS; m = np.zeros((H, W), np.uint8); p, R = self.pose(j)
        for v, _c in self.mesh:
            w = v @ R.T + p
            if (w[:, 2] - cz < 0.4).any(): continue
            cv2.fillPoly(m, [np.round(proj(w, cz)).astype(np.int32)], 255)
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not cs: return np.array([[0, 0], [1, 1], [0, 1]], float)
        c = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
        k = max(3, len(c) // 160) | 1
        c = np.stack([np.convolve(np.r_[c[-k:, i], c[:, i], c[:k, i]], np.ones(k) / k, 'same')[k:-k] for i in (0, 1)], 1)
        n = len(c); ph = self.rng.uniform(0, 6, 2); a = np.linspace(0, 2 * np.pi, n, endpoint=False)
        d = c - c.mean(0); d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
        return c + d * (2.0 * np.sin(a * 5 + ph[0]) + 1.2 * np.sin(a * 11 + ph[1]))[:, None]

    def draw_thing(self, img, j, cz):
        p, R = self.pose(j); faces = []; cam = CAM + np.array([0, 0, cz])
        for v, col in self.mesh:
            w = v @ R.T + p; nrm = np.cross(w[1] - w[0], w[2] - w[0]); ln = np.linalg.norm(nrm)
            if ln < 1e-9: continue
            nrm /= ln; cen = w.mean(0)
            if np.dot(nrm, cam - cen) <= 0: continue
            sh = 0.55 + 0.45 * max(0.0, float(np.dot(nrm, SUN)))
            faces.append((np.linalg.norm(w - cam, axis=1).max() * 0.5 + np.linalg.norm(cen - cam) * 0.5, w, tuple(int(min(255, c * sh)) for c in col)))
        if p[2] - cz > 1.2:                                                  # its shadow on the road, smaller the higher it is
            sp = proj(np.array([p[0], 0.02, p[2]]), cz); r = 900 / max(p[2] - cz, 1) / (1 + 0.25 * max(0, p[1] - 0.6))
            sh = img.copy(); cv2.ellipse(sh, (int(sp[0]), int(sp[1])), (int(r * 1.4), int(r * 0.35)), 0, 0, 360, (40, 40, 45), -1, cv2.LINE_AA)
            cv2.addWeighted(sh, 0.35, img, 0.65, 0, img)
        for _d, w, col in sorted(faces, key=lambda f: -f[0]):
            if (w[:, 2] - cz < 0.4).any(): continue
            pts = np.round(proj(w, cz) * 8).astype(np.int32)
            cv2.fillPoly(img, [pts], col, cv2.LINE_AA, 3); cv2.polylines(img, [pts], True, tuple(int(c * 0.7) for c in col), 1, cv2.LINE_AA, 3)

    def frame(self, i):
        j = i % self.cyc
        cz = self.speed * j / FPS; k = float(self.kick[min(i, self.n - 1)])
        img = self.street(cz)
        self.draw_thing(img, j, cz)
        loop = np.round(self.loop * 8).astype(np.int32)                       # the line: on the whole time
        ov = img.copy(); cv2.polylines(ov, [loop], True, (235, 25, 30), 7, cv2.LINE_AA, 3); cv2.addWeighted(ov, 0.95, img, 0.05, 0, img)
        if abs(j - self.jl) < 4:                                              # the bump when we hit it
            dy = int(10 * (1 - abs(j - self.jl) / 4))
            if dy: img = np.ascontiguousarray(np.r_[np.repeat(img[:1], dy, 0), img[:-dy]])
        im = Image.fromarray(img); d = ImageDraw.Draw(im)
        title = 'CAN YOU STOP THIS?'; y0 = 250
        tw = d.textlength(title, font=self.f_title)
        lay = Image.new('L', (int(tw) + 40, 170), 0); ImageDraw.Draw(lay).text((20, 10), title, font=self.f_title, fill=255)
        lay = lay.transform(lay.size, Image.AFFINE, (1, 0.18, -14, 0, 1, 0), Image.BICUBIC)
        grad = np.linspace(0, 1, lay.size[1])[:, None]
        rgb = (np.array([150, 240, 40]) * (1 - grad[..., None]) + np.array([255, 235, 40]) * grad[..., None]) * np.ones((1, lay.size[0], 1))
        txt = Image.fromarray(rgb.astype(np.uint8)); x = int((W - lay.size[0]) / 2)
        from PIL import ImageFilter
        im.paste((10, 40, 20), (x, y0), lay.filter(ImageFilter.MaxFilter(9))); im.paste(txt, (x, y0), lay)
        d.text((W / 2, y0 + 190), ASKS[self.ask].upper(), font=self.f_sub, fill=(255, 255, 255), anchor='mm', stroke_width=4, stroke_fill=(20, 20, 20))
        d.text((W / 2, H * 0.80), self.credit, font=self.f_small, fill=(245, 245, 245), anchor='mm', stroke_width=2, stroke_fill=(30, 30, 30))
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames; loop', self.cyc, 'hit', self.jl, 'line', self.jh); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 60 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'stopit')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 44.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
