#!/usr/bin/env python3
"""nyc.daily.aesthetic (Daily NYC Memes & Culture): real New York footage cut on the beat, as a meme or as a fact.

    python studio/nyc_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)

The nightly job's renderer for the "nyc" style (studio/nightly.py). Clips come from the footage library
(studio/footage.py, theme "nyc": public-domain New York footage from Wikimedia Commons and the Prelinger Archives)
and are cut on bar lines.
  kind   meme: a white caption bar over the clips, the way meme reels are set; fact: a New York number counts up
         on the beat over darkened clips, with what it counts underneath
  look   the grade: natural, warm (golden hour), night (cool, crushed), film (grain and a little fade)
  pace   a cut every bar or every two bars
The memes and facts are written below. The facts are ones that do not drift: if one is ever out of date, fix it
here. All of them are knobs (studio/knobs.py), so the learner finds out what people watch.
"""
import json, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage
from glitch_video import Clips, W, H, FPS

MEMES = [
    "pov: \"we are being held momentarily by the train's dispatcher\"",
    "me walking 4 blocks out of my way to avoid one slow tourist",
    "\"it's like a 10 minute walk\" - a new yorker, describing 30 minutes",
    "the 2am dollar slice that fixes everything",
    "when the express train actually shows up first",
    "pov: you moved here for the \"energy\"",
    "when the bodega cat finally lets you pet it",
    "new yorkers when it's 55 degrees and sunny",
    "me pretending i didn't just miss the train by 2 seconds",
    "the empty subway car is empty for a reason",
    "nyc weather: four seasons in one week",
    "the bodega guy remembering your order >>>",
    "when someone stops dead at the top of the subway stairs",
    "my apartment listing said \"cozy\"",
    "car alarm at 3am. nobody moves.",
    "that scaffolding has been up since before i moved here",
    "every umbrella in midtown at exactly eye level",
    "the walk from the train to my apartment is my whole cardio",
    "me after one week here: \"as a new yorker...\"",
    "brooklyn people explaining manhattan is \"too much\"",
    "when the L train is down again this weekend",
    "jaywalking is a personality here",
    "a $9 iced coffee hits different after a 45 minute commute",
    "\"showtime!\" at 8am on a monday",
    "pov: the A train skipped your stop and you're in queens now",
    "staten island ferry: the best free date in the city",
    "me saying \"sorry\" while walking straight through you",
    "when it's sunny and the whole city is in the same park",
    "being from here means you never look up at the buildings",
    "the city at 5am hits different",
]
# (number, how it is written, what it counts)
FACTS = [
    (843, '{:,.0f}', 'acres of central park'),
    (472, '{:,.0f}', 'subway stations. more than any other system on earth'),
    (24, '{:,.0f}/7', 'the subway never closes'),
    (102, '{:,.0f}', 'floors in the empire state building'),
    (410, '{:,.0f}', 'days it took to build the empire state building'),
    (800, 'UP TO {:,.0f}', 'languages are spoken in new york city'),
    (44, '{:,.0f}', 'platforms at grand central. the most of any station in the world'),
    (0, '${:,.0f}', 'to ride the staten island ferry'),
    (1904, '{:.0f}', 'the year the first subway line opened'),
    (1883, '{:.0f}', 'the year the brooklyn bridge opened'),
    (13.4, '{:.1f} MI', 'the length of manhattan'),
    (151, '{:,.0f} FT', 'statue of liberty, without the pedestal'),
    (1776, '{:,.0f} FT', 'one world trade center. on purpose'),
    (520, '{:,.0f} MI', 'of waterfront in new york city'),
    (1700, '{:,.0f}+', 'parks in the five boroughs'),
]
LOOKS = ['natural', 'warm', 'night', 'film']


