"""Helpers for the colour scenes (aurora.py, daisies.py, galaxy.py, fireworks.py): each paints, per letter cell, a
brightness L (0..1, which letter) and a colour (rgb, 0..255). Coordinates are in pixels of the 1080-wide art."""
import math
import numpy as np

E = {}


def setup(e):
    E.update(e)
    R, C, cw, ch = e['rows'], e['cols'], e['cw'], e['ch']
    y, x = np.mgrid[0:R, 0:C].astype(np.float32)
    E['X'] = (x + 0.5) * cw; E['Y'] = (y + 0.5) * ch; E['AW'] = C * cw; E['AH'] = R * ch


def t_of(i): return E['t0'] + i / 30.0


def lerp(a, b, u):
    u = np.clip(u, 0, 1)[..., None]
    return np.array(a, np.float32) * (1 - u) + np.array(b, np.float32) * u


def ramp3(c0, c1, c2, u):
    """Colour along three stops, u in 0..1."""
    u = np.clip(u, 0, 1)
    return np.where((u < 0.5)[..., None], lerp(c0, c1, u * 2), lerp(c1, c2, u * 2 - 1))


def waves(x, y, t, n=5, seed=0, scale=200.0):
    """Smooth moving noise from a few travelling waves (cheap, and the same every run for a seed)."""
    r = np.random.default_rng(seed); out = np.zeros_like(x)
    for k in range(n):
        a = r.uniform(0, 2 * math.pi); f = r.uniform(0.6, 1.6) * (2 ** (k * 0.5)) / scale; sp = r.uniform(-0.6, 0.6)
        out += np.sin((x * math.cos(a) + y * math.sin(a)) * f + sp * t + r.uniform(0, 6.28)) / (1 + k * 0.6)
    return out / 2.2


def stars(n, seed, ymax):
    r = np.random.default_rng(seed)
    return [(r.uniform(0, E['AW']), r.uniform(0, ymax), r.uniform(0, 1), r.uniform(0, 6.28)) for _ in range(n)]


def cell(px, py):
    """The letter cell (row, col) a pixel falls in."""
    return int(py // E['ch']), int(px // E['cw'])


def source(path):
    """The scene's own source, shown in the editor panel: what is on screen is what draws it."""
    return open(path).read().split('\n# ----\n', 1)[-1]
