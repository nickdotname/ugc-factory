#!/usr/bin/env python3
"""math.explainers, the "surface" style: one chapter of multivariable calculus on a lit 3D surface, in an editorial
look (serif headline with an italic word, small-caps chapter line, typeset equation, a live computed readout).

    python studio/surface_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/surface_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

Every number on screen is computed from the surface drawn: the height under the climbing ball, the best point on the
circle (searched over 3600 angles), the column sum against the integral (a 600x600 grid). Nothing is made up.
Chapters (knob 'chapter'):
  gradient  - arrows of grad f over the surface; a ball climbs along them to the top (gradient ascent)
  lagrange  - a glowing circle on the surface; a point runs round it and stops where f is highest on it,
              where grad f lines up with the circle's normal
  columns   - the volume over the disc filled with columns, 4 -> 16 -> 64 -> 256, the sum closing on the integral
Knobs: chapter, surface (which landscape), palette (turbo/ocean/ember).
Drawn in numpy/OpenCV, equations with matplotlib's mathtext (Computer Modern), headline in Fraunces (OFL).
"""
import io, json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
BG = np.array([17, 17, 20], np.float32)

SURFACES = {   # sums of bumps: (x0, y0, height, width)
    'hills':  [(0.45, -0.35, 1.25, 0.42), (-0.55, 0.45, -0.9, 0.38), (0.55, 0.55, 0.55, 0.3)],
    'ridge':  [(-0.2, -0.3, 1.0, 0.5), (0.5, 0.35, 0.8, 0.35), (-0.6, 0.6, -0.6, 0.3)],
    'crater': [(0.0, 0.0, 1.1, 0.6), (0.0, 0.0, -0.8, 0.25), (0.6, -0.5, 0.4, 0.25)],
}
PALS = {
    'turbo': [(48, 18, 59), (70, 107, 227), (40, 188, 235), (50, 241, 151), (164, 252, 60), (237, 208, 58), (251, 128, 34), (210, 48, 5), (122, 4, 3)],
    'ocean': [(8, 29, 88), (37, 52, 148), (34, 94, 168), (29, 145, 192), (65, 182, 196), (127, 205, 187), (199, 233, 180), (237, 248, 177)],
    'ember': [(20, 11, 52), (87, 16, 110), (151, 41, 102), (209, 76, 76), (243, 127, 40), (250, 193, 39), (252, 255, 164)],
}
CHAPTERS = {
    'gradient': ('I.', 'GRADIENTS', ('Always walk ', 'uphill'), 'the arrows point the steepest way up', r'$\nabla f = \left(\frac{\partial f}{\partial x},\ \frac{\partial f}{\partial y}\right)$'),
    'lagrange': ('II.', 'LAGRANGE MULTIPLIERS', ('Climb, but stay on the ', 'circle'), 'the top of the path is where the arrows line up', r'$\nabla f = \lambda\,\nabla g,\quad g(x,y)=x^2+y^2-r^2$'),
    'columns':  ('III.', 'DOUBLE INTEGRALS', ('Fill the space under it with ', 'columns'), 'over the disc inside the circle', r'$V = \iint_D f(x,y)\,dA$'),
}


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def mono(size):
    p = os.path.join(REPO, 'fonts', 'DejaVuSansMono-Bold.ttf')
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def mathtext(tex, size, color=(235, 235, 235)):
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['mathtext.fontset'] = 'cm'
    fig = plt.figure(figsize=(0.01, 0.01), dpi=100)
    fig.text(0, 0, tex, fontsize=size, color=tuple(c / 255 for c in color))
    buf = io.BytesIO(); fig.savefig(buf, dpi=100, transparent=True, bbox_inches='tight', pad_inches=0.05); plt.close(fig)
    return Image.open(buf).convert('RGBA')


