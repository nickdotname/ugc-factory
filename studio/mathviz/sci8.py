"""Pixel-art science explainers, in parts, on the beat (a 270x480 canvas blown up 4x).

Each topic is a chain of short parts that escalate: the hook number, "but that's not the crazy part", the twist,
something you can picture it against, the payoff. A part lasts one or two bars and gets its own scene; numbers count up,
the characters (cells, hearts, eyes, all with faces) react to the kick, and a pixel dissolve changes scene on the
downbeat. Every number is a well-established figure, noted beside it. Knobs: topic, sky (the palette)."""
import sys, os, math, random
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *
from pixel import ptext, dgrad, disc, LW, LH, BY

SLUG, B0, SEED = conf('fixation', 96)
_r = random.Random(SEED)
TOPIC = K.pick('subject', ['brain', 'heart', 'eyes', 'fission'], _r, weights=[2, 0, 1, 1])   # review 2026-11-26: brain best, heart off
SKY = K.pick('sky', ['violet', 'navy', 'plum'], _r)
BG = {'violet': ((40, 30, 92), (24, 18, 58)), 'navy': ((18, 30, 76), (8, 14, 40)), 'plum': ((70, 28, 84), (34, 14, 48))}[SKY]
GOLD, WHITE, SOFT, INK = (255, 214, 90), (248, 248, 255), (200, 205, 235), (16, 12, 32)

# ------------------------------------------------------------------ drawing
def line(c, p0, p1, col, w=1): cv2.line(c, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), col, max(1, int(w)), cv2.LINE_8)

def blob(c, cx, cy, rx, ry, base, light, dark, outline=INK):
    """A shaded ellipse, dithered like a sprite: lit from the upper left."""
    yy, xx = np.ogrid[0:LH, 0:LW]; u = (xx - cx) / max(1, rx); v = (yy - cy) / max(1, ry); d = u * u + v * v
    o = d <= 1.0
    if outline is not None: c[(d <= (1 + 2.6 / max(rx, ry)) ** 2) & ~o] = outline
    lit = 0.5 - 0.55 * u - 0.6 * v
    c[o] = base
    c[o & (lit > 0.75 + 0.3 * BY[:LH, :LW])] = light
    c[o & (lit < -0.05 + 0.3 * BY[:LH, :LW])] = dark

def face(c, cx, cy, s, blink=False, mood='calm', look=0):
    ex = max(2, int(s * 0.32))
    for sx in (-ex, ex):
        if blink: c[int(cy):int(cy) + 1, int(cx + sx - s * 0.12):int(cx + sx + s * 0.12) + 1] = INK
        else:
            disc(c, cx + sx, cy, max(1.5, s * 0.17), (255, 255, 255)); disc(c, cx + sx + look, cy + 0.5, max(1, s * 0.09), INK)
    my = int(cy + s * 0.3)
    if mood == 'wow': disc(c, cx, my + 1, max(1.5, s * 0.1), INK)
    elif mood == 'happy': c[my:my + 1, int(cx - s * 0.15):int(cx + s * 0.15) + 1] = INK; c[my - 1, int(cx - s * 0.18)] = INK; c[my - 1, int(cx + s * 0.18)] = INK
    else: c[my:my + 1, int(cx - s * 0.1):int(cx + s * 0.1) + 1] = INK

def glow(c, cx, cy, r, col, a=1.0):
    yy, xx = np.ogrid[0:LH, 0:LW]; d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    m = np.clip(1 - d / r, 0, 1) ** 2 * a
    c += np.array(col, np.float32) * m[..., None]

def branch(c, x, y, ang, ln, w, depth, rng, col):
    if depth == 0 or ln < 2: return
    x1, y1 = x + math.cos(ang) * ln, y + math.sin(ang) * ln
    line(c, (x, y), (x1, y1), col, w)
    for s in (-1, 1):
        branch(c, x1, y1, ang + s * rng.uniform(0.3, 0.7), ln * rng.uniform(0.6, 0.78), max(1, w - 1), depth - 1, rng, col)

def back(c, k, kick):
    top, low = BG; dgrad(c, 0, LH, top, low)
    r = random.Random(3)
    for j in range(60):                                       # soft bokeh and specks
        x, y = r.randrange(LW), r.randrange(LH); tw = (math.sin(k * 1.7 + j) + 1) / 2
        if r.random() < 0.15: disc(c, x, y, r.randrange(4, 10), tuple(int(a * 1.12) for a in top))
        elif tw > 0.6: c[y, x] = (150, 140, 210)

