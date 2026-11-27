"""Isometric pixel worlds that move to the music (a style of the ASCII / creative-coding account).

A scene (bridge.py, court.py) builds its world out of voxels and says what moves; this draws the world once onto a
270 x 480 canvas, draws the moving parts on top every frame, and blows the canvas up with hard pixel edges. The whole
world moves with the song: it hops on the kick, brightens with the bass, throws sparks on the snare, and fireflies
glow with the vocal, while the camera cuts between a wide shot and close-ups on bar lines. Underneath, as in the
ASCII videos, the code that draws it scrolls in an editor, with the stats and the lyric being "printed". Every look
choice is a knob (studio/knobs.py), so the learner finds out what gets watched.
"""
import json, math, os, re, subprocess, sys, importlib, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); STUDIO = os.path.dirname(HERE); REPO = os.path.dirname(STUDIO)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(STUDIO, 'mathviz')); sys.path.insert(0, STUDIO)
import beat as audio
import knobs as K
from vox import Canvas, upscale
from sky import Air, SKIES

W, H, FPS = 1080, 1920, 30
LW, LH, BASE = 270, 480, 4                              # the pixel canvas, blown up four times
MONO = os.path.join(REPO, 'fonts', 'DejaVuSansMono-Bold.ttf')
BGS = {'night': (16, 15, 30), 'ink': (10, 12, 18), 'plum': (24, 14, 32)}
PANEL = 1380                                            # where the editor starts
# the code panel, coloured the way the ASCII videos colour theirs
KW = {'def', 'return', 'for', 'in', 'if', 'else', 'max', 'min', 'while', 'True', 'not', 'and', 'or', 'abs', 'range'}
SYN = dict(kw=(255, 123, 114), fn=(210, 168, 255), num=(121, 192, 255), com=(139, 148, 158), str=(165, 214, 255), txt=(201, 209, 217), np=(255, 166, 87))
TOK = re.compile(r'(#.*$)|("[^"]*")|(\b\d+\.?\d*\b)|(\b[A-Za-z_]\w*\b)|(\s+)|(.)')


