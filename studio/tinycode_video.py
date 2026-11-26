#!/usr/bin/env python3
"""Tiny code: a program short enough to read in one glance, running to one song.

    python studio/tinycode_video.py SONG_DIR SEED OUT.mp4 [--frames a,b,c]     (CQ_WINDOW="t0,t1")

The top of the screen is an editor holding the whole program (a few lines of numpy, a couple of hundred
characters); the square under it is what that program draws, frame by frame. The program shown is the program run:
each PROGRAMS entry is exec'd every frame with t (seconds), k (the kick, 0..1), b (the bass) and N in scope, and
returns points (x, y in -1..1) with a hue each, or (for the field ones) a brightness per pixel.
Knobs: program, palette, glow, trail.
"""
import json, os, random, subprocess, sys, math
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish

W, H, FPS = 1080, 1920, 30
MONO = next(p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', os.path.join(REPO, 'fonts', 'DejaVuSansMono.ttf')) if os.path.exists(p))

# Each program sets x, y (points) and c (a hue 0..1 per point), or F (a field over the grid u, v).
PROGRAMS = {
    'sunflower': """i = arange(N)
r = sqrt(i / N) * (1 + .25 * k)
a = i * 2.39996 + t * (1 - r)
w = .2 * sin(9 * a + 3 * t)
x, y = r * cos(a) * (1 + w), r * sin(a) * (1 - w)
c = r + .1 * t""",
    'knot': """s = linspace(0, 2 * pi, N)
p, q = 3, 5 + round(2 * k)
x = (cos(q * s) + 2) * cos(p * s + t) / 3.2
y = (cos(q * s) + 2) * sin(p * s + t) / 3.2
y += .3 * sin(q * s - t) * (.6 + k)
c = s / 2 / pi + .2 * sin(t)""",
    'ridges': """i = arange(N)
row, s = i // 1500, i % 1500 / 750 - 1
z = exp(-6 * s * s) * sin(row * 1.7 + 3 * t + 7 * s)
x = s * .9
y = row / 20 - 1 + .3 * abs(z) * (1 + 2 * k)
c = row / 40 + .1 * t""",
    'orbits': """i = arange(N)
m = i % 7 + 1
a = i * .013 + t * m / 4
r = .2 + .11 * m
r += .04 * sin(3 * m * a) * (1 + 3 * k)
x, y = r * cos(a), r * sin(a) * .8
c = m / 7 + .03 * t""",
    'interference': """u, v = meshgrid(*[linspace(-1, 1, 1000)] * 2)
a = hypot(u - .4 * sin(t), v - .3)
b = hypot(u + .4 * cos(t * .7), v + .3)
F = sin(30 * a - 5 * t) + sin(30 * b - 5 * t)
F = (F / 2) ** 2 * (.7 + .6 * k)
C = .5 + .5 * sin(3 * (a - b) + t)""",
    'lissajous': """s = linspace(0, 2 * pi, N)
a, b = 3, 4 + round(k)
x = sin(a * s + t) * (1 - .3 * k * sin(9 * s))
y = sin(b * s) * cos(s + t / 3)
c = s / 2 / pi + .1 * t""",
    'rose': """s = linspace(0, 2 * pi, N)
n = 5 + 2 * sin(t / 4)
r = cos(n * s) * (.8 + .2 * k)
r += .03 * sin(60 * s + 9 * t)
x, y = r * cos(s + t / 5), r * sin(s + t / 5)
c = abs(r) + .05 * t""",
    'spirograph': """s = linspace(0, 40 * pi, N)
R, r = 1, .37 + .02 * sin(t / 3)
d = .6 + .25 * k
x = (R - r) * cos(s) + d * cos((R - r) / r * s)
y = (R - r) * sin(s) - d * sin((R - r) / r * s)
x, y, c = x / 1.4, y / 1.4, s / 40 / pi""",
    'attractor': """x = y = linspace(-1, 1, N)
a = -1.4 + .1 * sin(t / 3)
b = 1.6 + .2 * k
for _ in range(24):
    x, y = (sin(a * y) + cos(a * x),
            sin(b * x) + .7 * cos(b * y))
x, y, c = x / 2.2, y / 2, .3 * x + .05 * t""",
    'plasma': """u, v = meshgrid(*[linspace(-1, 1, 1000)] * 2)
F = sin(9 * u + t) + sin(8 * v - t)
F += sin(7 * (u + v) + 2 * t)
F += sin(11 * hypot(u, v) - 3 * t)
C = F / 8 + .1 * t
F = .4 + .4 * (F / 4) ** 2 + .5 * k""",
    'tunnel': """u, v = meshgrid(*[linspace(-1, 1, 1000)] * 2)
r, a = hypot(u, v) + .01, arctan2(v, u)
z = 1 / r + 2 * t
F = (sin(6 * a + 4 * z) > .3 - .4 * k) * r
F = F * 1.4
C = z / 6 + a / 2 / pi""",
    'metaballs': """u, v = meshgrid(*[linspace(-1, 1, 1000)] * 2)
F = 0 * u
for j in range(6):
    p = .6 * sin(t * (.5 + j / 7) + j)
    q = .6 * cos(t * (.4 + j / 9) + 2 * j)
    F += .05 * (1 + k) / ((u-p)**2 + (v-q)**2)
C = .2 * sin(F) + .05 * t
F = (F > 1) * .9 + .2 * tanh(F / 6)""",
    'galaxy': """i = arange(N)
arm = i % 4
r = (i / N) ** .6
a = arm * pi / 2 + 4 * r - t / 3
a += .4 * sin(i * 7.31) * (1 - r)
x, y = r * cos(a), .6 * r * sin(a)
c = arm / 4 + r / 2 + .3 * k""",
}
PALETTES = {                                    # iq's cosine palettes: colour(h) = a + b * cos(2π(c * h + d))
    'neon': ([.5, .5, .5], [.5, .5, .5], [1, 1, 1], [0, .33, .67]),
    'sunset': ([.5, .5, .5], [.5, .5, .5], [1, .7, .4], [0, .15, .20]),
    'ice': ([.5, .5, .5], [.5, .5, .5], [1, 1, .5], [.8, .9, .3]),
    'acid': ([.5, .5, .5], [.5, .5, .5], [2, 1, 0], [.5, .2, .25]),
}
NS = {k: getattr(np, k) for k in ('arange', 'sqrt', 'sin', 'cos', 'exp', 'hypot', 'linspace', 'meshgrid', 'pi', 'round', 'abs', 'tanh', 'arctan2')}
NS['round'] = round
NS['range'] = range


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed)
        self.prog = K.pick('program', sorted(PROGRAMS), r)
        self.pal = K.pick('palette', sorted(PALETTES), r)
        self.glow = float(K.pick('glow', [0.6, 1.0, 1.5], r))
        self.trail = float(K.pick('trail', [0.0, 0.55, 0.8], r, weights=[1, 2, 1]))
        self.code = PROGRAMS[self.prog]; self.compiled = compile(self.code, self.prog, 'exec')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 5.0); self.bass = np.convolve(a['bass'], np.ones(3) / 3, 'same')
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — close quarters' % song.get('title', self.slug).lower()
        self.S = 1000; self.prev = np.zeros((self.S, self.S, 3), np.float32)
        self.f_code = ImageFont.truetype(MONO, 28); self.f_ui = ImageFont.truetype(MONO, 24)
        self.editor = self.draw_editor()

    def colour(self, h):
        a, b, c, d = (np.array(x, np.float32) for x in PALETTES[self.pal])
        h = np.asarray(h, np.float32)[..., None]
        return np.clip(a + b * np.cos(2 * np.pi * (c * h + d)), 0, 1) * 255

    def draw_editor(self):
        lines = self.code.split('\n'); lh = 46
        im = Image.new('RGB', (W - 80, lh * len(lines) + 40), (18, 20, 26)); d = ImageDraw.Draw(im)
        kw = {'for', 'in', 'def', 'return'}
        for j, line in enumerate(lines):
            d.text((20, 22 + j * lh), '%2d' % (j + 1), font=self.f_code, fill=(70, 76, 90))
            x = 80
            for tok in __import__('re').findall(r"\d*\.?\d+|[A-Za-z_]+|\s+|.", line):
                col = (230, 232, 240)
                if tok[:1].isdigit() or tok[:1] == '.' and tok[1:2].isdigit(): col = (255, 184, 108)
                elif tok in NS or tok in ('linspace', 'meshgrid'): col = (130, 200, 255)
                elif tok in ('t', 'k', 'N'): col = (255, 121, 198)
                elif tok in kw: col = (255, 121, 198)
                d.text((x, 22 + j * lh), tok, font=self.f_code, fill=col); x += self.f_code.getlength(tok)
        return np.asarray(im)

    def canvas(self, i):
        t = i / FPS; S = self.S
        ns = dict(NS, t=t, k=float(self.kick[i]), b=float(self.bass[i]), N=60000)
        exec(self.compiled, ns)
        if 'F' in ns:
            F = np.clip(ns['F'], 0, 1.5); C = ns.get('C', F)
            img = self.colour(C) * F[..., None]
            img = cv2.resize(img.astype(np.float32), (S, S), interpolation=cv2.INTER_CUBIC)
        else:
            x, y, c = (np.asarray(ns[k], np.float32).ravel() for k in ('x', 'y', 'c'))
            fx = (x * 0.47 + 0.5) * S - .5; fy = (-y * 0.47 + 0.5) * S - .5          # each point shared over its four pixels: smooth, not stair-stepped
            px = np.floor(fx).astype(np.int32); py = np.floor(fy).astype(np.int32); ax = fx - px; ay = fy - py
            ok = (px >= 0) & (px < S - 1) & (py >= 0) & (py < S - 1)
            px, py, ax, ay = px[ok], py[ok], ax[ok], ay[ok]; col = self.colour(c[ok]) * (0.55 * 60000 / max(len(x), 1))
            img = np.zeros((S, S, 3), np.float32)
            for dx, dy, wgt in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
                idx = (py + dy) * S + px + dx
                for ch in range(3): img[..., ch] += np.bincount(idx, col[:, ch] * wgt, S * S).reshape(S, S)
            img = cv2.GaussianBlur(img, (0, 0), .8) * 2.2
        small = cv2.resize(img, (S // 4, S // 4), interpolation=cv2.INTER_AREA)
        img = img + cv2.resize(cv2.GaussianBlur(small, (0, 0), 6), (S, S)) * self.glow * (0.8 + 0.8 * self.kick[i])
        img = np.maximum(img, self.prev * self.trail); self.prev = img
        return 255 * (1 - np.exp(-np.clip(img, 0, None) / 160))     # soft tone-map: dense areas glow instead of clipping

    def frame(self, i):
        out = np.full((H, W, 3), 8, np.float32)
        e = self.editor; ey = 170; out[ey:ey + e.shape[0], 40:40 + e.shape[1]] = e
        c = self.canvas(i); S = self.S
        top = ey + e.shape[0]; cy = top + max(30, (H - 150 - top - S) // 2)   # the square sits in the middle of what is left
        out[cy:cy + S, (W - S) // 2:(W - S) // 2 + S] = c
        im = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        d.text((40, 95), '%s.py' % self.prog, font=self.f_ui, fill=(200, 205, 215))
        d.text((W - 40, 95), '%d chars · running' % len(self.code), font=self.f_ui, fill=(126, 231, 135) if (i // 15) % 2 == 0 else (80, 160, 95), anchor='ra')
        d.text((40, H - 95), self.credit, font=self.f_ui, fill=(225, 225, 232))
        d.text((W - 40, H - 95), 't = %5.2f   k = %.2f' % (i / FPS, self.kick[i]), font=self.f_ui, fill=(120, 124, 136), anchor='ra')
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = []
            for f in range(max(fs) + 1):
                if f in fs: ims.append(Image.fromarray(self.frame(f)).resize((360, 640)))
                elif self.trail: self.canvas(f)                                 # keep the trail honest
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n): p.stdin.write(self.frame(i).tobytes())
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'tinycode')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
