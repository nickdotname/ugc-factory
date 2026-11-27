#!/usr/bin/env python3
"""nyc.daily.aesthetic: New York as it looks today, cut on the beat of a Close Quarters song.

    python studio/nyc_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/nyc_video.py SONG_DIR SEED sheet.png --frames 0,40,140     (a contact sheet; CQ_FULL=1 also saves full frames)

The nightly job's renderer for the "nyc" style (studio/nightly.py). Footage: today's New York from Pexels (theme
nyc_now, the Pexels licence; places, not people) and Nick's own clips (theme nyc, source own); for the then-and-now
split, public-domain films of the same places (theme nyc: the Brooklyn Bridge in 1899, the East River in 1903). studio/nyc/places.json lists every clip as looked at by eye: what place it shows
(the label on screen), its mood, how well it opens a video, and the clips never to use (a person as the subject, a
trademark, a billboard about an election).

  kind   walk: full-screen city cut on the beat, a short line at the top for the first bars, the place's name
         and, for a landmark, its coordinates on each cut. meme: the white caption bar, its line written for one
         kind of shot (studio/nyc/memes.txt, `needs:` a places.json tag): the video opens on a clip with that tag,
         holds it for the first 2.4 s while the line is read, and cuts mostly to clips with the same tag, so the
         picture is the joke's second beat. walk and meme 1 : 1 (review 2026-11-26). thennow: the same place in an
         old film (top) and today (bottom): off until the old film is cleaned up and there are 5+ pairs. fact: a New
         York number over the city: retired 2026-11-25 (16 views vs meme 116).
  mood   night, sunset, snow, day: the opening clip and most of the cuts share it, and so does the line at the top
  look   the grade: cine (teal shadows, warm highlights), night (cool, crushed, lights bloom), film (warm, faded,
         grain), clean
  pace   beat2 (a cut every two beats) or bar (every bar; two beats whenever a bar is longer than 2.6 s)
Every video opens on a clip marked hero (a frame worth stopping for) and its last cut is the same clip running into
the first frame, so it loops. All text sits inside Instagram's safe area (x 96-930, y 250-1500).

The facts are ones that do not drift, checked on 2026-11-23 against the MTA (472 stations, 24/7), Guinness (Grand
Central's 44 platforms), NYC Planning (520 miles of waterfront), NYC Parks (1,700+ parks and facilities), the
Endangered Language Alliance (700-800 languages) and the Empire State Building's 410 days. Coordinates are
Wikipedia's for each landmark. If one is ever out of date, fix it here or in places.json.
"""
import json, os, random, subprocess, sys, zlib
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage

W, H, FPS = 1080, 1920, 30
SAFE_X0, SAFE_X1, SAFE_Y0, SAFE_Y1 = 96, 930, 250, 1500
PLACES = json.load(open(os.path.join(HERE, 'nyc', 'places.json')))['clips']

def memes(path=os.path.join(HERE, 'nyc', 'memes.txt')):
    """[(line, needs)] from studio/nyc/memes.txt: each line with the places.json tag its picture must show."""
    out = []
    for row in open(path, encoding='utf-8'):
        row = row.rstrip('\n')
        if not row.strip() or row.lstrip().startswith('#'): continue
        line, _, need = row.partition('needs:')
        out.append((line.strip(), need.strip()))
    return out


