#!/usr/bin/env python3
"""Kinetic-type lyric videos for The Loose Change (campaign nick_studio): the song's words set as a printed poster
that prints itself while they are sung. Every line is on the page from the moment it starts, its words drawn as
empty outlines; each word is inked in the instant it is sung, so frame 0 is already a readable lyric and the eye
follows the voice word by word. Two inks on a paper stock (riso style), with the second ink a little out of
register, a giant cropped echo of the line's biggest word behind, and a small typeset header and credit.

    python studio/type_video.py SONG_DIR SEED OUT.mp4                 (CQ_WINDOW="t0,t1" picks the stretch)
    python studio/type_video.py SONG_DIR SEED SHEET.png --frames 0,40,80   (add --full to also save each frame)

Words come from the song's lines.json (each word's start time, checked by studio/force_align.py). A line the
aligner scored under LINE_CONF inks all at once as it starts instead of word by word; words after the vocal stem
ends (placeholder timings in the songs prepared only to 100 s) are dropped; a gap inside a line longer than
SPLIT_GAP (the aligner smearing a held note) splits it in two.

Knobs (studio/knobs.py), so the learner finds out what gets watched:
  layout   block (the line as a justified poster block, every row full width), slam (the word being sung huge,
           the line as a small block above it), scroll (the line as a block low in the frame, the two before it
           above, the page sliding up a line at a time)
  palette  riso, kraft, night, mint, news, hazard: a paper stock, a main ink and a spot ink
  font     fraunces (soft black serif, lower case), anton (condensed caps), figtree (black grotesk caps),
           montserrat (wide caps)
  motion   wipe (ink sweeps across the word over the time it is sung), pop (the word lands in the spot ink,
           a little big, and settles), block (a spot-ink bar snaps behind the word, the word reversed out of it)
  texture  riso (mottled ink, out of register, jolts on the snare), photocopy (toner speckle), clean
  echo     outline, halftone, none: the line's biggest word, huge and cropped, drifting behind
  flip     line (every other line prints ink-on-paper the other way round), none
"""
import json, math, os, random, re, subprocess, sys
import numpy as np, cv2, soundfile as sf
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish
import sync_check

W, H, FPS = 1080, 1920, 30
# Instagram's interface covers the top 250 px, the bottom 420 px and the right 150 px: every word stays inside.
SAFE_L, SAFE_R, SAFE_T, SAFE_B = 96, W - 156, 290, H - 450
LINE_CONF = 0.5          # a line the aligner was less sure of than this is not shown
SPLIT_GAP = 1.6          # seconds between two words of one line that split it in two
LEAD = 0.04              # words ink this much before they are sung: late reads as wrong, early does not

STOCKS = {               # paper, main ink, spot ink
    'riso':   ((244, 239, 227), (22, 50, 140), (255, 72, 150)),
    'kraft':  ((206, 178, 136), (30, 24, 20), (214, 48, 28)),
    'night':  ((17, 17, 21), (240, 236, 226), (196, 255, 36)),
    'mint':   ((192, 229, 210), (22, 34, 60), (255, 98, 48)),
    'news':   ((233, 230, 223), (16, 16, 16), (212, 34, 34)),
    'hazard': ((255, 210, 0), (18, 18, 18), (226, 0, 108)),
}
# file, variation axes (in the font's own order), whether the face is set in capitals
FACES = {
    'fraunces':   ('Fraunces.ttf', [144, 900, 100, 1], False),
    'anton':      ('Anton-Regular.ttf', None, True),
    'figtree':    ('Figtree.ttf', [900], True),
    'montserrat': ('Montserrat-ExtraBold.ttf', None, True),
}
MONO = 'DejaVuSansMono-Bold.ttf'


def font_path(name):
    for root in (os.path.join(REPO, 'fonts'), '/usr/share/fonts', '/Library/Fonts'):
        for base, _, files in os.walk(root):
            if name in files: return os.path.join(base, name)
    return os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf')


def clean(w, caps):
    w = re.sub(r'^[\"(\[]+|[\",.;:!)\]]+$', '', w.strip())
    return w.upper() if caps else w.lower()