# ------------------------------------------------------------------ scenes (k: beats into the part, kick 0..1, p: part progress 0..1)
def neuron(c, cx, cy, s, col, light, dark, k, kick, seed, awake=True, sig=None):
    rng = random.Random(seed)
    for j in range(7): branch(c, cx, cy, -math.pi / 2 + (j - 3) * 0.55 + rng.uniform(-0.2, 0.2), s * 1.4, max(1, int(s / 6)), 4, rng, col)
    ax = (cx + s * 3.2, cy + s * 4.2); line(c, (cx, cy), ax, col, max(2, int(s / 4)))
    for j in range(3): branch(c, ax[0], ax[1], math.pi * 0.35 + (j - 1) * 0.6, s * 0.8, 1, 2, rng, col)
    blob(c, cx, cy, s, s * 1.08, col, light, dark)
    face(c, cx - s * 0.05, cy - s * 0.05, s * 1.1, blink=not awake, mood='wow' if kick > 0.6 else 'calm')
    if sig is not None:                                       # a signal running down the axon
        x, y = cx + (ax[0] - cx) * sig, cy + (ax[1] - cy) * sig
        glow(c, x, y, 14, (120, 200, 255), 0.9); disc(c, x, y, 3, (240, 250, 255))
    if kick > 0.5:
        for a in (-0.5, 0.4, 1.9): line(c, (cx + math.cos(a) * s * 1.4, cy + math.sin(a) * s * 1.4), (cx + math.cos(a) * s * 1.8, cy + math.sin(a) * s * 1.8 + 2), WHITE)

def sc_neurons(c, k, kick, p, last_kick):
    for j, (x, y, s) in enumerate([(40, 200, 9), (230, 230, 11), (200, 400, 10), (30, 380, 8), (150, 150, 7)]):
        neuron(c, x, y, s, (84, 66, 160), (110, 92, 190), (62, 48, 124), k, 0, 10 + j, awake=False)
    neuron(c, 100, 280, 22, (240, 160, 70), (255, 220, 140), (200, 110, 50), k, kick, 1, sig=min(1.0, (k - last_kick) / 0.9))

HEAD = None
def sc_head(c, k, kick, p, last_kick):
    pts = np.array([(70, 470), (60, 360), (50, 300), (60, 230), (100, 180), (160, 170), (215, 195), (245, 250), (240, 300), (262, 330), (240, 345), (238, 380), (210, 395), (200, 470)], np.int32)
    cv2.fillPoly(c, [pts], (20, 22, 60)); cv2.polylines(c, [pts], False, (90, 150, 230), 1)
    yy, xx = np.ogrid[0:LH, 0:LW]
    br = (((xx - 150) / 72.0) ** 2 + ((yy - 255) / 52.0) ** 2) <= 1 + 0.06 * np.sin(xx * 0.4) * np.cos(yy * 0.3)
    c[br] = (86, 70, 170)
    c[(br) & ((np.sin(xx * 0.15 + yy * 0.05) * np.cos(yy * 0.13)) > 0.92)] = (40, 30, 90)       # the folds
    c[(((xx - 140) / 12.0) ** 2 + ((yy - 320) / 26.0) ** 2) <= 1] = (86, 70, 170)               # the stem
    r = np.random.default_rng(int(k * 6)); n = 900
    ys = r.integers(195, 335, n); xs = r.integers(70, 230, n); ok = br[ys, xs] if br.ndim == 2 else np.array([br[y, x] for y, x in zip(ys, xs)])
    c[ys[ok], xs[ok]] = (255, 190, 80)

def sc_network(c, k, kick, p, last_kick):
    cx, cy = 135, 270; r = random.Random(5); lit = int(80 * min(1, p * 1.3))
    for j in range(80):
        a = r.uniform(0, 2 * math.pi); d = r.uniform(50, 125); x, y = cx + math.cos(a) * d, cy + math.sin(a) * d * 1.1
        on = j < lit
        line(c, (cx, cy), (x, y), (255, 200, 90) if on else (70, 60, 130), 1)
        disc(c, x, y, 2.5, (255, 220, 120) if on else (100, 90, 170))
        if on and j == lit - 1: glow(c, x, y, 10, (255, 200, 90), 0.8)
    neuron(c, cx, cy, 13, (240, 160, 70), (255, 220, 140), (200, 110, 50), k, kick, 2)

def sc_field(c, k, kick, p, last_kick):
    """Zoomed out: hundreds of cells, each wired to its nearest neighbours, twinkling."""
    r = np.random.default_rng(9); n = 260
    xs, ys = r.integers(8, LW - 8, n), r.integers(160, 410, n); ph = r.random(n)
    P = np.stack([xs, ys], 1).astype(np.float32); D = ((P[:, None] - P[None]) ** 2).sum(-1); np.fill_diagonal(D, 1e9)
    near = np.argsort(D, 1)[:, :3]
    for a in range(n):
        for b in near[a]:
            on = math.sin(k * 2.5 + ph[a] * 9) > 0.5
            line(c, P[a], P[b], (255, 190, 80) if on else (80, 70, 160), 1)
    for a in range(n):
        disc(c, xs[a], ys[a], 2, (255, 220, 130) if math.sin(k * 2.5 + ph[a] * 9) > 0.5 else (130, 115, 210))

