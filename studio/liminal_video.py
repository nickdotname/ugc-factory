#!/usr/bin/env python3
"""Nostalgic places for a stretch of a song, as if filmed on a family camcorder: the indoor play place with its ball
pit, the roller rink's cosmic carpet, the school computer lab, a school hallway, the mall, the hotel pool, the back rooms.

    python studio/liminal_video.py studio/songs/<slug> <seed> out.mp4          (window from CQ_WINDOW="start,end")
    python studio/liminal_video.py studio/songs/<slug> <seed> out.png --frames 0,200     (CQ_FULL=1: full-size frames)

No footage: every frame is ray-cast from nothing, so nothing in it is anyone else's (no logos, no characters).
The seed picks the place, its light, the tape's date stamp and how the camera drifts; a line naming one specific
memory of that place is on screen from the first frame. The corridor repeats, and the camera moves exactly a whole
number of repeats in the clip (the step bob and tilt are whole cycles too), so the video loops with no seam. The lights
hum with the music and flicker on the hardest drum hits, and a tracking band tears through on them.
A recipe .json is written beside the video.
"""
import sys, os, json, random, subprocess
import numpy as np, soundfile as sf, cv2
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cards as _cards

SONG_DIR = os.path.abspath(sys.argv[1]); seed = int(sys.argv[2]); out = sys.argv[3]
SONG = json.load(open(os.path.join(SONG_DIR, 'song.json')))
def _find(stem, exts): return next((os.path.join(SONG_DIR, stem + e) for e in exts if os.path.exists(os.path.join(SONG_DIR, stem + e))), os.path.join(SONG_DIR, stem + exts[0]))
MASTER = _find('master', ('.wav', '.flac', '.ogg')); stem_path = lambda name: _find(os.path.join('stems', name), ('.flac', '.ogg'))
T0, T1 = [float(x) for x in os.environ['CQ_WINDOW'].split(',')]
FPS, W, H = 30, 1080, 1920
w, h = 432, 768                      # tape resolution: drawn small and blown up, which is the look
N = max(1, int(round((T1 - T0) * FPS))); rng = random.Random(seed)
FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts')

# ---- what the music is doing ----------------------------------------------------------------
def env(name, smooth):
    p = stem_path(name)
    if not os.path.exists(p): return np.zeros(N)
    a, sr = sf.read(p, dtype='float32', always_2d=True); a = a.mean(1)[int(T0 * sr):int(T1 * sr)]; hop = sr / FPS
    e = np.array([np.sqrt(np.mean(a[int(i * hop):int((i + 1) * hop)] ** 2) + 1e-9) for i in range(N)])
    e = np.clip(e / (np.percentile(e, 98) + 1e-9), 0, 1.5); o = np.zeros(N); v = 0.0
    for i in range(N): v = e[i] if e[i] > v else v * smooth + e[i] * (1 - smooth); o[i] = v
    return o
DRUM, BASS, VOX = env('Drums', .6), env('Bass', .9), env('Vocals', .85)
hit = np.clip(np.diff(DRUM, prepend=0), 0, None); hit = hit / (hit.max() + 1e-9)

# ---- the place -------------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import knobs as K
# Childhood places first (2026-11-24 review): the play place, the roller rink and the school computer lab are the
# rooms people say "I was HERE" about, and a specific memory is what gets sent to a friend; the empty yellow back
# rooms have been everywhere since the 2026 film. office and parking were dropped: nothing in them is a memory.
PLACES = ['playplace', 'playplace', 'rink', 'rink', 'lab', 'lab', 'school', 'school', 'mall', 'pool', 'backrooms', 'hotel']
if os.environ.get('CQ_PLACE'): K.FORCED.setdefault('place', os.environ['CQ_PLACE'])
place = K.pick('place', PLACES, rng)
P = dict(backrooms=dict(width=3.2, height=2.6, period=4.0, fog=(.42, .38, .22), fogd=.11, gap=(1.2, 2.6), eye=1.55, gloss=0, pace=.45),
         pool=dict(width=4.4, height=3.2, period=3.0, fog=(.62, .78, .80), fogd=.08, gap=(0.9, 2.4), eye=1.55, gloss=0, pace=.5),
         mall=dict(width=6.0, height=4.2, period=6.0, fog=(.55, .50, .52), fogd=.06, gap=(1.0, 4.5), eye=1.7, gloss=.35, pace=.3),
         hotel=dict(width=2.2, height=2.5, period=3.2, fog=(.10, .07, .05), fogd=.16, gap=(1.6, 2.4), eye=1.55, gloss=0, pace=.55),
         school=dict(width=3.0, height=2.9, period=4.0, fog=(.55, .56, .50), fogd=.09, gap=(2.6, 2.3), eye=1.35, gloss=.30, pace=.5),
         playplace=dict(width=3.6, height=2.8, period=3.0, fog=(.80, .62, .46), fogd=.08, gap=(0, 0), eye=1.15, gloss=0, pace=.4),
         rink=dict(width=4.4, height=3.2, period=4.0, fog=(.10, .04, .16), fogd=.07, gap=(0, 0), eye=1.45, gloss=0, pace=.45),
         lab=dict(width=2.5, height=2.6, period=3.6, fog=(.02, .04, .06), fogd=.07, gap=(0, 0), eye=1.05, gloss=.25, pace=.4))[place]
