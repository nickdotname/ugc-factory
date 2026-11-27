#!/usr/bin/env python3
"""Colour illusions: the same colour that looks like two, asked and then proven on the beat (a ready page:
colour.lies, paused until its Instagram account exists; see docs/brain/ready-pages.md).

    python studio/hue_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/hue_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

Every picture is drawn in code. A video is one illusion:
  munker    bars of one colour laid in two sets of stripes (Munker-White)        "same colour, or not?"
  confetti  grey dots behind two sets of coloured stripes (confetti illusion)    "what colour are the dots?"
  contrast  one small square on two coloured grounds (simultaneous contrast)     "same colour, or not?"
  bezold    one colour under thin black lines and under thin white lines (Bezold) "which side is brighter?"
  (cast     a table of balls behind a coloured filter, the middle ball grey: drawn, not yet in rotation)
The question holds for a few seconds (a bar fills under it), then on the beat an eyedropper takes one pixel from
each piece: two swatches drop out, slide together until they touch, and each shows the hex code READ OFF THE FRAME
at the marked pixel. Then the surroundings fade to plain grey and the pieces are seen as they are; then it all comes
back ("same colour. still looks different."). Choreographed in beats; a stretch too short exits 3.
No finishing pass (studio/polish.py would grade and vignette the colours the video is about); the hex codes are true.
Knobs (studio/knobs.py): kind, set (the colours of that kind), page (dark, light), flip (which side is which).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
MAX_LEN = 24.0
PY0, PH = 470, 790                  # the picture: full width, y 470..1260 (40 px shorter since 2026-11-27: the swatches, codes and credit all fit under it)
GROUND = np.array([128, 128, 128], np.float32)     # what the surroundings fade to: a plain mid grey
SW, SY = 130, 1340                  # swatch size and centre line: swatches 1275-1405, codes ~1441, credit 1480
PAGES = {'dark': dict(bg=(26, 26, 28), txt=(240, 240, 236), dim=(120, 120, 120)),
         'light': dict(bg=(236, 236, 234), txt=(24, 24, 26), dim=(140, 140, 140))}
BACK = 'same colour.\nstill looks different.'


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)


def mix(a, b, t): return np.asarray(a, np.float32) * t + np.asarray(b, np.float32) * (1 - t)


# ---- the illusions. Each draws the picture (PH x W, float RGB) for a given ctx (1 = surroundings shown, 0 = faded
# to grey), and gives two sample points (picture coordinates) that land on the pieces being compared.
class Munker:
    SETS = {'sunset': dict(a=(250, 214, 0), b=(36, 64, 230), t=(236, 70, 96)),
            'lime':   dict(a=(0, 190, 90), b=(214, 0, 170), t=(168, 160, 150)),
            'ember':  dict(a=(255, 120, 0), b=(0, 150, 210), t=(214, 190, 150))}
    ask = 'same colour,\nor not?'
    def __init__(s, r, flip, set_):
        s.c = s.SETS[set_]; s.h = r.choice([14, 16, 18]); s.flip = flip
        s.box = [(80, 150, 500, 690), (580, 150, 1000, 690)]      # x0, y0, x1, y1 of the two blocks of bars
    def picture(s, ctx):
        T = np.float32(s.c['t'])
        A = mix(s.c['a'], GROUND, ctx); B = mix(s.c['b'], GROUND, ctx)
        img = np.empty((PH, W, 3), np.float32)
        rows = np.arange(PH) // s.h
        img[rows % 2 == 0] = A; img[rows % 2 == 1] = B
        for k, (x0, y0, x1, y1) in enumerate(s.box):
            par = (k + s.flip) % 2                                # bars replace the even rows in one block, odd in the other
            for y in range(y0, y1):
                if rows[y] % 2 == par: img[y, x0:x1] = T
        return img
    def points(s):
        pts = []
        for k, (x0, y0, x1, y1) in enumerate(s.box):
            par = (k + s.flip) % 2; ym = (y0 + y1) // 2
            row = ym // s.h
            if row % 2 != par: row += 1
            pts.append(((x0 + x1) // 2, row * s.h + s.h // 2))
        return pts
    def answer(s): return 'the same colour.'


class Confetti:
    SETS = {'yellowblue': dict(a=(255, 222, 0), b=(40, 120, 255), t=(178, 178, 178)),
            'redgreen':   dict(a=(255, 40, 60), b=(0, 214, 110), t=(178, 178, 178)),
            'pinkteal':   dict(a=(255, 60, 200), b=(0, 210, 200), t=(170, 170, 170))}
    ask = 'what colour\nare the dots?'
    def __init__(s, r, flip, set_):
        s.c = s.SETS[set_]; s.p = 26; s.w = 9; s.flip = flip
        s.dots = []
        y = 80
        while y < PH - 70:
            yc = (y // s.p) * s.p + 17                     # centre row sits in a gap between stripes
            off = r.uniform(0, 70)
            x = 60 + off
            while x < W - 55:
                if abs(x - 540) > 70: s.dots.append((x + r.uniform(-14, 14), yc, r.choice([34, 38, 42])))
                x += r.uniform(118, 150)
            y += r.choice([104, 130])
        s.pts = [min((d for d in s.dots if d[0] < 540), key=lambda d: abs(d[0] - 300) + abs(d[1] - 415)),
                 min((d for d in s.dots if d[0] > 540), key=lambda d: abs(d[0] - 780) + abs(d[1] - 415))]
    def picture(s, ctx):
        img = np.empty((PH, W, 3), np.float32); img[:] = mix((18, 18, 18), GROUND, ctx)
        u8 = np.zeros((PH, W, 3), np.uint8)
        for x, y, rr in s.dots: cv2.circle(u8, (int(x), int(y)), rr, (255, 255, 255), -1, cv2.LINE_AA)
        m = u8[..., :1].astype(np.float32) / 255
        img = img * (1 - m) + np.float32(s.c['t']) * m
        stripe = (np.arange(PH) % s.p) < s.w
        L, R = (s.c['a'], s.c['b']) if not s.flip else (s.c['b'], s.c['a'])
        for x0, x1, col in ((0, 540, L), (540, W, R)):
            seg = img[stripe, x0:x1]
            img[stripe, x0:x1] = seg * (1 - ctx) + np.float32(col) * ctx
        return img
    def points(s): return [(int(d[0]), int(d[1])) for d in s.pts]
    def answer(s): return 'all the same grey.'


class Contrast:
    SETS = {'bluegold': dict(a=(30, 70, 210), b=(246, 196, 20), t=(140, 138, 134)),
            'redgreen': dict(a=(214, 28, 44), b=(20, 168, 92), t=(150, 140, 140)),
            'tealorange': dict(a=(0, 150, 170), b=(250, 120, 20), t=(156, 132, 120))}
    ask = 'same colour,\nor not?'
    def __init__(s, r, flip, set_):
        s.c = s.SETS[set_]; s.flip = flip; s.q = r.choice([130, 150, 170])
        s.blk = [(0, 60, 540, 790), (540, 60, W, 790)]
    def picture(s, ctx):
        img = np.empty((PH, W, 3), np.float32); img[:] = GROUND
        L, R = (s.c['a'], s.c['b']) if not s.flip else (s.c['b'], s.c['a'])
        for (x0, y0, x1, y1), col in zip(s.blk, (L, R)):
            img[y0:y1, x0:x1] = mix(col, GROUND, ctx)
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            img[cy - s.q // 2:cy + s.q // 2, cx - s.q // 2:cx + s.q // 2] = s.c['t']
        return img
    def points(s): return [((x0 + x1) // 2, (y0 + y1) // 2) for x0, y0, x1, y1 in s.blk]
    def answer(s): return 'the same colour.'


class Bezold:
    SETS = {'red': dict(t=(196, 36, 52), name='red'), 'blue': dict(t=(40, 86, 214), name='blue'),
            'green': dict(t=(30, 160, 84), name='green')}
    def __init__(s, r, flip, set_):
        s.c = s.SETS[set_]; s.flip = flip; s.p = r.choice([24, 28]); s.w = 8
        s.blk = [(60, 70, 520, 760), (560, 70, 1020, 760)]
        s.ask = 'which %s\nis brighter?' % s.c['name']
    def picture(s, ctx):
        img = np.empty((PH, W, 3), np.float32); img[:] = GROUND
        T = np.float32(s.c['t']); line = (np.arange(PH) % s.p) < s.w
        inks = [(10, 10, 10), (250, 250, 250)] if not s.flip else [(250, 250, 250), (10, 10, 10)]
        for (x0, y0, x1, y1), ink in zip(s.blk, inks):
            img[y0:y1, x0:x1] = T
            rows = np.where(line[y0:y1])[0] + y0
            img[rows, x0:x1] = mix(ink, T, ctx)
        return img
    def points(s):
        out = []
        for x0, y0, x1, y1 in s.blk:
            ym = (y0 + y1) // 2; ym = (ym // s.p) * s.p + s.w + (s.p - s.w) // 2
            out.append(((x0 + x1) // 2, ym))
        return out
    def answer(s): return 'the same %s.' % s.c['name']


class Cast:
    """A table of shaded balls seen through a coloured filter (per-channel gains). The middle ball is coloured so that
    after the filter every one of its lit pixels has R = G = B: grey. The eye discounts the filter and sees colour."""
    SETS = {'cyan': dict(g=(0.42, 0.92, 1.0), k=88, name='red',
                         others=[(236, 200, 40), (40, 92, 204), (232, 232, 226), (40, 164, 74)]),
            'blue': dict(g=(0.52, 0.58, 1.0), k=104, name='yellow',
                         others=[(214, 40, 44), (40, 164, 74), (232, 232, 226), (40, 92, 204)])}
    ask = 'what colour is\nthe middle ball?'
    def __init__(s, r, flip, set_):
        s.c = s.SETS[set_]; g = np.float32(s.c['g'])
        s.target = tuple(s.c['k'] / g)                        # the ball's own colour before the filter
        oth = list(s.c['others']); r.shuffle(oth)
        sx = -1 if flip else 1
        s.balls = [(540 + sx * 300, 610, 104, oth[0]), (540 - sx * 320, 600, 96, oth[1]),
                   (540 - sx * 130, 470, 70, oth[2]), (540 + sx * 170, 455, 64, oth[3]),
                   (540, 585, 128, s.target)]
        s.lift = 18.0
        s.base, s.mask = s.scene()
    def scene(s):
        img = np.zeros((PH, W, 3), np.float32)
        yy, xx = np.mgrid[0:PH, 0:W].astype(np.float32)
        wall = np.float32((246, 240, 228)) * (0.82 + 0.18 * (1 - yy / 400))[..., None]
        table_y = 400
        wood = np.float32((214, 160, 104)) * (0.78 + 0.22 * ((yy - table_y) / (PH - table_y)))[..., None]
        grain = (np.sin(xx / 9.0 + 3 * np.sin(yy / 60.0)) * 0.04 + 1)[..., None]
        img[:] = np.where((yy < table_y)[..., None], wall, wood * grain)
        img[table_y - 3:table_y + 3] *= 0.6
        L = np.float32([-0.55, -0.6, 0.58]); L /= np.linalg.norm(L)
        mask = np.zeros((PH, W), np.float32)
        for cx, cy, R, col in s.balls:
            # contact shadow on the table, down and to the right of the light
            sh = np.exp(-(((xx - cx - 0.35 * R) / (1.15 * R)) ** 2 + ((yy - cy - 0.9 * R) / (0.32 * R)) ** 2) * 2.2)
            img *= (1 - 0.55 * sh)[..., None]
        for cx, cy, R, col in s.balls:
            dx, dy = (xx - cx) / R, (yy - cy) / R; d2 = dx * dx + dy * dy
            inside = np.clip((1 - np.sqrt(d2)) * R + 0.5, 0, 1)        # antialiased edge
            nz = np.sqrt(np.clip(1 - d2, 0, 1))
            lam = np.clip(-(dx * L[0] + dy * L[1]) + nz * L[2], 0, 1)
            shade = 0.46 + 0.54 * lam
            hl = np.exp(-(((dx + 0.38) ** 2 + (dy + 0.42) ** 2) / 0.018)) * 0.9      # a small soft highlight
            ballc = np.float32(col)[None, None] * shade[..., None]
            ballc = ballc * (1 - hl[..., None]) + 255 * hl[..., None]
            img = img * (1 - inside[..., None]) + ballc * inside[..., None]
            if col is s.target: mask = np.maximum(mask, inside)
            else: mask = mask * (1 - inside)                          # a ball in front hides the target
        img = np.clip(img, 0, 255) * np.float32(s.c['g']) + s.lift
        return img, mask
    def picture(s, ctx):
        m = s.mask[..., None]
        return s.base * m + (s.base * ctx + GROUND * (1 - ctx)) * (1 - m)
    def points(s):
        # two pixels mirrored about the light's direction: the same angle to the light, so the same shade
        cx, cy, R, _ = s.balls[-1]
        lx, ly = -0.55, -0.6; n = math.hypot(lx, ly); lx, ly = lx / n, ly / n
        px, py = 0.10, -0.48                                     # an offset (in radii) on the lit side, off the highlight
        d = px * lx + py * ly; qx, qy = 2 * d * lx - px, 2 * d * ly - py
        return [(int(round(cx + px * R)), int(round(cy + py * R))), (int(round(cx + qx * R)), int(round(cy + qy * R)))]
    def answer(s): return 'grey.\nno %s in it.' % s.c['name']


# cast is not in rotation: on the first renders the middle ball simply looked grey (the filter did not fool the eye).
# It stays here to be tuned (docs/brain/backlog.md); CQ_KNOBS='{"kind":"cast"}' still draws it.
KINDS = {'munker': Munker, 'confetti': Confetti, 'contrast': Contrast, 'bezold': Bezold}
EXTRA = {'cast': Cast}


def hexof(px): return '#%02X%02X%02X' % tuple(int(v) for v in px)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir))
        t1 = min(t1, t0 + MAX_LEN)
        r = random.Random(seed)
        self.kind = K.pick('kind', sorted(KINDS), r, [3, 3, 1, 3])     # bezold, confetti, contrast (weakest on screen), munker
        kinds = dict(KINDS, **EXTRA)
        self.set = K.pick('set', sorted(kinds[self.kind].SETS), r)
        self.page_name = K.pick('page', ['dark', 'dark', 'light'], r)
        flip = K.flag('flip', 0.5, r)
        self.page = PAGES[self.page_name]
        a = audio.load(self.slug, t0, t1); n = a['n']
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.kick = audio.hits(a['kicks'], n, 7.0)
        B = [int(round(f)) for _, f in a['beats'] if 0 <= f < n]
        if len(B) < 12: print('not rendered: %.1f s is too short (%s)' % (t1 - t0, self.slug)); sys.exit(3)
        step = (B[-1] - B[0]) / max(1, len(B) - 1)
        u = max(1, int(math.ceil(12 / step)))                       # one move takes u beats (at least 0.4 s)

        def beat_at_or_after(f):
            nb = [b for b in B if b >= f]; return nb[0] if nb else None
        ask = beat_at_or_after(int(4.6 * FPS))                     # time to look and answer
        if ask is None: print('not rendered: too short to ask (%s)' % self.slug); sys.exit(3)
        i0 = B.index(ask)
        if i0 + 4 * u + 1 + 3 * u >= len(B): print('not rendered: %.1f s is too short to prove (%s)' % (t1 - t0, self.slug)); sys.exit(3)
        bt = lambda k: B[i0 + k]
        self.t_pick = (bt(0), bt(u)); self.t_slide = (bt(u), bt(2 * u)); self.t_ctx = (bt(2 * u), bt(3 * u))
        hold_end = beat_at_or_after(bt(3 * u) + int(2.4 * FPS))
        if hold_end is None or B.index(hold_end) + 2 * u >= len(B):
            print('not rendered: too short to hold the answer (%s)' % self.slug); sys.exit(3)
        j = B.index(hold_end)
        self.t_back = (B[j], B[j + u])
        end = B[j + u] + int(2.0 * FPS) + 9
        self.n = n = min(n, end)
        self.t0, self.t1 = t0, t0 + n / FPS
        self.ill = kinds[self.kind](r, flip, self.set)
        self.ask = self.ill.ask
        self.f_ask = font('Fraunces.ttf', 70); self.f_lab = font('DejaVuSansMono-Bold.ttf', 36)
        self.f_credit = font('DejaVuSansMono-Bold.ttf', 26)
        self._first = None

    def state(self, i):
        prog = lambda t: ease((i - t[0]) / max(1, t[1] - t[0]))
        back = prog(self.t_back)
        pick = prog(self.t_pick) - back
        slide = prog(self.t_slide) - back
        ctx = 1 - prog(self.t_ctx) + back
        cl = lambda v: min(max(v, 0.0), 1.0)
        return cl(ctx), cl(slide), cl(pick)

    def draw(self, i, top=True):
        img = np.empty((H, W, 3), np.uint8); img[:] = self.page['bg']
        ctx, slide, pick = self.state(i)
        pic = np.clip(np.rint(self.ill.picture(ctx)), 0, 255).astype(np.uint8)
        img[PY0:PY0 + PH] = pic
        pts = [(x, y + PY0) for x, y in self.ill.points()]
        cols = [tuple(int(v) for v in img[y, x]) for x, y in pts]    # read off the frame itself
        txt = self.page['txt']
        if pick > 0:
            # where each swatch sits: apart under its piece, then together, touching at the centre
            for k, ((px, py), col) in enumerate(zip(pts, cols)):
                apart = 300 if k == 0 else 780
                if self.ill.points()[0][0] > self.ill.points()[1][0]: apart = 780 if k == 0 else 300
                side = -1 if apart < 540 else 1
                tog = 540 + side * SW / 2
                sx = apart + (tog - apart) * ease(slide)
                # the swatch travels from the pixel down to its place and grows as it goes
                e = ease(pick); cx = px + (sx - px) * e; cy = py + (SY - py) * e; sz = 12 + (SW - 12) * e
                x0, y0, x1, y1 = int(cx - sz / 2), int(cy - sz / 2), int(cx + sz / 2), int(cy + sz / 2)
                cv2.rectangle(img, (x0, y0), (x1, y1), col, -1)
                if slide < 0.98:
                    cv2.rectangle(img, (x0 - 3, y0 - 3), (x1 + 3, y1 + 3), txt, 3)
            for (px, py) in pts:          # the eyedropper's mark on the pixel it read
                rr = int(18 + 6 * (1 - pick))
                cv2.circle(img, (px, py), rr, (0, 0, 0), 7, cv2.LINE_AA); cv2.circle(img, (px, py), rr, (255, 255, 255), 3, cv2.LINE_AA)
            if slide >= 0.98:
                cv2.rectangle(img, (int(540 - SW - 3), int(SY - SW / 2 - 3)), (int(540 + SW + 3), int(SY + SW / 2 + 3)), txt, 3)
        im = Image.fromarray(img); d = ImageDraw.Draw(im)
        if pick >= 1:
            for k, col in enumerate(cols):
                apart = 300 if (k == 0) == (self.ill.points()[0][0] < self.ill.points()[1][0]) else 780
                side = -1 if apart < 540 else 1
                x = apart + (540 + side * SW / 2 - apart) * ease(slide)
                if slide >= 0.98: x = 540 + side * (SW / 2 + 70)
                d.text((x, SY + SW / 2 + 36), hexof(col), font=self.f_lab, fill=txt, anchor='mm')
        if top:
            if i < self.t_pick[0]: t = self.ask
            elif i < self.t_back[0]: t = self.ill.answer() if i >= self.t_ctx[1] else self.ask
            else: t = BACK
            d.multiline_text((W / 2, 300), t, font=self.f_ask, fill=txt, anchor='mm', align='center', spacing=14)
            if i < self.t_pick[0]:     # a bar fills while you decide
                u = i / max(1, self.t_pick[0]); k = float(self.kick[min(i, len(self.kick) - 1)])
                x0, x1 = 340, 740; y = 420
                d.rounded_rectangle((x0, y - 5, x1, y + 5), 5, fill=self.page['dim'])
                d.rounded_rectangle((x0, y - 5 - 2 * k, x0 + (x1 - x0) * u, y + 5 + 2 * k), 5, fill=txt)
        d.text((W / 2, 1482), self.credit, font=self.f_credit, fill=self.page['dim'], anchor='mm')   # inside Instagram's safe area
        return np.asarray(im)

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
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', 'pick', self.t_pick, 'ctx', self.t_ctx, 'back', self.t_back); return
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
        rec = K.record(); rec['pictures'] = 'drawn in code (classic colour illusions; hex codes read off the frame)'
        json.dump(rec, open(out[:-4] + '.json', 'w')); print('done', out, rec['knobs'])


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 52.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
