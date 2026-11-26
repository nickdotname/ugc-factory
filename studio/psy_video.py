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
PUNCH = np.zeros(N); _v = 0.0                             # each real drum hit punches the whole picture in, then lets go
for _i in range(N): _v = max(float(onset[_i]) if onset[_i] > .35 else 0.0, _v * .78); PUNCH[_i] = _v

# ---- the plan this seed makes -----------------------------------------------------------
PALS = {'acid': [(.5, .5, .5), (.5, .5, .5), (1, 1, 1), (0, .33, .67)], 'sunset': [(.5, .5, .5), (.5, .5, .5), (1, 1, .5), (.8, .9, .3)],
        'ocean': [(.5, .5, .5), (.5, .5, .5), (1, .7, .4), (0, .15, .2)], 'neon': [(.5, .5, .5), (.5, .5, .5), (2, 1, 0), (.5, .2, .25)],
        'candy': [(.8, .5, .4), (.2, .4, .2), (2, 1, 1), (0, .25, .25)], 'lava': [(.5, .5, .5), (.5, .5, .5), (1, 1, 1), (0, .1, .2)],
        'gold': [(.55, .42, .2), (.45, .36, .22), (1, 1, 1), (0, .06, .16)], 'ice': [(.55, .65, .78), (.35, .32, .28), (1, 1, 1), (.52, .58, .66)],
        'vapor': [(.66, .5, .74), (.34, .36, .26), (1, 1, 1), (.85, .15, .45)], 'toxic': [(.4, .6, .3), (.5, .5, .4), (1, 1, .5), (.6, .2, .8)],
        'mono': [(.5, .5, .5), (.5, .5, .5), (1, 1, 1), (0, 0, 0)]}
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import knobs as K
# Repeats set the odds. 2026-11-24 review: kaleido, tunnel and marble are the fields people watched most and the
# richest on a phone; bryce is the operator's ask. rings (flat target rings) and cells (a blurry blob soup) read as
# screensavers and were dropped from the menu; spiral (median 21 views, the lowest) is kept at one share.
FIELDS = ['kaleido', 'kaleido', 'tunnel', 'tunnel', 'marble', 'marble', 'bryce', 'bryce', 'bryce', 'oil', 'julia', 'spiral', 'moire', 'warp', 'voronoi']
if os.environ.get('CQ_FIELD'): K.FORCED.setdefault('field', os.environ['CQ_FIELD'])      # the old way of asking for one
plan = dict(field=K.pick('field', FIELDS, rng), sym=K.pick('sym', [3, 4, 5, 6, 8, 12], rng),
            pal=K.pick('pal', sorted(p for p in PALS if p != 'mono'), rng), feedback=K.flag('feedback', .35, rng), spin=rng.choice([-1, 1]) * rng.uniform(.03, .12),
            warp=rng.uniform(.6, 1.6), mirror=K.flag('mirror', .35, rng), grain=K.flag('grain', .5, rng), strobe=K.flag('strobe', .12, rng),
            lyrics=(lambda pick: None if os.environ.get('CQ_LYRICS') == 'none' else pick)(K.pick('lyrics', ['word', 'line', None, None, None], rng)), ring=K.flag('ring', .2, rng),
            motif=K.pick('motif', [None, None, None, None, 'poly', 'star', 'eye'], rng), contour=K.flag('contour', .55, rng), poster=K.flag('poster', .3, rng),
            font=K.pick('font', ['Poppins-Bold.ttf', 'Poppins-Black.ttf', 'DejaVuSerif-Bold.ttf'], rng), word_y=K.pick('word_y', [.5, .5, .72], rng),
            scale=rng.uniform(2.2, 4.5), second=K.pick('second', [None, 'kaleido', 'rings', 'marble', 'spiral', 'warp'], rng), flip_at=rng.uniform(.4, .65),
            speed=K.pick('speed', [.6, 1.0, 1.0, 1.6], rng))
