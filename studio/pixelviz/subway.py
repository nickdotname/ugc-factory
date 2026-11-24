"""Pixel world: a subway platform, cut open. A train pulls in and stops exactly on a bar line, the doors open, and on
every beat after that one rider steps off or one steps on; the doors shut and it pulls out on another bar line. The
people waiting nod on the kick, the busker never stops, and when the train has gone a rat has the tracks to itself,
moving on the hi-hats."""
import math
import numpy as np
from vox import *

NAME, PLACE = 'NEXT STOP', 'the train pulls in on the downbeat'
NX, NY, NZ = 72, 34, 16
OX, OY = 100, 156
BED, PLAT = 1, 4                        # top of the track bed, top of the platform
TY0, TY1 = 4, 11                        # the train runs along x between these y
CAR, LINK = 30, 2                       # a car's length, the gap between the two
STOP = 67.0                             # where the front of the train stops
DOORS = (6, 20)                         # where a car's doors start (each four wide)
FOCUS = [(40, 13, 6), (20, 18, 6), (58, 14, 6)]

FONT = {'8': '111101111101111', 'S': '111100111001111', 'T': '111010010010010', 'N': '101111111111101',
        'Y': '101101010010010', 'U': '101101101101111', '-': '000000111000000', ' ': '000000000000000'}
SIGN = '8 ST - NYU'

