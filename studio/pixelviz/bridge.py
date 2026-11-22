"""Pixel world: an old stone bridge over a river. People cross it stepping on the beat, the water glitters on the
hats, ripples ring out round the rocks on the kicks, and on the big hit someone dives off the top of the arch and
lands with a splash two beats later."""
import math
import numpy as np
from vox import *

NAME, PLACE = 'OLD BRIDGE', 'river at dusk'
N = 60
RIVER = (23, 37)                      # the river runs along x, between these y
BRIDGE_X = (28, 33)                   # the bridge crosses it here, along y
Y0, Y1 = 14, 46                       # where the bridge starts and ends
WATER_Z = 2
OY = 168
FOCUS = [(31, 30, 16), (40, 33, 3), (25, 12, 18), (36, 44, 8)]      # close-ups: the top of the arch, the rocks, the tower, the far end

def deck(y):
    """Height of the bridge's walking surface at y: a steep hump, highest over the middle of the river."""
    u = np.clip((y - Y0) / (Y1 - Y0), 0, 1)
    return 6 + 9 * np.sin(np.pi * u) ** 1.3

def build(rng):
    w = World(N, N, 36, seed=int(rng.integers(1 << 30)))
    X, Y, Z = w.grid()
    river = (Y >= RIVER[0]) & (Y < RIVER[1])
    bank = (Y < RIVER[0]) | (Y >= RIVER[1])
    w.put(bank & (Z <= 4) & (Z >= 0), DIRT, (110, 86, 62), 10)
    w.put(bank & (Z == 5), GRASS, (74, 122, 62), 14)
    # stone embankments along both banks
    w.put(((Y == RIVER[0] - 1) | (Y == RIVER[1])) & (Z <= 5), STONE, (176, 170, 156), 12)
    w.put(river & (Z <= WATER_Z - 1), DIRT, (60, 70, 70), 6)
    w.put(river & (Z == WATER_Z), WATER, (38, 112, 132), 7)
    # boulders in the water near the banks
    for (bx, by, r) in [(18, 25, 2.2), (21, 26, 1.6), (40, 35, 2.0), (44, 34, 1.5), (36, 24.5, 1.4), (12, 35, 1.8)]:
        w.sphere(bx, by, WATER_Z + 0.6, r, ROCK, (196, 190, 178), 12, squash=0.8)
    # the bridge: a stone hump with an arch cut out over the water and a low parapet each side
    hx = (X >= BRIDGE_X[0]) & (X < BRIDGE_X[1]); top = deck(Y)
    body = hx & (Y >= Y0) & (Y < Y1) & (Z <= top) & (Z >= 3)
    mid = (RIVER[0] + RIVER[1]) / 2; half = (RIVER[1] - RIVER[0]) / 2 + 0.5
    under = WATER_Z + 10.5 * np.sqrt(np.clip(1 - ((Y - mid + 0.5) / half) ** 2, 0, 1))
    body &= ~((Y >= RIVER[0] - 0) & (Y < RIVER[1]) & (Z < under))
    w.put(body, STONE, (206, 200, 186), 13)
    par = ((X == BRIDGE_X[0]) | (X == BRIDGE_X[1] - 1)) & (Y >= Y0) & (Y < Y1) & (Z > top) & (Z <= top + 1)
    w.put(par, STONE, (214, 208, 194), 10)
    # a square tower at the near end, a round one with a cone roof at the far end
    w.box(22, 29, 9, 16, 5, 24, STONE, (198, 192, 178), 12)
    w.box(21, 30, 8, 17, 24, 25, STONE, (186, 180, 166), 10)
    for zz in (10, 16, 20):
        w.box(22, 23, 11, 13, zz, zz + 2, DARK, (34, 30, 30), 2); w.box(24, 26, 9, 10, zz, zz + 2, DARK, (34, 30, 30), 2)
    rr = (X - 38.5) ** 2 + (Y - 13.5) ** 2
    w.put((rr <= 16) & (Z >= 5) & (Z < 20), STONE, (194, 188, 174), 12)
    w.put((rr <= (4 - (Z - 20) * 0.55) ** 2) & (Z >= 20) & (Z < 27), ROOF, (128, 124, 122), 8)
    w.box(36, 37, 15, 17, 12, 14, DARK, (34, 30, 30), 2)
    # little houses with red roofs on both banks
    for (hx0, hy0, hw, hd) in [(10, 8, 6, 5), (40, 47, 6, 6), (14, 48, 5, 5)]:
        w.box(hx0, hx0 + hw, hy0, hy0 + hd, 6, 11, STONE, (222, 214, 196), 8)
        for k in range(4):
            w.box(hx0 - 1 + k, hx0 + hw + 1 - k, hy0 - 1, hy0 + hd + 1, 11 + k, 12 + k, ROOF, (184, 92, 62), 10)
        w.box(hx0 + 2, hx0 + 3, hy0 + hd - 1, hy0 + hd, 7, 9, DARK, (40, 32, 28), 2)
    w.bricks(STONE)
    for (tx, ty) in [(6, 16), (15, 14), (50, 18), (52, 42), (8, 42), (24, 52), (50, 54), (55, 30), (46, 8)]:
        w.tree(tx, ty, 6, r=2.6 + rng.uniform(0, 1.2), trunk=2 + int(rng.integers(0, 2)))
    w.shadows()
    return w