def sc_galaxy(c, k, kick, p, last_kick):
    r = np.random.default_rng(4); n = 1800
    t = r.random(n) * 4 * math.pi; arm = r.integers(0, 2, n); rad = 6 + t * 9 + r.normal(0, 5, n)
    ang = t + arm * math.pi + k * 0.15
    xs = (135 + np.cos(ang) * rad).astype(int); ys = (280 + np.sin(ang) * rad * 0.55).astype(int)
    ok = (xs >= 0) & (xs < LW) & (ys >= 0) & (ys < LH)
    c[ys[ok], xs[ok]] = (230, 220, 255)
    glow(c, 135, 280, 40 + 6 * kick, (255, 220, 160), 0.9)
    for dx in (-90, 90):                                      # and more of them, smaller, further off
        for q in range(80): c[int(400 + r.normal(0, 4)), int(np.clip(135 + dx + r.normal(0, 8), 0, LW - 1))] = (170, 160, 230)

def heart_shape(c, cx, cy, s, col, light, dark):
    yy, xx = np.ogrid[0:LH, 0:LW]; x = (xx - cx) / s; y = -(yy - cy) / s
    m = (x * x + y * y - 1) ** 3 - x * x * y ** 3 <= 0
    edge = ((x * 1.08) ** 2 + (y * 1.08) ** 2 - 1) ** 3 - (x * 1.08) ** 2 * (y * 1.08) ** 3 <= 0
    c[m & ~edge | (m & False)] = INK; c[edge] = col
    lit = 0.4 - 0.6 * x + 0.5 * y
    c[edge & (lit > 0.85 + 0.3 * BY[:LH, :LW])] = light; c[edge & (lit < -0.1 + 0.3 * BY[:LH, :LW])] = dark
    bound = m & ~cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool); c[bound] = INK

def sc_heart(c, k, kick, p, last_kick, s=70, cx=135, cy=270):
    pump = 1 + 0.14 * kick
    for j, x in enumerate((-18, 0, 18)): line(c, (cx + x, cy - s * 0.7), (cx + x * 1.4, cy - s * 1.25), (200, 60, 80), 6)
    heart_shape(c, cx, cy, s * pump, (225, 50, 80), (255, 130, 150), (160, 20, 60))
    face(c, cx, cy - s * 0.05, s * 0.7 * pump, blink=(int(k * 2) % 7 == 0), mood='happy' if kick < 0.5 else 'wow')
    if kick > 0.4:
        for a in (-2.4, -0.7, 0.7, 2.4): line(c, (cx + math.cos(a) * s * 1.3, cy + math.sin(a) * s * 1.2), (cx + math.cos(a) * s * 1.55, cy + math.sin(a) * s * 1.45), WHITE)

def sc_count(c, k, kick, p, last_kick):
    sc_heart(c, k, kick, p, last_kick, s=34, cx=135, cy=310)
    for j in range(10):                                       # a row of little hearts filling as the count rises
        x = 30 + j * 23; on = j < int(10 * min(1, p * 1.2))
        heart_shape(c, x, 395, 7, (225, 50, 80) if on else (80, 60, 110), (255, 130, 150) if on else (100, 80, 140), (160, 20, 60) if on else (60, 40, 90))

def sc_tank(c, k, kick, p, last_kick):
    x0, x1, y0, y1 = 70, 200, 190, 400
    c[y0:y1, x0:x1] = (40, 40, 70); lvl = int(y1 - (y1 - y0 - 10) * min(1, p * 1.15))
    c[lvl:y1, x0:x1] = (200, 30, 60); c[lvl:lvl + 2, x0:x1] = (255, 110, 130)
    for x in range(x0, x1, 4): c[int(lvl + 2 * math.sin(x * 0.4 + k * 6)), x] = (255, 150, 160)
    c[y0:y1, x0 - 3:x0] = (180, 190, 220); c[y0:y1, x1:x1 + 3] = (180, 190, 220); c[y1:y1 + 3, x0 - 3:x1 + 3] = (180, 190, 220)
    for y in range(y0 + 20, y1, 40): c[y, x1 - 12:x1] = (180, 190, 220); ptext(c, '%dL' % int(7500 * (y1 - y) / (y1 - y0)), x1 + 6, y - 3, 1, SOFT)
    sc_heart(c, k, kick, p, last_kick, s=22, cx=232, cy=210)
    line(c, (215, 214), (200, 214), (200, 60, 80), 3)

def sc_bath(c, k, kick, p, last_kick):
    c[330:380, 50:220] = (235, 235, 245); c[330:334, 46:224] = (255, 255, 255)
    lvl = int(372 - 34 * min(1, p * 1.2)); c[lvl:376, 56:214] = (200, 30, 60)
    for x in range(56, 214, 3): c[int(lvl + 1.5 * math.sin(x * 0.5 + k * 5)), x] = (255, 140, 150)
    c[380:396, 60:68] = (180, 180, 200); c[380:396, 202:210] = (180, 180, 200)
    c[290:300, 200:240] = (190, 190, 210); c[300:330 if p < 0.98 else 300, 205:209] = (200, 30, 60)
    sc_heart(c, k, kick, p, last_kick, s=20, cx=240, cy=260)

