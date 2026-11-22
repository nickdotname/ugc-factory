"""ASCII scene (colour): the northern lights over a frozen lake. The curtains ripple with the bass, flare on the kick,
and the lake below shows them back, broken up by the water; stars twinkle on the hi-hats."""
import math
import numpy as np
import paint as P
from paint import E

FILE = 'aurora.py'
# ----
GREEN, TEAL, VIOLET = (70, 255, 160), (60, 200, 255), (210, 90, 255)
SKY_TOP, SKY_LOW = (4, 6, 22), (14, 30, 62)
STARS = []


def setup(e):
    P.setup(e); STARS[:] = P.stars(260, 11, E['AH'] * 0.55)


def curtain(x, y, t, amp):
    """How bright the aurora is at (x, y): a ribbon whose lower edge
    waves across the sky, fading upward, cut into vertical rays."""
    edge = (E['AH'] * 0.43 + 70 * np.sin(x / 170 + 0.30 * t)
            + 34 * np.sin(x / 61 - 0.55 * t) + 16 * np.sin(x / 23 + t))
    up = edge - y                                  # how far above the edge
    body = np.where(up > 0, np.exp(-up / (260 + 60 * amp)), np.exp(up / 9))
    rays = 0.55 + 0.45 * np.sin(x / 7.5 + 2.2 * np.sin(x / 90 + 0.4 * t))
    fold = 0.6 + 0.4 * np.sin(x / 140 - 0.7 * t)
    return np.clip(1.35 * body * rays * fold * amp, 0, 1.2), up


def image(i):
    t = P.t_of(i); X, Y, AH = E['X'], E['Y'], E['AH']
    amp = 0.55 + 0.45 * E['bass'][i] + 0.35 * E['kick'][i]
    lake = AH * 0.70; shore = AH * 0.90
    # the sky, darkest at the top
    rgb = P.lerp(SKY_TOP, SKY_LOW, Y / lake); L = 0.05 + 0.05 * (Y / lake)
    a, up = curtain(X, Y, t, amp)
    col = P.ramp3(GREEN, TEAL, VIOLET, up / 420)
    sky = Y < lake
    L = np.where(sky, np.maximum(L, a * 0.95), L)
    rgb = np.where((sky & (a > 0.04))[..., None], col * np.clip(a * 1.3, 0.4, 1)[..., None] + rgb, rgb)
    # mountains along the far shore
    ridge = lake - 30 - 90 * np.abs(np.sin(X / 260 + 0.6)) - 40 * np.abs(np.sin(X / 97))
    hill = (Y > ridge) & sky
    cap = Y < ridge + 12
    L = np.where(hill, np.where(cap, 0.38, 0.16), L)
    rgb = np.where(hill[..., None], np.where(cap[..., None], np.float32([175, 195, 235]), np.float32([38, 52, 92])), rgb)
    # the lake: the sky upside down, broken by the water
    wet = (Y >= lake) & (Y < shore)
    my = lake - (Y - lake) * 2.4 + 6 * np.sin(Y / 5 + 2 * t)   # a squashed mirror: the far lake shows the sky
    mx = X + 9 * np.sin(Y / 11 - 1.5 * t) * (Y - lake) / (shore - lake)
    ra, rup = curtain(mx, my, t, amp)
    rcol = P.ramp3(GREEN, TEAL, VIOLET, rup / 420)
    ripple = 0.55 + 0.45 * np.sin(Y / 3.0 + X / 40 - 3 * t)
    L = np.where(wet, 0.05 + ra * 0.8 * ripple, L)
    rgb = np.where(wet[..., None], rcol * np.clip(ra * 1.1, 0.2, 1)[..., None] + 8, rgb)
    # snow on the near shore
    snow = Y >= shore
    drift = np.clip(0.10 + 0.14 * np.sin(X / 33 + Y / 9) + 0.1 * np.sin(X / 7.3 - Y / 4.1), 0, 1)
    L = np.where(snow, drift, L)
    rgb = np.where(snow[..., None], np.array((165, 180, 215), np.float32), rgb)
    return L, rgb


def particles(i, rows, cols):
    t = P.t_of(i); out = []
    hat = E['pulse'][i]
    for k, (x, y, b, ph) in enumerate(STARS):
        tw = b * (0.6 + 0.4 * math.sin(3 * t + ph)) + 0.4 * hat * (k % 3 == 0)
        if tw < 0.35: continue
        r, c = P.cell(x, y)
        out.append((r, c, '*' if tw > 0.9 else '+' if tw > 0.6 else '.', (230, 236, 255)))
    return out


def stats(i, sparks):
    amp = 0.55 + 0.45 * E['bass'][i] + 0.35 * E['kick'][i]
    return 'aurora %d   kp %d   stars %d' % (int(900 * amp), int(3 + 5 * amp), len(STARS))


CODE = P.source(__file__)
