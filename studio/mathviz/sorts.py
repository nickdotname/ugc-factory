"""Math In Time: a sorting-algorithm race. Four algorithms sort the same shuffled numbers side by side, one step each
at the same rate, so you watch O(n log n) leave O(n^2) behind; each finisher gets its place on the beat it lands on,
then what the gap means at a million numbers.
python studio/mathviz/sorts.py out.mp4 [--seed N] [--frames a,b,c]

Every step is a real comparison or write of the algorithm named over it (the traces are recorded from running it).
Which four race, how many bars and how they are drawn are knobs."""
import sys, os, math, random
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

SLUG, B0, SEED = conf('fixation', 64)
ST = Style(SEED)
CL = Clock(SLUG, B0, 44)
CREDIT = credit(SLUG)
R = random.Random(SEED * 31 + 7)
BG = background(ST); FONT = FONTS[ST.font]
def mix(c1, c2, t): return tuple(int(a * (1 - t) + b * t) for a, b in zip(c1, c2))


# ---------------------------------------------------------------- the algorithms, as traces of (kind, i, j) steps
def bubble(a):
    a = a[:]; n = len(a)
    for end in range(n - 1, 0, -1):
        done = True
        for i in range(end):
            yield ('cmp', i, i + 1)
            if a[i] > a[i + 1]: a[i], a[i + 1] = a[i + 1], a[i]; done = False; yield ('swap', i, i + 1)
        if done: return

def cocktail(a):
    a = a[:]; lo, hi = 0, len(a) - 1
    while lo < hi:
        sw = False
        for i in range(lo, hi):
            yield ('cmp', i, i + 1)
            if a[i] > a[i + 1]: a[i], a[i + 1] = a[i + 1], a[i]; sw = True; yield ('swap', i, i + 1)
        hi -= 1
        for i in range(hi, lo, -1):
            yield ('cmp', i - 1, i)
            if a[i - 1] > a[i]: a[i - 1], a[i] = a[i], a[i - 1]; sw = True; yield ('swap', i - 1, i)
        lo += 1
        if not sw: return

def insertion(a):
    a = a[:]
    for i in range(1, len(a)):
        j = i
        while j > 0:
            yield ('cmp', j - 1, j)
            if a[j - 1] <= a[j]: break
            a[j - 1], a[j] = a[j], a[j - 1]; yield ('swap', j - 1, j); j -= 1

def selection(a):
    a = a[:]; n = len(a)
    for i in range(n - 1):
        m = i
        for j in range(i + 1, n):
            yield ('cmp', m, j)
            if a[j] < a[m]: m = j
        if m != i: a[i], a[m] = a[m], a[i]; yield ('swap', i, m)

def quick(a):
    a = a[:]
    def part(lo, hi):
        if lo >= hi: return
        p = a[hi]; i = lo
        for j in range(lo, hi):
            yield ('cmp', j, hi)
            if a[j] < p:
                if i != j: a[i], a[j] = a[j], a[i]; yield ('swap', i, j)
                i += 1
        if i != hi: a[i], a[hi] = a[hi], a[i]; yield ('swap', i, hi)
        yield from part(lo, i - 1); yield from part(i + 1, hi)
    yield from part(0, len(a) - 1)

def merge(a):
    a = a[:]
    def ms(lo, hi):
        if hi - lo < 2: return
        mid = (lo + hi) // 2
        yield from ms(lo, mid); yield from ms(mid, hi)
        left, right = a[lo:mid], a[mid:hi]; i = j = 0; k = lo
        while i < len(left) and j < len(right):
            yield ('cmp', lo + i, mid + j)
            if left[i] <= right[j]: a[k] = left[i]; i += 1
            else: a[k] = right[j]; j += 1
            yield ('set', k, a[k]); k += 1
        for v in left[i:] + right[j:]: a[k] = v; yield ('set', k, v); k += 1
    yield from ms(0, len(a))