WID, HEI, PER, EYE = P['width'], P['height'], P['period'], P['eye']
pace = K.pick('pace', ['slow', 'walk', 'walk'], rng)
laps = max(1, round((T1 - T0) * P['pace'] * (.55 if pace == 'slow' else 1) / PER * 2))   # whole repeats per clip
SPEED = laps * PER / (N / FPS)
STEPS = max(1, round(N / FPS * (1.0 if pace == 'slow' else 1.6)))                        # footfalls per clip, whole, so the bob loops
year = rng.randint(1994, 2004); month = rng.randint(1, 12); day = rng.randint(1, 28)
# the night places at small hours, the rest in the daytime (13-16 is the afternoon: it was 1-4, which the stamp printed as AM)
hour, minute = rng.choice([2, 3, 3, 4, 23, 1]) if place in ('backrooms', 'hotel', 'mall') else rng.choice([10, 11, 13, 14, 15, 16]), rng.randint(0, 59)
side_bias = rng.uniform(-.25, .25) * (WID / 3.2)   # camera a little off centre
look = rng.uniform(-.07, .07)                       # and turned a little, so the vanishing point is never dead centre
warm = rng.uniform(-.04, .04)
tint = K.pick('tint', ['neutral', 'neutral', 'warm', 'cold', 'green'], rng)
warm += {'neutral': 0, 'warm': .07, 'cold': -.07, 'green': 0}[tint]
tape_wear = K.pick('tape', ['clean', 'worn', 'worn', 'chewed'], rng)
label = K.pick('label', ['PLAY ▶', 'PLAY ▶', 'REC ●', 'none'], rng)
stamp = K.pick('stamp', ['date', 'date', 'none'], rng)
phase = rng.uniform(0, 6.28)
LOCKER = rng.choice([[.18, .32, .62], [.62, .14, .14], [.16, .45, .30]])

# camera rays, made once (drawn at tape resolution and blown up: that softness is the look)
yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
fov = 1.15
dx = (xx - w / 2) / (w / 2) * np.tan(fov / 2) * (w / h); dy = -(yy - h / 2) / (h / 2) * np.tan(fov / 2); dz = np.ones_like(dx)
c, s = np.cos(look), np.sin(look); dx, dz = dx * c + dz * s, -dx * s + dz * c
n = np.sqrt(dx * dx + dy * dy + dz * dz); dx, dy, dz = dx / n, dy / n, dz / n

def noise2(u, v, k):
    """cheap hash in [0, 1) of integer cells"""
    return (np.sin(u * 12.9898 * k + v * 78.233 + k * 37.719) * 43758.5453) % 1.0

def stain(u, v):
    """smooth blotches in about [-1, 1] that repeat every PER along the corridor (so the loop has no seam)"""
    q = 2 * np.pi / PER
    return (np.sin(2 * q * u + 1.7 * v + phase) * np.sin(3 * q * u - 2.3 * v + 1.1) + .6 * np.sin(5 * q * u + 4.1 * v + 2 * phase)) / 1.6

def surfaces(cx, cz, eye):
    """distance and hit point on each of floor, ceiling, left, right wall. -> t, kind, px, py, pz"""
    big = np.float32(1e9)
    tf = np.where(dy < -1e-4, (0 - eye) / np.minimum(dy, -1e-4), big)
    tc = np.where(dy > 1e-4, (HEI - eye) / np.maximum(dy, 1e-4), big)
    tl = np.where(dx < -1e-4, (-WID / 2 - cx) / np.minimum(dx, -1e-4), big)
    tr = np.where(dx > 1e-4, (WID / 2 - cx) / np.maximum(dx, 1e-4), big)
    T = np.stack([tf, tc, tl, tr]); kind = T.argmin(0); t = T.min(0)
    px, py, pz = cx + dx * t, eye + dy * t, cz + dz * t
    return t, kind, px, py, pz

def light_at(pz, flick):
    """lights every PER along the ceiling centre; how lit a point at depth z is"""
    zr = (pz % PER) / PER
    d = np.minimum(zr, 1 - zr)
    k = np.floor(pz / PER + .5).astype(np.int64)
    f = flick[(k % len(flick))]
    return (0.55 + 0.45 * np.exp(-(d * PER) ** 2 / 2.2)) * f

def where(mask, a, b): return np.where(mask[..., None], a, b)

def ceiling_tiles(px, pz, tile=(.86, .84, .74), grid=(.62, .60, .50), panel=(1.6, 1.55, 1.3), pw=.45):
    fz = round(PER * 1.6) / PER
    t = ((np.abs((px * 1.6) % 1 - .5) > .46) | (np.abs((pz * fz) % 1 - .5) > .46))
    c = where(t, grid, tile) * (.94 + .06 * noise2(np.floor(px * 1.6), np.floor((pz % PER) * 1.6), 9))[..., None]
    pnl = (np.abs(px) < pw) & (np.abs(((pz % PER) / PER) - .5) > .42)
    return where(pnl, panel, c)

NEON = np.array([[1.5, .25, .85], [.2, 1.25, 1.5], [1.5, 1.3, .2], [.35, 1.5, .4], [1.5, .6, .15]], np.float32)