def build(rng):
    w = World(NX, NY, NZ, seed=int(rng.integers(1 << 30)))
    X, Y, Z = w.grid()
    w.put(Z == 0, DIRT, (40, 40, 46), 5)
    # the trench: gravel, sleepers, two rails
    w.put((Y >= 2) & (Y <= 12) & (Z == BED), ROCK, (58, 56, 62), 9)
    w.put((Y >= TY0) & (Y <= TY1) & (Z == BED) & (X % 3 == 0), WOOD, (74, 58, 44), 6)
    w.put(((Y == 5) | (Y == 10)) & (Z == BED + 1), FENCE, (150, 154, 164), 5)
    # the far wall: white tile, a mosaic band with the station's name
    w.put((Y <= 1) & (Z >= 1), STONE, (212, 212, 204), 5)
    w.bricks(STONE, every=3, dark=0.90)
    band = (Y == 1) & (Z >= 8) & (Z <= 14)
    w.put(band, DARK, (36, 58, 124), 4)
    w.put(band & ((Z == 8) | (Z == 14)), DARK, (206, 164, 74), 5)
    x0 = (NX - 4 * len(SIGN)) // 2
    for k, ch in enumerate(SIGN):
        for r in range(5):
            for c in range(3):
                if FONT[ch][r * 3 + c] == '1': w.box(x0 + 4 * k + c, x0 + 4 * k + c + 1, 1, 2, 13 - r, 14 - r, LINE, (244, 240, 228), 2)
    # the platform, its yellow edge, columns with a lamp each, a bench, a bin, the stairs out
    w.put((Y >= 13) & (Z >= 1) & (Z <= PLAT), ROCK, (122, 122, 128), 5)
    w.put((Y >= 14) & (Z == PLAT) & ((X // 2 + Y // 2) % 2 == 0), ROCK, (112, 112, 118), 4)
    w.put((Y == 13) & (Z == PLAT), LINE, (234, 198, 62), 6)
    for cx in (9, 25, 41, 57):
        w.box(cx, cx + 1, 18, 19, PLAT + 1, 14, FENCE, (46, 86, 72), 4)
        w.box(cx - 1, cx + 2, 18, 19, 14, 15, FENCE, (40, 74, 62), 3)
        w.box(cx, cx + 1, 19, 20, 13, 14, SPLASH, (255, 244, 208), 2)
    w.box(29, 37, 29, 31, PLAT + 1, PLAT + 2, WOOD, (128, 94, 62), 6); w.box(29, 37, 31, 32, PLAT + 1, PLAT + 4, WOOD, (112, 82, 54), 6)
    w.box(18, 20, 30, 32, PLAT + 1, PLAT + 3, DARK, (52, 58, 66), 5)
    for s in range(8):
        w.box(63 + s, 64 + s, 24, 31, PLAT + 1, PLAT + 2 + s, ROCK, (104, 104, 110), 5)
    w.put((X >= 63) & ((Y == 23) | (Y == 31)) & (Z >= PLAT + 1) & (Z <= PLAT + 3 + (X - 63)) & (Z >= PLAT + 2 + (X - 63)), FENCE, (46, 86, 72), 4)
    w.lit = np.ones(w.mat.shape, bool)                                          # underground: no sun, no cast shadows
    return w

def setup(E, rng):
    n = E['n']; downs = [d for d in E['downs'] if 0 < d < n]
    near = lambda f, lo: min([d for d in downs if d >= lo] or [int(f)], key=lambda d: abs(d - f))
    S = near(min(0.38 * n, 150), 45); D = near(max(S + 105, 0.76 * n), S + 75)
    if D <= S + 60 or D > n - 20: D = None                                      # too short a stretch: it stays in the station
    E['S'], E['D'] = S, D
    doors = [STOP - (2 * CAR + LINK) + car * (CAR + LINK) + d + 1.5 for car in (0, 1) for d in DOORS]
    beats = [int(round(f)) for _, f in E['beats'] if S + 8 <= f < (D - 14 if D else n - 10)]
    if len(beats) > 10: beats = beats[::2] if len(beats) > 20 else beats
    order = [int(k) for k in rng.permutation(4)]
    E['riders'] = []                                                            # (frame, 'off' | 'on', door x, shirt, y to walk to)
    for k, f in enumerate(beats[:12]):
        E['riders'].append((f, 'off' if k % 2 == 0 else 'on', doors[order[(k // 2) % 4]], tuple(int(c) for c in rng.integers(70, 235, 3)), float(rng.uniform(17, 22))))
    ons = [r for r in E['riders'] if r[1] == 'on']
    E['waiting'] = [(r[2] + float(rng.uniform(-1.5, 1.5)), 15.0 + (k % 2), r[3], r[0]) for k, r in enumerate(ons)]
    E['waiting'] += [(float(rng.uniform(6, 60)), float(rng.uniform(22, 27)), tuple(int(c) for c in rng.integers(70, 235, 3)), None) for _ in range(3)]
    E['rat'] = np.cumsum(np.where(E['hat'][:n] > 0.5, 0.55, 0.04))

def front(E, i):
    """Where the front of the train is: easing in to stop on a bar line, standing, then pulling out on another."""
    S, D = E['S'], E['D']
    if i <= S: return STOP - 76.0 * (1 - i / S) ** 2.4
    if D is None or i <= D: return STOP
    return STOP + 0.016 * (i - D) ** 2

def doors_open(E, i):
    S, D = E['S'], E['D']
    a = min(1.0, max(0.0, (i - S - 2) / 6.0)); b = 1.0 if D is None else min(1.0, max(0.0, (D - 4 - i) / 6.0))
    return min(a, b)

def train(E, i):
    """The two cars as voxels: a roof, the side we can see (windows, doors, a stripe) and the front."""
    f = front(E, i); op = doors_open(E, i); glow = 0.75 + 0.25 * float(min(1.0, E['bassf'][i]))
    xs, ys, zs, cs = [], [], [], []
    def add(x, y, z, c): xs.append(x); ys.append(y); zs.append(z); cs.append(c)
    for car in (0, 1):
        x0 = f - (2 * CAR + LINK) + car * (CAR + LINK)
        if x0 > NX + 30 or x0 + CAR < -30: continue
        for u in range(CAR):
            x = x0 + u
            for y in range(TY0, TY1 + 1):                                       # the roof
                add(x, y, 10, (150, 154, 164) if y in (7, 8) and 4 <= u % 15 <= 10 else (182, 186, 196))
            door = any(d <= u < d + 4 for d in DOORS)
            half = any(u in (d, d + 3) for d in DOORS)
            for z in range(2, 10):                                              # the near side
                if z == 2: c = (34, 34, 40) if (u % 15) in (2, 3, 11, 12) else (64, 66, 74)
                elif z == 3: c = (36, 138, 150)
                elif door and (op > 0.5 and not half or op > 0.95): c = (255, 236, 184) if z > 3 else (120, 110, 90)
                elif door: c = (150, 154, 166) if z < 6 or z > 8 else tuple(int(v * glow) for v in (236, 214, 150))
                elif 6 <= z <= 8 and (u % 6) in (1, 2, 3): c = tuple(int(v * glow) for v in (255, 228, 156))
                else: c = (196, 200, 208)
                add(x, TY1, z, c)
        xe = x0 + CAR - 1
        for y in range(TY0, TY1 + 1):                                           # the front of each car
            for z in range(2, 10):
                c = (176, 180, 190)
                if car == 1:
                    if z in (7, 8) and TY0 + 2 <= y <= TY1 - 2: c = (30, 40, 58)
                    if z == 9 and TY0 + 2 <= y <= TY1 - 2: c = (255, 170, 60)
                    if z == 4 and y in (TY0 + 1, TY1 - 1): c = (255, 252, 230)
                add(xe, y, z, c)
    return np.array(xs, np.float64), np.array(ys, np.float64), np.array(zs, np.float64), np.array(cs, np.float32).reshape(-1, 3), f

def dynamic(cv, i, E):
    kick = float(E['kick'][i]); S, D = E['S'], E['D']
    xs, ys, zs, cs, f = train(E, i)
    if len(xs): cv.draw(xs, ys, zs, cs, DARK)
    if f < NX + 4 and (i < S or (D is not None and i > D)):                     # headlights on the rails ahead
        for dx in range(1, 12):
            for y in (5, 6, 9, 10):
                if (dx + y) % 2 == 0 and f + dx < NX: cv.draw([f + dx], [y], [BED + 1], [[255, 244, 190]], SPLASH, faces=(1,))
    if i - S in range(0, 5):                                                    # it stops: the door frames flash
        x0 = STOP - (2 * CAR + LINK)
        for car in (0, 1):
            for d in DOORS:
                for u in range(d, d + 4): cv.draw([x0 + car * (CAR + LINK) + u], [TY1], [10], [[255, 255, 255]], SPLASH)
    off = on = 0
    for (rf, kind, dx, shirt, wy) in E['riders']:
        t = i - rf
        if kind == 'off' and t >= 0:
            off += 1
            if t < 10: x, y, z = dx, 12 + (wy - 12) * t / 10.0, PLAT + 1
            else:
                x = dx + 0.55 * (t - 10); y = wy + (27.5 - wy) * min(1.0, (t - 10) / 40.0)
                z = PLAT + 1 + max(0.0, x - 62.5) if y > 24 else PLAT + 1
                if x > 70: continue
            px, py, pz, pc = person(x, y, z, shirt, 0.5 * abs(math.sin(t * 0.9)))
            cv.draw(px, py, pz, pc, PERSON)
        elif kind == 'on' and t >= 0: on += 1
    for (wx, wy, shirt, leave) in E['waiting']:
        if leave is not None and i >= leave:
            t = i - leave
            if t >= 9: continue
            door = [r[2] for r in E['riders'] if r[0] == leave][0]
            x = wx + (door - wx) * t / 9.0; y = wy + (11.6 - wy) * t / 9.0
        else: x, y = wx, wy
        px, py, pz, pc = person(x, y, PLAT + 1, shirt, 0.5 * kick)
        cv.draw(px, py, pz, pc, PERSON)
    beat = max((fr for _, fr in E['beats'] if fr <= i), default=-99)            # the busker, on every beat
    px, py, pz, pc = person(34, 25, PLAT + 1, (214, 172, 60), 0.7 * max(0.0, 1 - (i - beat) / 6.0), hair=(150, 40, 40))
    cv.draw(px, py, pz, pc, PERSON)
    cv.draw([35, 35], [24.4, 25.2], [PLAT + 2, PLAT + 2], [[150, 96, 52], [150, 96, 52]], WOOD)
    cv.draw([36, 37], [26, 26], [PLAT + 1, PLAT + 1], [[40, 34, 30], [40, 34, 30]], DARK, faces=(1,))
    if D is not None and i > D + 55:                                            # the rat
        rx = 66 - (E['rat'][i] - E['rat'][D + 55]) % 60
        cv.draw([rx, rx + 1], [7.5, 7.5], [BED + 1, BED + 1], [[150, 132, 124], [112, 96, 92]], DARK, faces=(1, 2))
    state = 'arriving' if i < S else 'doors open' if D is None or i < D - 4 else 'doors closing' if i < D else 'departing' if f < NX + 62 else 'gone'
    return dict(state=state, off=off, on=on)

def stats(i, E, info, voxels):
    return 'voxels %s   train: %s   off %d   on %d' % (format(voxels, ','), info['state'], info['off'], info['on'])

FILE = 'subway.py'
CODE = '''def world():
    # a station, cut open and drawn block by block
    w = World(72, 34, 16)
    w.trench(y=(2, 12), gravel=True)
    w.sleepers(every=3); w.rails(y=(5, 10))
    w.wall(y=0, tile=WHITE, band=mosaic("8 ST - NYU"))
    w.platform(y=13, edge=YELLOW)
    for x in (9, 25, 41, 57):
        w.column(x, lamp=True)
    return w

def train(song):
    # it stops on one bar line and leaves on another
    stop = bar_line(song, near=0.38)
    leave = bar_line(song, near=0.76)
    return stop, leave

def front(t):
    if t <= stop:                     # ease in
        return STOP - 76 * (1 - t / stop) ** 2.4
    if t <= leave:
        return STOP
    return STOP + 0.016 * (t - leave) ** 2

def riders(song):
    # one off or one on, every beat the doors are open
    return [(b, "off" if k % 2 == 0 else "on")
            for k, b in enumerate(beats(song, stop, leave))]

def frame(i):
    hop = 2 * kick(i)
    waiting.nod(kick(i)); busker.play(beat(i))
    if gone(i): rat.scurry(hats(i))
    return draw_iso(world, train_at(front(i)), riders, hop)
'''