def read_lines(song_dir, song, t0, t1):
    """The lines to set: [[start, end, [(word, start, end), ...]]], only what the aligner stands behind."""
    # one rule for every lyric renderer (studio/sync_check.py): lines the timing check does not trust come with every
    # word at the line's start (they ink whole, never word by word); words past the vocal stem are already dropped
    pieces = []
    for e, ws in sync_check.load_lines(song_dir):
        ws = [(w, t) for w, t in ws if w.strip()]
        if not ws: continue
        if len({t for _, t in ws}) == 1 and len(ws) > 1:
            pieces.append(ws); continue
        piece = [ws[0]]
        for w, t in ws[1:]:
            if t - piece[-1][1] > SPLIT_GAP: pieces.append(piece); piece = []
            piece.append((w, t))
        pieces.append(piece)
    lines = []
    for p in pieces:
        words = []
        for j, (w, t) in enumerate(p):
            nxt = p[j + 1][1] if j + 1 < len(p) else t + 0.45
            words.append((w, t, min(nxt, t + 1.0) if nxt > t else t + 0.45))
        lines.append([p[0][1], words[-1][2], words])
    lines = [L for L in lines if L[1] > t0 and L[0] < t1]
    for a, b in zip(lines, lines[1:]): a[1] = min(a[1], b[0])
    return lines


WEAK = set("""a an the and or but so if of to in on at by for with from up out as is am are was were be been being
i i'm im me my mine you you're your yours he him his she her it it's its we us our they them their this that these those
what who how when where why not no yeah yea oh uh just like gonna wanna got get do don't does did can can't will won't
all some too very really then than there here now""".split())


