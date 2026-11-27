"""Math In Time: "every sound you hear is just sine waves" (Fourier series) over Won't Be the Same Again.
Epicycles add a harmonic on every beat, the drawn wave squares up on the drop, then it all folds back to one.
python studio/mathviz/fourier.py out.mp4 [--seed N] [--beats 44|24] [--frames a,b,c]

44 beats: sixteen harmonics added one a beat, twelve beats of square wave and formula, the fold back. 24 beats
(kit.short()): the same claim on frame 0, eight harmonics, six beats of square wave, the fold back to one wave in the
last six, looping into frame 0."""
import sys, os, math
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

SLUG, B0, SEED = conf('wont-be-the-same-again', 244)
ST = Style(SEED)
SHORT = short(); Q = lambda long, brief: brief if SHORT else long      # a cue in beats: the 44-beat value, the 24-beat value
CL = Clock(SLUG, B0, Q(44, 24), loop=SHORT)
CREDIT = credit(SLUG)
CX0, CY0, A = 290.0, 870.0, 118.0
WX0, WX1 = 575, 1025
BG = background(ST); FONT = FONTS[ST.font]
def mix(c1, c2, t): return tuple(int(a * (1 - t) + b * t) for a, b in zip(c1, c2))
RING = mix(ST.bg, ST.muted, 0.45)
TITLE, ONE, ADD, DROP, END = Q(3.8, 2.4), Q(4, 3), Q(8, 4), Q(24, 12), Q(36, 18)   # the title fades; one sine; a harmonic a beat; the square; the fold back
HITS = {DROP: 1.0, DROP + Q(4, 2): 0.4, END: 0.7}
HITS.update({b: 0.25 for b in CL.snare_beats if DROP <= b < DROP + Q(4, 2)})

def harmonics(k):
    if k < ADD: return 1
    if k < DROP: return 1 + int(k - ADD + 1)               # one more on every beat
    if k < END: return harmonics(DROP - 0.01) + int(min(1, (k - DROP) / 1.0) * (41 - harmonics(DROP - 0.01)))
    return max(1, int(41 * (1 - float(ease_in_out((k - END) / Q(6, 4))))))   # and back down to one, so it loops
NMAX = harmonics(END - 0.1)                                # the most circles on screen: what built the square

def rings(c, centres, radii, color, width, alpha):
    """All the epicycle circles in one pass (one mask, one blend)."""
    tmp = np.zeros((H, W), np.float32)
    for (x, y), r in zip(centres, radii):
        if r >= 1.5: cv2.circle(tmp, (int(round(x * 16)), int(round(y * 16))), int(round(r * 16)), 1.0, width, cv2.LINE_AA, shift=4)
    a = tmp[..., None] * alpha; c *= (1 - a); c += a * np.array(color, np.float32)

