#!/usr/bin/env python3
"""vintage.media.archive: public-domain films and cartoons from before 1931, cut on the beat and shown as old film.

    python studio/vintage_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)

The nightly job's renderer for the "vintage" style (studio/nightly.py). Clips come from the footage library
(studio/footage.py, theme "silent": films made before 1931, which are in the US public domain) and are cut on bar
lines, the same way glitch.archive cuts its footage. What changes is the look: the picture is made to read as a
projected print, not as a video file.
  tint    the colour the print was dyed: sepia, amber, night blue, rose, green, or plain black and white
  crank   the frame rate it was shot at: every frame (smooth) or every other frame held (the 1920s stutter)
  gate    the projector's gate: a rounded frame, an iris that opens at every cut, or the full frame
  cards   the lyrics as intertitle cards: full-screen cards on a line or two, a title box low on every line, or none
  trip    now and then the print misbehaves: it melts on the bass, burns through, or two reels play at once
Every one is a knob (studio/knobs.py), so the learner finds out which looks people watch. Grain, flicker, gate
weave, dust and scratches are always there; the kick nudges the flicker and the weave.
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage
from glitch_video import Clips, W, H, FPS

# dark and light ends of each dye, RGB
TINTS = {'sepia': ((26, 17, 10), (236, 221, 190)), 'amber': ((30, 16, 4), (255, 214, 140)), 'night': ((6, 12, 30), (150, 190, 235)),
         'rose': ((28, 8, 14), (240, 190, 200)), 'green': ((8, 22, 12), (190, 230, 190)), 'bw': ((10, 10, 10), (238, 236, 230))}
TRIPS = ['none', 'melt', 'burn', 'double']


def serif(size):
    for p in (os.path.join(REPO, 'fonts', 'Fraunces.ttf'), '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def lyric_lines(song_dir, t0, t1):
    """(start, end, text) of each sung line that starts inside the window, in seconds from the window's start."""
    if os.environ.get('CQ_LYRICS') == 'none': return []          # nightly: this stretch's words do not measure as in sync
    import sync_check
    rows = sync_check.load_lines(song_dir)
    out = []
    for end, words in rows:
        if not words: continue
        s = words[0][1]
        if t0 <= s < t1 - 0.4: out.append((s - t0, min(end, t1) - t0, ' '.join(w for w, _ in words)))
    return out


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.tint = K.pick('tint', list(TINTS), r, weights=[3, 2, 2, 1, 1, 3])
        self.hold = int(K.pick('crank', [1, 2], r))
        self.gate = K.pick('gate', ['rounded', 'iris', 'full'], r)
        self.cards = K.pick('cards', ['full', 'lower', 'none'], r)
        self.trip = K.pick('trip', TRIPS, r, weights=[5, 2, 2, 2])
        self.pace = float(K.pick('pace', [1, 2], r))
        lib = footage.pull(('silent',))
        self.source = 'silent'
        if len(lib) < 3: lib = footage.pull(('archive',)); self.source = 'archive'     # until the silent films are fetched
        K.MENU['source'] = ['silent', 'archive']; K.CHOSEN['source'] = self.source
        if not lib: sys.exit('the footage library is empty: run the footage workflow first')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 6.0); self.snare = audio.hits(a['snares'], n, 8.0)
        self.bass = np.convolve(a['bass'], np.ones(7) / 7, 'same')
        self.clips = Clips(lib, n, self.spb, self.pace, r)
        self.ghost = Clips(lib, n, self.spb, self.pace * 2, random.Random(seed + 7)) if self.trip == 'double' else None
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        lines = lyric_lines(song_dir, t0, t1)
        self.lines = [(int(s * FPS), int(e * FPS), txt) for s, e, txt in lines]
        if self.cards == 'full':                        # two cards at most, on lines a few seconds apart, never the first frames
            picked, last = [], -10 ** 9
            for s, e, txt in self.lines:
                if s >= FPS and s - last > 4 * FPS and len(picked) < 2: picked.append((s, min(e, s + int(2.2 * FPS)), txt)); last = s
            self.full = picked
        else: self.full = []
        self.f_card, self.f_low = serif(78), serif(52)
        sans = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/Library/Fonts/Arial Unicode.ttf') if os.path.exists(p)), None)
        self.f_credit = ImageFont.truetype(sans, 28) if sans else serif(30)       # the serif has no note sign
        lo, hi = TINTS[self.tint]; self.lo = np.array(lo[::-1], np.float32); self.hi = np.array(hi[::-1], np.float32)   # BGR
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
        self.vig = np.clip(1.15 - d ** 2 * 0.75, 0.25, 1).astype(np.float32)
        self.rr = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (W / 2)) ** 2).astype(np.float32)   # for the iris
        m = Image.new('L', (W, H), 0); ImageDraw.Draw(m).rounded_rectangle([38, 60, W - 38, H - 60], radius=110, fill=255)
        g = cv2.GaussianBlur(np.asarray(m, np.float32) / 255, (0, 0), 9)
        self.round = g
        gr = np.random.default_rng(seed)
        self.grain = [cv2.resize(gr.normal(0, 1, (H // 3, W // 3)).astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR) for _ in range(6)]
        self.scratches = []; self.weave = np.zeros(2, np.float32)
        self.burn_at = None
        if self.trip == 'burn':                         # one burn, on a bar line in the back half
            bars = [int(fr) for b, fr in a['beats'] if b % 4 == 0 and n * 0.45 < fr < n - FPS * 1.2]
            self.burn_at = r.choice(bars) if bars else int(n * 0.7)
            self.burn_noise = cv2.GaussianBlur(gr.random((H // 8, W // 8)).astype(np.float32), (0, 0), 3)
            self.burn_noise = cv2.resize((self.burn_noise - self.burn_noise.min()) / (np.ptp(self.burn_noise) + 1e-6), (W, H))
            cy, cx = gr.integers(H // 4, 3 * H // 4), gr.integers(W // 4, 3 * W // 4)
            self.burn_noise = self.burn_noise * 0.55 + np.sqrt(((xx - cx) / W) ** 2 + ((yy - cy) / W) ** 2) * 0.9
        self.melt_x = np.arange(W, dtype=np.float32)[None, :].repeat(H, 0); self.melt_y = np.arange(H, dtype=np.float32)[:, None].repeat(W, 1)

    # ---------------------------------------------------------------- the print
    def gray(self, f):
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        lo, hi = np.percentile(g[::8, ::8], 2), np.percentile(g[::8, ::8], 98)
        g = np.clip((g - lo) / max(0.15, hi - lo), 0, 1)                            # old prints are contrasty
        return g * g * (3 - 2 * g) * 0.85 + g * 0.15                                  # an S curve

    def frame(self, i):
        src = i - (i % self.hold)
        f, k, e = self.clips.frame(src)
        cut = getattr(self, '_k', None) not in (None, k); self._k = k
        if cut: self.cut_at = i
        g = self.gray(f)
        if self.ghost is not None:
            gf, *_ = self.ghost.frame(src); g = np.clip(g * 0.62 + self.gray(gf) * 0.48, 0, 1)
        rng = np.random.default_rng(i * 7919 + 13)
        if self.trip == 'melt':
            amp = 4 + 46 * float(self.bass[i]) ** 2 + 30 * self.kick[i]
            t = i / FPS
            dy = np.sin(self.melt_x / 140.0 + t * 2.1) * amp + np.sin(self.melt_y / 310.0 + t) * amp * 0.4
            dx = np.sin(self.melt_y / 180.0 + t * 1.3) * amp * 0.35
            g = cv2.remap(g, (self.melt_x + dx).astype(np.float32), (self.melt_y - np.abs(dy)).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        self.weave = self.weave * 0.7 + rng.normal(0, [1.2, 2.0]).astype(np.float32) * 0.6
        jump = 10 * self.kick[i] if self.kick[i] > 0.7 else 0
        M = np.float32([[1, 0, self.weave[0]], [0, 1, self.weave[1] + jump]])
        g = cv2.warpAffine(g, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        g = g * (1 + 0.045 * rng.normal() + 0.09 * self.kick[i])                       # flicker
        g = g + self.grain[i % len(self.grain)] * 0.055
        g = g * self.vig
        for _ in range(rng.poisson(5)):                                               # dust
            x, y, s = int(rng.integers(0, W)), int(rng.integers(0, H)), int(rng.integers(2, 7))
            cv2.circle(g, (x, y), s, float(rng.choice([0.0, 1.0])), -1)
        if rng.random() < 0.12: self.scratches.append([int(rng.integers(60, W - 60)), int(rng.integers(3, 14)), float(rng.choice([0.1, 0.9]))])
        for sc in self.scratches:
            cv2.line(g, (sc[0], 0), (sc[0] + int(rng.integers(-3, 4)), H), sc[2], 2); sc[0] += int(rng.integers(-2, 3)); sc[1] -= 1
        self.scratches = [sc for sc in self.scratches if sc[1] > 0]
        g = np.clip(g, 0, 1)
        img = self.lo + (self.hi - self.lo) * g[..., None]                            # the dye
        if self.burn_at is not None and self.burn_at <= i < self.burn_at + int(1.1 * FPS):
            p = (i - self.burn_at) / (1.1 * FPS); edge = self.burn_noise - p * 1.6
            hole = edge < 0; rim = (edge >= 0) & (edge < 0.07)
            img[rim] = img[rim] * 0.2 + np.array([40, 140, 255], np.float32) * 0.8      # orange, BGR
            img[hole] = np.array([235, 245, 255], np.float32)
        if self.gate == 'rounded': img *= self.round[..., None]
        elif self.gate == 'iris':
            since = i - getattr(self, 'cut_at', 0); rad = 0.2 + 2.0 * min(1.0, since / (0.5 * FPS))
            img *= np.clip((rad - self.rr) / 0.08, 0, 1)[..., None]
        out = Image.fromarray(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(out)
        card = next((txt for s, e, txt in self.full if s <= i < e), None)
        if card: self.draw_card(out, d, card)
        elif self.cards == 'lower':
            txt = next((txt for s, e, txt in self.lines if s <= i < e), None)
            if txt: self.draw_lower(d, txt)
        d.text((W / 2, H - 110), self.credit, font=self.f_credit, fill=tuple(int(c) for c in TINTS[self.tint][1]), anchor='mm',
               stroke_width=2, stroke_fill=(0, 0, 0))
        return np.asarray(out)

    # ---------------------------------------------------------------- intertitles
    def wrap(self, txt, font, width):
        words, rows, cur = txt.split(), [], ''
        for w in words:
            t = (cur + ' ' + w).strip()
            if font.getlength(t) <= width or not cur: cur = t
            else: rows.append(cur); cur = w
        return rows + ([cur] if cur else [])

    def draw_card(self, out, d, txt):
        ink = tuple(int(c) for c in TINTS[self.tint][1])
        d.rectangle([0, 0, W, H], fill=(10, 9, 8))
        for m, wdt in ((120, 4), (140, 2)):                                           # a double rule, as the title cards had
            d.rectangle([m, H // 2 - 430 - (m - 120), W - m, H // 2 + 430 + (m - 120)], outline=ink, width=wdt)
        for cx, cy in ((120, H // 2 - 430), (W - 120, H // 2 - 430), (120, H // 2 + 430), (W - 120, H // 2 + 430)):
            d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=ink, width=3)
        rows = self.wrap(txt.strip(' ,'), self.f_card, W - 340)
        y = H / 2 - (len(rows) - 1) * 52
        for row in rows: d.text((W / 2, y), row, font=self.f_card, fill=ink, anchor='mm'); y += 104

    def draw_lower(self, d, txt):
        ink = tuple(int(c) for c in TINTS[self.tint][1])
        rows = self.wrap(txt.strip(' ,'), self.f_low, W - 260)[:3]
        h = 70 * len(rows) + 50; y0 = H - 330 - h
        d.rectangle([90, y0, W - 90, y0 + h], fill=(8, 8, 8), outline=ink, width=3)
        y = y0 + 25 + 35
        for row in rows: d.text((W / 2, y), row, font=self.f_low, fill=ink, anchor='mm'); y += 70

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
