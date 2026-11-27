"""Math In Time: "what IS a derivative?" over Suspended. A secant through two points, h halves on the beat,
the second point slides in, and on "...you call me professor" h hits 0: the secant snaps to the tangent.
python studio/mathviz/derivative.py out.mp4 [--seed N] [--frames a,b,c]"""
import sys, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

SLUG, B0, SEED = conf('suspended', 188)
ST = Style(SEED)
CL = Clock(SLUG, B0, 44)
CREDIT = credit(SLUG)
f = lambda x: x ** 3 / 3 - x
df = lambda x: x * x - 1
X0 = 1.5; SLOPE = df(X0)
OX, OY, SX, SY = 522, 975, 185, 185
X = lambda x: OX + x * SX; Y = lambda y: OY - y * SY
XL, XR, YB, YT = -2.4, 2.6, -1.6, 3.0
XS = np.linspace(XL, XR, 500); CURVE = np.stack([X(XS), Y(f(XS))], 1)
ok = (f(XS) > YB) & (f(XS) < YT + 0.3)
BG = background(ST); FONT = FONTS[ST.font]
def mix(c1, c2, t): return tuple(int(a * (1 - t) + b * t) for a, b in zip(c1, c2))
HITS = {24: 0.4, 32: 1.0, 36: 0.6, 40: 0.4}
HITS.update({b: 0.25 for b in CL.snare_beats if 32 <= b < 36})

HALVE = [16, 18, 20, 22, 24, 26]                      # h halves on these beats, then melts to 0 by beat 32
def h_at(k):
    if k < 28:
        n = sum(1 for b in HALVE if k >= b); h_prev = 0.5 ** max(0, n - 1); h_new = 0.5 ** n
        if n == 0: return 1.0
        return h_prev + (h_new - h_prev) * float(ease_out((k - HALVE[n - 1]) / 0.45))
    return 0.5 ** 6 * (1 - float(ease_in_out((k - 28) / 4)))

def line_through(c, x, y, m, color, width, glow=0.0):
    """A straight line of slope m through (x, y), clipped to the plot."""
    xs = np.array([XL, XR]); ys = y + m * (xs - x)
    if abs(m) > 1e-9:                                   # trim to the plot's top and bottom
        lo, hi = sorted([x + (YB - y) / m, x + (YT - y) / m]); xs = np.clip(xs, max(XL, lo), min(XR, hi)); ys = y + m * (xs - x)
    poly(c, np.stack([X(xs), Y(ys)], 1), color, width, glow=glow)