def eye(c, cx, cy, s, look, blur=0.0, lid=0.0):
    blob(c, cx, cy, s, s * 0.62, (245, 245, 250), (255, 255, 255), (200, 200, 220))
    ix, iy = cx + look[0] * s * 0.45, cy + look[1] * s * 0.25
    if blur > 0:                                              # the smear the brain never shows you
        for q in range(8): disc(c, ix - blur * q * 5, iy, s * 0.26, (120, 150, 210))
    disc(c, ix, iy, s * 0.3, (70, 140, 200)); disc(c, ix, iy, s * 0.3 - 3, (40, 100, 170)); disc(c, ix, iy, s * 0.14, INK); disc(c, ix - s * 0.08, iy - s * 0.08, 2, WHITE)
    if lid > 0: c[int(cy - s * 0.65):int(cy - s * 0.65 + lid * s * 1.3), int(cx - s):int(cx + s)] = (235, 170, 150)

LOOKS = [(-0.9, -0.4), (0.8, 0.2), (-0.2, 0.5), (0.9, -0.5), (-0.7, 0.4), (0.3, -0.3), (0.6, 0.5), (-0.9, 0.0)]
def sc_eye(c, k, kick, p, last_kick, blur=False):
    b = int(k); f = k - b; a, z = LOOKS[b % 8], LOOKS[(b + 1) % 8]; u = min(1, f / 0.12)
    look = (a[0] + (z[0] - a[0]) * u, a[1] + (z[1] - a[1]) * u)
    eye(c, 135, 270, 80, look, blur=(1 - u) * 1.2 if blur and u < 1 else 0.0)
    for j in range(5): line(c, (70 + j * 32, 215 - abs(j - 2) * 6), (64 + j * 32, 200 - abs(j - 2) * 8), INK, 2)

def sc_eraser(c, k, kick, p, last_kick):
    sc_eye(c, k, kick, p, last_kick, blur=True)
    bx, by = 110 + 45 * math.sin(k * 3.1), 262                 # the brain, with an eraser, wiping the smear away
    blob(c, 52, 372, 30, 22, (240, 150, 190), (255, 200, 220), (200, 100, 150)); face(c, 52, 368, 22, mood='happy')
    line(c, (70, 358), (bx, by + 14), (240, 150, 190), 3)
    c[int(by):int(by + 16), int(bx - 14):int(bx + 14)] = (250, 120, 150); c[int(by):int(by + 5), int(bx - 14):int(bx + 14)] = (90, 120, 220)

def sc_clock(c, k, kick, p, last_kick):
    disc(c, 135, 280, 74, INK); disc(c, 135, 280, 70, (240, 236, 220)); disc(c, 135, 280, 3, INK)
    for h in range(12):
        a = h / 12 * 2 * math.pi; c[int(280 - math.cos(a) * 60), int(135 + math.sin(a) * 60)] = INK
    sec = 0 if p < 0.45 else (k - 4 * 0.45 * 2)               # the second hand sticks, then catches up
    a = (sec * 0.25) % 1 * 2 * math.pi; line(c, (135, 280), (135 + math.sin(a) * 58, 280 - math.cos(a) * 58), (220, 40, 60), 2)
    line(c, (135, 280), (135 + 30, 280 - 20), INK, 3)
    eye(c, 225, 160, 28, (-0.9, 0.7))


# ---- fission: from a city at night down to one atom, and back up
def sc_city(c, k, kick, p, last_kick):
    r = random.Random(11)
    x = 0
    while x < 175:                                            # the skyline, windows lighting up on the kick
        w = r.randrange(18, 34); h = r.randrange(60, 150); top = 400 - h
        c[top:400, x:x + w - 2] = (30, 34, 80); c[top:top + 2, x:x + w - 2] = (60, 66, 130)
        for yy in range(top + 6, 392, 9):
            for xx in range(x + 3, x + w - 5, 6):
                if r.random() < 0.55 + 0.35 * kick: c[yy:yy + 4, xx:xx + 3] = (255, 200, 90) if r.random() < 0.8 else (140, 200, 255)
        x += w
    for y in range(240, 400):                                 # the cooling tower: a hyperboloid, lit from the left
        hw = int(24 + 22 * ((y - 330) / 90) ** 2); cx = 222
        row = np.arange(cx - hw, cx + hw)
        lit = (row - (cx - hw)) / (2 * hw)
        col = np.where((lit < 0.35 + 0.3 * BY[y, row % LW])[:, None], np.array([150, 165, 230], np.float32), np.array([80, 92, 170], np.float32))
        c[y, row[(row >= 0) & (row < LW)]] = col[(row >= 0) & (row < LW)]
    for j in range(9):                                        # steam rising and drifting
        q = (k * 0.35 + j / 9) % 1; disc(c, 222 + 22 * q + 4 * math.sin(j + k), 236 - 95 * q, 10 + 13 * q, (220, 228, 255), shade=(170, 180, 230))
    c[400:440] = (20, 30, 90)
    for j in range(24):                                       # lights on the water
        xx = (j * 37 + int(k * 6)) % LW; c[408 + (j * 7) % 28, xx:xx + 6] = (255, 190, 90) if j % 3 else (120, 180, 255)
    c[300:338, 30:240] = (14, 12, 34); c[300:302, 30:240] = (120, 170, 255); c[336:338, 30:240] = (120, 170, 255)
    c[300:338, 30:32] = (120, 170, 255); c[300:338, 238:240] = (120, 170, 255)
    ptext(c, 'NUCLEAR FISSION', 135, 308, 2, WHITE, align='c'); ptext(c, 'MATH.EXPLAINERS', 135, 326, 1, (120, 170, 255), align='c')

