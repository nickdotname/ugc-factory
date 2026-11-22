"""ASCII scene: a jellyfish swimming in the dark. The bell squeezes on every kick, eight tentacles sway one after
another, bubbles drift up behind it and the snare throws sparks across the bell."""
import math
import numpy as np

FILE = 'jelly.py'
SCALE, FOCAL, CENTER = 215.0, 4.5, 0.30
STEPS, STEP = 70, 0.8
GLOW_MISS, GLOW_W = 0.62, 0.014          # thin tentacles glow even where a ray only just misses them
GRAD = [(255, 105, 180), (235, 95, 235), (150, 110, 255), (80, 150, 255), (70, 225, 240)]
ARMS, TENTACLES = 4, 8
E = {}
def setup(e): E.update(e)

def ellipsoid(px, py, pz, a, b):
    k0 = np.sqrt((px / a) ** 2 + (py / b) ** 2 + (pz / a) ** 2)
    k1 = np.sqrt((px / a ** 2) ** 2 + (py / b ** 2) ** 2 + (pz / a ** 2) ** 2) + 1e-6
    return k0 * (k0 - 1) / k1

def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1); return b * (1 - h) + a * h - k * h * (1 - h)

def local(px, py, pz, i):
    """Into the jellyfish's own frame: it drifts, bobs on the kick, tilts its opening towards us and slowly turns."""
    t = E['t0'] + i / 30; pulse = E['pulse'][i]
    yo = 0.10 * np.sin(0.45 * t) + 0.08 * pulse; spin = 0.22 * t; tilt = 0.32 + 0.05 * np.sin(0.3 * t)
    cs, sn, ct, st = np.cos(spin), np.sin(spin), np.cos(tilt), np.sin(tilt)
    x, y, z = px, py - yo, pz
    y, z = y * ct - z * st, y * st + z * ct
    x, z = x * cs - z * sn, x * sn + z * cs
    return x, y, z

def jelly(px, py, pz, t, pulse):
    sx, sy = 1 - 0.14 * pulse, 1 + 0.10 * pulse              # the bell squeezes on the kick
    phi = np.arctan2(pz, px)
    rim = 0.06 * np.sin(8 * phi + 2.5 * t)                   # eight scallops travelling round the rim
    outer = ellipsoid(px, py, pz, 1.15 * sx, 0.95 * sy)
    inner = ellipsoid(px, py + 0.16, pz, 1.02 * sx, 0.78 * sy)
    d = np.maximum(np.maximum(outer, -inner), -(py + 0.02 + rim))
    for k in range(ARMS):                                    # four ruffled oral arms in the middle
        a = k * np.pi / 2 + 0.4
        xc = 0.16 * np.cos(a) + 0.13 * np.sin(2.0 * py + 1.6 * t + k)
        zc = 0.16 * np.sin(a) + 0.13 * np.cos(1.7 * py + 1.3 * t + k)
        r = 0.05 + 0.04 * (0.5 + 0.5 * np.sin(14 * py - 4 * t + k))
        dy = np.maximum(np.maximum(py + 0.05, -1.7 - py), 0)
        d = smin(d, np.sqrt((px - xc) ** 2 + (pz - zc) ** 2 + dy ** 2) - r * np.clip(1.2 + py * 0.4, 0.3, 1), 0.12)
    for k in range(TENTACLES):                               # each tentacle sways a little after the last
        a = 2 * np.pi * k / TENTACLES; lag = 0.35 * k; depth = np.clip(-py, 0, None)
        xc = 0.98 * sx * np.cos(a) * (1 - 0.06 * depth) + 0.17 * depth * np.sin(2.4 * depth - 2.0 * t + lag) + 0.05 * depth * np.sin(5.1 * depth - 3.1 * t + 2 * lag)
        zc = 0.98 * sx * np.sin(a) * (1 - 0.06 * depth) + 0.17 * depth * np.cos(2.1 * depth - 1.7 * t + lag)
        dy = np.maximum(np.maximum(py, -2.9 - py), 0)
        d = np.minimum(d, np.sqrt((px - xc) ** 2 + (pz - zc) ** 2 + dy ** 2) - 0.022 * np.clip(1 - depth / 3.2, 0.35, 1))
    return d

def sdf(px, py, pz, i):
    return jelly(*local(px, py, pz, i), E['t0'] + i / 30, E['pulse'][i])

LIGHT = np.array([0.35, 0.85, 0.45]); LIGHT /= np.linalg.norm(LIGHT)
def shade(p, n, rd, i):
    fres = (1 - np.abs((n * rd).sum(-1))) ** 2
    return 0.16 + 0.42 * np.clip(n @ LIGHT, 0, 1) + 0.75 * fres

rng = np.random.default_rng(7)
BUB = [(rng.uniform(0, 120), rng.uniform(0, 66), rng.uniform(1.5, 4.5), rng.choice(list("o.°'"))) for _ in range(46)]
def particles(i, rows, cols):
    t = i / 30; out = []
    for bx, by, sp, c in BUB:                                 # bubbles drifting up behind it
        out.append((int((by - sp * t * 1.3) % rows), int(bx + 1.2 * math.sin(t * 0.8 + by)) % cols, c, 0.35))
    return out

def colour(yr, xr, t, L): return yr * 0.75 + xr * 0.35 - 0.05 + 0.08 * math.sin(t * 0.4)

def stats(i, sparks):
    return 'kicks %-4d arms %d   tentacles %d   sparks %d' % (int((E['kicks'] <= i).sum()), ARMS, TENTACLES, sparks)

CODE = '''def pulse(t):
    # the bell squeezes on every kick, then floats open again
    return 1 - 0.14 * kick(t)

def bell(p, t):
    # a dome with eight scallops travelling round the rim
    rim = 0.06 * np.sin(8 * angle(p) + 2.5 * t)
    outer = ellipsoid(p, 1.15 * pulse(t), 0.95)
    inner = ellipsoid(p + [0, 0.16, 0], 1.02, 0.78)
    return max(outer, -inner, -(p.y + rim))

def tentacle(p, k, t):
    # eight of them, each swaying a little after the last
    depth, lag = -p.y, 0.35 * k
    x = rim_x(k) + 0.17 * depth * np.sin(2.4 * depth - 2 * t + lag)
    z = rim_z(k) + 0.17 * depth * np.cos(2.1 * depth - 1.7 * t + lag)
    return np.hypot(p.x - x, p.z - z) - 0.022

def to_ascii(light):
    # dark cells get dots, bright ones get dense letters,
    # and edges get / | \\\\ by which way they lean
    ramp = " .:;i!tjrxnuzcvXUJCLQ0OZqpdbkhao*#W&8%B@$"
    return [ramp[int(l * 40)] for l in light]
'''
