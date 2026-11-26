#!/usr/bin/env python3
"""A country's outline drawn by spinning circles, a few more circles on every bar, to a song: a new niche page's
renderer (the "Reveal" idea in docs/brain/backlog.md; paused until its Instagram account exists).

    python studio/reveal_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/reveal_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

The outline is a real country's coastline and borders (Natural Earth 1:110m, public domain: studio/reveal/shapes.json,
built by studio/reveal/build_shapes.py). Its Fourier series is computed here; stage one draws it with 2 or 3 circles
(a blob), and every stage adds more (the biggest terms first) until ~150 circles trace it almost exactly. Each stage is
one full turn of the circles, a whole number of beats long, starting on a beat. The number of circles and how far the
drawing is from the real outline (mean distance as a share of the country's longer side) are computed, never made up.
Then the answer: the real outline fills in and the name appears. The last frames fade back into frame 0 (loop).
Knobs (studio/knobs.py): country (its level, easy or hard, follows from it), palette, ask (the opening line).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
CX, CY, SIZE = W / 2, 900.0, 800.0          # the outline's longer side on screen, centred inside the safe area
M = 1024                                    # samples round the outline
EASY = ['the USA', 'Italy', 'Brazil', 'Australia', 'Japan', 'Great Britain', 'France', 'Spain', 'Mexico', 'Chile',
        'Canada', 'Greenland', 'Madagascar', 'Norway', 'Cuba', 'Vietnam', 'South Africa', 'Argentina', 'New Zealand (South Island)',
        'Thailand', 'Turkey', 'Portugal', 'Finland', 'Sweden']
DROP = {'Egypt', 'Ireland', 'Sri Lanka', 'Iceland', 'Greece'}        # too coarse at 1:110m, or a stray inner line
PALETTES = {  # background, circles, arm, pen, text
    'chalk': ((30, 38, 36), (92, 108, 102), (150, 165, 160), (255, 214, 90), (236, 240, 232)),
    'blueprint': ((16, 46, 98), (64, 102, 160), (150, 185, 230), (255, 255, 255), (225, 236, 255)),
    'paper': ((240, 233, 216), (196, 186, 168), (120, 112, 100), (214, 58, 48), (38, 36, 44)),
    'night': ((9, 10, 20), (52, 56, 92), (110, 116, 170), (90, 232, 255), (236, 238, 250)),
}
ASKS = {'name': 'name the country\nbefore the circles do', 'when': 'how many circles\nuntil you know it?',
        'early': 'this is a country.\nguess it early'}


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def outline(name):
    d = json.load(open(os.path.join(HERE, 'reveal', 'shapes.json')))['shapes'][name]
    p = np.array(d['pts'], float); p = np.r_[p, p[:1]]
    seg = np.hypot(*np.diff(p, axis=0).T); s = np.r_[0, np.cumsum(seg)]; u = np.linspace(0, s[-1], M, endpoint=False)
    z = np.interp(u, s, p[:, 0]) + 1j * np.interp(u, s, p[:, 1])
    if np.sum(z.real * np.roll(z.imag, -1) - np.roll(z.real, -1) * z.imag) < 0: z = z[::-1]     # always counter-clockwise
    return z


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed)
        names = [n for n in json.load(open(os.path.join(HERE, 'reveal', 'shapes.json')))['shapes'] if n not in DROP]
        pool = sorted(names)                    # one knob over every country (nightly keeps it fresh); easy ones 3x as likely
        self.country = K.pick('country', pool, r, weights=[3 if n in EASY else 1 for n in pool])
        self.level = 'easy' if self.country in EASY else 'hard'
        pal = PALETTES[K.pick('palette', sorted(PALETTES), r)]
        self.bg, self.ring, self.arm, self.pen, self.ink = [np.array(c, np.float32) for c in pal]
        self.ask = K.pick('ask', sorted(ASKS), r)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 7.0)
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())

        # The series: z(t) = sum c_k e^{ikt}, terms biggest first (the constant term is the centre and stays put).
        z = outline(self.country); c = np.fft.fft(z) / M; k = np.fft.fftfreq(M, 1 / M).astype(int)
        order = [j for j in np.argsort(-np.abs(c)) if k[j] != 0]
        w, h = np.ptp(z.real), np.ptp(z.imag); self.size = min(SIZE / w, 740.0 / h)     # wide ones 800 px across, tall ones 740 px high
        self.c0 = c[k == 0][0]; self.terms = [(int(k[j]), c[j]) for j in order]; self.true = z

        # Stages on the beat grid: one full turn each, whole beats long; the answer gets the last beats.
        bf = [int(round(f)) for _, f in a['beats'] if 0 <= f < n]
        B = len(bf)
        if B < 12: print('not rendered: %d beats is too short for the circles to get anywhere (%s %.1f-%.1f s)' % (B, self.slug, t0, t1)); sys.exit(3)
        rev = 4 if B >= 18 else 3
        per = max(2, min(8, (B - rev) // 7))                                  # up to seven turns fill the stretch; the answer takes what is left
        st = max(2, min(7, (B - rev) // per))
        ladder = sorted(set(int(round(x)) for x in np.geomspace(2 if st >= 5 else 3, 150, st)))
        self.ladder = ladder
        cuts = [0] + [bf[min(B - 1, (j + 1) * per)] for j in range(len(ladder))]
        self.stages = [(cuts[j], cuts[j + 1], ladder[j]) for j in range(len(ladder))]
        self.reveal = cuts[-1]
        th = np.linspace(0, 2 * np.pi, M, endpoint=False)
        self.curves, self.err = {}, {}
        for N in ladder:
            zz = self.c0 + sum(cc * np.exp(1j * kk * th) for kk, cc in self.terms[:N])
            self.curves[N] = zz; self.err[N] = float(np.mean(np.abs(zz - z))) * 100   # longer side is 1
        self.f_big = font('Montserrat-ExtraBold.ttf', 74); self.f_name = font('Anton-Regular.ttf', 150)
        self.f_num = font('DejaVuSansMono-Bold.ttf', 66); self.f_mid = font('Figtree.ttf', 46); self.f_small = font('Figtree.ttf', 38); self.f_credit = font('DejaVuSansMono-Bold.ttf', 26)
        self._first = None

    def P(self, z):
        return np.c_[CX + self.size * z.real, CY - self.size * z.imag]

    def stage(self, i):
        for j, (a, b, N) in enumerate(self.stages):
            if a <= i < b: return j, a, b, N
        return None

    def draw(self, i):
        img = np.empty((H, W, 3), np.float32); img[:] = self.bg; k = float(self.kick[min(i, self.n - 1)])
        glow = np.zeros_like(img)
        S16 = lambda x, y: (int(round(x * 16)), int(round(y * 16)))
        s = self.stage(i)
        if s is not None:
            j, a, b, N = s; u = (i - a) / max(1, b - a); th = 2 * np.pi * u
            if j > 0:                                                          # the last turn's drawing, fading
                prev = self.P(self.curves[self.stages[j - 1][2]])
                f = 0.45 * (1 - min(1.0, u * 2.5))
                if f > 0.01: cv2.polylines(img, [(prev * 16).astype(np.int32)], True, tuple(float(x) for x in self.bg * (1 - f) + self.pen * f), 3, cv2.LINE_AA, 4)
            m = int(u * M); pts = self.P(self.curves[N][:m + 1])
            if len(pts) > 1:
                cv2.polylines(glow, [(pts * 16).astype(np.int32)], False, tuple(float(x) for x in self.pen), 14, cv2.LINE_AA, 4)
                cv2.polylines(img, [(pts * 16).astype(np.int32)], False, tuple(float(x) for x in self.pen), 6, cv2.LINE_AA, 4)
            pos = self.c0; arms = [pos]
            for kk, cc in self.terms[:N]:
                pos = pos + cc * np.exp(1j * kk * th); arms.append(pos)
            xy = self.P(np.array(arms))
            for q in range(len(arms) - 1):
                rad = self.size * abs(self.terms[q][1])
                if rad >= 2.0: cv2.circle(img, S16(*xy[q]), int(rad * 16), tuple(float(x) for x in self.ring), 2, cv2.LINE_AA, 4)
            cv2.polylines(img, [(xy * 16).astype(np.int32)], False, tuple(float(x) for x in self.arm), 2, cv2.LINE_AA, 4)
            cv2.circle(glow, S16(*xy[-1]), int((16 + 10 * k) * 16), tuple(float(x) for x in self.pen), -1, cv2.LINE_AA, 4)
            cv2.circle(img, S16(*xy[-1]), int((7 + 3 * k) * 16), (255.0, 255.0, 255.0), -1, cv2.LINE_AA, 4)
        else:                                                                  # the answer
            u = min(1.0, (i - self.reveal) / (0.5 * FPS)); last = self.P(self.curves[self.ladder[-1]])
            true = self.P(self.true)
            fill = img.copy(); cv2.fillPoly(fill, [(true * 16).astype(np.int32)], tuple(float(x) for x in self.pen), cv2.LINE_AA, 4)
            img = img * (1 - 0.32 * u) + fill * 0.32 * u
            cv2.polylines(glow, [(last * 16).astype(np.int32)], True, tuple(float(x) for x in self.pen), 14, cv2.LINE_AA, 4)
            cv2.polylines(img, [(last * 16).astype(np.int32)], True, tuple(float(x) for x in self.pen), 6, cv2.LINE_AA, 4)
        img = img + cv2.GaussianBlur(glow, (0, 0), 12) * (0.55 + 0.35 * k)

        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im); ink = tuple(int(x) for x in self.ink)
        sub = tuple(int(x) for x in self.ink * 0.62 + self.bg * 0.38)
        if s is not None:
            j, a, b, N = s
            d.multiline_text((W / 2, 340), ASKS[self.ask], font=self.f_big, fill=ink, anchor='mm', align='center', spacing=14)
            d.text((W / 2, 480), 'level: %s' % self.level, font=self.f_small, fill=sub, anchor='mm')
            pop = 1.0 + 0.25 * max(0.0, 1 - (i - a) / 6.0) if j > 0 else 1.0
            fn = font('DejaVuSansMono-Bold.ttf', int(66 * pop)) if pop > 1.001 else self.f_num
            d.text((W / 2, 1390), '%d circle%s' % (N, '' if N == 1 else 's'), font=fn, fill=tuple(int(x) for x in self.pen), anchor='mm')
            d.text((W / 2, 1462), 'off by %s%% of its size' % ('%.0f' % self.err[N] if self.err[N] >= 1.5 else '%.1f' % max(0.1, self.err[N])),
                   font=self.f_mid, fill=sub, anchor='mm')
        else:
            u = min(1.0, (i - self.reveal) / (0.35 * FPS)); sc = 0.8 + 0.2 * u
            name = self.country.split(' (')[0].upper(); f = font('Anton-Regular.ttf', int(150 * sc))
            while d.textlength(name, font=f) > 820 and f.size > 60: f = font('Anton-Regular.ttf', f.size - 8)
            d.text((W / 2, 360), name, font=f, fill=ink, anchor='mm')
            extra = {'New Zealand (South Island)': ' (south island)', 'Japan': ' (honshu, its biggest island)'}.get(self.country, '')
            d.text((W / 2, 1390), 'drawn with %d circles%s' % (self.ladder[-1], extra), font=self.f_mid, fill=sub, anchor='mm')
            d.text((W / 2, 1460), 'outline: natural earth', font=self.f_small, fill=sub, anchor='mm')
        d.text((W / 2, 1540), self.credit, font=self.f_credit, fill=sub, anchor='mm')
        return np.asarray(im)

    def frame(self, i):
        o = self.draw(i); tail = 9
        if i >= self.n - tail:                                                 # fade into frame 0, so the reel loops
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
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', 'stages', self.stages, 'reveal', self.reveal); return
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
        rec = K.record(); rec['outline_source'] = 'Natural Earth 1:110m (public domain)'
        json.dump(rec, open(out[:-4] + '.json', 'w')); print('done', out, rec['knobs'])


Video.frame = _polish.wrap(Video.frame, 'reveal')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 50.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
