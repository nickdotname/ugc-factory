"""Pixel world: a blacktop basketball court under a brick wall. A pickup game, two a side: every bounce of the ball is a
hit from the song (the kick and the snare, a third of a second apart at least). After a few dribbles the shot goes up
on one hit and drops through the net on the next; the other side takes it the other way. The bench hops on the kick
and jumps when a shot falls."""
import math
import numpy as np
from vox import *

NAME, PLACE = 'PICKUP GAME', 'blacktop court, every bounce on the beat'
NX, NY, NZ = 60, 40, 20
OX, OY = 115, 172
G = 1                                  # the blacktop: things stand on z = G + 1
RIM_Z = 9
HOOPS = [(7.0, 20.0), (52.0, 20.0)]    # rim centres; team 0 shoots at the right one
FOCUS = [(30, 20, 3), (50, 20, 7), (9, 20, 7)]
GAP = 10                               # frames between two bounces, at least

def build(rng):
    w = World(NX, NY, NZ, seed=int(rng.integers(1 << 30)))
    X, Y, Z = w.grid()
    w.put(Z == 0, DIRT, (60, 56, 58), 6)
    w.put(Z == G, ROCK, (70, 72, 80), 7)                                        # asphalt
    court = (X >= 4) & (X <= 55) & (Y >= 6) & (Y <= 33) & (Z == G)
    w.put(court, CLAY, (52, 104, 104), 6)                                       # painted playing surface
    for hx, s in ((HOOPS[0][0], 1), (HOOPS[1][0], -1)):                         # the keys, painted rust red
        x0, x1 = (4, 14) if s == 1 else (45, 55)
        w.put((X >= x0) & (X <= x1) & (Y >= 15) & (Y <= 24) & (Z == G), CLAY, (172, 84, 62), 7)
    L = (236, 234, 226)
    def line(m): w.put(m & court, LINE, L, 3)
    line((X == 4) | (X == 55) | (Y == 6) | (Y == 33))
    line(X == 30)
    line(np.abs(np.hypot(X - 29.5, Y - 19.5) - 5.2) < 0.6)                      # centre circle
    for (hx, hy), s in zip(HOOPS, (1, -1)):
        x0, x1 = (4, 14) if s == 1 else (45, 55); ft = x1 if s == 1 else x0
        line(((Y == 15) | (Y == 24)) & (X >= x0) & (X <= x1))
        line((X == ft) & (Y >= 15) & (Y <= 24))
        line((np.abs(np.hypot(X - ft, Y - 19.5) - 4.6) < 0.6) & ((X - ft) * s >= 0))           # top of the key
        line((np.abs(np.hypot(X - hx, Y - hy) - 14.0) < 0.6) & ((X - hx) * s >= -2))          # three-point arc
    # hoops: pole, arm, backboard, rim and net
    for (hx, hy), s in zip(HOOPS, (1, -1)):
        hx, hy = int(hx), int(hy); px = hx - 5 * s; bx = hx - 2 * s
        w.box(px, px + 1, hy, hy + 1, G + 1, 12, FENCE, (120, 124, 134), 4)
        w.box(min(px, bx), max(px, bx) + 1, hy, hy + 1, 11, 12, FENCE, (120, 124, 134), 4)
        w.box(bx, bx + 1, hy - 3, hy + 4, RIM_Z, RIM_Z + 4, LINE, (232, 232, 236), 3)
        w.box(bx, bx + 1, hy - 1, hy + 2, RIM_Z + 1, RIM_Z + 3, LINE, (214, 92, 60), 3)        # the shooter's square
        ring = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
        for dx, dy in ring:
            w.box(hx + dx, hx + dx + 1, hy + dy, hy + dy + 1, RIM_Z, RIM_Z + 1, WOOD, (236, 112, 44), 3)
            for z in (RIM_Z - 1, RIM_Z - 2):
                if (dx + dy + z) % 2 == 0: w.box(hx + dx, hx + dx + 1, hy + dy, hy + dy + 1, z, z + 1, NET, (236, 236, 232), 3)
    # the brick building behind the court, some windows lit
    w.put((Y == 0) & (Z >= G + 1) & (Z <= 18), STONE, (150, 78, 62), 9)
    w.bricks(STONE, every=3, dark=0.84)
    for wx in range(3, 57, 6):
        for wz in (5, 10, 15):
            lit = rng.random() < 0.55
            w.box(wx, wx + 3, 0, 1, wz, wz + 3, DARK, (250, 214, 128) if lit else (44, 52, 78), 5)
    # chain-link fence: tall at the back, low at the front so the court shows
    ring = ((X == 1) | (X == 58)) & (Y >= 1) & (Y <= 38) | ((Y == 1) | (Y == 38)) & (X >= 1) & (X <= 58)
    front = ((X == 58) | (Y == 38)) & ring
    tall = np.where(front, 3, 9)
    w.put(ring & (Z >= G + 1) & (Z <= tall) & (((X + Y + Z) % 2) == 0), FENCE, (96, 102, 112), 6)
    w.put(ring & (Z == tall + 1), FENCE, (122, 128, 138), 4)
    w.put(ring & (Z >= G + 1) & (Z <= tall + 1) & (((X % 8) == 1) & ((Y == 1) | (Y == 38)) | ((Y % 8) == 1) & ((X == 1) | (X == 58))), FENCE, (132, 136, 144), 4)
    # a bench along the back line, a street lamp in the corner, a tree
    w.box(20, 40, 3, 5, G + 1, G + 2, WOOD, (124, 92, 60), 6)
    w.box(3, 4, 36, 37, G + 1, 15, FENCE, (84, 88, 96), 3); w.box(3, 6, 36, 37, 15, 16, FENCE, (84, 88, 96), 3)
    w.box(5, 6, 36, 37, 14, 15, SPLASH, (255, 238, 176), 2)
    w.tree(3, 3, G + 1, r=2.8, trunk=4)
    w.shadows()
    return w

