"""Math In Time: "what IS an integral?" in 11 bars of Full Ride. Riemann rectangles land on the beat, double on
each bar, melt into the true area on the drop; the derivation, then the answer counted up.
python studio/mathviz/integral.py out.mp4 [--seed N] [--beats 44|24] [--frames a,b,c]

24 beats (kit.short()): the question on frame 0, four rectangles one a beat, then doubling every beat, the melt, the
integral written once and its value counted up, and the answer in words; the antiderivative steps (what the 44-beat
scene spends beats 28-40 on) are left out, since the question is what an integral IS. Loops into frame 0."""
import sys, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

SLUG, B0, SEED = conf('full-ride', 192)
ST = Style(SEED)
SHORT = short(); Q = lambda long, brief: brief if SHORT else long      # a cue in beats: the 44-beat value, the 24-beat value
CL = Clock(SLUG, B0, Q(44, 24), loop=SHORT)
# the title fades; the axes; the first four rectangles (one a beat); n -> infinity; the derivation; the count-up; the answer in words
TITLE, AX, R4, INF, DER, CNT, RES = Q(3.8, 2.4), Q(4, 2.5), Q(12, 7), Q(24, 16), Q(28, 18), Q(36, 19), Q(40, 20.5)
DOUBLE = [(R4 + 4, 8), (R4 + Q(6, 5), 16), (R4 + Q(8, 6), 32), (R4 + Q(10, 7), 64)]   # when each doubling lands: every bar, or every beat
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
HITS = {INF: 1.0, Q(30, 17): 0.5, Q(36, 19): 1.0, Q(42, 22): 0.6}
HITS.update({b: 0.3 for b in CL.snare_beats if INF <= b < INF + Q(4, 2) or CNT <= b < CNT + Q(4, 2)})