def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i]); t = i / FPS
    c = BG.copy()
    th = 2 * math.pi * t / (4 * CL.spb)                    # one turn per bar
    N = harmonics(k); ks = np.arange(1, 2 * N, 2)
    show = float(ease_out((k - (TITLE - 0.2)) / 0.6))
    if k < TITLE + 0.6:                                    # the hook: one plain wave across the screen
        xs = np.arange(40, W - 40, 2.0); ys = 870 - (160 + 40 * kick) * np.sin(xs * 0.012 - th)
        poly(c, np.stack([xs, ys], 1), ST.d, 6, glow=(1 + kick) * ST.glow * (1 - show))
    if show > 0:
        x, y = CX0, CY0; pts = [(x, y)]; radii = []
        for kk in ks:
            r = A * 4 / math.pi / kk; radii.append(r)
            x += r * math.cos(kk * th); y -= r * math.sin(kk * th); pts.append((x, y))
        rings(c, pts[:-1], radii, RING, 2, show)
        poly(c, pts, ST.a, 3)
        xs = np.arange(WX0, WX1, 1.5); s = (xs - WX0) * 0.0125
        ys = CY0 - sum(A * 4 / math.pi / kk * np.sin(kk * (th - s)) for kk in ks)
        poly(c, [(x, y), (WX0, ys[0])], mix(ST.bg, ST.fg, 0.55), 2)
        if DROP <= k < END:                                # the square wave it is heading for
            sq = CY0 - A * np.sign(np.sin(th - s))
            tmp = c.copy(); poly(tmp, np.stack([xs, sq], 1), mix(ST.bg, ST.muted, 0.8), 3)
            a_ = 0.6 * window(k, DROP + 0.5, END - 0.5); c *= (1 - a_); c += tmp * a_
        poly(c, np.stack([xs, ys], 1), ST.d, 6, glow=(1 + 1.2 * kick) * show * ST.glow)
        circle(c, (x, y), 5, ST.c, -1)
    # words
    if k < TITLE + 0.8:
        a = 1 - float(ease_out((k - TITLE) / 0.5))
        e1 = 1.0; e2 = float(ease_back((k - Q(1.5, 0.9)) / 0.45)); e3 = float(ease_back((k - Q(2.5, 1.6)) / 0.45))
        paste(c, text('every sound you hear', F(FONT, 74), ST.fg), W / 2, 500, e1, a * min(1, e1))
        paste(c, text('is just', F(FONT, 74), ST.fg), W / 2, 600, e2, a * min(1, e2))
        paste(c, text('sine waves.', F(FONT, 132), ST.d), W / 2, 1250, e3 * (1 + 0.05 * kick), a * min(1, e3))
    chips(c, ST, k, [(ONE, ADD, 1, 'one sine wave', ST.d), (ADD, DROP, 2, 'add faster, smaller ones', ST.d), (DROP, END, 3, 'infinitely many = a square', ST.c)])
    if ONE <= k < DROP:                                    # the newest term pops in on its beat
        n = 2 * harmonics(k) - 1
        pop = float(ease_back((k - math.floor(k)) / 0.35)) if k >= ADD else float(ease_back((k - ONE) / 0.4))
        term = r'$\sin x$' if n == 1 else r'$+\ \frac{\sin %dx}{%d}$' % (n, n)
        paste(c, tex(term, 64, ST.hx(ST.a)), W / 2, 1230, pop * (1 + 0.05 * kick), min(1.0, pop + 0.3) if k >= ADD else min(1, pop))
        cnt = harmonics(k)
        paste(c, text('%d sine wave%s' % (cnt, '' if cnt == 1 else 's'), F(MONO, 62), ST.fg), W / 2, 1390, 1 + 0.04 * kick, float(ease_out((k - ONE - 0.2) / 0.5)))
    if DROP <= k < END: paste(c, text('a prism for sound.', F(FONT, 70), ST.c), W / 2, 1210, float(ease_back((k - DROP - 0.3) / 0.5)), window(k, DROP + 0.3, END - 0.5))
    FORM = DROP + Q(4, 1)                                  # the formula and its author
    if FORM <= k < END:
        paste(c, tex(r'$f(x) = \frac{4}{\pi}\sum_{n=1}^{\infty}\frac{\sin\left((2n-1)x\right)}{2n-1}$', 58, ST.hx(ST.fg)), W / 2, 1440, float(ease_back((k - FORM) / 0.5)), window(k, FORM, END - 0.5))
        paste(c, text('Joseph Fourier, 1807', F(INTER, 44), ST.muted), W / 2, 1610, 1, window(k, FORM + Q(2, 1), END - 0.5))
        paste(c, text('the idea behind how music gets compressed', F(INTER, 38), ST.muted), W / 2, 1680, 1, window(k, FORM + Q(4, 2.5), END - 0.5))
    if END <= k:
        e = float(ease_back((k - END) / 0.45)); paste(c, text('every sound', F(FONT, 84), ST.fg), W / 2, 1290, e, min(1, e))
        e = float(ease_back((k - END - 1) / 0.45)); paste(c, text('= sine waves.', F(FONT, 110), ST.d), W / 2, 1410, e * (1 + 0.05 * kick), min(1, e))
        paste(c, text('%d circles. one square wave.' % NMAX, F(INTER, 40), ST.muted), W / 2, 1560, 1, float(ease_out((k - END - Q(4, 2.5)) / 0.6)))
    amp, ph = shake_at(k, HITS, ST)
    zoom = 1 + 0.045 * float(ease_in_out((k - ADD) / (DROP - ADD))) * (1 - float(ease_in_out((k - DROP) / 2))) + 0.010 * kick
    o = finish(c, k, amp, ph, zoom, W / 2, CY0, ST)
    return overlay_fixed(o, ST, k, CL.beats, CREDIT)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