def setup(E, rng):
    """The game. One bounce on each kick or snare (thinned). A possession is a few dribbles up the court, a shot that
    leaves on one hit and goes in on the next, and the ball landing under the hoop on the one after."""
    n = E['n']
    cand = sorted(set(int(f) for f in list(E['kicks']) + list(E['snares']) if 0 <= f < n))
    hits = []
    for f in cand:
        if not hits or f - hits[-1] >= GAP: hits.append(f)
    if len(hits) < 6: hits = [int(round(f)) for _, f in E['beats'] if 0 <= f < n]
    segs = []; team = 0; k = 0
    pos = (16.0, float(rng.uniform(15, 25)))
    while k < len(hits) - 1:
        hoop = HOOPS[1 - team]; d = 1 if team == 0 else -1
        left = len(hits) - 1 - k
        nd = int(min(max(left - 2, 0), rng.integers(3, 6)))                      # dribbles before the shot
        spot = (hoop[0] - d * float(rng.uniform(8, 12)), hoop[1] + float(rng.uniform(-6, 6)))
        pts = [pos] + [(pos[0] + (spot[0] - pos[0]) * (j + 1) / max(nd, 1), pos[1] + (spot[1] - pos[1]) * (j + 1) / max(nd, 1) + (1.6 if j % 2 else -1.6) * (j < nd - 1))
                       for j in range(nd)]
        for a, b in zip(pts, pts[1:]):
            segs.append((hits[k], hits[k + 1], 'dribble', a, b, team)); k += 1
        if k >= len(hits) - 1: break
        segs.append((hits[k], hits[k + 1], 'shot', pts[-1], hoop, team)); k += 1
        under = (hoop[0] - d * 1.5, hoop[1] + float(rng.uniform(-1.5, 1.5)))
        team = 1 - team
        if k < len(hits) - 1:
            segs.append((hits[k], hits[k + 1], 'drop', hoop, under, team)); k += 1
        pos = under
    E['segs'] = segs; E['hits'] = hits
    E['makes'] = [(s[1], s[5]) for s in segs if s[2] == 'shot']                  # (frame it goes in, team)
    # where everyone stands each frame: targets from the ball, eased so nobody teleports
    side = [1, -1, -1, 1]; P = np.zeros((n, 4, 2), np.float32)
    cur = np.array([[14, 18], [22, 28], [20, 21], [28, 12]], np.float32)
    for i in range(n):
        x, y, z, s = ball(E, i); team = s[5] if s else 0; d = 1 if team == 0 else -1
        h = team * 2; df = (1 - team) * 2; hoop = HOOPS[1 - team]
        T = cur.copy()
        T[h] = (x - d * 0.9, y + 1.0) if not s or s[2] != 'drop' else (s[4][0], s[4][1] + 1.0)
        T[df] = (x + d * 3.5, 0.6 * y + 0.4 * hoop[1])
        T[h + 1] = (x + d * 7.0, 20 + 10 * side[h + 1]); T[df + 1] = (x + d * 9.0, 20 + 6 * side[df + 1])
        T[:, 0] = np.clip(T[:, 0], 5, 54); T[:, 1] = np.clip(T[:, 1], 7, 32)
        cur = cur + (T - cur) * 0.16
        P[i] = cur
    E['players'] = P
    E['bench'] = [(22 + 3 * k, 4, tuple(int(c) for c in rng.integers(70, 235, 3))) for k in range(6)]

