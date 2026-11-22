"""ASCII scene: Sisyphus pushing the boulder uphill, a step on every beat; past the middle of the clip it gets away from him."""
import numpy as np, math
FILE = 'sisyphus.py'
SCALE, FOCAL, CENTER = 210.0, 6.0, 0.52
STEPS, STEP = 64, 0.65
GLOW_MISS, GLOW_W = 0.25, 0.015
GRAD = [(235, 255, 235), (150, 255, 180), (70, 225, 150), (40, 175, 175), (50, 120, 175)]
E = {}; DIST = None; BEAT = None
AL = 0.45; EU = np.array([math.cos(AL), math.sin(AL), 0.0]); EW = np.array([-math.sin(AL), math.cos(AL), 0.0])
R = 0.95; C = np.array([0.95, 0.75, 0.0]); P0 = C - R * EW
ROLL = (9.0, 11.4)                            # when it gets away from him: set from the clip's length in setup

def setup(e):
    global DIST, BEAT, ROLL, CODE
    E.update(e); n = e['n']; t = np.arange(n) / 30
    a = round(0.58 * e['dur'], 1); ROLL = (a, min(e['dur'] - 0.3, a + 2.4))
    CODE = CODE_T.replace('ROLL0', '%.1f' % ROLL[0]).replace('ROLL1', '%.1f' % ROLL[1]).replace('ROLLW', '%.1f' % (ROLL[1] - ROLL[0]))
    speed = np.where((t > ROLL[0]) & (t < ROLL[1]), -2.3 * np.sin(np.pi * (t - ROLL[0]) / (ROLL[1] - ROLL[0])) - 0.2, 0.42 + 0.12 * e['kick'])
    DIST = np.cumsum(speed) / 30; BEAT = t / e['spb']

def W(u, w, z=0.0): return P0 + u * EU + w * EW + np.array([0, 0, z])

def capsule(px, py, pz, a, b, r):
    ba = b - a; qx, qy, qz = px - a[0], py - a[1], pz - a[2]
    h = np.clip((qx * ba[0] + qy * ba[1] + qz * ba[2]) / (ba @ ba), 0, 1)
    return np.sqrt((qx - ba[0] * h) ** 2 + (qy - ba[1] * h) ** 2 + (qz - ba[2] * h) ** 2) - r

def figure(i):
    """The joints, in the slope's frame: leaning into the stone, a step on every beat."""
    rolling = ROLL[0] < i / 30 < ROLL[1]
    ph = math.pi * BEAT[i] * (2.2 if rolling else 1.0); lean = -0.25 if rolling else 0.0
    hip = np.array([-1.75 + lean, 1.0]); sh = np.array([-1.22 + lean * 1.6, 1.62 - abs(lean) * 0.3]); head = sh + np.array([0.2, 0.25])
    hands = [np.array([R * math.cos(math.radians(a)), R + R * math.sin(math.radians(a))]) for a in (160, 178)]
    if rolling: hands = [h + np.array([-0.35, 0.25]) for h in hands]                 # arms thrown up as it goes
    sw = 0.32 * math.sin(ph); feet = [np.array([-1.9 + sw + lean, 0.05 + 0.12 * max(0, math.cos(ph))]), np.array([-1.9 - sw + lean, 0.05 + 0.12 * max(0, -math.cos(ph))])]
    j = dict(hip=hip, sh=sh, head=head, hands=hands, feet=feet)
    return j

def parts(px, py, pz, i):
    # the boulder, rolling: its lumps turn with it
    th = -DIST[i] / R; c, s = math.cos(th), math.sin(th)
    qx, qy, qz = px - C[0], py - C[1], pz - C[2]; qx, qy = qx * c - qy * s, qx * s + qy * c
    lumps = 0.06 * np.sin(2.3 * qx + 1) * np.sin(2.9 * qy + 2) * np.sin(2.1 * qz + 0.5) + 0.03 * np.sin(5.3 * qx + 4.1 * qz) * np.sin(4.7 * qy + 1.3)
    stone = np.sqrt(qx * qx + qy * qy + qz * qz) - R * (1 + 0.02 * E['pulse'][i]) - lumps
    ground = np.maximum((px - P0[0]) * EW[0] + (py - P0[1]) * EW[1], np.abs(pz) - 0.6)   # the hill: a slab of slope, seen side on
    j = figure(i); body = np.full(px.shape, 9.0)
    def seg(a2, b2, r, z): return capsule(px, py, pz, W(a2[0], a2[1], z), W(b2[0], b2[1], z), r)
    body = np.minimum(body, seg(j['hip'], j['sh'], 0.15, 0.0))
    hd = W(j['head'][0], j['head'][1]); body = np.minimum(body, np.sqrt((px - hd[0]) ** 2 + (py - hd[1]) ** 2 + (pz - hd[2]) ** 2) - 0.17)
    for z, hand in zip((0.16, -0.16), j['hands']):
        el = (j['sh'] + hand) / 2 + np.array([0.02, -0.14])
        body = np.minimum(body, np.minimum(seg(j['sh'], el, 0.065, z), seg(el, hand, 0.055, z)))
    for z, ft in zip((0.12, -0.12), j['feet']):
        kn = (j['hip'] + ft) / 2 + np.array([0.15, 0.04])
        body = np.minimum(body, np.minimum(seg(j['hip'], kn, 0.085, z), seg(kn, ft, 0.07, z)))
    return stone, body, ground

