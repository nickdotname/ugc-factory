#!/usr/bin/env python3
"""glitch.archive: public-domain footage of creeks, forests, cities, space and old film, broken on the beat.

    python studio/glitch_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)

The nightly job's renderer for the "glitch" style (studio/nightly.py). Clips come from the footage library
(studio/footage.py) and are cut on bar lines. Over them runs one main treatment and one accent, picked per video:
  mosh    datamosh: at a cut the old picture is not replaced but dragged along the new clip's motion, and on the
          kicks the picture freezes and smears the same way (what a video file does when its key frames are lost)
  track   blob tracking: whatever moves gets a box, a crosshair, an ID and coordinates, joined by lines
  sort    pixel sorting: runs of pixels in a brightness band are sorted, in bands that flare on the snare
  slit    slit-scan: each row of the picture shows a different moment, the delay set by the bass
  points  a point cloud: brightness taken as depth, the picture turned in 3D and drawn as dots
accents: rgb (the colour channels drift apart in time), blocks (macroblock smears on the snare), none;
tones: natural, thermal, mono, duotone, xray, night. All of them are knobs (studio/knobs.py), so the learner
finds out which looks people watch; with ~5 x 3 x 6 combinations and the footage changing, no two look alike.
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage

W, H, FPS = 1080, 1920, 30
THEMES = ['water', 'nature', 'city', 'space', 'archive', 'mixed']
MAINS = ['mosh', 'track', 'sort', 'slit', 'points']
ACCENTS = ['rgb', 'blocks', 'none']
TONES = ['natural', 'thermal', 'mono', 'duotone', 'xray', 'night']


def font(size):
    for p in (os.path.join(REPO, 'fonts', 'DejaVuSansMono-Bold.ttf'), '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class Clips:
    """The footage, cut on bar lines: which clip plays when, and its frames, cropped to the vertical frame."""
    def __init__(self, entries, n, spb, bars_per_cut, rng):
        self.rng = rng; self.cache = {}
        step = max(1, int(round(bars_per_cut * 4 * spb * FPS)))
        self.cuts = list(range(0, n, step))
        pool = entries[:]; rng.shuffle(pool)
        self.plan = []
        for k, c in enumerate(self.cuts):
            e = pool[k % len(pool)]; cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset']))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 300; cap.release()
            seg = (self.cuts[k + 1] if k + 1 < len(self.cuts) else n) - c
            self.plan.append((c, e, rng.randrange(0, max(1, total - seg)), rng.uniform(1.0, 1.12), rng.uniform(-0.15, 0.15)))

    def segment(self, i):
        k = max(j for j, (c, *_r) in enumerate(self.plan) if c <= i); return k, self.plan[k]

    def frame(self, i):
        k, (c, e, off, zoom, pan) = self.segment(i)
        if k not in self.cache:                                   # read a segment's frames once
            for old in [j for j in self.cache if j < k - 1]: del self.cache[old]
            cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset'])); cap.set(cv2.CAP_PROP_POS_FRAMES, off); fr = []
            seg = (self.plan[k + 1][0] if k + 1 < len(self.plan) else c + 10 ** 6) - c
            while len(fr) < min(seg, 400):
                ok, f = cap.read()
                if not ok:
                    if not fr: break
                    fr += fr[::-1]; continue                       # a short clip plays forward then back
                fr.append(f)
            cap.release(); self.cache[k] = fr or [np.zeros((H, W, 3), np.uint8)]
        fr = self.cache[k]; f = fr[min(i - c, len(fr) - 1)]
        h, w = f.shape[:2]; s = max(W / w, H / h) * zoom * (1 + 0.04 * (i - c) / max(1, len(fr)))   # slow push-in
        f = cv2.resize(f, (int(w * s) + 1, int(h * s) + 1), interpolation=cv2.INTER_LINEAR)
        x0 = int((f.shape[1] - W) * (0.5 + pan)); y0 = (f.shape[0] - H) // 2
        return np.ascontiguousarray(f[y0:y0 + H, max(0, min(x0, f.shape[1] - W)):][:, :W]), k, e


def flow(a, b):
    sa, sb = cv2.resize(a, (W // 4, H // 4)), cv2.resize(b, (W // 4, H // 4))
    ga, gb = cv2.cvtColor(sa, cv2.COLOR_BGR2GRAY), cv2.cvtColor(sb, cv2.COLOR_BGR2GRAY)
    f = cv2.calcOpticalFlowFarneback(ga, gb, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    return cv2.resize(f, (W, H)) * 4


GX, GY = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.theme = K.pick('source', THEMES, r); self.main = K.pick('main', MAINS, r)
        self.accent = K.pick('accent', ACCENTS, r); self.tone = K.pick('tone', TONES, r)
        self.pace = float(K.pick('pace', [1, 2], r)); self.label = K.pick('label', ['rec', 'none'], r)
        lib = footage.pull(() if self.theme == 'mixed' else (self.theme,))
        if len(lib) < 3: lib = footage.pull(())
        if not lib: sys.exit('the footage library is empty: run the footage workflow first')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 6.0); self.snare = audio.hits(a['snares'], n, 8.0)
        self.bass = np.convolve(a['bass'], np.ones(5) / 5, 'same'); self.vox = np.convolve(a['vocals'], np.ones(5) / 5, 'same')
        self.kicks = set(int(k) for k in a['kicks'])
        self.clips = Clips(lib, n, self.spb, self.pace, r)
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.f_small, self.f_lab = font(26), font(22)
        self.prev = None; self.acc = None; self.mosh_left = 0; self.buf = []; self.tracks = {}; self.next_id = 1

    # ---------------------------------------------------------------- treatments
    def mosh(self, f, i, k_changed):
        if self.acc is None: self.acc = f.astype(np.float32)
        if k_changed and self.prev is not None: self.mosh_left = int(FPS * self.r.uniform(0.6, 1.4))          # a cut: bleed instead of switching
        if i in self.kicks and self.r.random() < 0.35 and self.mosh_left <= 0: self.mosh_left = int(FPS * 0.5)
        if self.mosh_left > 0 and self.prev is not None:
            fl = flow(self.prev, f) * (1.4 + 1.2 * self.bass[i])
            self.acc = cv2.remap(self.acc, GX - fl[..., 0], GY - fl[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            self.mosh_left -= 1
            if self.mosh_left == 0: self.settle = 6
            return self.acc
        a = 1.0 if not getattr(self, 'settle', 0) else 1.0 / self.settle
        self.settle = max(0, getattr(self, 'settle', 0) - 1)
        self.acc = self.acc * (1 - a) + f.astype(np.float32) * a
        return self.acc

    def track(self, f, i):
        out = f.astype(np.float32)
        if self.prev is None: return out
        small = cv2.cvtColor(cv2.resize(f, (W // 6, H // 6)), cv2.COLOR_BGR2GRAY); ps = cv2.cvtColor(cv2.resize(self.prev, (W // 6, H // 6)), cv2.COLOR_BGR2GRAY)
        m = cv2.GaussianBlur(cv2.absdiff(small, ps), (0, 0), 2); m = (m > max(6, np.percentile(m, 92))).astype(np.uint8)
        m = cv2.dilate(m, np.ones((5, 5), np.uint8))
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = sorted([cv2.boundingRect(c) for c in cs], key=lambda b: -b[2] * b[3])[:int(6 + 6 * self.snare[i])]
        # keep IDs steady: a box takes the ID of the nearest box from the last frame
        new = {}
        for (x, y, w, h) in boxes:
            cx, cy = (x + w / 2) * 6, (y + h / 2) * 6
            best = min(self.tracks.items(), key=lambda kv: (kv[1][0] - cx) ** 2 + (kv[1][1] - cy) ** 2, default=None)
            if best and (best[1][0] - cx) ** 2 + (best[1][1] - cy) ** 2 < 140 ** 2 and best[0] not in new: tid = best[0]
            else: tid = self.next_id; self.next_id += 1
            new[tid] = (cx, cy, x * 6, y * 6, w * 6, h * 6)
        self.tracks = new
        img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(img)
        pts = [(v[0], v[1]) for v in new.values()]
        for a_, b_ in zip(pts, pts[1:]): d.line([a_, b_], fill=(255, 255, 255), width=2)
        flash = self.snare[i] > 0.5
        for tid, (cx, cy, x, y, w, h) in new.items():
            col = (255, 60, 60) if flash and tid % 2 else (255, 255, 255)
            d.rectangle([x, y, x + w, y + h], outline=col, width=3)
            for sx, sy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)): d.rectangle([sx - 5, sy - 5, sx + 5, sy + 5], fill=col)
            d.line([cx - 14, cy, cx + 14, cy], fill=col, width=2); d.line([cx, cy - 14, cx, cy + 14], fill=col, width=2)
            d.text((x + 4, y - 26), 'ID %02d  %.2f %.2f' % (tid % 100, cx / W, cy / H), font=self.f_lab, fill=col)
        return np.asarray(img).astype(np.float32)

    def sort(self, f, i):
        amt = 0.25 + 0.6 * self.snare[i] + 0.3 * self.bass[i]
        s = cv2.resize(f, (W // 2, H // 2)); lum = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY).astype(np.float32)
        lo, hi = np.percentile(lum, 50 - 40 * min(amt, 1)), np.percentile(lum, 99)
        mask = (lum > lo) & (lum < hi)
        # runs of masked pixels down each column are sorted by brightness, brightest falling to the bottom
        run = np.cumsum(~mask, axis=0)                                   # a new run starts after every unmasked pixel
        key = run * 512.0 + np.where(mask, lum, -1.0)
        order = np.argsort(key, axis=0, kind='stable')
        out = np.take_along_axis(s, order[..., None], axis=0)
        band = (np.arange(W // 2) // 40) % 3 != 1 if self.snare[i] < 0.5 else np.ones(W // 2, bool)   # in bands, all over on the snare
        res = np.where(band[None, :, None], out, s)
        return cv2.resize(res, (W, H), interpolation=cv2.INTER_NEAREST).astype(np.float32)

    def slit(self, f, i):
        self.buf.append(f); depth = 48
        if len(self.buf) > depth: self.buf.pop(0)
        n = len(self.buf); d = 0.4 + 0.6 * self.bass[i]
        rows = np.arange(H); idx = np.clip((n - 1) - ((rows / H) * (n - 1) * d).astype(int), 0, n - 1)
        if self.kick[i] > 0.6: idx = np.clip(idx - ((np.sin(rows / 37.0 + i) > 0) * 6), 0, n - 1)
        stack = np.stack(self.buf)                                       # n, H, W, 3
        return stack[idx, rows].astype(np.float32)

    def points(self, f, i):
        s = cv2.resize(f, (W // 6, H // 6)); lum = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        z = cv2.GaussianBlur(lum, (0, 0), 1.5) * (1.6 + 1.2 * self.bass[i])
        yy, xx = np.mgrid[0:s.shape[0], 0:s.shape[1]].astype(np.float32)
        X = (xx - s.shape[1] / 2) * 6; Y = (yy - s.shape[0] / 2) * 6; Z = (z - 0.5) * 520
        t = i / FPS; ay = 0.35 * math.sin(t * 0.5) + 0.12 * self.kick[i]; ax = 0.25 + 0.1 * math.sin(t * 0.3)
        X2 = X * math.cos(ay) + Z * math.sin(ay); Z2 = -X * math.sin(ay) + Z * math.cos(ay)
        Y2 = Y * math.cos(ax) - Z2 * math.sin(ax); Z3 = Y * math.sin(ax) + Z2 * math.cos(ax)
        p = 1400 / (1400 + Z3); u = (W / 2 + X2 * p).astype(int); v = (H / 2 + Y2 * p).astype(int)
        ok = (u >= 0) & (u < W - 2) & (v >= 0) & (v < H - 2) & (lum > 0.08)
        out = np.zeros((H, W, 3), np.float32); col = s.astype(np.float32)[ok] * 1.3
        for dy in (0, 1):
            for dx in (0, 1): out[v[ok] + dy, u[ok] + dx] = col
        return out + cv2.GaussianBlur(out, (0, 0), 6) * 0.6

    # ---------------------------------------------------------------- accents and tones
    def accent_fx(self, img, i):
        if self.accent == 'rgb':
            sh = int(6 + 22 * self.kick[i] + 10 * self.bass[i])
            img = img.copy(); img[..., 2] = np.roll(img[..., 2], sh, axis=1); img[..., 0] = np.roll(img[..., 0], -sh, axis=1)
        elif self.accent == 'blocks' and self.snare[i] > 0.35:
            r = np.random.default_rng(i); img = img.copy()
            for _ in range(int(30 * self.snare[i])):
                bw, bh = r.choice([32, 64, 128]), r.choice([16, 32, 64]); x, y = r.integers(0, W - bw), r.integers(0, H - bh)
                sx, sy = int(np.clip(x + r.integers(-120, 120), 0, W - bw)), int(np.clip(y + r.integers(-40, 40), 0, H - bh))
                img[y:y + bh, x:x + bw] = img[sy:sy + bh, sx:sx + bw] if r.random() < 0.6 else img[y:y + 1, x:x + bw]   # moved, or smeared down
        return img

    def tone_fx(self, img):
        u8 = np.clip(img, 0, 255).astype(np.uint8)
        if self.tone == 'natural': return img
        g = cv2.cvtColor(u8, cv2.COLOR_BGR2GRAY)
        if self.tone == 'thermal': return cv2.applyColorMap(g, cv2.COLORMAP_INFERNO).astype(np.float32)
        if self.tone == 'mono': return cv2.cvtColor(cv2.equalizeHist(g), cv2.COLOR_GRAY2BGR).astype(np.float32)
        if self.tone == 'xray': return cv2.cvtColor(255 - g, cv2.COLOR_GRAY2BGR).astype(np.float32) * np.array([1.0, 0.95, 0.85])
        if self.tone == 'night': return (np.stack([g * 0.25, g * 1.0, g * 0.35], -1) * 1.1).astype(np.float32)
        lo, hi = np.array([60, 20, 30], np.float32), np.array([120, 230, 255], np.float32)     # duotone: deep blue to warm white (BGR)
        x = (g.astype(np.float32) / 255)[..., None]; return lo * (1 - x) + hi * x

    def frame(self, i):
        f, k, e = self.clips.frame(i)
        changed = getattr(self, '_k', None) not in (None, k); self._k = k
        img = getattr(self, self.main)(f, i, changed) if self.main == 'mosh' else getattr(self, self.main)(f, i)
        self.prev = f
        img = self.tone_fx(self.accent_fx(img, i))
        img *= 1 + 0.12 * self.kick[i]                                    # a little lift on the kick
        g = np.random.default_rng(i).normal(0, 6, (H // 4, W // 4)).astype(np.float32)
        img += cv2.resize(g, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]   # grain
        out = Image.fromarray(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(out)
        if self.label == 'rec':
            t = self.t0 + i / FPS
            if (i // 15) % 2 == 0: d.ellipse([40, 52, 62, 74], fill=(230, 40, 40))
            d.text((74, 48), 'REC  %02d:%02d:%02d' % (t // 60, t % 60, (i % FPS)), font=self.f_small, fill=(240, 240, 240))
            d.text((40, 88), 'SRC %s / %s' % (e['source'], e['query'].replace(' ', '_')), font=self.f_lab, fill=(200, 200, 200))
        d.text((W / 2, H - 60), self.credit, font=self.f_small, fill=(235, 235, 235), anchor='mm')
        return np.asarray(out)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            want = set(fs); ims = []
            for i in range(max(fs) + 1):
                fr = self.frame(i)
                if i in want: ims.append(Image.fromarray(fr).resize((360, 640)))
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
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
        used = sorted({e['key'] for _, e, *_r in self.clips.plan})
        json.dump(dict(K.record(), footage=used), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
