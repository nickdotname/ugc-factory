#!/usr/bin/env python3
"""The physics-sims account: satisfying simulations where every collision lands on a hit from the song.

    python studio/physics_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)

The nightly job's renderer for the "physics" style (studio/nightly.py). The hits are found in one stem (all the
drums, the kick, the bass, or the melody in "other"), and the simulation is solved backwards from them: the ball
leaves one wall and arrives at the next exactly on the next hit, so what you see bounce is what you hear.
Scenes (a knob): circle and square (a ball in an arena that fills the screen), rings (a ball inside rotating rings
with gaps; on the big hits it escapes and the ring shatters), pendulum (a pendulum wave tuned to the tempo,
realigning every four bars, each bob flashing as it passes the bottom on a hit).
In circle and square something builds with every bounce, and the first frame says what (the `rule` knob), because a
ball that only bounces gives nobody a reason to stay:
  grow      the ball gets bigger every bounce, until on the last note it fills the arena
  lines     every bounce leaves a line from where it hit to the ball: a web that thickens to the end
  multiply  the balls keep doubling (1, 2, 4 ... 32), every one of them landing on every note
Palette, trail, hit source and the opening line are knobs too. The ball is already flying in frame 0.
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2, librosa, soundfile as sf
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
SKIP = 3          # exit code for "this stretch makes no video": studio/nightly.py skips it instead of failing the night
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish

W, H = 1080, 1920
# 60 fps: half the timing error of 30 (a collision lands within 8 ms of its hit) and smoother flight; Reels keep 60
FPS = int(os.environ.get('CQ_FPS', 60)); audio.FPS = FPS
CX, CY = W / 2, H * 0.47
PALETTES = {'neon': [(255, 60, 200), (60, 200, 255), (255, 220, 60), (120, 255, 140), (180, 110, 255)],
            'sunset': [(255, 120, 80), (255, 190, 90), (255, 90, 140), (200, 80, 200), (255, 230, 160)],
            'ice': [(120, 220, 255), (180, 240, 255), (90, 140, 255), (200, 200, 255), (60, 255, 230)],
            'mono': [(255, 255, 255), (200, 200, 210), (160, 160, 175), (230, 230, 240), (120, 120, 140)],
            'rainbow': [(255, 70, 70), (255, 170, 50), (250, 240, 70), (70, 230, 110), (70, 160, 255), (170, 90, 255)]}


def font(size):
    for p in (os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf'), os.path.join(REPO, 'fonts', 'Poppins-Bold.ttf')):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def stem_hits(song_dir, stem, t0, t1):
    """Hits in one stem, as (seconds from t0, strength), to the millisecond (studio/mathviz/beat.py)."""
    s = json.load(open(os.path.join(song_dir, 'song.json'))); off = float(s.get('stems_start_sec') or 0)
    y, sr = audio.read(os.path.join(song_dir, 'stems', stem + '.ogg'), t0 - off, t1 - off)
    t, st = audio.onsets(y, sr, min_gap=0.09)
    return [(float(x), float(v)) for x, v in zip(t, st) if x < t1 - t0]


def thin(hits, n, gap):
    """At most one hit per `gap` frames, keeping the strongest of any that crowd together (not the first: the first
    of a flam or a hat-then-kick is the weaker one)."""
    out = []
    for f, st in sorted(hits, key=lambda h: -h[1]):
        if 0 < f < n and all(abs(f - g) >= gap for g, _ in out): out.append((f, st))
    return sorted(f for f, _ in out)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.scene = K.pick('scene', ['circle', 'square', 'rings', 'pendulum'], r, weights=[4, 3, 3, 1])
        # what the ball follows: the kick and snare most of the time (the groove you feel), sometimes the kick alone or
        # the lead line. Not the bass: a held bass note has no attack you can see a ball hit.
        self.source = K.pick('hits', ['drums', 'kick', 'melody'], r, weights=[0.6, 0.2, 0.2])
        self.pal = [np.array(c, np.float32) for c in PALETTES[K.pick('palette', sorted(PALETTES), r)]]
        self.trail = K.pick('trail', ['long', 'short', 'ribbon'], r)
        self.hook = K.pick('hook', ['song', 'hits', 'none'], r)
        self.rule = K.pick('rule', ['grow', 'lines', 'multiply'], r) if self.scene in ('circle', 'square') else None
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        # every collision comes from the song's Ableton project: its MIDI notes and the attacks in its arranged audio
        # clips, lined up with the master to a few milliseconds (studio/als_hits.py, studio/project_sync.py)
        P = audio.project(self.slug, t0, t1)
        if P is None: sys.exit('no project hits for %s: run studio/als_hits.py on its Ableton project, then studio/project_sync.py' % self.slug)
        self.split_loop(P, t0, t1)
        to_f = lambda x: int(round(x * FPS))                      # the frame the hit is heard in
        gap = int(round((0.2 if self.scene != 'pendulum' else 0.1) * FPS))
        drums = P['kick'] + P['snare']
        if len(thin([(to_f(x), st) for x, st in drums], n, gap)) < 8: drums = sorted(drums + P['hats'] + P['drums'])   # a sparse kit: its hats too
        pick = {'drums': drums, 'kick': P['kick'] or drums, 'melody': P['lead']}[self.source]
        hits = [(to_f(x), st) for x, st in pick]
        if len(thin(hits, n, gap)) < 8:                           # that part is quiet here: the drums instead
            hits = [(to_f(x), st) for x, st in drums]; self.source = 'drums'
        self.kick = audio.hits(np.array([to_f(x) for x, _ in (P['kick'] or drums)], int), n, 6.0)
        self.strength = {}
        for f, st in hits: self.strength[f] = max(st, self.strength.get(f, 0.0))
        self.bass = np.convolve(a['bass'], np.ones(5) / 5, 'same')
        self.hits = [int(h) for h in thin(hits, n, gap)]
        self.flash = audio.hits(np.array(self.hits), n, 9.0)
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.f_hook, self.f_small, self.f_count = font(64), font(30), font(40)
        sans = next((p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/Library/Fonts/Arial Unicode.ttf') if os.path.exists(p)), None)
        if sans: self.f_small = ImageFont.truetype(sans, 28)
        self.trail_img = np.zeros((H, W, 3), np.float32)
        getattr(self, 'setup_' + self.scene)()

    def split_loop(self, P, t0, t1):
        """A kit bounced as one audio loop comes out of the project as untyped 'drums' hits: every kick, snare, hat and
        ghost note alike, so a ball following them bounces on the hats too and stops feeling like the groove. Each is
        sorted into kick, snare or hat by where its energy sits in the drum stem (beat.drum_kinds)."""
        if not P['drums']: return
        song = json.load(open(os.path.join(audio.SONGS, self.slug, 'song.json'))); off = float(song.get('stems_start_sec') or 0)
        f = os.path.join(audio.SONGS, self.slug, 'stems', 'Drums.ogg')
        if not os.path.exists(f): return
        y, sr = audio.read(f, t0 - off, t1 - off)
        role = {'kick': 'kick', 'snare': 'snare', 'hat': 'hats'}
        for (t, st), k in zip(P['drums'], audio.drum_kinds(y, sr, [t for t, _ in P['drums']])): P[role[k]].append((t, st))
        for k in ('kick', 'snare', 'hats'): P[k].sort()
        P['drums'] = []

    # ---------------------------------------------------------------- scenes: a path through the hits
    def wall_path(self, R_of, rng):
        """Points on a wall, one per hit. Each flight crosses most of the way over (that is what reads as a bounce):
        a long gap between hits is a long chord, a short one a shorter chord, never a skim along the wall."""
        gaps = np.diff(self.hits) if len(self.hits) > 1 else np.array([FPS / 2]); med = max(FPS / 7.5, float(np.median(gaps)))
        ang = rng.uniform(0, 2 * math.pi); pts = [(self.hits[0] if self.hits else 0, ang)]; side = 1
        drift = rng.uniform(0.25, 0.6)                                          # the path turns a little each time: star shapes, not one line
        for k in range(1, len(self.hits)):
            dt = self.hits[k] - self.hits[k - 1]
            chord = float(np.clip(0.6 + 0.4 * dt / med, 0.6, 0.995))            # as a share of the diameter
            turn = math.pi - 2 * math.acos(chord)                                # the angle a chord that long spans
            if rng.random() < 0.3: side = -side
            ang += side * turn + drift + rng.uniform(-0.1, 0.1)
            pts.append((self.hits[k], ang))
        return pts

    def setup_circle(self): self.A = 480.0; self.setup_bounce()

    def setup_square(self): self.A = 470.0; self.setup_bounce()

    def setup_bounce(self):
        """One ball's path through the hits, and for `multiply` the balls that split off it: each new ball leaves from
        where its parent just hit and takes its own way round, and all of them reach a wall on every note."""
        N = len(self.hits); self.pts = self.wall_path(None, self.r); self.paths = [(0, self.pts)]
        if self.rule == 'multiply' and N > 4:
            stages = 5 if N >= 30 else 4 if N >= 16 else 3
            for m in range(1, stages + 1):
                at = max(1, min(N - 1, int(round(N * m / (stages + 1)))))
                for _, parent in list(self.paths):
                    own = self.wall_path(None, random.Random(self.r.random())); d = parent[at][1] - own[at][1]
                    self.paths.append((at, [(h, a + d) for h, a in own]))

    def ball_r(self, j):
        """The ball's radius as it reaches its j-th wall."""
        if self.rule != 'grow': return 26.0
        return 26.0 + (self.A * 0.9 - 26.0) * (j / max(1, len(self.hits) - 1)) ** 1.5

    def setup_rings(self):
        self.rings = [210 + 66 * j for j in range(5)]; self.gap = 0.55; self.spin = [0.9 * (-1) ** j * (1 + 0.15 * j) for j in range(5)]
        bigs = [h for h in self.hits if self.kick[h] > 0.85]
        step = max(1, len(bigs) // 5); self.escapes = [int(b) for b in bigs[step::step][:4]] if bigs else []
        self.level = lambda i: sum(1 for e in self.escapes if e <= i)
        self.pts = []; ang = self.r.uniform(0, 6.28)
        for h in self.hits:
            lvl = self.level(h - 1)
            if h in self.escapes: ang = self.gap_angle(lvl, h)                 # this hit is the escape: aim for the gap
            else:
                g = self.gap_angle(lvl, h); ang = ang + math.pi + self.r.uniform(-0.9, 0.9)
                if abs((ang - g + math.pi) % (2 * math.pi) - math.pi) < self.gap: ang += 2 * self.gap   # never through the gap by accident
            self.pts.append((h, ang))
        self.shards = []; self.paths = [(0, self.pts)]

    def gap_angle(self, j, i): return (self.spin[min(j, 4)] * i / FPS + j * 1.3) % (2 * math.pi)

    def setup_pendulum(self):
        self.N = 15; cycle = 16 * self.spb                                     # they all line up again every four bars
        self.periods = [cycle / (20 + k) for k in range(self.N)]

    def pos(self, i, pts=None):
        """Where a ball is at frame i: between the walls of the last hit and the next one, in a straight line.
        -> x, y, the wall it last reached, how far it is to the next (0..1)"""
        pts = pts or self.pts
        if not pts: return CX, CY, 0, 0.0
        h0, a0 = pts[0]
        if i < h0:                                                             # before the first note: already in flight towards it
            p0 = self.wall_point(a0 + 2.5, self.reach(0)); p1 = self.wall_point(a0, self.reach(0)); u = i / max(1, h0)
            return p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u, 0, 0.0
        k = max((j for j, (h, _) in enumerate(pts) if h <= i), default=0); k1 = min(k + 1, len(pts) - 1)
        h0, a0 = pts[k]; h1, a1 = pts[k1]
        u = 0 if h1 == h0 else min(1, max(0, (i - h0) / (h1 - h0)))
        p0 = self.wall_point(a0, self.reach(k)); p1 = self.wall_point(a1, self.reach(k1))
        return p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u, k, u

    def reach(self, j):
        """How far from the middle the ball's centre is when it touches its j-th wall."""
        if self.scene == 'rings': return self.rings[min(self.level(self.pts[j][0] - 1), 4)] - 22
        return self.A - self.ball_r(j) - 4

    def wall_point(self, a, R):
        if self.scene == 'square':                                             # the point on the square's edge in that direction
            c, s = math.cos(a), math.sin(a); m = max(abs(c), abs(s)); return CX + R * c / m, CY + R * s / m
        return CX + R * math.cos(a), CY + R * math.sin(a)

    # ---------------------------------------------------------------- drawing
    def frame(self, i):
        t = i / FPS; fl = float(self.flash[i]); hitk = sum(1 for h in self.hits if h <= i)
        col = self.pal[hitk % len(self.pal)]
        self.trail_img *= {'long': 0.94, 'short': 0.82, 'ribbon': 0.97}[self.trail] ** (30.0 / FPS)
        layer = np.zeros((H, W, 3), np.float32)
        def P(x, y): return (int(round(x * 16)), int(round(y * 16)))
        if self.scene == 'pendulum':                                        # a pendulum wave seen from above: a snake of bobs
            top, gapy, A = H * 0.17, (H * 0.6) / (self.N - 1), 430
            pts = []
            for k in range(self.N):
                x = CX + A * math.sin(2 * math.pi * t / self.periods[k]); y = top + k * gapy; pts.append((x, y))
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]): cv2.line(layer, P(x0, y0), P(x1, y1), (70, 70, 90), 2, cv2.LINE_AA, 4)
            cv2.line(layer, P(CX, top - 40), P(CX, top + (self.N - 1) * gapy + 40), (50, 50, 64), 2, cv2.LINE_AA, 4)
            for k, (x, y) in enumerate(pts):
                near = abs(x - CX) < 40; c = self.pal[k % len(self.pal)]
                rad = 30 + (18 * fl if near else 0)
                cv2.circle(layer, P(x, y), int(rad * 16), tuple(float(v) for v in c * (1.5 if near and fl > 0.3 else 1.0)), -1, cv2.LINE_AA, 4)
                cv2.circle(self.trail_img, P(x, y), int(10 * 16), tuple(float(v) * 0.18 for v in c), -1, cv2.LINE_AA, 4)
        else:
            if self.scene == 'circle':
                cv2.circle(layer, P(CX, CY), int(self.A * 16), tuple(float(v) for v in col * (0.6 + 0.8 * fl)), 7, cv2.LINE_AA, 4)
            elif self.scene == 'square':
                cv2.rectangle(layer, P(CX - self.A, CY - self.A), P(CX + self.A, CY + self.A), tuple(float(v) for v in col * (0.6 + 0.8 * fl)), 7, cv2.LINE_AA, 4)
            else:
                lvl = self.level(i)
                for j, Rr in enumerate(self.rings):
                    if j < lvl: continue
                    g = self.gap_angle(j, i); c = self.pal[j % len(self.pal)] * (0.5 + (0.8 * fl if j == lvl else 0.2))
                    cv2.ellipse(layer, P(CX, CY), (int(Rr * 16), int(Rr * 16)), 0, math.degrees(g + self.gap), math.degrees(g + 2 * math.pi - self.gap), tuple(float(v) for v in c), 7, cv2.LINE_AA, 4)
                for e in self.escapes:                                         # a ring breaks into pieces when the ball gets out
                    if e <= i < e + 4 * FPS // 3 and not any(s[0] == e for s in self.shards):
                        j = self.escapes.index(e); Rr = self.rings[j]; rr = random.Random(int(e))
                        self.shards += [(e, CX + Rr * math.cos(q), CY + Rr * math.sin(q), rr.uniform(-9, 9), rr.uniform(-14, 4), j) for q in np.linspace(0, 2 * math.pi, 48)]
                for (e, x, y, vx, vy, j) in self.shards:
                    a = (i - e) / FPS
                    if 0 <= a < 1.3: cv2.circle(layer, P(x + vx * a * 30, y + vy * a * 30 + 260 * a * a), 5 * 16, tuple(float(v) for v in self.pal[j % len(self.pal)] * (1 - a / 1.3)), -1, cv2.LINE_AA, 4)
            live = [pp for at, pp in self.paths if at == 0 or hitk > at]       # a ball exists from the note it split off on
            balls = [self.pos(i, pp) for pp in live]; wall = getattr(self, 'A', None)
            if self.rule == 'lines':                                           # every wall it has hit keeps a line to the ball
                x, y = balls[0][:2]
                for j in range(hitk):
                    cx, cy = self.wall_point(self.pts[j][1], wall); fresh = 1.0 if j == hitk - 1 else 0.0
                    cv2.line(layer, P(cx, cy), P(x, y), tuple(float(v) for v in self.pal[j % len(self.pal)] * (0.42 + 0.5 * fresh * fl)), 2, cv2.LINE_AA, 4)
                    cv2.circle(layer, P(cx, cy), 7 * 16, tuple(float(v) for v in self.pal[j % len(self.pal)] * 0.8), -1, cv2.LINE_AA, 4)
            last = max((h for h in self.hits if h <= i), default=None)
            age = (i - last) / FPS if last is not None else 9.0
            if age < 0.3:                                                      # the impact: a ripple and sparks from where each hit
                st = 0.6 + 0.4 * self.strength.get(last, 1.0); u = age / 0.3; c = tuple(float(v) for v in col * (1 - u))
                for b, pp in enumerate(live):
                    a = pp[hitk - 1][1]; cx, cy = self.wall_point(a, wall if wall else self.reach(hitk - 1)); nrm = math.atan2(CY - cy, CX - cx)
                    cv2.circle(layer, P(cx, cy), int((24 + (150 if len(live) <= 8 else 60) * st * u ** 0.6) * 16), c, max(1, int(5 * (1 - u))), cv2.LINE_AA, 4)
                    rr = random.Random(int(last) * 7919 + b)
                    for _ in range(12 if len(live) <= 2 else 5):
                        q = nrm + rr.uniform(-1.25, 1.25); d = rr.uniform(500, 1100) * st * age   # straight out; they fade, not fall
                        cv2.circle(layer, P(cx + d * math.cos(q), cy + d * math.sin(q)), int(max(1.0, 7 * (1 - u)) * 16), c, -1, cv2.LINE_AA, 4)
            small = 26 if len(balls) <= 4 else 21 if len(balls) <= 16 else 17
            for b, (x, y, k, u) in enumerate(balls):
                grown = self.ball_r(k) + (self.ball_r(min(k + 1, len(self.pts) - 1)) - self.ball_r(k)) * u if self.rule == 'grow' else small
                rad = grown * (1 + 0.25 * fl) if grown < 60 else grown; bc = self.pal[(hitk + b) % len(self.pal)]
                if grown < 60:
                    if self.trail == 'ribbon' and len(balls) == 1 and getattr(self, '_last', None):
                        cv2.line(self.trail_img, P(*self._last), P(x, y), tuple(float(v) for v in col * 0.9), int(2 * rad), cv2.LINE_AA, 4)
                    else: cv2.circle(self.trail_img, P(x, y), int(rad * 16), tuple(float(v) * 0.7 for v in bc), -1, cv2.LINE_AA, 4)
                sq = max(0.0, 1 - age / 0.07) if age < 0.07 and grown < 60 else 0.0   # squashed flat against the wall for an instant
                if self.rule == 'grow' and grown >= 40:                        # a big ball is its colour, not a white-out, with a bright rim
                    cv2.circle(layer, P(x, y), int(rad * 16), tuple(float(v) for v in col * (0.42 + 0.2 * fl)), -1, cv2.LINE_AA, 4)
                    cv2.circle(layer, P(x, y), int(rad * 16), (255, 255, 255), 6, cv2.LINE_AA, 4)
                elif sq > 0:
                    nrm_deg = math.degrees(math.atan2(CY - y, CX - x))
                    cv2.ellipse(layer, P(x, y), (int(rad * (1 - 0.38 * sq) * 16), int(rad * (1 + 0.3 * sq) * 16)), nrm_deg, 0, 360, (255, 255, 255), -1, cv2.LINE_AA, 4)
                else: cv2.circle(layer, P(x, y), int(rad * 16), (255, 255, 255), -1, cv2.LINE_AA, 4)
                if fl > 0.6 and grown < 60 and len(balls) <= 8:                # the ring a hit throws out
                    cv2.circle(layer, P(x, y), int(rad * (1 + 3 * (1 - fl)) * 16), tuple(float(v) for v in col), 3, cv2.LINE_AA, 4)
            self._last = balls[0][:2]
        img = self.trail_img + layer
        img = img + cv2.GaussianBlur(img, (0, 0), 14) * (0.7 + 0.6 * fl)       # glow
        img = np.clip(img + np.array([14, 10, 18], np.float32), 0, 255).astype(np.uint8)
        im = Image.fromarray(img); d = ImageDraw.Draw(im)
        # the premise, from the first frame: what builds, and that the bounces are the song (never under Instagram's
        # own buttons: nothing below 80% of the height or in the top 10%)
        says = {'grow': 'the ball grows\nevery bounce', 'lines': 'every bounce\nadds a line', 'multiply': 'the balls\nkeep doubling'}.get(self.rule)
        if says is None and self.hook != 'none': says = 'every bounce is a note\nfrom "%s"' % self.title if self.hook == 'song' else 'every hit is a beat.\nsound on.'
        if says and t < 3.5:
            d.multiline_text((W / 2, 250), says, font=self.f_hook, fill=(255, 255, 255), anchor='mm', align='center', spacing=14, stroke_width=4, stroke_fill=(10, 8, 14))
        elif self.rule and self.hook == 'song' and t < 7:
            d.text((W / 2, 250), 'every bounce is a note from "%s"' % self.title, font=self.f_count, fill=(235, 235, 245), anchor='mm', stroke_width=3, stroke_fill=(10, 8, 14))
        count = '%d' % hitk
        if self.rule == 'lines': count = '%d lines' % hitk
        if self.rule == 'multiply': count = '%d ball%s' % (len(live), '' if len(live) == 1 else 's')
        d.text((W / 2, H * 0.765), count, font=self.f_hook if self.rule else self.f_count, fill=(235, 235, 245), anchor='mm')
        d.text((W / 2, H * 0.80), self.credit, font=self.f_small, fill=(190, 190, 205), anchor='mm')
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; want = set(fs); ims = []
            for i in range(max(fs) + 1):
                fr = self.frame(i)
                if i in want: ims.append(Image.fromarray(fr).resize((360, 640)))
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], len(self.hits), 'hits'); return
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


