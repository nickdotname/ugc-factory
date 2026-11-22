"""ASCII scene (colour): a spiral galaxy turning, seen at an angle. Two arms wind out of a bright core that flares on
the kick; pink star-forming knots dot the arms, dark dust lanes run along their inner edges, and the field of stars
behind twinkles."""
import math
import numpy as np
import paint as P
from paint import E

FILE = 'galaxy.py'
# ----
ARMS, PITCH = 2, 0.28                  # two arms; how tightly they wind
TILT, ANGLE = 0.56, -0.45              # how flat we see it, and its turn on screen
KNOTS, STARS = [], []


def setup(e):
    P.setup(e); r = np.random.default_rng(21)
    for _ in range(90):                # star-forming knots, placed along the arms
        rad = r.uniform(60, 420); arm = r.integers(ARMS)
        KNOTS.append((rad, arm * 2 * math.pi / ARMS + math.log(rad / 40) / PITCH + r.normal(0, 0.12), r.uniform(0.5, 1)))
    STARS[:] = P.stars(320, 8, E['AH'])


def plane(x, y):
    """Screen to the galaxy's own plane: undo the turn and the tilt."""
    cx, cy = E['AW'] / 2, E['AH'] * 0.5
    u, v = x - cx, (y - cy)
    c, s = math.cos(ANGLE), math.sin(ANGLE)
    u, v = u * c - v * s, u * s + v * c
    return u, v / TILT


def image(i):
    t = P.t_of(i); X, Y = E['X'], E['Y']; kick = E['kick'][i]
    u, v = plane(X, Y)
    r = np.hypot(u, v) + 1e-3; th = np.arctan2(v, u)
    spin = 0.05 * t
    phase = ARMS * (th - spin) - ARMS * np.log(r / 40) / PITCH
    arm = 0.5 + 0.5 * np.cos(phase)
    dust = 0.5 + 0.5 * np.cos(phase + 0.9)
    disc = np.exp(-r / 230)
    core = np.exp(-(r / (55 + 25 * kick)) ** 2)
    light = disc * (0.25 + 1.1 * arm ** 3) * (1 - 0.55 * dust ** 6) + 1.2 * core
    L = np.clip(light * (0.9 + 0.25 * E['bass'][i]), 0, 1)
    rgb = P.ramp3((120, 160, 255), (220, 220, 255), (255, 228, 180), np.clip(core * 1.5 + 0.2 * disc, 0, 1))
    rgb = rgb * np.clip(0.35 + light, 0, 1.2)[..., None]
    return L, rgb


def particles(i, rows, cols):
    t = P.t_of(i); out = []
    cx, cy = E['AW'] / 2, E['AH'] * 0.5; c, s = math.cos(-ANGLE), math.sin(-ANGLE)
    for rad, ang, b in KNOTS:          # the knots turn with the galaxy (inner ones faster)
        a = ang + 0.05 * t * (400 / (rad + 150))
        u, v = rad * math.cos(a), rad * math.sin(a) * TILT
        x, y = cx + u * c - v * s, cy + u * s + v * c
        if b * (0.7 + 0.3 * math.sin(3 * t + rad)) > 0.55:
            rr, cc = P.cell(x, y); out.append((rr, cc, '*' if b > 0.85 else 'o', (255, 130, 190)))
    for (x, y, b, ph) in STARS:
        if b * (0.6 + 0.4 * math.sin(2.5 * t + ph)) + 0.3 * E['pulse'][i] * (b > 0.8) > 0.55:
            rr, cc = P.cell(x, y); out.append((rr, cc, '+' if b > 0.9 else '.', (200, 210, 255)))
    return out


def stats(i, sparks):
    t = P.t_of(i)
    return 'arms %d   knots %d   turned %.1f°   ly %s' % (ARMS, len(KNOTS), math.degrees(0.05 * t) % 360, format(105700, ','))


CODE = P.source(__file__)
