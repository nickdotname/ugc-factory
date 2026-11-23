#!/usr/bin/env python3
"""Animated cut-out videos for close__quarters: the band, cut out of their own dance footage, thrown around on the beat.

    python studio/cutout_video.py SONG_DIR SEED OUT.mp4            (CQ_WINDOW="t0,t1": the stretch to play)
    python studio/cutout_video.py SONG_DIR SEED SHEET.png --frames 0,60,120

The same footage as lofi_video.py (studio/lofi/index.json: the band filmed dancing, cut out ten times a second),
but full screen and moving a lot: a sticker outline round each cut-out, the camera punching in on the kick and
leaning on the snare, the background flipping colour on the beat, and each bar staged one of four ways:
  big    one of them huge, bouncing
  echo   one of them with a trail of delayed, tinted copies behind (the frames from a moment earlier)
  grid   a wall of copies in different tints, popping in beat by beat
  duo    two of them side by side, trading places on the beat
The words come up one at a time, big, as they are sung. Now and then the picture turns (trip): it melts on the bass,
tears into glitch slices on the snare, or its colours split.
Knobs (studio/knobs.py): stage (which of the four it leans on), palette, trip, outline, words.
Band footage: this style is only ever for @close__quarters (CLAUDE.md).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import knobs as K
import lofi_video as LV                     # the footage, its timing, the lyrics and fonts (it reads the same argv)
import lofi_lib as LIB

W, H, FPS = LV.W, LV.H, LV.FPS
PALETTES = {'acid': [(226, 255, 0), (255, 40, 160), (20, 20, 20), (0, 220, 255)], 'edu': [(74, 12, 208), (226, 40, 150), (20, 150, 230), (255, 110, 40)],
            'candy': [(255, 150, 200), (130, 220, 255), (255, 230, 120), (180, 140, 255)], 'mono': [(15, 15, 15), (240, 240, 235), (230, 30, 40), (240, 240, 235)]}
TINTS = [((40, 0, 95), (200, 40, 210), (255, 185, 250)), ((0, 30, 80), (0, 170, 200), (200, 255, 250)), ((60, 10, 0), (240, 90, 20), (255, 230, 160)),
         ((0, 50, 20), (40, 200, 90), (220, 255, 200))]
ANTON = os.path.join(REPO, 'fonts', 'Anton-Regular.ttf')
GX, GY = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))


def sticker(im, width):
    """The cut-out with a white outline and a soft shadow, as RGBA."""
    a = im.getchannel('A')
    grown = a.filter(ImageFilter.MaxFilter(width * 2 + 1)) if width else a
    out = Image.new('RGBA', im.size, (0, 0, 0, 0))
    sh = Image.new('RGBA', im.size, (0, 0, 0, 0)); sh.putalpha(grown.point(lambda v: int(v * 0.35)).filter(ImageFilter.GaussianBlur(10)))
    out.alpha_composite(sh, (8, 12))
    if width:
        white = Image.new('RGBA', im.size, (255, 255, 255, 0)); white.putalpha(grown); out.alpha_composite(white)
    out.alpha_composite(im)
    return out


class Video:
    def __init__(self, seed):
        for c in LIB.clips_for(LV.SLUG): LV.CLIPS.setdefault(c['who'], []).append((c['id'], c['offset'], c['frames'], c['fps']))
        if not LV.CLIPS: sys.exit('no footage for %s in studio/lofi/index.json' % LV.SLUG)
        w = os.environ.get('CQ_WINDOW'); first = LV.CLIPS[sorted(LV.CLIPS)[0]][0][1]
        T0, T1 = (float(x) for x in w.split(',')) if w else (first + 1, first + 16)
        self.T0, self.T1 = LV.fit_window(T0, T1, seed)
        r = random.Random(seed); self.r = r
        self.stage = K.pick('stage', ['mix', 'big', 'echo', 'grid', 'duo'], r, weights=[3, 1, 1, 1, 1])
        self.pal = PALETTES[K.pick('palette', sorted(PALETTES), r)]
        self.trip = K.pick('trip', ['none', 'melt', 'glitch', 'split'], r, weights=[4, 2, 2, 2])
        self.outline = int(K.pick('outline', [0, 8, 14], r, weights=[1, 2, 2]))
        self.words = K.pick('words', ['big', 'none'], r, weights=[4, 1]) if LV.SHOW_LYRICS else 'none'
        beats = [b for b in LV.BEATS if self.T0 - 2 <= b <= self.T1 + 2]
        self.beats = np.array(beats or [self.T0]); spb = float(np.median(np.diff(self.beats))) if len(self.beats) > 2 else 0.5
        self.spb = spb
        # the bars: which staging, who, which tint for each
        self.plan = []; bar = 0; t = self.T0
        kinds = ['big', 'echo', 'grid', 'duo']
        while t < self.T1:
            who = LV.present(t + 0.1) or sorted(LV.CLIPS)
            k = r.choice(kinds) if self.stage == 'mix' else (self.stage if r.random() < 0.7 else r.choice(kinds))
            if k == 'duo' and len(who) < 2: k = 'echo'
            self.plan.append(dict(t0=t, kind=k, who=r.choice(who), others=who, tint=r.randrange(len(TINTS)), col=bar % len(self.pal)))
            t += 4 * spb; bar += 1
        # word timings inside the window
        self.wordlist = [(t, wd) for _, ws in LV.LINES for wd, t in ws if self.T0 <= t < self.T1] if self.words == 'big' else []
        y, sr = None, None
        self.kick = np.zeros(int((self.T1 - self.T0) * FPS) + 2); self.snare = np.zeros_like(self.kick); self.bass = np.zeros_like(self.kick)
        try:
            import beat as audio
            a = audio.load(LV.SLUG, self.T0, self.T1)
            n = min(len(self.kick), a['n']); self.kick[:n] = audio.hits(a['kicks'], a['n'], 6.0)[:n]; self.snare[:n] = audio.hits(a['snares'], a['n'], 8.0)[:n]
            self.bass[:n] = np.convolve(a['bass'], np.ones(7) / 7, 'same')[:n]
        except Exception as exc: print('no drum hits (%r): moving on the beat grid only' % exc)
        self._tinted = {}
        self.f_word = ImageFont.truetype(ANTON, 190) if os.path.exists(ANTON) else ImageFont.load_default()
        sans = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',) if os.path.exists(p)), None)
        self.f_credit = ImageFont.truetype(sans, 28) if sans else self.f_word
        self.credit = '♪ %s — close quarters' % LV.SONG.get('title', LV.SLUG).lower()

    def beat_phase(self, T):
        k = np.searchsorted(self.beats, T) - 1
        if k < 0: return 0, 0.0
        return int(k), float((T - self.beats[k]) / self.spb)

    def cut(self, who, T, tint=None, width=None):
        im = LV.person(who, T)
        if im is None:
            for w in LV.present(T): im = LV.person(w, T); break
        if im is None: return None
        if tint is not None: im = LV.duotone(im, *TINTS[tint])
        return sticker(im, self.outline if width is None else width)

    def place(self, canvas, im, cx, base, height, rot=0.0):
        s = height / im.height; im2 = im.resize((max(1, int(im.width * s)), max(1, int(height))), Image.BILINEAR)
        if rot: im2 = im2.rotate(rot, resample=Image.BILINEAR, expand=True)
        canvas.alpha_composite(im2, (int(cx - im2.width / 2), int(base - im2.height)))

    def frame(self, i):
        T = self.T0 + i / FPS; kb, ph = self.beat_phase(T)
        sc = next((s for s in reversed(self.plan) if s['t0'] <= T), self.plan[0])
        bounce = math.exp(-ph * 4.5)                                                   # 1 on the beat, falling away
        col = self.pal[(sc['col'] + kb) % len(self.pal)] if sc['kind'] != 'grid' else self.pal[sc['col'] % len(self.pal)]
        canvas = Image.new('RGBA', (W, H), col + (255,))
        d = ImageDraw.Draw(canvas)
        ring = self.pal[(sc['col'] + kb + 1) % len(self.pal)]
        for k in range(6):                                                             # rings pulsing out from the middle
            rad = (k * 260 + (i * 9) % 260) * (1 + 0.15 * bounce)
            d.ellipse([W / 2 - rad, H * 0.45 - rad, W / 2 + rad, H * 0.45 + rad], outline=ring + (90,), width=26)
        kind = sc['kind']
        if kind == 'big':
            im = self.cut(sc['who'], T)
            if im: self.place(canvas, im, W / 2, H * 0.93, H * (0.86 + 0.06 * bounce), rot=6 * math.sin(kb * 1.7) * bounce)
        elif kind == 'echo':
            for j, lag in enumerate((0.45, 0.3, 0.15)):
                im = self.cut(sc['who'], T - lag, tint=(sc['tint'] + j) % len(TINTS), width=0)
                if im: self.place(canvas, im, W / 2 - 120 + j * 60, H * 0.93 - 60 + j * 20, H * 0.8)
            im = self.cut(sc['who'], T)
            if im: self.place(canvas, im, W / 2 + 60, H * 0.95, H * (0.82 + 0.05 * bounce))
        elif kind == 'grid':
            nb = int((T - sc['t0']) / self.spb) + 1; cells = [(c, r_) for r_ in range(3) for c in range(2)][:min(6, 2 * nb)]
            for n_, (c, r_) in enumerate(cells):
                im = self.cut(sc['who'], T - 0.05 * n_, tint=(sc['tint'] + n_) % len(TINTS), width=6)
                if im: self.place(canvas, im, W * (0.27 + 0.46 * c), H * (0.47 + 0.26 * r_), H * 0.25 * (1 + 0.08 * bounce))
        else:                                                                          # duo
            a_, b_ = (sc['others'] + sc['others'])[:2]
            if kb % 2: a_, b_ = b_, a_
            for x, w_ in ((W * 0.3, a_), (W * 0.7, b_)):
                im = self.cut(w_, T)
                if im: self.place(canvas, im, x, H * 0.93, H * (0.7 + 0.05 * bounce))
        img = np.asarray(canvas.convert('RGB')).astype(np.float32)
        n = min(i, len(self.kick) - 1)
        z = 1.0 + 0.09 * self.kick[n] + 0.02 * math.sin(i / 40.0); ang = 3.5 * self.snare[n] * (1 if kb % 2 else -1)
        M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, z)
        img = cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        if self.trip == 'melt':
            amp = 6 + 50 * float(self.bass[n]) ** 2
            dy = (np.sin(GX / 130.0 + i / 9.0) * amp).astype(np.float32); dx = (np.sin(GY / 170.0 + i / 13.0) * amp * 0.4).astype(np.float32)
            img = cv2.remap(img, GX + dx, GY - np.abs(dy), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        elif self.trip == 'glitch' and self.snare[n] > 0.35:
            rr = np.random.default_rng(i)
            for _ in range(int(6 + 14 * self.snare[n])):
                y0 = int(rr.integers(0, H - 80)); hh = int(rr.integers(12, 80)); sh = int(rr.integers(-140, 140))
                img[y0:y0 + hh] = np.roll(img[y0:y0 + hh], sh, axis=1)
        elif self.trip == 'split':
            sh = int(4 + 26 * self.kick[n]); img[..., 0] = np.roll(img[..., 0], sh, axis=1); img[..., 2] = np.roll(img[..., 2], -sh, axis=1)
        out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(out)
        word = next((wd for t, wd in reversed(self.wordlist) if t <= T < t + 0.9), None)
        if word:
            t0 = next(t for t, wd in reversed(self.wordlist) if t <= T and wd == word); age = T - t0
            s = 1.0 + 0.35 * math.exp(-age * 10); f = self.f_word.font_variant(size=int(190 * s))
            d.text((W / 2, H * (0.13 if sc['kind'] == 'grid' else 0.2)), word.strip(',.?!"').upper(), font=f, fill=(255, 255, 255), anchor='mm', stroke_width=12, stroke_fill=(0, 0, 0))
        d.text((W / 2, H - 110), self.credit, font=self.f_credit, fill=(255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        return np.asarray(out)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(f)).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, round(self.T0, 2), round(self.T1, 2), K.record()['knobs'], [s['kind'] for s in self.plan]); return
        tmp = out[:-4] + '.part.mp4'; n = int((self.T1 - self.T0) * FPS)
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-ss', '%.3f' % self.T0, '-t', '%.3f' % (self.T1 - self.T0), '-i', LV.MASTER,
                              '-af', 'afade=t=in:d=0.04,afade=t=out:st=%.2f:d=0.5' % max(0, self.T1 - self.T0 - 0.5),
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'),
                              '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 90 == 0: print(i, '/', n, flush=True)
        p.stdin.close(); p.wait()
        if p.returncode: sys.exit('encode failed')
        os.replace(tmp, out)
        json.dump(dict(K.record(), plan=dict(hook='', window=[round(self.T0, 2), round(self.T1, 2)], scenes=[s['kind'] for s in self.plan],
                                              people=sorted({s['who'] for s in self.plan}))), open(out[:-4] + '.json', 'w'))
        print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    Video(int(sys.argv[2])).render(sys.argv[3])