def _strong(word):
    w = ''.join(c for c in word.lower() if c.isalpha() or c == "'")
    return len(w.strip("'")) >= 3 and w not in WEAK and w.strip("'") not in WEAK


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.layout = K.pick('layout', ['block', 'slam', 'scroll'], r, weights=[2, 1, 2])   # slam holds the line's last strong word (never 'and'/'you')
        self.pal_name = K.pick('palette', sorted(STOCKS), r); self.stock = STOCKS[self.pal_name]
        self.face = K.pick('font', sorted(FACES), r)
        self.motion = K.pick('motion', ['wipe', 'pop', 'block'], r)
        self.texture = K.pick('texture', ['riso', 'photocopy', 'clean'], r)
        self.echo = K.pick('echo', ['outline', 'halftone', 'none'], r)
        self.flip = K.pick('flip', ['line', 'none'], r)
        if self.layout == 'slam': self.echo = 'none'; K.CHOSEN['echo'] = 'none'     # two giant words fight: slam has its own
        fname, self.axes, self.caps = FACES[self.face]; self.fpath = font_path(fname)
        self._fonts, self._cache = {}, {}
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.song = song
        self.title = song.get('title', self.slug); self.artist = song.get('artist', 'Close Quarters')
        lyrics = os.environ.get('CQ_LYRICS') != 'none'
        self.lines = read_lines(song_dir, song, t0, t1) if lyrics else []
        for L in self.lines: L[2] = [(clean(w, self.caps), a, b) for w, a, b in L[2] if clean(w, self.caps)]
        self.lines = [L for L in self.lines if L[2]]
        a = audio.load(self.slug, t0, t1); self.n = a['n']
        self.kick = audio.hits(a['kicks'], self.n, 9.0); self.snare = audio.hits(a['snares'], self.n, 12.0)
        # print texture, made once: paper fibre, and three ink mottles the frames cycle through (a slight boil)
        g = np.random.default_rng(seed)
        fib = cv2.GaussianBlur(g.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 0.8)
        fib += cv2.resize(g.normal(0, 1, (H // 24, W // 24)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC) * 0.3
        dark = sum(self.stock[0]) < 200
        self.paper_tex = (1 + (0.035 if not dark else 0.06) * fib)[..., None]
        self.mottle = []
        for _ in range(3):
            if self.texture == 'riso':
                m = cv2.resize(g.normal(0, 1, (H // 6, W // 6)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
                m = np.clip(0.92 + 0.05 * m + 0.06 * g.normal(0, 1, (H, W)).astype(np.float32), 0.72, 1.0)
            elif self.texture == 'photocopy':
                sp = g.random((H, W)).astype(np.float32)
                m = np.where(sp < 0.012, 0.25, 1.0).astype(np.float32)
                m *= np.clip(0.94 + 0.05 * cv2.resize(g.normal(0, 1, (H // 40, W // 40)).astype(np.float32), (W, H)), 0.85, 1.0)
            else:
                m = np.ones((H, W), np.float32)
            self.mottle.append(m)
        self.toner = None
        if self.texture == 'photocopy':          # stray toner on the paper itself
            sp = g.random((H, W)).astype(np.float32)
            self.toner = np.clip(cv2.GaussianBlur((sp < 0.0016).astype(np.float32), (0, 0), 0.9) * 2.2, 0, 1)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32); c, s = math.cos(0.26), math.sin(0.26)
        u, v = (xx * c - yy * s) / 14.0, (xx * s + yy * c) / 14.0
        self.dots = (np.sqrt((u - np.round(u)) ** 2 + (v - np.round(v)) ** 2) < 0.30).astype(np.float32)   # halftone screen
        self.f_mono = self.font(26, MONO); self.f_credit = self.font(30, 'DejaVuSans-Bold.ttf')

    # ---------------------------------------------------------------- type
    def font(self, size, name=None):
        size = max(8, int(round(size))); key = (name or self.fpath, size)
        if key not in self._fonts:
            f = ImageFont.truetype(font_path(name) if name else self.fpath, size)
            if not name and self.axes:
                try: f.set_variation_by_axes(self.axes)
                except Exception: pass
            self._fonts[key] = f
        return self._fonts[key]

    def ink_box(self, text, size):
        """(x0, y0, x1, y1) of text's ink, drawn from its left baseline."""
        return self.font(size).getbbox(text, anchor='ls')

    def rows_for(self, words, box_w, box_h, max_size, min_size=60):
        """Split a line into rows, each scaled to the full width (a justified poster block): the split that fills the
        box best without one row towering over the rest. Returns [(first word, end word, size, baseline y)], height."""
        n = len(words); best = None; ref = 200
        widths = [self.font(ref).getlength(w) for w in words]; space = self.font(ref).getlength(' ')
        for r in range(1, min(n, 6) + 1):
            rows = []
            for a, b in self.partition(widths, space, r):
                x0, y0, x1, y1 = self.ink_box(' '.join(words[a:b]), ref)
                rows.append([a, b, min(max_size, ref * box_w / max(1, x1 - x0)), y0 / ref, y1 / ref])
            full = [row[2] for row in rows]                           # each row's size at full width (or its cap)
            total = sum((y1 - y0) * s for _, _, s, y0, y1 in rows) + 0.07 * sum(row[2] for row in rows[1:])
            if total > box_h:
                for row in rows: row[2] *= box_h / total
                total = box_h
            sizes = [row[2] for row in rows]
            if min(sizes) < min_size and r > 1: continue
            # how much of the box the ink covers (a block shrunk to fit is narrower), and how even the rows are
            cover = sum((y1 - y0) * s * (s / f) for (_, _, s, y0, y1), f in zip(rows, full)) / box_h
            score = cover + 0.4 * min(sizes) / max(sizes) - (0.25 if r == 1 and n > 4 else 0)
            if best is None or score > best[0]: best = (score, rows, total)
        if best is None: return [], 0
        _, rows, total = best; out = []; y = 0.0
        for j, (a, b, s, y0, y1) in enumerate(rows):
            if j: y += 0.07 * s
            out.append((a, b, s, y - y0 * s)); y += (y1 - y0) * s
        return out, total

    @staticmethod
    def partition(widths, space, r):
        """Cut the words into r runs of as near equal width as can be."""
        n = len(widths); target = (sum(widths) + space * (n - 1)) / r
        if n > 14: return [(i * n // r, (i + 1) * n // r) for i in range(r)]
        best, best_cost = None, None
        def rec(i, k, acc):
            nonlocal best, best_cost
            if k == 1:
                parts = acc + [(i, n)]
                cost = sum((sum(widths[a:b]) + space * (b - a - 1) - target) ** 2 for a, b in parts)
                if best_cost is None or cost < best_cost: best, best_cost = parts, cost
                return
            for j in range(i + 1, n - k + 2): rec(j, k - 1, acc + [(i, j)])
        rec(0, r, []); return best

    def place(self, words, times, box_l, box_t, box_w, box_h, max_size, valign):
        rows, total = self.rows_for(words, box_w, box_h, max_size)
        top = box_t + (box_h - total) * valign; out = []
        for a, b, s, base in rows:
            f = self.font(s); x = box_l - self.ink_box(' '.join(words[a:b]), s)[0]
            for j in range(a, b):
                out.append((words[j], x, top + base, s, times[j][0], times[j][1]))
                x += f.getlength(words[j] + ' ')
        return out

    def plan(self, k, box_l, box_t, box_w, box_h, max_size, valign=0.5):
        """Where every word of line k goes: [(text, x, baseline, size, start, end)]."""
        key = ('plan', k, box_l, box_t, box_w, box_h, max_size, valign)
        if key not in self._cache:
            L = self.lines[k][2]
            self._cache[key] = self.place([w for w, _, _ in L], [(a, b) for _, a, b in L], box_l, box_t, box_w, box_h, max_size, valign)
        return self._cache[key]

    # ---------------------------------------------------------------- which line is up
    def line_at(self, T):
        """The line on the page at T: from just before its first word until just before the next line's. Before the
        first line, the first line (as outlines), so frame 0 is always a readable lyric, never a title card."""
        if not self.lines: return None
        k = 0
        for j, L in enumerate(self.lines):
            if L[0] - 0.3 <= T: k = j
        return k

    def colours(self, k):
        paper, ink, spot = self.stock
        if self.flip == 'line' and k % 2 == 1: paper, ink = ink, paper
        return paper, ink, spot

    # ---------------------------------------------------------------- drawing words into the plates
    def outline(self, d, xy, text, f, sw):
        d.text(xy, text, font=f, fill=255, anchor='ls', stroke_width=sw, stroke_fill=255)
        d.text(xy, text, font=f, fill=0, anchor='ls')

    def put_words(self, plates, words, T):
        """Draw words into the plates by their state: sung = ink, being sung = the motion, not yet = outline."""
        ink, spot, ghost, knock = plates
        di, ds, dg, dk = (ImageDraw.Draw(p) for p in plates)
        for text, x, y, s, a, b in words:
            f = self.font(s); sw = max(2, int(s * 0.03))
            if a < 0:                                                 # the title (no lyrics here): just ink
                di.text((x, y), text, font=f, fill=255, anchor='ls'); continue
            if T < a - LEAD: self.outline(dg, (x, y), text, f, sw); continue
            age = T - (a - LEAD)
            if T >= b: di.text((x, y), text, font=f, fill=255, anchor='ls'); continue
            x0, y0, x1, y1 = f.getbbox(text, anchor='ls')
            if self.motion == 'wipe':
                prog = min(1.0, 0.3 + 0.7 * age / max(0.08, b - a)); cut = int(x + x0 + (x1 - x0) * prog)
                tmp = Image.new('L', (W, H), 0); ImageDraw.Draw(tmp).text((x, y), text, font=f, fill=255, anchor='ls')
                tmp.paste(0, (max(0, cut), 0, W, H)); spot.paste(255, mask=tmp)
                self.outline(dg, (x, y), text, f, sw)
            elif self.motion == 'pop':
                sc = 1 + 0.16 * math.exp(-age * 13) * math.cos(age * 20)
                ds.text((x + (x0 + x1) / 2, y + (y0 + y1) / 2), text, font=self.font(s * sc), fill=255, anchor='mm')
            else:                                                     # block: a spot bar, the word knocked out of it
                pad = s * 0.07; grow = min(1.0, age / 0.07)
                ds.rectangle([x + x0 - pad, y + y0 - pad, x + x0 - pad + (x1 - x0 + 2 * pad) * grow, y + y1 + pad], fill=255)
                dk.text((x, y), text, font=f, fill=255, anchor='ls')

    def echo_mask(self, k):
        """The line's biggest word, huge, as an outline or solid (screened later), cropped: drawn once per line."""
        key = ('echo', k)
        if key in self._cache: return self._cache[key]
        word = max((w for w, _, _ in self.lines[k][2]), key=len)
        f = self.font(1250 if len(word) <= 4 else 1050); x0, y0, x1, y1 = f.getbbox(word, anchor='ls')
        im = Image.new('L', (int(x1 - x0) + 60, int(y1 - y0) + 60), 0); d = ImageDraw.Draw(im)
        if self.echo == 'outline': self.outline(d, (30 - x0, 30 - y0), word, f, 12)
        else: d.text((30 - x0, 30 - y0), word, font=f, fill=255, anchor='ls')
        self._cache[key] = np.asarray(im).astype(np.float32) / 255
        return self._cache[key]

    # ---------------------------------------------------------------- a frame
    def frame(self, i):
        T = self.t0 + i / FPS; k = self.line_at(T)
        paper, ink, spot = (np.array(c, np.float32) for c in self.colours(k or 0))
        kick, snare = float(self.kick[i]), float(self.snare[i])
        plates = [Image.new('L', (W, H), 0) for _ in range(4)]       # ink, spot, outline, knock-out
        box_w = SAFE_R - SAFE_L
        if k is None:
            words = self.plan_title()
        elif self.layout == 'block':
            words = self.plan(k, SAFE_L, SAFE_T + 60, box_w, SAFE_B - SAFE_T - 130, 400)
        elif self.layout == 'slam':
            words = self.plan(k, SAFE_L, SAFE_T + 50, box_w, 300, 110, valign=0.0)
        else:                                                         # scroll
            words = self.plan(k, SAFE_L, SAFE_B - 560, box_w, 500, 240, valign=1.0)
        self.put_words(plates, words, T)
        if k is not None and self.layout == 'slam': self.draw_slam(plates, words, T)
        if k is not None and self.layout == 'scroll': self.draw_before(plates, k, T, min(w[2] - w[3] * 0.78 for w in words))
        im = np.empty((H, W, 3), np.float32); im[:] = paper; im *= self.paper_tex
        if self.toner is not None: im += (ink - im) * (self.toner * 0.8)[..., None]
        mot = self.mottle[(i // 3) % 3]
        if k is not None and self.echo != 'none':
            m = self.echo_mask(k); age = T - self.lines[k][0]
            ox = int(-m.shape[1] * 0.16 - 26 * age); oy = int((SAFE_T + SAFE_B) / 2 - m.shape[0] / 2 + 40)
            canvas = np.zeros((H, W), np.float32)
            xa, ya = max(0, ox), max(0, oy); xb, yb = min(W, ox + m.shape[1]), min(H, oy + m.shape[0])
            if xb > xa and yb > ya: canvas[ya:yb, xa:xb] = m[ya - oy:yb - oy, xa - ox:xb - ox]
            if self.echo == 'halftone': canvas *= self.dots
            im += (spot - im) * (canvas * (0.3 if self.echo == 'outline' else 0.26) * (1 + 0.5 * kick))[..., None]
        mi, ms, mg, mk = (np.asarray(p).astype(np.float32) / 255 for p in plates)
        if self.texture == 'riso':        # the spot plate sits a little out of register, and jumps on the snare
            dx, dy = 4 + int(round(9 * snare)), 3 - int(round(5 * snare))
            ms = np.roll(ms, (dy, dx), (0, 1)); mk = np.roll(mk, (dy, dx), (0, 1))
        im += (ink - im) * (mg * 0.8)[..., None]
        im += (spot - im) * (ms * mot)[..., None]
        if mk.any(): im += (paper - im) * (mk * ms)[..., None]
        im += (ink - im) * (mi * mot)[..., None]
        out = Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)); self.furniture(ImageDraw.Draw(out), T, ink)
        img = np.asarray(out)
        if kick > 0.05:                                               # the page leans in on the kick
            z = 1 + 0.016 * kick; cx, cy = (SAFE_L + SAFE_R) / 2, (SAFE_T + SAFE_B) / 2
            img = cv2.warpAffine(img, np.float32([[z, 0, cx * (1 - z)], [0, z, cy * (1 - z)]]), (W, H), borderMode=cv2.BORDER_REFLECT)
        return img

    def draw_slam(self, plates, words, T):
        """slam: the word being sung (or the last one sung), as big as the frame is wide."""
        # the giant word is the last STRONG word sung (never 'and', 'you', 'my'...): until the line's first strong
        # word lands, the first strong word waits as an outline
        strong = [w for w in words if _strong(w[0])] or [max(words, key=lambda w: len(w[0]))]
        cur = [w for w in strong if w[4] - LEAD <= T] or strong[:1]
        text, a, b = cur[-1][0], cur[-1][4], cur[-1][5]
        ink, spot, ghost, knock = plates
        fit = min(520, 200 * (SAFE_R - SAFE_L) / max(1, self.ink_box(text, 200)[2] - self.ink_box(text, 200)[0]))
        f = self.font(fit); x0, y0, x1, y1 = f.getbbox(text, anchor='ls')
        cy = (SAFE_T + 420 + SAFE_B - 40) / 2; y = cy - (y0 + y1) / 2; x = SAFE_L - x0
        age = max(0.0, T - (a - LEAD)); landing = a - LEAD <= T < b
        if self.motion == 'block' and landing:
            pad = fit * 0.06; ImageDraw.Draw(spot).rectangle([x + x0 - pad, y + y0 - pad, x + x1 + pad, y + y1 + pad], fill=255)
            ImageDraw.Draw(knock).text((x, y), text, font=f, fill=255, anchor='ls'); return
        sc = 1 + (0.12 * math.exp(-age * 12) * math.cos(age * 18) if self.motion == 'pop' else 0)
        dy = -90 * math.exp(-age * 16) if self.motion == 'wipe' else 0
        if T < a - LEAD:                                              # frame 0 before the first word: its outline
            self.outline(ImageDraw.Draw(ghost), (x, y), text, f, max(3, int(fit * 0.02))); return
        ImageDraw.Draw(spot if landing else ink).text((x + (x0 + x1) / 2, y + (y0 + y1) / 2 + dy), text, font=self.font(fit * sc), fill=255, anchor='mm')

    def draw_before(self, plates, k, T, top):
        """scroll: the two lines before this one, smaller and fainter, above it, sliding up as the new line arrives."""
        ink = plates[0]
        start = self.lines[k][0] - 0.3; slide = max(0.0, 1 - (T - start) / 0.22) ** 2
        y = top - 40 - slide * 120
        for back, L in enumerate(reversed(self.lines[max(0, k - 2):k])):
            s = 64 if back == 0 else 52; f = self.font(s); rows, cur = [], ''
            for w in (w for w, _, _ in L[2]):
                if f.getlength((cur + ' ' + w).strip()) > SAFE_R - SAFE_L: rows.append(cur); cur = w
                else: cur = (cur + ' ' + w).strip()
            rows.append(cur)
            for row in reversed(rows):
                if y - s < SAFE_T + 50: return
                tmp = Image.new('L', (W, H), 0); ImageDraw.Draw(tmp).text((SAFE_L, y), row, font=f, fill=255, anchor='ls')
                ink.paste(int(255 * (0.5 if back == 0 else 0.28)), (0, 0), tmp)
                y -= s * 1.12
            y -= s * 0.45

    def plan_title(self):
        """No lyrics in this stretch (CQ_LYRICS=none): the song's title as the block."""
        if 'title' not in self._cache:
            t = (self.title.upper() if self.caps else self.title.lower()).split()
            self._cache['title'] = self.place(t, [(-1, -1)] * len(t), SAFE_L, SAFE_T + 60, SAFE_R - SAFE_L, SAFE_B - SAFE_T - 130, 380, 0.5)
        return self._cache['title']

    def furniture(self, d, T, ink):
        """A typeset header (the album, the track's number, the song's clock) and the credit: real numbers only."""
        col = tuple(int(c) for c in ink)
        tr, tot = self.song.get('track'), self.song.get('tracks_total') or 15
        d.text((SAFE_L, SAFE_T - 14), ('EDUCATION  %02d/%02d' % (tr, tot)) if tr else 'EDUCATION', font=self.f_mono, fill=col, anchor='ls')
        m, s = divmod(max(0.0, T), 60)
        d.text((SAFE_R, SAFE_T - 14), '%d:%04.1f' % (m, s), font=self.f_mono, fill=col, anchor='rs')
        d.line([(SAFE_L, SAFE_T), (SAFE_R, SAFE_T)], fill=col, width=3)
        d.line([(SAFE_L, SAFE_B - 6), (SAFE_R, SAFE_B - 6)], fill=col, width=3)
        d.text((SAFE_L, SAFE_B + 34), '♪ %s — %s' % (self.title.lower(), self.artist.lower()), font=self.f_credit, fill=col, anchor='ls')

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            frames = [self.frame(i) for i in fs]
            if '--full' in sys.argv:
                for i, f in zip(fs, frames): Image.fromarray(f).save(out[:-4] + '_f%d.png' % i)
            sheet = Image.new('RGB', (360 * len(frames), 640))
            for j, f in enumerate(frames): sheet.paste(Image.fromarray(f).resize((360, 640), Image.LANCZOS), (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
        if not self.lines: sys.exit('no proven lyrics in this stretch: nothing to set in type')
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '6M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '12M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 90 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'type')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
