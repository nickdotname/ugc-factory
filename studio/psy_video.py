#!/usr/bin/env python3
"""Audio-reactive psychedelic visuals for a stretch of a song.

    python studio/psy_video.py studio/songs/<slug> <seed> out.mp4          (window from CQ_WINDOW="start,end")
    python studio/psy_video.py studio/songs/<slug> <seed> out.png --frames 120,400

No footage: the picture is generated from the song's own stems (made by prep_song.py). Bass swells the zoom, drums flash and kick the colours round, the vocal bends
the pattern, everything else sets how busy it is. The seed picks the pattern, the symmetry,
the palette and whether the picture feeds back into itself (or, some of the time, a 1990s
ray-traced landscape in the Bryce manner instead: mountains, mirror water, chrome spheres),
and what sits on top: the lyrics
(one huge word at a time, or a line that fills in), the vocal drawn as a ring, a turning
line figure, contour bands. Every seed is a different video of the same music. A recipe .json is written beside the video.
"""
import sys, os, json, random, subprocess
import numpy as np, soundfile as sf, cv2
from PIL import Image, ImageDraw, ImageFont

SONG_DIR = os.path.abspath(sys.argv[1]); seed = int(sys.argv[2]); out = sys.argv[3]
SONG = json.load(open(os.path.join(SONG_DIR, 'song.json')))
def _find(stem, exts): return next((os.path.join(SONG_DIR, stem + e) for e in exts if os.path.exists(os.path.join(SONG_DIR, stem + e))), os.path.join(SONG_DIR, stem + exts[0]))
MASTER = _find('master', ('.wav', '.flac', '.ogg')); stem_path = lambda name: _find(os.path.join('stems', name), ('.flac', '.ogg'))
T0, T1 = [float(x) for x in os.environ['CQ_WINDOW'].split(',')]
FPS, W, H = 30, 1080, 1920
w, h = 432, 768                      # drawn small, scaled up: soft edges suit it and it is 6x faster
N = int((T1 - T0) * FPS); rng = random.Random(seed)

# ---- what the music is doing, per frame -------------------------------------------------
def env(name, smooth):
    a, sr = sf.read(stem_path(name), dtype='float32')
    a = a[int(T0 * sr):int(T1 * sr)]; hop = sr / FPS
    e = np.array([np.sqrt(np.mean(a[int(i * hop):int((i + 1) * hop)] ** 2) + 1e-9) for i in range(N)])
    e = e / (np.percentile(e, 98) + 1e-9); e = np.clip(e, 0, 1.5)
    o = np.zeros(N); v = 0.0
    for i in range(N):                # fast up, slow down: a hit lands at once and then decays
        v = e[i] if e[i] > v else v * smooth + e[i] * (1 - smooth); o[i] = v
    return o
BASS, DRUM, VOX, OTH = env('Bass', .85), env('Drums', .7), env('Vocals', .8), env('Other', .9)
onset = np.clip(np.diff(DRUM, prepend=0), 0, None); onset = onset / (onset.max() + 1e-9)
hue_kick = np.cumsum(onset * (onset > .35)) * 0.07      # each real drum hit moves the colours on a step

# ---- the plan this seed makes -----------------------------------------------------------
PALS = {'acid': [(.5, .5, .5), (.5, .5, .5), (1, 1, 1), (0, .33, .67)], 'sunset': [(.5, .5, .5), (.5, .5, .5), (1, 1, .5), (.8, .9, .3)],
        'ocean': [(.5, .5, .5), (.5, .5, .5), (1, .7, .4), (0, .15, .2)], 'neon': [(.5, .5, .5), (.5, .5, .5), (2, 1, 0), (.5, .2, .25)],
        'candy': [(.8, .5, .4), (.2, .4, .2), (2, 1, 1), (0, .25, .25)], 'lava': [(.5, .5, .5), (.5, .5, .5), (1, 1, 1), (0, .1, .2)]}