def ball(E, i):
    """Where the ball is, and which stretch of the game it is in."""
    S = E['segs']
    if not S: return 30.0, 20.0, G + 2.0, None
    if i < S[0][0]:                                                              # held, then dropped onto the first hit
        u = max(0.0, 1 - (S[0][0] - i) / 12.0); return S[0][3][0], S[0][3][1], G + 1 + 3.0 * (1 - u * u), S[0]
    for s in S:
        f0, f1, kind, a, b, team = s
        if f0 <= i < f1:
            u = (i - f0) / (f1 - f0); x = a[0] + (b[0] - a[0]) * u; y = a[1] + (b[1] - a[1]) * u
            if kind == 'dribble': z = G + 1 + min(4.5, 1.6 + 0.09 * (f1 - f0)) * 4 * u * (1 - u)
            elif kind == 'shot': z = G + 1 + (RIM_Z + 0.4 - G - 1) * u + 13.0 * u * (1 - u)
            else: z = RIM_Z + 0.4 - (RIM_Z + 0.4 - G - 1) * u * u
            return x, y, z, s
    f0, f1, kind, a, b, team = S[-1]; t = i - f1                                 # after the last hit: picked up and held
    return b[0], b[1], G + 1 + 2.6 * (1 - math.exp(-t / 4.0)), S[-1]

SHIRTS = [(206, 64, 56), (206, 64, 56), (238, 238, 240), (238, 238, 240)]
LEGS = [(34, 34, 44), (34, 34, 44), (60, 84, 160), (60, 84, 160)]

def dynamic(cv, i, E):
    kick = float(E['kick'][i])
    x, y, z, s = ball(E, i)
    made = [f for f, _ in E['makes'] if f <= i]; since = i - made[-1] if made else 999
    for k in range(4):
        px, py = E['players'][i, k]
        jump = 0.0
        if s and s[2] == 'shot' and k == s[5] * 2: jump = 1.6 * math.sin(math.pi * min(1.0, (i - s[0]) / max(8.0, 0.6 * (s[1] - s[0]))))
        xs, ys, zs, cs = person(float(px), float(py), G + 1, SHIRTS[k], jump, legs=LEGS[k])
        cv.draw(xs, ys, zs, cs, PERSON)
        cv.shadow_at(float(px), float(py), G + 2, G, size=1)
    for (bx, by, shirt) in E['bench']:
        xs, ys, zs, cs = person(bx, by, G + 2, shirt, 0.5 * kick + (1.4 * math.sin(math.pi * since / 9.0) if since < 9 else 0.0))
        cv.draw(xs, ys, zs, cs, PERSON)
    cv.shadow_at(x, y, z, G, size=0, strength=0.5)
    cv.draw([x], [y], [z], [[236, 128, 52]], BALL)
    if since < 7:                                                                # it drops: the net kicks out and flashes
        f, team = [m for m in E['makes'] if m[0] <= i][-1]; hx, hy = HOOPS[1 - team]
        for a in range(8):
            r = 1.4 + 0.25 * since
            cv.draw([hx + r * math.cos(a * 0.785)], [hy + r * math.sin(a * 0.785)], [RIM_Z - 0.5 * since], [[255, 250, 214]], SPLASH, faces=(1,))
    score = [sum(1 for f, t in E['makes'] if f <= i and t == 0), sum(1 for f, t in E['makes'] if f <= i and t == 1)]
    return dict(bounces=sum(1 for f in E['hits'] if f <= i), score=score)

def stats(i, E, info, voxels):
    return 'voxels %s   bounces %d   score %d-%d' % (format(voxels, ','), info['bounces'], info['score'][0] * 2, info['score'][1] * 2)

FILE = 'hoops.py'
CODE = '''def world():
    # a blacktop court, drawn block by block
    w = World(60, 40, 20)
    w.put(z == 1, ASPHALT)
    for line in sidelines + keys + arcs + centre_circle:
        w.put(line, PAINT)
    for hoop in hoops:
        w.pole(hoop); w.backboard(hoop); w.rim(hoop, z=9)
    w.wall(y=0, bricks=True, windows=lit(0.55))
    w.fence(mesh=lambda x, y, z: (x + y + z) % 2 == 0)
    return w.shadows(sun=(1.5, 0.45))

def game(song):
    # one bounce on every kick or snare, at least 0.33 s apart
    hits = thin(kicks(song) + snares(song), gap=0.33)
    plays = []
    while hits:
        dribbles = take(hits, randint(3, 5))
        up, in_, down = take(hits, 3)     # the shot leaves, drops, lands
        plays.append((dribbles, up, in_, down))
    return plays

def ball(t):
    a, b = hit_before(t), hit_after(t)
    u = (t - a.t) / (b.t - a.t)
    if a.kind == "shot":                  # up and through the rim
        return lerp(a.pos, rim, u), 13 * u * (1 - u)
    return lerp(a.pos, b.pos, u), bounce(u)

def frame(i):
    hop = 2 * kick(i)
    players.follow(ball(i))
    if swish(i): bench.jump()
    return draw_iso(world, players, ball(i), hop)
'''