if plan['field'] == 'bryce': plan.update(motif=None, ring=False, strobe=False, word_y=.5)      # the landscape is busy enough: words only
if plan['field'] == 'bryce': plan['trip'] = K.flag('trip', .65, rng)      # the Bryce world in acid colours that turn on the drums (else as rendered in 1996)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import hook as _hook
plan['hook'] = _hook.pick('psy', seed)                       # the line shown for the first two seconds ('' = none)
if os.environ.get('CQ_CARDS'): plan.update(motif=None, ring=False, strobe=False)      # fact reels: nothing drawn through the text cards
# The fields are drawn as real shaders at full size when the machine can (studio/gl.py); numpy at 432x768 is the fallback.
GLSH = None
if plan['field'] != 'bryce' and os.environ.get('CQ_GL', '1') != '0':
    import gl as _gl
    if _gl.available():
        _r2 = random.Random(seed * 7 + 77)                       # its own dice, so every older seed keeps the rest of its plan
        plan['relief'] = K.flag('relief', .45, _r2); plan['gl'] = True
        GLSH = _gl.Shader(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shaders', 'psy.glsl')).read(), (W, H), ss=float(os.environ.get('CQ_SS', '1.5')))
ys, xs = np.mgrid[0:h, 0:w].astype(np.float32); X = (xs - w / 2) / (w / 2); Y = (ys - h / 2) / (w / 2)
R = np.sqrt(X * X + Y * Y) + 1e-6; A = np.arctan2(Y, X)

def palette(t, name):
    a, b, c, d = [np.array(v, np.float32) for v in PALS[name]]
    return a + b * np.cos(6.28318 * (c * t[..., None] + d))

BLOBS = np.random.default_rng(seed).uniform(-1, 1, (7, 4)).astype(np.float32)      # oil: where each blob drifts
SITES = np.random.default_rng(seed + 1).uniform(-1, 1, (14, 4)).astype(np.float32)  # voronoi: the cells' centres

def field(kind, T, i):
    T = T * plan['speed']
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
    if kind == 'oil':                                                                         # a 1960s liquid light show: blobs of dye that merge and part
        pot = np.zeros_like(X)
        for k, (ax, ay, fx_, fy_) in enumerate(BLOBS):
            cx = .75 * np.sin(T * (.21 + .1 * fx_) + k * 1.7 + ax * 3); cy = 1.4 * np.sin(T * (.17 + .08 * fy_) + k * 2.3 + ay * 3)
            rr = (.18 + .05 * (k % 3)) * (1 + .5 * b + .3 * vx)
            pot += rr * rr / ((X - cx) ** 2 + (Y - cy) ** 2 + .02)
        return np.sin(np.log(pot + 1e-3) * 2.2 - T * .6) * .7 + np.tanh(pot - 1.2) * .5
    if kind == 'julia':                                                                       # a Julia set that the bass and vocal steer
        z = (X + 1j * Y).astype(np.complex64) * (1.25 / (1 + .25 * b)) * np.exp(1j * T * plan['spin'] * 2)
        c = np.complex64(.7885 * np.exp(1j * (T * .11 + .35 * vx + 2.0)))
        n_ = np.zeros(X.shape, np.float32); alive = np.ones(X.shape, bool)
        for _ in range(22):
            z = np.where(alive, z * z + c, z); a2 = np.abs(z) < 4; n_ += a2; alive &= a2
        return np.sin(n_ * .45 - T * 1.5) * .8 + (n_ / 22) * .4
    if kind == 'spiral':                                                                      # a hypnotic log spiral, wound tighter by the bass
        s = plan['sym']; return np.sin(s * ang + np.log(R) * sc * 2.2 - T * 3 - b * 2) * .7 + np.sin(R * sc * 2 - T) * .3
    if kind == 'moire':                                                                       # two sets of rings sliding over each other
        a1, a2 = .3 * np.sin(T * .3), .3 * np.cos(T * .23); k1 = sc * 9 * (1 + .1 * vx)
        return np.sin(np.hypot(X - a1, Y - .6 + a2) * k1 - T * 2) * np.sin(np.hypot(X + a1, Y + .6 - a2) * k1 + T * 1.7 + b * 2)
    if kind == 'warp':                                                                        # smoke: the picture folded into itself three times
        u, v = X * sc * .7, Y * sc * .7
        for k in range(3):
            u, v = u + plan['warp'] * .55 * np.sin(v * 1.7 + T * (.25 + .1 * k) + k), v + plan['warp'] * .55 * np.cos(u * 1.3 - T * (.2 + .1 * k) + vx)
        return np.sin(u * 1.3 + np.cos(v * 1.1 + T * .4)) * .6 + np.sin(v * .9 - T * .3 + b) * .4
    if kind == 'voronoi':                                                                     # cells with bright seams, pushed about by the drums
        d1 = np.full(X.shape, 9.0, np.float32); d2 = d1.copy()
        for k, (ax, ay, fx_, fy_) in enumerate(SITES):
            cx = ax * .9 + .15 * np.sin(T * (.3 + .2 * fx_) + k); cy = ay * 1.6 + .15 * np.cos(T * (.25 + .2 * fy_) + k)
            d = np.hypot(X - cx, Y - cy); d2 = np.minimum(d2, np.maximum(d1, d)); d1 = np.minimum(d1, d)
        return np.clip(1 - (d2 - d1) * (6 + 6 * dr), -1, 1) * .8 + np.sin(d1 * sc * 6 - T * 2) * .3
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
    hm = np.real(np.fft.ifft2(np.fft.fft2(r.standard_normal((n, n))) / f ** r.uniform(1.55, 1.9))); hm = (hm - hm.min()) / (hm.max() - hm.min())
    if r.random() < .6: hm = 1 - np.abs(2 * hm - 1)                      # ridged mountains
    hgt = (hm - r.uniform(.42, .55)) * r.uniform(2.8, 3.8); S = n / 16.0
    scene = os.environ.get('CQ_SCENE') or r.choice(['monument', 'monument', 'flight']); yy, xx = np.mgrid[0:n, 0:n]; wx = ((xx / S + 8) % 16) - 8; wz = yy / S
    def spike(x, z, rad, tall):
        d = np.maximum(np.abs(wx - x), np.abs(wz - z)); return np.clip(1 - d / rad, 0, 1) * tall
    orb = None
    if scene == 'monument':                                              # a staged scene: an avenue of water, obelisks either side, a great orb at the end
        z0 = 2.0; lane = (np.abs(wx) < r.uniform(1.0, 1.5)) & (wz > z0 - 2) & (wz < z0 + 11); hgt = np.where(lane, -.2, hgt)
        hgt = np.where((np.abs(wx) < 3.2) & (wz > z0 - 2) & (wz < z0 + 11), np.minimum(hgt, .9), hgt)
        gap = r.uniform(1.0, 1.4); kind = r.choice(['obelisk', 'pyramid'])
        for q in range(int(r.integers(2, 5))):
            for sgn in (-1, 1): hgt = np.maximum(hgt, spike(sgn * gap, z0 + 3.2 + q * 2.1, .2 if kind == 'obelisk' else .55, r.uniform(2.2, 3.0) if kind == 'obelisk' else 1.5))
        orb = (0.0, r.uniform(2.0, 2.6), z0 + 9.5, r.uniform(.85, 1.2))
    else:
        for _ in range(int(r.integers(2, 6))): hgt = np.maximum(hgt, spike(r.uniform(-8, 8), r.uniform(0, 16), r.uniform(.15, .3), r.uniform(1.6, 3.2)))
    hgt = hgt.astype(np.float32); gx = (np.roll(hgt, -1, 1) - np.roll(hgt, 1, 1)) * .5; gy = (np.roll(hgt, -1, 0) - np.roll(hgt, 1, 0)) * .5
    cl = np.real(np.fft.ifft2(np.fft.fft2(r.standard_normal((n, n))) / f ** 1.6)); cl = ((cl - cl.min()) / (cl.max() - cl.min())).astype(np.float32)
    v, u = np.mgrid[0:BH, 0:BW].astype(np.float32); u = (u - BW / 2) / (BH / 2); v = -(v - BH / 2) / (BH / 2)
    sun = np.array([r.uniform(-.5, .5), r.uniform(.12, .35), 1.0]) if scene == 'flight' else np.array([r.uniform(-.25, .25), r.uniform(.3, .5), 1.0]); sun /= np.linalg.norm(sun)
    sph = [(r.uniform(-.9, .9), r.uniform(.55, 1.3), r.uniform(2.6, 4.6), r.uniform(.22, .5), r.uniform(0, 6)) for _ in range(int(r.integers(1, 4)) if scene == 'flight' else int(r.integers(0, 3)))]
    return dict(hgt=hgt, gx=gx.astype(np.float32), gy=gy.astype(np.float32), cl=cl, u=u, v=v, sun=sun, sph=sph, pal={k: np.array(c, np.float32) for k, c in BPAL[r.choice(sorted(BPAL))].items()},
                speed=r.uniform(.35, .8), sway=r.uniform(.2, .7), camy=r.uniform(.75, 1.25), n=n, S=S, scene=scene, orb=orb, checker=r.random() < .5, strata=r.uniform(10, 22), trip=plan.get('trip', False))
BR = None
def bsample(m, x, z):                                                   # look the map up at world x,z (it tiles for ever)
    return cv2.remap(m, ((x * BR['S']) % BR['n']).astype(np.float32), ((z * BR['S']) % BR['n']).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
def bsky(dx, dy, dz, T, i):
    P = BR['pal']; t = np.clip(dy, 0, 1) ** .55; col = P['hor'] * (1 - t[..., None]) + P['zen'] * t[..., None]
    k = 1 / (np.abs(dy) + .16); c = cv2.remap(BR['cl'], ((dx * k * 26 + T * 3) % BR['n']).astype(np.float32), ((dz * k * 26 + T * 1.2) % BR['n']).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    c = np.clip((c - .5) * 4, 0, 1) * np.clip(dy * 6, 0, 1); col = col * (1 - .55 * c[..., None]) + (P['hor'] * .5 + .5) * .55 * c[..., None]
    s = np.clip(dx * BR['sun'][0] + dy * BR['sun'][1] + dz * BR['sun'][2], 0, 1); return col + P['sun'] * (s ** 500 * 1.2 + s ** 40 * (.1 + .25 * DRUM[i]))[..., None]
def bsphere(ox, oy, oz, dx, dy, dz, c, rr):                             # where each ray meets a sphere: (hit?, distance, normal)
    lx, ly, lz = ox - c[0], oy - c[1], oz - c[2]; bq = dx * lx + dy * ly + dz * lz; disc = bq * bq - (lx * lx + ly * ly + lz * lz - rr * rr); ts = -bq - np.sqrt(np.maximum(disc, 0))
    return (disc > 0) & (ts > 0), ts, ((lx + dx * ts) / rr, (ly + dy * ts) / rr, (lz + dz * ts) / rr)
def borb(n3, pulse):                                                    # the great orb: lit from inside, darker underneath
    P = BR['pal']; ny = n3[1]; return (P['sun'] * (.55 + .6 * np.clip(ny + .15, 0, 1))[..., None] + P['zen'] * .5 * np.clip(-ny, 0, 1)[..., None]) * (.8 + .5 * pulse)
def bryce(i):
    global BR
    if BR is None: BR = bryce_setup()
    T = i / FPS; P = BR['pal']; b, dr, vx = BASS[i], DRUM[i], VOX[i]; u, v = BR['u'], BR['v']; mon = BR['scene'] == 'monument'
    if mon: ox, oz, yaw, pitch = .3 * np.sin(T * .21), .4 + T * .11, .05 * np.sin(T * .17), .02
    else: ox, oz, yaw, pitch = BR['sway'] * np.sin(T * .23), T * BR['speed'], .25 * np.sin(T * .17), -.16
    ahead = max(float(BR['hgt'][int((oz + q) * BR['S']) % BR['n'], int(ox * BR['S']) % BR['n']]) for q in np.arange(-0.5, 3.01, .25))      # stay above whatever is coming
    oy = (.62 if mon else max(BR['camy'], ahead + .55)) + .05 * np.sin(T * .5)
    dx, dy, dz = u * np.cos(yaw) + 1.5 * np.sin(yaw), v + pitch, 1.5 * np.cos(yaw) - u * np.sin(yaw); ln = np.sqrt(dx * dx + dy * dy + dz * dz); dx, dy, dz = dx / ln, dy / ln, dz / ln
    hit = np.zeros((BH, BW), np.float32); lo_t = np.zeros((BH, BW), np.float32); done = np.zeros((BH, BW), bool); pt = .2
    for k in range(56):                                                 # walk each ray out until it goes under the land or the water
        t = .2 * (1.088 ** k); under = (oy + dy * t < np.maximum(bsample(BR['hgt'], ox + dx * t, oz + dz * t), 0)) & ~done
        hit[under] = t; lo_t[under] = pt; done |= under; pt = t
    for _ in range(4):                                                  # then close in on the exact surface, so edges are clean
        mid = (hit + lo_t) * .5; under = oy + dy * mid < np.maximum(bsample(BR['hgt'], ox + dx * mid, oz + dz * mid), 0); hit = np.where(under, mid, hit); lo_t = np.where(under, lo_t, mid)
    px, pz = ox + dx * hit, oz + dz * hit; hh = bsample(BR['hgt'], px, pz); wet = done & (hh <= 0.02)
    gx, gy = bsample(BR['gx'], px, pz) * BR['S'], bsample(BR['gy'], px, pz) * BR['S']; nl = 1 / np.sqrt(gx * gx + 1 + gy * gy)
    lam = np.clip((-gx * BR['sun'][0] + BR['sun'][1] - gy * BR['sun'][2]) * nl, 0, 1); a = np.clip(hh / 1.4, 0, 1)[..., None]
    land = np.where(a < .45, P['lo'] + (P['mid'] - P['lo']) * (a / .45), P['mid'] + (P['hi'] - P['mid']) * ((a - .45) / .55))
    land = land * (.86 + .14 * np.sin(hh * BR['strata'] + gx * .6))[..., None] * (.28 + .95 * lam[..., None])           # strata, then sunlight
    rip = (.02 + .05 * b) * np.sin(pz * 9 + T * 2.2) + .015 * np.sin(px * 13 - T * 1.7); rdy = np.abs(dy) + .02
    water = P['wat'] * .3 + bsky(dx + rip, rdy, dz, T, i) * .75
    if BR['checker']: water = water * np.where(((np.floor(px * 1.6) + np.floor(pz * 1.6)) % 2 == 0), 1.0, .5)[..., None]   # a mirror-tile floor
    if BR['orb']:                                                       # the orb, seen in the water
        c = BR['orb']; on, ts, n3 = bsphere(px, np.zeros_like(px), pz, dx + rip, rdy, dz, c, c[3] * (1 + .15 * b)); water = np.where((on & wet)[..., None], water * .35 + borb(n3, dr) * .6, water)
    sky = bsky(dx, dy, dz, T, i); fog = (1 - np.exp(-hit * (.1 if mon else .16)))[..., None]
    img = np.where(done[..., None], np.where(wet[..., None], water, land) * (1 - fog) + (P['hor'] * .9) * fog, sky); depth = np.where(done, hit, 1e9)
    if BR['orb']:
        c = BR['orb']; on, ts, n3 = bsphere(ox, oy, oz, dx, dy, dz, c, c[3] * (1 + .15 * b)); on &= ts < depth; img = np.where(on[..., None], borb(n3, dr), img); depth = np.where(on, ts, depth)
        den = dx * dx + dz * dz + 1e-9; tb = ((c[0] - ox) * dx + (c[2] - oz) * dz) / den; dist = np.sqrt((ox + dx * tb - c[0]) ** 2 + (oz + dz * tb - c[2]) ** 2); yb = oy + dy * tb
        beam = np.exp(-(dist / (.2 + .1 * b)) ** 2) * ((yb < c[1]) & (yb > -.05) & (tb > 0) & (tb < depth)); img = img + P['sun'] * (beam * (.55 + .6 * b))[..., None]      # the beam under it
        halo = np.clip(dx * (c[0] - ox) + dy * (c[1] - oy) + dz * (c[2] - oz), 0, None) / np.sqrt((c[0] - ox) ** 2 + (c[1] - oy) ** 2 + (c[2] - oz) ** 2); img = img + P['sun'] * (halo ** 90 * .35 * (.6 + dr))[..., None]
    for sx, sy, sz, rad, ph in BR['sph']:                               # chrome spheres hanging in front of the camera
        c = (ox + sx, sy + .14 * np.sin(T * .9 + ph) * (1 + vx), oz + sz); on, ts, (nx, ny, nz) = bsphere(ox, oy, oz, dx, dy, dz, c, rad * (1 + .28 * b)); on &= ts < depth
        dn = dx * nx + dy * ny + dz * nz; rx, ry, rz = dx - 2 * dn * nx, dy - 2 * dn * ny, dz - 2 * dn * nz
        ref = np.where((ry > 0)[..., None], bsky(rx, ry, rz, T, i), (P['wat'] * .5 + P['mid'] * .5) * (.5 + .5 * np.clip(-ry, 0, 1))[..., None] + bsky(rx, -ry, rz, T, i) * .35)
        img = np.where(on[..., None], ref * (.82 + .18 * np.clip(1 + dn, 0, 1)[..., None]), img); depth = np.where(on, ts, depth)
    img = np.clip(img * (.92 + .25 * dr), 0, 1) ** .9
    if BR['trip']:                                                      # the trippy grade: colours pushed and turned round the wheel, a step on every drum hit
        g = img.mean(-1, keepdims=True); img = np.clip(g + (img - g) * 1.55, 0, 1)
        th = 6.28318 * (T * .03 + hue_kick[i] * .6); c_, s_ = np.cos(th), np.sin(th)
        yiq = img @ np.array([[.299, .596, .211], [.587, -.274, -.523], [.114, -.322, .312]], np.float32)
        yiq[..., 1], yiq[..., 2] = yiq[..., 1] * c_ - yiq[..., 2] * s_, yiq[..., 1] * s_ + yiq[..., 2] * c_
        img = np.clip(yiq @ np.array([[1, 1, 1], [.956, -.272, -1.106], [.621, -.647, 1.703]], np.float32), 0, 1)
    bay = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16 - .5        # the 1994 colour depth
    img = np.floor(img * 23 + np.tile(bay, (BH // 4, BW // 4))[..., None] + .5) / 23
    return cv2.resize(np.clip(img, 0, 1).astype(np.float32), (w, h), interpolation=cv2.INTER_NEAREST)

_FI = ['kaleido', 'tunnel', 'marble', 'rings', 'oil', 'julia', 'spiral', 'moire', 'warp', 'voronoi', 'cells']
if GLSH is not None:
    _a, _b, _c, _d = PALS[plan['pal']]
    GLSH.set(uField=_FI.index(plan['field']) if plan['field'] in _FI else 10, uSecond=_FI.index(plan['second']) if plan['second'] in _FI else -1,
             uSym=int(plan['sym']), uPoster=int(plan['poster']), uContour=int(plan['contour']), uStrobe=int(plan['strobe']), uMirror=int(plan['mirror']),
             uRelief=int(plan['relief']), uScale=plan['scale'], uSpin=plan['spin'], uWarp=plan['warp'], pa=_a, pb=_b, pc=_c, pd=_d)
    for _k in range(7): GLSH.set(**{'uBlobs[%d]' % _k: tuple(BLOBS[_k])})
    for _k in range(14): GLSH.set(**{'uSites[%d]' % _k: tuple(SITES[_k])})

def frame(i, prev):
    if plan['field'] == 'bryce': return bryce(i - i % 2)          # 15 pictures a second, like the real thing never managed
    if GLSH is not None:
        T = i / FPS; m = min(1.0, (i / N - plan['flip_at']) * 6) if plan['second'] and i / N > plan['flip_at'] else 0.0
        img = GLSH.render(uT=T * plan['speed'], uBass=BASS[i], uDrum=DRUM[i], uVox=VOX[i], uOth=OTH[i], uHue=hue_kick[i], uOnset=onset[i], uMix=m)
        if plan['feedback'] and prev is not None:
            z = 1.02 + .05 * BASS[i]; M = cv2.getRotationMatrix2D((W / 2, H / 2), plan['spin'] * 20, z)
            back = cv2.warpAffine(prev, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            k = .55 - .35 * DRUM[i]; img = img * (1 - k) + back * k
        return img
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
import sync_check                                    # lines whose sync is not proven come whole, never word by word
LINES = [(e, ws) for e, ws in sync_check.load_lines(SONG_DIR) if ws and ws[0][1] < T1 and e > T0]
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
    hit = None                         # the latest line that has started wins, so a lingering line never holds back the next one's first word
    for e, ws in LINES:
        if ws[0][1] - .05 <= Ta <= e + .25: hit = (e, ws)
    return hit
def overlays(a, i):
    T = i / FPS; Ta = T0 + T; b, dr = BASS[i], DRUM[i]; cx, cy = W // 2, H // 2
    if plan['motif']:
        r = 330 * (1 + .3 * b); th = T * plan['spin'] * 9; n = plan['sym'] if plan['sym'] <= 8 else 6; lw = 5
        def ngon(n, r, th): return np.array([[cx + r * np.cos(th + k * 6.28318 / n), cy + r * np.sin(th + k * 6.28318 / n)] for k in range(n)], np.int32)
        if plan['motif'] == 'poly':
            for q in range(4): cv2.polylines(a, [ngon(n, r * (1 - q * .2), th + q * .25)], True, (255, 255, 255), lw, cv2.LINE_AA)
        elif plan['motif'] == 'star':
            m = n * 2 if n % 2 else n; m = 8 if m == 6 else m                      # never six points: two crossed triangles are not ours to spin over fact reels
            p = ngon(m, r, th)
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
    ln = now_line(Ta) if plan['lyrics'] and T >= (2.6 if plan['hook'] else 0.8) else None      # frame 0 is the cover: never a stray lyric word on it, never two texts at once
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
        rows.append(cur); im = Image.fromarray(a); d = ImageDraw.Draw(im); y = int(H * .60)
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

CARDS = json.load(open(os.environ['CQ_CARDS'])) if os.environ.get('CQ_CARDS') else []      # fact reels: [[t0, t1, big, small], ...]
_CF = {}
def _cfont(name, size):
    k = (name, size)
    if k not in _CF:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts', name)
        _CF[k] = ImageFont.truetype(p, size) if os.path.exists(p) else _font(size)
    return _CF[k]

def _wrap(d, text, f, width):
    out, cur = [], ''
    for w in text.split():
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=f) <= width or not cur: cur = t
        else: out.append(cur); cur = w
    return out + ([cur] if cur else [])

def cards(a, t):
    """A text card over the visuals: a big yellow word or two, then a sentence, on a dark band."""
    c = next((c for c in CARDS if c[0] <= t < c[1]), None)
    if not c: return a
    H_, W_ = a.shape[:2]; im = Image.fromarray(a); lay = Image.new('RGBA', (W_, H_), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    big, small = c[2] or '', c[3] or ''
    fb = _cfont('Anton-Regular.ttf', 150); fs = _cfont('Poppins-Bold.ttf', 62 if big else 88)      # a card with no big word is the opening line: make it big
    bl = _wrap(d, big.upper(), fb, W_ * .86); sl = _wrap(d, small, fs, W_ * .84)
    lh = 80 if big else 112
    h = len(bl) * 165 + (30 if bl and sl else 0) + len(sl) * lh; y = H_ * .5 - h / 2
    pop = 1.0 if c[0] == 0 else min(1.0, (t - c[0]) / .18); alpha = int(215 * pop)
    d.rectangle([0, y - 60, W_, y + h + 60], fill=(8, 6, 14, alpha))
    for ln in bl:
        d.text(((W_ - d.textlength(ln, font=fb)) / 2, y), ln, font=fb, fill=(255, 226, 60, int(255 * pop))); y += 165
    y += 30 if bl and sl else 0
    for ln in sl:
        d.text(((W_ - d.textlength(ln, font=fs)) / 2, y), ln, font=fs, fill=(255, 255, 255, int(255 * pop))); y += lh
    im.paste(lay, (0, 0), lay); return np.asarray(im)

def finish(img, i):
    a = (np.clip(img, 0, 1) * 255 + .5).astype(np.uint8)
    if a.shape[:2] != (H, W): a = cv2.resize(a, (W, H), interpolation=cv2.INTER_NEAREST if plan['field'] == 'bryce' else cv2.INTER_CUBIC)
    if plan['grain']:
        g = np.random.default_rng(seed * 100003 + i).integers(-9, 10, (H // 2, W // 2, 1), dtype=np.int16)
        a = np.clip(a.astype(np.int16) + cv2.resize(g.astype(np.float32), (W, H), interpolation=cv2.INTER_NEAREST)[..., None].astype(np.int16), 0, 255).astype(np.uint8)
    p_ = PUNCH[i]
    if p_ > .04:                                             # the kick: the picture jumps in and its colours split, then settle
        z = 1 + .07 * p_; cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2; x0, y0 = (W - cw) // 2, (H - ch) // 2
        a = cv2.resize(a[y0:y0 + ch, x0:x0 + cw], (W, H), interpolation=cv2.INTER_LINEAR); d = int(16 * p_)
        if d: a = a.copy(); a[:, d:, 0] = a[:, :-d, 0]; a[:, :-d, 2] = a[:, d:, 2]
    a = _hook.draw(overlays(np.ascontiguousarray(a), i), plan['hook'], i / FPS, y=.165)
    if CARDS: a = cards(np.ascontiguousarray(a), i / FPS)
    # No fade-in: Instagram uses the first frame as the cover, and a black one is a black square on the profile.
    # The end only dips (never to black) so the loop back to frame one is a breath, not a blink.
    return a                       # no dip at the end either: the sound crossfades into its own start, so the video loops

recipe = dict(song=SONG['slug'], style='psy', seed=seed, window=[T0, T1], plan=plan, **K.record())
if '--frames' in sys.argv:
    want = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; prev = None; got = []
    for i in range(max(want) + 1):
        prev = frame(i, prev)
        if i in want: got.append(finish(prev, i))
    cv2.imwrite(out, cv2.cvtColor(np.hstack(got), cv2.COLOR_RGB2BGR)); print(json.dumps(plan)); sys.exit(0)

wav = out[:-4] + '.wav'; tmp = out[:-4] + '.part.mp4'
import soundfile as _sf
_sr = _sf.info(MASTER).samplerate; _n = int(0.12 * _sr); _a = int(T0 * _sr)
_x, _ = _sf.read(MASTER, start=_a, stop=int(T1 * _sr), always_2d=True, dtype='float32')
_pre, _ = _sf.read(MASTER, start=max(0, _a - _n), stop=_a, always_2d=True, dtype='float32')
if len(_pre) == _n:                                    # the end fades into the sound just before the start, so it runs straight on into it
    _r = np.linspace(0, 1, _n)[:, None]; _x[-_n:] = _x[-_n:] * (1 - _r) + _pre * _r
_sf.write(wav, _x * min(1.0, 0.98 / (np.abs(_x).max() + 1e-9)), _sr)
p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', wav,
                      '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                      '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
                      '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
prev = None
for i in range(N):
    prev = frame(i, prev); p.stdin.write(finish(prev, i).tobytes())
p.stdin.close()
if p.wait() != 0: sys.exit('ffmpeg failed')
os.replace(tmp, out); os.remove(wav); json.dump(recipe, open(out[:-4] + '.json', 'w'), indent=1); print('wrote', out)