def cosmic(u, v, cell=1.0, wrap=4):
    """the roller-rink / bowling-alley carpet: neon rings, squiggles, zigzags and confetti on near-black. Drawn here."""
    iu, iv = np.floor(u / cell), np.floor(v / cell) % wrap
    fu, fv = (u / cell) % 1, (v / cell) % 1
    hs = noise2(iu, iv, 3); kind = np.floor(hs * 4)
    col = NEON[(np.floor(noise2(iu, iv, 5) * 5)).astype(int) % 5]
    rr = np.sqrt((fu - .5) ** 2 + (fv - .5) ** 2)
    ring = np.abs(rr - .26) < .045
    squig = np.abs(fv - .5 - .14 * np.sin(fu * 4 * np.pi + hs * 6)) < .05
    zig = np.abs(fv - .5 - .16 * (4 * np.abs((fu * 2.5) % 1 - .5) - 1)) < .05
    blob = rr < .12
    shape = np.where(kind == 0, ring, np.where(kind == 1, squig, np.where(kind == 2, zig, blob)))
    fu2, fv2 = (u / cell * 4) % 1, (v / cell * 4) % 1
    conf = (noise2(np.floor(u / cell * 4), np.floor(v / cell * 4) % (wrap * 4), 7) < .22) & ((fu2 - .5) ** 2 + (fv2 - .5) ** 2 < .05)
    ccol = NEON[(np.floor(noise2(np.floor(u / cell * 4), np.floor(v / cell * 4) % (wrap * 4), 8) * 5)).astype(int) % 5]
    base = np.array([.05, .035, .11], np.float32) * (.8 + .4 * noise2(np.floor(u * 40), np.floor((v % (cell * wrap)) * 40), 2))[..., None]
    return where(shape, col, where(conf, ccol * .9, base)), shape | conf

