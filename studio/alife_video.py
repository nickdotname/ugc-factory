#!/usr/bin/env python3
"""Digital creatures: a slime mould of a couple of hundred thousand simple agents finding its shape to one song.

    python studio/alife_video.py SONG_DIR SEED OUT.mp4 [--frames a,b,c]     (CQ_WINDOW="t0,t1")

Each agent only smells the trail in front of it (left, ahead, right), turns toward the strongest, steps forward and
leaves a little trail of its own; the trail spreads and fades. From that the colony draws veins, loops and networks,
the way Physarum polycephalum does. The music is the weather: the kick makes them run, the snare scatters a burst of
new agents from a point, the bass widens how far they look.
Knobs: start (ring, seeds, rain), palette, sense (how far ahead they smell), steps (simulation steps per frame), line (the
opening line, 64 px from frame 0, each true of every video). CQ_WARMUP (default 10) is the number of steps before frame 0:
it was 90, which threw away the best four seconds (the colony exploding out of the seed) before the song started.
"""
import json, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish
from numba import njit, prange


@njit(parallel=True, fastmath=True, cache=True)
def _move(x, y, h, sp, T, sa, sd, turn, speed, jit, avoid):
    """Each agent smells left, ahead and right (its own species' trail, minus the others' when they avoid each
    other), turns toward the strongest, and steps."""
    S, gh, gw = T.shape
    for k in prange(x.size):
        best = -1e9; pick = 0
        for j in range(3):
            a = h[k] + (j - 1) * sa
            sx = int(x[k] + sd * np.cos(a)) % gw; sy = int(y[k] + sd * np.sin(a)) % gh
            v = 0.0
            for q in range(S):
                v += T[q, sy, sx] if q == sp[k] else -avoid * T[q, sy, sx]
            if j == 1: v += 1e-6                              # ties go straight on
            if v > best: best = v; pick = j
        h[k] += (pick - 1) * turn + jit[k]
        x[k] = (x[k] + speed * np.cos(h[k])) % gw; y[k] = (y[k] + speed * np.sin(h[k])) % gh

@njit(fastmath=True, cache=True)
def _deposit(x, y, sp, T, amt):
    for k in range(x.size):
        T[sp[k], int(y[k]), int(x[k])] += amt

