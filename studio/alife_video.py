#!/usr/bin/env python3
"""Digital creatures: a slime mould of a couple of hundred thousand simple agents finding its shape to one song.

    python studio/alife_video.py SONG_DIR SEED OUT.mp4 [--frames a,b,c]     (CQ_WINDOW="t0,t1")

Each agent only smells the trail in front of it (left, ahead, right), turns toward the strongest, steps forward and
leaves a little trail of its own; the trail spreads and fades. From that the colony draws veins, loops and networks,
the way Physarum polycephalum does. The music is the weather: the kick makes them run, the snare scatters a burst of
new agents from a point, the bass widens how far they look.
Knobs: start (ring, seeds, rain), palette, sense (how far ahead they smell), steps (simulation steps per frame), line (the
opening line, 64 px from frame 0, each true of every video). CQ_WARMUP (default 10) is the number of steps before frame 0:
it was 90, which threw away the best four seconds (the colony exploding out of the seed) before the song started.

goal (food 3 : race 2 : none 1, since 2026-11-27) gives the clip an arc with an end (docs/brain/reviews/2026-11-26/perception.md §4):
  food  3-5 meals (knob `meals`) inside the ring the colony starts as. It falls in on them, then only an agent fresh from
        a meal lays much trail, so the veins that lead nowhere fade and the ones between meals stay. 'connected: N of M'
        is measured every frame off the trail (connected components of the trail above THR); the closing line says
        what it ended at. Opens on 'no brain. five meals. watch.'
  race  two colonies in opposite corners of a walled dish, one meal near the middle; each one's distance to it, and the
        first whose own trail touches it, measured every frame; the end names it ('gold got there on beat 10').
  none  the plain mould, as before (start, species and line apply only here).
With a goal the last 9 frames fade into frame 0, so the reel loops. Every number on screen is measured, never set.
"""
import json, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish
from numba import njit, prange


@njit(parallel=True, fastmath=True, cache=True)
def _move(x, y, h, sp, T, F, sa, sd, turn, speed, jit, avoid, walls):
    """Each agent smells left, ahead and right (its own species' trail, minus the others' when they avoid each
    other, plus the food when there is any: F is 1x1 when there is none), turns toward the strongest, and steps.
    The dish wraps round (off the right edge, back on the left) unless it has walls, which smell of nothing good and
    turn an agent back."""
    S, gh, gw = T.shape; food = F.shape[0] > 1
    for k in prange(x.size):
        best = -1e9; pick = 0
        for j in range(3):
            a = h[k] + (j - 1) * sa
            fx = x[k] + sd * np.cos(a); fy = y[k] + sd * np.sin(a)
            if walls and (fx < 0 or fx >= gw or fy < 0 or fy >= gh):
                v = -1.0
            else:
                sx = int(fx) % gw; sy = int(fy) % gh
                v = F[sy, sx] if food else 0.0
                for q in range(S):
                    v += T[q, sy, sx] if q == sp[k] else -avoid * T[q, sy, sx]
            if j == 1: v += 1e-6                              # ties go straight on
            if v > best: best = v; pick = j
        h[k] += (pick - 1) * turn + jit[k]
        nx = x[k] + speed * np.cos(h[k]); ny = y[k] + speed * np.sin(h[k])
        if walls:
            if nx < 0 or nx >= gw: h[k] = np.pi - h[k]; nx = x[k]
            if ny < 0 or ny >= gh: h[k] = -h[k]; ny = y[k]
        x[k] = nx % gw; y[k] = ny % gh

@njit(fastmath=True, cache=True)
def _deposit(x, y, sp, T, amt, fresh, meal, floor, fade):
    """Each agent leaves trail where it stands. With food on the dish an agent's trail is as strong as it is fresh:
    full on a meal, fading with every step away from one (fade), never below floor. Floor 1 is the plain mould."""
    for k in range(x.size):
        iy = int(y[k]); ix = int(x[k])
        if floor < 1.0:
            if meal[iy, ix]: fresh[k] = 1.0
            else: fresh[k] *= fade
            T[sp[k], iy, ix] += amt * (floor + (1.0 - floor) * fresh[k])
        else:
            T[sp[k], iy, ix] += amt

