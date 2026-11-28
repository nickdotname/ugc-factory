#!/usr/bin/env python3
"""Magic-eye pictures drawn in code, then solved on the beat (a ready page: hidden.in.dots, paused until its Instagram
account exists; see docs/brain/ready-pages.md).

    python studio/depth_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/depth_video.py SONG_DIR SEED SHEET.png --frames 0,200,330

An autostereogram: a strip of texture P pixels wide (periodic, so it has no seam), repeated across the frame, except
that wherever the hidden shape is, each pixel copies the one P - D*z to its left instead of P (z = the shape's height,
0..1). Look through the screen (the two dots become three) and the shape stands out of the page. Shapes are our own,
drawn in code: heart, star, moon, bolt, notes, ring, fish, house, digits.
  flat   the shape is one raised plane      round   the shape is a dome (height from its distance transform)
The question holds ~6 s with a filling bar (and the guide dots). Then on the beat a copy of the picture slides exactly
one repeat (P px) to the right: everything that repeats now lies on itself, so the difference between the two copies is
exactly zero there, and only the hidden shape is left (it is the one place that does not repeat at P). The page goes dark
except the shape, the answer is named, then the picture comes back ('now look again.'). The proof is real: the reveal is
|picture - picture shifted by P|, nothing else. No polish pass (grain would break the cancellation).
Choreographed in beats; a stretch too short exits 3. The last 9 frames fade into frame 0.
Knobs (studio/knobs.py): shape (the nightly subject), kind (flat, round), texture (confetti, reef, ember, moss, mono),
repeat (P: 112, 120, 128), pulse (the shape's height breathes on the kicks: off 2:1 on).
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
Y0, Y1 = 480, 1560                       # the picture's band (the question sits above, the credit below)
HS = Y1 - Y0

TEXTURES = {   # four or five colours each; the last is the band colour above and below the picture
    'confetti': [(238, 64, 84), (255, 196, 54), (58, 170, 226), (120, 206, 112), (250, 246, 236), (24, 22, 30)],
    'reef':     [(16, 92, 120), (34, 170, 178), (250, 128, 104), (244, 226, 196), (8, 40, 60), (10, 26, 38)],
    'ember':    [(120, 20, 22), (220, 70, 30), (252, 170, 60), (250, 232, 180), (40, 10, 14), (22, 10, 12)],
    'moss':     [(36, 72, 40), (98, 146, 66), (196, 214, 120), (240, 236, 210), (18, 36, 22), (14, 22, 16)],
    'mono':     [(12, 12, 12), (90, 90, 90), (180, 180, 180), (250, 250, 250), (40, 40, 40), (16, 16, 16)],
}
SHAPES = ['heart', 'star', 'moon', 'bolt', 'notes', 'ring', 'fish', 'house', '7', '3', '8', '5']
ANSWER = {'heart': 'a heart.', 'star': 'a star.', 'moon': 'a crescent moon.', 'bolt': 'a lightning bolt.',
          'notes': 'two music notes.', 'ring': 'a ring.', 'fish': 'a fish.', 'house': 'a house.'}
ASK = ["what's hidden\nin here?", 'can you see it?', "what's in\nthe dots?", 'what does\nthis hide?']
ASK_DIGIT = ['what number\nis hidden?', 'which number\ncan you see?']
HINT = 'look through the screen until\nthe two dots become three'
SLIDE = 'slide a copy exactly\none repeat over (%d px)'
CANCEL = 'everything that repeats\ncancels out.'
AGAIN = 'now look again.'


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)


# ---------------------------------------------------------------- the hidden shape
def shape_mask(name, cx, cy, s):
    """A 0/1 mask of the band (HS x W) with the shape centred at (cx, cy), about s px across."""
    im = Image.new('L', (W, HS), 0); d = ImageDraw.Draw(im)
    if name == 'heart':
        t = np.linspace(0, 2 * np.pi, 400)
        x = 16 * np.sin(t) ** 3; y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
        k = s / 34.0; d.polygon(list(zip(cx + k * x, cy + k * (y + 1))), fill=255)
    elif name == 'star':
        pts = []
        for j in range(10):
            a = -np.pi / 2 + j * np.pi / 5; r = s / 2 if j % 2 == 0 else s * 0.21
            pts.append((cx + r * np.cos(a), cy + 0.04 * s + r * np.sin(a)))
        d.polygon(pts, fill=255)
    elif name == 'moon':
        r = s * 0.46; d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        o = s * 0.24; r2 = r * 0.86; d.ellipse((cx - r2 + o, cy - r2 - o * 0.5, cx + r2 + o, cy + r2 - o * 0.5), fill=0)
    elif name == 'bolt':
        P = [(0.10, -0.50), (-0.28, 0.06), (-0.02, 0.06), (-0.14, 0.50), (0.30, -0.10), (0.04, -0.10), (0.20, -0.50)]
        d.polygon([(cx + s * x, cy + s * y) for x, y in P], fill=255)
    elif name == 'notes':
        r = s * 0.13; lw = int(s * 0.06)
        for hx in (-0.25, 0.25):
            x0, y0 = cx + s * hx, cy + s * (0.30 if hx < 0 else 0.22)
            d.ellipse((x0 - r * 1.25, y0 - r, x0 + r * 1.25, y0 + r), fill=255)
            d.rectangle((x0 + r * 1.25 - lw, y0 - s * 0.62, x0 + r * 1.25, y0), fill=255)
        xa, xb = cx - s * 0.25 + r * 1.25, cx + s * 0.25 + r * 1.25
        d.polygon([(xa - lw, cy - s * 0.32), (xb, cy - s * 0.40), (xb, cy - s * 0.27), (xa - lw, cy - s * 0.19)], fill=255)
    elif name == 'ring':
        r = s * 0.46; d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        r2 = r * 0.55; d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), fill=0)
    elif name == 'fish':
        d.ellipse((cx - s * 0.42, cy - s * 0.24, cx + s * 0.22, cy + s * 0.24), fill=255)
        d.polygon([(cx + s * 0.14, cy), (cx + s * 0.50, cy - s * 0.26), (cx + s * 0.50, cy + s * 0.26)], fill=255)
        e = s * 0.045; d.ellipse((cx - s * 0.27 - e, cy - s * 0.07 - e, cx - s * 0.27 + e, cy - s * 0.07 + e), fill=0)
    elif name == 'house':
        d.rectangle((cx - s * 0.32, cy - s * 0.06, cx + s * 0.32, cy + s * 0.46), fill=255)
        d.polygon([(cx - s * 0.46, cy - s * 0.04), (cx, cy - s * 0.48), (cx + s * 0.46, cy - s * 0.04)], fill=255)
        d.rectangle((cx - s * 0.08, cy + s * 0.18, cx + s * 0.08, cy + s * 0.46), fill=0)
    else:   # a digit
        f = font('Anton-Regular.ttf', int(s * 1.05))
        d.text((cx, cy), name, font=f, fill=255, anchor='mm')
    return (np.asarray(im) > 127).astype(np.float32)


def height(mask, kind):
    if kind == 'flat':
        return cv2.GaussianBlur(mask, (0, 0), 1.2)
    dist = cv2.distanceTransform((mask > 0.5).astype(np.uint8), cv2.DIST_L2, 5)
    R = max(1.0, float(dist.max()))
    return np.sqrt(np.clip(dist / R, 0, 1)).astype(np.float32)


# ---------------------------------------------------------------- the picture
def texture(colours, P, rng):
    """A HS x P strip, periodic left to right (no seam where it repeats): two layers of FFT noise mapped to colours."""
    def noise(scale):
        F = np.fft.fft2(rng.standard_normal((HS, P)))
        fy = np.fft.fftfreq(HS)[:, None]; fx = np.fft.fftfreq(P)[None, :]
        f = np.sqrt(fx ** 2 + fy ** 2) * scale
        return np.real(np.fft.ifft2(F * np.exp(-f ** 2)))
    a = noise(26.0); b = noise(7.0)
    cols = np.array(colours[:4], np.float32)
    q = np.searchsorted(np.percentile(a, [30, 55, 78]), a)           # four colours in blobs
    img = cols[q]
    sp = b > np.percentile(b, 88)                                     # and a finer speckle on top
    img[sp] = cols[(q[sp] + 2) % 4]
    return img.astype(np.uint8)


def stereogram(z, tex, P, D):
    """Each pixel copies the one sep = P - D*z to its left; the first P columns are the strip itself."""
    sep = P - np.round(D * z).astype(np.int32)
    out = np.empty((HS, W, 3), np.uint8); out[:, :P] = tex
    rows = np.arange(HS)
    for x in range(P, W):
        out[:, x] = out[rows, x - sep[:, x]]
    return out


def shifted(S, off):
    """S moved off px to the right; the columns it leaves are S itself (so they cancel)."""
    if off <= 0: return S
    o = S.copy(); o[:, off:] = S[:, :-off]; return o


# ---------------------------------------------------------------- the video
class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.seed = seed
        self.slug = os.path.basename(os.path.normpath(song_dir))
        t1 = min(t1, t0 + MAX_LEN)
        r = random.Random(seed)
        self.shape = K.pick('shape', SHAPES, r)
        self.kind = K.pick('kind', ['flat', 'round'], r)
        self.tex_name = K.pick('texture', sorted(TEXTURES), r)
        self.P = K.pick('repeat', [112, 120, 128], r)
        self.pulse = K.pick('pulse', ['off', 'off', 'on'], r) == 'on'
        self.cols = TEXTURES[self.tex_name]
        self.D = round(self.P * 0.2)
        digit = self.shape.isdigit()
        self.ask = r.choice(ASK_DIGIT if digit else ASK)
        self.answer = ('the number %s.' % self.shape) if digit else ANSWER[self.shape]
        rng = np.random.default_rng(seed)
        self.tex = texture(self.cols, self.P, rng)
        self.z = height(shape_mask(self.shape, W // 2 + 30, HS // 2, 560), self.kind)
        self.S = stereogram(self.z, self.tex, self.P, self.D)
        a = audio.load(self.slug, t0, t1); n = a['n']
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.kick = audio.hits(a['kicks'], n, 7.0)
        B = [int(round(f)) for _, f in a['beats'] if 0 <= f < n]
        if len(B) < 16: print('not rendered: %.1f s is too short (%s)' % (t1 - t0, self.slug)); sys.exit(3)
        step = (B[-1] - B[0]) / max(1, len(B) - 1)
        u = max(1, int(math.ceil(12 / step)))                       # one move takes at least 0.4 s

        def at_or_after(f):
            nb = [b for b in B if b >= f]; return nb[0] if nb else None
        go = at_or_after(int(6.0 * FPS))
        if go is None or B.index(go) + 4 * u >= len(B): print('not rendered: too short to slide (%s)' % self.slug); sys.exit(3)
        i0 = B.index(go)
        self.t_slide = (B[i0], B[i0 + 3 * u])                       # the copy slides one repeat in three moves
        self.t_dark = (B[i0 + 3 * u], B[i0 + 4 * u])                # then the page goes dark but the shape
        back = at_or_after(self.t_dark[1] + int(3.0 * FPS))
        if back is None or B.index(back) + 2 * u >= len(B): print('not rendered: too short to come back (%s)' % self.slug); sys.exit(3)
        j = B.index(back)
        self.t_back = (B[j], B[j + 2 * u])
        self.n = n = min(n, self.t_back[1] + int(2.0 * FPS) + 9)
        self.t0, self.t1 = t0, t0 + n / FPS
        # the reveal, computed once: where the picture and its copy one repeat over differ
        diff = np.abs(self.S.astype(np.int16) - shifted(self.S, self.P).astype(np.int16)).max(2).astype(np.float32)
        self.cancel_zero = float(diff[self.z < 1e-3].max()) if (self.z < 1e-3).any() else 0.0   # 0: it really cancels
        m = cv2.boxFilter((diff > 0).astype(np.float32), -1, (13, 13))
        self.reveal = np.clip(m / 0.45, 0, 1)[..., None]
        self.f_ask = font('Fraunces.ttf', 72); self.f_hint = font('Figtree.ttf', 38)
        self.f_ans = font('Fraunces.ttf', 84); self.f_credit = font('DejaVuSansMono-Bold.ttf', 26)
        self._first = None

    def picture(self, i):
        if not self.pulse or i >= self.t_slide[0]: return self.S
        k = float(self.kick[min(i, len(self.kick) - 1)])
        return stereogram(self.z * (0.82 + 0.18 * k), self.tex, self.P, self.D)

    def draw(self, i, top=True):
        band = np.array(self.cols[5], np.float32)
        img = np.empty((H, W, 3), np.float32); img[:] = band
        S = self.picture(i).astype(np.float32)
        p = lambda t: ease((i - t[0]) / max(1, t[1] - t[0]))
        slide, dark, back = p(self.t_slide), p(self.t_dark), p(self.t_back)
        off = int(round(self.P * slide)) if back < 1 else 0
        pic = S
        if slide > 0 and back < 1:
            Sh = shifted(S, off)
            blend = 0.5 * S + 0.5 * Sh                               # the copy sliding over the picture
            lit = S * (0.08 + 0.92 * self.reveal)                     # only what does not repeat stays lit
            v = blend * (1 - dark) + lit * dark
            pic = v * (1 - back) + S * back
        img[Y0:Y1] = pic
        im = Image.fromarray(img.astype(np.uint8)); d = ImageDraw.Draw(im)
        txt = (246, 244, 238); dim = tuple(int(c * 0.75 + b * 0.25) for c, b in zip(txt, self.cols[5]))
        showing_dots = i < self.t_slide[0] or i >= (self.t_back[0] + self.t_back[1]) // 2
        if top:
            if i < self.t_slide[0]:
                d.multiline_text((W / 2, 205), self.ask, font=self.f_ask, fill=txt, anchor='mm', align='center', spacing=10)
                d.multiline_text((W / 2, 340), HINT, font=self.f_hint, fill=dim, anchor='mm', align='center', spacing=6)
            elif i < self.t_dark[0]:
                d.multiline_text((W / 2, 250), SLIDE % self.P, font=self.f_ask, fill=txt, anchor='mm', align='center', spacing=10)
            elif i < self.t_back[0]:
                ans = i >= self.t_dark[1] + int(0.8 * FPS)
                d.multiline_text((W / 2, 250), self.answer if ans else CANCEL, font=self.f_ans if ans else self.f_ask,
                                 fill=txt, anchor='mm', align='center', spacing=10)
            else:
                d.text((W / 2, 230), AGAIN, font=self.f_ask, fill=txt, anchor='mm')
            if showing_dots:                                          # two dots one repeat apart: the viewing aid
                for x in (W / 2 - self.P / 2, W / 2 + self.P / 2):
                    d.ellipse((x - 11, 430 - 11, x + 11, 430 + 11), fill=txt)
            if i < self.t_slide[0]:                                   # a bar fills while you look
                u = i / max(1, self.t_slide[0]); k = float(self.kick[min(i, len(self.kick) - 1)])
                x0, x1 = 340, 740; y = 1600
                d.rounded_rectangle((x0, y - 5, x1, y + 5), 5, fill=tuple(int(c * 0.2 + b * 0.8) for c, b in zip(txt, self.cols[5])))
                d.rounded_rectangle((x0, y - 5 - 2 * k, x0 + (x1 - x0) * u, y + 5 + 2 * k), 5, fill=self.cols[1] if self.tex_name != 'mono' else txt)
        d.text((W / 2, 1650), self.credit, font=self.f_credit, fill=dim, anchor='mm')
        return np.asarray(im)

    def frame(self, i):
        tail = 9; o = self.draw(i, top=i < self.n - tail - 4)
        if i >= self.n - tail:
            if self._first is None: self._first = self.draw(0).astype(np.float32)
            a = (i - (self.n - tail) + 1) / (tail + 1)
            o = (o.astype(np.float32) * (1 - a) + self._first * a).astype(np.uint8)
        return o

    def render(self, out):
        print('cancels outside the shape: max diff %.0f (must be 0)' % self.cancel_zero)
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', 'slide', self.t_slide, 'dark', self.t_dark, 'back', self.t_back); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '18'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 60 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        rec = K.record(); rec['pictures'] = 'drawn in code (autostereograms of our own shapes)'
        json.dump(rec, open(out[:-4] + '.json', 'w')); print('done', out, rec['knobs'])


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 52.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
