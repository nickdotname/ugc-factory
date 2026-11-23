"""ASCII scene (colour): a school of goldfish drifting through the dark, set in small glowing letters. Each fish is a
real 3D body (an outline swept round in ovals), covered in rows of scales that catch the light, with see-through fins
and a tail fan of rays that trail behind it as it swims. On every kick the whole school pushes forward (the tails beat
harder), the snare sends up bubbles."""
import math
import numpy as np
import paint as P
from paint import E

FILE = 'goldfish.py'
EDGES = False                           # the letters follow the scales, not the outline
GLOW = 0.4                              # a soft glow: the letters stay readable
# ----
N_FISH = 6
SS = 3                                   # sub-samples per letter cell, each way
LIGHT = np.array([0.3, 0.8, 0.5]); LIGHT /= np.linalg.norm(LIGHT)      # points away from the light: it comes from above, in front
FISH, BUBBLES = [], []


def body_points(nu=110, nt=72):
    """The body: its side outline swept round in ovals, so it is truly round."""
    u, th = np.meshgrid(np.linspace(0, 1, nu), np.linspace(0, 2 * np.pi, nt, endpoint=False))
    u, th = u.ravel(), th.ravel()
    h = 0.42 * np.sin(np.pi * np.clip(u, 0.002, 1)) ** 0.62 * (1 - 0.38 * u)        # tall in front, thin at the tail
    w = 0.72 * h
    mid = -0.07 * np.sin(np.pi * u)                                                    # a slight hump
    x, y, z = (0.5 - u), mid + h * np.sin(th), w * np.cos(th)
    n = np.stack([0.25 * (u - 0.5), np.sin(th) * w, np.cos(th) * h], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
    # scales: overlapping rows, offset every other row; each scale brighter at its centre
    sr, sc = u * 26, th / (2 * np.pi) * 34
    sc = sc + 0.5 * (np.floor(sr) % 2)
    edge = np.clip(1 - np.hypot(sr % 1 - 0.5, sc % 1 - 0.5) * 1.6, 0, 1)
    eye = np.hypot(u - 0.13, (th - 0.35 * np.pi) * 0.16) < 0.045
    return np.stack([x, y, z], -1), n, u, edge, eye


def fin_points():
    """The fins: a filled outline with rays drawn on top, ragged at the tips."""
    r = np.random.default_rng(3); pts, wt = [], []
    a, b = np.meshgrid(np.linspace(0, 1, 46), np.linspace(-1, 1, 70)); a, b = a.ravel(), b.ravel()
    ray = np.abs(np.sin(b * 4.5 * np.pi)) ** 8                              # nine rays
    rag = a < 0.82 + 0.18 * np.abs(np.sin(b * 11)) + 0.04 * r.random(a.size)  # ragged tips
    tail = np.stack([0.5 + 0.8 * a, 0.55 * b * (0.12 + a) + 0.06 * np.sin(5 * a + 2 * b) * a, np.zeros_like(a)], -1)   # a long, flowing fan
    pts.append(tail[rag]); wt.append((0.35 + 0.9 * ray)[rag])
    d = np.stack([0.15 - 0.42 * a * (1 - 0.3 * b), -0.26 - 0.3 * a * (0.6 + 0.4 * np.abs(b)), np.zeros_like(a)], -1)   # dorsal
    pts.append(d); wt.append(0.25 + 0.6 * ray)
    for side in (-1, 1):                                                    # the pair of fins under the head
        p = np.stack([0.18 - 0.22 * a, 0.16 + 0.2 * a * (0.5 + 0.5 * b), side * (0.18 + 0.1 * a)], -1)
        pts.append(p); wt.append(0.2 + 0.5 * ray)
    return np.concatenate(pts), np.concatenate(wt), np.concatenate([np.full(len(p), k) for k, p in enumerate(pts)])


def setup(e):
    P.setup(e); r = np.random.default_rng(e.get('seed', 7))
    B = body_points(); F = fin_points()
    FISH[:] = []
    for k in range(N_FISH):
        d = r.choice([-1, 1])
        FISH.append(dict(B=B, F=F, dir=d, size=r.uniform(210, 330), speed=r.uniform(55, 95), x0=r.uniform(0, E['AW']),
                         y0=E['AH'] * r.uniform(0.15, 0.85), z0=r.uniform(-250, 450), ph=r.uniform(0, 6.28), beat=r.uniform(4.5, 6.5)))
    BUBBLES[:] = [(r.uniform(0, E['AW']), r.uniform(0, E['AH']), r.uniform(12, 30), r.uniform(0, 6.28)) for _ in range(26)]


def swim(f, t, push):
    """Where a fish is and which way it faces: a wandering path, faster on the kick."""
    span = E['AW'] + 700
    x = (f['x0'] + f['dir'] * (f['speed'] * t + 60 * push) + 350) % span - 350
    y = f['y0'] + 45 * math.sin(0.45 * t + f['ph'])
    z = f['z0'] + 160 * math.sin(0.3 * t + 2 * f['ph'])
    yaw = math.atan2(48 * math.cos(0.3 * t + 2 * f['ph']), f['speed']) * f['dir'] + (0 if f['dir'] > 0 else math.pi)
    return x, y, z, yaw


def place(p, f, t, push, yaw, x, y, z, bend_u):
    """Fish space to the screen: the tail swings, the body turns, then perspective."""
    s = f['size']; q = p * s
    swing = (0.10 + 0.08 * push) * s * np.clip(bend_u - 0.25, 0, None) ** 1.6 * np.sin(f['beat'] * t - 5.5 * bend_u + f['ph'])
    q = q + np.stack([np.zeros_like(swing), np.zeros_like(swing), swing], -1)
    c, sn = math.cos(yaw), math.sin(yaw)
    qx, qz = q[:, 0] * c - q[:, 2] * sn, q[:, 0] * sn + q[:, 2] * c
    k = 900.0 / (900.0 + z + qz)
    return E['AW'] / 2 + (x - E['AW'] / 2 + qx) * k, E['AH'] / 2 + (y - E['AH'] / 2 + q[:, 1]) * k, z + qz, c, sn


def image(i):
    t = P.t_of(i); push = float(E['kick'][i]); R, C = E['rows'], E['cols']
    h, w = R * SS, C * SS; sx, sy = w / E['AW'], h / E['AH']
    zb = np.full((h, w), 1e9, np.float32); Lb = np.zeros((h, w), np.float32); rgb = np.zeros((h, w, 3), np.float32)
    fin_L = np.zeros((h, w), np.float32); fin_rgb = np.zeros((h, w, 3), np.float32)
    order = sorted(FISH, key=lambda f: -swim(f, t, push)[2])
    for f in order:
        x, y, z, yaw = swim(f, t, push)
        (bp, bn, bu, edge, eye) = f['B']; (fp, fw, fk) = f['F']
        X, Y, Z, c, s = place(bp, f, t, push, yaw, x, y, z, bu)
        nx, nz = bn[:, 0] * c - bn[:, 2] * s, bn[:, 0] * s + bn[:, 2] * c
        n = np.stack([nx, bn[:, 1], nz], -1)
        dif = np.clip(n @ -LIGHT, 0, 1); spec = np.clip(n @ np.array([0, 0, -1.0]), 0, 1) ** 18
        L = np.clip(0.06 + 1.05 * dif ** 0.9 * (0.45 + 0.75 * edge) + 0.35 * spec, 0, 1)        # each scale a letter brighter than its rim
        col = P.ramp3((120, 22, 6), (255, 105, 20), (255, 200, 90), np.clip(dif * 0.9 + 0.3 * edge * dif, 0, 1)) + P.lerp((0, 0, 0), (255, 240, 190), spec * 0.9)
        L = np.where(eye, 0.05 + 0.9 * (spec > 0.3), L); col[eye] = (20, 16, 18)
        ix, iy = (X * sx).astype(int), (Y * sy).astype(int)
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):                    # each point covers 2x2 sub-cells
            jx, jy = ix + dx, iy + dy; ok = (jx >= 0) & (jx < w) & (jy >= 0) & (jy < h)
            o = np.argsort(-Z[ok]); jx, jy, zz = jx[ok][o], jy[ok][o], Z[ok][o]
            near = zz < zb[jy, jx]
            jx, jy, zz = jx[near], jy[near], zz[near]; src = np.flatnonzero(ok)[o][near]
            zb[jy, jx] = zz; Lb[jy, jx] = L[src]; rgb[jy, jx] = col[src]
        fu = np.clip(fp[:, 0] + 0.5, 0, 1.2)
        X, Y, Z, c, s = place(fp, f, t, push, yaw, x, y, z, fu)
        ix, iy = (X * sx).astype(int), (Y * sy).astype(int); ok = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        a = fw[ok] * (0.55 + 0.45 * math.sin(3 * t + f['ph'])) * 0.32
        np.add.at(fin_L, (iy[ok], ix[ok]), a)
        np.add.at(fin_rgb, (iy[ok], ix[ok]), a[:, None] * np.array([255, 150, 50], np.float32))
    body = zb < 1e9
    L = np.where(body, Lb, np.clip(fin_L, 0, 0.55))
    col = np.where(body[..., None], rgb, fin_rgb / (fin_L[..., None] + 1e-6))
    # down to letter cells: brightness is the mean; colour is brightness-weighted
    Lc = L.reshape(R, SS, C, SS).mean((1, 3))
    cc = (col * L[..., None]).reshape(R, SS, C, SS, 3).sum((1, 3)) / (L.reshape(R, SS, C, SS).sum((1, 3))[..., None] + 1e-6)
    return np.clip(Lc * (0.9 + 0.2 * E['bass'][i]), 0, 1), cc


def particles(i, rows, cols):
    """Bubbles: a few always drifting up, a burst on the snare."""
    t = P.t_of(i); out = []
    for (x, y0, v, ph) in BUBBLES:
        y = (y0 - v * t) % E['AH']; xx = x + 6 * math.sin(1.3 * t + ph)
        rr, cc = P.cell(xx, y); out.append((rr, cc, 'o' if v > 22 else '°', (120, 120, 128)))
    if E['snare'][i] > 0.3:
        r = np.random.default_rng(i // 3)
        for _ in range(int(14 * E['snare'][i])):
            rr, cc = P.cell(r.uniform(0, E['AW']), r.uniform(0, E['AH'])); out.append((rr, cc, 'o', (230, 230, 235)))
    return out


def stats(i, sparks):
    return 'fish %d    push %.2f' % (N_FISH, E['kick'][i])


CODE = P.source(__file__)
