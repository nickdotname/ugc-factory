#!/usr/bin/env python3
"""retro.vibes.arcade: PS2-era game worlds and cutscene CGI (made by studio/retro_gen.py on Kaggle) cut to the song.

    python studio/retro_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/retro_video.py SONG_DIR SEED SHEET.png --frames 0,40,80   (a contact sheet instead of a video)

The nightly job's renderer for the "retro" style (studio/nightly.py). Clips come from the retro library and are cut
on the bar lines of the song (every bar or every two). Knobs (studio/knobs.py), so the learner finds what people watch:
  theme   which worlds (the themes of studio/retro/prompts.json: racing, skate, hub, town, city, ...), or mixed
  screen  how the picture is shown: ps2 (480i: soft, 15-bit colour, interlace combing on movement), crt (scanlines,
          bloom, curved glass), vhs (chroma bleed, tracking noise on the snare), clean (the render as it is, with bloom)
  frame   what sits over it: osd (a VCR's PLAY and counter, inside Instagram's safe area), none. (The glossy media
          player skin was retired 2026-11-24: it covered a sixth of the picture and read as a widget, not a world.)
  trans   how a clip gives way to the next: hard, flash (a white pop on the downbeat), slide (the old clip pushed off),
          dissolve (half a beat of crossfade). Named trans, not cut: nightly records its own `cut` (full/tight/short
          length) over the renderer's, so a knob called cut was never learned.
  pace    1 or 2 bars per clip (spot always 1: a "pick one" needs at least three places)
  hook    a line over the picture, the kind people send to a friend: spot (a question about the places: "pick one to
          live in"; each place gets a number so there is something to answer with), memory (a line about having been
          here: "you were here at 2am in 2004"), none. Questions only: never "comment", "tag" or "send this".
          (smoke, "where would you smoke?", was retired 2026-11-24: Instagram's recommendation guidelines hold back
          content that promotes tobacco or cannabis, and a strike there costs the whole account its reach.)

Clips listed in studio/retro/rejects.json (smeared, melted or not the look) are never used. The first place is one
of the clips that moves most, so frame 0 is already moving; a clip shorter than its bar is slowed to fit instead of
played backwards; the last few frames fade back into frame 0 so the video loops without a jump.
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
THEMES = list(json.load(open(lib.PROMPTS))['themes']) + ['mixed']
SCREENS = ['ps2', 'crt', 'vhs', 'clean']
FRAMES = ['osd', 'none']
# A "pick one" line has to fit what is on screen: nobody "lives" on a race track. So a spot video stays inside one
# theme and its line is that theme's; if the theme has too few places (or is mixed) the line is a neutral one.
SPOT = {
    'racing': ["pick your track", "you get one lap. which track?", "which one are you racing on?", "pick the circuit you'd never get bored of"],
    'skate': ["pick your skate spot", "which park are you skating first?", "one spot, all summer. which?"],
    'hub': ["pick a world to live in", "which island is yours?", "pick the world you'd never leave"],
    'town': ["pick the town you'd move to", "which street do you live on?", "pick the town you'd grow up in"],
    'city': ["pick a city to get lost in", "which city are you walking at 2am?", "pick your city"],
    'mall': ["pick your mall", "which mall are you spending saturday in?", "pick where you'd hang out after school"],
    'pool': ["pick your pool", "which one are you swimming in?", "pick the pool you'd have all to yourself"],
    'arcade': ["pick where you're spending friday night", "which one are you spending your quarters in?"],
    'space': ["pick your station", "which one are you launching from?", "pick where you'd spend a year in space"],
    'beach': ["pick your beach", "which one are you watching the sunset from?", "pick your summer"],
    'snow': ["pick your mountain", "which run are you taking first?", "pick where you're snowed in"],
    'water': ["which one are you diving into?", "pick where you'd explore first"],
    'impossible': ["which dream are you walking into?", "pick the one you've dreamed about", "which door are you opening?"],
    'aero': ["pick a world to live in", "which one was your desktop?", "pick the world you'd log into"],
}
SPOT_ANY = ["pick a level", "which level are you loading first?", "pick your save file", "which one are you playing first?"]
HOOKS = {'memory': ["you were here at 2am in 2004", "the level you never wanted to leave", "memory card slot 1 · 47 hours",
                    "this loaded while dinner went cold", "nobody else remembers this level"]}
TRANS = ['hard', 'flash', 'slide', 'dissolve']
REJECTS = os.path.join(HERE, 'retro', 'rejects.json')


def font(size, bold=True, mono=False):
    names = (['DejaVuSansMono-Bold.ttf', 'DejaVuSansMono.ttf'] if mono else ['DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'])
    for n in names:
        for d in (os.path.join(REPO, 'fonts'), '/usr/share/fonts/truetype/dejavu'):
            p = os.path.join(d, n)
            if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class Clips:
    """Which clip plays when (a new one on each cut), and its frames scaled and cropped to the vertical frame."""
    def __init__(self, entries, cuts, n, rng, kick):
        self.rng = rng; self.cache = {}; self.cuts = cuts; self.n = n; self.kick = kick
        pool = entries[:]; rng.shuffle(pool)
        by = {}                                                    # no two neighbours from the same scene
        for e in pool: by.setdefault((e['theme'], e['scene']), []).append(e)
        order = []; last = None
        while any(by.values()):
            keys = [k for k, v in by.items() if v and k != last] or [k for k, v in by.items() if v]
            k = max(keys, key=lambda k: (len(by[k]), rng.random())); order.append(by[k].pop()); last = k
        # frame 0 is the hook: open on one of the clips that moves most (an index's motion is the mean frame-to-frame
        # change; above ~6 it is usually a smear, so those are passed over when there is a choice)
        lively = sorted(order, key=lambda e: -min(e.get('motion', 0), 6 - 0.5 * max(0, e.get('motion', 0) - 6)))[:3]
        if lively:
            first = rng.choice(lively); order.remove(first); order.insert(0, first)
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
            self.cache[j] = fr                                   # a short clip is slowed to fit (frame()), never reversed
        return self.cache[j]

    def want(self, j):
        return (self.plan[j + 1][0] if j + 1 < len(self.plan) else self.n) - self.plan[j][0]

    def pick(self, j, k):
        """Frame k of segment j: as recorded while the clip lasts; a clip shorter than its bar plays slower, blended."""
        fr = self.frames(j); want = self.want(j)
        if len(fr) >= want or len(fr) < 2: return fr[min(k, len(fr) - 1)].astype(np.float32)
        x = min(k * (len(fr) - 1) / max(1, want - 1), len(fr) - 1); a = int(x); b = min(a + 1, len(fr) - 1); t = x - a
        return fr[a].astype(np.float32) * (1 - t) + fr[b].astype(np.float32) * t

    def frame(self, i, j=None):
        j = self.seg(i) if j is None else j
        c, e, off, zoom, pan = self.plan[j]; f = self.pick(j, max(0, i - c))
        h, w = f.shape[:2]
        s = max(W / w, H / h) * zoom * (1 + 0.07 * max(0, i - c) / max(1, self.want(j))) * (1 + 0.012 * self.kick[i])  # push-in, a nudge on the kick
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
PS2_MASK = np.repeat((0.9 + 0.1 * (np.arange(H) // 3 % 2 == 0))[:, None, None] * np.ones((1, W, 1)) * VIGNETTE ** 0.35 * 1.02, 3, axis=2).astype(np.float32)
BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16 - 0.5)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.theme = K.pick('theme', THEMES, r); self.screen = K.pick('screen', SCREENS, r)
        self.frame_kind = K.pick('frame', FRAMES, r); self.cut = K.pick('trans', TRANS, r); self.pace = int(K.pick('pace', [1, 2], r))
        self.hook = K.pick('hook', ['spot', 'memory', 'none'], r, weights=[4, 2, 2])
        if self.hook == 'spot' and self.pace != 1:                 # a "pick one" needs at least three places to pick from
            self.pace = 1; K.CHOSEN['pace'] = '1'
        bad = set(json.load(open(REJECTS)).get('clips', {})) if os.path.exists(REJECTS) else set()
        lib_ = [e for e in lib.pull(() if self.theme == 'mixed' else (self.theme,)) if e['asset'] not in bad]
        if len({(e['theme'], e['scene']) for e in lib_}) < 3:
            every = [e for e in lib.pull(()) if e['asset'] not in bad]
            full = sorted({t for t in {e['theme'] for e in every} if len({e['scene'] for e in every if e['theme'] == t}) >= 3})
            if self.hook == 'spot' and full:                       # a "pick one" stays in one theme that has 3+ places
                self.theme = r.choice(full); K.CHOSEN['theme'] = self.theme
                lib_ = [e for e in every if e['theme'] == self.theme]
            else:
                lib_ = every
        themes = {e['theme'] for e in lib_}
        if self.hook == 'spot':                                    # the line has to fit the places on screen
            only = next(iter(themes)) if len(themes) == 1 else None
            self.line = r.choice(SPOT.get(only, SPOT_ANY))
        else:
            self.line = r.choice(HOOKS[self.hook]) if self.hook != 'none' else ''
        if not lib_: sys.exit('the retro library is empty: run the retro workflow first')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 7.0); self.snare = audio.hits(a['snares'], n, 9.0)
        sm = lambda x: np.convolve(x, np.ones(4) / 4, 'same')
        self.bands = [sm(a['bass']), sm(a['drums']), sm(a['other']), sm(a['vocals'])]
        bars = [int(round(f)) for b, f in a['beats'] if b % (4 * self.pace) == 0 and 0 < f < n - FPS]
        cuts = [0] + [c for c in bars if c > FPS * 0.8]
        if len(cuts) < 2:                                          # no grid here: every 2 s
            cuts = list(range(0, n, 2 * FPS))
        self.cuts = cuts; self.clips = Clips(lib_, cuts, n, r, self.kick); self.first = None
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.title = song.get('title', self.slug); self.artist = song.get('artist', 'Close Quarters')
        self.credit = '♪ %s — %s' % (self.title.lower(), self.artist.lower())
        self.f_credit, self.f_osd = font(30), font(46, mono=True)
        self.f_hook, self.f_num = font(68), font(120)
        seen = []                                                  # each place's number, in the order it first appears
        for _c, e, *_ in self.clips.plan:
            if e['asset'] not in seen: seen.append(e['asset'])
        self.number = {a: k + 1 for k, a in enumerate(seen)}
        self.prev_small = None

    # ---------------------------------------------------------------- screens
    def bloom(self, img, amt):
        # a bright picture (a white mall, a sunlit pool) blooms to a white sheet: the brighter it is, the less glow
        amt = amt * float(np.clip(1.7 - img[::16, ::16].mean() / 95.0, 0.15, 1.0))
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
        if self.screen == 'ps2':                                         # what a 2002 console put out: 480 lines, interlaced, 15-bit colour
            s = cv2.resize(img, (360, 640), interpolation=cv2.INTER_AREA)
            th = np.tile(BAYER, (160, 90))[..., None]
            s = np.floor(np.clip(s / 8 + th * 0.6 + 0.5, 0, 31)) * (255 / 31)               # 32 levels a channel, lightly dithered
            if self.prev_small is not None:                              # a field from the frame before: combing wherever things move
                s[(i % 2)::2] = s[(i % 2)::2] * 0.55 + self.prev_small[(i % 2)::2] * 0.45
            self.prev_small = s.copy()
            img = cv2.resize(s.astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
            img = self.bloom(img, 0.8 + 0.5 * self.kick[i])
            return cv2.multiply(img, PS2_MASK)
        return self.bloom(img, 0.7 + 0.5 * self.kick[i])

    # ---------------------------------------------------------------- overlays
    def overlay(self, im, i):
        d = ImageDraw.Draw(im); t = self.t0 + i / FPS
        if self.frame_kind == 'osd':                                    # inside the safe area: below the top 250 px, left of the right 150 px
            if (i // 20) % 4 != 3: d.text((80, 262), 'PLAY ▶', font=self.f_osd, fill=(245, 245, 245, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
            d.text((W - 170, 262), 'CH 03', font=self.f_osd, fill=(245, 245, 245, 255), anchor='ra', stroke_width=3, stroke_fill=(0, 0, 0, 255))
            d.text((80, H - 560), 'SP  %d:%02d:%02d' % (t // 3600, (t // 60) % 60, t % 60), font=self.f_osd, fill=(245, 245, 245, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
        if self.line and (self.hook != 'memory' or i < 4.5 * FPS):          # a question stays up: someone can land on any second of a loop
            words = self.line.split(); half = len(words) // 2 + 1
            rows = [self.line] if d.textlength(self.line, font=self.f_hook) < W - 320 else [' '.join(words[:half]), ' '.join(words[half:])]
            y0h = 330 if self.frame_kind != 'osd' else 420
            for k, row in enumerate(rows):
                d.text((W / 2, y0h + k * 84), row, font=self.f_hook, fill=(255, 255, 255, 255), anchor='mm', stroke_width=7, stroke_fill=(0, 0, 0, 255))
            if self.hook == 'spot' and self.n - 1 - i >= 9:            # not over the fade back to place 1
                num = self.number.get(self.clips.plan[self.clips.seg(i)][1]['asset'], 1); y1 = y0h + len(rows) * 84 + 70
                d.text((W / 2, y1), str(num), font=self.f_num, fill=(255, 232, 80, 255), anchor='mm', stroke_width=8, stroke_fill=(0, 0, 0, 255))
        d.text((W / 2 - 75, H - 440), self.credit, font=self.f_credit, fill=(240, 240, 240, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0, 255))

    # ---------------------------------------------------------------- one frame
    def frame(self, i):
        f, j, e = self.clips.frame(i); img = f.astype(np.float32)
        c = self.clips.plan[j][0]; since = i - c
        if j > 0 and since < 8:
            if self.cut == 'flash': img = img + (255 - img) * (1 - since / 8) ** 2 * 0.85
            elif self.cut == 'dissolve' and since < 7:
                p, _jj, _e = self.clips.frame(i, j - 1); a = since / 7; img = p.astype(np.float32) * (1 - a) + img * a
            elif self.cut == 'slide':
                p, _jj, _e = self.clips.frame(i, j - 1); x = int(W * (1 - (1 - since / 8) ** 3))
                img = np.concatenate([p.astype(np.float32)[:, x:], img[:, :x]], axis=1) if x < W else img
        img *= 1 + 0.10 * self.kick[i]
        if i == 0: self.first = img.copy()
        tail = self.n - 1 - i                                     # the last frames fade back into frame 0: the loop has no seam
        if self.first is not None and tail < 9 and self.n > 3 * FPS: img = img + (self.first - img) * (1 - tail / 9) ** 1.5
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