def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = BG.copy()
    ax = float(ease_out((k - 4) / 1.2))
    if ax > 0:
        poly(c, [(X(XL), OY), (X(XL) + (X(XR) - X(XL)) * ax, OY)], ST.muted, 4)
        poly(c, [(OX, Y(YB)), (OX, Y(YB) - (Y(YB) - Y(YT)) * ax)], ST.muted, 4)
    cv = float(ease_out((k - 5) / 2.0))
    if cv > 0:
        idx = np.nonzero(ok)[0]; m = max(2, int(len(idx) * cv)); poly(c, CURVE[idx[:m]], ST.a, 7, glow=(0.5 + 0.7 * kick) * ST.glow)
    h = h_at(k); P = (X0, f(X0)); Q = (X0 + h, f(X0 + h))
    sec = (Q[1] - P[1]) / h if h > 1e-6 else SLOPE
    tan_ = float(ease_out((k - 32) / 0.35))
    if 8.5 <= k:
        a_ = float(ease_out((k - 8.5) / 0.6))
        m_ = sec + (SLOPE - sec) * tan_
        col = ST.b if tan_ < 0.5 else ST.c
        if a_ > 0.02: line_through(c, P[0], P[1], m_, col, 5 if tan_ < 0.5 else 6, glow=(0.6 + 0.8 * kick) * tan_ * ST.glow)
        if k < 32.3 and h > 0.004:                     # the run, h, under the two points
            yb = Y(min(P[1], Q[1])) + 0 * 1; poly(c, [(X(P[0]), Y(P[1])), (X(Q[0]), Y(P[1]))], mix(ST.bg, ST.fg, 0.6), 3)
            poly(c, [(X(Q[0]), Y(P[1])), (X(Q[0]), Y(Q[1]))], mix(ST.bg, ST.fg, 0.6), 3)
            paste(c, tex(r'$h$', 44, ST.hx(ST.fg)), (X(P[0]) + X(Q[0])) / 2, Y(P[1]) + 34, 1, a_ * min(1, (X(Q[0]) - X(P[0])) / 40))
        if k < 32.3: circle(c, (X(Q[0]), Y(Q[1])), 11 * (1 + 0.15 * kick), ST.b, -1)
    if 7 <= k:
        e = float(ease_back((k - 7) / 0.45)); circle(c, (X(P[0]), Y(P[1])), 12 * e * (1 + 0.15 * kick), ST.c, -1)
    # words
    if k < 4.6:
        o_ = 1 - float(ease_out((k - 4.1) / 0.45)); s1 = 1.0; s2 = float(ease_back((k - 2) / 0.45))
        paste(c, tex(r'$\frac{d}{dx}$', 230, ST.hx(mix(ST.bg, ST.fg, 0.16))), W / 2, 830, 1 + 0.05 * kick, o_)
        paste(c, text('What IS a', F(FONT, 96), ST.fg), W / 2, 760, s1, min(1, s1) * o_)
        paste(c, text('derivative?', F(FONT, 140), ST.a), W / 2, 905, s2 * (1 + 0.05 * kick), min(1, s2) * o_)
        paste(c, text('the slope, in %d seconds' % seconds(CL), F(INTER, 40), ST.muted), W / 2, 1060, 1, float(ease_out((k - 3) / 0.5)) * o_)
    if k >= 4:
        up = float(ease_out((k - 4) / 0.8)); paste(c, text('What IS a derivative?', F(FONT, 64), ST.fg), W / 2, 360 - 30 * (1 - up), 1, up)   # under the credit row, even zoomed in
    if 6 <= k < 17: paste(c, tex(r'$f(x) = \frac{x^3}{3} - x$', 46, ST.hx(ST.a)), X(-1.3), Y(2.1), 1, float(ease_out((k - 6) / 0.6)) * (1 - float(ease_out((k - 16) / 0.8))))
    chips(c, ST, k, [(8, 16, 1, 'pick a 2nd point, h away', ST.b), (16, 28, 2, 'halve h on every beat', ST.b), (28, 36, 3, 'let h hit zero', ST.c)], 450)
    if 10 <= k < 32.2:
        fade = 1 - float(ease_out((k - 31.8) / 0.4)); e = float(ease_out((k - 10) / 0.5))
        paste(c, tex(r'$\mathrm{slope} = \frac{f(x+h) - f(x)}{h}$', 58, ST.hx(ST.fg)), W / 2, 1390, 1, e * fade)
        paste(c, text('h = %s' % ('%.4f' % h if h < 0.1 else '%.3f' % h), F(MONO, 64), ST.muted), W / 2, 1540, 1, e * fade * (1 - float(ease_out((k - 28) / 0.3))))
        paste(c, text('slope ≈ %.4f' % sec, F(MONO, 88), ST.fg), W / 2, 1650, 1 + 0.05 * kick, e * fade)
    if 28 <= k < 32.4: paste(c, tex(r'$h \to 0$', 110, ST.hx(ST.c)), W / 2, 1525, float(ease_back((k - 28) / 0.45)) * (1 + 0.06 * kick), 1 - float(ease_out((k - 32) / 0.4)))
    if 32 <= k < 40:
        g = 1 - float(ease_out((k - 39.4) / 0.6)); e = float(ease_back((k - 32) / 0.45))
        paste(c, tex(r"$f\,'(x) = \lim_{h\to 0}\ \frac{f(x+h) - f(x)}{h}$", 60, ST.hx(ST.fg)), W / 2, 1400, e, min(1, e) * g)
        paste(c, tex(r"$= x^2 - 1$", 64, ST.hx(ST.fg)), W / 2, 1560, 1, float(ease_out((k - 34) / 0.5)) * g)
    if 36 <= k:
        cnt = SLOPE * float(ease_out((k - 36) / 1.4))
        paste(c, text("f'(1.5) = %.2f" % (cnt if k < 40 else SLOPE), F(MONO, 84), ST.c), W / 2, 1710 if k < 40 else 1380, float(ease_back((k - 36) / 0.5)) * (1 + 0.05 * kick), 1)
    if 40 <= k:
        paste(c, text('the slope at one instant,', F(FONT, 58), ST.fg), W / 2, 1520, 1, float(ease_out((k - 40) / 0.6)))
        paste(c, text('not between two points.', F(FONT, 58), ST.fg), W / 2, 1600, 1, float(ease_out((k - 40.8) / 0.6)))
        e = float(ease_back((k - 42) / 0.5)); paste(c, text("that's a derivative.", F(FONT, 76), ST.a), W / 2, 1720, e, min(1, e))
    amp, ph = shake_at(k, HITS, ST)
    zoom = 1 + 0.07 * float(ease_in_out((k - 16) / 12)) * (1 - float(ease_in_out((k - 32) / 3))) + 0.010 * kick
    o = finish(c, k, amp, ph, zoom, X(X0), Y(f(X0)), ST)
    return overlay_fixed(o, ST, k, CL.beats, CREDIT)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
