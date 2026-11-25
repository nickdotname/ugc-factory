#!/usr/bin/env python3
"""rubber-hose page: cartoons from before 1931 cut as a modern edit, on the beat.

    python studio/toon_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/toon_video.py SONG_DIR SEED SHEET.png --frames 0,20,140 [--full]   (a contact sheet instead)

Clips come from the footage library, theme "toons" (studio/footage.py): Internet Archive cartoons published in 1930
or earlier (US public domain), with no still-defended character in them (footage.TRADEMARK). The clip choice is
vintage_video's (studio/vintage_video.py): cards, black and fades are never used, each cut takes the liveliest
stretch of its clip, films alternate, the last cut runs into the first frame so it loops.

What makes it an edit rather than an old print (each a knob, studio/knobs.py):
  pace     a cut on every beat, or every other beat
  punch    the frame jumps in on every kick, or only on the cuts
  stutter  on a snare the frame holds for two frames and jumps back (the rubber-hose double take)
  wash     the ink: plain black and white, cream paper, a pop colour that changes on every cut, or crushed ink
  frame    the full screen, or a rounded 1930s cabinet TV glowing round the picture
  caption  the song's words one at a time as they are sung (sung-time sync from sync_check.load_lines), a line
           of our own at the top, or none
The film's title and year sit small at the bottom as a credit; the song credit under it.
"""
import json, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage
import vintage_video as V

