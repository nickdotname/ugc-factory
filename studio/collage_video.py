#!/usr/bin/env python3
"""psychedelic.station, collage style: a mirrored, maximalist techno-temple that moves to the song.

    python studio/collage_video.py SONG_DIR SEED OUT.mp4                (CQ_WINDOW="t0,t1" picks the stretch)
    python studio/collage_video.py SONG_DIR SEED SHEET.png --frames 0,60,120

Everything is drawn in code, nothing is taken from anyone: a sky and a field, and over them a symmetric altar of
circuit-board panels (chips, buses, LED rows, rows of little eyes), a stone cube with one great eye in it, a black
monitor of turning wireframes, a twisted wireframe hyperboloid over a burst of red lines, chrome spheres, blocks of
voxels and fans of white spikes. Every 8 bars the altar is rebuilt from a new seed (a cut on the downbeat); the
palette moves every 4. The kick dilates the eye and throws the rays, the snare blinks every eye, the hats run the
LEDs, the bass turns the wireframes and twists the hyperboloid.

Knobs (studio/knobs.py): palette (circuit, acid, temple, ice), ground (field, void), density (0.45, 0.6, 0.75).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30; HW = W // 2
TOP, BOT = 150, 1830
PALETTES = {
    'circuit': dict(a=(32, 70, 230), b=(70, 205, 255), c=(255, 222, 40), d=(255, 140, 40), e=(255, 90, 190), ink=(10, 12, 30)),
    'acid':    dict(a=(20, 150, 70), b=(150, 255, 80), c=(255, 60, 200), d=(255, 240, 60), e=(90, 230, 255), ink=(8, 14, 10)),
    'temple':  dict(a=(170, 40, 40), b=(240, 190, 70), c=(30, 150, 150), d=(250, 240, 210), e=(240, 110, 60), ink=(26, 12, 8)),
    'ice':     dict(a=(60, 90, 200), b=(200, 230, 255), c=(140, 255, 230), d=(255, 255, 255), e=(170, 120, 255), ink=(8, 10, 24)),
}
ORDER = ['a', 'b', 'c', 'd', 'e']


def font(size):
    p = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


# ------------------------------------------------------------------ pieces
def sky_field(ground, rng):
    """A summer sky over a green field (or a black void with a grid floor): the backdrop the altar stands in."""
    y = np.arange(H, dtype=np.float32)[:, None, None]
    if ground == 'void':
        img = np.zeros((H, W, 3), np.float32) + np.float32([6, 6, 16])
        for k in range(1, 26):                                           # a perspective grid floor
            yy = int(1500 + 420 * (k / 26) ** 2); img[yy:yy + 2] = (40, 60, 140)
        for k in range(-14, 15):
            cv2.line(img, (HW, 1500), (int(HW + k * 120), H), (40, 60, 140), 2)
        return img
    hz = 1560
    sky = np.float32([90, 150, 235]) * (1 - y / hz) + np.float32([200, 225, 250]) * (y / hz)
    img = np.broadcast_to(sky, (H, W, 3)).copy()
    noise = cv2.resize(np.random.default_rng(rng.randrange(1 << 30)).random((24, 14)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
    cloud = np.clip((noise - 0.55) * 3, 0, 1) * (y[..., 0] < hz - 80)
    img += (255 - img) * cloud[..., None] * 0.9
    g = np.float32([60, 130, 50]) * 0.85 + np.float32([30, 60, 20]) * ((y - hz) / (H - hz)).clip(0, 1)
    img[hz:] = np.broadcast_to(g[hz:], (H - hz, W, 3))
    for k in range(1, 40): img[hz + int(360 * (k / 40) ** 2)] *= 0.9                       # rows in the field
    return img


def split(rect, rng, depth, out, centre):
    x0, y0, x1, y1 = rect; w, h = x1 - x0, y1 - y0
    if depth > 6 or (w < 120 and h < 120) or (depth > 2 and rng.random() < 0.18):
        out.append(rect); return
    if (w > h * 0.8 and w > 80) or h < 80:
        cut = int(x0 + w * rng.uniform(0.3, 0.7))
        if centre - 40 < cut < centre + 40: cut = centre                  # keep the cut that frames the middle column
        split((x0, y0, cut, y1), rng, depth + 1, out, centre); split((cut, y0, x1, y1), rng, depth + 1, out, centre)
    else:
        cut = int(y0 + h * rng.uniform(0.3, 0.7))
        split((x0, y0, x1, cut), rng, depth + 1, out, centre); split((x0, cut, x1, y1), rng, depth + 1, out, centre)


def eye_icon(d, cx, cy, s, ink, white, iris, open_=1.0):
    """A small line-drawn eye: almond, iris, pupil; open_ 0 is shut."""
    hh = s * 0.45 * open_
    pts_top = [(cx - s + 2 * s * k / 12, cy - hh * math.sin(math.pi * k / 12)) for k in range(13)]
    pts_bot = [(cx - s + 2 * s * k / 12, cy + hh * math.sin(math.pi * k / 12)) for k in range(13)]
    if open_ > 0.15:
        d.polygon(pts_top + pts_bot[::-1], fill=white)
        r = min(hh, s * 0.42); d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=iris)
        d.ellipse([cx - r * 0.45, cy - r * 0.45, cx + r * 0.45, cy + r * 0.45], fill=ink)
    d.line(pts_top, fill=ink, width=max(2, int(s / 8))); d.line(pts_bot, fill=ink, width=max(2, int(s / 8)))


def chrome(img, cx, cy, r, tint):
    """A chrome sphere: the sky reflected in it, a dark horizon band, a hard highlight."""
    y0, y1, x0, x1 = int(max(0, cy - r)), int(min(H, cy + r)), int(max(0, cx - r)), int(min(W, cx + r))
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32); nx, ny = (xx - cx) / r, (yy - cy) / r; d2 = nx * nx + ny * ny
    m = d2 <= 1; nz = np.sqrt(np.clip(1 - d2, 0, 1))
    ref = -ny * 0.9 + nz * 0.3                                          # how far up the reflected ray points
    col = np.where((ref > 0)[..., None], np.float32([150, 190, 240]) * (0.6 + 0.6 * ref[..., None]), np.float32([40, 42, 50]) + np.float32(tint) * 0.3)
    col = np.where((np.abs(ref) < 0.06)[..., None], np.float32([235, 240, 250]), col)
    spec = np.clip(1 - np.hypot(nx + 0.35, ny + 0.4) / 0.22, 0, 1) ** 2
    col = col + 255 * spec[..., None]
    img[y0:y1, x0:x1] = np.where(m[..., None], np.clip(col, 0, 255), img[y0:y1, x0:x1])


def project(p, ang, cx, cy, s):
    """3D points (n, 3) turned by (ax, ay) and projected to the screen."""
    ax, ay = ang; ca, sa, cb, sb = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay)
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    x, z = x * cb + z * sb, -x * sb + z * cb
    y, z = y * ca - z * sa, y * sa + z * ca
    f = 4 / (4 + z); return np.stack([cx + x * s * f, cy + y * s * f], 1)


def wire_sphere():
    segs = []
    for k in range(1, 6):
        la = -math.pi / 2 + math.pi * k / 6; r = math.cos(la); y = math.sin(la)
        pts = [(r * math.cos(a), y, r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 25)]; segs.append(np.array(pts))
    for k in range(8):
        a = math.pi * k / 8; segs.append(np.array([(math.cos(la) * math.cos(a), math.sin(la), math.cos(la) * math.sin(a)) for la in np.linspace(-math.pi / 2, math.pi / 2, 13)] +
                                                  [(-math.cos(la) * math.cos(a), math.sin(la), -math.cos(la) * math.sin(a)) for la in np.linspace(math.pi / 2, -math.pi / 2, 13)]))
    return segs


CUBE = [np.array(e, float) for e in ([(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, -1)], [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1), (-1, -1, 1)],
                                     [(-1, -1, -1), (-1, -1, 1)], [(1, -1, -1), (1, -1, 1)], [(1, 1, -1), (1, 1, 1)], [(-1, 1, -1), (-1, 1, 1)])]
PYR = [np.array(e, float) for e in ([(-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1), (-1, 1, -1)], [(-1, 1, -1), (0, -1.2, 0)], [(1, 1, -1), (0, -1.2, 0)],
                                    [(1, 1, 1), (0, -1.2, 0)], [(-1, 1, 1), (0, -1.2, 0)])]
SPHERE = wire_sphere()


# ------------------------------------------------------------------ the video
class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r; self.seed = seed
        self.pal_name = K.pick('palette', sorted(PALETTES), r); self.ground = K.pick('ground', ['field', 'void'], r, weights=[3, 1])
        self.density = float(K.pick('density', [0.45, 0.6, 0.75], r))
        a = audio.load(self.slug, t0, t1); self.n = a['n']
        self.kick = audio.hits(a['kicks'], self.n, 7.0); self.snare = audio.hits(a['snares'], self.n, 10.0)
        self.hats = audio.hits(a.get('hats', []), self.n, 14.0); self.bass = np.convolve(a['bass'], np.ones(5) / 5, 'same')
        bars = [int(round(f)) for b, f in a['beats'] if b % 4 == 0 and 0 <= f < self.n]
        self.sections = [0] + [f for k, f in enumerate(bars) if k % 8 == 0 and f > FPS] if bars else [0]
        self.paltimes = [0] + [f for k, f in enumerate(bars) if k % 4 == 0 and f > FPS] if bars else [0]
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.f_credit = font(28); self.cache = {}; self.spin = np.cumsum(0.02 + 0.06 * self.bass)

    def palette(self, i):
        k = max(j for j, f in enumerate(self.paltimes) if f <= i); P = PALETTES[self.pal_name]
        keys = ORDER[k % 5:] + ORDER[:k % 5]                              # the accents rotate every 4 bars
        return {**{ORDER[j]: P[keys[j]] for j in range(5)}, 'ink': P['ink']}

    def section(self, i):
        return max(j for j, f in enumerate(self.sections) if f <= i)

    def build(self, s, pal):
        """The still part of an altar: backdrop, the circuit panels (left half, mirrored), spheres, voxels, spike fans."""
        key = (s, tuple(pal['a']))
        if key in self.cache: return self.cache[key]
        r = random.Random(self.seed * 31 + s); img = sky_field(self.ground, r)
        layer = Image.new('RGBA', (HW, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
        rects = []; split((0, TOP, HW, BOT), r, 0, rects, HW - 150)
        anim = []
        for (x0, y0, x1, y1) in rects:
            w, h = x1 - x0, y1 - y0
            if x0 >= HW - 150 or r.random() > self.density: continue          # the middle column, and holes onto the sky
            kind = r.choice(['chip', 'chip', 'grid', 'bus', 'leds', 'eyes'])
            ink = pal['ink'] + (255,)
            d.rectangle([x0 + 3, y0 + 3, x1 - 3, y1 - 3], fill=pal['a'] + (255,), outline=pal['b'] + (255,), width=4)
            if kind == 'chip':
                m = min(w, h) * 0.22; d.rectangle([x0 + m, y0 + m, x1 - m, y1 - m], fill=pal['c'] + (255,), outline=ink, width=3)
                for px in range(int(x0 + m), int(x1 - m), 12):
                    d.line([px, y0 + m - 10, px, y0 + m], fill=pal['d'] + (255,), width=4); d.line([px, y1 - m, px, y1 - m + 10], fill=pal['d'] + (255,), width=4)
                if w > 60 and h > 60: d.rectangle([x0 + m + 10, y0 + m + 10, x0 + m + 26, y0 + m + 26], fill=pal['e'] + (255,))
            elif kind == 'grid':
                for gx in range(x0 + 12, x1 - 16, 16):
                    for gy in range(y0 + 12, y1 - 16, 16):
                        d.rectangle([gx, gy, gx + 10, gy + 10], fill=(pal['b'] if (gx // 16 + gy // 16) % 3 else pal['e']) + (255,))
            elif kind == 'bus':
                vert = h > w
                for q, c in enumerate(range((x0 if vert else y0) + 10, (x1 if vert else y1) - 10, 7)):
                    col = pal[ORDER[q % 5]] + (255,)
                    d.line([c, y0 + 8, c, y1 - 8] if vert else [x0 + 8, c, x1 - 8, c], fill=col, width=3)
            elif kind == 'leds':
                for gx in range(x0 + 18, x1 - 14, 26):
                    for gy in range(y0 + 18, y1 - 14, 26): anim.append(('led', gx, gy, r.random()))
            else:
                for gx in range(x0 + 34, x1 - 30, 64):
                    for gy in range(y0 + 30, y1 - 24, 46): anim.append(('eye', gx, gy, r.random()))
        half = np.asarray(layer).astype(np.float32); alpha = half[..., 3:] / 255
        full = np.concatenate([half, half[:, ::-1]], 1); fa = np.concatenate([alpha, alpha[:, ::-1]], 1)
        img = img * (1 - fa) + full[..., :3] * fa
        # chrome spheres low on the sides, voxel blocks high, spike fans in the middle height
        for k in range(r.randint(1, 3)):
            cx, cy, rad = r.uniform(70, 260), r.uniform(1350, 1700), r.uniform(50, 85)
            chrome(img, cx, cy, rad, pal['e']); chrome(img, W - cx, cy, rad, pal['e'])
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        bx, by = r.uniform(60, 180), r.uniform(220, 420)
        for gx in range(5):                                                   # voxel blocks (isometric), mirrored
            for gy in range(4):
                if r.random() < 0.35: continue
                hgt = r.randint(1, 3)
                for zz in range(hgt):
                    x, y = bx + (gx - gy) * 22, by + (gx + gy) * 12 - zz * 24
                    for sx in (x, W - x):
                        d.polygon([(sx, y), (sx + 22, y + 12), (sx, y + 24), (sx - 22, y + 12)], fill=(250, 248, 240))
                        d.polygon([(sx - 22, y + 12), (sx, y + 24), (sx, y + 48), (sx - 22, y + 36)], fill=(190, 186, 176))
                        d.polygon([(sx + 22, y + 12), (sx, y + 24), (sx, y + 48), (sx + 22, y + 36)], fill=(120, 116, 110))
        fx, fy = r.uniform(150, 260), r.uniform(820, 1100)
        for k in range(9):                                                    # a fan of white spikes, mirrored
            a = -math.pi / 2 + (k - 4) * 0.22; L = r.uniform(110, 190)
            for sx, sg in ((fx, 1), (W - fx, -1)):
                tip = (sx + sg * L * math.cos(a), fy + L * math.sin(a)); bl = (sx + sg * 10 * math.cos(a + 1.57), fy + 10 * math.sin(a + 1.57))
                br = (sx - sg * 10 * math.cos(a + 1.57), fy - 10 * math.sin(a + 1.57))
                d.polygon([bl, tip, br], fill=(235, 235, 240), outline=(60, 60, 70))
        base = np.asarray(im).astype(np.float32)
        self.cache = {key: (base, anim)}                                      # one altar at a time is enough
        return base, anim

    # ---------------------------------------------------------------- the moving middle
    def middle(self, d, i, pal):
        kick, snare, bass = self.kick[i], self.snare[i], self.bass[i]; t = i / FPS; ink = pal['ink']
        # rays from the top lattice to the corners, and the beam down the middle
        for k in range(16):
            a = math.pi * (k + 0.5) / 16
            d.line([HW, 350, HW + math.cos(a) * 700, 350 - math.sin(a) * 700 * (0.4 + 0.6 * kick)], fill=(250, 250, 250), width=2)
        d.line([HW, 330, HW, 1700], fill=pal['c'], width=int(4 + 8 * kick))
        # the diamond lattice
        dw, dh = 330, 150
        d.polygon([(HW - dw, 350), (HW, 350 - dh), (HW + dw, 350), (HW, 350 + dh)], fill=(250, 250, 250), outline=ink)
        for k in range(1, 6):
            s = k / 6; d.polygon([(HW - dw * s, 350), (HW, 350 - dh * s), (HW + dw * s, 350), (HW, 350 + dh * s)], outline=ink, width=3)
        for k in range(-4, 5):
            d.ellipse([HW + k * 50 - 10, 350 - 10, HW + k * 50 + 10, 350 + 10], outline=ink, width=3)
        # the stone cube with the eye
        cx, cy, s = HW, 760, 250
        top = [(cx - s, cy - s + 40), (cx + s, cy - s + 40), (cx + s - 60, cy - s - 30), (cx - s + 60, cy - s - 30)]
        d.polygon([(cx - s, cy - s + 40), (cx + s, cy - s + 40), (cx + s, cy + s - 60), (cx - s, cy + s - 60)], fill=(225, 214, 190))
        d.polygon(top, fill=(240, 232, 214)); d.polygon([(cx - s, cy + s - 60), (cx + s, cy + s - 60), (cx + s - 40, cy + s + 30), (cx - s + 40, cy + s + 30)], fill=(40, 40, 48))
        blink = 1.0 - min(1.0, snare * 1.4) if snare > 0.6 else 1.0
        ew = 170; eh = 85 * blink
        lid = [(cx - ew + 2 * ew * k / 20, cy - eh * math.sin(math.pi * k / 20)) for k in range(21)]
        low = [(cx - ew + 2 * ew * k / 20, cy + eh * math.sin(math.pi * k / 20)) for k in range(21)]
        d.polygon([(p[0] + 18, p[1] + 26) for p in low] + [(cx + ew + 30, cy + 40)], fill=(140, 130, 112))   # the socket's shadow
        if blink > 0.15:
            d.polygon(lid + low[::-1], fill=(245, 245, 250))
            ir = 70 * min(1, blink * 1.2); hue = pal['b']
            d.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], fill=hue, outline=ink, width=3)
            for k in range(14):
                a = 2 * math.pi * k / 14; d.line([cx + math.cos(a) * ir * 0.4, cy + math.sin(a) * ir * 0.4, cx + math.cos(a) * ir, cy + math.sin(a) * ir], fill=pal['e'], width=3)
            pw = 10 + 26 * kick                                                 # a slit that opens on the kick
            d.ellipse([cx - pw, cy - ir * 0.9, cx + pw, cy + ir * 0.9], fill=(10, 8, 14))
        d.line(lid, fill=ink, width=6); d.line(low, fill=ink, width=4)
        # the monitor of wireframes
        mx0, my0, mx1, my1 = HW - 250, 1080, HW + 250, 1250
        d.rectangle([mx0 - 8, my0 - 8, mx1 + 8, my1 + 8], fill=pal['a']); d.rectangle([mx0, my0, mx1, my1], fill=(4, 4, 8))
        ang = (0.6 + 0.3 * math.sin(t), self.spin[i])
        for shape, ox, col in ((SPHERE, -160, pal['b']), (CUBE, 0, pal['e']), (PYR, 160, pal['c'])):
            for seg in shape:
                pts = project(seg, ang, HW + ox, (my0 + my1) / 2, 52 + 6 * kick)
                d.line([tuple(p) for p in pts], fill=col, width=2)
        # the twisted hyperboloid over a red burst
        hy0, hy1, rx = 1400, 1700, 230
        for k in range(48):
            a = 2 * math.pi * k / 48; L = 160 + 120 * kick
            d.line([HW, (hy0 + hy1) / 2, HW + math.cos(a) * L, (hy0 + hy1) / 2 + math.sin(a) * L], fill=(230, 40, 50), width=2)
        tw = 0.8 + 1.2 * bass + 0.3 * math.sin(t * 0.7)
        for k in range(36):
            a = 2 * math.pi * k / 36
            p0 = (HW + rx * math.cos(a), hy0 + 40 * math.sin(a)); p1 = (HW + rx * math.cos(a + tw), hy1 + 40 * math.sin(a + tw))
            d.line([p0, p1], fill=(250, 250, 250), width=3)
        d.ellipse([HW - rx, hy0 - 40, HW + rx, hy0 + 40], outline=ink, width=4); d.ellipse([HW - rx, hy1 - 40, HW + rx, hy1 + 40], outline=ink, width=4)
        d.ellipse([HW - 14, hy1 - 14, HW + 14, hy1 + 14], fill=pal['c'])

    def frame(self, i):
        pal = self.palette(i); s = self.section(i)
        base, anim = self.build(s, pal)
        im = Image.fromarray(base.astype(np.uint8)); d = ImageDraw.Draw(im)
        hat, snare = self.hats[i], self.snare[i]
        for kind, x, y, ph in anim:
            for sx in (x, W - x):
                if kind == 'led':
                    on = ((i // 3 + int(ph * 10)) % 5 == 0) or (hat > 0.5 and ph > 0.5) or self.kick[i] > 0.7
                    d.ellipse([sx - 7, y - 7, sx + 7, y + 7], fill=pal['d'] if on else pal['ink'], outline=pal['b'], width=2)
                else:
                    eye_icon(d, sx, y, 24, pal['ink'], (250, 250, 250), pal['e'], 0.0 if snare > 0.7 and ph > 0.3 else 1.0)
        self.middle(d, i, pal)
        f = np.asarray(im).astype(np.float32)
        if i in self.sections[1:] or (i - 1) in self.sections[1:]: f = f * 0.4 + 255 * 0.6          # a white pop on the cut
        z = 1 + 0.012 * self.kick[i]
        if z > 1.001:
            M = cv2.getRotationMatrix2D((HW, H / 2), 0, z); f = cv2.warpAffine(f, M, (W, H), borderMode=cv2.BORDER_REFLECT)
        if snare > 0.6:
            sh = int(8 * snare); f[..., 0] = np.roll(f[..., 0], sh, 1); f[..., 2] = np.roll(f[..., 2], -sh, 1)
        out = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(out)
        tw = d.textlength(self.credit, font=self.f_credit)
        d.rounded_rectangle([HW - tw / 2 - 18, 1290, HW + tw / 2 + 18, 1336], 20, fill=(0, 0, 0))   # between the monitor and the hyperboloid
        d.text((HW, 1313), self.credit, font=self.f_credit, fill=(245, 245, 245), anchor='mm')
        return np.asarray(out)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((432, 768)) for f in fs]
            sheet = Image.new('RGB', (432 * len(ims), 768))
            for k, im in enumerate(ims): sheet.paste(im, (432 * k, 0))
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
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
