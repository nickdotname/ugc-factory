#!/usr/bin/env python3
"""museum-zoom page: a public-domain painting or print, then a dive into one small detail of it on the drop.

    python studio/zoom_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/zoom_video.py SONG_DIR SEED SHEET.png --frames 0,200,300 [--full]   (a contact sheet instead)

Works come from the art library (studio/art.py: The Met, Cleveland and the Art Institute of Chicago, public domain /
CC0, full size). The detail is found in the picture itself: a small face (a tiny figure far from the middle is the
best find), else the busiest patch of brushwork away from the edges. Its place is said in words ("the bottom left
corner"), so the hook is always true of the picture. Title, artist, date and museum come from the museum's record.

The camera: the whole work on a wall, a slow push, then on the first strong bar after a third of the clip it dives
in (6-20x) and drifts across the detail with the kick; it pulls back out at the end so the video loops. Knobs:
  dive    snap (0.4 s) or glide (1.3 s)
  mark    a ring is drawn round the spot a beat before the dive, or nothing gives it away
  wall    a gallery wall with a gilt frame, or the picture blurred and enlarged behind itself
  hook    which true line sits at the top (the artist and year, the age, or where to look)
  tour    one detail, or a second one on the next phrase
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish
import art

W, H, FPS = 1080, 1920, 30
# Works seen on review and left out: sketch sheets with little to find, a closed book, a bathing scene.
SKIP = {'cleveland:675346', 'cleveland:675347', 'cleveland:675348', 'cleveland:95343', 'cleveland:140492'}
SAFE_TOP, SAFE_BOTTOM = 250, H - 420
CY = 930                                      # where the picture's centre sits on screen at the start
BOX_W, BOX_H = 1030, 1180                      # the picture fits inside this at the start


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def ease(u): return u * u * (3 - 2 * u)


def place(cx, cy, w, h):
    """Where a point is in the picture, in words."""
    col = 'left' if cx < w / 3 else 'right' if cx > 2 * w / 3 else ''
    row = 'top' if cy < h / 3 else 'bottom' if cy > 2 * h / 3 else ''
    if row and col: return '%s %s corner' % (row, col)
    if row: return '%s edge' % row if row == 'top' else 'bottom'
    if col: return '%s side' % col
    return 'middle'


def details(img, rng, n=2):
    """Up to n (cx, cy, size) spots worth diving into, in the picture's own pixels."""
    h, w = img.shape[:2]; s = 1600 / max(h, w); sm = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    grey = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY); sh, sw = grey.shape
    found = []
    for name in ('haarcascade_frontalface_default.xml', 'haarcascade_profileface.xml'):
        path = os.path.join(getattr(getattr(cv2, 'data', None), 'haarcascades', ''), name)
        casc = cv2.CascadeClassifier(path) if os.path.exists(path) else None
        if casc is None or casc.empty(): continue                                  # an OpenCV without the face models: brushwork only
        for x, y, fw, fh in casc.detectMultiScale(grey, 1.08, 6, minSize=(14, 14), maxSize=(sw // 8, sh // 8)):
            cx, cy = x + fw / 2, y + fh / 2
            off = math.hypot(cx / sw - 0.5, cy / sh - 0.5)
            found.append((off - fw / sw, cx / s, cy / s, max(fw / s * 7, 0.6 * W)))
    found.sort(key=lambda f: -f[0])
    spots = [(cx, cy, size) for _sc, cx, cy, size in found[:6]]
    rng.shuffle(spots)
    lap = cv2.GaussianBlur(np.abs(cv2.Laplacian(grey.astype(np.float32), cv2.CV_32F)), (0, 0), sw / 40)
    m = int(0.1 * min(sh, sw)); lap[:m] = 0; lap[-m:] = 0; lap[:, :m] = 0; lap[:, -m:] = 0
    for _ in range(4):
        y, x = np.unravel_index(int(np.argmax(lap)), lap.shape)
        spots.append((x / s, y / s, max(w / 10, 0.6 * W)))
        r = int(sw / 6); lap[max(0, y - r):y + r, max(0, x - r):x + r] = 0
    out = []
    for cx, cy, size in spots:                                                  # far enough apart to be two places
        if all(math.hypot(cx - ox, cy - oy) > max(w, h) / 6 for ox, oy, _s in out): out.append((cx, cy, min(size, w / 3)))
        if len(out) == n: break
    return out


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        works = art.pull()
        if not works: sys.exit('the art library is empty: run the art workflow first')
        by = {w['key']: w for w in works if w['key'] not in SKIP}                                         # the work is a knob: nightly.py's FRESH rule keeps it from repeating
        self.work = e = by.get(K.pick('work', sorted(by), r)) or r.choice(works)
        img = cv2.imread(os.path.join(art.CACHE, e['asset']), cv2.IMREAD_COLOR)
        self.ih, self.iw = img.shape[:2]
        self.pyr = [img]
        while max(self.pyr[-1].shape[:2]) > 900: self.pyr.append(cv2.pyrDown(self.pyr[-1]))
        self.dive = K.pick('dive', ['snap', 'glide'], r)
        self.mark = K.pick('mark', ['ring', 'none'], r, weights=[2, 3])
        self.wall = K.pick('wall', ['gallery', 'blur'], r, weights=[3, 2])
        self.tour = K.pick('tour', ['one', 'two'], r, weights=[3, 2])
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 6.0)
        bars = [int(round(fr)) for b, fr in a['beats'] if b % 4 == 0 and 0 <= fr < n]
        self.drop = next((f for f in bars if f >= 1.5 * FPS), int(1.5 * FPS))    # the dive inside ~1.5 s: the cut to the detail IS the hook (it was the first bar after 30% of the clip, ~6 s of push-in)
        later = [f for f in bars if f >= self.drop + 3 * FPS and f < n - 2.5 * FPS]
        self.second = later[0] if (self.tour == 'two' and later) else None
        self.spots = details(img, r, 2 if self.second else 1)
        if self.second and len(self.spots) < 2: self.second = None
        self.fit = max(self.iw / BOX_W, self.ih / BOX_H)                          # picture px per screen px at the start
        self.out_at = n - int(0.8 * FPS)
        cx, cy, _s = self.spots[0]
        year = e.get('year'); kind = 'painting' if 'paint' in (e.get('kind') or '') else 'print' if 'print' in (e.get('kind') or '') else 'picture'
        who = e.get('artist') or ''
        opts = ['where']
        if who and year: opts.append('who')
        if year and year < 1900: opts.append('age')
        self.hook_kind = K.pick('hook', opts, r)
        spot = place(cx, cy, self.iw, self.ih)
        self.hook = {'who': '%s, %d. look at the %s.' % (who, year, spot) if who and year else '',
                     'age': 'this %s is %d years old. look at the %s.' % (kind, 2026 - (year or 2026), spot),
                     'where': 'keep your eye on the %s.' % spot}[self.hook_kind]
        self.f_hook = font('Montserrat-ExtraBold.ttf', 58); self.f_title = font('Fraunces.ttf', 50); self.f_meta = font('BarlowCondensed-Medium.ttf', 38)
        sans = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        self.f_credit = ImageFont.truetype(sans, 30) if os.path.exists(sans) else self.f_meta
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        mean = self.pyr[-1].reshape(-1, 3).mean(0)
        self.wall_c = np.clip(mean * 0.35 + np.array([30, 32, 36]), 0, 255)       # BGR, a wall that suits the picture
        if self.wall == 'blur':
            sm = self.pyr[-1]; s = max(W / sm.shape[1], H / sm.shape[0]) * 1.15
            bg = cv2.resize(sm, (int(sm.shape[1] * s), int(sm.shape[0] * s)))
            y0, x0 = (bg.shape[0] - H) // 2, (bg.shape[1] - W) // 2
            self.bg = cv2.GaussianBlur(bg[y0:y0 + H, x0:x0 + W], (0, 0), 30).astype(np.float32) * 0.45
        else:
            self.bg = np.zeros((H, W, 3), np.float32) + self.wall_c
            yy = np.arange(H, dtype=np.float32)[:, None, None]
            self.bg *= np.clip(1.15 - ((yy - CY) / H) ** 2 * 1.4, 0.55, 1.15)     # a lamp over the picture

    def camera(self, i):
        """(centre x, centre y, picture px per screen px) at frame i."""
        n = self.n; c0 = (self.iw / 2, self.ih / 2, self.fit)
        cx, cy, size = self.spots[0]; c1 = (cx, cy, size / W)
        L = int((0.4 if self.dive == 'snap' else 1.3) * FPS)
        drift = lambda c, t: (c[0] + math.sin(t * 0.7) * c[2] * 40, c[1] + math.cos(t * 0.5) * c[2] * 30, c[2] * (1 - 0.06 * min(1.0, t / 4)))
        def mix(a, b, u):
            u = ease(min(1.0, max(0.0, u)))
            return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, math.exp(math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * u))
        if i < self.drop:
            u = i / max(1, self.drop)
            return mix(c0, (c0[0] + (cx - c0[0]) * 0.12, c0[1] + (cy - c0[1]) * 0.12, c0[2] * 0.86), u)
        pre = mix(c0, (c0[0] + (cx - c0[0]) * 0.12, c0[1] + (cy - c0[1]) * 0.12, c0[2] * 0.86), 1.0)
        at = drift(c1, (i - self.drop) / FPS)
        cam = mix(pre, at, (i - self.drop) / L)
        if self.second and i >= self.second:
            x2, y2, s2 = self.spots[1]; c2 = drift((x2, y2, s2 / W), (i - self.second) / FPS)
            cam = mix(at, c2, (i - self.second) / (1.0 * FPS))
        if i >= self.out_at:
            cam = mix(cam, c0, (i - self.out_at) / (self.n - 1 - self.out_at))
        return cam

    def frame(self, i):
        cx, cy, s = self.camera(i)
        s = s / (1 + 0.025 * float(self.kick[i]))
        lvl = max(0, min(len(self.pyr) - 1, int(math.floor(math.log2(max(1.0, s))))))
        src = self.pyr[lvl]; f = 2 ** lvl; sl = s / f                                   # src px per screen px
        # screen (x, y) <- source (cx/f + (x - W/2) * sl, cy/f + (y - CY) * sl)
        M = np.float32([[1 / sl, 0, W / 2 - cx / f / sl], [0, 1 / sl, CY - cy / f / sl]])
        pic = cv2.warpAffine(src, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        inside = cv2.warpAffine(np.ones(src.shape[:2], np.uint8) * 255, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0).astype(np.float32)[..., None] / 255
        img = self.bg * (1 - inside) + pic.astype(np.float32) * inside
        x0, y0 = W / 2 - cx / s, CY - cy / s; x1, y1 = x0 + self.iw / s, y0 + self.ih / s
        out = Image.fromarray(np.clip(img[..., ::-1], 0, 255).astype(np.uint8)); d = ImageDraw.Draw(out)
        if self.wall == 'gallery' and x1 - x0 < W * 1.5:                             # the gilt frame, while the edges are in view
            t = max(6, int(28 * (self.fit / s)))
            for k, col in enumerate(((120, 86, 34), (196, 158, 82), (148, 110, 48))):
                o = t - k * t // 3
                d.rectangle([x0 - o, y0 - o, x1 + o, y1 + o], outline=col, width=max(2, t // 3))
        if self.mark == 'ring' and self.drop - int(0.6 * FPS) <= i < self.drop + 3:
            tx, ty, size = self.spots[0]
            rx, ry = W / 2 + (tx - cx) / s, CY + (ty - cy) / s; rr = max(26, size / s / 2)
            for k, a in ((6, (255, 60, 60)),):
                d.ellipse([rx - rr, ry - rr, rx + rr, ry + rr], outline=a, width=k)
        if i < self.drop + int(2.5 * FPS) and self.hook:
            y = SAFE_TOP + 60
            for row in self.wrap(self.hook, self.f_hook, W - 220):
                d.text((W / 2, y), row, font=self.f_hook, fill=(255, 255, 255), anchor='mm', stroke_width=6, stroke_fill=(0, 0, 0)); y += 72
        e = self.work
        if i >= self.drop + int(2.5 * FPS) or not self.hook:                       # the museum label once the hook has gone
            y = SAFE_BOTTOM - 190
            title = e.get('title') or ''
            for row in self.wrap(title, self.f_title, W - 260)[:2]:
                d.text((W / 2, y), row, font=self.f_title, fill=(250, 246, 236), anchor='mm', stroke_width=4, stroke_fill=(0, 0, 0)); y += 56
            meta = ' · '.join(x for x in (e.get('artist'), e.get('date'), e.get('museum')) if x)
            d.text((W / 2, y + 4), meta[:60], font=self.f_meta, fill=(230, 224, 210), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        d.text((W / 2, SAFE_BOTTOM - 24), self.credit, font=self.f_credit, fill=(240, 236, 226), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        return np.asarray(out)

    def wrap(self, txt, fnt, width):
        rows, cur = [], ''
        for w in txt.split():
            t = (cur + ' ' + w).strip()
            if fnt.getlength(t) <= width or not cur: cur = t
            else: rows.append(cur); cur = w
        return rows + ([cur] if cur else [])

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; ims = []
            for i in fs:
                fr = self.frame(min(i, self.n - 1)); ims.append(Image.fromarray(fr).resize((360, 640)))
                if '--full' in sys.argv: Image.fromarray(fr).save(out[:-4] + '_f%d.png' % i)
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.work['title'], self.spots, 'drop', self.drop); return
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
        json.dump(dict(K.record(), footage=[self.work['key']]), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'zoom')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
