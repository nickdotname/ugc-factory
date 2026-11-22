"""Pixel world: a clay tennis court behind a chain-link fence. Two players rally, and every shot is struck on a hit
from the song (the kick and the snare, a third of a second apart at least); the ball bounces on the far side between
hits, its shadow runs along the clay, and a little crowd watches from the bench."""
import math
import numpy as np
from vox import *

NAME, PLACE = 'MATCH POINT', 'clay court, every shot on the beat'
NX, NY, NZ = 64, 44, 20
OX, OY = 115, 182
FOCUS = [(31, 22, 4), (9, 22, 3), (54, 22, 3)]
CLAY_Z = 1
AX, BX = 7.5, 55.5                    # where the two players stand (baselines)

def build(rng):
    w = World(NX, NY, NZ, seed=int(rng.integers(1 << 30)))
    X, Y, Z = w.grid()
    w.put(Z == 0, DIRT, (104, 80, 58), 8)
    w.put((Z == 1), GRASS, (66, 112, 58), 12)
    surround = (X >= 4) & (X < 60) & (Y >= 4) & (Y < 40) & (Z == CLAY_Z)
    w.put(surround, CLAY, (184, 98, 66), 9)
    L = (236, 232, 222)
    def line(m): w.put(m & (Z == CLAY_Z), LINE, L, 4)
    line(((X == 8) | (X == 55)) & (Y >= 8) & (Y <= 35))
    line(((Y == 8) | (Y == 35) | (Y == 12) | (Y == 31)) & (X >= 8) & (X <= 55))
    line(((X == 18) | (X == 45)) & (Y >= 12) & (Y <= 31))
    line((Y == 21) & (X >= 18) & (X <= 45))
    # the net, its white band and posts
    w.put((X == 31) & (Y >= 6) & (Y <= 37) & (Z >= 2) & (Z <= 3) & ((Y + Z) % 2 == 0), NET, (40, 40, 48), 4)
    w.put((X == 31) & (Y >= 6) & (Y <= 37) & (Z == 4), LINE, (240, 240, 236), 3)
    w.put((X == 31) & ((Y == 5) | (Y == 38)) & (Z >= 2) & (Z <= 4), WOOD, (60, 60, 66), 4)
    # chain-link fence round the court, with a solid top rail and posts every eight
    ring = ((X == 2) | (X == 61)) & (Y >= 2) & (Y <= 41) | ((Y == 2) | (Y == 41)) & (X >= 2) & (X <= 61)
    front = ((X == 61) | (Y == 41)) & ring                                     # the near sides stay low so the court shows
    tall = np.where(front, 3, 9)
    mesh = ring & (Z >= 2) & (Z <= tall) & (((X + Y + Z) % 2) == 0)
    w.put(mesh, FENCE, (96, 102, 112), 6)
    w.put(ring & (Z == tall + 1), FENCE, (120, 126, 136), 4)
    w.put(ring & (Z >= 2) & (Z <= tall + 1) & (((X % 8) == 2) & ((Y == 2) | (Y == 41)) | ((Y % 8) == 2) & ((X == 2) | (X == 61))), FENCE, (130, 134, 142), 4)
    # the umpire's chair and a bench by the net
    w.box(30, 33, 39, 40, 2, 5, WOOD, (112, 82, 54), 6); w.box(30, 33, 38, 40, 5, 6, WOOD, (128, 94, 62), 6)
    w.box(36, 44, 38, 39, 2, 3, WOOD, (120, 88, 58), 6); w.box(36, 44, 39, 40, 3, 4, WOOD, (104, 76, 50), 6)
    w.box(20, 23, 38, 40, 2, 3, DARK, (70, 120, 160), 6)                       # a cooler of balls
    # hedges and trees outside the fence
    w.put(((X <= 1) | (X >= 62) | (Y <= 1) | (Y >= 42)) & (Z >= 2) & (Z <= 3) & ((X * 7 + Y * 3) % 5 != 0), LEAF, (64, 110, 56), 16)
    for (tx, ty, r) in [(4, 4, 3.4), (58, 3, 3.0), (60, 40, 3.2), (3, 41, 2.8)]:
        w.tree(tx, ty, 2, r=r, trunk=3)
    w.shadows()
    return w

def setup(E, rng):
    """The rally: one shot on each kick or snare at least 0.42 s after the last; the players take turns."""
    cand = sorted(set(int(f) for f in list(E['kicks']) + list(E['snares'])))
    hits = []
    for f in cand:
        if not hits or f - hits[-1] >= 13: hits.append(f)
    if len(hits) < 4: hits = [int(round(f)) for _, f in E['beats'] if f >= 0][::2]
    E['shots'] = [(f, k % 2, float(rng.uniform(11, 32))) for k, f in enumerate(hits)]
    E['crowd'] = [(36 + 2 * k, 39, (int(rng.integers(60, 230)), int(rng.integers(60, 230)), int(rng.integers(60, 230)))) for k in range(4)]