def texture(kind, px, py, pz, T, i, flick):
    out = np.zeros(kind.shape + (3,), np.float32)
    fl, ce, wl = kind == 0, kind == 1, kind >= 2
    u_w = pz; v_w = py
    zmod = pz % PER
    door = wl & (zmod > P['gap'][0]) & (zmod < P['gap'][0] + 1.0) & (py < P['gap'][1]) if place in ('backrooms', 'hotel', 'mall', 'school') else np.zeros_like(wl)
    if place == 'backrooms':                                              # mono-yellow wallpaper, damp carpet, the hum
        motif = (np.abs((u_w * 5) % 1 - .5) + np.abs((v_w * 3.5) % 1 - .5)) < .2
        stripe = (np.abs((u_w * 10) % 1 - .5) > .46)
        wall = np.array([.80, .71, .40]) * (1 - .06 * motif - .04 * stripe)[..., None]
        damp = np.clip(stain(u_w, v_w * .7) * 1.4 - .3, 0, 1) * np.clip(1.4 - v_w, 0, 1)   # water creeping up from the floor
        wall = wall * (1 - .35 * damp)[..., None] + np.array([.10, .07, .0]) * damp[..., None]
        out[wl] = wall[wl]
        out[wl & (py < .1)] = [.42, .36, .20]                                # skirting
        carpet = np.array([.56, .49, .29]) * (0.82 + .18 * noise2(np.floor(px * 30), np.floor((pz % PER) * 30), 1))[..., None]
        wet = np.clip(stain(pz, px * 1.3) * 1.2 - .2, 0, 1)
        out[fl] = (carpet * (1 - .38 * wet)[..., None])[fl]
        out[ce] = ceiling_tiles(px, pz)[ce]
        out[door] = [.05, .04, .02]
    elif place == 'pool':
        gl = ((np.abs((u_w * 6) % 1 - .5) > .45) | (np.abs((v_w * 6) % 1 - .5) > .45))
        out[wl] = where(gl, [.62, .70, .72], [.92, .96, .97])[wl]
        out[wl & (py < .5)] = where(gl, [.10, .30, .55], [.16, .44, .74])[wl & (py < .5)]      # a blue tile band at the waterline
        water = (px > -WID / 2 + .9) & (px < WID / 2 - .9)
        q = 2 * np.pi * i / N; caust = (np.sin(px * 7 + 6 * q) * np.sin(pz * 2 * np.pi * 2 / PER - 5 * q) + np.sin(px * 9 + pz * 2 * np.pi * 4 / PER + 11 * q)) * .5
        lane = water & (np.abs((px % 1.2) - .6) < .05)
        flr = where(water, np.stack([.16 + .07 * caust, .50 + .12 * caust, .64 + .1 * caust], -1),
                    where(((np.abs((px * 5) % 1 - .5) > .45) | (np.abs((pz * 5) % 1 - .5) > .45)), [.6, .66, .66], [.9, .93, .93]))
        flr = where(lane, [.10, .18, .40], flr)
        out[fl] = flr[fl]
        sky = (np.abs(px) < 1.1) & ((pz % PER) / PER > .25) & ((pz % PER) / PER < .75)
        out[ce] = where(sky, [1.5, 1.55, 1.55], [.80, .84, .84])[ce]
    elif place == 'mall':
        out[wl] = where(((py > 3.2) | (np.abs(zmod - 3) > 2.6)), [.86, .74, .74], [.90, .84, .80])[wl]
        shop = wl & (np.abs(zmod - 3.2) < 2.0) & (py < 3.0)
        grate = (np.sin(py * 60) > .3)
        out[shop] = where(grate, [.30, .30, .32], [.12, .12, .14])[shop]
        sign = wl & (np.abs(zmod - 3.2) < 1.6) & (np.abs(py - 3.4) < .22)      # a dark, blank sign box over each shop
        out[sign] = [.16, .14, .18]
        chk = ((np.floor(px * 1.5) + np.floor(pz * 1.5)) % 2 == 0)
        out[fl] = where(chk, [.86, .84, .82], [.42, .62, .60])[fl]
        out[ce] = where(((pz % PER) / PER > .3) & (np.abs(px) < 2), [1.45, 1.42, 1.35], [.78, .76, .74])[ce]
        door = np.zeros_like(wl)
    elif place == 'school':                                                # a school corridor lined with lockers
        lk = (py > .15) & (py < 1.95) & ~((zmod > P['gap'][0]) & (zmod < P['gap'][0] + 1.0))
        colr = np.array(LOCKER)
        seam = (np.abs((pz * 2.5) % 1 - .5) > .46) | (np.abs(py - 1.0) < .02)
        vent = (np.abs(py - 1.75) < .08) & (np.sin(py * 140) > .2)
        board = (py > 2.05) & (py < 2.6) & (np.abs(zmod - 1.2) < .9)        # a cork board over the lockers with paper on it
        paper = board & (noise2(np.floor(zmod * 5), np.floor(py * 6), 4) > .45)
        wall = where(lk, colr * (1 - .55 * (seam | vent))[..., None], np.array([.86, .84, .76]))
        wall = where(board, [.62, .44, .26], wall); wall = where(paper, [.95, .93, .86], wall)
        out[wl] = wall[wl]
        out[wl & (py < .15)] = [.25, .22, .2]
        chk = ((np.floor(px * 2.0) + np.floor(pz * 2.0)) % 2 == 0)
        out[fl] = where(chk, [.84, .82, .74], [.30, .40, .35])[fl]
        out[ce] = ceiling_tiles(px, pz, (.88, .87, .82), (.6, .6, .56), (1.6, 1.6, 1.5))[ce]
        out[door] = [.45, .30, .18]
        door = np.zeros_like(wl)
    elif place == 'playplace':                                             # the indoor play place: ball pit, padding, nets, a tube slide
        cs = PER / 20; iz = np.floor(pz / cs); off = .5 * (iz % 2)
        ix = np.floor(px / cs + off); fx = (px / cs + off) % 1 - .5; fz = (pz / cs) % 1 - .5
        hsh = noise2(ix, iz % 20, 6); fx = fx - (hsh - .5) * .12; fz = fz - (noise2(ix, iz % 20, 11) - .5) * .12
        r2 = (fx * fx + fz * fz) / (.47 ** 2)
        balls = np.array([[.90, .10, .08], [.98, .80, .08], [.08, .32, .90], [.12, .66, .22], [.98, .45, .05], [.55, .15, .75]], np.float32)
        bc = balls[(np.floor(hsh * 6)).astype(int) % 6]
        shade = np.sqrt(np.clip(1 - r2, 0, 1)); spec = np.exp(-((fx + .14) ** 2 + (fz - .14) ** 2) / .006)
        pit = np.where((r2 < 1)[..., None], bc * (.35 + .75 * shade)[..., None] + .7 * spec[..., None], np.array([.10, .06, .08]))
        out[fl] = pit[fl]
        pw = .75; k = np.floor(pz / pw) % 4; uu = (pz % pw) / pw
        padc = np.array([[.86, .12, .10], [.10, .30, .82], [.96, .78, .10], [.12, .62, .25]], np.float32)[k.astype(int)]
        vv = np.clip(py / .95, 0, 1)
        edge = np.clip(1 - .45 * (np.exp(-uu / .07) + np.exp(-(1 - uu) / .07) + np.exp(-vv / .1) + np.exp(-(1 - vv) / .1)), .3, 1)
        pad = padc * edge[..., None] * (1 + .18 * np.exp(-((uu - .35) ** 2 + (vv - .7) ** 2) / .03))[..., None]
        net = (np.abs(((pz + py) * 4) % 1 - .5) > .40) | (np.abs(((pz - py) * 4) % 1 - .5) > .40)
        pole = (zmod < .16) | (zmod > PER - .16)
        backc = np.array([.95, .86, .55]) * (.85 + .15 * np.sin(py * 2))[..., None]
        upper = where(net, [.05, .05, .06], backc)
        upper = where(pole, np.array([.98, .80, .10]) * (.6 + .4 * np.cos((zmod - np.where(zmod > PER / 2, PER, 0)) / .16 * 1.5))[..., None], upper)
        rail = np.abs(py - 1.0) < .06
        wall = where(py < .95, pad, where(rail, [.98, .80, .10], upper))
        out[wl] = wall[wl]
        tube = np.abs(px) < .6
        tshade = np.cos(np.clip(px / .6, -1, 1) * 1.4)
        ring = np.abs((pz * 2) % 1 - .5) > .44
        tcol = np.array([.92, .14, .12]) * (.35 + .75 * tshade)[..., None] * (1 - .35 * ring)[..., None]
        lamp = (np.abs(np.abs(px) - 1.25) < .28) & (np.abs(((pz % PER) / PER) - .5) > .40)
        cl = where(tube, tcol, where(lamp, [1.7, 1.65, 1.5], [.16, .20, .42]))
        out[ce] = cl[ce]
    elif place == 'rink':                                                  # roller rink at night: the cosmic carpet, neon, a mirror ball
        carpet, _ = cosmic(px, pz, 1.0, int(PER))                            # the carpet round the rink: the part everyone remembers
        out[fl] = (carpet * 1.25)[fl]
        wc, _ = cosmic(py + 10, pz, .5, int(round(PER / .5)))
        tube1 = np.exp(-((py - 1.25) / .035) ** 2); tube2 = np.exp(-((py - 1.42) / .035) ** 2)
        glow = np.exp(-((py - 1.33) / .25) ** 2) * .25
        top = np.array([.05, .04, .09], np.float32) + glow[..., None] * np.array([.8, .3, 1.0])
        wall = where(py < 1.12, wc * .85, top)
        wall = wall + tube1[..., None] * np.array([2.0, .3, 1.2]) + tube2[..., None] * np.array([.3, 1.6, 2.0])
        out[wl] = wall[wl]
        out[ce] = np.array([.07, .04, .12])
    elif place == 'lab':                                                   # the school computer lab: beige towers, CRTs, blue chairs
        tile = np.array([.62, .66, .70]) * (.92 + .08 * noise2(np.floor(px / .6), np.floor((pz % PER) / .6), 13))[..., None]
        speck = noise2(np.floor(px * 60), np.floor((pz % PER) * 60), 14) > .85
        grout = (np.abs((px / .6) % 1 - .5) > .47) | (np.abs((pz / .6) % 1 - .5) > .47)
        out[fl] = where(grout, [.45, .48, .50], where(speck, tile * .7, tile))[fl]
        cell = PER / 3; uu = (pz % cell) / cell; mi = np.floor(pz / cell) % 3
        block = np.array([.86, .84, .78]) * (1 - .12 * ((np.abs((py / .2) % 1 - .5) > .45) | (np.abs(((pz + .2 * (np.floor(py / .2) % 2)) / .4) % 1 - .5) > .47)))[..., None]
        wall = block
        wall = where(py < .74, np.array([.52, .52, .54]) * (1 - .3 * (np.abs(uu - .5) > .47))[..., None], wall)
        wall = where(np.abs(py - .74) < .025, [.82, .80, .74], wall)
        mon = (uu > .12) & (uu < .88) & (py > .80) & (py < 1.42)
        scr = (uu > .19) & (uu < .81) & (py > .88) & (py < 1.33)
        su, sv = (uu - .19) / .62, (py - .88) / .45                           # screen coords, 0..1
        side = (np.floor(px) > 0).astype(int)                               # which wall: each screen is different
        sk = noise2(np.floor(pz / cell) % 3, side, 15)
        desk_ = np.array([.05, .50, .52]) * (1 + .0 * su)[..., None]
        icons = (su < .16) & (np.abs((sv * 6) % 1 - .5) < .3) & (np.abs((su * 12) % 1 - .5) < .3) & (sv > .3)
        bar = sv < .09
        win_ = (su > .28) & (su < .9) & (sv > .25) & (sv < .85)
        winc = where(sv > .76, [.05, .10, .55], [.92, .92, .90])
        screen = where(bar, [.75, .75, .75], where(icons, [.95, .95, .95], where(win_ & (sk > .45), winc, desk_)))
        stars = (noise2(np.floor(su * 14), np.floor(sv * 14 + 28 * i / N) % 14, 16) > .9)  # a starfield screensaver on some
        screen = where(sk < .25, where(stars, [1.0, 1.0, 1.0], [.01, .01, .04]), screen)
        screen = where(sk > .92, [.02, .02, .02], screen)                   # one switched off
        bev = np.array([.80, .76, .64]) * (1 - .25 * ((uu < .14) | (py < .82)))[..., None]
        wall = where(mon, where(scr, screen * 1.35, bev), wall)
        glow = (np.abs(uu - .5) < .45) & (py > .55) & (py < .80)                 # each screen lights the desk under it
        wall = wall * (1 + 1.2 * glow * np.exp(-((py - .8) / .12) ** 2))[..., None] * where(glow, [.6, 1.2, 1.2], [1, 1, 1])
        EMIT[:] = wl & mon & scr
        chair = (uu > .30) & (uu < .70) & (py > .40) & (py < .92)
        wall = where(chair, np.array([.10, .16, .38]) * (1 - .3 * (np.abs(uu - .5) > .17))[..., None], wall)
        out[wl] = wall[wl]
        out[ce] = ceiling_tiles(px, pz, (.86, .86, .84), (.58, .58, .56), (1.6, 1.62, 1.58), .5)[ce]
    else:  # hotel
        out[wl] = where((py < .9), [.48, .36, .26], [.82, .74, .58])[wl]
        flock = wl & (py >= .9) & ((np.abs((u_w * 5) % 1 - .5) + np.abs((v_w * 3) % 1 - .5)) < .16)
        out[flock] = out[flock] * .88
        out[door] = [.30, .18, .10]
        plate = door & (np.abs(zmod - (P['gap'][0] + .5)) < .07) & (np.abs(py - 1.55) < .05)
        out[plate] = [.9, .75, .35]
        diam = (np.abs((px * 2.5) % 1 - .5) + np.abs((pz * 2.5) % 1 - .5)) < .32
        out[fl] = where(diam, [.62, .42, .12], [.42, .08, .10])[fl]
        out[ce] = [.70, .64, .54]
        sconce = wl & (np.abs(zmod - .4) < .12) & (np.abs(py - 1.9) < .1)
        out[sconce] = [2.0, 1.6, 1.0]
        door = np.zeros_like(wl)
    if place in ('backrooms', 'mall'): out[door] = [.04, .035, .03]
    return out