def heap(a):
    a = a[:]; n = len(a)
    def sift(s, end):
        r = s
        while 2 * r + 1 <= end:
            c = 2 * r + 1; sw = r
            yield ('cmp', sw, c)
            if a[sw] < a[c]: sw = c
            if c + 1 <= end:
                yield ('cmp', sw, c + 1)
                if a[sw] < a[c + 1]: sw = c + 1
            if sw == r: return
            a[r], a[sw] = a[sw], a[r]; yield ('swap', r, sw); r = sw
    for s in range((n - 2) // 2, -1, -1): yield from sift(s, n - 1)
    for end in range(n - 1, 0, -1):
        a[0], a[end] = a[end], a[0]; yield ('swap', 0, end); yield from sift(0, end - 1)

def shell(a):
    a = a[:]; n = len(a); gap = n // 2
    while gap:
        for i in range(gap, n):
            j = i
            while j >= gap:
                yield ('cmp', j - gap, j)
                if a[j - gap] <= a[j]: break
                a[j - gap], a[j] = a[j], a[j - gap]; yield ('swap', j - gap, j); j -= gap
        gap //= 2

def bogo(a):
    a = a[:]; rr = random.Random(5)
    while True:
        for i in range(len(a) - 1):
            yield ('cmp', i, i + 1)
            if a[i] > a[i + 1]: break
        else: return
        for i in range(len(a) - 1, 0, -1):
            j = rr.randrange(i + 1); a[i], a[j] = a[j], a[i]; yield ('swap', i, j)

ALGOS = {'bubble': (bubble, 'bubble sort', 2), 'cocktail': (cocktail, 'cocktail shaker', 2), 'insertion': (insertion, 'insertion sort', 2),
         'selection': (selection, 'selection sort', 2), 'quick': (quick, 'quicksort', 1), 'merge': (merge, 'merge sort', 1),
         'heap': (heap, 'heapsort', 1), 'shell': (shell, 'shell sort', 1.5), 'bogo': (bogo, 'bogosort', 9)}
LINEUPS = {'classic': ['bubble', 'insertion', 'merge', 'quick'], 'fast': ['merge', 'quick', 'heap', 'shell'],
           'slow': ['bubble', 'selection', 'insertion', 'cocktail'], 'mixed': ['selection', 'shell', 'heap', 'cocktail'],
           'bogo': ['bubble', 'quick', 'merge', 'bogo']}
LINEUP = K.pick('lineup', ['classic', 'fast', 'slow', 'mixed', 'bogo'], random.Random(SEED), weights=[3, 2, 2, 2, 1])
N = int(K.pick('bars', [32, 48, 64], random.Random(SEED + 1), weights=[2, 3, 1]))
LOOK = K.pick('bars_look', ['bars', 'dots', 'rainbow'], random.Random(SEED + 2))
VALUES = list(range(1, N + 1)); R.shuffle(VALUES)


def trace(name, cap):
    """Every array state the algorithm passes through, and what it touched at each step."""
    a = VALUES[:]; states = [a[:]]; touch = [()]
    for step in ALGOS[name][0](VALUES):
        kind, i, j = step
        if kind == 'swap': a[i], a[j] = a[j], a[i]
        elif kind == 'set': a[i] = j
        states.append(a[:]); touch.append((i, j) if kind != 'set' else (i,))
        if len(states) > cap: return np.array(states, np.int16), touch, False
    return np.array(states, np.int16), touch, True

RACE0, RACE1 = 7.0, 33.0                       # the race runs from beat 7; the slowest real finisher lands on beat 33
NAMES = LINEUPS[LINEUP]
TR = {}
for nm in NAMES: TR[nm] = trace(nm, 400000 if nm != 'bogo' else 60000)
slow = max(len(TR[nm][0]) for nm in NAMES if TR[nm][2])
RATE = (slow - 1) / (RACE1 - RACE0)            # steps per beat, the same for every lane
FIN = {nm: RACE0 + (len(TR[nm][0]) - 1) / RATE if TR[nm][2] else None for nm in NAMES}
ORDER = sorted([nm for nm in NAMES if FIN[nm] is not None], key=lambda nm: FIN[nm])
PLACE = {nm: k + 1 for k, nm in enumerate(ORDER)}
HITS = {round(FIN[nm] * 2) / 2: 0.7 for nm in ORDER}
HITS.update({RACE0: 0.9, 36: 0.6})

LANE_Y0, LANE_H, GAP = 470, 240, 20                  # the last lane ends at 1490: inside Instagram's safe area
def lane_box(k):
    y = LANE_Y0 + k * (LANE_H + GAP); return 70, y, W - 70, y + LANE_H

def colour_of(v):
    t = (v - 1) / max(1, N - 1)
    if LOOK == 'rainbow':
        h = np.uint8([[[int(170 * t), 210, 255]]]); return tuple(int(x) for x in cv2.cvtColor(h, cv2.COLOR_HSV2RGB)[0, 0])
    return mix(ST.b, ST.a, t)

COLS = {v: np.array(colour_of(v), np.float32) for v in VALUES}

def draw_lane(c, k, nm, kb, kick):
    x0, y0, x1, y1 = lane_box(k)
    states, touch, ok = TR[nm]
    s = 0 if kb < RACE0 else min(len(states) - 1, int((kb - RACE0) * RATE))
    arr = states[s]; hot = set(touch[s]) if 0 < s < len(states) - 1 else set()
    done = FIN[nm] is not None and kb >= FIN[nm]
    panel = np.array(mix(ST.bg, ST.fg, 0.06), np.float32)
    c[y0:y1, x0:x1] = c[y0:y1, x0:x1] * 0.35 + panel * 0.65
    bx0, bx1, by1, bh = x0 + 16, x1 - 16, y1 - 14, LANE_H - 78
    bw = (bx1 - bx0) / N
    sweep = (kb - FIN[nm]) / 1.0 if done else -1
    for idx, v in enumerate(arr):
        h = bh * v / N; xa = int(bx0 + idx * bw + 1); xb = int(bx0 + (idx + 1) * bw - 1)
        col = COLS[int(v)]
        if done:                                               # a white flash runs along the sorted bars on the finishing beat
            flash = math.exp(-((idx / N - sweep * 1.2 + 0.1) * 7) ** 2) if sweep < 1.3 else 0.0
            if LOOK != 'rainbow' and idx / N < sweep: col = np.array(ST.d, np.float32)
            col = col + (255 - col) * 0.8 * flash
        if idx in hot: col = np.array(ST.c, np.float32) * (1 + 0.3 * kick)
        if LOOK == 'dots':
            cy = int(by1 - h); cv2.circle(c, ((xa + xb) // 2, cy), max(3, (xb - xa) // 2 + 1), tuple(float(x) for x in col), -1, cv2.LINE_AA)
        else:
            c[int(by1 - h):by1, xa:max(xa + 1, xb)] = col
    paste(c, text(ALGOS[nm][1], F(FONT, 40), ST.fg), x0 + 20 + text(ALGOS[nm][1], F(FONT, 40), ST.fg).shape[1] / 4, y0 + 34)
    steps = '%s steps' % format(s, ',')
    sp = text(steps, F(MONO, 30), ST.muted); paste(c, sp, x1 - 20 - sp.shape[1] / 4, y0 + 34)
    if done:
        e = float(ease_back((kb - FIN[nm]) / 0.4)); p = PLACE[nm]
        lab = {1: '1st', 2: '2nd', 3: '3rd'}.get(p, '%dth' % p)
        paste(c, text(lab, F(FONT, 70), ST.d if p == 1 else ST.fg, stroke=3), x1 - 110, y0 + LANE_H / 2 + 10, e, min(1, e))
    elif kb >= RACE1 + 0.2 and FIN[nm] is None:
        paste(c, text('still shuffling...', F(FONT, 44), ST.c, stroke=3), (x0 + x1) / 2, y0 + LANE_H / 2 + 10, 1, window(kb, RACE1 + 0.2, 99))


def bogo_years():
    lg = math.lgamma(N + 1) / math.log(10) - 9 - math.log10(3.156e7)     # expected shuffles, a billion a second, in years
    return '10^%d' % int(lg)


def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = BG.copy()
    # the question stays up all race
    q = 'which one finishes first?'
    if k < 4.6:
        e1 = 1.0; e2 = float(ease_back((k - 1.3) / 0.45)); e3 = float(ease_back((k - 2.4) / 0.45))   # the title is on frame 0: the cover
        a = 1 - float(ease_out((k - 4.0) / 0.5))
        paste(c, text('4 sorting algorithms.', F(FONT, 76), ST.fg), W / 2, 325, e1, a * min(1, e1))
        paste(c, text('the same %d numbers.' % N, F(FONT, 60), ST.muted), W / 2, 405, e2, a * min(1, e2))
        paste(c, text('which one', F(FONT, 92), ST.a, stroke=3), W / 2, 1600, e3 * (1 + 0.04 * kick), a * min(1, e3))
        paste(c, text('finishes first?', F(FONT, 92), ST.a, stroke=3), W / 2, 1700, e3 * (1 + 0.04 * kick), a * min(1, e3))
    else:
        paste(c, text(q, F(FONT, 58), ST.a), W / 2, 330, 1, window(k, 4.4, 34.5))
    show = 1 if k < 34 else 1 - 0.9 * float(ease_out((k - 34) / 0.8))
    for n_, nm in enumerate(NAMES): draw_lane(c, n_, nm, k, kick)
    if show < 1: c[:] = c * show + BG * (1 - show)
    if 4 <= k < 7.6:                                         # 3, 2, 1, go: one a beat
        n = int(k - 4); lab = ['3', '2', '1', 'GO'][min(3, n)]
        e = float(ease_back((k - 4 - n) / 0.3))
        paste(c, text(lab, F(FONT, 240), ST.c if lab == 'GO' else ST.fg, stroke=6), W / 2, 1000, e * (1 + 0.06 * kick), min(1, e) * (1 - float(ease_out((k - 4 - n - 0.7) / 0.3))))
    if k >= 34:                                              # the results, then what they mean at scale
        for p, nm in enumerate(ORDER[:3]):
            e = float(ease_back((k - 34.3 - 0.5 * p) / 0.4))
            secs = (FIN[nm] - RACE0) * CL.spb
            paste(c, text('%d. %s  %.1fs' % (p + 1, ALGOS[nm][1], secs), F(FONT, 60), ST.d if p == 0 else ST.fg, stroke=3), W / 2, 820 + p * 95, e, min(1, e) * window(k, 34.3, 38.4))
        # at a million numbers and a billion comparisons a second: n^2/2 comparisons ~ 8 min (bubble, selection), n^2/4 ~ 4 min
        # (insertion, on average); n log2 n ~ 0.02 s (merge), ~1.4 n log2 n ~ 0.03 s (quick), ~2 n log2 n ~ 0.04 s (heap)
        SLOWT = {'bubble': '~8 minutes', 'selection': '~8 minutes', 'insertion': '~4 minutes'}
        FASTT = {'merge': '~0.02 seconds', 'quick': '~0.03 seconds', 'heap': '~0.04 seconds'}
        sq = [nm for nm in NAMES if nm in SLOWT]; fast = [nm for nm in ORDER if nm in FASTT]
        if k >= 38.4:
            if 'bogo' in NAMES:
                lines = [('bogosort shuffles until sorted.', ST.muted, 50), ('%d numbers would take' % N, ST.fg, 60), ('%s years' % bogo_years(), ST.c, 96), ('(a billion shuffles a second)', ST.muted, 36)]
            elif sq and fast:
                lines = [('with 1,000,000 numbers:', ST.muted, 54), ('%s: %s' % (ALGOS[sq[0]][1], SLOWT[sq[0]]), ST.c, 68),
                         ('%s: %s' % (ALGOS[fast[0]][1], FASTT[fast[0]]), ST.d, 68), ('(a billion comparisons a second)', ST.muted, 36)]
            else:
                lines = [('n log n vs n²', ST.a, 90), ('same job,', ST.fg, 64), ('wildly different work', ST.fg, 64)]
            for p, (s, col, sz) in enumerate(lines):
                e = float(ease_back((k - 38.4 - 0.6 * p) / 0.4))
                paste(c, text(s, F(FONT if sz >= 60 else INTER, sz), col, stroke=3 if sz >= 60 else 0), W / 2, 820 + p * 110, e * (1 + 0.04 * kick * (p == 2)), min(1, e))
            paste(c, text('%d numbers. %d sorts. one order.' % (N, len(NAMES)), F(INTER, 40), ST.muted), W / 2, 1560, 1, float(ease_out((k - 41.5) / 0.6)))
    amp, ph = shake_at(k, HITS, ST)
    o = finish(c, k, amp, ph, 1 + 0.008 * kick, W / 2, H / 2, ST)
    return overlay_fixed(o, ST, k, CL.beats, CREDIT)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