def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = BG.copy()
    ax = ease_out((k - AX) / 1.2)
    if ax > 0:                                  # axes grow in
        poly(c, [(X(-0.3), OY), (X(-0.3) + (X(4.5) - X(-0.3)) * ax, OY)], ST.muted, 4)
        poly(c, [(OX, Y(-0.15)), (OX, Y(-0.15) - (Y(-0.15) - Y(2.45)) * ax)], ST.muted, 4)
        for xv in range(1, 5):
            if ax > 0.2 * xv: poly(c, [(X(xv), OY - 10), (X(xv), OY + 10)], ST.muted, 3)
    region = ease_out((k - Q(8, 4.5)) / 1.0)
    n_now = n_drop = 0
    if R4 <= k < R4 + 4: n_now, n_drop = 4, int(k - R4) + 1
    elif k >= R4 + 4 and k < INF + 2: n_now = next(n for b, n in reversed(DOUBLE) if k >= b)
    smooth = ease_out((k - INF) / Q(2.5, 1.5))
    if region > 0 and k < R4 + 0.5: fill(c, REGION, ST.d, 0.30 * region * (1 - ease_out((k - R4) / 0.5)))
    if n_now and smooth < 1:
        dx = (B_ - A_) / n_now; rects = range(n_drop) if n_drop else range(n_now)
        land0 = {n: b for b, n in DOUBLE}.get(n_now, 0)
        boxes = []
        for r in rects:
            x0 = A_ + r * dx; h = f(x0)
            hd = h * float(ease_back((k - (12 + r)) / 0.5)) if n_drop else h * (0.85 + 0.15 * float(ease_back((k - land0) / 0.4)))
            gap = 1.0 if n_now <= 16 else 0.0
            boxes.append([(X(x0) + gap, Y(hd)), (X(x0 + dx) - gap, Y(hd)), (X(x0 + dx) - gap, Y(0)), (X(x0) + gap, Y(0))])
        fill_many(c, boxes, ST.b, 0.40 * (1 - smooth))
        if n_now <= 16: outline_many(c, boxes, mix(ST.b, ST.fg, 0.45), 2)
    if smooth > 0: fill(c, REGION, ST.d, min(0.75, 0.42 * smooth * (1 + 0.35 * kick)))
    cv = float(ease_out((k - AX - 1) / Q(2.2, 1.5)))
    if cv > 0:                                  # the curve, drawn left to right, glowing on the kicks
        m = max(2, int(len(XS) * cv)); poly(c, CURVE[:m], ST.a, 7, glow=(0.5 + 0.8 * kick) * ST.glow)
    bd = float(ease_back((k - Q(8.5, 5)) / 0.6))
    if bd > 0:
        for xv in (A_, B_): poly(c, [(X(xv), Y(0)), (X(xv), Y(0) - (Y(0) - Y(f(xv) + 0.35)) * min(bd, 1))], ST.c, 4)
    # words
    if k < TITLE + 0.8:
        s1 = 1.0; s2 = float(ease_back((k - Q(2, 1.3)) / 0.45)); out_ = 1 - float(ease_out((k - TITLE - 0.3) / 0.45))
        paste(c, tex(r'$\int$', 300, FAINT), W / 2, 830, 1 + 0.05 * kick, out_)
        paste(c, text('What IS an', F(FONT, 96), ST.fg), W / 2, 760, s1, min(1, s1) * out_)
        paste(c, text('integral?', F(FONT, 150), ST.a), W / 2, 905, s2 * (1 + 0.05 * kick), min(1, s2) * out_)
        paste(c, text('calculus in %d seconds' % seconds(CL), F(INTER, 40), ST.muted), W / 2, 1060, 1, float(ease_out((k - Q(3, 1.8)) / 0.5)) * out_)
    if k >= AX:
        up = float(ease_out((k - AX) / 0.8))
        paste(c, text('What IS an integral?', F(FONT, 64), ST.fg), W / 2, 350 - 30 * (1 - up), 1, up)   # under the credit row, even zoomed in
    if AX + 2 <= k: paste(c, tex(r'$f(x) = 1 + x - \frac{x^2}{4}$', 46, ST.hx(ST.a)), W / 2, 540, 1, float(ease_out((k - AX - 2) / 0.6)) * (1 - float(ease_out((k - (DER - 1)) / 1))))
    if Q(9, 5.2) <= k:
        for xv, lab in ((A_, r'$a=0$'), (B_, r'$b=4$')): paste(c, tex(lab, 40, ST.hx(ST.c)), X(xv), Y(0) + 48, 1, float(ease_out((k - Q(9, 5.2)) / 0.5)))
    if R4 - 2 <= k < R4 + 0.2: paste(c, text('area = ?', F(FONT, 90), ST.c), X(2), Y(0.8), float(ease_back((k - R4 + 2) / 0.45)), 1 - float(ease_out((k - R4 + 0.3) / 0.5)))
    chips(c, ST, k, [(R4, R4 + 4, 1, 'slice it into rectangles', ST.b), (R4 + 4, INF, 2, 'double them every %s' % Q('bar', 'beat'), ST.b), (INF, INF + Q(4, 2.5), 3, 'infinitely thin', ST.c)], 440)
    if R4 <= k < INF + 0.2:
        if n_drop: est = sum(f(A_ + r) for r in range(n_drop)); lab = '%d rectangle%s' % (n_drop, 's' if n_drop > 1 else '')
        else: est = left_sum(n_now); lab = '%d rectangles' % n_now
        fade = 1 - float(ease_out((k - (INF - 0.4)) / 0.5))
        paste(c, text(lab, F(INTER, 46), ST.muted), W / 2, 1330, 1, fade)
        paste(c, text('area ≈ %.3f' % est, F(MONO, 92), ST.fg), W / 2, 1440, 1 + 0.05 * kick, fade)
    if DOUBLE[2][0] <= k < INF + 0.2: paste(c, tex(r'$\sum_{i=1}^{n} f(x_i)\,\Delta x$', 62, ST.hx(ST.fg)), W / 2, 1650, float(ease_back((k - DOUBLE[2][0]) / 0.5)), 1 - float(ease_out((k - (INF - 0.4)) / 0.5)))
    if INF <= k < INF + Q(4.5, 2): paste(c, tex(r'$n \to \infty$', 150, ST.hx(ST.c)), W / 2, 1450, float(ease_back((k - INF) / 0.4)) * (1 + 0.06 * kick), 1 - float(ease_out((k - INF - Q(3.6, 1.2)) / 0.8)))
    if DER <= k < RES:
        g = 1 - float(ease_out((k - (RES - 1)) / Q(1, 0.8)))
        if not SHORT: paste(c, tex(r'$\lim_{n\to\infty}\ \sum_{i=1}^{n} f(x_i)\,\Delta x$', 54, ST.hx(ST.fg)), W / 2, 1300, 1, float(ease_out((k - 28) / 0.6)) * (1 - float(ease_out((k - 32) / 0.5))))
        up = 1.0 if SHORT else float(ease_out((k - 32) / 0.6)); e = float(ease_back((k - Q(30, DER)) / 0.5))   # short: the integral is written straight away, where the limit line would have been
        paste(c, tex(r'$= \int_0^4 \left(1 + x - \frac{x^2}{4}\right)\,dx$', 62, ST.hx(ST.fg)), W / 2, 1530 - 190 * up, e, min(1, e) * g)
    if not SHORT and 32 <= k < 40:
        g = 1 - float(ease_out((k - 39) / 1))
        paste(c, tex(r'$= \left[\,x + \frac{x^2}{2} - \frac{x^3}{12}\,\right]_0^4$', 56, ST.hx(ST.fg)), W / 2, 1520, 1, float(ease_out((k - 32.3) / 0.6)) * g)
        paste(c, tex(r'$= 4 + 8 - \frac{16}{3}$', 56, ST.hx(ST.fg)), W / 2, 1670, 1, float(ease_out((k - 34) / 0.6)) * g)
    if CNT <= k:
        cnt = EXACT * float(ease_out((k - CNT) / Q(1.5, 1.2)))
        s = '= 20/3 ≈ %.3f' % (cnt if k < RES else EXACT)
        paste(c, text(s, F(MONO, 84), ST.a), W / 2, Q(1795, 1500) if k < RES else 1360, float(ease_back((k - CNT) / 0.5)) * (1 + 0.05 * kick), 1)
    if RES <= k:
        paste(c, text('add up infinitely many,', F(FONT, 58), ST.fg), W / 2, 1500, 1, float(ease_out((k - RES) / 0.6)))
        paste(c, text('infinitely thin slices.', F(FONT, 58), ST.fg), W / 2, 1580, 1, float(ease_out((k - RES - Q(0.8, 0.6)) / 0.6)))
        e = float(ease_back((k - RES - Q(2, 1.4)) / 0.5)); paste(c, text("that's an integral.", F(FONT, 76), ST.a), W / 2, 1700, e, min(1, e))
    amp, ph = shake_at(k, HITS, ST)
    zoom = 1 + 0.05 * float(ease_in_out((k - R4) / (INF - R4))) * (1 - float(ease_in_out((k - INF) / Q(3, 2)))) + 0.010 * kick
    o = finish(c, k, amp, ph, zoom, X(2), Y(0.9), ST)
    return overlay_fixed(o, ST, k, CL.beats, CREDIT)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
