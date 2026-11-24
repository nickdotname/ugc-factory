#!/usr/bin/env python3
"""Kinetic-type lyric videos: the words of the song, big, landing as they are sung. The Loose Change account's
style (campaign nick_studio), so its lyric videos look nothing like close__quarters' retro desktop or
dylancantor23's stems: flat colour, huge type, no windows, no photos.

    python studio/type_video.py SONG_DIR SEED OUT.mp4                 (CQ_WINDOW="t0,t1" picks the stretch)
    python studio/type_video.py SONG_DIR SEED SHEET.png --frames 0,40,80

Words come from the song's lines.json (each word's start time, checked by studio/force_align.py). Knobs
(studio/knobs.py), so the learner finds out what gets watched:
  layout   slam (one word at a time, filling the frame, the line so far small above it), stack (the line builds as
           rows, each word as wide as the frame), split (the frame cut in two colours, words landing in turn)
  palette  riso, mono, acid, sunset, paper: the colours the background flips between, line by line
  font     anton, montserrat, inter, poppins
  motion   pop (a word lands big and settles), drop (falls in and bounces), shake (the page jolts on the kick)
  texture  halftone, grain, none
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import sync_check

W, H, FPS = 1080, 1920, 30
TOP, BOTTOM = 300, H - 520            # Instagram covers the top bar and the bottom fifth: the words stay between
PALETTES = {
    'riso':   [(255, 72, 176), (0, 120, 191), (255, 232, 0), (0, 169, 92), (245, 240, 230), (24, 24, 28)],
    'mono':   [(12, 12, 12), (245, 244, 238)],
    'acid':   [(8, 8, 8), (200, 255, 0), (255, 0, 128)],
    'sunset': [(255, 94, 58), (255, 190, 11), (58, 12, 163), (247, 37, 133), (20, 12, 40)],
    'paper':  [(240, 234, 220), (22, 22, 22), (214, 40, 40)],
}
FONTS = {'anton': 'Anton-Regular.ttf', 'montserrat': 'Montserrat-ExtraBold.ttf', 'inter': 'Inter-ExtraBold.otf', 'poppins': 'Poppins-Bold.ttf'}


def font_path(name):
    for root in (os.path.join(REPO, 'fonts'), '/usr/share/fonts', '/Library/Fonts'):
        for base, _, files in os.walk(root):
            if name in files: return os.path.join(base, name)
    return os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf')


def lum(c): return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.layout = K.pick('layout', ['slam', 'stack', 'split'], r)
        self.pal_name = K.pick('palette', sorted(PALETTES), r); self.pal = PALETTES[self.pal_name]
        self.font_name = K.pick('font', sorted(FONTS), r); self.fpath = font_path(FONTS[self.font_name])
        self.motion = K.pick('motion', ['pop', 'drop', 'shake'], r); self.texture = K.pick('texture', ['halftone', 'grain', 'none'], r)
        self._fonts = {}
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.title = song.get('title', self.slug); self.artist = song.get('artist', 'Close Quarters')
        lines = sync_check.load_lines(song_dir)          # lines whose sync is not proven come whole, never word by word
        lyrics = os.environ.get('CQ_LYRICS') != 'none'
        self.lines = [L for L in lines if L[1] and L[0] > t0 and L[1][0][1] < t1] if lyrics else []
        a = audio.load(self.slug, t0, t1); self.n = a['n']
        self.kick = audio.hits(a['kicks'], self.n, 8.0); self.snare = audio.hits(a['snares'], self.n, 10.0)
        # each line gets its own pair of colours (background, type), never the same pair twice running
        self.colours = []; prev = None
        for k in range(len(self.lines) + 1):
            bg = r.choice([c for c in self.pal if c != prev] or self.pal)
            fg = max((c for c in self.pal if c != bg), key=lambda c: abs(lum(c) - lum(bg)) + r.random() * 60)
            acc = r.choice([c for c in self.pal if c not in (bg, fg)] or [fg])
            self.colours.append((bg, fg, acc)); prev = bg
        self.f_credit = self.font(30, 'DejaVuSans-Bold.ttf')          # has the ♪ the display faces lack
        self.halftone = self.make_halftone() if self.texture == 'halftone' else None

    def font(self, size, name=None):
        size = max(8, int(size) // 2 * 2); key = (name or self.fpath, size)
        if key not in self._fonts: self._fonts[key] = ImageFont.truetype(font_path(name) if name else self.fpath, size)
        return self._fonts[key]

    def make_halftone(self):
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32); c, s = math.cos(0.4), math.sin(0.4)
        u, v = (xx * c - yy * s) / 9.0, (xx * s + yy * c) / 9.0
        d = np.sqrt((u - np.round(u)) ** 2 + (v - np.round(v)) ** 2)
        return (1 - 0.10 * (d < 0.28))[..., None].astype(np.float32)

    def fit(self, text, maxw, maxsize):
        """The size at which text is as wide as maxw, capped at maxsize."""
        f = self.font(200); w = max(1.0, f.getlength(text))
        return min(maxsize, 200 * maxw / w)

    # ---------------------------------------------------------------- which words are up
    def line_at(self, T):
        hit = None                     # the latest line that has started wins, so a lingering line never holds back the next one's first word
        for k, (e, ws) in enumerate(self.lines):
            nxt = self.lines[k + 1][1][0][1] if k + 1 < len(self.lines) else e + 0.6
            if ws[0][1] - 0.05 <= T < max(e + 0.25, min(nxt - 0.05, e + 0.9)): hit = k
        return hit

    def ease(self, s):
        """How a word arrives s seconds after it is sung: (scale, dy)."""
        if s < 0: return 0.0, 0.0
        if self.motion == 'pop': return 1 + 0.32 * math.exp(-s * 16) * math.cos(s * 28), 0.0
        if self.motion == 'drop': return 1.0, -260 * math.exp(-s * 11) * math.cos(s * 24)
        return 1.0, 0.0

    def text(self, d, xy, txt, size, fill, anchor='mm', stroke=0, sfill=None):
        d.text(xy, txt, font=self.font(size), fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sfill or fill)

    # ---------------------------------------------------------------- layouts
    def slam(self, d, k, T, fg, acc):
        ws = self.lines[k][1]; up = [(w, t) for w, t in ws if t <= T + 0.02]
        if not up: return
        w, t = up[-1]; word = w.upper().strip(',.?!"')
        sc, dy = self.ease(T - t); size = self.fit(word, W - 140, 460) * sc
        self.text(d, (W / 2, (TOP + BOTTOM) / 2 + 60 + dy), word, size, fg)
        line = ' '.join(x.upper() for x, _ in up)                     # the line so far, small, above
        f = self.font(56); rows, cur = [], ''
        for x in line.split():
            if f.getlength((cur + ' ' + x).strip()) > W - 160: rows.append(cur); cur = x
            else: cur = (cur + ' ' + x).strip()
        rows.append(cur)
        for j, row in enumerate(rows[-3:]): self.text(d, (W / 2, TOP + 40 + j * 66), row, 56, acc)

    def stack(self, d, k, T, fg, acc):
        ws = self.lines[k][1]; up = [(w.upper().strip(',.?!"'), t) for w, t in ws if t <= T + 0.02]
        if not up: return
        rows = [(w, self.fit(w, W - 120, 300), t) for w, t in up]
        total = sum(s * 0.86 for _, s, _ in rows); room = BOTTOM - TOP
        scale = min(1.0, room / max(1, total))
        y = TOP + max(0, (room - total * scale) / 2)
        for j, (w, s, t) in enumerate(rows):
            s *= scale; sc, dy = self.ease(T - t); h = s * 0.86
            col = fg if j % 2 == 0 else acc
            self.text(d, (W / 2, y + h / 2 + dy), w, s * sc, col)
            y += h

    def split(self, d, k, T, fg, acc, bg):
        ws = self.lines[k][1]; up = [(w.upper().strip(',.?!"'), t) for w, t in ws if t <= T + 0.02]
        mid = (TOP + BOTTOM) / 2; tilt = 70 * math.sin(T * 0.8)
        d.polygon([(0, mid - tilt), (W, mid + tilt), (W, H), (0, H)], fill=acc)
        for j, (w, t) in enumerate(up[-2:]):
            half = (len(up) - len(up[-2:]) + j) % 2
            sc, dy = self.ease(T - t); size = self.fit(w, W - 160, 300) * sc
            y = (TOP + mid) / 2 + 20 if half == 0 else (mid + BOTTOM) / 2 + 20
            self.text(d, (W / 2, y + dy), w, size, fg if half == 0 else bg)

    # ---------------------------------------------------------------- a frame
    def frame(self, i):
        T = self.t0 + i / FPS; k = self.line_at(T)
        bg, fg, acc = self.colours[k if k is not None else len(self.lines)]
        if self.snare[i] > 0.9 and self.pal_name != 'mono': bg, fg = fg, bg            # a flash of the colours swapped on the snare
        im = Image.new('RGB', (W, H), bg); d = ImageDraw.Draw(im)
        if k is None: self.text(d, (W / 2, (TOP + BOTTOM) / 2), self.title.upper(), self.fit(self.title.upper(), W - 160, 380) * (1 + 0.06 * self.kick[i]), bg, stroke=5, sfill=fg)
        elif self.layout == 'slam': self.slam(d, k, T, fg, acc)
        elif self.layout == 'stack': self.stack(d, k, T, fg, acc)
        else: self.split(d, k, T, fg, acc, bg)
        d.text((W / 2, H - 440), '♪ %s — %s' % (self.title.lower(), self.artist.lower()), font=self.f_credit, fill=fg, anchor='mm')
        img = np.asarray(im).astype(np.float32)
        if self.motion == 'shake' and self.kick[i] > 0.3:
            g = np.random.default_rng(i); m = np.float32([[1, 0, g.integers(-14, 14) * self.kick[i]], [0, 1, g.integers(-10, 10) * self.kick[i]]])
            img = cv2.warpAffine(img, m, (W, H), borderMode=cv2.BORDER_REPLICATE)
        if self.halftone is not None: img = img * self.halftone
        if self.texture == 'grain':
            g = np.random.default_rng(i).normal(0, 9, (H // 2, W // 2)).astype(np.float32)
            img += cv2.resize(g, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]
        return np.clip(img, 0, 255).astype(np.uint8)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(i)).resize((360, 640)) for i in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
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


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
