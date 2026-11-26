"""ASCII art that moves to the music, with the code that draws it underneath (the ASCII account).

A scene (planet.py, boulder.py, jelly.py) supplies a signed distance field, its shading and the code shown in the
panel; this raymarches it once per character cell (66 x 120 cells), turns brightness into letters (and edges into
/ | \\ -), colours them, and lays out the frame: art on top, a stats line, the lyric being "printed", and the code
scrolling in an editor panel. Everything moves with the stems: kicks swell shapes, snares throw sparks, the bass
and the vocal drive the glow. Every look choice is a knob (studio/knobs.py) so the learner can tell what works.
"""
import json, math, os, re, subprocess, sys, importlib, random
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); STUDIO = os.path.dirname(HERE); REPO = os.path.dirname(STUDIO)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(STUDIO, 'mathviz')); sys.path.insert(0, STUDIO)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30
CW, CH = 9, 17; ROWS = 66; COLS = W // CW
CCW, CCH, CROWS = 10, 18, 66          # the colour scenes: 108 x 66 bold letters, each one big enough to read on a phone

def _font(*names):
    roots = [os.path.join(REPO, 'fonts'), '/usr/share/fonts', '/Library/Fonts', os.path.expanduser('~/Library/Fonts')]
    for n in names:
        for r in roots:
            if os.path.exists(os.path.join(r, n)): return os.path.join(r, n)
            for d, _, fs in os.walk(r) if os.path.isdir(r) else ():
                if n in fs: return os.path.join(d, n)
    raise SystemExit('no font: %s' % (names,))
MONO = _font('DejaVuSansMono.ttf', 'DejaVuSansMono-Bold.ttf')
BOLD = _font('DejaVuSansMono-Bold.ttf', 'DejaVuSansMono.ttf')

RAMPS = {'classic': " .:;i!tjrxnuzcvXUJCLQ0OZqpdbkhao*#W&8%B@$",
         'dense': " .'`^\",:;Il!i><~+_-?][}{1)(tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
         'blocks': " .:-=+*#%@░▒▓█",
         'texture': " .'`:-+=<>(){}[]ilcrsunoeazx*%$&8B#@"}   # sorted by how much ink each letter has (below): letters as texture
# The colour scenes' letters: few and heavy, so a patch of one brightness is a run of one letter (BBBB, @@@@, 0000)
# and the picture reads as type, not as dots. Same knob names as RAMPS.
CRAMPS = {'classic': " .:-=+oO0Q8#B@$",
          'dense': " .,:;~=+xoO0Q8&#B@$",
          'blocks': " .:-=+*x%#@",
          'texture': " .:-~=<>coeax08&B#@"}
PALETTES = {'sunset': [(255, 222, 150), (255, 165, 85), (255, 100, 120), (200, 90, 220), (120, 110, 255)],
            'reef': [(255, 105, 180), (235, 95, 235), (150, 110, 255), (80, 150, 255), (70, 225, 240)],
            'terminal': [(235, 255, 235), (150, 255, 180), (70, 225, 150), (40, 175, 175), (50, 120, 175)],
            'ember': [(255, 240, 200), (255, 190, 90), (255, 120, 40), (220, 60, 40), (150, 40, 80)],
            'ice': [(240, 250, 255), (170, 220, 255), (110, 170, 255), (90, 120, 230), (130, 100, 210)],
            'mono': [(255, 255, 255), (225, 225, 230), (190, 190, 198), (150, 150, 160), (120, 120, 130)]}
EXTRA = "|/\\-_*+o.'`°,~"
KW = {'def', 'return', 'for', 'in', 'if', 'else', 'max', 'min', 'while', 'True', 'not', 'and', 'or', 'abs'}
SYN = dict(kw=(255, 123, 114), fn=(210, 168, 255), num=(121, 192, 255), com=(139, 148, 158), str=(165, 214, 255), txt=(201, 209, 217), np=(255, 166, 87))
TOK = re.compile(r'(#.*$)|("[^"]*")|(\b\d+\.?\d*\b)|(\b[A-Za-z_]\w*\b)|(\s+)|(.)')