W, H, FPS = 1080, 1920, 30
GW, GH = 1080, 1640                               # the simulation grid: one cell per pixel (it was half size, scaled up: soft)
NA = int(os.environ.get('CQ_AGENTS', '1200000'))   # agents: enough for the fine lace of the real thing, not a few thick veins
MONO = next(p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', os.path.join(REPO, 'fonts', 'DejaVuSansMono.ttf')) if os.path.exists(p))
HOUSE = os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf')
LINES = {'noplan': 'no brain.\nno plan.', 'rules': 'smell. turn. step.\nno brain.', 'cells': '%s cells.\nno brain.'}   # all true of every video
PALETTES = {'gold': [(0, 0, 0), (90, 30, 0), (255, 170, 40), (255, 250, 220)],
            'bio': [(0, 0, 0), (0, 40, 60), (0, 220, 180), (230, 255, 250)],
            'violet': [(0, 0, 0), (40, 0, 70), (220, 60, 255), (255, 230, 255)],
            'ember': [(0, 0, 0), (70, 0, 10), (255, 60, 40), (255, 230, 160)]}
SPECIES = {'gold': [(255, 170, 40), (255, 90, 60), (255, 240, 200)], 'bio': [(0, 230, 190), (60, 140, 255), (200, 255, 120)],
           'violet': [(220, 60, 255), (60, 120, 255), (255, 120, 200)], 'ember': [(255, 60, 40), (255, 190, 60), (120, 40, 255)]}


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.rng = np.random.default_rng(seed)
        self.start = K.pick('start', ['ring', 'seeds', 'rain'], r)
        self.pal = K.pick('palette', sorted(PALETTES), r)
        self.sense = float(K.pick('sense', [6, 9, 14], r))
        self.steps = int(K.pick('steps', [1, 2], r, weights=[1, 2]))
        self.line = K.pick('line', sorted(LINES), r)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 5.0); self.snare = audio.hits(a['snares'], n, 9.0)
        self.snares = set(int(round(f)) for f in a['snares']); self.bass = np.convolve(a['bass'], np.ones(5) / 5, 'same')
        N = NA; g = self.rng
        r2 = random.Random(seed * 13 + 5)                          # its own dice: older seeds keep the rest of their plan
        self.species = int(K.pick('species', [1, 1, 3], r2))       # three colonies that avoid each other's trails
        if self.start == 'ring':
            ang = g.uniform(0, 2 * np.pi, N); rad = g.uniform(0, 1, N) ** 0.5 * 120 + 540
            self.x = GW / 2 + rad * np.cos(ang) * 0.72; self.y = GH / 2 + rad * np.sin(ang) * 1.1; self.h = ang + np.pi
        elif self.start == 'seeds':
            c = g.uniform([160, 240], [GW - 160, GH - 240], (7, 2)); k = g.integers(0, 7, N)
            ang = g.uniform(0, 2 * np.pi, N); rad = g.uniform(0, 50, N)
            self.x = c[k, 0] + rad * np.cos(ang); self.y = c[k, 1] + rad * np.sin(ang); self.h = ang
        else:
            self.x = g.uniform(0, GW, N); self.y = g.uniform(0, GH, N); self.h = g.uniform(0, 2 * np.pi, N)
        self.x, self.y, self.h = self.x.astype(np.float32) % GW, self.y.astype(np.float32) % GH, self.h.astype(np.float32)
        self.sp = (g.integers(0, self.species, N) if self.species > 1 else np.zeros(N, np.int64)).astype(np.int64)
        self.T = np.zeros((self.species, GH, GW), np.float32); self.age = 0
        cols = np.array(PALETTES[self.pal], np.float32); xs = np.linspace(0, 1, len(cols))
        self.lut = np.stack([np.interp(np.linspace(0, 1, 256), xs, cols[:, c]) for c in range(3)], -1).astype(np.float32)
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — close quarters' % song.get('title', self.slug).lower()
        self.f_ui = ImageFont.truetype(MONO, 24); self.f_small = ImageFont.truetype(MONO, 22)
        self.f_credit = ImageFont.truetype(MONO, 36); self.f_line = ImageFont.truetype(HOUSE, 64) if os.path.exists(HOUSE) else self.f_credit
        self.says = LINES[self.line] % format(self.x.size, ',') if '%s' in LINES[self.line] else LINES[self.line]

    def step(self, i):
        sa = 0.39 + 0.15 * self.bass[i]; sd = 2 * self.sense * (1 + 0.6 * self.bass[i])      # at full size it looks twice as far
        jit = self.rng.uniform(-0.05, 0.05, self.x.size).astype(np.float32)
        _move(self.x, self.y, self.h, self.sp, self.T, np.float32(sa), np.float32(sd), np.float32(0.785), np.float32(1.6 + 3.2 * self.kick[i]), jit, np.float32(.6))
        _deposit(self.x, self.y, self.sp, self.T, np.float32(0.12 * (1 + self.kick[i])))
        for q in range(self.species):                         # the trail spreads and fades; a ceiling keeps the colony from collapsing into a few thick veins
            self.T[q] = np.minimum(cv2.blur(self.T[q], (3, 3)) * 0.92, 2.5)

    def burst(self, i):
        """A snare: a few thousand of them are flung out of one point."""
        k = self.rng.choice(self.x.size, 50000, replace=False); px, py = self.rng.uniform([120, 160], [GW - 120, GH - 160])
        self.x[k] = px; self.y[k] = py; self.h[k] = self.rng.uniform(0, 2 * np.pi, k.size)

    def advance(self, i):
        if i in self.snares and self.snare[i] > 0.5: self.burst(i)
        for _ in range(self.steps): self.step(i)
        self.age += self.steps

    def picture(self, i):
        if self.species == 1:
            ref = max(float(np.percentile(self.T[0], 99.7)), 1e-3)        # exposure follows the colony, so it never burns to white
            img = self.lut[(np.clip(self.T[0] / ref, 0, 1) ** 0.8 * 255).astype(np.uint8)]
        else:                                                              # three colonies, three colours, added as light
            img = np.zeros((GH, GW, 3), np.float32)
            for q, col in enumerate(SPECIES[self.pal]):
                ref = max(float(np.percentile(self.T[q], 99.7)), 1e-3)
                img += (np.clip(self.T[q] / ref, 0, 1) ** 0.85)[..., None] * np.array(col, np.float32)
            img = 255 * (1 - np.exp(-img / 255 * 1.2))                     # soft shoulder where they overlap
        small = cv2.resize(img, (GW // 4, GH // 4), interpolation=cv2.INTER_AREA)
        img = img + cv2.resize(cv2.GaussianBlur(small, (0, 0), 5), (GW, GH)) * (0.5 + 0.7 * self.kick[i])
        return np.clip(img, 0, 255)

    def frame(self, i):
        self.advance(i)
        out = np.zeros((H, W, 3), np.float32); p = self.picture(i); y0 = 200
        out[y0:y0 + p.shape[0]] = p[:H - y0]
        im = Image.fromarray(out.astype(np.uint8)); d = ImageDraw.Draw(im)
        # everything written stays inside Instagram's safe area (y 250-1500, left of the right-hand 150 px)
        d.multiline_text((W / 2, 340), self.says, font=self.f_line, fill=(255, 255, 255), anchor='mm', align='center', spacing=14, stroke_width=5, stroke_fill=(0, 0, 0))
        d.text((40, 1400), 'physarum · %s agents%s · step %05d' % (format(self.x.size, ','), ' · 3 colonies' if self.species > 1 else '', self.age), font=self.f_ui, fill=(225, 225, 232), anchor='lm', stroke_width=3, stroke_fill=(0, 0, 0))
        d.text((40, 1432), 'each one smells left, ahead, right · turns · steps · leaves a trail', font=self.f_small, fill=(170, 174, 186), anchor='lm', stroke_width=3, stroke_fill=(0, 0, 0))
        d.text((40, 1476), self.credit, font=self.f_credit, fill=(225, 225, 232), anchor='lm', stroke_width=3, stroke_fill=(0, 0, 0))
        return np.asarray(im)

    def warm_up(self):
        for _ in range(int(os.environ.get('CQ_WARMUP', '10'))): self.advance(0)       # a few steps so the seed is a shape, not a dot; the network forms on camera

    def render(self, out):
        self.warm_up()
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; ims = []
            for f in range(max(fs) + 1):
                if f in fs: ims.append(Image.fromarray(self.frame(f)).resize((360, 640)))
                else: self.advance(f)
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n): p.stdin.write(self.frame(i).tobytes())
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'alife')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