W, H, FPS = 1080, 1920, 30
GW, GH = 1080, 1640                               # the simulation grid: one cell per pixel (it was half size, scaled up: soft)
NA = int(os.environ.get('CQ_AGENTS', '1200000'))   # agents: enough for the fine lace of the real thing, not a few thick veins
MONO = next(p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', os.path.join(REPO, 'fonts', 'DejaVuSansMono.ttf')) if os.path.exists(p))
HOUSE = os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf')
LINES = {'noplan': 'no brain.\nno plan.', 'rules': 'smell. turn. step.\nno brain.', 'cells': '%s cells.\nno brain.'}   # all true of every video
PALETTES = {'gold': [(0, 0, 0), (90, 30, 0), (255, 170, 40), (255, 250, 220)],
            'bio': [(0, 0, 0), (0, 40, 60), (0, 220, 180), (230, 255, 250)],
            'violet': [(0, 0, 0), (40, 0, 70), (220, 60, 255), (255, 230, 255)],
            'ember': [(0, 0, 0), (70, 0, 10), (255, 60, 40), (255, 230, 160)]}
SPECIES = {'gold': [(255, 170, 40), (255, 90, 60), (255, 240, 200)], 'bio': [(0, 230, 190), (60, 140, 255), (200, 255, 120)],
           'violet': [(220, 60, 255), (60, 120, 255), (255, 120, 200)], 'ember': [(255, 60, 40), (255, 190, 60), (120, 40, 255)]}
NAMES = {'gold': ['gold', 'red', 'cream'], 'bio': ['teal', 'blue', 'lime'], 'violet': ['violet', 'blue', 'pink'], 'ember': ['red', 'amber', 'indigo']}   # a colony's name on screen
GOALS = ['food', 'race', 'none']                  # what the colony is after: meals to join, one meal to reach first, nothing
GOAL_ODDS = [3, 2, 1]
WORDS = {3: 'three', 4: 'four', 5: 'five'}
SCENT = [float(v) for v in os.environ.get('CQ_SCENT', '1.5,24').split(',')]   # a meal's smell: strength (the trail tops out at 2.5), reach in px
MEAL_R = 24                                       # a meal's radius on the grid
THR = float(os.environ.get('CQ_THR', '0.35'))     # trail above this (at a quarter size) counts as colony, wherever something is counted
PRUNE = (0.3, 0.7)                                # with food: the stretch of the clip over which a stale agent's trail fades out
FADE = float(os.environ.get('CQ_FADE', '0.995'))  # how much of its freshness an agent keeps per step away from a meal
RACE_PACE = 0.55                                  # the race's agents walk at this share of the usual speed: the meal is reached mid-clip, not in the first seconds
END, LOOP = 75, 9                                 # the closing line's frames; the frames that fade back into frame 0


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.rng = np.random.default_rng(seed)
        self.start = K.pick('start', ['ring', 'seeds', 'rain'], r)
        self.pal = K.pick('palette', sorted(PALETTES), r)
        self.sense = float(K.pick('sense', [6, 9, 14], r))
        self.steps = int(K.pick('steps', [1, 2], r, weights=[1, 2]))
        self.line = K.pick('line', sorted(LINES), r)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 5.0); self.snare = audio.hits(a['snares'], n, 9.0)
        self.snares = set(int(round(f)) for f in a['snares']); self.bass = np.convolve(a['bass'], np.ones(5) / 5, 'same')
        self.beats = sorted(f for _, f in a['beats'] if f >= -0.5)   # the clip's beats, as frames: "beat 14" is the 14th one heard
        N = NA; g = self.rng
        r2 = random.Random(seed * 13 + 5)                          # its own dice: older seeds keep the rest of their plan
        self.species = int(K.pick('species', [1, 1, 3], r2))       # three colonies that avoid each other's trails
        r3 = random.Random(seed * 31 + 7)                          # and the goal its own again
        self.goal = K.pick('goal', GOALS, r3, weights=GOAL_ODDS)
        meals = int(K.pick('meals', [3, 4, 5], r3))
        if self.goal != 'none':                                    # a goal sets where the colony starts, how many there are and what is said
            for k in ('start', 'species', 'line', 'sense'): K.drop(k)
            self.sense = 14.0                                      # nearer-sighted colonies stay a ring and never cross the dish
        if self.goal != 'food': K.drop('meals')
        self.food = np.zeros((0, 2), np.float32); self.home = None; self.pace = 1.0
        if self.goal == 'food':                                    # a ring around the dish, the meals inside it: the colony falls in on them
            self.species = 1; self.food = self._place(meals, r3); self.start = 'ring'
        elif self.goal == 'race':                                  # a colony in each of two opposite corners, a colour each, the meal in the middle
            self.species = 2; self.food = np.array([[GW / 2 + r3.uniform(-90, 90), GH / 2 + r3.uniform(-140, 140)]], np.float32)   # never quite fair
            self.steps = 2; K.drop('steps'); self.pace = RACE_PACE    # the steps knob would make it a sprint or a crawl: fixed, and slower
            self.home = np.array([[150, 260], [GW - 150, GH - 260]], np.float32)
        if self.goal == 'race':
            k = g.integers(0, 2, N); ang = g.uniform(0, 2 * np.pi, N); rad = g.uniform(0, 1, N) ** 0.5 * 70
            self.x = self.home[k, 0] + rad * np.cos(ang); self.y = self.home[k, 1] + rad * np.sin(ang); self.h = ang
            self.sp = k.astype(np.int64)
        elif self.start == 'ring':
            ang = g.uniform(0, 2 * np.pi, N); rad = g.uniform(0, 1, N) ** 0.5 * 120 + 540
            self.x = GW / 2 + rad * np.cos(ang) * 0.72; self.y = GH / 2 + rad * np.sin(ang) * 1.1; self.h = ang + np.pi
        elif self.start == 'seeds':
            c = g.uniform([160, 240], [GW - 160, GH - 240], (7, 2)); k = g.integers(0, 7, N)
            ang = g.uniform(0, 2 * np.pi, N); rad = g.uniform(0, 50, N)
            self.x = c[k, 0] + rad * np.cos(ang); self.y = c[k, 1] + rad * np.sin(ang); self.h = ang
        else:
            self.x = g.uniform(0, GW, N); self.y = g.uniform(0, GH, N); self.h = g.uniform(0, 2 * np.pi, N)
        self.x, self.y, self.h = self.x.astype(np.float32) % GW, self.y.astype(np.float32) % GH, self.h.astype(np.float32)
        if self.goal != 'race':
            self.sp = (g.integers(0, self.species, N) if self.species > 1 else np.zeros(N, np.int64)).astype(np.int64)
        self.T = np.zeros((self.species, GH, GW), np.float32); self.age = 0
        # the food: a scent every colony smells, kept out of the colonies' own trails (what is counted is the colony's),
        # and the meal cells where an agent counts as fed
        self.F = np.zeros((1, 1), np.float32); self.meal = np.zeros((GH, GW), np.uint8)
        if len(self.food):
            yy, xx = np.mgrid[0:GH, 0:GW].astype(np.float32); self.F = np.zeros((GH, GW), np.float32)
            for fx, fy in self.food:
                d2 = (xx - fx) ** 2 + (yy - fy) ** 2
                self.F += np.where(d2 < (2.5 * SCENT[1]) ** 2, SCENT[0] * np.exp(-d2 / (2 * SCENT[1] ** 2)), 0)   # cut off: any whiff decides a tie, and a tie anywhere would pull them all in
                self.meal[d2 < MEAL_R ** 2] = 1
        self.fresh = np.zeros(N, np.float32)
        sy, sx = np.mgrid[0:GH // 4, 0:GW // 4]
        self.near = [((sx * 4 + 2 - fx) ** 2 + (sy * 4 + 2 - fy) ** 2) < (MEAL_R + 8) ** 2 for fx, fy in self.food]
        self.joined, self.joins = 0, [False] * len(self.food)     # food: the most meals one piece of trail touches, and which
        self.reached, self.won, self.gap = set(), None, [None, None]   # race: who got there, the first (colony, frame), how far each is
        cols = np.array(PALETTES[self.pal], np.float32); xs = np.linspace(0, 1, len(cols))
        self.lut = np.stack([np.interp(np.linspace(0, 1, 256), xs, cols[:, c]) for c in range(3)], -1).astype(np.float32)
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — close quarters' % song.get('title', self.slug).lower()
        self.f_ui = ImageFont.truetype(MONO, 24); self.f_small = ImageFont.truetype(MONO, 22)
        self.f_credit = ImageFont.truetype(MONO, 36)
        house = (lambda px: ImageFont.truetype(HOUSE, px)) if os.path.exists(HOUSE) else (lambda px: self.f_credit)
        self.f_line, self.f_count = house(64), house(52)
        if self.goal == 'food': self.says = 'no brain.\n%s meals.\nwatch.' % WORDS[len(self.food)]
        elif self.goal == 'race': self.says = 'two slimes,\none meal'
        else: self.says = LINES[self.line] % format(self.x.size, ',') if '%s' in LINES[self.line] else LINES[self.line]
        self.first = None

    @staticmethod
    def _place(m, r):
        """m meals well apart, well inside the starting ring (so the count starts at 0) and clear of the written bands."""
        for gap in (360, 320, 280, 250, 220, 190):
            for _ in range(300):
                pts = []
                for _ in range(60 * m):
                    p = (r.uniform(250, GW - 250), r.uniform(380, GH - 560))
                    if ((p[0] - GW / 2) / 389) ** 2 + ((p[1] - GH / 2) / 594) ** 2 > 0.72 ** 2: continue
                    if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= gap ** 2 for q in pts): pts.append(p)
                    if len(pts) == m: return np.array(pts, np.float32)
        return np.array(pts, np.float32)

    def step(self, i):
        sa = 0.39 + 0.15 * self.bass[i]; sd = 2 * self.sense * (1 + 0.6 * self.bass[i])      # at full size it looks twice as far
        jit = self.rng.uniform(-0.05, 0.05, self.x.size).astype(np.float32)
        _move(self.x, self.y, self.h, self.sp, self.T, self.F, np.float32(sa), np.float32(sd), np.float32(0.785), np.float32((1.6 + 3.2 * self.kick[i]) * self.pace), jit, np.float32(.6), self.goal == 'race')
        # with food the colony floods first; then only an agent fresh from a meal lays much trail, so a vein that leads
        # nowhere fades and the ones walked meal to meal stay
        p = i / max(self.n - 1, 1)
        floor = 1.0 if self.goal != 'food' else float(np.clip(1 - (p - PRUNE[0]) / (PRUNE[1] - PRUNE[0]), 0.015, 1))
        _deposit(self.x, self.y, self.sp, self.T, np.float32(0.12 * (1 + self.kick[i])), self.fresh, self.meal, np.float32(floor), np.float32(FADE))
        for q in range(self.species):                         # the trail spreads and fades; a ceiling keeps the colony from collapsing into a few thick veins
            self.T[q] = np.minimum(cv2.blur(self.T[q], (3, 3)) * 0.92, 2.5)

    def burst(self, i):
        """A snare: a few thousand of them are flung out of one point (in the race, each colony's out of its own arc)."""
        k = self.rng.choice(self.x.size, 50000, replace=False)
        if self.goal != 'race':
            px, py = self.rng.uniform([120, 160], [GW - 120, GH - 160])
        else:
            px, py = self.home[self.sp[k], 0], self.home[self.sp[k], 1]
        self.x[k] = px; self.y[k] = py; self.h[k] = self.rng.uniform(0, 2 * np.pi, k.size)

    def advance(self, i):
        pruning = self.goal == 'food' and i / max(self.n - 1, 1) > PRUNE[0]           # a burst would only scribble over the network being pruned
        if i in self.snares and self.snare[i] > 0.5 and not pruning: self.burst(i)
        for _ in range(self.steps): self.step(i)
        self.age += self.steps
        if self.goal != 'none': self.judge(i)

    def judge(self, i):
        """What is said on screen, measured off the trail itself: each colony's trail at a quarter size, above THR, cut
        into the pieces that touch (connected components). With food: the most meals any one piece touches. In the race:
        how far each colony's main body (its biggest piece, not a stray) is from the meal, and the first to touch it."""
        for q in range(self.species):
            sm = self.T[q].reshape(GH // 4, 4, GW // 4, 4).max(axis=(1, 3))     # the brightest of each 4x4: a thin vein still counts
            nl, lab, st, _ = cv2.connectedComponentsWithStats((sm > THR).astype(np.uint8), connectivity=8)
            if self.goal == 'food':
                touch = [set(np.unique(lab[m]).tolist()) - {0} for m in self.near]
                count = np.zeros(nl, int)
                for ps in touch:
                    for c in ps: count[c] += 1
                c = int(np.argmax(count)); self.joined = int(count[c])
                self.joins = [self.joined > 0 and c in ps for ps in touch]
                continue
            if nl < 2: continue
            body = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
            if q not in self.reached and np.any(lab[self.near[0]] == body):
                self.reached.add(q)
                if self.won is None: self.won = (q, i)
                elif self.won[1] == i: self.won = (None, i)        # both on the same frame: a dead heat
            yx = np.argwhere(lab == body)
            self.gap[q] = max(0, int(np.sqrt(((yx[:, 1] * 4 + 2 - self.food[0, 0]) ** 2 + (yx[:, 0] * 4 + 2 - self.food[0, 1]) ** 2).min()) - MEAL_R))

    def beat(self, f):
        """The beat a frame falls on, counted from the clip's first: 1, 2, 3..."""
        return max(1, sum(1 for b in self.beats if b <= f + 0.5))

    def picture(self, i):
        if self.species == 1:
            ref = max(float(np.percentile(self.T[0], 99.7)), 1e-3)        # exposure follows the colony, so it never burns to white
            img = self.lut[(np.clip(self.T[0] / ref, 0, 1) ** 0.8 * 255).astype(np.uint8)]
        else:                                                              # the colonies, a colour each, added as light
            img = np.zeros((GH, GW, 3), np.float32)
            for q, col in enumerate(SPECIES[self.pal][:self.species]):
                ref = max(float(np.percentile(self.T[q], 99.7)), 1e-3)
                img += (np.clip(self.T[q] / ref, 0, 1) ** 0.85)[..., None] * np.array(col, np.float32)
            img = 255 * (1 - np.exp(-img / 255 * 1.2))                     # soft shoulder where they overlap
        small = cv2.resize(img, (GW // 4, GH // 4), interpolation=cv2.INTER_AREA)
        img = img + cv2.resize(cv2.GaussianBlur(small, (0, 0), 5), (GW, GH)) * (0.5 + 0.7 * self.kick[i])
        return np.clip(img, 0, 255)

    def end(self):
        """The closing line, from what was measured."""
        if self.goal == 'food':
            m = len(self.food)
            return ('%s meals.\none network.\nno brain.' % WORDS[m]) if self.joined == m else ('%d of %d meals joined.\nno brain.' % (self.joined, m))
        if self.won is None: return 'neither got there.\nyet.'
        q, f = self.won
        if q is None: return 'a dead heat,\non beat %d' % self.beat(f)
        return '%s got there\non beat %d' % (NAMES[self.pal][q], self.beat(f))

    def frame(self, i):
        self.advance(i)
        out = np.zeros((H, W, 3), np.float32); p = self.picture(i); y0 = 200
        out[y0:y0 + p.shape[0]] = p[:H - y0]
        im = Image.fromarray(out.astype(np.uint8)); d = ImageDraw.Draw(im)
        for j, (fx, fy) in enumerate(self.food):                          # the meals, bright from frame 0; ringed once the network joins them
            cx, cy = fx, fy + y0; on = self.goal == 'food' and self.joins[j]
            if self.won and self.won[0] is not None: on = SPECIES[self.pal][self.won[0]]       # the race's meal takes the winner's colour
            d.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), outline=(on if isinstance(on, tuple) else (255, 255, 255)) if on else (140, 140, 150), width=5 if on else 2)
            d.ellipse((cx - 13, cy - 13, cx + 13, cy + 13), fill=(255, 255, 245))
        closing = self.goal != 'none' and i >= self.n - END
        fading = self.goal != 'none' and i >= self.n - LOOP              # the fade brings frame 0's lines back; two sets crossing would be mush
        # everything written stays inside Instagram's safe area (y 250-1500, left of the right-hand 150 px)
        if not fading: d.multiline_text((W / 2, 262), self.end() if closing else self.says, font=self.f_line, fill=(255, 255, 255), anchor='ma', align='center', spacing=14, stroke_width=5, stroke_fill=(0, 0, 0))
        count = None
        if self.goal == 'food': count = 'connected: %d of %d' % (self.joined, len(self.food))
        elif self.goal == 'race':
            count = '   '.join('%s: %s' % (NAMES[self.pal][q], 'there' if q in self.reached else '%d px' % self.gap[q] if self.gap[q] is not None else '...') for q in range(2))
        if count and not fading: d.text((W / 2 - 40, 1330), count, font=self.f_count, fill=(255, 255, 255), anchor='mm', stroke_width=4, stroke_fill=(0, 0, 0))
        what = {'food': ' · %d meals' % len(self.food), 'race': ' · 2 colonies · 1 meal'}.get(self.goal, ' · 3 colonies' if self.species > 1 else '')
        if not fading: d.text((40, 1400), 'physarum · %s agents%s · step %05d' % (format(self.x.size, ','), what, self.age), font=self.f_ui, fill=(225, 225, 232), anchor='lm', stroke_width=3, stroke_fill=(0, 0, 0))
        d.text((40, 1432), 'each one smells left, ahead, right · turns · steps · leaves a trail', font=self.f_small, fill=(170, 174, 186), anchor='lm', stroke_width=3, stroke_fill=(0, 0, 0))
        d.text((40, 1476), self.credit, font=self.f_credit, fill=(225, 225, 232), anchor='lm', stroke_width=3, stroke_fill=(0, 0, 0))
        img = np.asarray(im)
        if i == 0: self.first = img.copy()
        k = i - (self.n - LOOP) + 1                                       # the last LOOP frames fade into frame 0, so the reel loops
        if self.goal != 'none' and k > 0 and self.first is not None:
            a = k / (LOOP + 1)
            img = (img.astype(np.float32) * (1 - a) + self.first.astype(np.float32) * a).astype(np.uint8)
        return img

    def warm_up(self):
        for _ in range(int(os.environ.get('CQ_WARMUP', '10'))): self.advance(0)       # a few steps so the seed is a shape, not a dot; the network forms on camera

    def render(self, out):
        self.warm_up()
        if '--frames' in sys.argv:                                         # -1 is the last frame
            fs = [self.n - 1 if int(x) < 0 else int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; ims = []
            for f in range(max(fs) + 1):
                if f in fs or f == 0:                                      # frame 0 always: the fade at the end goes back to it
                    im = self.frame(f)
                    if f in fs: ims.append(Image.fromarray(im).resize((360, 640)))
                else: self.advance(f)
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], '|', self.says.replace('\n', ' '), '->', self.end().replace('\n', ' ') if self.goal != 'none' else ''); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n): p.stdin.write(self.frame(i).tobytes())
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'alife')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
