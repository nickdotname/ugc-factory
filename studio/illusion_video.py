#!/usr/bin/env python3
"""Turning things your eyes cannot pin down, to a song: a new niche account's renderer (not live yet).

    python studio/illusion_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/illusion_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

Every video is a real perception effect drawn from scratch, and every line on screen is true of the picture:
  cloud   a shape made of dots, turning, drawn with no depth at all (every dot the same size and brightness, no
          perspective). Which way it turns is undecided, so the brain picks, and can be made to flip. Then the video
          flips it for you: the near side is drawn larger and brighter one way, then the other, then the cue is taken
          away again. Same dots throughout.
  shadow  the same, as a flat filled shadow of the shape (the dancer effect), opening into dots for the two cues
  cone    eccentric circles on a flat disc, turning: they read as a cone coming out of the screen (stereokinetic)
  wheel   a spoked wheel that only ever speeds up; filmed at 30 frames a second it seems to slow, stop and run
          backwards (the wagon-wheel effect), with its true speed counted beside it
  group   twelve dots that are three turning squares and four turning triangles at once; the lines show each
          reading in turn, then go away
  stripes diagonal stripes that are identical in every frame, with discs sliding over them that swap black and
          white inside; the stripes seem to slide, and never do
  necker  a cube of dots standing on a face, turning slowly, seen from a little above with no perspective (a Necker
          cube that turns): which way it turns is up to the viewer. The cue is occlusion: the three edges a solid cube
          would hide fade out, one way (the true cube, seen from above), then the other (the same outline as a cube
          seen from below turning the other way), then every edge comes back
  walker  fifteen dots walking in place (a point-light walker, after Johansson), seen a little from the side with
          no perspective: a walker coming towards you and one walking away make the same picture. The cue: the far
          side's dots drawn smaller and dimmer and hidden behind the body, one way, then the other
  ames    a trapezoid window of dots (an Ames window) turning a full circle, the same way, the whole time; it seems
          to swing back and forth, because the long side reads as near. The cue: the far side drawn dimmer and
          smaller, so it turns; then the cue goes and it swings again
Shapes are our own, built here from formulas (a mug, a knot, a double helix, a tilted cube, a guitar, a ringed planet,
a spiral stair, a chair, a key, an hourglass, a rocket, a tilted donut): none is taken from anywhere, and the staging (a full-screen
object, the flip done for you, the speed readout) is ours; no platform ring, no "difficulty" rating.
One turn takes a whole number of bars, the clip is cut to a whole number of turns and its last 9 frames fade into frame 0,
so it loops without a seam; the dots swell on the kick.
Knobs (studio/knobs.py): kind, shape (cloud and shadow only), palette, ask (the opening question; cloud and shadow only), phase (when the two cues
come: pct = at 42 / 62 / 82 % of the clip, secs = undecided 5 s, cued right 3 s, cued left 3 s, 'you choose' to the end).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
CX, CY, S = W / 2, H * 0.47, 480.0
PALETTES = {'bone': [(245, 240, 225)], 'acid': [(190, 255, 90), (90, 255, 200)], 'ember': [(255, 150, 70), (255, 80, 120)],
            'ice': [(130, 215, 255), (200, 170, 255)], 'candy': [(255, 110, 200), (120, 220, 255), (255, 225, 90)]}
SHAPES = ['mug', 'knot', 'helix', 'cube', 'guitar', 'planet', 'stair', 'chair', 'key', 'hourglass', 'rocket', 'donut']
ASKS = {'which': 'which way\nis it turning?', 'flip': 'left or right?\nnow make it switch', 'sure': 'it turns one way.\nare you sure which?'}


def font(size):
    for p in (os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf'), os.path.join(REPO, 'fonts', 'Poppins-Bold.ttf')):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def box(rng, n, lo, hi):
    """n points on the faces of a box from corner lo to corner hi."""
    lo, hi = np.array(lo, float), np.array(hi, float); p = rng.uniform(lo, hi, (n, 3)); ax = rng.integers(0, 3, n)
    p[np.arange(n), ax] = np.where(rng.random(n) < 0.5, lo[ax], hi[ax]); return p


def lathe(rng, n, prof):
    """n points on the surface made by turning a profile [(radius, height), ...] about the upright axis."""
    prof = np.array(prof, float); k = rng.integers(0, len(prof) - 1, n); u = rng.random(n); a = rng.uniform(0, 2 * np.pi, n)
    r = prof[k, 0] + (prof[k + 1, 0] - prof[k, 0]) * u; y = prof[k, 1] + (prof[k + 1, 1] - prof[k, 1]) * u
    return np.c_[r * np.cos(a), y, r * np.sin(a)]


def tube(rng, n, curve, rad):
    """n points on a tube of radius rad around curve(t), t in 0..1."""
    t = rng.random(n); c = curve(t); d = curve(t + 1e-3) - c; d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
    u = np.cross(d, [0.3, 1.0, 0.2]); u /= np.linalg.norm(u, axis=1, keepdims=True) + 1e-9; v = np.cross(d, u); a = rng.uniform(0, 2 * np.pi, n)[:, None]
    return c + rad * (np.cos(a) * u + np.sin(a) * v)


def cube_edges(e, u):
    """Points on the twelve edges of the cube [-.6, .6]^3 (edge e, 0..11, at u along it), and the outward normals of the
    two faces that meet at each."""
    m = len(e); s1 = np.where((e // 2) % 2, .6, -.6); s2 = np.where(e % 2, .6, -.6); ax = e // 4; idx = np.arange(m)
    p = np.zeros((m, 3)); p[idx, ax] = u; p[idx, (ax + 1) % 3] = s1; p[idx, (ax + 2) % 3] = s2
    n1, n2 = np.zeros((m, 3)), np.zeros((m, 3)); n1[idx, (ax + 1) % 3] = np.sign(s1); n2[idx, (ax + 2) % 3] = np.sign(s2)
    return p, n1, n2


def walker(ph):
    """The 15 points of a person walking in place at gait phase ph (one stride = 2 pi), in metres: x across the body,
    y up from the floor, z the way they walk. Head, neck, pelvis, then per side hip, knee, ankle, shoulder, elbow, wrist;
    the arms swing against the legs, the knee bends most early in the swing, the body rises at mid-stance."""
    bob = .025 * math.cos(2 * ph); sw = .018 * math.sin(ph); out = [(sw, 1.68 + bob, .02), (sw, 1.50 + bob, 0), (sw, .97 + bob, 0)]
    for side, p in ((1, ph), (-1, ph + math.pi)):
        hip = np.array((sw + side * .1, .95 + bob, .035 * math.sin(p))); th = .42 * math.sin(p); kn = .08 + .95 * max(0.0, math.cos(p + .35)) ** 2
        knee = hip + .45 * np.array((0, -math.cos(th), math.sin(th))); ankle = knee + .45 * np.array((0, -math.cos(th - kn), math.sin(th - kn)))
        sh = np.array((sw + side * .19, 1.45 + bob, -.03 * math.sin(p))); a = -.38 * math.sin(p); el = .25 + .2 * max(0.0, -math.sin(p))
        elbow = sh + .29 * np.array((0, -math.cos(a), math.sin(a))); wrist = elbow + .27 * np.array((0, -math.cos(a + el), math.sin(a + el)))
        out += [hip, knee, ankle, sh, elbow, wrist]
    return np.array(out, float)


def ames_window(step=.028):
    """Dots along the bars of an Ames window: a flat trapezoid (one side 1.1 high, the other 0.6) painted as a
    rectangular window seen at an angle, its frame and panes narrowing towards the short side as perspective would."""
    hL, hR, Wd = 1.1, .6, .85; h = lambda x: hL + (hR - hL) * (x + Wd) / (2 * Wd)
    xa, xb = -Wd + .1, Wd - .055; f = .41
    lines = [(-Wd, hL / 2, Wd, hR / 2), (-Wd, -hL / 2, Wd, -hR / 2), (-Wd, -hL / 2, -Wd, hL / 2), (Wd, -hR / 2, Wd, hR / 2),
             (xa, f * h(xa), xb, f * h(xb)), (xa, -f * h(xa), xb, -f * h(xb)), (xa, -f * h(xa), xa, f * h(xa)), (xb, -f * h(xb), xb, f * h(xb)), (xa, 0, xb, 0)]
    for t in (1 / 3, 2 / 3):                                       # the mullions, spaced as on a rectangle seen in perspective
        hh = 1 / ((1 - t) / h(xa) + t / h(xb)); x = xa + (xb - xa) * (hh - h(xa)) / (h(xb) - h(xa)); lines.append((x, -f * hh, x, f * hh))
    pts = []
    for x0, y0, x1, y1 in lines:
        k = max(2, int(math.hypot(x1 - x0, y1 - y0) / step) + 1); u = np.linspace(0, 1, k)
        pts.append(np.c_[x0 + (x1 - x0) * u, y0 + (y1 - y0) * u])
    return np.vstack(pts)


def shape(name, n, seed):
    """n points on one of our shapes, inside the unit cube, upright along y. Each is lopsided on purpose: a shape
    that looks the same all the way round would not seem to turn at all."""
    r = np.random.default_rng(seed); T = 2 * np.pi
    if name == 'mug':
        return np.r_[lathe(r, int(n * .7), [(0, -.6), (.5, -.6), (.5, .6), (.44, .6), (.44, -.5)]),
                     tube(r, n - int(n * .7), lambda t: np.c_[.5 + .34 * np.sin(np.pi * t), .38 * np.cos(np.pi * t), 0 * t], .06)]
    if name == 'donut':                                            # tilted, so it wobbles as it turns
        p = tube(r, n, lambda t: np.c_[.6 * np.cos(T * t), 0 * t, .6 * np.sin(T * t)], .24); c, q = math.cos(.5), math.sin(.5)
        return p @ np.array([[1, 0, 0], [0, c, -q], [0, q, c]]).T
    if name == 'knot':
        return tube(r, n, lambda t: np.c_[(2 + np.cos(3 * T * t)) * np.cos(2 * T * t), 1.25 * np.sin(3 * T * t), (2 + np.cos(3 * T * t)) * np.sin(2 * T * t)] / 3.3, .09)
    if name == 'helix':
        a = tube(r, n * 2 // 5, lambda t: np.c_[.45 * np.cos(2.5 * T * t), 1.8 * t - .9, .45 * np.sin(2.5 * T * t)], .05)
        b = a * [-1, 1, -1]; k = r.integers(0, 14, n - 2 * len(a)); y = (k + .5) / 14 * 1.8 - .9; u = r.uniform(-1, 1, len(k)); th = 2.5 * T * (y + .9) / 1.8
        return np.r_[a, b, np.c_[.45 * u * np.cos(th), y, .45 * u * np.sin(th)]]
    if name == 'cube':
        e = r.integers(0, 12, n); u = r.uniform(-.6, .6, n); p = cube_edges(e, u)[0]
        c, s = math.cos(.62), math.sin(.62); p = p @ np.array([[1, 0, 0], [0, c, -s], [0, s, c]]).T @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]).T
        return p + r.normal(0, .012, p.shape)
    if name == 'guitar':                                           # a flat body, a neck and a head, a finger thick
        out = []
        while len(out) < n:
            x, y = r.uniform(-.5, .5), r.uniform(-.95, .95)
            body = (x / .44) ** 2 + ((y + .58) / .36) ** 2 < 1 or (x / .33) ** 2 + ((y + .2) / .26) ** 2 < 1
            hole = x * x + (y + .33) ** 2 < .012
            neck = abs(x) < .055 and -.1 < y < .78; head = abs(x - .03) < .1 and .78 <= y < .95
            if (body and not hole) or neck or head: out.append((x, y, r.uniform(-.07, .07)))
        return np.array(out)
    if name == 'planet':
        v = r.normal(size=(n // 2, 3)); v = .5 * v / np.linalg.norm(v, axis=1, keepdims=True); a = r.uniform(0, T, n - n // 2); rr = np.sqrt(r.uniform(.72 ** 2, 1, len(a)))
        ring = np.c_[rr * np.cos(a), 0 * a, rr * np.sin(a)]; c, s = math.cos(.45), math.sin(.45)
        return np.r_[v, ring @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]).T]
    if name == 'stair':
        k = r.integers(0, 16, n); u = r.uniform(.08, .8, n); th = k * T / 9 + r.uniform(0, .5, n)
        return np.r_[np.c_[u * np.cos(th), k / 16 * 1.7 - .85 + r.uniform(0, .03, n), u * np.sin(th)][: n * 4 // 5], lathe(r, n - n * 4 // 5, [(.07, -.9), (.07, .9)])]
    if name == 'chair':
        m = n // 6; legs = [box(r, m // 2, (sx * .4 - .05, -.9, sz * .4 - .05), (sx * .4 + .05, -.1, sz * .4 + .05)) for sx in (-1, 1) for sz in (-1, 1)]
        return np.r_[np.vstack(legs), box(r, 2 * m, (-.47, -.1, -.47), (.47, 0, .47)), box(r, n - 4 * (m // 2) - 2 * m, (-.47, 0, .37), (.47, .9, .47))]
    if name == 'key':
        ring = tube(r, n // 2, lambda t: np.c_[.3 * np.cos(T * t), .55 + .3 * np.sin(T * t), 0 * t], .06)
        return np.r_[ring, box(r, n // 3, (-.05, -.9, -.05), (.05, .25, .05)), box(r, n - n // 2 - n // 3, (.05, -.85, -.04), (.3, -.55, .04))]
    if name == 'hourglass':
        return np.r_[lathe(r, n * 3 // 4, [(.5, -.85), (.5, -.75), (.06, 0), (.5, .75), (.5, .85)]), box(r, n - n * 3 // 4, (.42, -.85, -.05), (.52, .85, .05))]
    return np.r_[lathe(r, n * 2 // 3, [(0, .95), (.18, .6), (.24, .1), (.24, -.6), (.14, -.7)]),               # a rocket with three fins, one longer
                 np.vstack([box(r, (n - n * 2 // 3) // 3 + 1, (.22, -.9, -.03), (.36 + .2 * (k == 0), -.3, .03)) @ np.array([[math.cos(k * T / 3), 0, -math.sin(k * T / 3)], [0, 1, 0], [math.sin(k * T / 3), 0, math.cos(k * T / 3)]]) for k in range(3)])]


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed)
        # review 2026-11-26: cloud, shadow and group won (8 of 15 posts got a batch), cone never did, the wheel is slow: cone is off the menu.
        # necker, walker and ames (2026-11-27) follow the winners' formula: a question, the eye picks, a cue flips it, 'you choose'
        self.kind = K.pick('kind', ['cloud', 'shadow', 'cone', 'wheel', 'group', 'stripes', 'necker', 'walker', 'ames'], r, weights=[5, 4, 0, 1, 4, 2, 2, 2, 2])
        self.shape = K.pick('shape', SHAPES, r) if self.kind in ('cloud', 'shadow') else None   # only the kinds that draw a shape record one (the learner saw phantom shapes)
        self.pal = [np.array(c, np.float32) for c in PALETTES[K.pick('palette', sorted(PALETTES), r)]]
        self.ask = K.pick('ask', sorted(ASKS), r); self.phase = K.pick('phase', ['pct', 'secs'], r)
        if self.kind not in ('cloud', 'shadow'): K.drop('ask')                 # the other kinds ask their own question
        a = audio.load(self.slug, t0, t1); n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 6.0)
        self.turn = 8 * self.spb * FPS                                         # frames in a turn: two bars (necker: a quarter turn, after which the cube looks the same)
        if self.kind == 'walker':                                              # a stride (two steps) every two beats: a step on the beat, kept to 75-145 steps a minute
            self.turn = (4 if self.spb < 0.42 else 1 if self.spb > 0.8 else 2) * self.spb * FPS
        self.n = n = int(round(max(1, n // self.turn) * self.turn)); self.t1 = t0 + n / FPS   # whole turns: the last frame runs into the first
        if self.shape: self.pts = shape(self.shape, 5200, seed); self.col = np.array([self.pal[k % len(self.pal)] for k in range(len(self.pts))], np.float32)
        if self.kind == 'necker':                                              # evenly spaced dots, so a quarter turn later every dot is where another was
            e = np.repeat(np.arange(12), 17); self.cube = cube_edges(e, np.tile(np.linspace(-.6, .6, 17), 12)); self.upright = (e // 4) == 1
        if self.kind == 'ames': self.win = ames_window()
        ph = [0.42, 0.62, 0.82]                                                # undecided, cued one way, cued the other, undecided again
        self.marks = [min(int(sec * FPS), int(p * n)) for sec, p in zip((5, 8, 11), ph)] if self.phase == 'secs' else [int(p * n) for p in ph]
        self._first = None
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.f_big, self.f_mid = font(70), font(44)
        sans = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',) if os.path.exists(p)), None)
        self.f_small = ImageFont.truetype(sans, 36) if sans else font(34)                # the credit: 28 px was unreadable on a phone

    def cue(self, i):
        """How strongly depth is shown, and which way round: 0 none, +1 the true near side, -1 the far side as near."""
        a, b, c = self.marks; ramp = lambda x: float(np.clip(x / (0.4 * FPS), 0, 1))
        if i < a: return 0.0
        if self.kind == 'ames': return ramp(i - a) * (1 - ramp(i - (c - 0.4 * FPS))) if i < c else 0.0    # one cue, the true one, then none
        if i < b: return ramp(i - a) * (1 - ramp(i - (b - 0.4 * FPS)))
        if i < c: return -ramp(i - b) * (1 - ramp(i - (c - 0.4 * FPS)))
        return 0.0

    def says(self, i):
        a, b, c = self.marks
        if self.kind == 'cone': return 'this is flat.\ncircles on a disc, turning' if i < a else 'your eyes build a cone\nout of it' if i < c else 'still flat.'
        if self.kind == 'wheel': return 'this wheel only\never speeds up' if i < a else '30 pictures a second\nare fooling you' if i < c else 'it never slowed down.'
        if self.kind == 'group': return 'three squares\nor four triangles?' if i < a else 'three squares' if i < b else 'four triangles' if i < c else 'same twelve dots.\nyou choose'
        if self.kind == 'stripes': return 'the stripes never move' if i < a else 'only the circles do' if i < c else 'pause it and check.'
        if self.kind == 'necker': return 'which way is\nthe cube turning?' if i < a else 'now it turns right →' if i < b else '← now it turns left' if i < c else 'every edge back.\nyou choose'
        if self.kind == 'walker': return 'walking towards you\nor away?' if i < a else 'now it walks\ntowards you' if i < b else 'now it walks\naway from you' if i < c else 'same 15 dots.\nyou choose'
        if self.kind == 'ames': return 'is it turning\nor swinging?' if i < a else 'far side drawn dim:\nit turns full circle' if i < c else 'no cue now.\nit never swings back'
        if i < a: return ASKS[self.ask]
        if i < b: return 'now it turns right →'
        if i < c: return '← now it turns left'
        return 'same dots the whole time.\nyou choose'

    def draw(self, i, top=True):
        img = np.zeros((H, W, 3), np.float32); k = float(self.kick[min(i, len(self.kick) - 1)])
        def P(x, y): return (int(round(x * 16)), int(round(y * 16)))
        if self.kind == 'cone':
            th = 2 * math.pi * i / self.turn
            for j in range(13, 0, -1):
                u = j / 13; off = 170 * (1 - u); c = self.pal[j % len(self.pal)] * (0.55 + 0.45 * (j % 2))
                cv2.circle(img, P(CX + off * math.cos(th), CY + off * math.sin(th)), int(S * 1.0 * u * 16), tuple(float(v) for v in c), 9 + int(6 * k), cv2.LINE_AA, 4)
        elif self.kind == 'wheel':
            N = 12; top = 2.25 * 2 * math.pi / N                               # radians a frame at the end: past two spokes' spacing
            th = 0.5 * top * i * i / max(1, self.n)                            # the angle so far, speed rising steadily from rest
            rpm = top * i / max(1, self.n) * FPS * 60 / (2 * math.pi)
            cv2.circle(img, P(CX, CY), int(S * 1.0 * 16), tuple(float(v) for v in self.pal[0]), 12, cv2.LINE_AA, 4)
            for j in range(N):
                q = th + j * 2 * math.pi / N
                cv2.line(img, P(CX + 60 * math.cos(q), CY + 60 * math.sin(q)), P(CX + S * 0.96 * math.cos(q), CY + S * 0.96 * math.sin(q)), tuple(float(v) for v in self.pal[0]), 14, cv2.LINE_AA, 4)
            cv2.circle(img, P(CX, CY), int((60 + 10 * k) * 16), tuple(float(v) for v in self.pal[-1]), -1, cv2.LINE_AA, 4)
            self._rpm = rpm
        elif self.kind == 'group':
            # Twelve dots at A*u_a + B*v_b: for each a the four are a square, for each b the three are a triangle.
            # Both readings are true at once, so the eye picks one; the lines show each in turn.
            A, B = 0.50 * S, 0.40 * S; al = 2 * math.pi * i / self.turn; be = -2 * math.pi * i / (1.5 * self.turn)
            u = [(A * math.cos(al + 2 * math.pi * j / 3), A * math.sin(al + 2 * math.pi * j / 3)) for j in range(3)]
            v = [(B * math.cos(be + 2 * math.pi * j / 4), B * math.sin(be + 2 * math.pi * j / 4)) for j in range(4)]
            pt = lambda j, m: (CX + u[j][0] + v[m][0], CY + u[j][1] + v[m][1])
            m0, m1, m2 = self.marks; col = lambda j: tuple(float(c) for c in self.pal[j % len(self.pal)])
            if m0 <= i < m1:
                for j in range(3):
                    for m in range(4): cv2.line(img, P(*pt(j, m)), P(*pt(j, (m + 1) % 4)), col(j), 7, cv2.LINE_AA, 4)
            elif m1 <= i < m2:
                for m in range(4):
                    for j in range(3): cv2.line(img, P(*pt(j, m)), P(*pt((j + 1) % 3, m)), col(m), 7, cv2.LINE_AA, 4)
            for j in range(3):
                for m in range(4): cv2.circle(img, P(*pt(j, m)), int((17 + 9 * k) * 16), (245.0, 245.0, 245.0), -1, cv2.LINE_AA, 4)
        elif self.kind == 'necker':
            # Orthographic, so the outline is the same for this cube seen from above and its mirror seen from below turning
            # the other way. The cue hides the edges on no face towards the viewer: the true ones (cue > 0), then the mirror's.
            th = 0.4 + 0.5 * math.pi * i / self.turn; ct, st = math.cos(th), math.sin(th); el = 0.38; cu = self.cue(i); sg = 1.0 if cu >= 0 else -1.0
            def view(v):                                                       # screen x, screen y (up), depth (towards us)
                x = v[:, 0] * ct + v[:, 2] * st; z = -v[:, 0] * st + v[:, 2] * ct
                return x, v[:, 1] * math.cos(el) - z * math.sin(el), z * math.cos(el) + v[:, 1] * math.sin(el)
            p, n1, n2 = self.cube; x, y, _ = view(p)
            vis = np.maximum(np.clip((sg * view(n1)[2] + .03) / .1, 0, 1), np.clip((sg * view(n2)[2] + .03) / .1, 0, 1))
            al = 1 - abs(cu) * (1 - vis); sc = S
            for j in np.argsort(al, kind='stable'):
                c = (self.pal[0] if self.upright[j] else self.pal[-1]) * al[j]
                cv2.circle(img, P(CX + sc * x[j], CY - sc * y[j]), int((6.5 + 2.5 * k) * 16), tuple(float(v) for v in c), -1, cv2.LINE_AA, 4)
        elif self.kind == 'walker':
            # Seen 0.5 rad off head-on, no perspective: the dots of a walker coming towards you, mirrored in depth, are a
            # walker going away. The cue: the far side smaller, dimmer, and hidden where the body is in front of it.
            q = walker(2 * math.pi * i / self.turn); yaw = 0.5; cu = self.cue(i); sc = 520.0; gy = 1415
            x = q[:, 0] * math.cos(yaw) + q[:, 2] * math.sin(yaw); d = -q[:, 0] * math.sin(yaw) + q[:, 2] * math.cos(yaw)
            sx, sy = CX + sc * x, gy - sc * q[:, 1]; near = cu * d / 0.2
            body = np.array([(sx[j], sy[j]) for j in (6, 12, 9, 3)], np.float32)   # shoulders and hips
            mid = body.mean(0); body = (mid + (body - mid) * 1.25).astype(np.float32)
            for j in np.argsort(near, kind='stable'):
                hid = near[j] < -0.15 and cv2.pointPolygonTest(body, (float(sx[j]), float(sy[j])), False) >= 0
                a = 1 - abs(cu) if hid else 1.0
                lum = float(np.clip(1 + 0.5 * near[j], 0.35, 1.5)) * a; rad = (15 + 5 * k) * float(np.clip(1 + 0.3 * near[j], 0.6, 1.4))
                if a > 0.02: cv2.circle(img, P(sx[j], sy[j]), int(rad * 16), tuple(float(v) for v in self.pal[0] * lum), -1, cv2.LINE_AA, 4)
        elif self.kind == 'ames':
            # A flat window turning about its upright centre line, drawn with no perspective. Cue: the true far side dimmer
            # and smaller. Nothing else changes; the window turns the same way at the same speed throughout.
            th = 0.6 + 2 * math.pi * i / self.turn; cu = self.cue(i); px, py = self.win[:, 0], self.win[:, 1]
            sx, sy = CX + S * px * math.cos(th), CY - S * py; near = cu * (-px * math.sin(th)) / 0.85
            lum = np.clip(1 + 0.85 * near, 0.15, 1.5); rad = (5.5 + 2.5 * k) * (1 + 0.4 * near)
            for j in np.argsort(near, kind='stable'):
                c = self.pal[j % len(self.pal)] * lum[j]
                cv2.circle(img, P(sx[j], sy[j]), int(max(1.0, rad[j]) * 16), tuple(float(v) for v in c), -1, cv2.LINE_AA, 4)
        elif self.kind == 'stripes':
            # Diagonal stripes that are the same in every frame. Discs slide across; inside a disc black and white
            # swap. Nothing striped ever moves, but the stripes seem to slide and ripple.
            R = int(S * 1.05); yy, xx = np.mgrid[-R:R, -R:R]; wd = 34
            stripe = (((xx + yy) // wd) % 2).astype(np.float32); mask = np.zeros(stripe.shape, np.uint8)
            sp = 2 * R / (4 * self.spb * FPS)                                  # one crossing every bar
            for row, dy in enumerate((-0.62, 0.0, 0.62)):
                for q in range(3):
                    x = ((q * 2 * R / 3 + (1 if row % 2 == 0 else -1) * sp * i) % (2 * R + 260)) - R - 130
                    cv2.circle(mask, (int(x + R), int(dy * R + R)), 118, 255, -1, cv2.LINE_AA)
            val = np.where(mask > 127, 1 - stripe, stripe) * (215 + 40 * k)
            x0, y0 = int(CX) - R, int(CY) - R
            img[y0:y0 + 2 * R, x0:x0 + 2 * R] = val[..., None] * (np.array(self.pal[0], np.float32) / 255.0 * 0.25 + 0.75)
            cv2.rectangle(img, (x0, y0), (x0 + 2 * R, y0 + 2 * R), tuple(float(c) for c in self.pal[-1]), 6)
        else:
            th = 2 * math.pi * i / self.turn; cu = self.cue(i); ct, st = math.cos(th), math.sin(th); e = 0.2  # seen from a little above
            x = self.pts[:, 0] * ct + self.pts[:, 2] * st; z = -self.pts[:, 0] * st + self.pts[:, 2] * ct
            y = self.pts[:, 1] * math.cos(e) - z * math.sin(e); near = cu * z                                # +1: towards us
            pers = 1 / (1 - 0.22 * near); sx = CX + S * x * pers; sy = CY - S * y * pers
            if self.kind == 'shadow' and abs(cu) < 0.05:                       # a flat shadow: no dot tells you front from back
                m = np.zeros((H, W), np.uint8)
                for px, py in zip(sx, sy): cv2.circle(m, (int(px), int(py)), 11, 255, -1)
                m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))
                img[m > 0] = self.pal[0] * (0.85 + 0.15 * k)
            else:
                rad = (3.6 + 1.6 * k) * (1 + 0.75 * near); lum = np.clip(0.9 + 0.75 * near, 0.18, 1.6)
                for j in np.argsort(near):                                     # far ones first, so near ones cover them when cued
                    cv2.circle(img, P(sx[j], sy[j]), int(max(1.0, rad[j]) * 16), tuple(float(v) for v in self.col[j] * lum[j]), -1, cv2.LINE_AA, 4)
        if self.kind != 'stripes': img = img + cv2.GaussianBlur(img, (0, 0), 9) * 0.35
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        if top: d.multiline_text((W / 2, 300), self.says(i), font=self.f_big, fill=(255, 255, 255), anchor='mm', align='center', spacing=16, stroke_width=4, stroke_fill=(0, 0, 0))
        if self.kind == 'wheel': d.text((W / 2, 1418), '%d turns a minute' % self._rpm, font=self.f_mid, fill=(235, 235, 245), anchor='mm')
        d.text((W / 2, 1472), self.credit, font=self.f_small, fill=(180, 180, 195), anchor='mm')   # inside Instagram's safe area (y 250-1500)
        return np.asarray(im)

    def frame(self, i):
        """The last 9 frames fade into frame 0 (as stare_video.py does): a clean loop on an account whose viewers replay."""
        tail = 9; o = self.draw(i, top=i < self.n - tail - 4)      # the last line clears just before the fade, so two lines never cross
        if i >= self.n - tail:
            if self._first is None: self._first = self.draw(0).astype(np.float32)
            a = (i - (self.n - tail) + 1) / (tail + 1)
            o = (o.astype(np.float32) * (1 - a) + self._first * a).astype(np.uint8)
        return o

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', round(self.n / self.turn, 2), 'turns', 'marks', self.marks); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 60 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 44.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
