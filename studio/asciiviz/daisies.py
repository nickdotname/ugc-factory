"""ASCII scene (colour): a field of daisies at night under a full moon. The flowers nod on the kick and sway in the
wind, nearer ones bigger; fireflies drift over the grass and flash on the snare."""
import math
import numpy as np
import paint as P
from paint import E

FILE = 'daisies.py'
# ----
N_DAISIES, N_FLIES = 52, 26
FLOWERS, FLIES, STARS = [], [], []


def setup(e):
    P.setup(e); r = np.random.default_rng(5); AH = E['AH']
    for _ in range(N_DAISIES):
        d = r.uniform(0, 1) ** 0.7                   # depth: 0 far, 1 near
        FLOWERS.append((r.uniform(-20, E['AW'] + 20), AH * (0.50 + 0.47 * d), d, r.uniform(0, 6.28), r.integers(9, 14)))
    FLOWERS.sort(key=lambda f: f[2])                 # far ones first, near ones on top
    for _ in range(N_FLIES):
        FLIES.append((r.uniform(0, E['AW']), AH * r.uniform(0.46, 0.92), r.uniform(0, 6.28), r.uniform(0.3, 1)))
    STARS[:] = P.stars(150, 3, AH * 0.40)


def image(i):
    t = P.t_of(i); X, Y, AW, AH = E['X'], E['Y'], E['AW'], E['AH']
    kick = E['kick'][i]; wind = 0.6 * math.sin(0.7 * t)
    horizon = AH * 0.47
    # sky: deep blue to violet at the horizon, and the moon with its halo
    rgb = P.lerp((6, 10, 36), (48, 36, 96), Y / horizon); L = 0.04 + 0.06 * Y / horizon
    mx, my, mr = AW * 0.72, AH * 0.15, 52.0
    d = np.hypot(X - mx, (Y - my) * 1.0)
    halo = np.exp(-np.maximum(d - mr, 0) / 70) * (0.5 + 0.2 * E['vox'][i])
    L = np.maximum(L, np.where(d < mr, 0.95 - 0.25 * (np.sin(X / 13) * np.sin(Y / 9) > 0.55), halo * 0.55))
    rgb = np.where((d < mr)[..., None], np.float32([250, 245, 220]), rgb + np.float32([120, 110, 160]) * halo[..., None])
    # the tree line on the horizon
    trees = horizon - 26 - 22 * np.abs(np.sin(X / 37)) - 14 * np.abs(np.sin(X / 13 + 1))
    tl = (Y > trees) & (Y < horizon + 4)
    L = np.where(tl, 0.07, L); rgb = np.where(tl[..., None], np.float32([18, 28, 40]), rgb)
    # grass: blades leaning in the wind, lit by the moon at the top
    g = Y >= horizon
    blade = np.sin((X + wind * (Y - horizon) * 0.3) / 5.0 + np.sin(Y / 17) * 2)
    depth = (Y - horizon) / (AH - horizon)
    L = np.where(g, 0.10 + 0.14 * (blade > 0.2) * (0.5 + depth), L)
    rgb = np.where(g[..., None], P.lerp((30, 70, 50), (60, 150, 80), depth) * (0.8 + 0.3 * (blade > 0.2))[..., None], rgb)
    # the daisies, far to near
    for (fx, fy, dp, ph, petals) in FLOWERS:
        r = 7 + 48 * dp ** 1.6
        sway = (6 + 10 * dp) * math.sin(1.3 * t + ph) * (0.6 + wind) + 8 * dp * kick
        cx, cy = fx + sway, fy - r * 0.2 - 10 * kick * dp
        x0, x1 = int(max(0, (cx - r * 1.3) // E['cw'])), int(min(E['cols'], (cx + r * 1.3) // E['cw'] + 1))
        y0, y1 = int(max(0, (cy - r) // E['ch'])), int(min(E['rows'], (fy + 40 * dp) // E['ch'] + 1))
        if x1 <= x0 or y1 <= y0: continue
        sx, sy = X[y0:y1, x0:x1] - cx, (Y[y0:y1, x0:x1] - cy) / (0.55 + 0.25 * dp)   # seen from above at an angle
        rr = np.hypot(sx, sy); th = np.arctan2(sy, sx) + 0.3 * math.sin(t + ph)
        petal = (rr < r * (0.55 + 0.45 * np.abs(np.cos(petals * th / 2)))) & (rr > r * 0.28)
        centre = rr <= r * 0.3
        stem = (np.abs(X[y0:y1, x0:x1] - (fx + sway * (1 - (Y[y0:y1, x0:x1] - cy) / max(1, fy + 40 * dp - cy)))) < 1.5 + 2 * dp) & (Y[y0:y1, x0:x1] > cy)
        Ls, Cs = L[y0:y1, x0:x1], rgb[y0:y1, x0:x1]
        Ls[stem] = 0.22; Cs[stem] = (70, 140, 70)
        lit = 0.55 + 0.4 * dp
        Ls[petal] = lit; Cs[petal] = (240, 240, 250)
        Ls[centre] = lit * 0.9; Cs[centre] = (255, 200, 40)
    return L, rgb


def particles(i, rows, cols):
    t = P.t_of(i); out = []; flash = E['snare'][i]
    for k, (x, y, ph, b) in enumerate(FLIES):
        fx = x + 40 * math.sin(0.4 * t + ph) + 12 * math.sin(1.7 * t + 2 * ph)
        fy = y + 25 * math.sin(0.6 * t + 1.3 * ph)
        glow = b * (0.5 + 0.5 * math.sin(2.2 * t + 3 * ph)) + flash * (k % 2)
        if glow < 0.35: continue
        r, c = P.cell(fx % E['AW'], fy)
        out.append((r, c, '*' if glow > 0.8 else 'o' if glow > 0.55 else '.', (230, 255, 120)))
    for (x, y, b, ph) in STARS:
        if b * (0.7 + 0.3 * math.sin(2 * t + ph)) > 0.5:
            r, c = P.cell(x, y); out.append((r, c, '.' if b < 0.85 else '+', (220, 225, 255)))
    return out


def stats(i, sparks):
    t = P.t_of(i); lit = sum(1 for k, (x, y, ph, b) in enumerate(FLIES) if b * (0.5 + 0.5 * math.sin(2.2 * t + 3 * ph)) > 0.35)
    return 'daisies %d   moon 100%%   fireflies %d' % (N_DAISIES, lit)


CODE = P.source(__file__)