def player_y(E, who, i):
    own = [(f, y) for f, w, y in E['shots'] if w == who]
    if not own: return 22.0
    if i <= own[0][0]: return own[0][1]
    for (f0, y0), (f1, y1) in zip(own, own[1:]):
        if f0 <= i < f1:
            u = (i - f0) / (f1 - f0); u = u * u * (3 - 2 * u); return y0 + (y1 - y0) * u
    return own[-1][1]

def ball(E, i):
    """Where the ball is: flying from the last shot to the next one, bouncing once on the receiver's side."""
    S = E['shots']
    for (f0, w0, y0), (f1, w1, y1) in zip(S, S[1:]):
        if f0 <= i < f1:
            u = (i - f0) / (f1 - f0)
            xa = AX + 1.5 if w0 == 0 else BX - 1.5; xb = AX + 1.5 if w1 == 0 else BX - 1.5
            x = xa + (xb - xa) * u; y = y0 + (y1 - y0) * u
            ub = 0.68                                                      # the bounce, on the receiver's side
            if u < ub: v = u / ub; z = CLAY_Z + 1 + 1.4 * (1 - v) + 7.0 * v * (1 - v)
            else: v = (u - ub) / (1 - ub); z = CLAY_Z + 1 + 1.4 * v + 5.0 * v * (1 - v)
            return x, y, z, (f0, i - f0)
    return None

def dynamic(cv, i, E):
    kick = float(E['kick'][i])
    for who, x in ((0, AX), (1, BX)):
        y = player_y(E, who, i)
        xs, ys, zs, cs = person(x, y, CLAY_Z + 1, (196, 70, 60) if who == 0 else (235, 235, 235), 0.0, legs=(230, 230, 230) if who == 0 else (40, 40, 52))
        cv.draw(xs, ys, zs, cs, PERSON)
        last = max((f for f, w, _ in E['shots'] if w == who and f <= i), default=-99)
        sw = i - last
        if 0 <= sw < 6:                                                    # the racket swings through on the shot
            rx = x + (1 if who == 0 else -1); ry = y + (1.2 - 0.4 * sw)
            cv.draw([rx], [ry], [CLAY_Z + 2], [[40, 40, 44]], PERSON)
            if sw < 3: cv.draw([rx + (0.6 if who == 0 else -0.6)], [ry], [CLAY_Z + 3], [[255, 250, 210]], SPLASH, faces=(1,))
        cv.shadow_at(x, y, CLAY_Z + 2, CLAY_Z, size=1)
    for (cx, cy, shirt) in E['crowd']:
        xs, ys, zs, cs = person(cx, cy, 4, shirt, 0.5 * kick)
        cv.draw(xs, ys, zs, cs, PERSON)
    b = ball(E, i)
    if b:
        x, y, z, _ = b
        cv.shadow_at(x, y, z, CLAY_Z, size=0, strength=0.5)
        cv.draw([x], [y], [z], [[226, 232, 80]], BALL)
    return dict(shots=sum(1 for f, _, _ in E['shots'] if f <= i))

def stats(i, E, info, voxels):
    return 'voxels %s   rally %d shots   kicks %d' % (format(voxels, ','), info['shots'], int((E['kicks'] <= i).sum()))

FILE = 'court.py'
CODE = '''def world():
    # a clay court, drawn block by block
    w = World(64, 44, 20)
    w.put(z == 1, CLAY)
    for line in baselines + sidelines + service_lines:
        w.put(line, LINE)
    w.net(x=31, height=4)
    w.fence(mesh=lambda x, y, z: (x + y + z) % 2 == 0)
    return w.shadows(sun=(1.5, 0.45))

def rally(song):
    # one shot on every kick or snare, at least 0.42 s apart
    shots = thin(kicks(song) + snares(song), gap=0.42)
    return [(t, k % 2) for k, t in enumerate(shots)]

def ball(t):
    a, b = shot_before(t), shot_after(t)
    u = (t - a.t) / (b.t - a.t)
    if u < 0.68:                          # over the net
        return lerp(a.pos, bounce, u / 0.68), arc(u / 0.68, 7)
    return lerp(bounce, b.pos, (u - 0.68) / 0.32), arc(u, 5)

def frame(i):
    hop = 2 * kick(i)
    players.run_to(ball(i + lead))
    sparks(tops, snare(i))
    return draw_iso(world, players, ball(i), hop)
'''