EMIT = np.zeros((h, w), bool)

def occlusion(kind, px, py):
    """darker into the corners where walls meet floor and ceiling: what makes a drawn room read as a real one"""
    dw = np.clip(WID / 2 - np.abs(px), 0, 50)
    a = np.where(kind == 0, 1 - .55 * np.exp(-dw / .22), np.where(kind == 1, 1 - .45 * np.exp(-dw / .25),
                 1 - .5 * np.exp(-np.clip(np.minimum(py, HEI - py), 0, 50) / .18)))
    return a.astype(np.float32)

def frame(i):
    T = i / FPS; ph = 2 * np.pi * i / N
    cz = SPEED * T
    cx = side_bias + .06 * np.sin(ph) + .02 * np.sin(ph * STEPS)             # a slow drift and the sway of each step
    eye = EYE + .022 * np.sin(ph * STEPS * 2)                                 # the bob of a camcorder carried down a hall
    flick = np.ones(16, np.float32)
    r = random.Random(seed * 1000 + i // 2)
    if hit[i] > .7 or r.random() < .03: flick[r.randrange(16)] = r.choice([.25, .5, .7])
    hum = 1 + .05 * BASS[i] + .04 * DRUM[i]
    t, kind, px, py, pz = surfaces(cx, cz, eye)
    tex = texture(kind, px, py, pz, T, i, flick)
    if place in ('playplace', 'rink'):                                        # fine floor patterns go to mush, not moire, in the distance
        avg = {'playplace': np.array([.55, .35, .25]), 'rink': np.array([.22, .12, .30])}[place]
        k = np.clip((t - 5) / 9, 0, 1)[..., None] * (kind == 0)[..., None]
        tex = tex * (1 - k) + avg * k
    lit = light_at(pz, flick)
    if place == 'lab': lit = .45 * lit                                       # after hours: the overheads off, the screens on
    if place == 'rink': lit = .75 + .45 * (lit - .55) / .45 * .4 + .25 * DRUM[i]   # dim, with the room breathing on the drums
    col = tex * lit[..., None] * hum * occlusion(kind, px, py)[..., None]
    if P['gloss']:                                                             # the lights reflected in a polished floor
        zr = (pz % PER) / PER; dp = np.minimum(zr, 1 - zr) * PER
        k = np.floor(pz / PER + .5).astype(np.int64); f = flick[k % len(flick)]
        refl = P['gloss'] * np.exp(-(px / .5) ** 2) * np.exp(-(dp / .45) ** 2) * f * (kind == 0)
        col = col + refl[..., None] * np.array([1.0, .98, .9])
    if place == 'rink':                                                        # the mirror ball's spots, sliding a whole turn per clip
        a = ph * 2
        su = ((pz * 1.25 + np.cos(a) * .7) % 1); sv = ((np.where(kind >= 2, py, px) * 1.25 + np.sin(a) * .7) % 1)
        spot = ((su - .5) ** 2 + (sv - .5) ** 2 < .012) & (kind != 0) | (((pz * 1.25 + np.cos(a) * .7) % 1 - .5) ** 2 + ((px * 1.25 + np.sin(a) * .7) % 1 - .5) ** 2 < .008) & (kind == 0)
        col = col + spot[..., None] * np.array([.9, .85, 1.0]) * (.5 + .5 * DRUM[i])
    if place == 'lab': col = np.where(EMIT[..., None], tex * (.9 + .1 * hum), col)
    fog = np.exp(-P['fogd'] * t)[..., None]
    col = col * fog + np.array(P['fog'], np.float32) * (1 - fog) * (.75 + .25 * hum)
    col *= 1 + np.array([warm, .05 if tint == 'green' else 0, -warm], np.float32)
    return np.clip(col, 0, 1.2)

# ---- the line on screen ----------------------------------------------------------------------
# One specific memory, true of any video of that place, held for the whole clip so it reads on a replay.
# Statements, not asks: no "comment", no "tag", no "if you remember this you had a good childhood".
LINES = {
    'playplace': ["the ball pit at every birthday party in 1999", "losing a shoe in the ball pit and never seeing it again",
                  "the play place you begged to stop at on road trips", "socks only. no shoes past this point",
                  "the tube slide that was always way too hot", "you were the last kid here before close"],
    'rink':      ["roller rink birthday parties were a whole event", "the carpet at the bowling alley. you know the one",
                  "couples skate. you stayed on the wall", "the rink on a friday night in 2001",
                  "the arcade carpet you could stare at for hours"],
    'lab':       ["the computer lab after everyone went home", "the school computer lab, 2003",
                  "the whole class on the same typing game", "the starfield screensaver on every monitor",
                  "computer lab day was the best day of the week"],
    'school':    ["the hallway after the last bell", "the last day of school before summer",
                  "being sent to the office in third grade", "the hallway smelled like floor wax and lunch"],
    'mall':      ["the mall on a weekday morning in 2002", "the mall after every store pulled the shutters down",
                  "the mall the year before it closed"],
    'pool':      ["the hotel pool at 10pm on the family road trip", "swim lessons at 8am in january",
                  "the indoor pool on a rainy saturday"],
    'hotel':     ["walking to the ice machine at midnight", "the hotel hallway on the family road trip"],
    'backrooms': ["the door at the back of the furniture store", "the part of the building you weren't meant to see",
                  "getting lost in a building as a kid"],
}
def _line():
    if os.environ.get('CQ_HOOK'): return '' if os.environ['CQ_HOOK'] == 'none' else os.environ['CQ_HOOK']
    return random.Random(seed * 7919 + 11).choice(LINES[place])

# ---- the tape --------------------------------------------------------------------------------
MON = 'JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()
def _font(name, size):
    p = os.path.join(FONTS, name)
    try: return ImageFont.truetype(p, size)
    except OSError:
        for q in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
            if os.path.exists(q): return ImageFont.truetype(q, size)
        return ImageFont.load_default()
FMONO = _font('DejaVuSansMono-Bold.ttf', 54)
FLINE = _font('Poppins-Bold.ttf', 70)
FCREDIT = _font('DejaVuSansMono-Bold.ttf', 28)
CREDIT = '\u266a %s \u2014 %s' % (SONG.get('title', os.path.basename(SONG_DIR)).lower(), SONG.get('artist', 'Close Quarters').lower())
def _agree(line):
    """The tape's date stamp never contradicts the line: 'in 2001' is stamped 2001, 'friday night' is a Friday evening,
    'in january' is January, 'at 10pm' reads PM 10. (A line said 2001 over a 1995 stamp; 'at 10pm' over AM 2:48.)"""
    global year, month, day, hour
    import re, datetime
    r = random.Random(seed * 31 + 3); low = line.lower()
    m = re.search(r'\b(19[89]\d|200\d)\b', low)
    if m: year = int(m.group(1))
    for k, name in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']):
        if re.search(r'\b%s\b' % name, low) and name != 'may': month = k + 1
    if 'summer' in low: month = 6
    m = re.search(r'\b(\d{1,2})\s*(am|pm)\b', low)
    if m: hour = int(m.group(1)) % 12 + (12 if m.group(2) == 'pm' else 0)
    elif 'midnight' in low: hour = 0
    elif 'morning' in low: hour = r.choice([9, 10, 11])
    elif 'night' in low or 'before close' in low: hour = r.choice([20, 21, 22])
    elif 'last bell' in low or 'after everyone went home' in low: hour = r.choice([15, 16])
    want = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6}
    wd = next((v for k, v in want.items() if k in low), None)
    if wd is None and 'weekday' in low: wd = r.choice([0, 1, 2, 3])
    if wd is None and place in ('school', 'lab'):                # school is a weekday in term time
        wd = r.choice([0, 1, 2, 3, 4])
        if month in (7, 8): month = r.choice([9, 10, 11, 2, 3, 4])
    if wd is not None: day = r.choice([d for d in range(1, 29) if datetime.date(year, month, d).weekday() == wd])
    return line
