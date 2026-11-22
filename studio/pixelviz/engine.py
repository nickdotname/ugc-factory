"""Isometric pixel worlds that move to the music (a style of the ASCII / creative-coding account).

A scene (bridge.py, court.py) builds its world out of voxels and says what moves; this draws the world once onto a
270 x 480 canvas, draws the moving parts on top every frame, and blows the canvas up with hard pixel edges. The
camera cuts between a wide shot and close-ups on bar lines, and the opening line, the world card and the song credit
sit on top. Every look choice is a knob (studio/knobs.py), so the learner finds out what gets watched.
"""
import json, math, os, subprocess, sys, importlib, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); STUDIO = os.path.dirname(HERE); REPO = os.path.dirname(STUDIO)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(STUDIO, 'mathviz')); sys.path.insert(0, STUDIO)
import beat as audio
import knobs as K
from vox import Canvas, upscale

W, H, FPS = 1080, 1920, 30
LW, LH, BASE = 270, 480, 4                              # the pixel canvas, blown up four times
FONTS = os.path.join(REPO, 'fonts')
BOLD = os.path.join(FONTS, 'Poppins-Bold.ttf'); MONO = os.path.join(FONTS, 'DejaVuSansMono-Bold.ttf')
BGS = {'night': (16, 15, 30), 'ink': (10, 12, 18), 'plum': (24, 14, 32)}
HOOKS = ["This isn't drawn.", 'Every pixel is code.', 'No sprites. No images.']


class Video:
    def __init__(self, scene, song_dir, seed, t0, t1, world_no=1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        r = random.Random(seed); self.rng = np.random.default_rng(seed)
        self.bg = BGS[K.pick('pixel_bg', sorted(BGS), r)]
        self.hook = K.pick('pixel_hook', HOOKS, r)
        self.cuts = K.pick('pixel_cuts', ['bars', 'none'], r)
        self.SC = importlib.import_module(scene)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        E = dict(n=n, spb=a['spb'], beats=a['beats'], kicks=a['kicks'], snares=a['snares'], hats=a['hats'],
                 kick=audio.hits(a['kicks'], n, 7.0), snare=audio.hits(a['snares'], n, 9.0), hat=audio.hits(a['hats'], n, 14.0),
                 bass=a['bass'], seed=seed)
        downs = [int(round(f)) for b, f in a['beats'] if b % 4 == 0 and f >= 0]
        E['downs'] = downs
        E['big'] = min(downs, key=lambda f: abs(f - 0.45 * n)) if downs else None
        self.E = E
        self.world = self.SC.build(self.rng); self.SC.setup(E, self.rng)
        cv = Canvas(LW, LH, getattr(self.SC, 'OX', LW // 2), getattr(self.SC, 'OY', 170), self.bg)
        self.voxels = cv.world(self.world); self.static = cv
        yy, xx = np.mgrid[0:LH, 0:LW]
        self.dots = ((xx % 6 == 3) & (yy % 6 == 3))
        self.label = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.world_no = world_no
        self.f_hook = ImageFont.truetype(BOLD, 92); self.f_small = ImageFont.truetype(MONO, 26)
        self.f_px = ImageFont.truetype(MONO, 9); self.f_px2 = ImageFont.truetype(MONO, 8)
        self.shots = self.plan(downs)

    def plan(self, downs):
        """The cut list: open close on the scene's first focus, cut wide on the first bar line after the hook, then every
        two bars cut between close-ups and the wide shot."""
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

    def frame(self, i):
        t = i / FPS; SC = self.SC; E = self.E
        cv = self.static.copy()
        info = SC.dynamic(cv, i, E)
        rgb = cv.rgb
        if hasattr(SC, 'water'): rgb = SC.water(cv, rgb, i, E)
        empty = cv.key < 0
        rgb[empty & self.dots] = np.array(self.bg, np.float32) * 1.0 + 22
        rgb = np.clip(rgb, 0, 255)
        # the pixel card: drawn at canvas size so its letters are pixels too
        card = Image.new('RGBA', (LW, LH), (0, 0, 0, 0)); d = ImageDraw.Draw(card)
        cy = 372
        d.rectangle([20, cy, 196, cy + 30], fill=(36, 36, 58, 235), outline=(120, 120, 150, 255))
        d.text((26, cy + 4), 'WORLD %02d / %s' % (self.world_no, SC.NAME), font=self.f_px, fill=(235, 235, 245, 255))
        d.text((26, cy + 17), SC.PLACE, font=self.f_px2, fill=(170, 170, 190, 255))
        d.text((20, cy + 38), SC.stats(i, E, info, self.voxels), font=self.f_px2, fill=(120, 124, 150, 255))
        focus = self.shot(i)
        if focus is None:
            big = upscale(rgb, BASE)
        else:
            sc = 6; cw, ch = W // sc, H // sc
            fx, fy = cv.screen(*focus); x0 = int(np.clip(fx - cw / 2, 0, LW - cw)); y0 = int(np.clip(fy - ch / 2, 0, LH - ch))
            big = upscale(rgb[y0:y0 + ch, x0:x0 + cw], sc)[:H, :W]
        big = np.ascontiguousarray(big[:H, :W]).astype(np.uint8)
        im = Image.fromarray(big)
        if focus is None:
            ca = card.resize((W, H), Image.NEAREST); im.paste(ca, (0, 0), ca)
        dd = ImageDraw.Draw(im)
        if t < 2.6:                                       # the opening line, typed in word by word on the beat
            words = self.hook.split(' '); k = min(len(words), 1 + int(t / max(0.25, E['spb'] * 0.75)))
            dd.text((W / 2, 300), ' '.join(words[:k]), font=self.f_hook, fill=(242, 240, 232), anchor='mm', stroke_width=6, stroke_fill=(14, 14, 24))
        if t > self.n / FPS - 2.2:
            dd.text((W / 2, 300), 'follow for world %02d' % (self.world_no + 1), font=ImageFont.truetype(BOLD, 64), fill=(242, 240, 232), anchor='mm', stroke_width=5, stroke_fill=(14, 14, 24))
        dd.text((W / 2, H - 70), self.label, font=self.f_small, fill=(150, 150, 170), anchor='mm')
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