MEMES = memes()
# (number, how it is written, what it counts)
FACTS = [
    (843, '{:,.0f}', 'acres of central park'),
    (472, '{:,.0f}', 'subway stations. more than any other system on earth'),
    (24, '{:,.0f}/7', 'the subway never closes'),
    (102, '{:,.0f}', 'floors in the empire state building'),
    (410, '{:,.0f}', 'days it took to build the empire state building'),
    (700, '{:,.0f}+', 'languages spoken in new york'),
    (44, '{:,.0f}', 'platforms at grand central. the most of any station in the world'),
    (0, '${:,.0f}', 'to ride the staten island ferry'),
    (1904, '{:.0f}', 'the year the first subway line opened'),
    (1883, '{:.0f}', 'the year the brooklyn bridge opened'),
    (13.4, '{:.1f} MI', 'the length of manhattan'),
    (151, '{:,.0f} FT', 'statue of liberty, without the pedestal'),
    (1776, '{:,.0f} FT', 'one world trade center. on purpose'),
    (520, '{:,.0f} MI', 'of waterfront in new york city'),
    (1700, '{:,.0f}+', 'parks, playgrounds and rec centers in the five boroughs'),
]
# The line at the top of a walk, chosen by the opening clip's mood. No numbers, no asks.
HOOKS = {
    'night': ["new york after dark", "manhattan, still awake", "the walk home through midtown",
              "nights like this are why people stay", "this city doesn't do quiet"],
    'sunset': ["when the whole city turns gold", "the skyline right before the lights come on",
               "golden hour over manhattan", "every evening the city does this"],
    'snow': ["the city goes quiet when it snows", "new york, first snow", "snow on the fire escapes",
             "the one week new york slows down"],
    'day': ["new york doesn't look real sometimes", "the city you see when you finally look up",
            "a few seconds of new york", "manhattan on a clear day", "the buildings never get old"],
}
LOOKS = ['cine', 'night', 'film', 'clean']
MOODS = ['night', 'sunset', 'snow', 'day']
LUMA = np.array([0.114, 0.587, 0.299], np.float32)          # BGR


def ttf(name, size, var=None):
    p = os.path.join(REPO, 'fonts', name)
    f = ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()
    if var:
        try: f.set_variation_by_name(var)
        except Exception: pass
    return f


def wrap(txt, font, width):
    words, rows, cur = txt.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if font.getlength(t) <= width or not cur: cur = t
        else: rows.append(cur); cur = w
    return rows + ([cur] if cur else [])


def balanced(txt, font, width):
    """The line in as few rows as fit, the rows as even as they can be (no lone word on the last row)."""
    rows = wrap(txt, font, width)
    if len(rows) != 2: return rows
    words = txt.split()
    best = min(range(1, len(words)), key=lambda k: max(font.getlength(' '.join(words[:k])), font.getlength(' '.join(words[k:]))))
    return [' '.join(words[:best]), ' '.join(words[best:])]


def info(e):
    """What places.json says about a clip ({} when it was never looked at; own clips count as good openers)."""
    p = dict(PLACES.get(e['asset'], {}))
    if e.get('source') == 'own': p.setdefault('hero', 2)
    return p


def library():
    """(today's clips, old films): every usable New York clip, the skipped ones left out."""
    now = footage.pull(('nyc_now',)); old = footage.pull(('nyc',))
    today = [e for e in now + [o for o in old if o.get('source') == 'own'] if not info(e).get('skip')]
    films = [e for e in old if e.get('source') != 'own' and not info(e).get('skip') and info(e).get('pair')]
    return today, films


def nframes(e):
    cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset'])); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1; cap.release(); return n


