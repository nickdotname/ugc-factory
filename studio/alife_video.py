#!/usr/bin/env python3
"""Digital creatures: a slime mould of a couple of hundred thousand simple agents finding its shape to one song.

    python studio/alife_video.py SONG_DIR SEED OUT.mp4 [--frames a,b,c]     (CQ_WINDOW="t0,t1")

Each agent only smells the trail in front of it (left, ahead, right), turns toward the strongest, steps forward and
leaves a little trail of its own; the trail spreads and fades. From that the colony draws veins, loops and networks,
the way Physarum polycephalum does. The music is the weather: the kick makes them run, the snare scatters a burst of
new agents from a point, the bass widens how far they look.
Knobs: start (ring, seeds, rain), palette, sense (how far ahead they smell), steps (simulation steps per frame).
"""
import json, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish

W, H, FPS = 1080, 1920, 30
GW, GH = 540, 820                                 # the simulation grid (half the picture's size)
MONO = next(p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', os.path.join(REPO, 'fonts', 'DejaVuSansMono.ttf')) if os.path.exists(p))
PALETTES = {'gold': [(0, 0, 0), (90, 30, 0), (255, 170, 40), (255, 250, 220)],
            'bio': [(0, 0, 0), (0, 40, 60), (0, 220, 180), (230, 255, 250)],
            'violet': [(0, 0, 0), (40, 0, 70), (220, 60, 255), (255, 230, 255)],
            'ember': [(0, 0, 0), (70, 0, 10), (255, 60, 40), (255, 230, 160)]}


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.rng = np.random.default_rng(seed)
        self.start = K.pick('start', ['ring', 'seeds', 'rain'], r)
        self.pal = K.pick('palette', sorted(PALETTES), r)
        self.sense = float(K.pick('sense', [6, 9, 14], r))
        self.steps = int(K.pick('steps', [1, 2], r, weights=[1, 2]))
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 5.0); self.snare = audio.hits(a['snares'], n, 9.0)
        self.snares = set(int(round(f)) for f in a['snares']); self.bass = np.convolve(a['bass'], np.ones(5) / 5, 'same')
        N = 140000; g = self.rng
        if self.start == 'ring':
            ang = g.uniform(0, 2 * np.pi, N); rad = g.uniform(0, 1, N) ** 0.5 * 60 + 320
            self.x = GW / 2 + rad * np.cos(ang) * 0.75; self.y = GH / 2 + rad * np.sin(ang); self.h = ang + np.pi
        elif self.start == 'seeds':
            c = g.uniform([80, 120], [GW - 80, GH - 120], (7, 2)); k = g.integers(0, 7, N)
            ang = g.uniform(0, 2 * np.pi, N); rad = g.uniform(0, 25, N)
            self.x = c[k, 0] + rad * np.cos(ang); self.y = c[k, 1] + rad * np.sin(ang); self.h = ang
        else:
            self.x = g.uniform(0, GW, N); self.y = g.uniform(0, GH, N); self.h = g.uniform(0, 2 * np.pi, N)
        self.T = np.zeros((GH, GW), np.float32); self.age = 0
        cols = np.array(PALETTES[self.pal], np.float32); xs = np.linspace(0, 1, len(cols))
        self.lut = np.stack([np.interp(np.linspace(0, 1, 256), xs, cols[:, c]) for c in range(3)], -1).astype(np.float32)
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — close quarters' % song.get('title', self.slug).lower()
        self.f_ui = ImageFont.truetype(MONO, 26); self.f_small = ImageFont.truetype(MONO, 22)

    def step(self, i):
        x, y, h, T = self.x, self.y, self.h, self.T
        sa = 0.39 + 0.15 * self.bass[i]; sd = self.sense * (1 + 0.6 * self.bass[i])
        def smell(off):
            sx = (x + sd * np.cos(h + off)).astype(np.int32) % GW; sy = (y + sd * np.sin(h + off)).astype(np.int32) % GH
            return T[sy, sx]
        l, c, rr = smell(sa), smell(0), smell(-sa)
        turn = 0.785
        jitter = self.rng.uniform(-0.05, 0.05, x.size)
        h += np.where((c >= l) & (c >= rr), 0, np.where(l > rr, turn, -turn)) + jitter
        speed = 1.0 + 2.2 * self.kick[i]
        x += speed * np.cos(h); y += speed * np.sin(h); x %= GW; y %= GH
        np.add.at(T, (y.astype(np.int32), x.astype(np.int32)), 0.25 * (1 + self.kick[i]))
        self.T = np.minimum(cv2.blur(T, (3, 3)) * 0.9, 2.5)   # a ceiling on the trail keeps the colony from collapsing into a few thick veins
        self.x, self.y, self.h = x, y, h

    def burst(self, i):
        """A snare: a few thousand of them are flung out of one point."""
        k = self.rng.choice(self.x.size, 6000, replace=False); px, py = self.rng.uniform([60, 80], [GW - 60, GH - 80])
        self.x[k] = px; self.y[k] = py; self.h[k] = self.rng.uniform(0, 2 * np.pi, k.size)

    def advance(self, i):
        if i in self.snares and self.snare[i] > 0.5: self.burst(i)
        for _ in range(self.steps): self.step(i)
        self.age += self.steps

    def picture(self, i):
        ref = max(float(np.percentile(self.T, 99.7)), 1e-3)            # exposure follows the colony, so it never burns to white
        v = np.clip(self.T / ref, 0, 1) ** 0.8
        img = self.lut[(v * 255).astype(np.uint8)]
        img = cv2.resize(img, (W, int(W * GH / GW)), interpolation=cv2.INTER_CUBIC)
        small = cv2.resize(img, (img.shape[1] // 4, img.shape[0] // 4), interpolation=cv2.INTER_AREA)
        img = img + cv2.resize(cv2.GaussianBlur(small, (0, 0), 5), img.shape[1::-1]) * (0.6 + 0.8 * self.kick[i])
        return np.clip(img, 0, 255)

    def frame(self, i):
        self.advance(i)
        out = np.zeros((H, W, 3), np.float32); p = self.picture(i); y0 = 200
        out[y0:y0 + p.shape[0]] = p[:H - y0]
        im = Image.fromarray(out.astype(np.uint8)); d = ImageDraw.Draw(im)
        d.text((40, 95), 'physarum · %s agents' % format(self.x.size, ','), font=self.f_ui, fill=(225, 225, 232))
        d.text((W - 40, 95), 'step %05d' % self.age, font=self.f_ui, fill=(140, 144, 156), anchor='ra')
        d.text((40, 140), 'each one smells left, ahead, right · turns · steps · leaves a trail', font=self.f_small, fill=(120, 124, 136))
        d.text((40, H - 95), self.credit, font=self.f_ui, fill=(225, 225, 232))
        return np.asarray(im)

    def render(self, out):
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
                              '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for _ in range(int(os.environ.get('CQ_WARMUP', '90'))): self.advance(0)       # let the network form before the song starts
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
