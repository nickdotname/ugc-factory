"""ASCII scene (colour): fireworks over a city by a river. A rocket goes up on the kick and bursts in a shell of
sparks that fall and fade; the snare sets off a smaller crackle. The skyline's windows glow and the river below
shows it all again, broken up by the water."""
import math
import numpy as np
import paint as P
from paint import E

FILE = 'fireworks.py'
# ----
COLOURS = [(255, 90, 90), (255, 200, 60), (120, 220, 255), (190, 120, 255), (120, 255, 150), (255, 140, 220)]
RISE, LIFE, G, DRAG = 0.7, 2.2, 160.0, 1.4     # seconds up, seconds of sparks, gravity px/s², air drag
SHELLS, BUILDINGS = [], []


def setup(e):
    P.setup(e); r = np.random.default_rng(31); AW, AH = E['AW'], E['AH']
    kicks = list(e['kicks']); snares = list(e.get('snares', []))
    last = -99
    for f in kicks:                                    # a rocket on the kick, at most one every 0.45 s
        if f - last < 13: continue
        last = f
        SHELLS.append(dict(f=f, x=r.uniform(0.15, 0.85) * AW, h=AH * r.uniform(0.12, 0.38), n=int(r.integers(55, 90)),
                           v=r.uniform(150, 230), col=COLOURS[int(r.integers(len(COLOURS)))], seed=int(r.integers(1e6)), big=True))
    for f in snares[::2]:                              # a crackle on every other snare
        SHELLS.append(dict(f=f, x=r.uniform(0.1, 0.9) * AW, h=AH * r.uniform(0.25, 0.5), n=24, v=90.0,
                           col=(255, 240, 200), seed=int(r.integers(1e6)), big=False))
    x = 0
    while x < AW:                                      # the skyline
        w = r.uniform(40, 110); BUILDINGS.append((x, w, AH * r.uniform(0.60, 0.74), int(r.integers(1e6)))); x += w + r.uniform(0, 8)


def sparks(i):
    """Every spark alive at frame i: (x, y, brightness 0..1, colour)."""
    out = []; t = i / 30.0; base = E['AH'] * 0.86
    for s in SHELLS:
        dt = t - s['f'] / 30.0 - (RISE if s['big'] else 0)
        if s['big'] and -RISE <= dt < 0:                # the rocket climbing, with a short trail
            u = (dt + RISE) / RISE; y = base - (base - s['h']) * (1 - (1 - u) ** 2)
            for k in range(4): out.append((s['x'], y + 10 * k, 0.9 - 0.2 * k, (255, 230, 180)))
        if not 0 <= dt < LIFE: continue
        r = np.random.default_rng(s['seed']); n = s['n']
        a = r.uniform(0, 2 * math.pi, n); z = r.uniform(-1, 1, n)
        sp = s['v'] * np.sqrt(1 - z ** 2) * r.uniform(0.85, 1.1, n)
        k = (1 - math.exp(-DRAG * dt)) / DRAG
        for back in (0.0, 0.05, 0.1):                   # each spark and two fainter steps behind it: a short tail
            tt = max(0.0, dt - back); kk = (1 - math.exp(-DRAG * tt)) / DRAG
            xs = s['x'] + np.cos(a) * sp * kk; ys = s['h'] + np.sin(a) * sp * kk + 0.5 * G * tt * tt * 0.6
            fade = max(0.0, 1 - dt / LIFE) ** 1.5 * (1 - 4 * back)
            for x, y in zip(xs, ys): out.append((x, y, fade, s['col']))
    return out


def image(i):
    t = P.t_of(i); X, Y, AW, AH = E['X'], E['Y'], E['AW'], E['AH']
    river = AH * 0.80
    sp = sparks(i); flash = min(1.0, sum(b for _, _, b, _ in sp) / 400)
    rgb = P.lerp((6, 6, 20), (26, 16, 46), Y / river) + np.float32([40, 30, 50]) * flash
    L = 0.03 + 0.05 * flash + 0 * Y
    for (bx, bw, top, seed) in BUILDINGS:              # the skyline, windows lit
        m = (X >= bx) & (X < bx + bw) & (Y >= top) & (Y < river)
        win = m & ((X - bx) % 14 < 6) & ((Y - top) % 22 < 9) & (np.sin((X // 14) * 12.9 + (Y // 22) * 78.2 + seed) > 0.1)
        L = np.where(m, 0.09, L); rgb = np.where(m[..., None], np.float32([22, 22, 40]), rgb)
        L = np.where(win, 0.42, L); rgb = np.where(win[..., None], np.float32([255, 205, 120]), rgb)
    for (x, y, b, col) in sp:                          # the sparks
        r, c = P.cell(x, y)
        if 0 <= r < E['rows'] and 0 <= c < E['cols'] and Y[r, c] < river:
            if b > L[r, c]: L[r, c] = b; rgb[r, c] = col
    wet = Y >= river                                   # the river: everything above, upside down and rippling
    sy = (2 * river - Y + 5 * np.sin(Y / 4 + 3 * t)).clip(0, river - 1)
    sx = (X + 10 * np.sin(Y / 7 - 2 * t)).clip(0, AW - 1)
    ri, ci = (sy // E['ch']).astype(int), (sx // E['cw']).astype(int)
    L = np.where(wet, L[ri, ci] * 0.55 * (0.6 + 0.4 * np.sin(Y / 2.5 + X / 30 - 4 * t) ** 2), L)
    rgb = np.where(wet[..., None], rgb[ri, ci] * 0.7, rgb)
    return L, rgb


def particles(i, rows, cols): return []


def stats(i, sparks_):
    t = i / 30.0
    up = sum(1 for s in SHELLS if s['f'] / 30.0 <= t)
    return 'launched %d   sparks %s' % (up, format(len(sparks(i)), ','))


CODE = P.source(__file__)