def sc_rods(c, k, kick, p, last_kick):
    c[:] = c * 0.4 + np.array([10, 40, 140], np.float32) * 0.6
    for j in range(7):                                        # fuel rods in water, glowing blue (Cherenkov light)
        x = 22 + j * 38 + int(6 * math.sin(k * 0.5 + j)); top = 150 + (j % 2) * 20
        c[top:470, x:x + 20] = (90, 170, 255); c[top:470, x + 5:x + 12] = (210, 240, 255)
        for y in range(top + 10, 470, 26): c[y:y + 2, x:x + 20] = (40, 90, 200)       # the pellets stacked inside
        glow(c, x + 10, 330, 70, (40, 120, 255), 0.35 + 0.5 * kick)

U_DOTS = []
def nucleus(c, cx, cy, r, k, kick, squash=1.0):
    if not U_DOTS:
        rr = random.Random(235); prot = set(rr.sample(range(235), 92))
        for n in range(235):
            a = n * 2.39996; d = math.sqrt(n / 235)
            U_DOTS.append((d * math.cos(a), d * math.sin(a), n in prot))
    for x, y, pr in U_DOTS:
        jx = 0.6 * math.sin(k * 9 + x * 40); jy = 0.6 * math.cos(k * 8 + y * 40)
        disc(c, cx + x * r * squash + jx, cy + y * r / squash + jy, 2.2, (235, 70, 70) if pr else (150, 160, 200))

SHELLS = [2, 8, 18, 32, 21, 9, 2]                             # uranium's 92 electrons, shell by shell
def sc_atom(c, k, kick, p, last_kick):
    cx, cy = 135, 290
    glow(c, cx, cy, 60, (40, 110, 255), 0.8 + 0.4 * kick)
    for j, n in enumerate(SHELLS):
        rad = 30 + j * 13; cv2.circle(c, (cx, cy), rad, (60, 110, 230), 1)
        for e in range(n):
            a = 2 * math.pi * e / n + k * (0.9 - j * 0.1) * (1 if j % 2 else -1)
            disc(c, cx + rad * math.cos(a), cy + rad * math.sin(a), 1.5, WHITE)
    nucleus(c, cx, cy, 17 * (1 + 0.06 * kick), k, kick)

def _bounces():
    r = random.Random(7); x, y, ang = -10.0, 190.0, 0.35; pts = [(x, y)]
    for ln in (150, 115, 85, 62, 45, 32, 22, 15):
        x = min(250, max(20, x + math.cos(ang) * ln)); y = min(390, max(160, y + math.sin(ang) * ln)); pts.append((x, y))
        tx, ty = 120 - x, 300 - y                               # each bounce turns it, loosely toward the uranium
        ang = math.atan2(ty, tx) + r.choice((-1, 1)) * r.uniform(0.6, 1.3)
    return pts
BOUNCE = _bounces()
_wr = random.Random(99)
WATER = [(x, y, _wr.uniform(0, 6.28)) for x, y in BOUNCE[1:]]
while len(WATER) < 34:
    x, y = _wr.uniform(12, 258), _wr.uniform(160, 395)
    if min(math.hypot(x - a, y - b) for a, b, _ in WATER) > 22: WATER.append((x, y, _wr.uniform(0, 6.28)))

def water(c, x, y, a, hit=0.0):
    disc(c, x, y, 5, (220 + 35 * hit, 50 + 120 * hit, 60 + 100 * hit), shade=(150, 20, 40))
    for s_ in (-1, 1): disc(c, x + 7 * math.cos(a + s_ * 0.9), y + 7 * math.sin(a + s_ * 0.9), 2.5, WHITE)

def sc_neutron(c, k, kick, p, last_kick):
    seg = min(len(BOUNCE) - 1.001, p * 1.08 * (len(BOUNCE) - 1)); j = int(seg); f = seg - j
    for n, (x, y, a) in enumerate(WATER):                     # water molecules: an oxygen and two hydrogens, jiggling
        hit = max(0.0, 1 - abs(seg - n - 1) * 3) if n < len(BOUNCE) - 1 else 0.0
        water(c, x + 0.8 * math.sin(k * 3 + n), y + 0.8 * math.cos(k * 2.6 + n), a + 0.3 * math.sin(k + n), hit)
    nx = BOUNCE[j][0] + (BOUNCE[j + 1][0] - BOUNCE[j][0]) * f; ny = BOUNCE[j][1] + (BOUNCE[j + 1][1] - BOUNCE[j][1]) * f
    for q in range(max(0, j - 2), j):                          # a short fading trail: only the last few legs
        fade = 0.25 + 0.35 * (q - j + 3) / 3
        line(c, BOUNCE[q], BOUNCE[q + 1], tuple(int(v * fade) for v in (80, 200, 255)), 1)
    line(c, BOUNCE[j], (nx, ny), (150, 230, 255), 2)
    glow(c, nx, ny, 20, (80, 200, 255), 1.0); disc(c, nx, ny, 3, (220, 250, 255))