plan = dict(field=os.environ.get('CQ_FIELD') or rng.choice(['kaleido', 'tunnel', 'marble', 'rings', 'cells', 'bryce', 'bryce', 'bryce']), sym=rng.choice([3, 4, 5, 6, 8, 12]),
            pal=rng.choice(sorted(PALS)), feedback=rng.random() < .6, spin=rng.choice([-1, 1]) * rng.uniform(.03, .12),
            warp=rng.uniform(.6, 1.6), mirror=rng.random() < .35, grain=rng.random() < .5, strobe=rng.random() < .3,
            lyrics=rng.choice(['word', 'word', 'word', 'line', 'line', None]), ring=rng.random() < .5,
            motif=rng.choice([None, None, 'poly', 'star', 'eye', 'cube']), contour=rng.random() < .55, poster=rng.random() < .3,
            font=rng.choice(['Poppins-Bold.ttf', 'Poppins-Black.ttf', 'DejaVuSerif-Bold.ttf']), word_y=rng.choice([.5, .5, .72]),
            scale=rng.uniform(2.2, 4.5), second=rng.choice([None, 'kaleido', 'rings', 'marble']), flip_at=rng.uniform(.4, .65))
if plan['field'] == 'bryce': plan.update(motif=None, ring=False, strobe=False)      # the landscape is busy enough: words only
ys, xs = np.mgrid[0:h, 0:w].astype(np.float32); X = (xs - w / 2) / (w / 2); Y = (ys - h / 2) / (w / 2)
R = np.sqrt(X * X + Y * Y) + 1e-6; A = np.arctan2(Y, X)

def palette(t, name):
    a, b, c, d = [np.array(v, np.float32) for v in PALS[name]]
    return a + b * np.cos(6.28318 * (c * t[..., None] + d))

def field(kind, T, i):
    b, dr, vx, ot = BASS[i], DRUM[i], VOX[i], OTH[i]; sc = plan['scale'] * (1 - .22 * b)   # bass pushes in
    ang = A + T * plan['spin'] * 6.283 + .5 * vx * np.sin(R * 3 - T)                         # vocal bends it
    if kind == 'kaleido':
        s = plan['sym']; a = np.abs(((ang / (6.28318 / s)) % 1) - .5) * 2
        return np.sin(R * sc * 3 - T * 1.3 + a * 4 * plan['warp']) * .5 + np.sin(a * 9 + R * sc * (1.5 + ot) + T * .7) * .5
    if kind == 'tunnel':
        d = 1 / (R + .12); return np.sin(d * sc * .8 + T * 2.2 + b * 2) * .6 + np.sin(ang * plan['sym'] + d * 1.5 - T) * .4
    if kind == 'marble':
        u = X * sc + np.sin(Y * sc * 1.3 + T * .6) * plan['warp'] * (1 + vx); v = Y * sc + np.cos(u * 1.1 - T * .5) * plan['warp']
        return np.sin(u + np.sin(v * 1.7 + T * .3) * 2) * .5 + np.cos(v * .8 + ot * 2) * .5
    if kind == 'rings':
        s = plan['sym']; wob = np.sin(ang * s + T * 1.5) * (.15 + .5 * vx)
        return np.sin((R + wob * .2) * sc * 6 - T * 2.5 - b * 3)
    u = X * sc + np.sin(T * .4); v = Y * sc + np.cos(T * .3)                                 # cells
    return np.sin(u * 2 + np.sin(v * 2 + T)) * np.cos(v * 2 + np.cos(u * 2 - T * .8)) + .3 * np.sin(R * sc * 4 - T * 2)