W, H, FPS = 1080, 1920, 30
SAFE_TOP, SAFE_BOTTOM = 250, H - 420
POP = [(255, 92, 170), (70, 170, 255), (255, 214, 40), (120, 230, 150), (255, 130, 60), (180, 120, 255)]
WASHES = ['bw', 'cream', 'pop', 'ink']
HOOKS = [line.strip() for line in open(os.path.join(HERE, 'toons', 'hooks.txt')) if line.strip() and not line.startswith('#')]


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def sung_words(song_dir, t0, t1):
    """(frame, word) for every sung word inside the window, at the time it is sung."""
    if os.environ.get('CQ_LYRICS') == 'none': return []
    import sync_check
    out = []
    for _end, words in sync_check.load_lines(song_dir):
        for w, t in words:
            if t0 <= t < t1 - 0.2: out.append((int(round((t - t0) * FPS)), w))
    return out


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.pace = K.pick('pace', ['beat', 'beat2'], r, weights=[2, 3])
        self.punch = K.pick('punch', ['kick', 'cut'], r, weights=[3, 2])
        self.stutter = K.pick('stutter', ['on', 'off'], r)
        self.wash = K.pick('wash', WASHES, r, weights=[2, 3, 3, 2])
        self.frame_k = K.pick('frame', ['full', 'tv'], r, weights=[3, 2])
        lib = [e for e in footage.pull(('toons',)) if not footage.BLOCK.search('%s %s' % (e.get('title', ''), e.get('key', '')))
               and not footage.TRADEMARK.search('%s %s' % (e.get('title', ''), e.get('key', '')))]
        if len(lib) < 3: sys.exit('the toons library has fewer than 3 clips: run the footage workflow first')
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 7.0)
        self.snares = set(int(round(f)) for f in a.get('snares', []))
        per = 1 if self.pace == 'beat' else 2
        if per * self.spb < 0.33: per *= 2                                         # never faster than three cuts a second
        beats = [(int(b), int(round(fr))) for b, fr in a['beats'] if 0 <= fr < n]
        cuts = [0]
        for b, fr in beats:
            if b % per == 0 and FPS * 0.5 <= fr <= n - FPS * 0.4 and fr - cuts[-1] >= FPS * 0.3: cuts.append(fr)
        if len(cuts) < 2: cuts = list(range(0, n, int(FPS * 0.9)))
        self.plan = V.Plan(lib, n, cuts, r)
        self.cuts = [c for c, *_x in self.plan.plan]
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        words = sung_words(song_dir, t0, t1)
        self.caption = K.pick('caption', ['words', 'hook', 'none'], r, weights=[4 if len(words) >= 6 else 0, 3, 1])
        self.words = words; self.hook = r.choice(HOOKS)
        self.f_word = font('Anton-Regular.ttf', 150); self.f_hook = font('Montserrat-ExtraBold.ttf', 62)
        self.f_small = font('BarlowCondensed-Medium.ttf', 40)
        sans = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        self.f_credit = ImageFont.truetype(sans, 30) if os.path.exists(sans) else self.f_small
        self.grain = [cv2.resize(np.random.default_rng(seed + k).normal(0, 1, (H // 3, W // 3)).astype(np.float32), (W, H)) for k in range(6)]
        if self.frame_k == 'tv':
            m = Image.new('L', (W, H), 0); ImageDraw.Draw(m).rounded_rectangle([70, 330, W - 70, H - 470], radius=150, fill=255)
            self.mask = cv2.GaussianBlur(np.asarray(m, np.float32) / 255, (0, 0), 5)
        self.held = None; self.hold_left = 0; self.shake = np.zeros(2, np.float32)

    def cut_index(self, i):
        return max(k for k, c in enumerate(self.cuts) if c <= i)

    def colour(self, g, k):
        """The grey frame (0..1) as RGB in the chosen wash."""
        if self.wash == 'bw': lo, hi = (12, 12, 12), (240, 238, 232)
        elif self.wash == 'cream': lo, hi = (30, 22, 14), (246, 232, 200)
        elif self.wash == 'ink':
            g = np.clip((g - 0.25) / 0.5, 0, 1); lo, hi = (6, 6, 8), (250, 248, 240)
        else:
            c = POP[k % len(POP)]; lo, hi = tuple(int(x * 0.12) for x in c), tuple(int(min(255, 90 + x * 0.75)) for x in c)
        lo, hi = np.array(lo, np.float32), np.array(hi, np.float32)
        return lo + (hi - lo) * g[..., None]

    def frame(self, i):
        src = i
        if self.stutter == 'on':
            if self.hold_left: self.hold_left -= 1; src = self.held
            elif i in self.snares and i - self.cuts[self.cut_index(i)] > 3: self.held = i - 2; self.hold_left = 2; src = self.held
        k = self.cut_index(i); since = i - self.cuts[k]
        if self.frame_k == 'tv': pw, ph = W - 140, H - 800
        else: pw, ph = W, H
        g, *_x = self.plan.picture(src, pw, ph)
        lo, hi = np.percentile(g[::5, ::5], 2), np.percentile(g[::5, ::5], 98)
        g = np.clip((g - lo) / max(0.2, hi - lo), 0, 1)
        z = 1.0
        if self.punch == 'kick': z += 0.10 * float(self.kick[i])
        z += 0.14 * max(0.0, 1 - since / 4)                                       # every cut lands zoomed in and settles
        rng = np.random.default_rng(i)
        self.shake = self.shake * 0.5 + (rng.normal(0, 9, 2).astype(np.float32) * float(self.kick[i]) if self.kick[i] > 0.5 else 0)
        M = cv2.getRotationMatrix2D((pw / 2, ph / 2), float(self.shake[0]) * 0.08, z); M[:, 2] += self.shake
        g = cv2.warpAffine(g, M, (pw, ph), borderMode=cv2.BORDER_REFLECT)
        g = np.clip(g + self.grain[i % 6] * 0.035, 0, 1)
        img = self.colour(g, k)
        if since == 0 and k: img = img * 0.55 + 115                                 # a flash on the cut
        if self.frame_k == 'tv':
            c = np.array(POP[k % len(POP)] if self.wash == 'pop' else (40, 32, 26), np.float32)
            canvas = np.zeros((H, W, 3), np.float32) + c * 0.25
            glow = cv2.GaussianBlur(cv2.resize(img, (W // 8, (H - 800) // 8)), (0, 0), 6)
            canvas[330:H - 470, 70:W - 70] = cv2.resize(glow, (W - 140, H - 800)) * 0.5
            canvas[330:H - 470, 70:W - 70] = canvas[330:H - 470, 70:W - 70] * (1 - self.mask[330:H - 470, 70:W - 70, None]) + img * self.mask[330:H - 470, 70:W - 70, None]
            img = canvas
        out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(out)
        self.draw_text(d, i, k)
        e = self.plan.plan[k][1]; title, year = V.film_label(e)
        label = ('%s · %s' % (title, year) if year else title).lower()
        d.text((W / 2, SAFE_BOTTOM - 70), label[:46], font=self.f_small, fill=(240, 236, 226), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        d.text((W / 2, SAFE_BOTTOM - 24), self.credit, font=self.f_credit, fill=(240, 236, 226), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        return np.asarray(out)

    def draw_text(self, d, i, k):
        if self.caption == 'hook' and i < self.n - 8:
            rows = V.Video.wrap(self, self.hook, self.f_hook, W - 240)
            y = SAFE_TOP + 70
            for row in rows:
                d.text((W / 2, y), row, font=self.f_hook, fill=(255, 255, 255), anchor='mm', stroke_width=7, stroke_fill=(0, 0, 0)); y += 76
        elif self.caption == 'words':
            cur = [(f, w) for f, w in self.words if f <= i]
            if not cur or i - cur[-1][0] > int(0.9 * FPS): return
            f, w = cur[-1]; w = w.strip(' ,.!?"').upper()
            age = i - f; s = 1.0 + 0.25 * max(0.0, 1 - age / 3)                     # each word pops in
            fnt = self.f_word if s == 1.0 else font('Anton-Regular.ttf', int(150 * s))
            while fnt.getlength(w) > W - 200 and fnt.size > 70: fnt = font('Anton-Regular.ttf', fnt.size - 10)
            fill = POP[(len(cur)) % len(POP)] if self.wash != 'pop' else (255, 255, 255)
            d.text((W / 2, H * 0.62), w, font=fnt, fill=fill, anchor='mm', stroke_width=10, stroke_fill=(0, 0, 0))

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; want = set(fs); ims = []
            for i in range(max(fs) + 1):
                fr = self.frame(i)
                if i in want:
                    ims.append(Image.fromarray(fr).resize((360, 640)))
                    if '--full' in sys.argv: Image.fromarray(fr).save(out[:-4] + '_f%d.png' % i)
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], [V.film_label(e)[0] for _c, e, _o in self.plan.plan]); return
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
        used = sorted({e['key'] for _c, e, _o in self.plan.plan})
        json.dump(dict(K.record(), footage=used), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