class Surface:
    def __init__(self, bumps):
        self.b = bumps

    def f(self, x, y):
        z = 0.0
        for x0, y0, h, w in self.b: z = z + h * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2 * w * w))
        return z

    def grad(self, x, y):
        gx = gy = 0.0
        for x0, y0, h, w in self.b:
            e = h * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2 * w * w)) / (w * w)
            gx = gx - e * (x - x0); gy = gy - e * (y - y0)
        return gx, gy


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed)
        self.chapter = K.pick('chapter', sorted(CHAPTERS), r)
        self.sname = K.pick('surface', sorted(SURFACES), r); self.S = Surface(SURFACES[self.sname])
        self.pal = np.array(PALS[K.pick('palette', sorted(PALS), r, weights=[3, 1, 1])], np.float32)
        a = audio.load(self.slug, t0, t1); self.n = a['n']; self.spb = a['spb']; self.kick = audio.hits(a['kicks'], self.n, 6.0)
        self.bar = 4 * self.spb * FPS
        g = np.linspace(-1, 1, 41); self.gx, self.gy = np.meshgrid(g, g); self.gz = self.S.f(self.gx, self.gy)
        self.zlo, self.zhi = float(self.gz.min()), float(self.gz.max())
        self.prepare()
        num, name, head, sub, tex = CHAPTERS[self.chapter]
        self.num, self.name, self.head, self.sub = num, name, head, sub
        self.eq = mathtext(tex, 34)
        self.f_head, self.f_sub = font('Fraunces.ttf', 66), font('Fraunces.ttf', 40)
        self.f_cap, self.f_big = mono(24), font('BarlowCondensed-Medium.ttf', 150)
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())

    # ------------------------------------------------------------------ what each chapter computes
    def prepare(self):
        S = self.S
        if self.chapter == 'gradient':                    # gradient ascent from a low start, to the nearest top
            p = np.array([-0.15, 0.85]); path = [p.copy()]
            for _ in range(4000):
                gx, gy = S.grad(p[0], p[1]); g = np.array([gx, gy]); ng = np.linalg.norm(g)
                if ng < 1e-4: break
                p = np.clip(p + 0.004 * g / max(ng, 0.15), -1, 1); path.append(p.copy())
            self.path = np.array(path)
        elif self.chapter == 'lagrange':
            self.R = 0.62; th = np.linspace(0, 2 * np.pi, 3600, endpoint=False)
            v = S.f(self.R * np.cos(th), self.R * np.sin(th)); self.best = float(th[int(np.argmax(v))]); self.bestv = float(v.max())
        else:
            self.R = 0.8; u = np.linspace(-self.R, self.R, 600); X, Y = np.meshgrid(u, u); inside = X * X + Y * Y <= self.R ** 2
            self.exact = float((S.f(X, Y) * inside).sum() * (u[1] - u[0]) ** 2)

    def columns(self, m):
        """m x m columns over the square around the disc; those whose centre is inside the disc count"""
        h = 2 * self.R / m; c = -self.R + h * (np.arange(m) + 0.5); out = []
        for x in c:
            for y in c:
                if x * x + y * y <= self.R ** 2: out.append((x, y, h, float(self.S.f(x, y))))
        return out, sum(z * h * h for *_, z in out)

    # ------------------------------------------------------------------ 3D
    def cam(self, i):
        az = math.radians(35 + 18 * math.sin(2 * math.pi * i / max(1, self.n))); el = math.radians(38)
        return az, el

    def proj(self, x, y, z, i):
        az, el = self.cam(i); s = 420.0
        X = x * math.cos(az) - y * math.sin(az); Y = x * math.sin(az) + y * math.cos(az)
        zz = z * 0.55
        sx = W / 2 + s * X; sy = H * 0.56 + s * (Y * math.sin(el) - zz * math.cos(el))
        depth = Y * math.cos(el) + zz * math.sin(el)
        return sx, sy, depth

    def color(self, z):
        t = np.clip((z - self.zlo) / (self.zhi - self.zlo + 1e-9), 0, 1) * (len(self.pal) - 1)
        k = np.minimum(t.astype(int), len(self.pal) - 2); f = (t - k)[..., None]
        return self.pal[k] * (1 - f) + self.pal[k + 1] * f

    def draw_surface(self, img, i, flat=1.0):
        gx, gy, gz = self.gx, self.gy, self.gz * flat
        sx, sy, d = self.proj(gx, gy, gz, i); col = self.color(self.gz); n = gx.shape[0] - 1
        quads = []
        for a in range(n):
            for b in range(n):
                dd = d[a:a + 2, b:b + 2].mean()
                pts = np.array([[sx[a, b], sy[a, b]], [sx[a, b + 1], sy[a, b + 1]], [sx[a + 1, b + 1], sy[a + 1, b + 1]], [sx[a + 1, b], sy[a + 1, b]]])
                # light from the slope: brighter facing the light
                dzx = gz[a, b + 1] - gz[a, b]; dzy = gz[a + 1, b] - gz[a, b]; sh = np.clip(0.85 + 3.5 * (dzx * 0.6 - dzy * 0.4), 0.55, 1.15)
                quads.append((dd, pts, col[a, b] * sh))
        for dd, pts, c in sorted(quads, key=lambda q: -q[0]):
            p = np.round(pts * 4).astype(np.int32)
            cv2.fillPoly(img, [p], tuple(float(v) for v in c), cv2.LINE_AA, 2)
            cv2.polylines(img, [p], True, tuple(float(v) * 0.72 for v in c), 1, cv2.LINE_AA, 2)

    def floor(self, img, i):
        for u in np.linspace(-1, 1, 21):
            for a, b in (((u, -1), (u, 1)), ((-1, u), (1, u))):
                p = np.array([self.proj(a[0], a[1], 0, i)[:2], self.proj(b[0], b[1], 0, i)[:2]])
                cv2.polylines(img, [np.round(p * 4).astype(np.int32)], False, (55, 60, 70), 1, cv2.LINE_AA, 2)

    def wire(self, img, i, flat):
        """the surface as faint lines over the columns, so the tops can be seen meeting it"""
        sx, sy, _ = self.proj(self.gx, self.gy, self.gz * flat, i); ov = np.zeros_like(img)
        for a in range(0, self.gx.shape[0], 2):
            cv2.polylines(ov, [np.round(np.c_[sx[a], sy[a]] * 4).astype(np.int32)], False, (230, 230, 230), 1, cv2.LINE_AA, 2)
            cv2.polylines(ov, [np.round(np.c_[sx[:, a], sy[:, a]] * 4).astype(np.int32)], False, (230, 230, 230), 1, cv2.LINE_AA, 2)
        self._wire = ov

    def line3(self, img, pts, i, color, width, glow=False):
        q = np.array([self.proj(x, y, z + 0.02, i)[:2] for x, y, z in pts])
        p = np.round(q * 4).astype(np.int32).reshape(-1, 1, 2)
        if glow:
            g = np.zeros_like(img); cv2.polylines(g, [p], False, color, width * 5, cv2.LINE_AA, 2)
            img += cv2.GaussianBlur(g, (0, 0), 9) * 0.6
        cv2.polylines(img, [p], False, color, width, cv2.LINE_AA, 2)

    def arrow3(self, img, x, y, dx, dy, i, color=(240, 240, 240), w=2):
        z = float(self.S.f(x, y)); a = self.proj(x, y, z + 0.02, i)[:2]; b = self.proj(x + dx, y + dy, float(self.S.f(x + dx, y + dy)) + 0.02, i)[:2]
        cv2.arrowedLine(img, (int(a[0] * 4), int(a[1] * 4)), (int(b[0] * 4), int(b[1] * 4)), color, w, cv2.LINE_AA, 2, 0.35)

    def ball(self, img, x, y, i, r=16, color=(255, 255, 255)):
        z = float(self.S.f(x, y)); sx, sy, _ = self.proj(x, y, z + 0.03, i)
        g = np.zeros_like(img); cv2.circle(g, (int(sx), int(sy)), r * 3, color, -1); img += cv2.GaussianBlur(g, (0, 0), 14) * 0.5
        cv2.circle(img, (int(sx), int(sy)), r, color, -1, cv2.LINE_AA)

    # ------------------------------------------------------------------ a frame
    def frame(self, i):
        img = np.zeros((H, W, 3), np.float32) + BG
        yy, xx = np.mgrid[0:H, 0:W]; v = 1 - 0.35 * (((xx - W / 2) / W) ** 2 + ((yy - H * 0.55) / H) ** 2) * 2
        img *= v[..., None]
        p = min(1.0, i / max(1, self.n - 1)); k = float(self.kick[min(i, self.n - 1)])
        rise = min(1.0, i / (self.bar * 0.75))                               # the surface rises out of the floor
        if self.chapter == 'columns': self.floor(img, i); self.wire(img, i, float(rise * (2 - rise)))
        else: self.draw_surface(img, i, flat=float(rise * (2 - rise)))
        readout, label = '', ''
        if self.chapter == 'gradient':
            m = 6
            for a in np.linspace(-0.85, 0.85, m * 2):
                for b in np.linspace(-0.85, 0.85, m * 2):
                    gx, gy = self.S.grad(a, b); ng = math.hypot(gx, gy) + 1e-9; L = 0.07 * min(1, ng / 1.2)
                    self.arrow3(img, a, b, L * gx / ng, L * gy / ng, i, (235, 235, 235), 1)
            t = min(1.0, max(0.0, (i - self.bar) / max(1, self.n - 2 * self.bar)))
            q = self.path[int(t * (len(self.path) - 1))]
            trail = self.path[:int(t * (len(self.path) - 1)) + 1:6]
            if len(trail) > 1: self.line3(img, [(x, y, float(self.S.f(x, y))) for x, y in trail], i, (255, 245, 200), 4, glow=True)
            self.ball(img, q[0], q[1], i, 14 + int(6 * k))
            readout = 'f = %.3f' % float(self.S.f(q[0], q[1])); label = 'HEIGHT UNDER THE BALL'
        elif self.chapter == 'lagrange':
            th = np.linspace(0, 2 * np.pi, 240)
            ring = [(self.R * math.cos(a), self.R * math.sin(a), float(self.S.f(self.R * math.cos(a), self.R * math.sin(a)))) for a in th]
            self.line3(img, ring, i, (220, 255, 245), 4, glow=True)
            t = min(1.0, max(0.0, (i - self.bar) / max(1, self.n - 2.5 * self.bar)))
            ang = self.best + (1 - t * (2 - t)) * 2 * math.pi * 1.25                # runs round, slows to the best point
            x, y = self.R * math.cos(ang), self.R * math.sin(ang)
            gx, gy = self.S.grad(x, y); ng = math.hypot(gx, gy) + 1e-9
            self.arrow3(img, x, y, 0.3 * gx / ng, 0.3 * gy / ng, i, (255, 230, 120), 5)            # grad f
            self.arrow3(img, x, y, 0.3 * math.cos(ang), 0.3 * math.sin(ang), i, (140, 220, 255), 5)  # grad g (outward)
            self.ball(img, x, y, i, 13 + int(5 * k))
            readout = 'f = %.3f' % float(self.S.f(x, y))
            label = 'MAX ON THE CIRCLE  f = %.3f' % self.bestv if t >= 1 else 'HEIGHT ON THE CIRCLE'
        else:
            steps = [4, 8, 16, 32]; stage = min(len(steps) - 1, int(max(0, i - self.bar) / max(1, (self.n - self.bar) / len(steps))))
            cols, V = self.columns(steps[stage])
            az, el = self.cam(i)
            def boxd(c): return self.proj(c[0], c[1], 0, i)[2]
            for x, y, h, z in sorted(cols, key=lambda c: -boxd(c)):
                zz = z * min(1.0, rise)                                 # below the floor where f < 0: those count negative
                corners = [(x - h / 2, y - h / 2), (x + h / 2, y - h / 2), (x + h / 2, y + h / 2), (x - h / 2, y + h / 2)]
                top = np.array([self.proj(cx, cy, zz, i)[:2] for cx, cy in corners]); bot = np.array([self.proj(cx, cy, 0, i)[:2] for cx, cy in corners])
                c = self.color(np.array(z))
                for e in range(4):
                    f2 = np.array([bot[e], bot[(e + 1) % 4], top[(e + 1) % 4], top[e]])
                    cv2.fillPoly(img, [np.round(f2 * 4).astype(np.int32)], tuple(float(v) * 0.62 for v in c), cv2.LINE_AA, 2)
                cv2.fillPoly(img, [np.round(top * 4).astype(np.int32)], tuple(float(v) for v in c), cv2.LINE_AA, 2)
            img += self._wire * 0.22
            th = np.linspace(0, 2 * np.pi, 200)
            self.line3(img, [(self.R * math.cos(a), self.R * math.sin(a), -0.02) for a in th], i, (235, 235, 235), 2)
            readout = 'V ≈ %.3f' % V; label = '%d COLUMNS   ·   EXACT %.3f' % (len(cols), self.exact)
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        # the editorial frame
        d.text((W / 2, 110), '@MATH.EXPLAINERS  ·  CALC III', font=self.f_cap, fill=(170, 170, 175), anchor='mm')
        d.text((70, 190), self.num, font=self.f_sub, fill=(150, 150, 155), anchor='lm')
        d.line((140, 190, W - 70 - d.textlength(self.name, font=self.f_cap) - 30, 190), fill=(70, 70, 75), width=2)
        d.text((W - 70, 190), self.name, font=self.f_cap, fill=(170, 170, 175), anchor='rm')
        a, b = self.head; fh = self.f_head
        while d.textlength(a + b, font=fh) > W - 110: fh = font('Fraunces.ttf', fh.size - 2)
        wa = d.textlength(a, font=fh); wb = d.textlength(b, font=fh)
        x0 = (W - wa - wb * 0.98) / 2; d.text((x0, 300), a, font=fh, fill=(240, 238, 232), anchor='lm')
        lay = Image.new('L', (int(wb) + 40, 110), 0); ImageDraw.Draw(lay).text((10, 55), b, font=fh, fill=255, anchor='lm')
        lay = lay.transform(lay.size, Image.AFFINE, (1, 0.2, -12, 0, 1, 0), Image.BICUBIC); im.paste((240, 238, 232), (int(x0 + wa - 10), 245), lay)
        lay = Image.new('L', (W, 70), 0); ImageDraw.Draw(lay).text((W / 2, 35), self.sub, font=self.f_sub, fill=255, anchor='mm')
        lay = lay.transform(lay.size, Image.AFFINE, (1, 0.2, -7, 0, 1, 0), Image.BICUBIC); im.paste((175, 172, 165), (0, 345), lay)
        eq = self.eq; im.paste(eq, (int((W - eq.width) / 2), 440), eq)
        if readout:
            d.text((70, H - 360), readout, font=self.f_big, fill=(245, 245, 245), anchor='lm')
            d.text((74, H - 270), label, font=self.f_cap, fill=(150, 150, 155), anchor='lm')
        d.text((W / 2, H - 170), self.credit, font=self.f_cap, fill=(160, 160, 165), anchor='mm')
        d.text((W / 2, H - 125), 'ANIMATED IN CODE  ·  EVERY NUMBER COMPUTED', font=ImageFont.truetype(os.path.join(REPO, 'fonts', 'DejaVuSansMono-Bold.ttf'), 18) if os.path.exists(os.path.join(REPO, 'fonts', 'DejaVuSansMono-Bold.ttf')) else self.f_cap, fill=(95, 95, 100), anchor='mm')
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((540, 960)) for f in fs]
            sheet = Image.new('RGB', (540 * len(ims), 960))
            for j, im in enumerate(ims): sheet.paste(im, (540 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n); return
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


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 44.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
