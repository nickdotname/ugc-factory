"""ASCII scene (colour): three koi in dark water, set in bold letters big enough to read. Each fish is a real 3D
body (an outline swept round in ovals) with white patches on orange, rows of scales that catch the light, and fins
whose rays are drawn as strokes (//// ||||). The water behind them is letters too: slow bands of light, hatched along
their slope. On every kick the fish push forward (the tails beat harder), the snare sends up bubbles."""
import math
import numpy as np
import paint as P
from paint import E

FILE = 'goldfish.py'
HATCH = (0.08, 0.36)                    # the water and the fins are hatched; the bodies keep their heavy letters
GLOW = 0.5
DOTS = False                            # the water fills the page
ZOOM = 1                                # drawn for the big letters
# ----
SIZES = (640, 400, 320)                 # the fish, nose to tail root, in pixels: with its tail the first fills the page
SS = 4                                   # sub-samples per letter cell, each way
LIGHT = np.array([0.3, 0.8, 0.5]); LIGHT /= np.linalg.norm(LIGHT)      # points away from the light: it comes from above, in front
FISH, BUBBLES = [], []


def body_points(nu=300, nt=170):
    """The body: its side outline swept round in ovals, so it is truly round."""
    u, th = np.meshgrid(np.linspace(0, 1, nu), np.linspace(0, 2 * np.pi, nt, endpoint=False))
    u, th = u.ravel(), th.ravel()
    h = 0.29 * np.sin(np.pi * np.clip(u, 0.002, 1)) ** 0.62 * (1 - 0.38 * u)        # tall in front, thin at the tail
    w = 0.72 * h
    mid = -0.07 * np.sin(np.pi * u)                                                    # a slight hump
    x, y, z = (0.5 - u), mid + h * np.sin(th), w * np.cos(th)
    n = np.stack([0.25 * (u - 0.5), np.sin(th) * w, np.cos(th) * h], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
    # scales: overlapping rows, offset every other row; each scale brighter at its centre
    sr, sc = u * 26, th / (2 * np.pi) * 34
    sc = sc + 0.5 * (np.floor(sr) % 2)
    edge = np.clip(1 - np.hypot(sr % 1 - 0.5, sc % 1 - 0.5) * 1.6, 0, 1)
    side = np.minimum(np.abs(th - (np.pi + 0.3)), np.abs(th - (2 * np.pi - 0.3)))   # one on each side, just above the middle
    eye = np.hypot(u - 0.11, side * 0.11) < 0.036
    # koi markings: white patches on the orange, the same on every fish but shifted along it
    patch = np.sin(u * 9.0 + 1.3 * np.sin(th * 2)) + 0.8 * np.sin(th * 3 + u * 5.0) + 0.5 * np.sin(u * 23.0 + th)
    return np.stack([x, y, z], -1), n, u, edge, eye, patch


def fin_points():
    """The fins: a filled outline with rays drawn on top, ragged at the tips."""
    r = np.random.default_rng(3); pts, wt = [], []
    a, b = np.meshgrid(np.linspace(0, 1, 130), np.linspace(-1, 1, 200)); a, b = a.ravel(), b.ravel()
    ray = np.abs(np.sin(b * 4.5 * np.pi)) ** 8                              # nine rays
    rag = a < 0.60 + 0.40 * np.abs(b) ** 1.4 + 0.05 * np.abs(np.sin(b * 11)) + 0.03 * r.random(a.size)   # a forked tail, ragged at the tips
    tail = np.stack([-0.47 - 0.55 * a, 0.40 * b * (0.10 + a) + 0.05 * np.sin(5 * a + 2 * b) * a, np.zeros_like(a)], -1)   # behind the body (the head is at +x)
    pts.append(tail[rag]); wt.append((0.35 + 0.9 * ray)[rag])
    d = np.stack([0.20 - 0.50 * a * (1 - 0.25 * b) - 0.12 * (b + 1), -0.20 - 0.17 * a * (1 - 0.35 * np.abs(b)), np.zeros_like(a)], -1)   # the fin along the back
    pts.append(d); wt.append(0.25 + 0.6 * ray)
    for side in (-1, 1):                                                    # the pair of fins under the head
        q = np.stack([0.20 - 0.20 * a, 0.10 + 0.17 * a * (0.5 + 0.5 * b), side * (0.13 + 0.09 * a)], -1)
        pts.append(q); wt.append(0.2 + 0.5 * ray)
    return np.concatenate(pts), np.concatenate(wt), np.concatenate([np.full(len(p), k) for k, p in enumerate(pts)])


def setup(e):
    P.setup(e); r = np.random.default_rng(e.get('seed', 7))
    B = body_points(); F = fin_points()
    FISH[:] = []
    up = r.choice([-1, 1]); d0 = r.choice([-1, 1])
    for k, size in enumerate(SIZES):
        d = d0 if k == 0 else r.choice([-1, 1])
        FISH.append(dict(B=B, F=F, dir=d, size=size, speed=r.uniform(42, 60) if k == 0 else r.uniform(60, 90),
                         x0=E['AW'] * (0.5 - 0.25 * d if k == 0 else r.uniform(0, 1)),
                         y0=E['AH'] * (0.5, 0.5 - 0.33 * up, 0.5 + 0.34 * up)[k], z0=(0, 220, 320)[k], ph=r.uniform(0, 6.28), beat=r.uniform(4.5, 6.5),
                         mark=r.uniform(0, 6.28), white=r.uniform(0.3, 0.9)))
    BUBBLES[:] = [(r.uniform(0, E['AW']), r.uniform(0, E['AH']), r.uniform(12, 30), r.uniform(0, 6.28)) for _ in range(16)]


def swim(f, t, push):
    """Where a fish is and which way it faces: a wandering path, faster on the kick."""
    pad = f['size'] * 1.1; span = E['AW'] + 2 * pad
    x = (f['x0'] + f['dir'] * (f['speed'] * (t - E['t0']) + 60 * push) + pad) % span - pad
    y = f['y0'] + 40 * math.sin(0.45 * t + f['ph'])
    z = f['z0'] + 90 * math.sin(0.3 * t + 2 * f['ph'])
    yaw = math.atan2(27 * math.cos(0.3 * t + 2 * f['ph']), f['speed']) * f['dir'] + (0 if f['dir'] > 0 else math.pi)
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


def water(t, h, w):
    """The water: slow bands of light coming down from the surface, dimmer with depth."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32); x *= E['AW'] / w; y *= E['AH'] / h
    band = P.waves(x + 0.35 * y, y * 0.5, t, n=4, seed=11, scale=260.0) + 0.5 * P.waves(x - 0.6 * y, y, t, n=3, seed=5, scale=120.0)
    L = np.clip(0.17 + 0.11 * band - 0.05 * y / E['AH'], 0.09, 0.30)
    return L, P.ramp3((40, 58, 98), (52, 90, 130), (104, 150, 176), (L - 0.09) / 0.21)


def image(i, full=False):
    t = P.t_of(i); push = float(E['kick'][i]); R, C = E['rows'], E['cols']
    h, w = R * SS, C * SS; sx, sy = w / E['AW'], h / E['AH']
    zb = np.full((h, w), 1e9, np.float32); Lb = np.zeros((h, w), np.float32); rgb = np.zeros((h, w, 3), np.float32)
    fin_L = np.zeros((h, w), np.float32); fin_n = np.zeros((h, w), np.float32)
    order = sorted(FISH, key=lambda f: -swim(f, t, push)[2])
    for f in order:
        x, y, z, yaw = swim(f, t, push)
        (bp, bn, bu, edge, eye, patch) = f['B']; (fp, fw, fk) = f['F']
        X, Y, Z, c, s = place(bp, f, t, push, yaw, x, y, z, bu)
        nx, nz = bn[:, 0] * c - bn[:, 2] * s, bn[:, 0] * s + bn[:, 2] * c
        n = np.stack([nx, bn[:, 1], nz], -1)
        dif = np.clip(n @ -LIGHT, 0, 1); spec = np.clip(n @ np.array([0, 0, -1.0]), 0, 1) ** 18
        white = (np.sin(bu * 7.0 + f['mark']) + 0.55 * patch) > 0.9 - f['white']
        # which letter: heavy everywhere on the body (the shade is in the colour), heavier on each scale's centre and in the light
        L = np.clip(0.50 + 0.24 * dif + 0.16 * edge + 0.3 * spec + 0.10 * white, 0, 1)
        shade = np.clip(0.22 + 0.9 * dif ** 0.9 + 0.12 * edge, 0, 1)
        col = np.where(white[:, None], P.ramp3((70, 84, 110), (200, 205, 205), (255, 252, 240), shade),
                       P.ramp3((120, 30, 8), (240, 100, 18), (255, 176, 60), shade)) + P.lerp((0, 0, 0), (255, 240, 190), spec * 0.9)
        L = np.where(eye, 0.0, L)                                           # the eye: a gap in the letters
        ix, iy = (X * sx).astype(int), (Y * sy).astype(int)
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):                    # each point covers 2x2 sub-cells
            jx, jy = ix + dx, iy + dy; ok = (jx >= 0) & (jx < w) & (jy >= 0) & (jy < h)
            o = np.argsort(-Z[ok]); jx, jy, zz = jx[ok][o], jy[ok][o], Z[ok][o]
            near = zz < zb[jy, jx]
            jx, jy, zz = jx[near], jy[near], zz[near]; src = np.flatnonzero(ok)[o][near]
            zb[jy, jx] = zz; Lb[jy, jx] = L[src]; rgb[jy, jx] = col[src]
        fu = np.clip(0.5 - fp[:, 0], 0, 1.6)                              # how far back along the fish: the tail swings most
        X, Y, Z, c, s = place(fp, f, t, push, yaw, x, y, z, fu)
        ix, iy = (X * sx).astype(int), (Y * sy).astype(int); ok = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        np.add.at(fin_L, (iy[ok], ix[ok]), fw[ok]); np.add.at(fin_n, (iy[ok], ix[ok]), 1.0)
    body = zb < 1e9; fin = (fin_n > 0) & ~body
    ray = fin_L / (fin_n + 1e-6)                                            # 0.2 between the rays .. 1.25 on one
    wL, wrgb = water(t, h, w)
    L = np.where(body, Lb, np.where(fin, np.clip(0.12 + 0.24 * ray, 0, 0.42), wL))
    col = np.where(body[..., None], rgb, np.where(fin[..., None], P.lerp((200, 80, 20), (255, 190, 90), ray / 1.25), wrgb))
    if full:                                                                # the whole picture, for letters.py to set in type
        return np.clip(col * (0.55 + 0.6 * L[..., None]) * (0.9 + 0.2 * E['bass'][i]), 0, 255).astype(np.uint8)
    # down to letter cells: a cell that is mostly fish is fish (no half-and-half letters on the outline)
    part = body.reshape(R, SS, C, SS).mean((1, 3)) > 0.45
    def cells(v, m):
        m = m.astype(np.float32); n = m.reshape(R, SS, C, SS).sum((1, 3)) + 1e-6
        if v.ndim == 3: return (v * m[..., None]).reshape(R, SS, C, SS, 3).sum((1, 3)) / n[..., None]
        return (v * m).reshape(R, SS, C, SS).sum((1, 3)) / n
    Lc = np.where(part, cells(L, body), cells(L, ~body)); cc = np.where(part[..., None], cells(col, body), cells(col, ~body))
    return np.clip(Lc, 0, 1), cc * (0.88 + 0.24 * E['bass'][i])          # the bass brightens the colours; the letters hold still


def picture(i):
    return image(i, full=True)


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
    return 'fish %d    push %.2f' % (len(FISH), E['kick'][i])


CODE = P.source(__file__)
