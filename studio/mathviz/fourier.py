"""Math In Time: "every sound you hear is just sine waves" (Fourier series) over Won't Be the Same Again.
Epicycles add a harmonic on every beat, the drawn wave squares up on the drop, then it all folds back to one.
python studio/mathviz/fourier.py out.mp4 [--seed N] [--frames a,b,c]"""
import sys, os, math
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

SLUG, B0, SEED = conf('wont-be-the-same-again', 244)
ST = Style(SEED)
CL = Clock(SLUG, B0, 44)
CREDIT = credit(SLUG)
CX0, CY0, A = 290.0, 870.0, 118.0
WX0, WX1 = 575, 1025
BG = background(ST); FONT = FONTS[ST.font]
def mix(c1, c2, t): return tuple(int(a * (1 - t) + b * t) for a, b in zip(c1, c2))
RING = mix(ST.bg, ST.muted, 0.45)
HITS = {24: 1.0, 28: 0.4, 36: 0.7}
HITS.update({b: 0.25 for b in CL.snare_beats if 24 <= b < 28})

def harmonics(k):
    if k < 8: return 1
    if k < 24: return 1 + int(k - 7)                       # one more on every beat
    if k < 36: return 17 + int(min(1, (k - 24) / 1.0) * 24)
    return max(1, int(41 * (1 - float(ease_in_out((k - 36) / 6)))))   # and back down to one, so it loops

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
    show = float(ease_out((k - 3.6) / 0.6))
    if k < 4.4:                                            # the hook: one plain wave across the screen
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
        if 24 <= k < 36:                                   # the square wave it is heading for
            sq = CY0 - A * np.sign(np.sin(th - s))
            tmp = c.copy(); poly(tmp, np.stack([xs, sq], 1), mix(ST.bg, ST.muted, 0.8), 3)
            a_ = 0.6 * window(k, 24.5, 35.5); c *= (1 - a_); c += tmp * a_
        poly(c, np.stack([xs, ys], 1), ST.d, 6, glow=(1 + 1.2 * kick) * show * ST.glow)
        circle(c, (x, y), 5, ST.c, -1)
    # words
    if k < 4.6:
        a = 1 - float(ease_out((k - 3.8) / 0.5))
        e1 = 1.0; e2 = float(ease_back((k - 1.5) / 0.45)); e3 = float(ease_back((k - 2.5) / 0.45))
        paste(c, text('every sound you hear', F(FONT, 74), ST.fg), W / 2, 500, e1, a * min(1, e1))
        paste(c, text('is just', F(FONT, 74), ST.fg), W / 2, 600, e2, a * min(1, e2))
        paste(c, text('sine waves.', F(FONT, 132), ST.d), W / 2, 1250, e3 * (1 + 0.05 * kick), a * min(1, e3))
    chips(c, ST, k, [(4, 8, 1, 'one sine wave', ST.d), (8, 24, 2, 'add faster, smaller ones', ST.d), (24, 36, 3, 'infinitely many = a square', ST.c)])
    if 4 <= k < 24:                                        # the newest term pops in on its beat
        n = 2 * harmonics(k) - 1
        pop = float(ease_back((k - math.floor(k)) / 0.35)) if k >= 8 else float(ease_back((k - 4) / 0.4))
        term = r'$\sin x$' if n == 1 else r'$+\ \frac{\sin %dx}{%d}$' % (n, n)
        paste(c, tex(term, 64, ST.hx(ST.a)), W / 2, 1230, pop * (1 + 0.05 * kick), min(1.0, pop + 0.3) if k >= 8 else min(1, pop))
        cnt = harmonics(k)
        paste(c, text('%d sine wave%s' % (cnt, '' if cnt == 1 else 's'), F(MONO, 62), ST.fg), W / 2, 1390, 1 + 0.04 * kick, float(ease_out((k - 4.2) / 0.5)))
    if 24 <= k < 36: paste(c, text('a prism for sound.', F(FONT, 70), ST.c), W / 2, 1210, float(ease_back((k - 24.3) / 0.5)), window(k, 24.3, 35.5))
    if 28 <= k < 36:
        paste(c, tex(r'$f(x) = \frac{4}{\pi}\sum_{n=1}^{\infty}\frac{\sin\left((2n-1)x\right)}{2n-1}$', 58, ST.hx(ST.fg)), W / 2, 1440, float(ease_back((k - 28) / 0.5)), window(k, 28, 35.5))
        paste(c, text('Joseph Fourier, 1807', F(INTER, 44), ST.muted), W / 2, 1610, 1, window(k, 30, 35.5))
        paste(c, text('the idea behind how music gets compressed', F(INTER, 38), ST.muted), W / 2, 1680, 1, window(k, 32, 35.5))
    if 36 <= k:
        e = float(ease_back((k - 36) / 0.45)); paste(c, text('every sound', F(FONT, 84), ST.fg), W / 2, 1290, e, min(1, e))
        e = float(ease_back((k - 37) / 0.45)); paste(c, text('= sine waves.', F(FONT, 110), ST.d), W / 2, 1410, e * (1 + 0.05 * kick), min(1, e))
        paste(c, text('follow for the next one', F(INTER, 40), ST.muted), W / 2, 1560, 1, float(ease_out((k - 40) / 0.6)))
    amp, ph = shake_at(k, HITS, ST)
    zoom = 1 + 0.045 * float(ease_in_out((k - 8) / 16)) * (1 - float(ease_in_out((k - 24) / 2))) + 0.010 * kick
    o = finish(c, k, amp, ph, zoom, W / 2, CY0, ST)
    return overlay_fixed(o, ST, k, CL.beats, CREDIT)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
