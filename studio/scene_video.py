#!/usr/bin/env python3
"""The band in real places, for close__quarters: cut out cleanly from their own dance footage and set into a world.

    python studio/scene_video.py SONG_DIR SEED OUT.mp4            (CQ_WINDOW="t0,t1": the stretch to play)
    python studio/scene_video.py SONG_DIR SEED SHEET.png --frames 0,60,120

The idea (people set into places rather than stickered onto colour) came from watching dev_lemons; everything else
here is ours, and her signatures (a letterboxed picture, small italic lyrics, laptops, handheld consoles, billboards
with WordArt, cartoon clouds, pixel waves) are left out on purpose. Full-screen vertical, one world a video:
  school   EDUCATION's world: empty school places after hours (a locker hallway, a classroom, the gym, the bus, the
           band room), from the AI plate library (studio/plates_gen.py); the lyric chalked on, word by word, in a
           schoolbell hand; a class-period tag ("PERIOD 3 · FIXATION") in the corner like a timetable
  psych    surreal but photographic landscapes (two moons over dunes, a lake full of aurora, giant flowers) from the
           plate library; the air ripples on the bass; the lyric scrawled in marker, tilted, a new colour each place
  nyc      New York as it looks now (the subway, skylines, rain on a street at night): free modern footage and our
           own clips (footage theme nyc_now, and studio/footage/inbox/nyc.txt), else New York plates; graded like film
           (warm highlights, teal shadows, grain), the camera handheld with a little gate weave; film subtitles
The person sits in the picture: their colour pulled towards the scene's light, a softened edge, grain over both, a
contact shadow, and they drift less than the place does (parallax). A new place every two bars, the camera pushing in
slowly and nudged by the kick.
Knobs (studio/knobs.py): world, side (where they stand), push (how far the camera travels).
Band footage: this style is only ever for @close__quarters (CLAUDE.md).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import knobs as K
import footage
import plates_gen
import lofi_video as LV                     # the dance footage, its timing, the lyrics (it reads the same argv)
import lofi_lib as LIB

W, H, FPS = LV.W, LV.H, LV.FPS
FONTS = os.path.join(REPO, 'fonts')
CHALK = os.path.join(FONTS, 'Schoolbell-Regular.ttf')
MARKER = os.path.join(FONTS, 'PermanentMarker-Regular.ttf')
MONO = os.path.join(FONTS, 'DejaVuSansMono-Bold.ttf')
INKS = [(255, 214, 10), (255, 92, 170), (120, 220, 255), (170, 255, 120), (255, 150, 60)]
WORLDS = ['school', 'psych', 'nyc']
ORDER = ['prologue', 'full-ride', 'hair-of-the-dog', 'talk', 'fixation', 'wont-be-the-same-again', 'myth-of-sisyphus',
         'suspended', 'subway-maintenance', 'silver-and-gold', 'evil-close-quarters', 'notta-problem', 'recess-rewind',
         'passage-waiting', 'epilogue-dismissal']


def cover(img, w, h, zoom=1.0, cx=0.5, cy=0.5):
    """img scaled to cover w x h (times zoom), cropped around (cx, cy) as shares of the image."""
    ih, iw = img.shape[:2]; s = max(w / iw, h / ih) * zoom
    r = cv2.resize(img, (int(iw * s) + 1, int(ih * s) + 1), interpolation=cv2.INTER_LINEAR)
    x0 = int(np.clip(cx * r.shape[1] - w / 2, 0, r.shape[1] - w)); y0 = int(np.clip(cy * r.shape[0] - h / 2, 0, r.shape[0] - h))
    return r[y0:y0 + h, x0:x0 + w]


def film(rgb, i, warm=True):
    """A film grade: lifted blacks, teal shadows and warm highlights, grain, a soft vignette."""
    a = rgb.astype(np.float32) / 255
    lum = a @ np.array([0.3, 0.59, 0.11], np.float32)
    a = a * 0.93 + 0.03
    if warm:
        a = a + (1 - lum)[..., None] * np.array([-0.02, 0.025, 0.045], np.float32) + lum[..., None] * np.array([0.05, 0.015, -0.035], np.float32)
    yy, xx = np.ogrid[-1:1:complex(0, a.shape[0]), -1:1:complex(0, a.shape[1])]
    a = a * (1 - 0.28 * np.clip(xx * xx * 0.6 + yy * yy * 0.4, 0, 1))[..., None]
    a = np.clip(a, 0, 1) * 255
    return a + np.random.default_rng(i).normal(0, 5.5, a.shape[:2]).astype(np.float32)[..., None]


def wrap(text, f, width):
    rows, cur = [], ''
    for wd in text.split():
        t = (cur + ' ' + wd).strip()
        if f.getlength(t) > width and cur: rows.append(cur); cur = wd
        else: cur = t
    return rows + ([cur] if cur else [])


class Video:
    def __init__(self, seed):
        for c in LIB.clips_for(LV.SLUG): LV.CLIPS.setdefault(c['who'], []).append((c['id'], c['offset'], c['frames'], c['fps']))
        if not LV.CLIPS: sys.exit('no footage for %s in studio/lofi/index.json' % LV.SLUG)
        w = os.environ.get('CQ_WINDOW'); first = LV.CLIPS[sorted(LV.CLIPS)[0]][0][1]
        T0, T1 = (float(x) for x in w.split(',')) if w else (first + 1, first + 16)
        self.T0, self.T1 = LV.fit_window(T0, T1, seed)
        r = random.Random(seed); self.r = r; self.seed = seed
        self.world = K.pick('world', WORLDS, r, weights=[3, 2, 2])
        self.side = K.pick('side', ['left', 'centre', 'right', 'move'], r, weights=[1, 2, 1, 2])
        self.push = float(K.pick('push', [0.04, 0.08, 0.14], r))
        self.pool = self.places(self.world)
        for alt in [x for x in WORLDS if x != self.world]:                       # a world with nothing cached: the next one
            if len(self.pool) >= 3: break
            print('no %s places cached; using %s' % (self.world, alt)); self.world = alt; K.CHOSEN['world'] = alt; self.pool = self.places(alt)
        if len(self.pool) < 3: sys.exit('no plates or New York clips cached: run studio/plates_gen.py pull and studio/footage.py pull nyc')
        beats = [b for b in LV.BEATS if self.T0 - 2 <= b <= self.T1 + 2]
        self.beats = np.array(beats or [self.T0]); self.spb = float(np.median(np.diff(self.beats))) if len(self.beats) > 2 else 0.5
        order = self.pool[:]; r.shuffle(order)
        self.plan = []; t = self.T0; k = 0
        while t < self.T1:
            who = LV.present(t + 0.1) or sorted(LV.CLIPS)
            x = {'left': 0.3, 'centre': 0.5, 'right': 0.7}.get(self.side) or r.choice([0.3, 0.5, 0.7])
            self.plan.append(dict(t0=t, who=r.choice(who), entry=order[k % len(order)], x=x, cx=r.uniform(0.35, 0.65),
                                  ink=INKS[(k + seed) % len(INKS)], tilt=r.uniform(-6, 6), off=r.randrange(0, 200), k=k))
            t += 8 * self.spb; k += 1
        self.kick = np.zeros(int((self.T1 - self.T0) * FPS) + 2); self.bass = np.zeros_like(self.kick)
        try:
            import beat as audio
            a = audio.load(LV.SLUG, self.T0, self.T1); n = min(len(self.kick), a['n'])
            self.kick[:n] = audio.hits(a['kicks'], a['n'], 6.0)[:n]; self.bass[:n] = np.convolve(a['bass'], np.ones(7) / 7, 'same')[:n]
        except Exception as exc: print('no drum hits (%r)' % exc)
        self.lines = [[(t, wd) for wd, t in ws] for _, ws in LV.LINES if ws and self.T0 - 1 <= ws[-1][1] and ws[0][1] < self.T1] if LV.SHOW_LYRICS else []
        self.f_chalk = ImageFont.truetype(CHALK if os.path.exists(CHALK) else LV.SANS, 100)
        self.f_marker = ImageFont.truetype(MARKER if os.path.exists(MARKER) else LV.SANS_B, 88)
        self.f_sub = ImageFont.truetype(LV.SANS_B, 54); self.f_tag = ImageFont.truetype(MONO, 30); self.f_credit = ImageFont.truetype(LV.SANS, 28)
        title = LV.SONG.get('title', LV.SLUG)
        self.credit = '♪ %s — close quarters' % title.lower()
        self.tag = 'PERIOD %d · %s' % ((ORDER.index(LV.SLUG) if LV.SLUG in ORDER else 0) % 8 + 1, title.upper())
        self._img = {}; self._cap = {}; self.yy, self.xx = np.mgrid[0:H, 0:W].astype(np.float32)

    @staticmethod
    def places(world):
        """The world's places: plate entries, or for nyc moving clips of New York as it looks now (theme nyc_now: free
        modern footage, plus our own clips from the inbox) once there are a few, else New York plates. The library's
        1899 films (theme nyc) are the wrong New York for this and never used here."""
        if world == 'nyc':
            try:
                now = [e for e in footage.index().get('clips', []) if e.get('theme') == 'nyc_now' or (e.get('theme') == 'nyc' and e.get('source') == 'own')]
                if len(now) >= 3:
                    footage.pull(('nyc_now',)); any(e.get('source') == 'own' for e in now) and footage.pull(('nyc',)); now = [e for e in now if os.path.exists(os.path.join(footage.CACHE, e['asset']))]
                    if len(now) >= 3: return [dict(e, moving=True) for e in now]
            except Exception as exc: print('no modern New York clips (%r)' % exc)
        try: got = plates_gen.pull((world,))
        except Exception as exc: print('no %s plates (%r)' % (world, exc)); return []
        return [e for e in got if os.path.exists(os.path.join(plates_gen.CACHE, e['asset']))]

    # ------------------------------------------------------------ the place
    def plate(self, e):
        if e['asset'] not in self._img:
            if len(self._img) > 5: self._img.pop(next(iter(self._img)))
            im = cv2.imread(os.path.join(plates_gen.CACHE, e['asset']))[..., ::-1]
            self._img[e['asset']] = cv2.resize(im, (int(im.shape[1] * (H + 100) / im.shape[0]), H + 100), interpolation=cv2.INTER_CUBIC)
        return self._img[e['asset']]

    def clip(self, sc, i):
        """The New York clip for this place, read once at half size and played forward then back."""
        key = sc['k']
        if key not in self._cap:
            for old in [c for c in self._cap if c != key][:-1]: del self._cap[old]
            cap = cv2.VideoCapture(os.path.join(footage.CACHE, sc['entry']['asset'])); total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 300
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(sc['off'], max(0, total - 90))); fr = []
            while len(fr) < 240:
                ok, f = cap.read()
                if not ok: break
                fr.append(cover(f[..., ::-1], W // 2, H // 2))
            cap.release(); self._cap[key] = (fr + fr[::-1]) or [np.zeros((H // 2, W // 2, 3), np.uint8)]
        fr = self._cap[key]
        return cv2.resize(fr[(i - int((sc['t0'] - self.T0) * FPS)) % len(fr)], (W, H), interpolation=cv2.INTER_LINEAR)

    def background(self, sc, i, travel):
        n = min(i, len(self.kick) - 1)
        if sc['entry'].get('moving'): return self.clip(sc, i).astype(np.float32)
        z = 1.02 + self.push * travel + 0.012 * self.kick[n]                     # a slow push-in, nudged by the kick
        bg = cover(self.plate(sc['entry']), W, H, z, sc['cx'] + 0.05 * (travel - 0.5), 0.5).astype(np.float32)
        if self.world == 'psych':                                                # the air ripples on the bass
            amp = 1.5 + 8 * float(self.bass[n]) ** 2
            mx = self.xx + amp * np.sin(self.yy / 85 + i / 9); my = self.yy + 0.5 * amp * np.sin(self.xx / 120 + i / 15)
            bg = cv2.remap(bg, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        elif self.world == 'school':                                             # after hours: the fluorescents hum
            bg *= 0.975 + 0.025 * math.sin(i * 1.7) * math.sin(i * 0.31)
        return bg

    # ------------------------------------------------------------ the person
    def person(self, sc, T, light):
        im = LV.person(sc['who'], T)
        if im is None:
            for w_ in LV.present(T): im = LV.person(w_, T); break
        if im is None: return None
        h = int(H * 0.74); s = h / im.height; im = im.resize((max(1, int(im.width * s)), h), Image.BILINEAR)
        a = np.asarray(im).astype(np.float32); rgb = a[..., :3]
        alpha = cv2.GaussianBlur(cv2.erode(a[..., 3], np.ones((5, 5), np.uint8)), (0, 0), 1.6)
        core = (cv2.erode(a[..., 3], np.ones((9, 9), np.uint8)) > 250).astype(np.float32)   # the edge takes the colour of
        num = cv2.GaussianBlur(rgb * core[..., None], (0, 0), 6); den = cv2.GaussianBlur(core, (0, 0), 6)[..., None]  # the inside,
        rgb = np.where(core[..., None] > 0, rgb, num / np.maximum(den, 1e-3))     # not the wall it was filmed against
        hh, ww = alpha.shape; ramp = lambda n, m: np.clip(np.minimum(np.arange(n), n - 1 - np.arange(n)) / (m * n), 0, 1)
        alpha = alpha * ramp(ww, 0.08)[None, :] * np.clip(np.arange(hh) / (0.05 * hh), 0, 1)[:, None]  # an arm that left
        rgb = rgb * 0.8 + np.array(light, np.float32) * 0.2                       # their camera fades, not a cut edge
        g = rgb.mean(axis=2, keepdims=True); rgb = g + (rgb - g) * 0.9
        return Image.fromarray(np.dstack([np.clip(rgb, 0, 255), alpha]).astype(np.uint8), 'RGBA')

    # ------------------------------------------------------------ the words
    def lyric(self, out, T, sc):
        line = next((ln for ln in self.lines if ln[0][0] - 0.15 <= T <= ln[-1][0] + 1.0), None)
        shown = [wd for t, wd in (line or []) if t <= T]
        if not shown: return
        text = ' '.join(shown); d = ImageDraw.Draw(out)
        if self.world == 'nyc':                                                  # film subtitles, low and centred
            rows = wrap(text, self.f_sub, W - 180)[-2:]
            for k, row in enumerate(rows):
                d.text((W / 2, H * 0.80 + k * 68), row, font=self.f_sub, fill=(255, 250, 225), anchor='mm', stroke_width=4, stroke_fill=(0, 0, 0))
            return
        f = self.f_chalk if self.world == 'school' else self.f_marker
        rows = wrap(text.lower() if self.world == 'school' else text.upper(), f, W - 160)[-3:]
        layer = Image.new('RGBA', (W, 440), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
        for k, row in enumerate(rows):
            y = 80 + k * 116
            if self.world == 'school':
                ld.text((W / 2 + 3, y + 4), row, font=f, fill=(0, 0, 0, 110), anchor='mm')
                ld.text((W / 2, y), row, font=f, fill=(246, 246, 238, 255), anchor='mm')
            else:
                ld.text((W / 2, y), row, font=f, fill=sc['ink'] + (255,), anchor='mm', stroke_width=6, stroke_fill=(18, 10, 24))
        if self.world == 'school':                                               # chalk: a dusty, broken stroke
            arr = np.asarray(layer).astype(np.float32); noise = np.random.default_rng(int(T * 4)).random(arr.shape[:2])
            arr[..., 3] *= np.clip(0.5 + 0.7 * noise, 0, 1); layer = Image.fromarray(arr.astype(np.uint8), 'RGBA')
        else:
            layer = layer.rotate(sc['tilt'], resample=Image.BICUBIC, center=(W / 2, 220))
        out.alpha_composite(layer, (0, int(H * 0.12)))

    # ------------------------------------------------------------ the frame
    def frame(self, i):
        T = self.T0 + i / FPS
        sc = next((s for s in reversed(self.plan) if s['t0'] <= T), self.plan[0])
        travel = min(1.0, (T - sc['t0']) / (8 * self.spb))
        bg = self.background(sc, i, travel)
        light = tuple(int(v) for v in cv2.resize(bg, (8, 8), interpolation=cv2.INTER_AREA).reshape(-1, 3).mean(0))
        canvas = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8)).convert('RGBA')
        p = self.person(sc, T, light)
        if p:
            x = sc['x'] if self.side != 'move' else 0.3 + 0.4 * (0.5 + 0.5 * math.sin((T - self.T0) * 0.5 + sc['k'] * 2.1))
            cx = W * x - (travel - 0.5) * 24                                     # they drift less than the place
            sw = int(p.width * 0.85); sh = Image.new('L', (sw, 100), 0); ImageDraw.Draw(sh).ellipse([0, 30, sw, 85], fill=150)
            blk = Image.new('RGBA', sh.size, (0, 0, 0, 255)); blk.putalpha(sh.filter(ImageFilter.GaussianBlur(18)))
            canvas.alpha_composite(blk, (int(cx - sw / 2), H - 95))
            canvas.alpha_composite(p, (int(cx - p.width / 2), int(H * 1.03 - p.height)))
        a = np.asarray(canvas.convert('RGB'))
        n = min(i, len(self.kick) - 1)
        if self.world == 'nyc':                                                  # handheld, with a little gate weave
            M = cv2.getRotationMatrix2D((W / 2 + 9 * math.sin(i / 13.0) + 2 * math.sin(i * 0.9), H / 2 + 7 * math.sin(i / 17.0) + 2 * math.sin(i * 1.3)),
                                        0.4 * math.sin(i / 21.0), 1.04 + 0.012 * self.kick[n])
            a = cv2.warpAffine(a, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        g = film(a, i, warm=self.world != 'psych')
        age = T - sc['t0']
        if age < 0.12 and sc['k']: g = g * (0.35 + 0.65 * age / 0.12)          # a quick dip into each new place
        out = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).convert('RGBA')
        self.lyric(out, T, sc); d = ImageDraw.Draw(out)
        if self.world == 'school':
            tw = self.f_tag.getlength(self.tag)
            d.rounded_rectangle([44, 96, 44 + tw + 36, 148], radius=6, fill=(250, 246, 226, 235))
            d.text((62, 122), self.tag, font=self.f_tag, fill=(48, 36, 36), anchor='lm')
        d.text((W / 2, H - 64), self.credit, font=self.f_credit, fill=(255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        return np.asarray(out.convert('RGB'))

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(f)).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, round(self.T0, 2), round(self.T1, 2), K.record()['knobs'], self.world); return
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
        json.dump(dict(K.record(), plan=dict(hook='', window=[round(self.T0, 2), round(self.T1, 2)], world=self.world,
                                              places=[s['entry'].get('scene') or s['entry'].get('title') for s in self.plan],
                                              people=sorted({s['who'] for s in self.plan}))), open(out[:-4] + '.json', 'w'))
        print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    Video(int(sys.argv[2])).render(sys.argv[3])
