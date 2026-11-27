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
Behind them (bg): the flat colour with rings, or real footage from the library (studio/footage.py: city streets,
space, water, old archive film), cut on the bar with a whip pan and graded to the palette (tone: duo, a two-colour
print; soft, blurred and darkened like a shallow focus) so the cut-out stays the thing you look at.
Movement: each beat sends the cut-out to a new spot, angle and size on a spring (it overshoots and settles), the
kick squashes it, each bar slides it in from a side, and the camera drifts like it's handheld.
Knobs (studio/knobs.py): stage (which of the four it leans on), palette, trip, outline, words, bg, tone.
A `short` cut from nightly (6-9 s, CQ_LOOP=1, CQ_LYRICS=none: no words, the footage carries) loops: its last 9
frames fade into frame 0 (lofi_video.looped).
Band footage: this style is only ever for @close__quarters (CLAUDE.md).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import knobs as K
import hook as _hook
import footage
from glitch_video import Clips              # library footage, cut on bar lines and cropped to the frame
import lofi_video as LV                     # the footage, its timing, the lyrics and fonts (it reads the same argv)
import lofi_lib as LIB

W, H, FPS = LV.W, LV.H, LV.FPS
PALETTES = {'acid': [(226, 255, 0), (255, 40, 160), (20, 20, 20), (0, 220, 255)], 'edu': [(74, 12, 208), (226, 40, 150), (20, 150, 230), (255, 110, 40)],
            'candy': [(255, 150, 200), (130, 220, 255), (255, 230, 120), (180, 140, 255)], 'mono': [(15, 15, 15), (240, 240, 235), (230, 30, 40), (240, 240, 235)]}
TINTS = [((40, 0, 95), (200, 40, 210), (255, 185, 250)), ((0, 30, 80), (0, 170, 200), (200, 255, 250)), ((60, 10, 0), (240, 90, 20), (255, 230, 160)),
         ((0, 50, 20), (40, 200, 90), (220, 255, 200))]
ANTON = os.path.join(REPO, 'fonts', 'Anton-Regular.ttf')
# The line on screen for the first two seconds (hook knob; 'none' too, so the learner can compare). Every one is true
# of every video of this style (it is always the band's own phone footage of themselves dancing to the album) and
# none asks the viewer for anything. The two hand-posted dance videos of 2026-11-22 (169 and 346 views, 5-6 s
# watched) are the best this account has done; the automated band lyric videos sit at a median of 76.
# Short, so the box stays big (hook.draw shrinks a long line to fit the width).
HOOKS = ["the band, dancing to the band", "we danced to our own album", "our album. our living room.",
         "new album. old moves."]
GX, GY = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
BGS = {'color': (), 'city': ('nyc', 'city'), 'space': ('space',), 'water': ('water',), 'archive': ('archive', 'silent')}


def spring(t):
    """0 -> 1 with an overshoot that settles: how a move lands when it is pushed on the beat."""
    t = max(0.0, t); return 1.0 - math.exp(-6.0 * t) * math.cos(9.0 * t)