def sc_split(c, k, kick, p, last_kick):
    cx, cy = 135, 300
    if p < 0.3:
        nucleus(c, cx, cy, 17, k, kick); nx = 10 + (cx - 30) * p / 0.3
        glow(c, nx, cy, 14, (80, 200, 255)); disc(c, nx, cy, 3, (200, 245, 255))
    elif p < 0.45:
        nucleus(c, cx, cy, 17, k * 3, kick, squash=1 + 1.5 * (p - 0.3) / 0.15)   # it wobbles and stretches into a peanut
    else:
        q = (p - 0.45) / 0.55; d = 20 + 120 * q
        glow(c, cx, cy, 120 * (1 - q) + 10, (255, 240, 200), 1.6 * (1 - q))
        nucleus(c, cx - d, cy - 0.2 * d, 12, k, kick); nucleus(c, cx + d, cy + 0.15 * d, 11, k, kick)
        if q > 0.25:                                          # one common pair of fragments
            ptext(c, 'BARIUM', int(cx - d), int(cy - 0.2 * d + 18), 1, SOFT, align='c'); ptext(c, 'KRYPTON', int(cx + d), int(cy + 0.15 * d + 17), 1, SOFT, align='c')
        for a in (-1.9, 0.4, 2.6):                            # three new neutrons fly out
            x, y = cx + math.cos(a) * d * 1.3, cy + math.sin(a) * d * 1.3
            glow(c, x, y, 12, (80, 200, 255)); disc(c, x, y, 3, (200, 245, 255))