Video.frame = _polish.wrap(Video.frame, 'physics')      # bloom, grain, grade, vignette: studio/polish.py

def song_end(song_dir):
    """Where the song ends, in master seconds (its stems' length past where they start), or None."""
    song = json.load(open(os.path.join(song_dir, 'song.json')))
    stems = os.path.join(song_dir, 'stems', 'Drums.ogg')
    return sf.info(stems).duration + float(song.get('stems_start_sec') or 0) if os.path.exists(stems) else None


def dead_air(hits, n, first=1.2, gap=4.0):
    """Why this stretch would make a dull video, or None: the first collision too late, or a long wait between two."""
    if not hits: return 'no collisions'
    if hits[0] > first * FPS: return 'first collision at %.1f s' % (hits[0] / FPS)
    waits = np.diff([0] + list(hits) + [n])
    if waits.max() > gap * FPS: return 'a %.1f s wait between collisions' % (waits.max() / FPS)
    return None


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    v = Video(song_dir, seed, t0, t1)
    if v.hits and v.hits[0] > 0.8 * FPS:
        # a section can open with bars of nothing (Prologue's intro): slide the stretch, same length, so the first
        # collision comes in its first second, never past the end of the song
        end = song_end(song_dir); shift = v.hits[0] / FPS - 0.3
        if end: shift = max(0.0, min(shift, end - t1))
        if shift > 0: t0, t1 = t0 + shift, t1 + shift; v = Video(song_dir, seed, t0, t1)
    why = dead_air(v.hits, v.n)
    if why: print('not rendered, the ball would sit still: %s (%s %.1f-%.1f s)' % (why, v.slug, t0, t1)); sys.exit(SKIP)
    v.render(out)
