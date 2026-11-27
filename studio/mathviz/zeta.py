"""Math In Time: "this spiral hides a $1,000,000 question" (the Riemann hypothesis) over Talk.
zeta(1/2 + it) is traced in the complex plane as t grows; every time the curve passes through 0 (a zero on the
critical line) it lands on a beat, and the count goes up. Then the question: are ALL of them on that line?
python studio/mathviz/zeta.py out.mp4 [--seed N] [--beats 44|24] [--frames a,b,c]

44 beats: a zero every two beats, the formula and Riemann's question, the prize. 24 beats (kit.short()): the same
question on frame 0, a zero every beat, the question and the prize in the last six beats, looping back to frame 0.

The curve is precomputed (zeta_line.npz: zeta(1/2 + it) for t in [0, 61.5] in steps of 0.01, and the first 14
zeros), so rendering needs no arbitrary-precision maths; make_line() rebuilds it with mpmath."""
import sys, os, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

LINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zeta_line.npz')

def make_line(path=LINE):
    import mpmath
    ts = np.arange(0, 61.5, 0.01)
    z = np.array([complex(mpmath.zeta(mpmath.mpc(0.5, t))) for t in ts])
    zeros = np.array([float(mpmath.zetazero(n).imag) for n in range(1, 15)])
    np.savez_compressed(path, t=ts.astype(np.float32), re=z.real.astype(np.float32), im=z.imag.astype(np.float32), zeros=zeros)

if not os.path.exists(LINE): make_line()
_L = np.load(LINE); TS, RE, IM, ZEROS = _L['t'].astype(np.float64), _L['re'].astype(np.float64), _L['im'].astype(np.float64), _L['zeros']

SLUG, B0, SEED = conf('talk', 96)
ST = Style(SEED)
SHORT = short(); Q = lambda long, brief: brief if SHORT else long      # a cue in beats: the 44-beat value, the 24-beat value
CL = Clock(SLUG, B0, Q(44, 24), loop=SHORT)
CREDIT = credit(SLUG)
OX, OY, S = 540.0, 860.0, 180.0                        # where 0 is, and pixels per unit
RE0 = 1.1                                              # the view is centred on Re = 1.1 so the whole curve fits
X = lambda re: OX + (re - RE0) * S
Y = lambda im: OY - im * S
ZX, ZY = X(0.0), Y(0.0)                                # the origin on screen
PTS = np.stack([X(RE), Y(IM)], 1)
BG = background(ST); FONT = FONTS[ST.font]
def mix(c1, c2, t): return tuple(int(a * (1 - t) + b * t) for a, b in zip(c1, c2))

ZB = [Q(8 + 2 * n, 4 + n) for n in range(len(ZEROS))]      # zero n lands on beat 8, 10, ... 34 (short: 4, 5, ... 17)
TITLE, TRACE, ASK, END = Q(3.8, 2.4), Q(4, 2.8), Q(24, 11), Q(36, 18)   # the title fades; the trace starts; the formula and question; the prize
HITS = {b: 0.35 for b in ZB}; HITS.update({ASK: 0.8, END: 1.0})

def t_at(k):
    """How far along the critical line (t) the trace is at beat k: from 0 to the first zero over beats 4-8, then one
    zero every two beats, easing into each one so the curve settles on 0 exactly on the beat; it holds after."""
    if k < TRACE: return 0.0
    if k < ZB[0]:
        u = (k - TRACE) / (ZB[0] - TRACE); return ZEROS[0] * float(ease_in_out(u))
    for j in range(1, len(ZB)):
        if k < ZB[j]:
            u = (k - ZB[j - 1]) / (ZB[j] - ZB[j - 1]); e = 0.35 * u + 0.65 * float(ease_in_out(u))
            return ZEROS[j - 1] + (ZEROS[j] - ZEROS[j - 1]) * e
    return float(ZEROS[-1])

def found(k): return sum(1 for b in ZB if k >= b)

def axes(c, alpha):
    col = mix(ST.bg, ST.muted, 0.35 * alpha)
    poly(c, [(60, ZY), (W - 60, ZY)], col, 2); poly(c, [(ZX, Y(2.45)), (ZX, Y(-2.5))], col, 2)
    if alpha > 0.05:
        paste(c, text('Re', F(INTER, 30), ST.muted), W - 80, ZY - 26, 1, alpha)
        paste(c, text('Im', F(INTER, 30), ST.muted), ZX + 34, Y(2.4), 1, alpha)