def sc_chain(c, k, kick, p, last_kick):
    gens = int(min(5, 1 + p * 6)); rows = [160, 210, 260, 310, 360]
    prev = [(135, rows[0])]
    for g in range(gens):
        n = 3 ** g; pos = [(135 + (i - (n - 1) / 2) * min(70, 250 / n), rows[g]) for i in range(n)]
        if g: [line(c, prev[i // 3], q, (80, 200, 255), 1) for i, q in enumerate(pos)]
        for (x, y) in pos:
            if g < 3: disc(c, x, y, 6 - g, (235, 70, 70), shade=(160, 40, 50))
            else: c[int(y) - 1:int(y) + 2, int(x) - 1:int(x) + 2] = (255, 120, 100)
            if g == gens - 1: glow(c, x, y, 10, (255, 220, 160), 0.6 * kick + 0.3)
        prev = pos
    ptext(c, '1 - 3 - 9 - 27 - 81', 135, 392, 1, SOFT, align='c')

def sc_coal(c, k, kick, p, last_kick):
    glow(c, 50, 300, 30, (80, 255, 140), 0.8 + 0.5 * kick)    # one small block of uranium
    c[292:308, 42:58] = (120, 230, 140); c[292:294, 42:58] = (200, 255, 210)
    ptext(c, '1 KG', 50, 316, 1, SOFT, align='c'); ptext(c, '=', 92, 296, 2, WHITE, align='c')
    r = random.Random(5); g = min(1, p * 1.25); h = 40 + 200 * g    # against a mountain of coal
    for j in range(int(420 * g) + 60):
        x = r.uniform(108, 266); top = 398 - h * max(0, 1 - abs(x - 187) / 80) ** 1.2
        y = r.uniform(top, 398); s_ = r.uniform(3, 7); disc(c, x, y, s_, (44, 44, 58), shade=(18, 18, 26))
        if r.random() < 0.15: c[int(y - s_ * 0.5), int(x - s_ * 0.4)] = (110, 110, 140)
    c[398:402, 100:270] = (30, 30, 44)

def sc_control(c, k, kick, p, last_kick):
    c[:] = c * 0.4 + np.array([10, 40, 140], np.float32) * 0.6
    drop = min(1, p * 2.2); level = 1.0 - 0.55 * drop             # control rods slide in; the glow settles
    for j in range(7):
        x = 22 + j * 38; c[170:470, x:x + 20] = (90, 170, 255); c[170:470, x + 5:x + 12] = (210, 240, 255)
        glow(c, x + 10, 330, 70, (40, 120, 255), level * (0.4 + 0.4 * kick))
    for j in range(6):                                          # dark boron rods between the fuel
        x = 45 + j * 38; bot = int(170 + 190 * drop)
        c[150:bot, x:x + 8] = (52, 56, 74); c[150:bot, x + 1:x + 3] = (96, 100, 124); c[bot - 3:bot, x:x + 8] = (30, 30, 44)
    r = random.Random(int(k * 4))
    for j in range(int(16 - 10 * drop)):                         # free neutrons: fewer and fewer as the rods eat them
        x, y = r.uniform(10, 260), r.uniform(170, 400); glow(c, x, y, 8, (80, 200, 255), 0.8); disc(c, x, y, 2, (220, 250, 255))
    ptext(c, 'EACH SPLIT: ONE MORE SPLIT', 135, 392, 1, WHITE, align='c', box=(14, 12, 34))

# ------------------------------------------------------------------ the topics: (bars, scene, [(text, colour, scale), ...], count-up)
TOPICS = {
    'brain': [   # 86 billion neurons (Azevedo et al. 2009); thousands of synapses each, 100+ trillion in all
        (2, sc_neurons, [('YOUR BRAIN HAS', WHITE, 2), ('86 BILLION', GOLD, 4), ('NEURONS', WHITE, 3)], None),
        (1, sc_head, [("BUT THAT'S NOT", WHITE, 2), ('THE CRAZY', GOLD, 3), ('NUMBER', WHITE, 3)], None),
        (2, sc_network, [('EACH LINKS TO ABOUT', WHITE, 2), ('{}', GOLD, 4), ('OTHERS', WHITE, 3)], (0, 7000, '{:,.0f}')),
        (2, sc_field, [("THAT'S OVER", WHITE, 2), ('100 TRILLION', GOLD, 3), ('CONNECTIONS', WHITE, 2)], None),
        (1, sc_galaxy, [('MORE THAN THE STARS', WHITE, 1), ('IN 250', GOLD, 4), ('MILKY WAYS', WHITE, 3)], None),
    ],
    'heart': [   # ~100,000 beats a day; ~2.5 billion over a lifetime; ~7,500 L (2,000 gal) of blood a day (AHA)
        (2, sc_heart, [('YOUR HEART BEATS', WHITE, 2), ('100,000', GOLD, 4), ('TIMES A DAY', WHITE, 2)], None),
        (2, sc_count, [('IN A LIFETIME', WHITE, 2), ('{}', GOLD, 3), ('BEATS', WHITE, 3)], (0, 2.5e9, '{:,.0f}')),
        (2, sc_tank, [('EVERY DAY IT PUMPS', WHITE, 2), ('{}', GOLD, 4), ('OF BLOOD', WHITE, 2)], (0, 7500, '{:,.0f} L')),
        (1, sc_bath, [("THAT'S A", WHITE, 2), ('FULL BATHTUB', GOLD, 3), ('EVERY HALF HOUR', WHITE, 2)], None),
        (1, sc_heart, [('AND IT', WHITE, 2), ('NEVER', GOLD, 4), ('STOPS', WHITE, 3)], None),
    ],
    'fission': [  # U-235: 92 protons, 143 neutrons; fission neutrons ~1 MeV (~14,000 km/s), slowed by water to ~2.2 km/s;
                  # 2-3 new neutrons per split; 1 kg U-235 fully split ~8x10^13 J, about 3,000 tonnes of coal at ~27 MJ/kg
        (2, sc_city, [('HOW DOES SPLITTING', WHITE, 2), ('ONE ATOM', GOLD, 3), ('LIGHT UP A CITY?', WHITE, 2)], None),
        (1, sc_rods, [('INSIDE A REACTOR:', WHITE, 2), ('URANIUM FUEL', GOLD, 3)], None),
        (2, sc_atom, [('ONE URANIUM-235 ATOM', WHITE, 2), ('92 PROTONS', GOLD, 3), ('143 NEUTRONS', SOFT, 2)], None),
        (2, sc_neutron, [('A STRAY NEUTRON', WHITE, 2), ('{}', GOLD, 3), ('WATER SLOWS IT DOWN', SOFT, 2)], (14000, 2, '{:,.0f} KM/S')),
        (1, sc_split, [('IT SPLITS THE ATOM', WHITE, 2), ('+ ENERGY', GOLD, 3), ('+ 2 OR 3 NEUTRONS', SOFT, 2)], None),
        (1, sc_chain, [('EACH NEW NEUTRON', WHITE, 2), ('SPLITS ANOTHER', GOLD, 3), ('A CHAIN REACTION', SOFT, 2)], None),
        (1, sc_control, [('CONTROL RODS', WHITE, 2), ('SOAK UP', GOLD, 3), ('THE EXTRAS', GOLD, 3)], None),
        (2, sc_coal, [('1 KG OF URANIUM-235', WHITE, 2), ('{}', GOLD, 3), ('TONNES OF COAL', WHITE, 2)], (0, 3000, 'ABOUT {:,.0f}')),
    ],
    'eyes': [    # ~3 saccades a second; saccadic suppression; chronostasis (the stopped-clock illusion)
        (2, sc_eye, [('YOUR EYES JUMP', WHITE, 2), ('3 TIMES', GOLD, 4), ('EVERY SECOND', WHITE, 2)], None),
        (2, sc_eraser, [('BUT YOU NEVER', WHITE, 2), ('SEE THE BLUR', GOLD, 3)], None),
        (1, sc_eraser, [('YOUR BRAIN', WHITE, 3), ('DELETES IT', GOLD, 3)], None),
        (2, sc_clock, [('EVER GLANCED AT A CLOCK', WHITE, 1), ('AND THE FIRST SECOND', WHITE, 1), ('FELT LONGER?', GOLD, 3)], None),
        (1, sc_clock, [("THAT'S YOUR BRAIN", WHITE, 2), ('FILLING THE GAP', GOLD, 2)], None),
    ],
}
# the scale box (metres, ticking down through the zoom) and where each cut zooms in
SCALE = {sc_city: 10000, sc_rods: 4, sc_control: 4, sc_atom: 4e-10, sc_neutron: 2e-9, sc_split: 2e-14, sc_chain: 2e-9}
ZOOM_AT = {sc_city: (222, 300), sc_rods: (135, 330), sc_neutron: (130, 300)}
def metres(v):
    if v >= 1: return '{:,.0f} M'.format(v)
    d = max(0, -int(math.floor(math.log10(v)))); return ('{:.%df} M' % d).format(v)

def scale_box(c, n, kp):
    sc = SCALE.get(PARTS[n][1])
    if sc is None: return
    prv = SCALE.get(PARTS[n - 1][1], sc) if n else sc
    t = min(1.0, kp / 1.5); t = 1 - (1 - t) ** 3                 # log-ticker over the first beat and a half
    v = 10 ** (math.log10(prv) + (math.log10(sc) - math.log10(prv)) * t)
    s_ = 'SCALE  ' + metres(v); w = len(s_) * 6 + 8; x0 = LW // 2 - w // 2
    c[10:26, x0:x0 + w] = (14, 12, 34); c[10, x0:x0 + w] = SOFT; c[25, x0:x0 + w] = SOFT; c[10:26, x0] = SOFT; c[10:26, x0 + w - 1] = SOFT
    ptext(c, s_, LW // 2, 14, 1, WHITE, align='c')

PARTS = TOPICS[TOPIC]
BEATS_N = sum(b for b, *_ in PARTS) * 4
CL = Clock(SLUG, B0, BEATS_N)
CREDIT = credit(SLUG)
STARTS = np.cumsum([0] + [b * 4 for b, *_ in PARTS])

def headline(c, lines, age):
    y = 46
    for j, (txt, col, sc) in enumerate(lines):
        if age < 0.12 * j: break                              # each line lands a moment after the one above
        drop = int(max(0.0, 1 - (age - 0.12 * j) / 0.12) * -10)
        ptext(c, txt, LW // 2, y + drop, sc, col, align='c'); y += 7 * sc + 6

def render_part(i, c, k, kick):
    n = int(np.searchsorted(STARTS, k, side='right') - 1); n = min(n, len(PARTS) - 1)
    bars, scene, lines, count = PARTS[n]; kp = k - STARTS[n]; p = kp / (bars * 4)
    kicks = [b for b in CL.kick_beats if b <= k]; lk = (kicks[-1] - STARTS[n]) if kicks else -9
    back(c, k, kick); scene(c, kp, kick, p, lk)
    if count:
        a, b, fmt = count; v = a + (b - a) * (1 - (1 - min(1, p * 1.4)) ** 3)
        lines = [(fmt.format(v) if t == '{}' else t, col, sc) for t, col, sc in lines]
        lines = [(t, col, sc if len(t) * 6 * sc < LW - 10 else max(2, (LW - 10) // (len(t) * 6))) for t, col, sc in lines]
    headline(c, lines, kp); scale_box(c, n, kp)
    return n

def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = np.zeros((LH, LW, 3), np.float32); n = render_part(i, c, k, kick)
    since = k - STARTS[n]
    zc = ZOOM_AT.get(PARTS[n - 1][1]) if n > 0 else None
    T = 0.6 if zc else 0.25
    if n > 0 and since < T:                                   # a pixel dissolve from the part before (pushing in, for a zoom)
        prev = np.zeros((LH, LW, 3), np.float32); render_part(i, prev, STARTS[n] - 0.01, kick)
        t = since / T
        if zc:
            z = 1 + 5 * t * t; M = np.float32([[z, 0, zc[0] * (1 - z) + (LW / 2 - zc[0]) * t], [0, z, zc[1] * (1 - z) + (LH / 2 - zc[1]) * t]])
            prev = cv2.warpAffine(prev, M, (LW, LH), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REPLICATE)
        m = (BY[:LH, :LW] > t)[..., None]; c = np.where(m, prev, c)
    big = cv2.resize(np.clip(c, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(np.float32)
    paste(big, text(CREDIT, F(DEJAVU, 30), (230, 230, 240), stroke=3), W / 2, 1470)   # inside Instagram's safe area
    return np.clip(big, 0, 255).astype(np.uint8)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