def sdf(px, py, pz, i):
    s, b, g = parts(px, py, pz, i); return np.minimum(np.minimum(s, b), g)

LIGHT = np.array([0.45, 0.8, 0.55]); LIGHT /= np.linalg.norm(LIGHT)
MAT = {}
def shade(p, n, rd, i):
    s, b, g = parts(p[:, 0], p[:, 1], p[:, 2], i); w = np.argmin(np.stack([s, b, g]), 0); MAT[i] = w
    lam = np.clip(n @ LIGHT, 0, 1); fres = (1 - np.abs((n * rd).sum(-1))) ** 2
    th = -DIST[i] / R
    rock = 0.15 + 0.7 * lam + 0.3 * fres
    person = 0.3 + 0.6 * lam + 0.6 * fres
    ug = (p - P0) @ EU + DIST[i]
    depth = (P0 - p) @ EW                                            # how far below the surface
    top = n[:, 2] < 0.7                                              # the slope's surface, seen from just above
    face = 0.1 + 0.16 * (np.sin(depth * 9 + 0.8 * np.sin(ug * 2.1)) > 0.55) + 0.05 * np.sin(ug * 6.1 + depth * 3)
    surf = 0.25 + 0.4 * ((ug * 0.9) % 1 < 0.1) + 0.1 * np.sin(ug * 7.3) * np.sin(p[:, 2] * 5.1)
    ground = np.where(top, surf, face * np.clip(1 - depth / 2.2, 0.25, 1))
    return np.select([w == 0, w == 1], [rock, person], ground)

def tint(P, hit, i):
    out = np.zeros(hit.shape); w = MAT.pop(i, None)
    if w is not None: out[hit] = np.select([w == 0, w == 1], [0.25, -0.1], 0.7)
    return out

def colour(yr, xr, t, L): return yr * 0.25 + xr * 0.1

def screen(p):
    k = FOCAL / (FOCAL - p[2]); u, v = p[0] * k, p[1] * k
    return int((-v * SCALE + 66 * 17 * CENTER) / 17), int((u * SCALE + 540) / 9)

rng = np.random.default_rng(5)
def particles(i, rows, cols):
    out = []; t = i / 30
    for kf in E['kicks']:                                            # dust kicked up behind the stone on every kick
        age = (i - kf) / 30
        if 0 <= age < 1.1:
            r2 = np.random.default_rng(int(kf))
            for _ in range(7):
                u0 = r2.uniform(-0.5, 0.1); vz = r2.uniform(-0.6, 0.6); sp = r2.uniform(0.5, 1.4)
                pt = W(u0 - sp * age, 0.05 + 0.6 * age * r2.uniform(0.3, 1) - 0.4 * age * age, vz)
                y, x = screen(pt); out.append((y, x, r2.choice(list(".,`'")), 0.45 * (1 - age / 1.1)))
    return out

def stats(i, sparks):
    h = max(0.0, DIST[i]) * math.sin(AL)
    return 'steps %-4d height %4.1f m   got away %d   sparks %d' % (int(BEAT[i]), h, int(i / 30 > ROLL[0]), sparks)

CODE_T = '''while True:
    push(boulder)        # one step on every beat, forever

def push(b, t):
    # uphill at a walking pace, turning as it rolls
    b.distance += speed(t) * dt
    b.angle = -b.distance / b.radius

def speed(t):
    # then, for a moment, it gets away from him
    if ROLL0 < t < ROLL1:
        return -2.3 * np.sin(np.pi * (t - ROLL0) / ROLLW)
    return 0.42 + 0.12 * kick(t)

def boulder(p, b):
    # a rough ball: lumps that turn with the stone
    q = rotate(p - b.centre, b.angle)
    lumps = 0.06 * np.sin(2.3 * q.x) * np.sin(2.9 * q.y) * np.sin(2.1 * q.z)
    return length(q) - b.radius - lumps

def feet(t):
    # left, right, once per beat
    swing = 0.32 * np.sin(np.pi * beat(t))
    return [-1.9 + swing, -1.9 - swing]
'''
CODE = CODE_T