class Video:
    def __init__(self, scene, song_dir, seed, t0, t1, lyrics=True):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        r = random.Random(seed)
        self.SC = importlib.import_module(scene)
        names = sorted(RAMPS)
        self.ramp_name = K.pick('ramp', names, r, weights=[4 if (n == 'texture' and hasattr(self.SC, 'image')) else 1 for n in names])
        self.palette = K.pick('palette', ['scene'] + sorted(PALETTES), r)
        self.layout = K.pick('layout', ['code', 'clean'], r, weights=[3, 1])   # the code under the art is the account's point: most videos show it
        self.sparks = float(K.pick('sparks', [0.5, 1.0, 1.6], r))
        # Colour scenes (SC.image) are pictures in full colour, set in small letters: a finer grid, and every letter
        # takes the colour of the picture under it. The older scenes raymarch a distance field into the coarse grid.
        self.colour = hasattr(self.SC, 'image') or hasattr(self.SC, 'picture')
        self.rows, self.cols, self.cw, self.ch = (CROWS, W // CCW, CCW, CCH) if self.colour else (ROWS, COLS, CW, CH)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 5.0); self.snare = audio.hits(a['snares'], n, 9.0)
        self.bass = np.convolve(a['bass'], np.ones(3) / 3, 'same'); self.vox = np.convolve(a['vocals'], np.ones(5) / 5, 'same')
        self.pulse = np.clip(0.75 * self.kick + 0.45 * self.bass, 0, 1)
        # A colour scene paints on a canvas measured in pixels. One drawn for the old small letters (6 px wide) gets a
        # canvas that many times smaller, so its moon or flower covers as many letters as it was drawn to; a scene
        # drawn for the big letters says ZOOM = 1.
        z = float(getattr(self.SC, 'ZOOM', CCW / 6.0)) if self.colour else 1.0
        self.SC.setup(dict(kick=self.kick, snare=self.snare, bass=self.bass, vox=self.vox, pulse=self.pulse, n=n, kicks=a['kicks'],
                           beats=a['beats'], spb=a['spb'], dur=t1 - t0, t0=t0, seed=seed, rows=self.rows, cols=self.cols, cw=self.cw / z, ch=self.ch / z, w=W / z,
                           snares=a['snares'], hats=a.get('hats', []), vocals=a['vocals']))
        self.grad = np.array(getattr(self.SC, 'GRAD', PALETTES['mono']) if self.palette == 'scene' else PALETTES[self.palette], np.float32)
        self.typeset = hasattr(self.SC, 'picture')                    # a scene that hands over a whole picture: letters.py sets it in type
        if self.typeset: import letters
        ramp = (CRAMPS if self.colour else RAMPS)[self.ramp_name]
        chars = sorted(set(ramp + EXTRA + getattr(self.SC, 'CHARS', '') + (letters.CHARS if self.typeset else '')))
        f = ImageFont.truetype(BOLD, 16) if self.colour else ImageFont.truetype(MONO, 15); self.atlas = np.zeros((len(chars), self.ch, self.cw), np.float32)
        for k, c in enumerate(chars):
            im = Image.new('L', (self.cw, self.ch))
            if self.colour: ImageDraw.Draw(im).text((self.cw / 2, self.ch - 4), c, font=f, fill=255, anchor='ms')
            else: ImageDraw.Draw(im).text((0, 0), c, font=f, fill=255)
            self.atlas[k] = np.asarray(im) / 255.0
        self.idx = {c: k for k, c in enumerate(chars)}
        if self.ramp_name == 'texture' or self.colour: ramp = ' ' + ''.join(sorted(ramp.replace(' ', ''), key=lambda c: self.atlas[self.idx[c]].sum()))
        self.ramp = np.array([self.idx[c] for c in ramp])
        if self.typeset:
            self.type = letters.Typesetter(self.rows, self.cols, {c: float(self.atlas[self.idx[c]].mean()) for c in letters.CHARS})
            self.lut = np.zeros(0x3000, np.int32)
            for c, k in self.idx.items(): self.lut[ord(c)] = k
        self.label = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        lines = __import__('sync_check').load_lines(song_dir) if lyrics and os.path.exists(os.path.join(song_dir, 'lines.json')) else []
        self.lines = [l for l in lines if l[1][0][1] < t1 and l[0] > t0]
        self.fs = ImageFont.truetype(MONO, 20); self.fh = ImageFont.truetype(MONO, 21); self.fc = ImageFont.truetype(MONO, 22); self.fl = ImageFont.truetype(MONO, 34)
        code = self.SC.CODE.split('\n'); self.code_n = len(code); self.lh = 33
        img = Image.new('RGB', (W, self.lh * (len(code) + 20)), (13, 17, 23)); d = ImageDraw.Draw(img)
        for k, line in enumerate(code):
            x = 28; after = False
            for m in TOK.finditer(line):
                s = m.group(0); c = SYN['txt']
                if m.group(1): c = SYN['com']
                elif m.group(2): c = SYN['str']
                elif m.group(3): c = SYN['num']
                elif m.group(4): c = SYN['kw'] if s in KW else SYN['fn'] if after else SYN['np'] if s == 'np' else SYN['txt']; after = s == 'def'
                d.text((x, 8 + k * self.lh), s, font=self.fc, fill=c); x += self.fc.getlength(s)
        self.code = np.asarray(img).astype(np.float32)

    def gradient(self, x):
        g = self.grad; x = np.clip(x, 0, 0.999) * (len(g) - 1); i = x.astype(int); f = (x - i)[..., None]
        return g[i] * (1 - f) + g[np.minimum(i + 1, len(g) - 1)] * f

    def light(self, i):
        SC = self.SC
        jj, ii = np.meshgrid(np.arange(COLS), np.arange(ROWS))
        u = ((jj + 0.5) * CW - W / 2) / SC.SCALE; v = -((ii + 0.5) * CH - ROWS * CH * SC.CENTER) / SC.SCALE
        f = SC.FOCAL; ro = np.array([0, 0, f]); rd = np.stack([u, v, -np.full_like(u, f)], -1); rd /= np.linalg.norm(rd, axis=-1, keepdims=True)
        sdf = lambda p: SC.sdf(p[..., 0], p[..., 1], p[..., 2], i)
        tt = np.full(u.shape, f - 2.6); hit = np.zeros(u.shape, bool); dmin = np.full(u.shape, 9.0)
        for _ in range(SC.STEPS):
            live = ~hit & (tt < f + 4)
            if not live.any(): break
            p = ro + rd[live] * tt[live][:, None]; d = sdf(p)
            dmin[live] = np.minimum(dmin[live], d)
            h = hit[live] | (d < 0.004); hit[live] = h
            tl = tt[live]; tt[live] = np.where(h, tl, tl + np.maximum(d * SC.STEP, 0.004))
        L = np.where(hit, 0.0, SC.GLOW_MISS * np.exp(-np.maximum(dmin, 0) / SC.GLOW_W))
        P = np.zeros(u.shape + (3,))
        if hit.any():
            p = ro + rd[hit] * tt[hit][:, None]; e = 0.008; P[hit] = p
            n = np.stack([sdf(p + [e, 0, 0]) - sdf(p - [e, 0, 0]), sdf(p + [0, e, 0]) - sdf(p - [0, e, 0]), sdf(p + [0, 0, e]) - sdf(p - [0, 0, e])], -1)
            n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
            L[hit] = np.clip(SC.shade(p, n, rd[hit], i), 0, 1)
        if hasattr(SC, 'compose'): L = SC.compose(L, hit, tt, ro, rd, i)
        return L, hit, P

    def art(self, i):
        SC = self.SC; t = i / FPS; idx = self.idx
        L, hit, P = self.light(i); Lf = L.astype(np.float32)
        gy = cv2.Sobel(Lf, cv2.CV_32F, 0, 1, ksize=3); gx = cv2.Sobel(Lf, cv2.CV_32F, 1, 0, ksize=3)
        mag = np.hypot(gx, gy); ang = (np.degrees(np.arctan2(gy, gx)) + 180) % 180
        ch = self.ramp[np.clip((L ** 0.8 * (len(self.ramp) - 1)).astype(int), 0, len(self.ramp) - 1)]
        edge = (mag > 0.9) & (L > 0.12)
        ech = np.where((ang < 22.5) | (ang >= 157.5), idx['|'], np.where(ang < 67.5, idx['\\'], np.where(ang < 112.5, idx['-'], idx['/'])))
        ch = np.where(edge, ech, ch)
        bright = np.where(L > 0.02, 0.55 + 0.85 * L, 0)
        spark = np.zeros_like(L, bool); r2 = np.random.default_rng(i // 2)
        if self.snare[i] > 0.4:
            cand = np.argwhere(L > 0.3)
            if len(cand):
                for y, x in cand[r2.choice(len(cand), min(len(cand), int(10 * self.sparks * self.snare[i])), replace=False)]: spark[y, x] = True
        ch = np.where(spark, idx['*'], ch)
        for (y, x, c, b) in SC.particles(i, ROWS, COLS):
            if 0 <= y < ROWS and 0 <= x < COLS and L[y, x] < 0.02 and c in idx: ch[y, x] = idx[c]; bright[y, x] = b
        pos = SC.colour(np.arange(ROWS)[:, None] / ROWS, np.arange(COLS)[None, :] / COLS, t, L)
        if hasattr(SC, 'tint'): pos = pos + SC.tint(P, hit, i)
        col = self.gradient(pos)
        col = np.where(spark[..., None], np.array([255, 255, 255], np.float32), col) * bright[..., None]
        mask = self.atlas[ch].transpose(0, 2, 1, 3).reshape(ROWS * CH, COLS * CW)
        layer = mask[..., None] * np.repeat(np.repeat(col, CH, 0), CW, 1)
        glow = cv2.GaussianBlur(layer, (0, 0), 5) * (1.0 + 0.8 * self.vox[i]) + cv2.GaussianBlur(layer, (0, 0), 24) * (0.6 + 0.5 * self.pulse[i])
        return np.clip(layer + glow, 0, 255), int((ch != idx[' ']).sum()), int(spark.sum())

    def art_colour(self, i):
        """A colour scene: the scene paints brightness and colour per letter cell (SC.image), this picks the letters
        (edges as / | \\ -), lets the snare throw sparks off the bright parts, and adds the glow."""
        SC = self.SC; idx = self.idx; R, C = self.rows, self.cols
        if hasattr(SC, 'picture'): return self.art_picture(i)
        L, rgb = SC.image(i); L = np.clip(L.astype(np.float32), 0, 1); rgb = rgb.astype(np.float32)
        ch = self.ramp[np.clip(np.rint(L ** 0.8 * (len(self.ramp) - 1)).astype(int), 0, len(self.ramp) - 1)]
        # The shaded side of a shape is hatched along its slope (//// \\\\ |||| ----); the lit side keeps its heavy letters.
        soft = cv2.GaussianBlur(L, (0, 0), 0.8)
        gy = cv2.Sobel(soft, cv2.CV_32F, 0, 1, ksize=3); gx = cv2.Sobel(soft, cv2.CV_32F, 1, 0, ksize=3)
        mag = np.hypot(gx, gy); ang = (np.degrees(np.arctan2(gy, gx)) + 180) % 180
        lo, hi = getattr(SC, 'HATCH', (0.10, 0.42))
        edge = (mag > 0.22) & (L > lo) & (L < hi) & getattr(SC, 'EDGES', True)
        ech = np.where((ang < 22.5) | (ang >= 157.5), idx['|'], np.where(ang < 67.5, idx['\\'], np.where(ang < 112.5, idx['-'], idx['/'])))
        ch = np.where(edge, ech, ch)
        spark = np.zeros((R, C), bool); r2 = np.random.default_rng(i // 2)
        if self.snare[i] > 0.4:
            cand = np.argwhere(L > 0.45)
            if len(cand):
                for y, x in cand[r2.choice(len(cand), min(len(cand), int(18 * self.sparks * self.snare[i])), replace=False)]: spark[y, x] = True
        ch = np.where(spark, idx['*'], ch)
        for (y, x, c, col) in SC.particles(i, R, C):
            if 0 <= y < R and 0 <= x < C and c in idx: ch[y, x] = idx[c]; rgb[y, x] = col; L[y, x] = max(L[y, x], 0.8)
        if self.palette != 'scene':                                  # a palette knob other than the scene's own: recolour by brightness
            rgb = self.gradient(1 - L) * (0.4 + 0.6 * (rgb.mean(-1, keepdims=True) / 255))
        # A letter is drawn at full strength in its own colour: a dim part of the picture is a light letter (. : -),
        # not a faded one, so every letter stays crisp.
        col = np.where(spark[..., None], np.array([255, 255, 255], np.float32), rgb) * (0.86 + 0.5 * L)[..., None]
        blank = ch == idx[' ']
        if getattr(SC, 'DOTS', True):                                 # the empty part of the page is a quiet grid of dots, so it is still type
            yy, xx = np.mgrid[0:R, 0:C]; grid = blank & ((yy + xx) % 2 == 0)
            ch = np.where(grid, idx['.'], ch); col = np.where(grid[..., None], np.array(getattr(SC, 'DOT', (46, 52, 64)), np.float32), col)
        mask = self.atlas[ch].transpose(0, 2, 1, 3).reshape(R * self.ch, C * self.cw)
        layer = mask[..., None] * np.repeat(np.repeat(col, self.ch, 0), self.cw, 1)
        lit = layer * np.repeat(np.repeat((~blank)[..., None].astype(np.float32), self.ch, 0), self.cw, 1)
        small = cv2.resize(lit, (layer.shape[1] // 3, layer.shape[0] // 3), interpolation=cv2.INTER_AREA)
        g = getattr(SC, 'GLOW', 1.0) * 0.45                           # a halo behind the letters, never over them: the letters stay sharp
        glow = (cv2.resize(cv2.GaussianBlur(small, (0, 0), 4), layer.shape[1::-1]) * (0.5 + 0.5 * self.vox[i])
                + cv2.resize(cv2.GaussianBlur(small, (0, 0), 14), layer.shape[1::-1]) * (0.7 + 0.6 * self.pulse[i])) * g
        return np.clip(np.maximum(layer, glow * (1 - mask[..., None])), 0, 255), int((~blank).sum()), int(spark.sum())

    def art_picture(self, i):
        """A scene that hands over a whole picture (SC.picture, RGB): letters.py chooses the letters and their colours,
        this draws them over the wash, lets the snare throw sparks off the bright ones and lifts the lot on the kick."""
        SC = self.SC; idx = self.idx; R, C = self.rows, self.cols
        char, ink, wash, L = self.type.set(SC.picture(i))
        ch = self.lut[char.view(np.uint32).reshape(R, C)]
        spark = np.zeros((R, C), bool)
        if self.snare[i] > 0.4:
            cand = np.argwhere(L > 0.6); r2 = np.random.default_rng(i // 2)
            if len(cand):
                for y, x in cand[r2.choice(len(cand), min(len(cand), int(26 * self.sparks * self.snare[i])), replace=False)]: spark[y, x] = True
        ch = np.where(spark, idx['*'], ch)
        for (y, x, c, col) in SC.particles(i, R, C):
            if 0 <= y < R and 0 <= x < C and c in idx: ch[y, x] = idx[c]; ink[y, x] = col
        if self.palette != 'scene':                                   # a palette knob: the same picture in that palette's colours
            g = self.gradient(1 - L); k = 0.5 + 0.5 * (ink.max(-1, keepdims=True) / 255)
            ink = g * k; wash = g * 0.2 * k
        lift = 0.94 + 0.16 * self.pulse[i]
        ink = np.where(spark[..., None], np.array([255, 255, 255], np.float32), ink * lift)
        mask = self.atlas[ch].transpose(0, 2, 1, 3).reshape(R * self.ch, C * self.cw)[..., None]
        up = lambda a: np.repeat(np.repeat(a, self.ch, 0), self.cw, 1)
        ground = cv2.resize(wash.astype(np.float32) * lift, (C * self.cw, R * self.ch), interpolation=cv2.INTER_LINEAR)
        return np.clip(ground * (1 - mask) + up(ink.astype(np.float32)) * mask, 0, 255), R * C, int(spark.sum())

    def frame_colour(self, i):
        """The colour scenes' page: a header line of live counts, the art, the line being printed, the code underneath."""
        t = i / FPS; SC = self.SC
        img = np.zeros((H, W, 3), np.float32)
        a, letters, sparks = self.art_colour(i); art_y = 150 if self.layout == 'code' else 300
        img[art_y:art_y + a.shape[0], :a.shape[1]] = a
        if self.layout == 'code':
            py = 1380; total = self.code_n * self.lh; view = H - py - 52
            scroll = int((t / (self.n / FPS)) * max(0, total - view + 40)); crop = self.code[scroll:scroll + view].copy()
            hl = int((t * 1.6) % self.code_n) * self.lh + 8 - scroll
            if 4 <= hl < view - self.lh: crop[hl - 4:hl + self.lh - 4] = crop[hl - 4:hl + self.lh - 4] * 0.8 + np.array([40, 52, 70]) * 0.6
            img[py + 52:py + 52 + crop.shape[0]] = crop
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        d.text((24, 40), self.label, font=self.fs, fill=(110, 118, 130))
        d.text((W - 150, 40), '● t %05.1f' % t, font=self.fs, fill=(88, 166, 255))
        d.text((24, 76), SC.stats(i, sparks) + '    letters %s' % format(letters, ','), font=self.fs, fill=(140, 150, 166))
        ly = self.lyric(t)
        if self.layout == 'code':
            d.rectangle([0, 1380, W, 1432], fill=(22, 27, 34)); d.line([0, 1380, W, 1380], fill=(48, 54, 61), width=2)
            d.text((24, 1394), SC.FILE, font=self.fh, fill=(201, 209, 217))
            d.ellipse([W - 250, 1401, W - 238, 1413], fill=(88, 166, 255) if (i // 15) % 2 == 0 else (40, 90, 160))
            d.text((W - 228, 1394), 'running   30 fps', font=self.fh, fill=(88, 166, 255))
            if ly: d.text((24, 1346), '>>> print("%s")' % ly, font=self.fs, fill=(126, 231, 135))
        elif ly:
            while self.fl.getlength(ly) > W - 80 and ' ' in ly: ly = ly.split(' ', 1)[1]
            d.text((W / 2, art_y + a.shape[0] + 80), ly, font=self.fl, fill=(126, 231, 135), anchor='mm')
        return np.asarray(im)

    def lyric(self, t):
        T = self.t0 + t; cur = [l for l in self.lines if l[1][0][1] <= T + 0.05]
        if not cur: return ''
        words = [w for w, s in cur[-1][1] if s <= T + 0.05]
        return ' '.join(words) if words and T < cur[-1][0] + 1.2 else ''

    def frame(self, i):
        if self.colour: return self.frame_colour(i)
        t = i / FPS; SC = self.SC
        img = np.zeros((H, W, 3), np.float32)
        a, letters, sparks = self.art(i)
        art_y = 130 if self.layout == 'code' else 300
        img[art_y:art_y + a.shape[0]] = a
        if self.layout == 'code':
            py = 1380; total = self.code_n * self.lh; view = H - py - 52
            scroll = int((t / (self.n / FPS)) * max(0, total - view + 40)); crop = self.code[scroll:scroll + view].copy()
            hl = int((t * 1.6) % self.code_n) * self.lh + 8 - scroll
            if 0 <= hl < view - self.lh and hl >= 4: crop[hl - 4:hl + self.lh - 4] = crop[hl - 4:hl + self.lh - 4] * 0.8 + np.array([40, 52, 70]) * 0.6
            img[py + 52:py + 52 + crop.shape[0]] = crop
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        stats_y = art_y + ROWS * CH + 10
        if self.layout == 'code':
            d.rectangle([0, 1380, W, 1432], fill=(22, 27, 34)); d.line([0, 1380, W, 1380], fill=(48, 54, 61), width=2)
            d.text((24, 1394), SC.FILE, font=self.fh, fill=(201, 209, 217))
            d.ellipse([W - 250, 1401, W - 238, 1413], fill=(88, 166, 255) if (i // 15) % 2 == 0 else (40, 90, 160))
            d.text((W - 228, 1394), 'running   30 fps', font=self.fh, fill=(88, 166, 255))
            d.text((24, stats_y), SC.stats(i, sparks), font=self.fs, fill=(150, 160, 175))
            d.text((24, stats_y + 30), 'letters %s' % format(letters, ','), font=self.fs, fill=(150, 160, 175))
            ly = self.lyric(t)
            if ly: d.text((24, stats_y + 68), '>>> print("%s")' % ly, font=self.fs, fill=(126, 231, 135))
        else:
            d.text((W / 2, stats_y + 20), SC.stats(i, sparks), font=self.fs, fill=(120, 128, 142), anchor='mm')
            ly = self.lyric(t)
            if ly:
                while self.fl.getlength(ly) > W - 80 and ' ' in ly: ly = ly.split(' ', 1)[1]
                d.text((W / 2, stats_y + 110), ly, font=self.fl, fill=(126, 231, 135), anchor='mm')
        d.text((W - 150, 40), '● t %05.1f' % t, font=self.fs, fill=(88, 166, 255))
        d.text((24, 40), self.label, font=self.fs, fill=(110, 118, 130))
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '18'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 60 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])

import polish as _polish
Video.frame = _polish.wrap(Video.frame, 'ascii')      # phosphor glow, grain, vignette: studio/polish.py