def ttf(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def wrap(txt, font, width):
    words, rows, cur = txt.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if font.getlength(t) <= width or not cur: cur = t
        else: rows.append(cur); cur = w
    return rows + ([cur] if cur else [])


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.kind = K.pick('kind', ['meme', 'fact'], r, weights=[3, 2])
        self.look = K.pick('look', LOOKS, r)
        self.pace = float(K.pick('pace', [1, 2], r))
        lib = footage.pull(('nyc',)); self.source = 'nyc'
        if len(lib) < 3: lib = footage.pull(('city',)); self.source = 'city'          # until the New York footage is fetched
        K.MENU['source'] = ['nyc', 'city']; K.CHOSEN['source'] = self.source
        if not lib: sys.exit('the footage library is empty: run the footage workflow first')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 6.0)
        self.beats = [int(fr) for b, fr in a['beats']]
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        sans = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/Library/Fonts/Arial Unicode.ttf') if os.path.exists(p)), None)
        self.f_credit = ImageFont.truetype(sans, 28) if sans else ttf('Poppins-Bold.ttf', 28)
        if self.kind == 'meme':
            self.text = MEMES[r.randrange(len(MEMES))]; K.CHOSEN['line'] = str(MEMES.index(self.text)); K.MENU['line'] = [str(j) for j in range(len(MEMES))]
            self.f_meme = ttf('Poppins-Bold.ttf', 58)
            self.rows = wrap(self.text, self.f_meme, W - 150)
            self.panel = 230 + 76 * len(self.rows) + 70                                # the white bar, from the top
            self.vh = H - self.panel
        else:
            self.fact = FACTS[r.randrange(len(FACTS))]; K.CHOSEN['fact'] = str(FACTS.index(self.fact)); K.MENU['fact'] = [str(j) for j in range(len(FACTS))]
            self.f_num, self.f_lab, self.f_kick = ttf('Anton-Regular.ttf', 300), ttf('Montserrat-ExtraBold.ttf', 58), ttf('Montserrat-ExtraBold.ttf', 36)
            self.vh = H
        self.clips = Clips(lib, n, self.spb, self.pace, r)
        gr = np.random.default_rng(seed)
        self.grain = [cv2.resize(gr.normal(0, 1, (H // 3, W // 3)).astype(np.float32), (W, H)) for _ in range(4)]

    def grade(self, f):
        img = f.astype(np.float32)
        if self.look == 'warm': img = img * np.array([0.86, 1.0, 1.12], np.float32) + np.array([0, 6, 16], np.float32)
        elif self.look == 'night':
            img = img * np.array([1.14, 0.98, 0.84], np.float32); img = np.clip((img - 20) * 1.12, 0, 255)
        elif self.look == 'film':
            img = img * 0.9 + 18; img[..., 1] *= 0.97
        hsv = cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] *= 1.18 if self.look != 'film' else 0.85
        return cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)

    def frame(self, i):
        f, k, e = self.clips.frame(i)
        img = self.grade(f)
        z = 1 + 0.025 * self.kick[i]                                                   # a small push on the kick
        if z > 1.001:
            img = cv2.resize(img, None, fx=z, fy=z); y0, x0 = (img.shape[0] - H) // 2, (img.shape[1] - W) // 2; img = img[y0:y0 + H, x0:x0 + W]
        if self.look == 'film': img += self.grain[i % 4][..., None] * 9
        if self.kind == 'meme':
            canvas = np.full((H, W, 3), 255, np.float32)
            y0 = (H - self.vh) // 2; canvas[self.panel:] = img[y0:y0 + self.vh]
            out = Image.fromarray(cv2.cvtColor(np.clip(canvas, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(out)
            y = 230 + 38
            for row in self.rows: d.text((75, y), row, font=self.f_meme, fill=(10, 10, 10), anchor='lm'); y += 76
        else:
            img *= 0.58
            out = Image.fromarray(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(out)
            self.draw_fact(d, i)
        d.text((W / 2, H - 110), self.credit, font=self.f_credit, fill=(240, 240, 240), anchor='mm', stroke_width=2, stroke_fill=(0, 0, 0))
        return np.asarray(out)

    def draw_fact(self, d, i):
        num, fmt, label = self.fact
        start = self.beats[1] if len(self.beats) > 1 else 0
        run = max(1, (self.beats[9] if len(self.beats) > 9 else start + 3 * FPS) - start)    # counts up over two bars
        p = min(1.0, max(0.0, (i - start) / run)); p = 1 - (1 - p) ** 3
        v = 1800 + (num - 1800) * p if 1800 <= num < 2100 else num * p              # a year counts up from 1800, not from 0
        d.rounded_rectangle([W / 2 - 170, 470, W / 2 + 170, 540], radius=35, fill=(255, 214, 10))
        d.text((W / 2, 505), 'NYC FACT', font=self.f_kick, fill=(10, 10, 10), anchor='mm')
        pop = 1 + 0.06 * self.kick[i]
        f_num = self.f_num if pop < 1.01 else self.f_num.font_variant(size=int(300 * pop))
        d.text((W / 2, 820), fmt.format(v), font=f_num, fill=(255, 255, 255), anchor='mm', stroke_width=4, stroke_fill=(0, 0, 0))
        if i >= start + run * 0.6:                                                     # what it counts, word by word on the beats
            words = label.split(); shown = sum(1 for b in self.beats if start + run * 0.6 <= b <= i) + 1
            rows = wrap(' '.join(words[:shown]), self.f_lab, W - 160); y = 1060
            for row in rows: d.text((W / 2, y), row.upper(), font=self.f_lab, fill=(255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0)); y += 74

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
        used = sorted({e['key'] for _, e, *_r in self.clips.plan})
        json.dump(dict(K.record(), footage=used), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