def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = BG.copy()
    show = float(ease_out((k - (TITLE - 0.2)) / 0.6))
    axes(c, show)
    n = found(k); last = ZB[n - 1] if n else -9
    since = k - last
    # the target at 0: a ring that flashes and throws a ripple each time the curve lands on it
    if show > 0:
        ring = 14 + 10 * math.exp(-since * 3) if n else 14
        circle(c, (ZX, ZY), ring, ST.c if n else mix(ST.bg, ST.c, 0.6), 3)
        if 0 <= since < 1.2: circle(c, (ZX, ZY), 18 + 130 * since, mix(ST.bg, ST.c, max(0, 1 - since / 1.2)), 3)
    t = t_at(k)
    if show > 0 and t > 0:
        m = max(2, int(t / 0.01) + 1)
        poly(c, PTS[:m], ST.d, 5, glow=(0.8 + 1.2 * kick) * ST.glow * show)
        hx, hy = PTS[m - 1]
        circle(c, (hx, hy), 9 + 4 * kick, ST.a, -1)
    elif show > 0:
        circle(c, (X(RE[0]), Y(IM[0])), 9, ST.a, -1)
    # words
    if k < TITLE + 0.8:
        a = 1 - float(ease_out((k - TITLE) / 0.5))
        e1 = 1.0; e2 = float(ease_back((k - Q(1.4, 0.9)) / 0.45)); e3 = float(ease_back((k - Q(2.4, 1.6)) / 0.45))
        paste(c, text('this spiral hides a', F(FONT, 74), ST.fg), W / 2, 520, e1, a * min(1, e1))
        paste(c, text('$1,000,000', F(FONT, 150), ST.a), W / 2, 760, e2 * (1 + 0.05 * kick), a * min(1, e2))
        paste(c, text('question.', F(FONT, 110), ST.fg), W / 2, 930, e3, a * min(1, e3))
    chips(c, ST, k, [(TRACE, ZB[0], 1, 'zeta(½ + it), as t grows', ST.d), (ZB[0], ASK, 2, 'every time it hits 0…', ST.c), (ASK, END, 3, 'a zero on the critical line', ST.a)])
    if ZB[0] <= k < END and n:
        pop = float(ease_back(min(1.0, since / 0.35)))
        paste(c, text('zero #%d' % n, F(FONT, 92), ST.c), W / 2, 1390, pop * (1 + 0.04 * kick), 1)
        paste(c, text('t = %.4f…' % ZEROS[n - 1], F(MONO, 54), ST.fg), W / 2, 1480, 1, float(ease_out(since / 0.4)))
    elif TITLE + 0.8 <= k < ZB[0]:
        paste(c, text('t = %.2f' % t, F(MONO, 54), ST.muted), W / 2, 1480, 1, float(ease_out((k - TITLE - 0.8) / 0.5)))
    if ASK <= k < END:
        paste(c, tex(r'$\zeta(s) = \sum_{n=1}^{\infty} \frac{1}{n^{s}}$', 50, ST.hx(ST.fg)), W / 2, 1625, float(ease_back((k - ASK) / 0.5)), window(k, ASK, END - 0.5))
        paste(c, text('Riemann, 1859: are ALL of them on this line?', F(INTER, 40), ST.muted), W / 2, 1755, 1, window(k, ASK + Q(2, 1), END - 0.5))
        paste(c, text('trillions checked by computer. none off it.', F(INTER, 38), ST.muted), W / 2, 1805, 1, window(k, ASK + Q(6, 3), END - 0.5))
    if END <= k:
        e = float(ease_back((k - END) / 0.45)); paste(c, text('prove it for every zero:', F(FONT, 72), ST.fg), W / 2, 1400, e, min(1, e))
        e = float(ease_back((k - END - 1) / 0.45)); paste(c, text('$1,000,000.', F(FONT, 140), ST.a), W / 2, 1540, e * (1 + 0.05 * kick), min(1, e))
        paste(c, text('2026: an AI proved at least 67% of them are on it', F(INTER, 36), ST.muted), W / 2, 1680, 1, float(ease_out((k - END - Q(3, 2)) / 0.6)))
        paste(c, text('%d zeros so far. every one on the line.' % n, F(INTER, 40), ST.muted), W / 2, 1750, 1, float(ease_out((k - END - Q(5, 3)) / 0.6)))
    amp, ph = shake_at(k, HITS, ST)
    zoom = 1 + 0.03 * float(ease_in_out((k - ZB[0]) / (END - 2 - ZB[0]))) + 0.010 * kick
    o = finish(c, k, amp, ph, zoom, ZX, ZY, ST)
    return overlay_fixed(o, ST, k, CL.beats, CREDIT)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
