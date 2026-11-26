#!/usr/bin/env python3
"""Classic size, straightness and brightness illusions, asked and then measured on the beat (a ready page:
ruler.says.no, paused until its Instagram account exists; see docs/brain/ready-pages.md).

    python studio/measure_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/measure_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

Every picture is drawn in code. A video is one illusion:
  mullerlyer  two equal lines, one with fins out, one with fins in          "which line is longer?"
  ebbinghaus  two equal orange discs, one ringed by big discs, one by small  "which orange circle is bigger?"
  ponzo       two equal bars between converging rails                        "which bar is longer?"
  jastrow     two identical curved tiles, one above the other                "which shape is bigger?"
  cafewall    rows of black and white tiles, every other row shifted         "are the grey lines straight?"
  hering      two parallel red lines over a fan of rays                      "are the red lines straight?"
  grey        two squares of the same grey on a dark-to-light ground         "which square is darker?"
The question holds for a few seconds (a bar fills under it), then on the beat the surroundings fade, the pieces slide
together and a ruler measures them: the numbers shown are read off the drawing itself (lengths in pixels of this
1080 x 1920 frame, the grey's RGB value). Then the surroundings come back ("measured. still looks wrong.") and the
last 9 frames fade into frame 0. Choreographed in beats; a stretch too short exits 3.
Knobs (studio/knobs.py): kind, palette (paper, chalk, blueprint), flip (which piece is on top / left).
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
SH = 4; SC = 1 << SH                        # cv2 sub-pixel shift for smooth motion

PALETTES = {   # ground, ink, accent (the pieces being compared), ruler
    'paper':     dict(bg=(240, 234, 220), ink=(28, 28, 32), acc=(226, 96, 40), rule=(30, 110, 200), txt=(28, 28, 32)),
    'chalk':     dict(bg=(30, 34, 36), ink=(236, 236, 228), acc=(250, 150, 60), rule=(250, 214, 80), txt=(240, 240, 232)),
    'blueprint': dict(bg=(22, 52, 104), ink=(226, 236, 250), acc=(255, 170, 70), rule=(250, 226, 110), txt=(236, 242, 252)),
}
ASK = {'mullerlyer': 'which line is longer?', 'ebbinghaus': 'which orange circle\nis bigger?', 'ponzo': 'which bar is longer?',
       'jastrow': 'which shape is bigger?', 'cafewall': 'are the grey lines\nstraight?', 'hering': 'are the red lines\nstraight?',
       'grey': 'which square is darker?'}
BACK = 'measured.\nstill looks wrong.'


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)


def P(x, y): return (int(round(x * SC)), int(round(y * SC)))


def line(img, a, b, col, w):
    cv2.line(img, P(*a), P(*b), col, int(w), cv2.LINE_AA, SH)


def disc(img, c, r, col):
    cv2.circle(img, P(*c), int(round(r * SC)), col, -1, cv2.LINE_AA, SH)


def ring(img, c, r, col, w):
    cv2.circle(img, P(*c), int(round(r * SC)), col, int(w), cv2.LINE_AA, SH)


def poly(img, pts, col):
    cv2.fillPoly(img, [np.array([P(x, y) for x, y in pts], np.int32)], col, cv2.LINE_AA, SH)


def ruler(img, a, b, col, s, ticks=10):
    """A measuring line from a to b, drawn out to fraction s, with end stops and ticks."""
    if s <= 0: return
    ax, ay = a; bx, by = b; ex, ey = ax + (bx - ax) * s, ay + (by - ay) * s
    L = math.hypot(bx - ax, by - ay) or 1; nx, ny = -(by - ay) / L, (bx - ax) / L
    line(img, (ax, ay), (ex, ey), col, 4)
    for k in range(ticks + 1):
        u = k / ticks
        if u > s + 1e-6: break
        tx, ty = ax + (bx - ax) * u, ay + (by - ay) * u; h = 22 if k in (0, ticks) else 11
        line(img, (tx - nx * h, ty - ny * h), (tx + nx * h, ty + ny * h), col, 4 if k in (0, ticks) else 3)


# ---- the illusions. Each: setup(r, flip) and draw(img, ctx, slide, meas) -> list of (text, x, y) labels.
# ctx: how much of the surroundings is shown (1 = all); slide: 0 = pieces apart, 1 = put together; meas: ruler 0..1.
class MullerLyer:
    def __init__(s, r, flip, pal):
        s.L = r.choice([400, 440, 480]); s.pal = pal; s.fin = r.choice([105, 120]); s.ang = math.radians(r.choice([35, 40]))
        s.ya, s.yb = (820, 1240) if not flip else (1240, 820); s.x0 = (W - s.L) / 2
    def pieces(s, slide):
        yb = s.yb + (s.ya + (190 if s.yb > s.ya else -190) - s.yb) * slide
        return [(s.ya, 'out'), (yb, 'in')]
    def draw(s, img, ctx, slide, meas, base):
        for y, kind in s.pieces(slide):
            a, b = (s.x0, y), (s.x0 + s.L, y)
            if ctx > 0:
                lay = img.copy()
                for x, sg in ((a[0], -1), (b[0], 1)):
                    d = sg if kind == 'out' else -sg       # fins open outward (out) or point in (in)
                    for vy in (-1, 1):
                        line(lay, (x, y), (x + d * s.fin * math.cos(s.ang), y + vy * s.fin * math.sin(s.ang)), s.pal['ink'], 7)
                img[:] = (img * (1 - ctx) + lay * ctx).astype(np.uint8)
            line(img, a, b, s.pal['acc'], 11)
        labs = []
        if meas > 0:
            ys = [y for y, _ in s.pieces(slide)]
            for x in (s.x0, s.x0 + s.L):
                line(img, (x, min(ys) - 60), (x, min(ys) - 60 + (max(ys) - min(ys) + 120) * ease(meas)), s.pal['rule'], 3)
            for y in ys:
                ruler(img, (s.x0, y + 40), (s.x0 + s.L, y + 40), s.pal['rule'], ease(meas))
                if meas >= 1: labs.append(('%d px' % s.L, W / 2, y + 95))
        return labs
    def answer(s): return 'the same length.'


class Ebbinghaus:
    def __init__(s, r, flip, pal):
        s.pal = pal; s.R = r.choice([52, 58, 64]); s.big = (s.R * 1.5, s.R * 3.0, 6); s.small = (s.R * 0.42, s.R * 1.75, 8)
        s.ca, s.cb = ((540, 770), (540, 1240)) if not flip else ((540, 1240), (540, 770))
    def draw(s, img, ctx, slide, meas, base):
        cb = (s.cb[0], s.cb[1] + (s.ca[1] - s.cb[1]) * slide)
        if ctx > 0:
            lay = img.copy()
            for c, (rr, dist, n) in ((s.ca, s.big), (s.cb, s.small)):
                for k in range(n):
                    a = 2 * math.pi * k / n + math.pi / 2
                    disc(lay, (c[0] + dist * math.cos(a), c[1] + dist * math.sin(a)), rr, s.pal['ink'])
            img[:] = (img * (1 - ctx) + lay * ctx).astype(np.uint8)
        disc(img, s.ca, s.R, s.pal['acc'])
        if slide > 0.999: ring(img, s.ca, s.R, s.pal['rule'], 4)
        else: disc(img, cb, s.R, s.pal['acc'])
        labs = []
        if meas > 0:
            for c in ([s.ca] if slide > 0.999 else [s.ca, cb]):
                ruler(img, (c[0] - s.R, c[1]), (c[0] + s.R, c[1]), s.pal['rule'], ease(meas), ticks=4)
                if meas >= 1: labs.append(('%d px across' % (2 * s.R), W / 2, c[1] + s.R + 50))
        return labs
    def answer(s): return 'the same size.'


class Ponzo:
    def __init__(s, r, flip, pal):
        s.pal = pal; s.L = r.choice([220, 250, 280]); s.vy = 470; s.top, s.bot = 700, 1320; s.flip = flip
    def rails_x(s, y, side):
        # rails from the bottom corners (x 160 / 920 at y 1500) to the vanishing point (540, vy)
        u = (y - s.vy) / (1500 - s.vy); return 540 + side * 380 * u
    def draw(s, img, ctx, slide, meas, base):
        yb = s.bot + (s.top + 120 - s.bot) * slide
        if ctx > 0:
            lay = img.copy()
            for side in (-1, 1): line(lay, (540, s.vy), (s.rails_x(1500, side), 1500), s.pal['ink'], 8)
            # sleepers between the rails, closer together further away
            for k in range(1, 14):
                y = s.vy + (1500 - s.vy) * (k / 14) ** 1.6
                line(lay, (s.rails_x(y, -1) - 18, y), (s.rails_x(y, 1) + 18, y), tuple(int(c * 0.55 + b * 0.45) for c, b in zip(s.pal['ink'], s.pal['bg'])), 3)
            img[:] = (img * (1 - ctx) + lay * ctx).astype(np.uint8)
        x0 = (W - s.L) / 2
        for y in (s.top, yb): line(img, (x0, y), (x0 + s.L, y), s.pal['acc'], 16)
        labs = []
        if meas > 0:
            for x in (x0, x0 + s.L):
                line(img, (x, s.top - 50), (x, s.top - 50 + (yb - s.top + 100) * ease(meas)), s.pal['rule'], 3)
            for y in (s.top, yb):
                ruler(img, (x0, y + 32), (x0 + s.L, y + 32), s.pal['rule'], ease(meas), ticks=5)
                if meas >= 1: labs.append(('%d px' % s.L, W / 2, y + 78))
        return labs
    def answer(s): return 'the same length.'


class Jastrow:
    def __init__(s, r, flip, pal):
        s.pal = pal; s.R1, s.R2 = 520, 700; s.span = math.radians(r.choice([46, 52]))
        s.dy = r.choice([200, 220]); s.cy0 = 1500; s.flip = flip
    def shape(s, cx, cy):
        a0 = -math.pi / 2 - s.span / 2; pts = []
        for k in range(33): a = a0 + s.span * k / 32; pts.append((cx + s.R2 * math.cos(a), cy + s.R2 * math.sin(a)))
        for k in range(32, -1, -1): a = a0 + s.span * k / 32; pts.append((cx + s.R1 * math.cos(a), cy + s.R1 * math.sin(a)))
        return pts
    def draw(s, img, ctx, slide, meas, base):
        # tile A on top, B a little below (its short top edge sits next to A's long bottom edge); B slides up onto A
        ya, yb = s.cy0, s.cy0 + s.dy
        yb2 = yb + (ya - yb) * slide
        ca, cb = (s.pal['acc'], s.pal['ink']) if not s.flip else (s.pal['ink'], s.pal['acc'])
        poly(img, s.shape(540, ya), ca)
        if slide > 0:
            lay = img.copy(); poly(lay, s.shape(540, yb2), cb)
            a = 0.55 if slide > 0.999 else 1.0
            img[:] = (img * (1 - a) + lay * a).astype(np.uint8)
            if slide > 0.999: cv2.polylines(img, [np.array([P(x, y) for x, y in s.shape(540, ya)], np.int32)], True, s.pal['rule'], 4, cv2.LINE_AA, SH)
        else:
            poly(img, s.shape(540, yb2), cb)
        labs = []
        if meas >= 1: labs.append(('one fits exactly on the other', W / 2, ya - s.R1 + 70))
        return labs
    def answer(s): return 'the same shape.\nthe same size.'


class CafeWall:
    def __init__(s, r, flip, pal):
        s.pal = pal; s.t = r.choice([90, 108]); s.rows = 9 if s.t == 90 else 8; s.m = 6; s.y0 = 560; s.ph = r.choice([0.25, 0.33])
        s.mortar = (128, 128, 128)
    def draw(s, img, ctx, slide, meas, base):
        # ctx 1 -> 0 straightens the wall: each row's shift goes to zero. slide is unused.
        t, m = s.t, s.m
        cv2.rectangle(img, (0, s.y0 - m), (W, s.y0 + s.rows * (t + m)), s.mortar, -1)
        for row in range(s.rows):
            y = s.y0 + row * (t + m)
            sh = (s.ph * t * (row % 4 if row % 4 < 3 else 1)) * ctx       # 0, 1, 2, 1, 0, ... quarters of a tile
            x = -2 * t + sh
            k = 0
            while x < W + t:
                if k % 2 == 0: cv2.rectangle(img, P(x, y), P(x + t, y + t), (16, 16, 16), -1, cv2.LINE_AA, SH)
                else: cv2.rectangle(img, P(x, y), P(x + t, y + t), (250, 250, 250), -1, cv2.LINE_AA, SH)
                x += t; k += 1
        if meas > 0:
            for row in range(1, s.rows):
                y = s.y0 + row * (t + m) - m / 2
                line(img, (0, y), (W * ease(meas), y), s.pal['rule'], 2)
        return [('every grey line: perfectly level', W / 2, s.y0 + s.rows * (t + m) + 60)] if meas >= 1 else []
    def answer(s): return 'all straight.\nall parallel.'
    still = True


class Hering:
    def __init__(s, r, flip, pal):
        s.pal = pal; s.gap = r.choice([200, 240]); s.n = r.choice([28, 36]); s.cy = 1000
    def draw(s, img, ctx, slide, meas, base):
        if ctx > 0:
            lay = img.copy()
            for k in range(s.n):
                a = math.pi * k / s.n
                dx, dy = math.cos(a) * 1400, math.sin(a) * 1400
                cx, cy = math.cos(a), math.sin(a)
                for sg in (-1, 1): line(lay, (540 + sg * 46 * cx, s.cy + sg * 46 * cy), (540 + sg * dx, s.cy + sg * dy), s.pal['ink'], 3)
            m = np.zeros(img.shape[:2], np.uint8); cv2.rectangle(m, (0, 520), (W, 1480), 1, -1)
            lay = np.where(m[..., None] > 0, lay, img)
            img[:] = (img * (1 - ctx) + lay * ctx).astype(np.uint8)
        red = (220, 40, 40)
        xs = [540 - s.gap / 2, 540 + s.gap / 2]
        for x in xs: line(img, (x, 560), (x, 1440), red, 9)
        if meas > 0:
            for x in xs:
                line(img, (x + 28, 560), (x + 28, 560 + 880 * ease(meas)), s.pal['rule'], 4)
        return [('%d px apart, top to bottom' % s.gap, W / 2, 1500)] if meas >= 1 else []
    def answer(s): return 'straight.\nand parallel.'


class Grey:
    def __init__(s, r, flip, pal):
        s.pal = pal; s.v = r.choice([118, 128, 138]); s.sz = r.choice([190, 220]); s.flip = flip
        g = np.linspace(8, 248, W) if not flip else np.linspace(248, 8, W)
        s.grad = np.repeat(np.repeat(g[None, :, None], 900, 0), 3, 2).astype(np.float32)
    def draw(s, img, ctx, slide, meas, base):
        y0 = 560
        flat = np.full_like(s.grad, 58.0)
        img[y0:y0 + 900] = (s.grad * ctx + flat * (1 - ctx)).astype(np.uint8)
        c = (s.v,) * 3; yc = y0 + 450
        xa, xb = 250, 830
        cv2.rectangle(img, (int(xa - s.sz / 2), int(yc - s.sz / 2)), (int(xa + s.sz / 2), int(yc + s.sz / 2)), c, -1)
        cv2.rectangle(img, (int(xb - s.sz / 2), int(yc - s.sz / 2)), (int(xb + s.sz / 2), int(yc + s.sz / 2)), c, -1)
        if slide > 0:   # a bridge of the same grey grows from one square to the other
            w = (xb - xa) * ease(slide)
            cv2.rectangle(img, (int(xa), int(yc - 22)), (int(xa + w), int(yc + 22)), c, -1)
        labs = []
        if meas >= 1:
            # read the value back off the frame itself
            va = int(img[int(yc), int(xa)][0]); vb = int(img[int(yc), int(xb)][0])
            labs += [('rgb %d' % va, xa, yc + s.sz / 2 + 50), ('rgb %d' % vb, xb, yc + s.sz / 2 + 50)]
        return labs
    def answer(s): return 'the same grey.'


KINDS = {'mullerlyer': MullerLyer, 'ebbinghaus': Ebbinghaus, 'ponzo': Ponzo, 'jastrow': Jastrow, 'cafewall': CafeWall,
         'hering': Hering, 'grey': Grey}


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir))
        t1 = min(t1, t0 + MAX_LEN)
        r = random.Random(seed)
        self.kind = K.pick('kind', sorted(KINDS), r)
        self.pal_name = K.pick('palette', ['paper', 'chalk', 'chalk', 'blueprint'], r)
        flip = K.flag('flip', 0.5, r)
        pal = PALETTES[self.pal_name]; self.pal = pal
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
        need = i0 + 4 * u + 1
        if need + 3 * u >= len(B): print('not rendered: %.1f s is too short to measure (%s)' % (t1 - t0, self.slug)); sys.exit(3)
        bt = lambda k: B[i0 + k]
        self.t_ctx = (bt(0), bt(u)); self.t_slide = (bt(u), bt(2 * u)); self.t_meas = (bt(2 * u), bt(3 * u))
        hold_end = beat_at_or_after(bt(3 * u) + int(2.2 * FPS))
        if hold_end is None or B.index(hold_end) + 2 * u >= len(B):
            print('not rendered: too short to hold the answer (%s)' % self.slug); sys.exit(3)
        j = B.index(hold_end)
        self.t_back = (B[j], B[j + u]); self.t_unslide = (B[j], B[j + u])
        end = B[j + u] + int(2.0 * FPS) + 9
        self.n = n = min(n, end)
        self.t0, self.t1 = t0, t0 + n / FPS
        self.ill = KINDS[self.kind](r, flip, pal)
        self.f_ask = font('Fraunces.ttf', 70); self.f_lab = font('DejaVuSansMono-Bold.ttf', 34)
        self.f_credit = font('DejaVuSansMono-Bold.ttf', 26)
        self._first = None

    def state(self, i):
        prog = lambda t: ease((i - t[0]) / max(1, t[1] - t[0]))
        back = prog(self.t_back)
        ctx = 1 - prog(self.t_ctx) + back
        slide = prog(self.t_slide) - prog(self.t_unslide)
        meas = 0.0 if i >= self.t_back[0] else (i - self.t_meas[0]) / max(1, self.t_meas[1] - self.t_meas[0])
        return min(max(ctx, 0), 1), min(max(slide, 0), 1), min(max(meas, 0), 1)

    def draw(self, i, top=True):
        img = np.empty((H, W, 3), np.uint8); img[:] = self.pal['bg']
        ctx, slide, meas = self.state(i)
        labs = self.ill.draw(img, ctx, slide, meas, None)
        im = Image.fromarray(img); d = ImageDraw.Draw(im); txt = self.pal['txt']
        if top:
            if i < self.t_ctx[0]: t = ASK[self.kind]
            elif i < self.t_back[0]: t = self.ill.answer() if i >= self.t_meas[1] else ASK[self.kind]
            else: t = BACK
            d.multiline_text((W / 2, 300), t, font=self.f_ask, fill=txt, anchor='mm', align='center', spacing=14)
            if i < self.t_ctx[0]:     # a bar fills while you decide
                u = i / max(1, self.t_ctx[0]); k = float(self.kick[min(i, len(self.kick) - 1)])
                x0, x1 = 340, 740; y = 410
                d.rounded_rectangle((x0, y - 5, x1, y + 5), 5, fill=tuple(int(c * 0.3 + b * 0.7) for c, b in zip(txt, self.pal['bg'])))
                d.rounded_rectangle((x0, y - 5 - 2 * k, x0 + (x1 - x0) * u, y + 5 + 2 * k), 5, fill=self.pal['acc'])
        for t, x, y in labs:
            d.text((x, y), t, font=self.f_lab, fill=(245, 245, 245) if self.kind == 'grey' else self.pal['rule'] if self.kind not in ('cafewall', 'hering') else txt, anchor='mm',
                   stroke_width=3, stroke_fill=self.pal['bg'] if self.kind != 'grey' else (40, 40, 40))
        d.text((W / 2, 1590), self.credit, font=self.f_credit, fill=tuple(int(c * 0.65 + b * 0.35) for c, b in zip(txt, self.pal['bg'])), anchor='mm')
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
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', 'ask', self.t_ctx[0], 'meas', self.t_meas, 'back', self.t_back); return
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
        rec = K.record(); rec['pictures'] = 'drawn in code (classic illusions, measured)'
        json.dump(rec, open(out[:-4] + '.json', 'w')); print('done', out, rec['knobs'])


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 52.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
