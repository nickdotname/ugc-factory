"""ASCII scene: a ringed planet with a moon. The planet swells on the kick, the rings brighten with the bass, stars twinkle on the snare."""
import numpy as np, math
FILE = 'planet.py'
SCALE, FOCAL, CENTER = 205.0, 6.0, 0.46
STEPS, STEP = 56, 0.9
GLOW_MISS, GLOW_W = 0.5, 0.02
GRAD = [(255, 222, 150), (255, 165, 85), (255, 100, 120), (200, 90, 220), (120, 110, 255)]
E = {}
def setup(e): E.update(e)

TX, TZ = -0.3, -0.28                     # the planet leans towards us, so the rings open into an ellipse
cx, sx, cz, sz = math.cos(TX), math.sin(TX), math.cos(TZ), math.sin(TZ)
def to_planet(px, py, pz):
    y, z = py * cx - pz * sx, py * sx + pz * cx
    x, y = px * cz - y * sz, px * sz + y * cz
    return x, y, z

def parts(px, py, pz, i):
    t = i / 30; R = 1.0 * (1 + 0.035 * E['pulse'][i])
    x, y, z = to_planet(px, py, pz)
    planet = np.sqrt(x * x + y * y + z * z) - R
    r = np.hypot(x, z)
    ring2 = np.maximum(r - 2.3, 1.42 - r); ring2 = np.maximum(ring2, -(np.abs(r - 1.92) - 0.06))   # the gap
    ring = np.maximum(ring2, np.abs(y) - 0.012)
    a = 0.55 * t; mx, my, mz = 2.8 * np.cos(a), 0.3 * np.sin(a), 2.8 * np.sin(a)          # the moon goes round, in front and behind
    moon = np.sqrt((x - mx) ** 2 + (y - my) ** 2 + (z - mz) ** 2) - 0.17
    return planet, ring, moon, (x, y, z, r)

def sdf(px, py, pz, i):
    p, r, m, _ = parts(px, py, pz, i); return np.minimum(p, m)      # the rings are drawn separately, as dust (compose)

RINGS = {}
def compose(L, hit, tt, ro, rd, i):
    # the rings: where each ray crosses the ring plane, if that is in front of whatever it hit
    o = to_planet(*ro); d = to_planet(rd[..., 0], rd[..., 1], rd[..., 2])
    s = np.where(np.abs(d[1]) > 1e-6, -o[1] / d[1], -1)
    qx, qz = o[0] + d[0] * s, o[2] + d[2] * s; r = np.hypot(qx, qz)
    on = (s > 0) & (r > 1.42) & (r < 2.3) & (np.abs(r - 1.92) > 0.06) & (~hit | (s < tt))
    lx, ly, lz = to_planet(*LIGHT); qy = 0
    b = qx * lx + qz * lz; c = qx * qx + qz * qz - 1.0
    shadow = (b * b - c > 0) & (-b - np.sqrt(np.maximum(b * b - c, 0)) > 0)
    Lr = (0.16 + 0.3 * np.sin(r * 48) ** 2) * np.where(shadow, 0.3, 1) * (1 + 0.6 * E['bass'][i])
    RINGS[i] = on
    return np.where(on, np.maximum(Lr, np.where(hit, L * 0.35, 0)), L)

LIGHT = np.array([-0.55, 0.45, 0.7]); LIGHT /= np.linalg.norm(LIGHT)
def shade(p, n, rd, i):
    t = i / 30
    pl, rg, mo, (x, y, z, r) = parts(p[:, 0], p[:, 1], p[:, 2], i)
    lam = np.clip(n @ LIGHT, 0, 1); fres = (1 - np.abs((n * rd).sum(-1))) ** 2
    L = 0.22 + 0.85 * lam + 0.45 * fres
    which = np.argmin(np.stack([pl, rg, mo]), 0)
    lat = np.arcsin(np.clip(y / (np.sqrt(x * x + y * y + z * z) + 1e-6), -1, 1)); lon = np.arctan2(z, x) + 0.3 * t
    bands = 0.8 + 0.2 * np.sin(lat * 15 + 0.7 * np.sin(lon * 3 + lat * 6))
    # the rings' shadow across the planet, and the planet's across the rings (both worked out exactly)
    lx, ly, lz = to_planet(*LIGHT)
    s_ring = np.where(np.abs(ly) > 1e-3, -y / ly, 1e9); hx, hz = x + lx * s_ring, z + lz * s_ring; hr = np.hypot(hx, hz)
    ring_shadow = (s_ring > 0) & (hr > 1.42) & (hr < 2.3) & (np.abs(hr - 1.92) > 0.06)
    b = x * lx + y * ly + z * lz; c = x * x + y * y + z * z - 1.0
    planet_shadow = (b * b - c > 0) & (-b - np.sqrt(np.maximum(b * b - c, 0)) > 0)
    Lp = L * bands * np.where(ring_shadow, 0.7, 1)
    Lr = (0.12 + 0.36 * np.sin(r * 48) ** 2) * (0.55 + 0.45 * lam) * np.where(planet_shadow, 0.25, 1) * (1 + 0.5 * E['bass'][i])
    return np.select([which == 0, which == 1], [Lp, Lr], L * 0.9)

rng = np.random.default_rng(3)
STARS = [(int(rng.uniform(0, 66)), int(rng.uniform(0, 120)), rng.uniform(0, 6.3)) for _ in range(80)]
def particles(i, rows, cols):
    t = i / 30; out = []
    for y, x, ph in STARS:
        tw = 0.5 + 0.5 * math.sin(t * 3 + ph) + 0.6 * E['snare'][i]
        out.append((y, x, '*' if tw > 1.1 else '+' if tw > 0.8 else '.', 0.25 + 0.35 * min(tw, 1.2)))
    return out

def colour(yr, xr, t, L): return yr * 0.35 + xr * 0.15 + 0.06 * math.sin(t * 0.5)

def tint(P, hit, i):
    # the planet warm, the rings and the moon cooler, so they read apart
    out = np.zeros(hit.shape)
    if hit.any():
        pl, rg, mo, _ = parts(P[hit][:, 0], P[hit][:, 1], P[hit][:, 2], i)
        w = np.argmin(np.stack([pl, mo]), 0); out[hit] = np.where(w == 0, 0.0, 0.7)
    out[RINGS.pop(i, np.zeros(hit.shape, bool))] = 0.5
    return out

def stats(i, sparks):
    return 'moons 1   rings 2   spin %.2f   kicks %d   sparks %d' % (0.3, int((E['kicks'] <= i).sum()), sparks)

CODE = '''def planet(p, t):
    # a ball that swells a little on every kick
    return length(p) - (1 + 0.035 * kick(t))

def rings(p):
    # a flat disc with a hole in the middle and a gap
    r = np.hypot(p.x, p.z)
    disc = max(r - 2.3, 1.42 - r, 0.06 - abs(r - 1.92))
    return max(disc, abs(p.y) - 0.012)

def bands(lat, lon, t):
    # storms that wrap round as it turns
    return 0.72 + 0.28 * np.sin(15 * lat + 0.7 * np.sin(3 * lon + 0.3 * t))

def moon(t):
    # goes round once every eleven seconds,
    # in front of the rings and then behind them
    a = 0.55 * t
    return [2.8 * np.cos(a), 0.3 * np.sin(a), 2.8 * np.sin(a)]

def shadow(p):
    # the rings shade the planet and the planet shades the rings
    return 0.45 if ring_between(p, sun) else 1.0
'''