def setup(E, rng):
    """Who walks, where the diver goes and when."""
    E['walkers'] = [dict(x=BRIDGE_X[0] + 1 + (k % 3), y0=Y0 + 2 + rng.uniform(0, Y1 - Y0 - 4), dirn=1 if k % 2 else -1,
                         speed=rng.uniform(0.18, 0.32), shirt=tuple(int(c) for c in rng.choice(
                             [(196, 70, 60), (70, 110, 190), (230, 190, 70), (90, 150, 90), (180, 90, 160), (220, 220, 220), (240, 140, 60)])))
                    for k in range(9)]
    beats = [b for _, b in E['beats']]
    big = E['big'] or (beats[len(beats) // 2] if beats else E['n'] // 2)
    E['dive'] = (big, big + int(round(2 * E['spb'] * 30)))           # jumps on the big hit, lands two beats later

def dynamic(cv, i, E):
    t = i / 30
    step = float(E['kick'][i]) * 0.5
    for wkr in E['walkers']:
        span = Y1 - Y0 - 3
        y = Y0 + 1.5 + ((wkr['y0'] - Y0 + wkr['dirn'] * wkr['speed'] * i) % span)
        z = deck(np.array(y)) + 1
        xs, ys, zs, cs = person(wkr['x'], y, float(z), wkr['shirt'], step)
        cv.draw(xs, ys, zs, cs, PERSON)
    j0, j1 = E['dive']
    ytop = (RIVER[0] + RIVER[1]) / 2
    if i < j0:
        xs, ys, zs, cs = person(BRIDGE_X[1] - 1, ytop, float(deck(np.array(ytop))) + 2, (250, 250, 250), 0)
        cv.draw(xs, ys, zs, cs, PERSON)
    elif i < j1:
        u = (i - j0) / max(1, j1 - j0)
        x = BRIDGE_X[1] - 0.5 + 6 * u; z0 = float(deck(np.array(ytop))) + 2
        z = z0 + 4 * math.sin(math.pi * min(u * 1.6, 1)) * (1 - u) - (z0 - WATER_Z) * u ** 2
        xs, ys, zs, cs = person(x, ytop, z, (250, 250, 250), 0)
        cv.draw(xs, ys, zs, cs, PERSON); cv.shadow_at(x, ytop, z, WATER_Z)
    # the splash, and the rings it leaves
    if j1 <= i < j1 + 40:
        a = (i - j1) / 40.0; r2 = np.random.default_rng(j1)
        n = 26; ang = r2.uniform(0, 2 * np.pi, n); sp = r2.uniform(1.5, 4.5, n); up = r2.uniform(4, 9, n)
        sx = BRIDGE_X[1] + 5.5 + np.cos(ang) * sp * a * 2; sy = ytop + np.sin(ang) * sp * a * 2
        sz = WATER_Z + 1 + up * a * 1.6 - 14 * a * a
        keep = sz > WATER_Z
        cv.draw(sx[keep], sy[keep], sz[keep], np.tile([[235, 245, 250]], (int(keep.sum()), 1)), SPLASH, faces=(1,))
    return dict(people=len(E['walkers']) + 1)

def water(cv, rgb, i, E):
    """Glitter and ripples on the water pixels: moving dither stripes, bright flecks on the hats, rings on kicks."""
    m = cv.mat == WATER
    if not m.any(): return rgb
    h, w = m.shape; yy, xx = np.mgrid[0:h, 0:w]
    t = i / 30
    band = (np.sin((xx * 0.9 + yy * 1.7) * 0.55 - t * 3.0) > 0.86) & ((xx + yy + i // 3) % 3 == 0)
    rgb[m & band] = rgb[m & band] * 1.25 + 18
    hat = float(E['hat'][i])
    if hat > 0.2:
        rr = np.random.default_rng(i)
        fl = rr.random((h, w)) < 0.012 * hat
        rgb[m & fl] = (220, 245, 250)
    k = float(E['kick'][i])
    if k > 0.05:
        for (bx, by) in [(18, 25), (40, 35), (12, 35)]:
            sx, sy = cv.screen(bx, by, WATER_Z)
            rad = 3 + (1 - k) * 9
            ring = np.abs(np.hypot((xx - sx) / 2.0, yy - sy) - rad) < 0.6
            rgb[m & ring] = rgb[m & ring] * (1 + 0.6 * k) + 25 * k
    return rgb

def stats(i, E, info, voxels):
    return 'voxels %s   people %d   kicks %d' % (format(voxels, ','), info['people'], int((E['kicks'] <= i).sum()))

FILE = 'bridge.py'
CODE = '''def world():
    # every block is placed by code: no sprites, no image files
    w = World(60, 60, 36)
    w.put(bank & (z <= 4), DIRT)
    w.put(river & (z == 2), WATER)
    for y in range(14, 46):
        top = 6 + 9 * sin(pi * (y - 14) / 32) ** 1.3
        w.column(x=28, y=y, z0=3, z1=top, mat=STONE)
    w.cut(arch(mid=30, half=7.5))          # the arch over the river
    w.tower(22, 9, height=24)
    w.tree(6, 16, r=3.2)
    return w.shadows(sun=(1.5, 0.45))     # long shadows from a low sun

def frame(i):
    hop = 2 * kick(i)                     # the world hops on the kick
    for p in people:
        p.y += p.speed                    # crossing the bridge
        p.z = deck(p.y) + step(i)         # stepping on the beat
    if i == big_hit:
        diver.jump(lands=i + 2 * beat)    # splash two beats later
    glitter(water, hats(i))
    sparks(tops, snare(i))
    return draw_iso(world, people, hop)
'''