class Reel:
    """One clip's frames for one cut: read once, cropped to the frame it fills (w x h), with a slow drift."""
    _box = {}

    def __init__(self, e, off, n, w, h, rng):
        self.w, self.h, self.n = w, h, n
        cap = cv2.VideoCapture(os.path.join(footage.CACHE, e['asset'])); cap.set(cv2.CAP_PROP_POS_FRAMES, off); fr = []
        while len(fr) < n:
            ok, f = cap.read()
            if not ok: break
            fr.append(f)
        cap.release()
        self.fr = fr or [np.zeros((h, w, 3), np.uint8)]
        self.box = self.content(e, self.fr[len(self.fr) // 2])
        self.z0, self.dz = rng.uniform(1.0, 1.04), rng.uniform(0.02, 0.05) * rng.choice([1, -1])
        self.px = rng.uniform(-0.12, 0.12)

    @classmethod
    def content(cls, e, f):
        """The part of the frame with picture in it (black bars a scan baked in are cut off)."""
        if e['asset'] in cls._box: return cls._box[e['asset']]
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY); rows = np.where(g.mean(1) > 14)[0]; cols = np.where(g.mean(0) > 14)[0]
        b = (0, 0, f.shape[1], f.shape[0])
        if len(rows) > g.shape[0] * 0.4 and len(cols) > g.shape[1] * 0.4: b = (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)
        cls._box[e['asset']] = b; return b

    def frame(self, j):
        """Frame j of this cut (a clip shorter than the cut is slowed, never played backwards)."""
        k = min(len(self.fr) - 1, int(j * len(self.fr) / self.n) if len(self.fr) < self.n else j)
        x0, y0, x1, y1 = self.box; f = self.fr[k][y0:y1, x0:x1]
        h, w = f.shape[:2]; t = j / max(1, self.n - 1)
        s = max(self.w / w, self.h / h) * (self.z0 + max(0, self.dz) * t + max(0, -self.dz) * (1 - t))
        f = cv2.resize(f, (int(w * s) + 2, int(h * s) + 2), interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)
        xs = int((f.shape[1] - self.w) * (0.5 + self.px)); ys = (f.shape[0] - self.h) // 2
        xs = max(0, min(xs, f.shape[1] - self.w))
        return f[ys:ys + self.h, xs:xs + self.w]


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        today, films = library()
        if len(today) < 3: sys.exit('no New York footage: run the footage workflow (theme nyc_now) first')
        pairs = sorted({info(e)['pair'] for e in films} & {info(e).get('pair') for e in today} - {None})
        # meme + walk 2:2 (docs/brain/reviews/2026-11-26/worlds.md §3): fact stays retired (nightly.yaml too), thennow is
        # off until its old film is levelled, sharpened and cropped and there are 5+ pairs (the 1899 bridge reads as mud)
        self.kind = K.pick('kind', ['walk', 'meme', 'thennow', 'fact'], r, weights=[1, 1, 0, 0])
        self.need = None
        if self.kind == 'meme':                                                     # the line first: it decides the picture
            tagged = {t for e in today for t in info(e).get('tags', ())}
            ok = [j for j, (_l, nd) in enumerate(MEMES) if nd in tagged] or list(range(len(MEMES)))
            want = K.FORCED.get('meme'); j = int(want) if want is not None and want.isdigit() and int(want) in ok else r.choice(ok)
            K.MENU['meme'] = [str(q) for q in ok]; K.CHOSEN['meme'] = str(j)
            self.text, self.need = MEMES[j]
            if self.need not in tagged: self.need = None
        mine = [e for e in today if self.need in info(e).get('tags', ())] if self.need else today
        have = {m: sum(1 for e in mine if info(e).get('mood') == m and (self.need or info(e).get('hero', 0) >= 2)) for m in MOODS}
        self.mood = K.pick('mood', MOODS, r, weights=[have[m] if self.need else (1 if have[m] else 0) for m in MOODS] if any(have.values()) else None)
        self.look = K.pick('look', LOOKS, r, weights=[2, 4, 1, 0] if self.mood == 'night' and self.kind != 'thennow' else [3, 0, 2, 1])   # the night grade turns daylight grey
        self.pace = K.pick('pace', ['beat2', 'bar'], r)
        self.pair = K.pick('pair', pairs or ['none'], r) if self.kind == 'thennow' else None
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 6.0)
        step = 2 if self.pace == 'beat2' or 4 * spb > 2.6 else 4
        first = int(2.4 * FPS) if self.kind == 'meme' else 8                       # a meme holds its first shot while the line is read
        self.cuts = sorted({0} | {int(round(fr)) for b, fr in a['beats'] if b % step == 0 and first <= fr <= n - 8})
        self.ends = self.cuts[1:] + [n]
        self.top_h = 952                                                             # thennow: the old film's half
        if self.kind == 'thennow':
            self.plan_old = self.plan([e for e in films if info(e).get('pair') == self.pair], old=True)
            self.plan_new = self.plan([e for e in today if info(e).get('pair') == self.pair])
        else:
            self.plan_old = []; self.plan_new = self.plan(today)
        self.fonts()
        if self.kind == 'meme':
            self.rows = wrap(self.text, self.f_meme, W - 150)
            self.panel = 268 + 76 * len(self.rows) + 40                              # the white bar, from the top
        elif self.kind == 'fact':
            self.fact = FACTS[r.randrange(len(FACTS))]; K.CHOSEN['fact'] = str(FACTS.index(self.fact)); K.MENU['fact'] = [str(j) for j in range(len(FACTS))]
        elif self.kind == 'walk':
            lines = HOOKS.get(info(self.plan_new[0][0]).get('mood') or 'day', HOOKS['day']); self.hook = lines[r.randrange(len(lines))]
            K.CHOSEN['hook'] = self.hook; K.MENU['hook'] = [h for v in HOOKS.values() for h in v]
        gr = np.random.default_rng(seed)
        self.grain = [cv2.resize(gr.normal(0, 1, (H // 2, W // 2)).astype(np.float32), (W, H)) for _ in range(4)]
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.vig = (1 - 0.32 * (((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)).clip(0.55, 1)[..., None]
        self.reels, self.layers = {}, {}
        y = np.arange(720, dtype=np.float32); self.scrim = (0.5 * np.clip(np.minimum((y - 140) / 160, (720 - y) / 260), 0, 1))[:, None, None]

    # ------------------------------------------------------------ which clip plays on which cut
    def plan(self, pool, old=False):
        """[(entry, offset)] per cut: a hero clip first, the mood's clips most, no clip or film twice in a row, and
        the last cut the opener again, ending on the frame the opener starts on (so the video loops)."""
        r = self.r; mood = self.mood
        lens = [b - a for a, b in zip(self.cuts, self.ends)]
        total = {e['asset']: nframes(e) for e in pool}
        if old:
            top = max(info(e).get('hero', 0) for e in pool); first = r.choice([e for e in pool if info(e).get('hero', 0) == top])
        else:
            mine = lambda e: self.kind == 'thennow' or info(e).get('mood') == mood
            heroes = [e for e in pool if info(e).get('hero', 0) >= 3 and mine(e)] or [e for e in pool if info(e).get('hero', 0) >= 2 and mine(e)] or \
                     sorted(pool, key=lambda e: -info(e).get('hero', 0))[:4]
            if self.need:                                                         # a meme opens on the thing its line is about
                fits = [e for e in pool if self.need in info(e).get('tags', ())]
                top = max(info(e).get('hero', 0) + (1 if mine(e) else 0) for e in fits)
                heroes = [e for e in fits if info(e).get('hero', 0) + (1 if mine(e) else 0) >= top - 1]
            first = r.choice(heroes)
        lo, hi = lens[-1], total[first['asset']] - lens[0]
        out = [(first, r.randint(lo, hi) if hi >= lo else max(0, hi))]
        used = {first['asset']: 1}
        for k in range(1, len(self.cuts)):
            last = k == len(self.cuts) - 1
            if last and k > 1 and out[0][1] >= lens[-1] and out[-1][0]['key'] != first['key']:
                out.append((first, out[0][1])); continue                              # the loop: back into frame 0
            prev = out[-1][0]
            cand = [e for e in pool if e['key'] != prev['key'] and (not last or e['key'] != first['key'])] or pool
            wts = [(10 if old or info(e).get('mood') == mood else 1) * (8 if self.need in info(e).get('tags', ()) else 1) *
                   (1 + info(e).get('hero', 0)) / (1 + 2 * used.get(e['asset'], 0)) for e in cand]
            e = r.choices(cand, weights=wts)[0]; used[e['asset']] = used.get(e['asset'], 0) + 1
            out.append((e, r.randrange(0, max(1, total[e['asset']] - lens[k]))))
        return out

    def seg(self, i):
        k = max(j for j, c in enumerate(self.cuts) if c <= i); return k, i - self.cuts[k]

    def reel(self, which, k, w, h):
        key = (which, k)
        if key not in self.reels:
            for o in [q for q in self.reels if q[1] < k - 1]: del self.reels[o]
            plan = self.plan_old if which == 'old' else self.plan_new
            e, off = plan[k]; n = self.ends[k] - self.cuts[k]
            if k == len(self.cuts) - 1 and k > 0 and e is plan[0][0]: off = max(0, off - n)     # the loop cut ends where the opener began
            self.reels[key] = Reel(e, off, n, w, h, random.Random(zlib.crc32(('%s%d%d' % (e['asset'], k, off)).encode())))
        return self.reels[key]

    # ------------------------------------------------------------ the grade
    def grade(self, f, i, old=False):
        img = f.astype(np.float32) / 255.0; h, w = f.shape[:2]
        if old:                                                                      # old film: silver, contrast, a little flicker
            g = img @ LUMA; lo, hi = np.percentile(g[::8, ::8], (2, 98))                 # a dark print is levelled up to full range
            g = np.clip((g - lo) / max(0.25, hi - lo), 0, 1) ** 0.9 * (1 + 0.035 * np.sin(i * 2.3))
            img = np.stack([g * 0.94, g * 0.98, g * 1.02], -1) + self.grain[i % 4][:h, :w, None] * 0.05
            return np.clip(img * 255, 0, 255)
        lum = (img @ LUMA)[..., None]
        if self.look == 'cine':                                                      # teal in the shadows, warm in the highlights
            sh = np.clip(1 - lum * 2, 0, 1); hi = np.clip(lum * 2 - 1, 0, 1)
            img = img + sh * np.array([0.05, 0.025, -0.01], np.float32) + hi * np.array([-0.04, 0.0, 0.05], np.float32)
            img = 0.5 + (img - 0.5) * 1.12
        elif self.look == 'night':                                                   # cool, crushed, the lights stay warm
            img = np.clip((img * np.array([1.12, 1.0, 0.88], np.float32) - 0.05) * 1.15, 0, 1)
            img = img + np.clip(lum * 2.2 - 1.2, 0, 1) * np.array([-0.06, 0.0, 0.08], np.float32)
        elif self.look == 'film':                                                    # warm, lifted blacks
            img = img * np.array([0.9, 0.99, 1.08], np.float32) * 0.9 + 0.06
        else:
            img = 0.5 + (img - 0.5) * 1.06
        img = np.clip(img, 0, 1)
        # halation: what is bright blooms, tinted warm (a city's lights at night)
        small = cv2.resize(img, (w // 8, h // 8), interpolation=cv2.INTER_AREA)
        b = cv2.GaussianBlur(np.clip(small @ LUMA - 0.72, 0, 1)[..., None] * small, (0, 0), 6)
        b = cv2.resize(b, (w, h), interpolation=cv2.INTER_LINEAR)
        img = img + b * np.array([0.55, 0.8, 1.0], np.float32) * {'night': 1.6, 'film': 1.2, 'cine': 1.0, 'clean': 0.5}[self.look]
        sat = {'cine': 1.06, 'night': 1.0, 'film': 0.86, 'clean': 1.05}[self.look]
        if sat != 1.0:
            m = img.mean(-1, keepdims=True); img = m + (img - m) * sat
        out = np.clip(img, 0, 1) * 255
        if self.look != 'clean':
            out = out + self.grain[i % 4][:h, :w, None] * {'film': 9, 'cine': 5, 'night': 6}[self.look]
        return out

    # ------------------------------------------------------------ text, drawn once as layers
    def fonts(self):
        self.f_hook = ttf('Fraunces.ttf', 82, 'SemiBold'); self.f_place = ttf('BarlowCondensed-Medium.ttf', 58)
        self.f_ll = ttf('DejaVuSansMono-Bold.ttf', 24); self.f_year = ttf('Fraunces.ttf', 150, 'Bold')
        self.f_meme = ttf('Poppins-Bold.ttf', 58); self.f_num = ttf('Anton-Regular.ttf', 300)
        self.f_lab = ttf('Montserrat-ExtraBold.ttf', 56); self.f_kick = ttf('Montserrat-ExtraBold.ttf', 34)

    def over(self, img, key, draw, alpha=1.0, dy=0):
        """Lay an RGBA text layer over img (BGR float). Each layer is drawn once and kept."""
        if key not in self.layers:
            im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); draw(ImageDraw.Draw(im))
            a = np.asarray(im).astype(np.float32); ys, xs = np.where(a[..., 3] > 0)
            y0, y1, x0, x1 = (ys.min(), ys.max() + 1, xs.min(), xs.max() + 1) if len(ys) else (0, 1, 0, 1)
            self.layers[key] = ((y0, y1, x0, x1), a[y0:y1, x0:x1, 2::-1].copy(), a[y0:y1, x0:x1, 3:] / 255.0)
        (y0, y1, x0, x1), rgb, a = self.layers[key]
        if alpha <= 0.01: return
        y0, y1 = y0 + dy, y1 + dy; a = a * alpha
        img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - a) + rgb * a

    @staticmethod
    def shadowed(d, xy, txt, font, anchor='la', sh=4):
        for off, al in ((sh, 90), (sh // 2, 120)):
            d.text((xy[0], xy[1] + off), txt, font=font, fill=(0, 0, 0, al), anchor=anchor)
        d.text(xy, txt, font=font, fill=(255, 255, 255, 255), anchor=anchor)

    def draw_hook(self, d):
        y = 320
        for row in balanced(self.hook, self.f_hook, SAFE_X1 - SAFE_X0 - 30): self.shadowed(d, (W // 2 - 20, y), row, self.f_hook, anchor='ma', sh=5); y += 98

    def draw_place(self, e, y=1352):
        p = info(e)
        def draw(d):
            x = SAFE_X0
            d.line([(x, y - 26), (x + 64, y - 26)], fill=(255, 255, 255, 230), width=4)
            d.text((x, y), p['place'].upper(), font=self.f_place, fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0, 60))
            sub = '  ·  '.join(s for s in (p.get('area', '').upper(), p.get('ll', '')) if s)
            if sub: d.text((x + 2, y + 70), sub, font=self.f_ll, fill=(255, 255, 255, 215))
        return draw

    # ------------------------------------------------------------ frames
    def full(self, which, i, w, h, old=False):
        k, j = self.seg(i); f = self.reel(which, k, w, h).frame(j)
        if f.shape[0] != h or f.shape[1] != w: f = cv2.resize(f, (w, h))
        if not old: f = cv2.addWeighted(f, 1.45, cv2.GaussianBlur(f, (0, 0), 1.6), -0.45, 0)   # 720p stock upscaled: give it its edges back
        img = self.grade(f, i, old)
        push = (0.045 * np.exp(-j / 3.0) if k else 0.0) + 0.012 * self.kick[i]   # (not on the opener: frame 0 must match the loop's last frame)                     # each cut lands with a small push, the kick a smaller one
        if push > 0.003:
            img = cv2.resize(img, None, fx=1 + push, fy=1 + push); y0, x0 = (img.shape[0] - h) // 2, (img.shape[1] - w) // 2; img = img[y0:y0 + h, x0:x0 + w]
        return img, k, j

    def frame(self, i):
        if self.kind == 'thennow': return self.frame_split(i)
        img, k, j = self.full('new', i, W, H)
        img = img * self.vig
        e = self.plan_new[k][0]
        if self.kind == 'meme':
            img[:self.panel] = 255
            def draw(d):
                y = 268
                for row in self.rows: d.text((75, y), row, font=self.f_meme, fill=(10, 10, 10, 255)); y += 76
            self.over(img, 'meme', draw)
        elif self.kind == 'fact':
            img *= 0.62; self.over(img, 'fact', self.draw_fact)
            pop = round(1 + 0.07 * self.kick[i], 2); self.over(img, ('num', pop), lambda d: self.draw_num(d, pop))
        else:
            if info(e).get('place'):
                self.over(img, ('place', e['asset']), self.draw_place(e), alpha=1.0 if k == 0 else min(1.0, j / 5.0), dy=0 if k == 0 else int(max(0, 12 - j * 3)))
            hold = min(max(self.ends[min(len(self.cuts) - 1, 2)], int(2.2 * FPS)), int(3.6 * FPS))   # the line stays for the first cuts, 2.2-3.6 s
            a = 1.0 if i < hold else max(0.0, 1 - (i - hold) / 8.0)
            if a > 0.01: img[:self.scrim.shape[0]] *= 1 - self.scrim * a                # a soft shade behind the line, so it reads on a busy sky
            self.over(img, 'hook', self.draw_hook, alpha=a)
        return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)

    def frame_split(self, i):
        th = self.top_h; bh = H - th - 16
        top, _k, _j = self.full('old', i, W, th, old=True)
        bot, _k2, _j2 = self.full('new', i, W, bh)
        img = np.full((H, W, 3), 12, np.float32); img[:th] = top; img[th + 16:] = bot
        img = img * self.vig
        e0 = self.plan_old[_k][0]; year = str(info(e0).get('year') or ''); place = (info(e0).get('place') or '').upper()
        def draw_top(d):
            self.shadowed(d, (SAFE_X0, 300), year, self.f_year, sh=6)
            d.text((SAFE_X0 + 4, 480), place, font=self.f_place, fill=(255, 255, 255, 240), stroke_width=2, stroke_fill=(0, 0, 0, 120))
        def draw_bot(d):
            self.shadowed(d, (SAFE_X0, th + 16 + 60), 'now', self.f_year, sh=6)
        self.over(img, ('top', year, place), draw_top); self.over(img, 'bot', draw_bot)
        return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)

    def draw_fact(self, d):
        label = self.fact[2]
        d.rounded_rectangle([W / 2 - 170, 330, W / 2 + 130, 392], radius=31, fill=(255, 214, 10, 255))
        d.text((W / 2 - 20, 361), 'NYC FACT', font=self.f_kick, fill=(10, 10, 10, 255), anchor='mm')
        y = 940
        for row in wrap(label.upper(), self.f_lab, SAFE_X1 - SAFE_X0 - 20):
            d.text((W / 2 - 20, y), row, font=self.f_lab, fill=(255, 255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0, 255)); y += 72

    def draw_num(self, d, pop):
        num, fmt, _label = self.fact
        f = self.f_num if pop < 1.01 else self.f_num.font_variant(size=int(300 * pop))
        d.text((W / 2 - 20, 680), fmt.format(num), font=f, fill=(255, 255, 255, 255), anchor='mm', stroke_width=4, stroke_fill=(0, 0, 0, 255))

    # ------------------------------------------------------------ output
    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = []
            for i in fs:
                fr = self.frame(min(i, self.n - 1)); ims.append(Image.fromarray(fr).resize((360, 640), Image.LANCZOS))
                if os.environ.get('CQ_FULL'): Image.fromarray(fr).save(out[:-4] + '_f%d.png' % i)
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], 'cuts', len(self.cuts)); return
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
        used = sorted({e['key'] for plan in (self.plan_new, self.plan_old) for e, _o in plan})
        json.dump(dict(K.record(), footage=used), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