plan = dict(place=place, laps=laps, year=year, pace=pace, tint=tint, tape=tape_wear, label=label, stamp=stamp, hook='' if _cards.CARDS else _agree(_line()), lyrics=None)
plan['year'] = year

# Instagram covers the top ~250 px, the bottom ~420 px and the right ~150 px with its own buttons and caption:
# every word drawn here stays inside x 60..930, y 250..1500.
SAFE_X0, SAFE_X1 = 60, W - 150

def _wrap(d, text, f, width):
    out, cur = [], ''
    for wd in text.split():
        t = (cur + ' ' + wd).strip()
        if d.textlength(t, font=f) <= width or not cur: cur = t
        else: out.append(cur); cur = wd
    return out + ([cur] if cur else [])

LINE_IMG = None
if plan['hook']:                                           # drawn once: white, heavy black outline, like text typed on a phone
    LINE_IMG = Image.new('RGBA', (W, H), (0, 0, 0, 0)); _d = ImageDraw.Draw(LINE_IMG)
    _wmax = SAFE_X1 - SAFE_X0 - 40; _rows = _wrap(_d, plan['hook'], FLINE, _wmax)
    while _wmax > 300 and len(_wrap(_d, plan['hook'], FLINE, _wmax - 20)) == len(_rows): _wmax -= 20   # even lines, no orphan word
    _rows = _wrap(_d, plan['hook'], FLINE, _wmax); _y = 400
    for _r in _rows:
        _x = (SAFE_X0 + SAFE_X1) / 2 - _d.textlength(_r, font=FLINE) / 2
        _d.text((_x, _y), _r, font=FLINE, fill=(255, 255, 255, 255), stroke_width=7, stroke_fill=(0, 0, 0, 255)); _y += 92

