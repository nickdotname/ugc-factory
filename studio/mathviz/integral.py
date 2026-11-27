"""Math In Time: "what IS an integral?" in 11 bars of Full Ride. Riemann rectangles land on the beat, double on
each bar, melt into the true area on the drop; the derivation, then the answer counted up.
python studio/mathviz/integral.py out.mp4 [--seed N] [--frames a,b,c]"""
import sys, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

SLUG, B0, SEED = conf('full-ride', 192)
ST = Style(SEED)
CL = Clock(SLUG, B0, 44)
CREDIT = credit(SLUG)

f = lambda x: 1 + x - x * x / 4                 # a hill: 1 at both ends, 2 at the top
A_, B_ = 0.0, 4.0; EXACT = 20 / 3
def left_sum(n): dx = (B_ - A_) / n; return sum(f(A_ + j * dx) for j in range(n)) * dx
OX, OY, SX, SY = 150, 1160, 195, 255
X = lambda x: OX + x * SX; Y = lambda y: OY - y * SY
XS = np.linspace(A_, B_, 400)
CURVE = np.stack([X(XS), Y(f(XS))], 1)
REGION = np.concatenate([CURVE, [[X(B_), Y(0)], [X(A_), Y(0)]]])
BG = background(ST)
FONT = FONTS[ST.font]
def mix(c1, c2, t): return tuple(int(a * (1 - t) + b * t) for a, b in zip(c1, c2))
FAINT = ST.hx(mix(ST.bg, ST.fg, 0.16))
HITS = {24: 1.0, 30: 0.5, 36: 1.0, 42: 0.6}
HITS.update({b: 0.3 for b in CL.snare_beats if 24 <= b < 28 or 36 <= b < 40})