# ---- "bryce": a 1990s ray-traced landscape (fractal mountains, mirror water, chrome spheres, hazy sky) ----
BW, BH = 216, 384                    # drawn very small on purpose: the crunch is the look
BPAL = {'dusk': dict(zen=(.22, .08, .42), hor=(.98, .55, .72), sun=(1, .55, .3), lo=(.86, .76, .5), mid=(.36, .3, .42), hi=(.96, .9, 1), wat=(.1, .45, .55)),
        'lagoon': dict(zen=(.04, .18, .45), hor=(.62, .92, .86), sun=(1, .95, .7), lo=(.92, .82, .6), mid=(.3, .36, .3), hi=(1, 1, 1), wat=(.04, .32, .5)),
        'mars': dict(zen=(.45, .12, .1), hor=(1, .74, .4), sun=(1, 1, .8), lo=(.72, .36, .2), mid=(.4, .2, .22), hi=(.96, .8, .6), wat=(.38, .1, .3)),
        'acid': dict(zen=(.08, .42, .22), hor=(.96, .95, .4), sun=(1, .4, .8), lo=(.6, .9, .5), mid=(.2, .3, .5), hi=(1, .8, 1), wat=(.5, .1, .6))}
def bryce_setup():
    r = np.random.default_rng(seed * 31 + 7); n = 256; fy, fx = np.meshgrid(np.fft.fftfreq(n), np.fft.fftfreq(n), indexing='ij'); f = np.sqrt(fx * fx + fy * fy); f[0, 0] = 1
    hm = np.real(np.fft.ifft2(np.fft.fft2(r.standard_normal((n, n))) / f ** r.uniform(1.7, 2.1))); hm = (hm - hm.min()) / (hm.max() - hm.min())
    if r.random() < .5: hm = 1 - np.abs(2 * hm - 1)                      # ridged mountains
    hgt = (hm - r.uniform(.42, .55)) * r.uniform(2.6, 3.6)
    yy, xx = np.mgrid[0:n, 0:n]
    for _ in range(int(r.integers(2, 6))):                               # obelisks: thin steep spikes standing in the scene
        cx, cy, rad, tall = r.integers(0, n), r.integers(0, n), r.uniform(2.5, 5), r.uniform(1.6, 3.2)
        d = np.maximum(np.abs((xx - cx + n // 2) % n - n // 2), np.abs((yy - cy + n // 2) % n - n // 2)); hgt = np.maximum(hgt, np.clip(1 - d / rad, 0, 1) * tall)
    hgt = hgt.astype(np.float32); gx = (np.roll(hgt, -1, 1) - np.roll(hgt, 1, 1)) * .5; gy = (np.roll(hgt, -1, 0) - np.roll(hgt, 1, 0)) * .5
    cl = np.real(np.fft.ifft2(np.fft.fft2(r.standard_normal((n, n))) / f ** 1.6)); cl = ((cl - cl.min()) / (cl.max() - cl.min())).astype(np.float32)
    v, u = np.mgrid[0:BH, 0:BW].astype(np.float32); u = (u - BW / 2) / (BH / 2); v = -(v - BH / 2) / (BH / 2)
    sun = np.array([r.uniform(-.5, .5), r.uniform(.12, .35), 1.0]); sun /= np.linalg.norm(sun)
    sph = [(r.uniform(-.9, .9), r.uniform(.55, 1.3), r.uniform(2.6, 4.6), r.uniform(.22, .5), r.uniform(0, 6)) for _ in range(int(r.integers(1, 4)))]
    return dict(hgt=hgt, gx=gx.astype(np.float32), gy=gy.astype(np.float32), cl=cl, u=u, v=v, sun=sun, sph=sph, pal={k: np.array(c, np.float32) for k, c in BPAL[r.choice(sorted(BPAL))].items()},
                speed=r.uniform(.35, .8), sway=r.uniform(.2, .7), camy=r.uniform(.75, 1.25), n=n, S=n / 16.0)
BR = None
def bsample(m, x, z):                                                   # look the map up at world x,z (it tiles for ever)
    return cv2.remap(m, ((x * BR['S']) % BR['n']).astype(np.float32), ((z * BR['S']) % BR['n']).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
def bsky(dx, dy, dz, T, i):
    P = BR['pal']; t = np.clip(dy, 0, 1) ** .55; col = P['hor'] * (1 - t[..., None]) + P['zen'] * t[..., None]
    k = 1 / (np.abs(dy) + .16); c = cv2.remap(BR['cl'], ((dx * k * 26 + T * 3) % BR['n']).astype(np.float32), ((dz * k * 26 + T * 1.2) % BR['n']).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    c = np.clip((c - .5) * 4, 0, 1) * np.clip(dy * 6, 0, 1); col = col * (1 - .55 * c[..., None]) + (P['hor'] * .5 + .5) * .55 * c[..., None]
    s = np.clip(dx * BR['sun'][0] + dy * BR['sun'][1] + dz * BR['sun'][2], 0, 1); return col + P['sun'] * (s ** 500 * 1.2 + s ** 40 * (.1 + .25 * DRUM[i]))[..., None]
def bryce(i):
    global BR
    if BR is None: BR = bryce_setup()
    T = i / FPS; P = BR['pal']; b, dr, vx = BASS[i], DRUM[i], VOX[i]; u, v = BR['u'], BR['v']
    ox, oz = BR['sway'] * np.sin(T * .23), T * BR['speed']; yaw = .25 * np.sin(T * .17)
    ahead = max(float(BR['hgt'][int((oz + q) * BR['S']) % BR['n'], int(ox * BR['S']) % BR['n']]) for q in np.arange(-0.5, 3.01, .25))      # stay above whatever is coming
    oy = max(BR['camy'], ahead + .55) + .06 * np.sin(T * .5)
    dx, dy, dz = u * np.cos(yaw) + 1.5 * np.sin(yaw), v - .16, 1.5 * np.cos(yaw) - u * np.sin(yaw); ln = np.sqrt(dx * dx + dy * dy + dz * dz); dx, dy, dz = dx / ln, dy / ln, dz / ln
    hit = np.full((BH, BW), 0, np.float32); done = np.zeros((BH, BW), bool); pt = .25
    for k in range(52):                                                 # walk each ray out until it goes under the land or the water
        t = .25 * (1.085 ** k); hh = np.maximum(bsample(BR['hgt'], ox + dx * t, oz + dz * t), 0); under = (oy + dy * t < hh) & ~done
        hit[under] = (pt + t) * .5; done |= under; pt = t
    px, pz = ox + dx * hit, oz + dz * hit; hh = bsample(BR['hgt'], px, pz); wet = done & (hh <= 0.01)
    gx, gy = bsample(BR['gx'], px, pz) * BR['S'], bsample(BR['gy'], px, pz) * BR['S']; nl = 1 / np.sqrt(gx * gx + 1 + gy * gy)
    lam = np.clip((-gx * BR['sun'][0] + BR['sun'][1] - gy * BR['sun'][2]) * nl, 0, 1); a = np.clip(hh / 1.3, 0, 1)[..., None]
    land = np.where(a < .45, P['lo'] + (P['mid'] - P['lo']) * (a / .45), P['mid'] + (P['hi'] - P['mid']) * ((a - .45) / .55)) * (.3 + .9 * lam[..., None])
    rip = (.03 + .05 * b) * np.sin(pz * 9 + T * 2.2) + .02 * np.sin(px * 13 - T * 1.7)
    water = P['wat'] * .3 + bsky(dx + rip, np.abs(dy) + .02, dz, T, i) * .75
    sky = bsky(dx, dy, dz, T, i); fog = (1 - np.exp(-hit * .16))[..., None]
    img = np.where(done[..., None], np.where(wet[..., None], water, land) * (1 - fog) + (P['hor'] * .9) * fog, sky)
    for sx, sy, sz, rad, ph in BR['sph']:                               # chrome spheres hanging in front of the camera
        cx, cy, cz = ox + sx, sy + .14 * np.sin(T * .9 + ph) * (1 + vx), oz + sz; rr = rad * (1 + .28 * b)
        lx, ly, lz = ox - cx, oy - cy, oz - cz; bq = dx * lx + dy * ly + dz * lz; disc = bq * bq - (lx * lx + ly * ly + lz * lz - rr * rr); ts = -bq - np.sqrt(np.maximum(disc, 0))
        on = (disc > 0) & (ts > 0) & (~done | (ts < hit))
        nx, ny, nz = (lx + dx * ts) / rr, (ly + dy * ts) / rr, (lz + dz * ts) / rr; dn = dx * nx + dy * ny + dz * nz; rx, ry, rz = dx - 2 * dn * nx, dy - 2 * dn * ny, dz - 2 * dn * nz
        ref = np.where((ry > 0)[..., None], bsky(rx, ry, rz, T, i), (P['wat'] * .5 + P['mid'] * .5) * (.5 + .5 * np.clip(-ry, 0, 1))[..., None] + bsky(rx, -ry, rz, T, i) * .35)
        img = np.where(on[..., None], ref * (.82 + .18 * np.clip(1 + dn, 0, 1)[..., None]), img)
    img = np.clip(img * (.92 + .25 * dr), 0, 1) ** .9
    bay = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16 - .5        # the 1994 colour depth
    img = np.floor(img * 23 + np.tile(bay, (BH // 4, BW // 4))[..., None] + .5) / 23
    return cv2.resize(np.clip(img, 0, 1).astype(np.float32), (w, h), interpolation=cv2.INTER_NEAREST)

def frame(i, prev):
    if plan['field'] == 'bryce': return bryce(i - i % 2)          # 15 pictures a second, like the real thing never managed
    T = i / FPS; f = field(plan['field'], T, i)
    if plan['second'] and i / N > plan['flip_at']:           # a second pattern folds in partway through
        m = min(1.0, (i / N - plan['flip_at']) * 6); f = f * (1 - m * .6) + field(plan['second'], T * 1.1, i) * m * .6
    t = f * .28 + T * .035 + hue_kick[i] + R * .12
    if plan['poster']: t = np.floor(t * 9) / 9
    img = palette(t, plan['pal'])
    if plan['contour']: img *= (.72 + .28 * np.cos(f * 16 + T * 2))[..., None]          # fine bands ride the pattern
    img *= (.55 + .45 * np.clip(1.25 - R * .55, 0, 1)[..., None])                           # darker towards the edges
    img *= .8 + .5 * DRUM[i]                                                                 # drums brighten it
    if plan['strobe'] and onset[i] > .6: img = 1 - img
    if plan['mirror']: img[:, w // 2:] = img[:, :w // 2][:, ::-1][:, :w - w // 2]
    img = np.clip(img, 0, 1)
    if plan['feedback'] and prev is not None:                # the last frame, zoomed and turned, shows through
        z = 1.02 + .05 * BASS[i]; M = cv2.getRotationMatrix2D((w / 2, h / 2), plan['spin'] * 20, z)
        back = cv2.warpAffine(prev, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        k = .55 - .35 * DRUM[i]; img = img * (1 - k) + back * k
    return img.astype(np.float32)


# ---- what sits on top (drawn at full size so type and lines stay sharp) ------------------
LINES = [(e, ws) for e, ws in json.load(open(os.path.join(SONG_DIR, 'lines.json'))) if ws and ws[0][1] < T1 and e > T0]
VRAW, VSR = sf.read(stem_path('Vocals'), dtype='float32'); VRAW = VRAW[int(T0 * VSR):int(T1 * VSR)]
VRAW = VRAW / (np.abs(VRAW).max() + 1e-9)
def _font(size):
    for d in ('/usr/share/fonts/truetype/google-fonts/', '/usr/share/fonts/truetype/dejavu/', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts') + '/'):
        if os.path.exists(d + plan['font']): return ImageFont.truetype(d + plan['font'], size)
    return ImageFont.truetype(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts', 'Montserrat-ExtraBold.ttf'), size)
_cache = {}
def word_img(text, size):
    key = (text, size)
    if key not in _cache:
        f = _font(size); l, t, r, b = f.getbbox(text)
        while r - l > W - 120 and size > 60: size -= 10; f = _font(size); l, t, r, b = f.getbbox(text)
        im = Image.new('L', (r - l + 40, b - t + 40), 0); ImageDraw.Draw(im).text((20 - l, 20 - t), text, font=f, fill=255)
        _cache[key] = np.asarray(im, np.float32) / 255
    return _cache[key]
def stamp(a, m, cx, cy, col, k=1.0):
    hh, ww = m.shape; x0 = int(cx - ww / 2); y0 = int(cy - hh / 2); X0, Y0 = max(x0, 0), max(y0, 0); X1, Y1 = min(x0 + ww, W), min(y0 + hh, H)
    if X1 <= X0 or Y1 <= Y0: return
    mm = m[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0, None] * k; reg = a[Y0:Y1, X0:X1].astype(np.float32)
    a[Y0:Y1, X0:X1] = (reg * (1 - mm) + np.array(col, np.float32) * mm).astype(np.uint8)
def now_line(Ta):
    for e, ws in LINES:
        if ws[0][1] - .05 <= Ta <= e + .25: return e, ws
    return None
def overlays(a, i):
    T = i / FPS; Ta = T0 + T; b, dr = BASS[i], DRUM[i]; cx, cy = W // 2, H // 2
    if plan['motif']:
        r = 330 * (1 + .3 * b); th = T * plan['spin'] * 9; n = plan['sym'] if plan['sym'] <= 8 else 6; lw = 5
        def ngon(n, r, th): return np.array([[cx + r * np.cos(th + k * 6.28318 / n), cy + r * np.sin(th + k * 6.28318 / n)] for k in range(n)], np.int32)
        if plan['motif'] == 'poly':
            for q in range(4): cv2.polylines(a, [ngon(n, r * (1 - q * .2), th + q * .25)], True, (255, 255, 255), lw, cv2.LINE_AA)
        elif plan['motif'] == 'star':
            p = ngon(n * 2 if n % 2 else n, r, th)
            for k in range(len(p)): cv2.line(a, tuple(p[k]), tuple(p[(k + len(p) // 2 - 1) % len(p)]), (255, 255, 255), lw - 1, cv2.LINE_AA)
        elif plan['motif'] == 'eye':
            cv2.ellipse(a, (cx, cy), (int(r * 1.25), int(r * .55 * (.5 + .5 * abs(np.cos(T * .9))) + 8)), 0, 0, 360, (255, 255, 255), lw, cv2.LINE_AA)
            cv2.circle(a, (cx, cy), int(r * .3 * (1 + .4 * dr)), (255, 255, 255), lw, cv2.LINE_AA); cv2.circle(a, (cx, cy), int(r * .1), (0, 0, 0), -1, cv2.LINE_AA)
        else:                                                                                # a cube turning in space
            c = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float32); ca, sa, cb, sb = np.cos(th), np.sin(th), np.cos(th * .7), np.sin(th * .7)
            c = c @ np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]], np.float32) @ np.array([[1, 0, 0], [0, cb, -sb], [0, sb, cb]], np.float32)
            pr = [(int(cx + r * .7 * x / (2.6 + z) * 2.6), int(cy + r * .7 * y / (2.6 + z) * 2.6)) for x, y, z in c]
            for u in range(8):
                for v in range(u + 1, 8):
                    if bin(u ^ v).count('1') == 1: cv2.line(a, pr[u], pr[v], (255, 255, 255), lw, cv2.LINE_AA)
    if plan['ring']:                                                                         # the vocal, drawn round a circle
        n = 360; s0 = int(i * VSR / FPS); seg = VRAW[s0:s0 + n * 3:3]
        if len(seg) == n:
            rr = 230 + 60 * b + seg * 150; ang = np.linspace(0, 6.28318, n, endpoint=False) + T * .4
            pts = np.stack([cx + rr * np.cos(ang), cy + rr * np.sin(ang)], 1).astype(np.int32)
            cv2.polylines(a, [pts], True, (0, 0, 0), 9, cv2.LINE_AA); cv2.polylines(a, [pts], True, (255, 255, 255), 4, cv2.LINE_AA)
    ln = now_line(Ta) if plan['lyrics'] else None
    if ln and plan['lyrics'] == 'word':                                                      # one huge word at a time
        e, ws = ln; k = max([j for j, (wd, st) in enumerate(ws) if st <= Ta + .03] or [0]); wd, st = ws[k]
        age = Ta - st; m = word_img(wd.strip('.,').upper(), 230); pop = 1 + .25 * max(0, 1 - age * 7)
        if pop > 1.01: m = cv2.resize(m, None, fx=pop, fy=pop, interpolation=cv2.INTER_LINEAR)
        y = H * plan['word_y'] + 18 * np.sin(T * 3); x = cx + 14 * np.sin(T * 2.1); d = 6 + 14 * dr
        stamp(a, m, x + 8, y + 10, (0, 0, 0), .75); stamp(a, m, x - d, y, (255, 40, 90), .9); stamp(a, m, x + d, y, (40, 230, 255), .9); stamp(a, m, x, y, (255, 255, 255))
    elif ln:                                                                                 # the line, filling in as it is sung
        e, ws = ln; f = _font(74); words = [wd for wd, st in ws]; rows, cur = [], []
        for j, wd in enumerate(words):
            if cur and f.getlength(' '.join(words[q] for q in cur + [j])) > W - 160: rows.append(cur); cur = []
            cur.append(j)
        rows.append(cur); im = Image.fromarray(a); d = ImageDraw.Draw(im); y = int(H * .70)
        for row in rows:
            x = (W - f.getlength(' '.join(words[q] for q in row))) / 2
            for q in row:
                st = ws[q][1]; nxt = ws[q + 1][1] if q + 1 < len(ws) else e
                if st <= Ta + .03:
                    d.text((x, y), words[q], font=f, fill=(255, 230, 60) if Ta < nxt else (255, 255, 255), stroke_width=7, stroke_fill=(0, 0, 0))
                x += f.getlength(words[q] + ' ')
            y += 96
        a[:] = np.asarray(im)
    return a

def finish(img, i):
    a = cv2.resize((np.clip(img, 0, 1) * 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST if plan['field'] == 'bryce' else cv2.INTER_CUBIC)
    if plan['grain']:
        g = np.random.default_rng(seed * 100003 + i).integers(-9, 10, (H // 2, W // 2, 1), dtype=np.int16)
        a = np.clip(a.astype(np.int16) + cv2.resize(g.astype(np.float32), (W, H), interpolation=cv2.INTER_NEAREST)[..., None].astype(np.int16), 0, 255).astype(np.uint8)
    a = overlays(np.ascontiguousarray(a), i)
    fade = min(1.0, i / 8, (N - 1 - i) / 12)
    return a if fade >= 1 else (a * max(fade, 0)).astype(np.uint8)

recipe = dict(song=SONG['slug'], style='psy', seed=seed, window=[T0, T1], plan=plan)
if '--frames' in sys.argv:
    want = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; prev = None; got = []
    for i in range(max(want) + 1):
        prev = frame(i, prev)
        if i in want: got.append(finish(prev, i))
    cv2.imwrite(out, cv2.cvtColor(np.hstack(got), cv2.COLOR_RGB2BGR)); print(json.dumps(plan)); sys.exit(0)

wav = out[:-4] + '.wav'; tmp = out[:-4] + '.part.mp4'
subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', str(T0), '-t', str(T1 - T0), '-i', MASTER,
                '-af', f'afade=t=in:d=0.05,afade=t=out:st={T1 - T0 - .4}:d=0.4', wav], check=True)
p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', wav,
                      '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '27'),
                      '-maxrate', os.environ.get('CQ_MAXRATE', '2500k'), '-bufsize', '5M', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
                      '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
prev = None
for i in range(N):
    prev = frame(i, prev); p.stdin.write(finish(prev, i).tobytes())
p.stdin.close()
if p.wait() != 0: sys.exit('ffmpeg failed')
os.replace(tmp, out); os.remove(wav); json.dump(recipe, open(out[:-4] + '.json', 'w'), indent=1); print('wrote', out)