def tape(rgb, i):
    a = (np.clip(rgb, 0, 1) ** (1 / 1.1) * 255).astype(np.uint8)
    a = cv2.resize(a, (W // 2, H // 2), interpolation=cv2.INTER_LINEAR)
    a = cv2.GaussianBlur(a, (0, 0), .9)
    roll = .45 * np.sin(2 * np.pi * i / N * 2)                                # the hand holding the camcorder: a slight, looping tilt
    M = cv2.getRotationMatrix2D((W / 4, H / 4), roll, 1.03); a = cv2.warpAffine(a, M, (W // 2, H // 2), borderMode=cv2.BORDER_REFLECT)
    b = a.astype(np.int16); sh, noise, rollp = {'clean': (2, 4, .02), 'worn': (3, 7, .05), 'chewed': (5, 11, .12)}[tape_wear]
    sh += int(3 * hit[i] > 2.4)                                               # colour bleeds further on the hardest hits
    b[:, sh:, 0] = a[:, :-sh, 0]; b[:, :-sh, 2] = a[:, sh:, 2]
    r = np.random.default_rng(seed * 7 + i)
    b += r.normal(0, noise, b.shape[:2])[..., None].astype(np.int16)
    b[::2] = (b[::2] * .9).astype(np.int16)                                   # scanlines
    if tape_wear == 'chewed' and r.random() < .04: b = np.roll(b, int(r.integers(-6, 7)), 0)
    if hit[i] > .85 or r.random() < rollp:                                    # a tracking band tears through on the big drum hits
        y0 = r.integers(0, b.shape[0] - 14); b[y0:y0 + 12] = np.roll(b[y0:y0 + 12], r.integers(8, 34), 1) + 28
    yv, xv = np.ogrid[:b.shape[0], :b.shape[1]]
    vig = 1 - .45 * (((xv - b.shape[1] / 2) / (b.shape[1] / 2)) ** 2 + ((yv - b.shape[0] / 2) / (b.shape[0] / 2)) ** 2) / 2
    b = (b * vig[..., None]).clip(0, 255).astype(np.uint8)
    a = cv2.resize(b, (W, H), interpolation=cv2.INTER_LINEAR)
    im = Image.fromarray(a); d = ImageDraw.Draw(im)
    secs = (i // FPS) % 60
    if label != 'none': d.text((70, 262), label, font=FMONO, fill=(240, 60, 50) if label.startswith('REC') and (i // 15) % 2 == 0 else (240, 240, 240))
    d.text((70, 328), CREDIT, font=FCREDIT, fill=(225, 225, 225), stroke_width=2, stroke_fill=(0, 0, 0))   # the song, small, in the tape's chrome (the stamp owns y 1360-1480)
    if stamp != 'none':
        d.text((70, H - 560), '%s %02d %d' % (MON[month - 1], day, year), font=FMONO, fill=(240, 240, 240))
        d.text((70, H - 495), '%s %d:%02d:%02d' % ('AM' if hour < 12 else 'PM', hour % 12 or 12, minute, secs), font=FMONO, fill=(240, 240, 240))
    if LINE_IMG is not None: im.paste(LINE_IMG, (0, 0), LINE_IMG)
    a = np.asarray(im)
    if _cards.CARDS: return _cards.draw(np.ascontiguousarray(a), i / FPS)
    return a

def finish(i): return tape(frame(i), i)

if len(sys.argv) > 5 and sys.argv[4] == '--frames':
    fs = [int(x) for x in sys.argv[5].split(',')]
    ims = [Image.fromarray(finish(f)) if os.environ.get('CQ_FULL') else Image.fromarray(finish(f)).resize((W // 3, H // 3)) for f in fs]
    sheet = Image.new('RGB', (sum(im.width for im in ims), ims[0].height))
    for k, im in enumerate(ims): sheet.paste(im, (k * im.width, 0))
    sheet.save(out); print(out, plan); sys.exit(0)

# ---- encode ------------------------------------------------------------------------------------
wav = out + '.wav'
_sr = sf.info(MASTER).samplerate; _n = int(0.12 * _sr); _a = int(T0 * _sr)
_x, _ = sf.read(MASTER, start=_a, stop=int(T1 * _sr), always_2d=True, dtype='float32')
_pre, _ = sf.read(MASTER, start=max(0, _a - _n), stop=_a, always_2d=True, dtype='float32')
if len(_pre) == _n:                                    # the end fades into the sound just before the start, so the loop has no seam
    _r = np.linspace(0, 1, _n)[:, None]; _x[-_n:] = _x[-_n:] * (1 - _r) + _pre * _r
sf.write(wav, _x * min(1.0, 0.98 / (np.abs(_x).max() + 1e-9)), _sr)
tmp = out + '.part.mp4'
p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                      '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'medium'),
                      '-crf', os.environ.get('CQ_CRF', '23'), '-maxrate', os.environ.get('CQ_MAXRATE', '6M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '12M'),
                      '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
for i in range(N): p.stdin.write(np.ascontiguousarray(finish(i)).tobytes())
p.stdin.close(); p.wait(); os.remove(wav)
if p.returncode: sys.exit('ffmpeg failed')
os.replace(tmp, out)
json.dump(dict(seed=seed, window=[T0, T1], song=os.path.basename(SONG_DIR), style='liminal', plan=plan, **K.record()), open(os.path.splitext(out)[0] + '.json', 'w'), indent=1)
print(out)
