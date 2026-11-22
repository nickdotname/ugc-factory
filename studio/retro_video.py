#!/usr/bin/env python3
"""retro.vibes.arcade: retro CGI worlds (made by studio/retro_gen.py on Kaggle) cut to the song.

    python studio/retro_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/retro_video.py SONG_DIR SEED SHEET.png --frames 0,40,80   (a contact sheet instead of a video)

The nightly job's renderer for the "retro" style (studio/nightly.py). Clips come from the retro library and are cut
on the bar lines of the song (every bar or every two). Knobs (studio/knobs.py), so the learner finds what people watch:
  theme   which worlds: arcade, mall, pool, screensaver, aero, space, city, toys, dream, desk, water, drive, or mixed
  screen  how the picture is shown: crt (scanlines, bloom, curved glass), vhs (chroma bleed, tracking noise on the
          snare), dither (a 1997 console's palette and pixels), clean (the render as it is, with bloom)
  frame   what sits over it: player (a glossy media player of our own design with a spectrum that moves with the
          stems), osd (a VCR's PLAY and counter), none
  cut     how a clip gives way to the next: hard, flash (a white pop on the downbeat), slide (the old clip pushed off)
  pace    1 or 2 bars per clip
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import retro_gen as lib

W, H, FPS = 1080, 1920, 30
THEMES = ['arcade', 'mall', 'pool', 'screensaver', 'aero', 'space', 'city', 'toys', 'dream', 'desk', 'water', 'drive', 'mixed']
SCREENS = ['crt', 'vhs', 'dither', 'clean']
FRAMES = ['player', 'osd', 'none']
CUTS = ['hard', 'flash', 'slide']


def font(size, bold=True, mono=False):
    names = (['DejaVuSansMono-Bold.ttf', 'DejaVuSansMono.ttf'] if mono else ['DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'])
    for n in names:
        for d in (os.path.join(REPO, 'fonts'), '/usr/share/fonts/truetype/dejavu'):
            p = os.path.join(d, n)
            if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class Clips:
    """Which clip plays when (a new one on each cut), and its frames scaled and cropped to the vertical frame."""
    def __init__(self, entries, cuts, n, rng):
        self.rng = rng; self.cache = {}; self.cuts = cuts
        pool = entries[:]; rng.shuffle(pool)
        by = {}                                                    # no two neighbours from the same scene
        for e in pool: by.setdefault((e['theme'], e['scene']), []).append(e)
        order = []; last = None
        while any(by.values()):
            keys = [k for k, v in by.items() if v and k != last] or [k for k, v in by.items() if v]
            k = max(keys, key=lambda k: (len(by[k]), rng.random())); order.append(by[k].pop()); last = k
        self.plan = []
        for j, c in enumerate(cuts):
            e = order[j % len(order)]; seg = (cuts[j + 1] if j + 1 < len(cuts) else n) - c
            cap = cv2.VideoCapture(os.path.join(lib.CACHE, e['asset'])); total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 150; cap.release()
            self.plan.append((c, e, rng.randrange(0, max(1, total - seg)), rng.uniform(1.0, 1.08), rng.uniform(-0.12, 0.12)))

    def seg(self, i):
        return max(j for j, p in enumerate(self.plan) if p[0] <= i)

    def frames(self, j):
        if j not in self.cache:
            for old in [k for k in self.cache if k < j - 1]: del self.cache[old]
            c, e, off, _z, _p = self.plan[j]; want = (self.plan[j + 1][0] if j + 1 < len(self.plan) else c + 600) - c
            cap = cv2.VideoCapture(os.path.join(lib.CACHE, e['asset'])); cap.set(cv2.CAP_PROP_POS_FRAMES, off); fr = []
            while True:
                ok, f = cap.read()
                if not ok: break
                fr.append(f)
                if len(fr) >= min(want, 400): break
            cap.release()
            if not fr: fr = [np.zeros((832, 480, 3), np.uint8)]
            while len(fr) < want: fr += fr[::-1][1:] or fr       # a short clip plays on, back and forth
            self.cache[j] = fr
        return self.cache[j]

    def frame(self, i, j=None):
        j = self.seg(i) if j is None else j
        c, e, off, zoom, pan = self.plan[j]; fr = self.frames(j); f = fr[min(i - c, len(fr) - 1)] if i >= c else fr[0]
        h, w = f.shape[:2]; s = max(W / w, H / h) * zoom * (1 + 0.035 * max(0, i - c) / max(1, len(fr)))   # slow push-in
        f = cv2.resize(f, (int(w * s) + 1, int(h * s) + 1), interpolation=cv2.INTER_CUBIC)
        x0 = int((f.shape[1] - W) * (0.5 + pan)); y0 = (f.shape[0] - H) // 2
        x0 = max(0, min(x0, f.shape[1] - W))
        return np.ascontiguousarray(f[y0:y0 + H, x0:x0 + W]), j, e


# precomputed screens
YY, XX = np.mgrid[0:H, 0:W].astype(np.float32)
SCAN = (0.78 + 0.22 * (np.cos(YY[:, :1] * (2 * math.pi / 4.0)) * 0.5 + 0.5))[..., None].astype(np.float32)   # a dark line every 4 px
_nx, _ny = (XX - W / 2) / (W / 2), (YY - H / 2) / (H / 2); _r2 = _nx ** 2 + _ny ** 2
VIGNETTE = np.clip(1.08 - 0.42 * _r2, 0.35, 1)[..., None].astype(np.float32)
BX = (W / 2 + _nx * (1 + 0.045 * _r2) * (W / 2) * 0.985).astype(np.float32)      # the curve of the glass
BY = (H / 2 + _ny * (1 + 0.045 * _r2) * (H / 2) * 0.985).astype(np.float32)
CRT_MASK = np.repeat(SCAN * VIGNETTE * 1.12, 3, axis=2).astype(np.float32)   # scanlines and vignette in one multiply
VHS_MASK = np.repeat(VIGNETTE ** 0.5, 3, axis=2).astype(np.float32)
BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16 - 0.5)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.theme = K.pick('theme', THEMES, r); self.screen = K.pick('screen', SCREENS, r)
        self.frame_kind = K.pick('frame', FRAMES, r); self.cut = K.pick('cut', CUTS, r); self.pace = int(K.pick('pace', [1, 2], r))
        lib_ = lib.pull(() if self.theme == 'mixed' else (self.theme,))
        if len({(e['theme'], e['scene']) for e in lib_}) < 3: lib_ = lib.pull(())
        if not lib_: sys.exit('the retro library is empty: run the retro workflow first')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 7.0); self.snare = audio.hits(a['snares'], n, 9.0)
        sm = lambda x: np.convolve(x, np.ones(4) / 4, 'same')
        self.bands = [sm(a['bass']), sm(a['drums']), sm(a['other']), sm(a['vocals'])]
        bars = [int(round(f)) for b, f in a['beats'] if b % (4 * self.pace) == 0 and 0 < f < n - FPS]
        cuts = [0] + [c for c in bars if c > FPS * 0.8]
        if len(cuts) < 2:                                          # no grid here: every 2 s
            cuts = list(range(0, n, 2 * FPS))
        self.cuts = cuts; self.clips = Clips(lib_, cuts, n, r)
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.title = song.get('title', self.slug); self.artist = song.get('artist', 'Close Quarters')
        self.credit = '♪ %s — %s' % (self.title.lower(), self.artist.lower())
        self.f_credit, self.f_ui, self.f_ui_s, self.f_osd = font(30), font(30), font(24, False), font(46, mono=True)
        self.spec = np.zeros(20); self.peak = np.zeros(20); self.marquee = 0.0
        self.chrome = self.player_skin() if self.frame_kind == 'player' else None

    # ---------------------------------------------------------------- screens
    def bloom(self, img, amt):
        hi = np.maximum(cv2.resize(img, (W // 4, H // 4), interpolation=cv2.INTER_AREA) - 170, 0)   # glow worked out small: same look, far faster
        glow = cv2.resize(cv2.GaussianBlur(hi, (0, 0), 4.5), (W, H), interpolation=cv2.INTER_LINEAR)
        return cv2.scaleAdd(glow, float(amt), img)

    def screen_fx(self, img, i):
        if self.screen == 'crt':
            img = self.bloom(img, 0.9 + 0.6 * self.kick[i])
            sh = 2 + int(3 * self.kick[i]); b, g, r = cv2.split(img)
            r[:, sh:] = r[:, :-sh].copy(); b[:, :-sh] = b[:, sh:].copy()   # red and blue a few pixels apart, more on the kick
            img = cv2.multiply(cv2.merge((b, g, r)), CRT_MASK)
            return cv2.remap(img, BX, BY, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        if self.screen == 'vhs':
            ycc = cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2YCrCb).astype(np.float32)
            for c in (1, 2): ycc[..., c] = np.roll(cv2.blur(ycc[..., c], (21, 3)), 9, axis=1)       # colour smears to the right
            img = cv2.cvtColor(np.clip(ycc, 0, 255).astype(np.uint8), cv2.COLOR_YCrCb2BGR).astype(np.float32)
            img = self.bloom(img, 0.5)
            band = int((i * 7) % (H + 300)) - 150; amt = 0.25 + 1.4 * self.snare[i]               # the tracking line, worse on the snare
            g = np.random.default_rng(i)
            for y in range(max(0, band), min(H, band + int(40 + 140 * self.snare[i])), 3):
                img[y:y + 3] = np.roll(img[y:y + 3], int(g.integers(-30, 30) * amt), axis=1) + g.normal(0, 30 * amt)
            img[H - 46:] = np.roll(img[H - 46:], int(g.integers(20, 60)), axis=1) * 0.8 + g.normal(0, 18, (46, W, 1))   # head switching
            if self.kick[i] > 0.85: img = np.roll(img, int(g.integers(-6, 6)), axis=0)
            return cv2.multiply(img, VHS_MASK)
        if self.screen == 'dither':
            s = cv2.resize(img, (W // 3, H // 3), interpolation=cv2.INTER_AREA)
            th = np.tile(BAYER, (s.shape[0] // 4 + 1, s.shape[1] // 4 + 1))[:s.shape[0], :s.shape[1], None]
            lv = 5.0                                                     # 6 levels per channel: a 216-colour palette
            q = np.floor(np.clip(s / 255 * lv + th * 0.9 + 0.5, 0, lv)) / lv * 255
            img = cv2.resize(q.astype(np.float32), (W, H), interpolation=cv2.INTER_NEAREST)
            return self.bloom(img, 0.35)
        return self.bloom(img, 0.7 + 0.5 * self.kick[i])

    # ---------------------------------------------------------------- overlays
    def player_skin(self):
        """A glossy media-player bar of our own design (no product's skin): rounded chrome, a blue glass display."""
        # It sits above the bottom fifth, which Instagram covers with the caption and buttons.
        X0, Y0 = 110, H - 790; bw_, bh_ = W - 220, 310
        sk = Image.new('RGBA', (bw_ + 16, bh_ + 16), (0, 0, 0, 0)); d = ImageDraw.Draw(sk)
        x0, y0, x1, y1 = 0, 0, bw_, bh_
        d.rounded_rectangle([x0 + 8, y0 + 12, x1 + 8, y1 + 12], 46, fill=(0, 0, 0, 90))
        body = Image.new('RGBA', (bw_, bh_)); bd = ImageDraw.Draw(body)
        for k in range(bh_):                                        # brushed chrome, lighter at the top
            t = k / bh_; c = int(232 - 70 * t + 18 * math.sin(t * 9))
            bd.line([0, k, bw_, k], fill=(c, c, min(255, c + 12), 238))
        m = Image.new('L', (bw_, bh_), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, bw_ - 1, bh_ - 1], 46, fill=238)
        body.putalpha(m); sk.alpha_composite(body)
        d = ImageDraw.Draw(sk)
        d.rounded_rectangle([x0, y0, x1, y1], 46, outline=(255, 255, 255, 200), width=3)
        d.rounded_rectangle([x0 + 34, y0 + 30, x1 - 34, y0 + 200], 22, fill=(8, 22, 60, 255), outline=(120, 170, 255, 255), width=3)
        d.rounded_rectangle([x0 + 40, y0 + 36, x1 - 40, y0 + 90], 18, fill=(255, 255, 255, 28))          # glass shine
        cy = y0 + 255
        for k, cx in enumerate((W / 2 - 170, W / 2, W / 2 + 170)):                                         # prev, play, next
            rr = 46 if k == 1 else 36
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(70, 120, 230, 255), outline=(255, 255, 255, 230), width=3)
            d.ellipse([cx - rr + 8, cy - rr + 5, cx + rr - 8, cy - 2], fill=(255, 255, 255, 70))
            if k == 1: d.polygon([(cx - 14, cy - 20), (cx - 14, cy + 20), (cx + 22, cy)], fill=(255, 255, 255, 255))
            else:
                s = -1 if k == 0 else 1
                for o in (0, 16): d.polygon([(cx - s * 14 + s * o, cy - 14), (cx - s * 14 + s * o, cy + 14), (cx + s * 2 + s * o, cy)], fill=(255, 255, 255, 255))
        self.at = (X0, Y0); self.box = (X0, Y0, X0 + bw_, Y0 + bh_); return sk

    def spectrum(self, i):
        b, dr, o, v = (x[i] for x in self.bands); g = np.random.default_rng(i // 2)
        shape = np.concatenate([np.full(5, b), np.full(5, 0.6 * dr + 0.4 * b), np.full(5, o), np.full(5, 0.5 * v + 0.5 * o)])
        tgt = np.clip(shape * (0.75 + 0.5 * g.random(20)) + 0.35 * self.kick[i] * (np.arange(20) < 6), 0, 1)
        self.spec = np.maximum(tgt, self.spec * 0.82); self.peak = np.maximum(self.spec, self.peak - 0.025); return self.spec

    def overlay(self, im, i):
        d = ImageDraw.Draw(im); t = self.t0 + i / FPS
        if self.frame_kind == 'player':
            im.paste(self.chrome, self.at, self.chrome); d = ImageDraw.Draw(im); x0, y0, x1, y1 = self.box
            sp = self.spectrum(i); bw = (x1 - x0 - 120) / 20
            for k in range(20):                                       # the spectrum, in the glass display
                bx = x0 + 60 + k * bw; top = y0 + 185 - sp[k] * 120
                for yy in range(int(y0 + 185), int(top), -8):
                    c = (90, 230, 255, 255) if yy > y0 + 130 else (150, 255, 200, 255) if yy > y0 + 95 else (255, 120, 200, 255)
                    d.rectangle([bx + 3, yy - 5, bx + bw - 3, yy], fill=c)
                py = y0 + 185 - self.peak[k] * 120; d.rectangle([bx + 3, py - 3, bx + bw - 3, py], fill=(255, 255, 255, 255))
            txt = '%s  ·  %s  ·  ' % (self.title.upper(), self.artist.upper()); tw = d.textlength(txt, font=self.f_ui)
            self.marquee = (self.marquee + 2.2) % tw
            disp = Image.new('RGBA', (x1 - x0 - 100, 40), (0, 0, 0, 0)); dd = ImageDraw.Draw(disp)
            for k in range(3): dd.text((-self.marquee + k * tw, 0), txt, font=self.f_ui, fill=(150, 220, 255, 255))
            im.paste(disp, (x0 + 50, y0 + 44), disp)
            d.text((x1 - 70, y0 + 255), '%d:%02d' % (t // 60, t % 60), font=self.f_ui_s, fill=(30, 40, 80, 255), anchor='rm')
        elif self.frame_kind == 'osd':
            if (i // 20) % 4 != 3: d.text((70, 120), 'PLAY ▶', font=self.f_osd, fill=(245, 245, 245, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
            d.text((W - 70, 120), 'CH 03', font=self.f_osd, fill=(245, 245, 245, 255), anchor='ra', stroke_width=3, stroke_fill=(0, 0, 0, 255))
            d.text((70, H - 560), 'SP  %d:%02d:%02d' % (t // 3600, (t // 60) % 60, t % 60), font=self.f_osd, fill=(245, 245, 245, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
        if self.frame_kind != 'player':
            d.text((W / 2, H - 440), self.credit, font=self.f_credit, fill=(240, 240, 240, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0, 255))

    # ---------------------------------------------------------------- one frame
    def frame(self, i):
        f, j, e = self.clips.frame(i); img = f.astype(np.float32)
        c = self.clips.plan[j][0]; since = i - c
        if j > 0 and since < 8:
            if self.cut == 'flash': img = img + (255 - img) * (1 - since / 8) ** 2 * 0.85
            elif self.cut == 'slide':
                p, _jj, _e = self.clips.frame(i, j - 1); x = int(W * (1 - (1 - since / 8) ** 3))
                img = np.concatenate([p.astype(np.float32)[:, x:], img[:, :x]], axis=1) if x < W else img
        img *= 1 + 0.10 * self.kick[i]
        img = self.screen_fx(img, i)
        g = np.random.default_rng(i).normal(0, 5, (H // 3, W // 3)).astype(np.float32)
        img += cv2.resize(g, (W, H), interpolation=cv2.INTER_NEAREST)[..., None]
        im = Image.fromarray(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB))
        self.overlay(im, i)
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            want = set(fs); ims = []
            for i in range(max(fs) + 1):
                fr = self.frame(i)
                if i in want: ims.append(Image.fromarray(fr).resize((360, 640)))
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 60 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        used = sorted({e['asset'] for _, e, *_r in self.clips.plan})
        json.dump(dict(K.record(), clips=used), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
