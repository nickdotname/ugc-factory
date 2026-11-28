#!/usr/bin/env python3
"""Turing patterns grown live on the beat (a ready page: two.chemicals, paused until its Instagram account exists; see
docs/brain/ready-pages.md).

    python studio/turing_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/turing_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

A Gray-Scott reaction-diffusion simulation on a 135 x 240 grid (one cell = 8 px), drawn smooth with a little relief.
Two chemicals: A feeds in everywhere (rate F), B eats A to make more B and is removed (rate k); A spreads twice as fast as
B. The same rule with different F and k grows spots, a maze, coral or holes: Turing's 1952 idea of how a coat
could pattern itself. Every number on screen is the simulation's own (F, k, the step count).
  ask    drops of B land on the kicks while the sim runs slowly; 'what grows from these drops?' with F and k
  grow   on the beat the sim runs ~60x faster ('step 4,180' counts up) and the dish fills; the answer is named
  scratch on the beat a disc is wiped clean ('scratch it.'), and it grows back by the same rule ('it grows back.')
  end    the Turing line; the last 9 frames fade into frame 0
Choreographed in beats; a stretch too short exits 3.
Knobs (studio/knobs.py): pattern (spots, maze, coral, holes; the nightly subject), palette (ochre, chalk,
reef, moss, neon).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
GW, GH, CELL = 135, 240, 8
MAX_LEN = 24.0

PATTERNS = {   # F, k, the answer, how many steps the dish needs to fill, how fast it runs after the drop
    'spots':   (0.0370, 0.0650, 'spots.', 6000),
    'maze':    (0.0290, 0.0570, 'a maze.', 4200),
    'coral':   (0.0545, 0.0620, 'coral.', 4200),
    'holes':   (0.0390, 0.0580, 'holes.', 4200),
}
PALETTES = {   # ground, pattern, text, card
    'ochre': dict(bg=(222, 172, 96), fg=(46, 28, 18), txt=(250, 244, 232), card=(46, 28, 18)),
    'chalk': dict(bg=(238, 234, 224), fg=(26, 26, 30), txt=(26, 26, 30), card=(238, 234, 224)),
    'reef':  dict(bg=(10, 42, 72), fg=(255, 124, 100), txt=(246, 240, 232), card=(8, 30, 52)),
    'moss':  dict(bg=(22, 46, 30), fg=(196, 224, 124), txt=(236, 242, 220), card=(14, 32, 20)),
    'neon':  dict(bg=(16, 10, 30), fg=(236, 64, 172), fg2=(64, 214, 236), txt=(244, 240, 250), card=(16, 10, 30)),
}
ASK = ['what grows from\nthese drops?', 'two chemicals, one rule.\nwhat pattern grows?', 'drops of one chemical\nin another. what grows?']
SCRATCH, HEAL = 'scratch it.', 'it grows back.'
END = 'Turing, 1952: two chemicals\nspreading at different speeds\ncan paint a pattern.'


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)


def lap(X):
    """The 3x3 Laplacian (0.2 sides, 0.05 corners, -1 centre) on a torus."""
    up, dn = np.roll(X, 1, 0), np.roll(X, -1, 0)
    return (-X + 0.2 * (up + dn + np.roll(X, 1, 1) + np.roll(X, -1, 1))
            + 0.05 * (np.roll(up, 1, 1) + np.roll(up, -1, 1) + np.roll(dn, 1, 1) + np.roll(dn, -1, 1)))


class Dish:
    def __init__(self, F, k):
        self.F, self.k = F, k; self.steps = 0
        self.A = np.ones((GH, GW), np.float32); self.B = np.zeros((GH, GW), np.float32)

    def drop(self, y, x, r=3.5):
        yy, xx = np.mgrid[0:GH, 0:GW]; m = (yy - y) ** 2 + (xx - x) ** 2 < r * r
        self.B[m] = 1.0; self.A[m] = 0.5

    def wipe(self, cy, cx, R):
        yy, xx = np.mgrid[0:GH, 0:GW]; m = (yy - cy) ** 2 + (xx - cx) ** 2 < R * R
        self.A[m] = 1.0; self.B[m] = 0.0

    def run(self, n):
        A, B, F, k = self.A, self.B, self.F, self.k
        for _ in range(n):
            AB2 = A * B * B
            A += lap(A) - AB2 + F * (1 - A)
            B += 0.5 * lap(B) + AB2 - (k + F) * B
        self.steps += n


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.seed = seed
        self.slug = os.path.basename(os.path.normpath(song_dir))
        t1 = min(t1, t0 + MAX_LEN)
        r = random.Random(seed); self.r = r
        self.pattern = K.pick('pattern', sorted(PATTERNS), r)
        self.pal_name = K.pick('palette', sorted(PALETTES), r)
        self.pal = PALETTES[self.pal_name]
        self.F, self.k, self.answer, self.fill = PATTERNS[self.pattern]
        self.ask = r.choice(ASK)
        a = audio.load(self.slug, t0, t1); n = a['n']
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.kick = audio.hits(a['kicks'], n, 7.0)
        B = [int(round(f)) for _, f in a['beats'] if 0 <= f < n]
        if len(B) < 16: print('not rendered: %.1f s is too short (%s)' % (t1 - t0, self.slug)); sys.exit(3)
        step = (B[-1] - B[0]) / max(1, len(B) - 1)
        u = max(1, int(math.ceil(12 / step)))

        def at_or_after(f):
            nb = [b for b in B if b >= f]; return nb[0] if nb else None
        grow = at_or_after(int(4.5 * FPS))
        if grow is None: print('not rendered: too short to ask (%s)' % self.slug); sys.exit(3)
        self.t_grow = grow
        scratch = at_or_after(grow + int(3.6 * FPS))
        if scratch is None or B.index(scratch) + u >= len(B): print('not rendered: too short to scratch (%s)' % self.slug); sys.exit(3)
        self.t_scratch = (scratch, B[B.index(scratch) + u])          # the disc is wiped over one move
        end = at_or_after(self.t_scratch[1] + int(3.0 * FPS))
        if end is None: print('not rendered: too short to end (%s)' % self.slug); sys.exit(3)
        self.t_end = end
        self.n = n = min(n, end + int(2.6 * FPS) + 9)
        self.t0, self.t1 = t0, t0 + n / FPS
        # drops: four already down at frame 0, then one on each kick of the question (at most 10 more)
        kicks = sorted(set(int(x) for x in a['kicks'] if 0 < x < grow))
        if len(kicks) > 10: kicks = kicks[::int(math.ceil(len(kicks) / 10))]
        self.drops = {0: [self._spot() for _ in range(4)]}
        for f in kicks: self.drops.setdefault(f, []).append(self._spot())
        self.wipe_at = (int(GH * r.uniform(0.40, 0.58)), int(GW * r.uniform(0.38, 0.62)), int(GW * 0.36))
        # steps per frame: slow while asking, then fast enough that the dish fills in ~3 s
        self.slow = 3
        self.fast = int(math.ceil(self.fill / (3.0 * FPS)))
        self.heal = int(math.ceil(self.fill * 0.75 / (3.0 * FPS)))
        self.f_ask = font('Fraunces.ttf', 66); self.f_num = font('DejaVuSansMono-Bold.ttf', 34)
        self.f_ans = font('Fraunces.ttf', 92); self.f_end = font('Fraunces.ttf', 54)
        self.f_credit = font('DejaVuSansMono-Bold.ttf', 26)
        self._cache = {}; self._first = None
        self._grad = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]

    def _spot(self):
        return (self.r.randint(58, 168), self.r.randint(14, GW - 15))       # clear of the question and the numbers

    def states(self):
        """Run the dish once, frame by frame: (A copy not needed) B of every frame and the step count."""
        if self._cache: return self._cache
        d = Dish(self.F, self.k); out = {}
        for i in range(self.n):
            for (y, x) in self.drops.get(i, []): d.drop(y, x)
            if self.t_scratch[0] <= i <= self.t_scratch[1]:
                cy, cx, R = self.wipe_at
                d.wipe(cy, cx, max(2, R * ease((i - self.t_scratch[0] + 1) / max(1, self.t_scratch[1] - self.t_scratch[0] + 1))))
            if i < self.t_grow: d.run(self.slow)
            elif i < self.t_scratch[0]: d.run(self.fast)
            elif i <= self.t_scratch[1]: pass
            elif i < self.t_end + int(1.0 * FPS): d.run(self.heal)
            else: d.run(self.slow)
            out[i] = (d.B.copy(), d.steps)
        self._cache = out
        return out

    def paint(self, Bm):
        v = np.clip(Bm * 3.2, 0, 1)
        big = cv2.resize(v, (W, H), interpolation=cv2.INTER_CUBIC)
        m = np.clip((big - 0.30) / 0.34, 0, 1); m = m * m * (3 - 2 * m)
        gy, gx = np.gradient(cv2.GaussianBlur(big, (0, 0), 3))
        light = np.clip(1.0 + (-gx - gy) * 9.0, 0.75, 1.25)[..., None]          # a little relief, lit from the top left
        bg = np.array(self.pal['bg'], np.float32); fg = np.array(self.pal['fg'], np.float32)
        if 'fg2' in self.pal: fg = fg * (1 - self._grad) + np.array(self.pal['fg2'], np.float32) * self._grad
        img = bg * (1 - m[..., None]) + fg * m[..., None]
        img = img * (1 + (light - 1) * m[..., None])
        return np.clip(img, 0, 255).astype(np.uint8)

    def card(self, d, xy, text, f, align='center'):
        x, y = xy
        bb = d.multiline_textbbox((x, y), text, font=f, anchor='mm', align=align, spacing=10)
        pad = 26
        c = self.pal['card']
        d.rounded_rectangle((bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad), 26, fill=c + (222,))
        d.multiline_text((x, y), text, font=f, fill=self.pal['txt'], anchor='mm', align=align, spacing=10)

    def draw(self, i, top=True):
        Bm, steps = self.states()[i]
        base = Image.fromarray(self.paint(Bm)).convert('RGBA')
        ov = Image.new('RGBA', base.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
        # a ripple where a drop just landed
        for f, spots in self.drops.items():
            if f > 0 and 0 <= i - f < 12:
                a = (i - f) / 12.0
                for (y, x) in spots:
                    R = 14 + 70 * a; cx, cy = x * CELL + CELL / 2, y * CELL + CELL / 2
                    d.ellipse((cx - R, cy - R, cx + R, cy + R), outline=tuple(self.pal['txt']) + (int(200 * (1 - a)),), width=4)
        if self.t_scratch[0] <= i < self.t_scratch[1] + 10:              # the scratch, outlined while it is made
            cy, cx, R = self.wipe_at; a = min(1.0, (i - self.t_scratch[0]) / 10.0) if i > self.t_scratch[1] else 0
            Rp = R * CELL * ease((i - self.t_scratch[0] + 1) / max(1, self.t_scratch[1] - self.t_scratch[0] + 1))
            X, Y = cx * CELL, cy * CELL
            d.ellipse((X - Rp, Y - Rp, X + Rp, Y + Rp), outline=tuple(self.pal['txt']) + (int(230 * (1 - a)),), width=6)
        if top:
            nums = 'feed %.4f   kill %.4f' % (self.F, self.k)
            if i < self.t_grow:
                self.card(d, (W / 2, 300), self.ask, self.f_ask)
                u = i / max(1, self.t_grow); k = float(self.kick[min(i, len(self.kick) - 1)])
                x0, x1, y = 340, 740, 1560
                d.rounded_rectangle((x0 - 14, y - 22, x1 + 14, y + 22), 22, fill=self.pal['card'] + (200,))
                d.rounded_rectangle((x0, y - 5, x1, y + 5), 5, fill=tuple(self.pal['txt']) + (70,))
                d.rounded_rectangle((x0, y - 5 - 2 * k, x0 + (x1 - x0) * u, y + 5 + 2 * k), 5, fill=tuple(self.pal['txt']) + (255,))
            elif i < self.t_scratch[0]:
                ans = i >= self.t_grow + int(1.6 * FPS)
                self.card(d, (W / 2, 300), self.answer if ans else 'step %s' % format(steps, ','), self.f_ans if ans else self.f_ask)
            elif i < self.t_scratch[1] + int(1.2 * FPS):
                self.card(d, (W / 2, 300), SCRATCH, self.f_ask)
            elif i < self.t_end:
                self.card(d, (W / 2, 300), HEAL, self.f_ask)
            else:
                self.card(d, (W / 2, 330), END, self.f_end)
            if i < self.t_end:
                self.card(d, (W / 2, 1460), nums, self.f_num)
        bb = d.textbbox((W / 2, 1650), self.credit, font=self.f_credit, anchor='mm')
        d.rounded_rectangle((bb[0] - 16, bb[1] - 10, bb[2] + 16, bb[3] + 10), 14, fill=self.pal['card'] + (190,))
        d.text((W / 2, 1650), self.credit, font=self.f_credit, fill=self.pal['txt'], anchor='mm')
        return np.asarray(Image.alpha_composite(base, ov).convert('RGB'))

    def frame(self, i):
        tail = 9; o = self.draw(i, top=i < self.n - tail - 4)
        if i >= self.n - tail:
            if self._first is None: self._first = self.draw(0).astype(np.float32)
            a = (i - (self.n - tail) + 1) / (tail + 1)
            o = (o.astype(np.float32) * (1 - a) + self._first * a).astype(np.uint8)
        return o

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', 'grow', self.t_grow, 'scratch', self.t_scratch, 'end', self.t_end, 'steps', self.states()[self.n - 1][1]); return
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
        rec = K.record(); rec['pictures'] = 'simulated in code (Gray-Scott reaction-diffusion)'
        json.dump(rec, open(out[:-4] + '.json', 'w')); print('done', out, rec['knobs'])


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 52.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