def back_out(t):
    """Ease out with a little run past the end (a slide that lands)."""
    t = min(1.0, max(0.0, t)) - 1.0; return 1.0 + 2.7 * t ** 3 + 1.7 * t ** 2


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
        self.bg = K.pick('bg', list(BGS), r, weights=[2, 3, 2, 2, 1])
        self.tone = K.pick('tone', ['duo', 'soft'], r)
        self.hook = os.environ.get('CQ_HOOK') or K.pick('hook', HOOKS + ['none'], r)
        if self.hook == 'none': self.hook = ''
        self.moves = random.Random(seed * 7919)          # where each beat sends the cut-out (drawn per beat, below)
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
        # the footage behind them, cut on the bar (one or two bars a shot)
        self.clips = None
        if self.bg != 'color':
            try: lib = footage.pull(BGS[self.bg])
            except Exception as exc: lib = []; print('no %s footage (%r)' % (self.bg, exc))
            lib = [e for e in lib if os.path.exists(os.path.join(footage.CACHE, e['asset']))]
            if len(lib) >= 3:
                n = int((self.T1 - self.T0) * FPS) + 2
                self.clips = Clips(lib, n, spb, r.choice([1, 2]), random.Random(seed + 7))
            else:
                print('only %d %s clips: flat colour instead' % (len(lib), self.bg)); self.bg = 'color'; K.CHOSEN['bg'] = 'color'
        # a spot, an angle and a size for every beat, so motion is a function of time (frames can be drawn in any order)
        nb = len(self.beats) + 2
        self.spots = [(self.moves.uniform(-90, 90), self.moves.uniform(-40, 30), self.moves.uniform(-7, 7), self.moves.uniform(0.94, 1.06)) for _ in range(nb)]
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

    def place(self, canvas, im, cx, base, height, rot=0.0, sx=1.0, sy=1.0):
        s = height / im.height; im2 = im.resize((max(1, int(im.width * s * sx)), max(1, int(height * sy))), Image.BILINEAR)
        if rot: im2 = im2.rotate(rot, resample=Image.BILINEAR, expand=True)
        canvas.alpha_composite(im2, (int(cx - im2.width / 2), int(base - im2.height)))

    def background(self, i, sc, kb, bounce, col, dx):
        """What is behind them: flat colour with rings, or library footage graded to the palette."""
        if self.clips is None:
            canvas = Image.new('RGBA', (W, H), col + (255,)); d = ImageDraw.Draw(canvas)
            ring = self.pal[(sc['col'] + kb + 1) % len(self.pal)]
            for k in range(6):                                                         # rings pulsing out from the middle
                rad = (k * 260 + (i * 9) % 260) * (1 + 0.15 * bounce)
                d.ellipse([W / 2 - rad, H * 0.45 - rad, W / 2 + rad, H * 0.45 + rad], outline=ring + (90,), width=26)
            return canvas
        f, k, _e = self.clips.frame(i)
        cut_at = self.clips.plan[k][0]
        f = np.roll(f, int(-dx * 0.25), axis=1)                                       # parallax against the cut-out
        if i - cut_at < 5:                                                             # whip pan into each new shot
            t = (i - cut_at) / 5.0; f = np.roll(f, int(W * 0.35 * (1 - t) ** 2), axis=1)
            f = cv2.blur(f, (int(9 + 80 * (1 - t)), 1))
        rgb = f[..., ::-1].astype(np.float32)
        if self.tone == 'duo':                                                         # a two-colour print in the palette
            lum = (rgb @ np.array([0.3, 0.59, 0.11], np.float32)) / 255.0
            lum = np.clip((lum - 0.12) / 0.76, 0, 1) ** 0.9
            lo = np.array(self.pal[(sc['col'] + 2) % len(self.pal)], np.float32) * 0.22
            hi = np.array(self.pal[(sc['col'] + kb) % len(self.pal)], np.float32)
            img = lo + (hi - lo) * lum[..., None]
        else:                                                                          # shallow focus: blurred, darker
            small = cv2.resize(rgb, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
            img = cv2.resize(cv2.GaussianBlur(small, (0, 0), 3.0), (W, H), interpolation=cv2.INTER_LINEAR) * 0.62
            g = img.mean(axis=2, keepdims=True); img = g + (img - g) * 1.35        # a little more colour
        img = img * (1.0 + 0.22 * bounce)                                              # flashes on the beat
        if sc['kind'] == 'grid': img = img * 0.7                                       # small figures need a quieter ground
        return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert('RGBA')

    def frame(self, i):
        T = self.T0 + i / FPS; kb, ph = self.beat_phase(T)
        sc = next((s for s in reversed(self.plan) if s['t0'] <= T), self.plan[0])
        bounce = math.exp(-ph * 4.5)                                                   # 1 on the beat, falling away
        col = self.pal[(sc['col'] + kb) % len(self.pal)] if sc['kind'] != 'grid' else self.pal[sc['col'] % len(self.pal)]
        n = min(i, len(self.kick) - 1)
        # where the cut-out is: the last beat's spot springing towards this beat's, plus a slide in at each bar
        a_, b_ = self.spots[max(0, kb - 1) % len(self.spots)], self.spots[kb % len(self.spots)]
        sp = spring(ph * self.spb / 0.45)
        dx, dy, rot, sz = (a_[j] + (b_[j] - a_[j]) * sp for j in range(4))
        into = (T - sc['t0']) / max(1e-3, 0.4 * self.spb)
        # every bar slides in from a side, except the first: frame 0 is the cover, and a slide put the cut-out off-screen
        if into < 1 and sc['kind'] in ('big', 'duo', 'echo') and sc is not self.plan[0]:
            side = 1 if self.plan.index(sc) % 2 else -1
            dx += side * W * 0.9 * (1 - back_out(into))
        squash = float(self.kick[n])
        sx, sy = 1 + 0.07 * squash, 1 - 0.06 * squash
        canvas = self.background(i, sc, kb, bounce, col, dx)
        kind = sc['kind']
        if kind == 'big':
            im = self.cut(sc['who'], T)
            if im: self.place(canvas, im, W / 2 + dx, H * 0.93 + dy * 0.5, H * (0.84 + 0.05 * bounce) * sz, rot=rot, sx=sx, sy=sy)
        elif kind == 'echo':
            for j, lag in enumerate((0.45, 0.3, 0.15)):
                im = self.cut(sc['who'], T - lag, tint=(sc['tint'] + j) % len(TINTS), width=0)
                if im: self.place(canvas, im, W / 2 - 120 + j * 60 + dx * (0.4 + 0.2 * j), H * 0.93 - 60 + j * 20, H * 0.8 * sz, rot=rot * 0.5)
            im = self.cut(sc['who'], T)
            if im: self.place(canvas, im, W / 2 + 60 + dx, H * 0.95 + dy * 0.4, H * (0.82 + 0.05 * bounce) * sz, rot=rot * 0.6, sx=sx, sy=sy)
        elif kind == 'grid':
            nb = int((T - sc['t0']) / self.spb) + 1; cells = [(c, r_) for r_ in range(3) for c in range(2)][:min(6, 2 * nb)]
            for n_, (c, r_) in enumerate(cells):
                im = self.cut(sc['who'], T - 0.05 * n_, tint=(sc['tint'] + n_) % len(TINTS), width=6)
                if im: self.place(canvas, im, W * (0.27 + 0.46 * c), H * (0.47 + 0.26 * r_), H * 0.25 * (1 + 0.08 * bounce))
        else:                                                                          # duo
            a_, b_ = (sc['others'] + sc['others'])[:2]
            if kb % 2: a_, b_ = b_, a_
            for j_, (x, w_) in enumerate(((W * 0.3, a_), (W * 0.7, b_))):
                im = self.cut(w_, T)
                if im: self.place(canvas, im, x + dx * 0.5, H * 0.93, H * (0.7 + 0.05 * bounce) * sz, rot=rot * (1 if j_ else -1) * 0.7, sx=sx, sy=sy)
        img = np.asarray(canvas.convert('RGB')).astype(np.float32)
        z = 1.0 + 0.09 * self.kick[n] + 0.02 * math.sin(i / 40.0); ang = 3.5 * self.snare[n] * (1 if kb % 2 else -1) + 0.8 * math.sin(i / 23.0)
        M = cv2.getRotationMatrix2D((W / 2 + 14 * math.sin(i / 17.0), H / 2 + 10 * math.sin(i / 29.0 + 1)), ang, z)   # handheld drift
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
        held = bool(self.hook) and T - self.T0 < _hook.SHOW + _hook.FADE     # the opening line has the top to itself
        word = None if held else next((wd for t, wd in reversed(self.wordlist) if t <= T < t + 0.9), None)
        if word:
            t0 = next(t for t, wd in reversed(self.wordlist) if t <= T and wd == word); age = T - t0
            s = 1.0 + 0.35 * math.exp(-age * 10); f = self.f_word.font_variant(size=int(190 * s))
            d.text((W / 2, H * (0.13 if sc['kind'] == 'grid' else 0.2)), word.strip(',.?!"').upper(), font=f, fill=(255, 255, 255), anchor='mm', stroke_width=12, stroke_fill=(0, 0, 0))
        # the credit just above Instagram's caption area (bottom 420 px); it used to sit at H - 110, under the UI
        d.text((W / 2, H - 450), self.credit, font=self.f_credit, fill=(255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        a = np.asarray(out)
        if held: a = _hook.draw(a, self.hook, T - self.T0, y=0.155)
        return a

    def render(self, out):
        n = int((self.T1 - self.T0) * FPS); draw = LV.looped(self.frame, n, LV.loop_wanted(self.T0, self.T1))
        if '--frames' in sys.argv:
            fs = [min(int(x), n - 1) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(draw(f)).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, round(self.T0, 2), round(self.T1, 2), K.record()['knobs'], [s['kind'] for s in self.plan]); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-ss', '%.3f' % self.T0, '-t', '%.3f' % (self.T1 - self.T0), '-i', LV.MASTER,
                              '-af', 'afade=t=in:d=0.04,afade=t=out:st=%.2f:d=0.5' % max(0, self.T1 - self.T0 - 0.5),
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'),
                              '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(n):
            p.stdin.write(draw(i).tobytes())
            if i % 90 == 0: print(i, '/', n, flush=True)
        p.stdin.close(); p.wait()
        if p.returncode: sys.exit('encode failed')
        os.replace(tmp, out)
        json.dump(dict(K.record(), plan=dict(hook=self.hook, window=[round(self.T0, 2), round(self.T1, 2)], scenes=[s['kind'] for s in self.plan],
                                              people=sorted({s['who'] for s in self.plan}))), open(out[:-4] + '.json', 'w'))
        print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    Video(int(sys.argv[2])).render(sys.argv[3])