def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = BG.copy()
    ax = ease_out((k - 4) / 1.2)
    if ax > 0:                                  # axes grow in
        poly(c, [(X(-0.3), OY), (X(-0.3) + (X(4.5) - X(-0.3)) * ax, OY)], ST.muted, 4)
        poly(c, [(OX, Y(-0.15)), (OX, Y(-0.15) - (Y(-0.15) - Y(2.45)) * ax)], ST.muted, 4)
        for xv in range(1, 5):
            if ax > 0.2 * xv: poly(c, [(X(xv), OY - 10), (X(xv), OY + 10)], ST.muted, 3)
    region = ease_out((k - 8) / 1.0)
    n_now = n_drop = 0
    if 12 <= k < 16: n_now, n_drop = 4, int(k - 12) + 1
    elif 16 <= k < 18: n_now = 8
    elif 18 <= k < 20: n_now = 16
    elif 20 <= k < 22: n_now = 32
    elif 22 <= k < 26: n_now = 64
    smooth = ease_out((k - 24) / 2.5)
    if region > 0 and k < 12.5: fill(c, REGION, ST.d, 0.30 * region * (1 - ease_out((k - 12) / 0.5)))
    if n_now and smooth < 1:
        dx = (B_ - A_) / n_now; rects = range(n_drop) if n_drop else range(n_now)
        land0 = {8: 16, 16: 18, 32: 20, 64: 22}.get(n_now, 0)
        boxes = []
        for r in rects:
            x0 = A_ + r * dx; h = f(x0)
            hd = h * float(ease_back((k - (12 + r)) / 0.5)) if n_drop else h * (0.85 + 0.15 * float(ease_back((k - land0) / 0.4)))
            gap = 1.0 if n_now <= 16 else 0.0
            boxes.append([(X(x0) + gap, Y(hd)), (X(x0 + dx) - gap, Y(hd)), (X(x0 + dx) - gap, Y(0)), (X(x0) + gap, Y(0))])
        fill_many(c, boxes, ST.b, 0.40 * (1 - smooth))
        if n_now <= 16: outline_many(c, boxes, mix(ST.b, ST.fg, 0.45), 2)
    if smooth > 0: fill(c, REGION, ST.d, min(0.75, 0.42 * smooth * (1 + 0.35 * kick)))
    cv = float(ease_out((k - 5) / 2.2))
    if cv > 0:                                  # the curve, drawn left to right, glowing on the kicks
        m = max(2, int(len(XS) * cv)); poly(c, CURVE[:m], ST.a, 7, glow=(0.5 + 0.8 * kick) * ST.glow)
    bd = float(ease_back((k - 8.5) / 0.6))
    if bd > 0:
        for xv in (A_, B_): poly(c, [(X(xv), Y(0)), (X(xv), Y(0) - (Y(0) - Y(f(xv) + 0.35)) * min(bd, 1))], ST.c, 4)
    # words
    if k < 4.6:
        s1 = 1.0; s2 = float(ease_back((k - 2) / 0.45)); out_ = 1 - float(ease_out((k - 4.1) / 0.45))
        paste(c, tex(r'$\int$', 300, FAINT), W / 2, 830, 1 + 0.05 * kick, out_)
        paste(c, text('What IS an', F(FONT, 96), ST.fg), W / 2, 760, s1, min(1, s1) * out_)
        paste(c, text('integral?', F(FONT, 150), ST.a), W / 2, 905, s2 * (1 + 0.05 * kick), min(1, s2) * out_)
        paste(c, text('calculus in %d seconds' % seconds(CL), F(INTER, 40), ST.muted), W / 2, 1060, 1, float(ease_out((k - 3) / 0.5)) * out_)
    if k >= 4:
        up = float(ease_out((k - 4) / 0.8))
        paste(c, text('What IS an integral?', F(FONT, 64), ST.fg), W / 2, 350 - 30 * (1 - up), 1, up)   # under the credit row, even zoomed in
    if 6 <= k: paste(c, tex(r'$f(x) = 1 + x - \frac{x^2}{4}$', 46, ST.hx(ST.a)), W / 2, 540, 1, float(ease_out((k - 6) / 0.6)) * (1 - float(ease_out((k - 27) / 1))))
    if 9 <= k:
        for xv, lab in ((A_, r'$a=0$'), (B_, r'$b=4$')): paste(c, tex(lab, 40, ST.hx(ST.c)), X(xv), Y(0) + 48, 1, float(ease_out((k - 9) / 0.5)))
    if 10 <= k < 12.2: paste(c, text('area = ?', F(FONT, 90), ST.c), X(2), Y(0.8), float(ease_back((k - 10) / 0.45)), 1 - float(ease_out((k - 11.7) / 0.5)))
    chips(c, ST, k, [(12, 16, 1, 'slice it into rectangles', ST.b), (16, 24, 2, 'double them every bar', ST.b), (24, 28, 3, 'infinitely thin', ST.c)], 440)
    if 12 <= k < 24.2:
        if n_drop: est = sum(f(A_ + r) for r in range(n_drop)); lab = '%d rectangle%s' % (n_drop, 's' if n_drop > 1 else '')
        else: est = left_sum(n_now); lab = '%d rectangles' % n_now
        fade = 1 - float(ease_out((k - 23.6) / 0.5))
        paste(c, text(lab, F(INTER, 46), ST.muted), W / 2, 1330, 1, fade)
        paste(c, text('area ≈ %.3f' % est, F(MONO, 92), ST.fg), W / 2, 1440, 1 + 0.05 * kick, fade)
    if 20 <= k < 24.2: paste(c, tex(r'$\sum_{i=1}^{n} f(x_i)\,\Delta x$', 62, ST.hx(ST.fg)), W / 2, 1650, float(ease_back((k - 20) / 0.5)), 1 - float(ease_out((k - 23.6) / 0.5)))
    if 24 <= k < 28.5: paste(c, tex(r'$n \to \infty$', 150, ST.hx(ST.c)), W / 2, 1450, float(ease_back((k - 24) / 0.4)) * (1 + 0.06 * kick), 1 - float(ease_out((k - 27.6) / 0.8)))
    if 28 <= k < 40:
        g = 1 - float(ease_out((k - 39) / 1))
        paste(c, tex(r'$\lim_{n\to\infty}\ \sum_{i=1}^{n} f(x_i)\,\Delta x$', 54, ST.hx(ST.fg)), W / 2, 1300, 1, float(ease_out((k - 28) / 0.6)) * (1 - float(ease_out((k - 32) / 0.5))))
        up = float(ease_out((k - 32) / 0.6)); e = float(ease_back((k - 30) / 0.5))
        paste(c, tex(r'$= \int_0^4 \left(1 + x - \frac{x^2}{4}\right)\,dx$', 62, ST.hx(ST.fg)), W / 2, 1530 - 190 * up, e, min(1, e) * g)
    if 32 <= k < 40:
        g = 1 - float(ease_out((k - 39) / 1))
        paste(c, tex(r'$= \left[\,x + \frac{x^2}{2} - \frac{x^3}{12}\,\right]_0^4$', 56, ST.hx(ST.fg)), W / 2, 1520, 1, float(ease_out((k - 32.3) / 0.6)) * g)
        paste(c, tex(r'$= 4 + 8 - \frac{16}{3}$', 56, ST.hx(ST.fg)), W / 2, 1670, 1, float(ease_out((k - 34) / 0.6)) * g)
    if 36 <= k:
        cnt = EXACT * float(ease_out((k - 36) / 1.5))
        s = '= 20/3 ≈ %.3f' % (cnt if k < 40 else EXACT)
        paste(c, text(s, F(MONO, 84), ST.a), W / 2, 1795 if k < 40 else 1360, float(ease_back((k - 36) / 0.5)) * (1 + 0.05 * kick), 1)
    if 40 <= k:
        paste(c, text('add up infinitely many,', F(FONT, 58), ST.fg), W / 2, 1500, 1, float(ease_out((k - 40) / 0.6)))
        paste(c, text('infinitely thin slices.', F(FONT, 58), ST.fg), W / 2, 1580, 1, float(ease_out((k - 40.8) / 0.6)))
        e = float(ease_back((k - 42) / 0.5)); paste(c, text("that's an integral.", F(FONT, 76), ST.a), W / 2, 1700, e, min(1, e))
    amp, ph = shake_at(k, HITS, ST)
    zoom = 1 + 0.05 * float(ease_in_out((k - 12) / 12)) * (1 - float(ease_in_out((k - 24) / 3))) + 0.010 * kick
    o = finish(c, k, amp, ph, zoom, X(2), Y(0.9), ST)
    return overlay_fixed(o, ST, k, CL.beats, CREDIT)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