class Video:
    def __init__(self, scene, song_dir, seed, t0, t1, world_no=1, lyrics=True):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        r = random.Random(seed); self.rng = np.random.default_rng(seed)
        self.bg = BGS['ink']
        self.cuts = K.pick('pixel_cuts', ['bars', 'none'], r)
        sky = K.pick('pixel_sky', sorted(SKIES), r); weather = K.pick('pixel_weather', ['clear', 'rain', 'snow'], r, weights=[2, 1, 1])
        self.SC = importlib.import_module(scene)
        if weather not in getattr(self.SC, 'WEATHER', ('clear', 'rain', 'snow')): weather = 'clear'; K.CHOSEN['pixel_weather'] = 'clear'
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        E = dict(n=n, spb=a['spb'], beats=a['beats'], kicks=a['kicks'], snares=a['snares'], hats=a['hats'],
                 kick=audio.hits(a['kicks'], n, 7.0), snare=audio.hits(a['snares'], n, 9.0), hat=audio.hits(a['hats'], n, 14.0),
                 bass=a['bass'], seed=seed)
        E['vox'] = np.convolve(a['vocals'], np.ones(5) / 5, 'same'); E['bassf'] = np.convolve(a['bass'], np.ones(3) / 3, 'same')
        downs = [int(round(f)) for b, f in a['beats'] if b % 4 == 0 and f >= 0]
        E['downs'] = downs
        E['big'] = min(downs, key=lambda f: abs(f - 0.45 * n)) if downs else None
        self.E = E
        self.world = self.SC.build(self.rng); self.SC.setup(E, self.rng)
        cv = Canvas(LW, LH, getattr(self.SC, 'OX', LW // 2), getattr(self.SC, 'OY', 170), self.bg)
        self.voxels = cv.world(self.world); self.static = cv
        rows = np.where((cv.key >= 0).any(1))[0]; cols = np.where((cv.key >= 0).any(0))[0]
        # the wide shot: as big as the world allows, in whole pixels (a small world is drawn five times over, not four)
        span = (cols[-1] - cols[0] + 16) if len(cols) else LW
        self.wide = 5 if span <= W // 5 else BASE
        cx = (cols[0] + cols[-1]) / 2 if len(cols) else LW / 2; cy = (rows[0] + rows[-1]) / 2 if len(rows) else LH / 2
        ww, wh = W // self.wide, PANEL // self.wide
        self.wx0 = int(np.clip(cx - ww / 2, 0, LW - ww)); self.wy0 = int(np.clip(cy - wh * 0.56, 0, LH - wh))
        self.air = Air(sky, weather, LW, LH, int(rows[0]) if len(rows) else 150, np.random.default_rng(seed + 11), view=self.wy0 if self.wide != BASE else 0)
        yy, xx = np.mgrid[0:LH, 0:LW]
        self.dots = ((xx % 6 == 3) & (yy % 6 == 3))
        self.flies = [(self.rng.uniform(20, LW - 20), self.rng.uniform(120, 330), self.rng.uniform(0, 6.28), self.rng.uniform(0.3, 0.9)) for _ in range(36)]
        self.label = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.world_no = world_no
        self.shots = self.plan(downs)
        self.fs = ImageFont.truetype(MONO, 20); self.fh = ImageFont.truetype(MONO, 21); self.fc = ImageFont.truetype(MONO, 22)
        lines = __import__('sync_check').load_lines(song_dir) if lyrics and os.path.exists(os.path.join(song_dir, 'lines.json')) else []
        self.lines = [l for l in lines if l[1][0][1] < t1 and l[0] > t0]
        code = self.SC.CODE.split('\n'); self.code_n = len(code); self.lh = 33
        img = Image.new('RGB', (W, self.lh * (len(code) + 20)), (13, 17, 23)); d = ImageDraw.Draw(img)
        for k, line in enumerate(code):
            x = 28; after = False
            for m in TOK.finditer(line):
                st = m.group(0); c = SYN['txt']
                if m.group(1): c = SYN['com']
                elif m.group(2): c = SYN['str']
                elif m.group(3): c = SYN['num']
                elif m.group(4): c = SYN['kw'] if st in KW else SYN['fn'] if after else SYN['np'] if st == 'np' else SYN['txt']; after = st == 'def'
                d.text((x, 8 + k * self.lh), st, font=self.fc, fill=c); x += self.fc.getlength(st)
        self.code = np.asarray(img).astype(np.float32)

    def plan(self, downs):
        """The cut list: open close on the scene's first focus, cut wide on the first bar line after two seconds, then
        every two bars cut between close-ups and the wide shot."""
        focus = getattr(self.SC, 'FOCUS', [])
        if self.cuts == 'none' or not focus: return [(0, None)]
        bars = [d for d in downs if d > 0]
        first = next((d for d in bars if d >= 2.2 * FPS), int(2.5 * FPS))
        shots = [(0, focus[0]), (first, None)]
        k = 1
        for d in bars:
            if d <= first: continue
            if (bars.index(d) - bars.index(first) if first in bars else 0) % 2 == 0:
                shots.append((d, focus[k % len(focus)] if len(shots) % 2 == 0 else None)); k += 1
        return shots

    def shot(self, i):
        cur = None
        for f, s in self.shots:
            if i >= f: cur = s
        return cur

    def lyric(self, t):
        T = self.t0 + t; cur = [l for l in self.lines if l[1][0][1] <= T + 0.05]
        if not cur: return ''
        words = [w for w, s in cur[-1][1] if s <= T + 0.05]
        return ' '.join(words) if words and T < cur[-1][0] + 1.2 else ''

    def react(self, cv, rgb, i):
        """The world moving with the song: brighter with the bass, sparks on the snare, fireflies glowing with the
        vocal, the dotted floor pulsing on the kick. Returns how many sparks it threw."""
        E = self.E; kick = float(E['kick'][i]); snare = float(E['snare'][i])
        bass = float(min(1.2, E['bassf'][i])); vox = float(min(1.2, E['vox'][i]))
        solid = cv.key >= 0
        rgb = self.air.light_world(rgb, solid, cv, i, E)
        rgb[solid] *= 0.90 + 0.16 * bass
        sky = self.air.backdrop(i, E)
        rgb[~solid] = sky[~solid] * (1 + 0.12 * kick)
        n = 0
        if snare > 0.35:                                   # sparks: bright pixels on the tops of things
            tops = np.argwhere(cv.face == 1)
            if len(tops):
                r2 = np.random.default_rng(i // 2); k = min(len(tops), int(60 * snare))
                for y, x in tops[r2.choice(len(tops), k, replace=False)]:
                    rgb[y, x] = (255, 250, 220); n += 1
        t = i / FPS
        for (fx, fy, ph, sp) in self.flies:                 # fireflies drifting over the scene, lit by the vocal
            x = int(fx + 6 * math.sin(t * sp + ph)); y = int(fy + 4 * math.cos(t * sp * 0.8 + ph * 1.3) - (t * 2 * sp) % 40)
            glow = 0.25 + 0.75 * vox * (0.5 + 0.5 * math.sin(t * 5 + ph * 3))
            if 0 <= x < LW and 0 <= y < LH and glow > 0.3:
                rgb[y, x] = rgb[y, x] * (1 - glow) + np.array([255, 236, 130], np.float32) * glow
        return n

    def frame(self, i):
        t = i / FPS; SC = self.SC; E = self.E
        cv = self.static.copy()
        info = SC.dynamic(cv, i, E)
        rgb = cv.rgb
        if hasattr(SC, 'water'): rgb = SC.water(cv, rgb, i, E)
        sparks = self.react(cv, rgb, i)
        rgb = self.air.front(rgb, i, E)
        rgb = np.clip(rgb, 0, 255)
        hop = int(round(2 * float(E['kick'][i])))          # the whole world hops a pixel or two on the kick
        if hop: rgb = np.concatenate([rgb[hop:], np.repeat(rgb[-1:], hop, 0)], 0)
        focus = self.shot(i)
        if focus is None and self.wide != BASE:
            big = upscale(rgb[self.wy0:self.wy0 + H // self.wide + 1, self.wx0:self.wx0 + W // self.wide], self.wide)
        elif focus is None:
            big = upscale(rgb, BASE)
        else:
            sc = 6; cw, ch = W // sc, H // sc
            fx, fy = cv.screen(*focus); x0 = int(np.clip(fx - cw / 2, 0, LW - cw)); y0 = int(np.clip(fy - ch / 2, 0, LH - ch))
            big = upscale(rgb[y0:y0 + ch, x0:x0 + cw], sc)
        img = np.ascontiguousarray(big[:H, :W]).astype(np.float32)
        # the editor underneath, scrolling through the code that draws this
        py = PANEL; total = self.code_n * self.lh; view = H - py - 52
        scroll = int((t / (self.n / FPS)) * max(0, total - view + 40)); crop = self.code[scroll:scroll + view].copy()
        hl = int((t * 1.6) % self.code_n) * self.lh + 8 - scroll
        if 4 <= hl < view - self.lh: crop[hl - 4:hl + self.lh - 4] = crop[hl - 4:hl + self.lh - 4] * 0.8 + np.array([40, 52, 70]) * 0.6
        img[py:] = np.array([13, 17, 23], np.float32)
        img[py + 52:py + 52 + crop.shape[0]] = crop[:H - py - 52]
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        d.rectangle([0, py, W, py + 52], fill=(22, 27, 34)); d.line([0, py, W, py], fill=(48, 54, 61), width=2)
        d.text((24, py + 14), SC.FILE, font=self.fh, fill=(201, 209, 217))
        d.ellipse([W - 250, py + 21, W - 238, py + 33], fill=(88, 166, 255) if (i // 15) % 2 == 0 else (40, 90, 160))
        d.text((W - 228, py + 14), 'running   30 fps', font=self.fh, fill=(88, 166, 255))
        sy = py - 118
        d.rectangle([0, sy - 12, W, py], fill=(13, 17, 23))
        d.text((24, sy), SC.stats(i, E, info, self.voxels), font=self.fs, fill=(150, 160, 175))
        d.text((24, sy + 30), 'sparks %d' % sparks, font=self.fs, fill=(150, 160, 175))
        ly = self.lyric(t)
        if ly: d.text((24, sy + 68), '>>> print("%s")' % ly, font=self.fs, fill=(126, 231, 135))
        d.text((W - 150, 40), '● t %05.1f' % t, font=self.fs, fill=(88, 166, 255))
        d.text((W - 24, sy + 30), self.label, font=self.fs, fill=(150, 160, 175), anchor='ra')   # in the status bar, inside the safe area (at (24, 40) it sat under the top bar)
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.voxels, 'voxels'); return
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
Video.frame = _polish.wrap(Video.frame, 'pixel')      # glow, grain, vignette: studio/polish.py
