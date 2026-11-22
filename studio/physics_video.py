#!/usr/bin/env python3
"""The physics-sims account: satisfying simulations where every collision lands on a hit from the song.

    python studio/physics_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)

The nightly job's renderer for the "physics" style (studio/nightly.py). The hits are found in one stem (all the
drums, the kick, the bass, or the melody in "other"), and the simulation is solved backwards from them: the ball
leaves one wall and arrives at the next exactly on the next hit, so what you see bounce is what you hear.
Scenes (a knob): circle (a ball in a ring, trailing light), square (a bouncing square in a box that shrinks on
every hit), rings (a ball inside rotating rings with gaps; on the big hits it escapes and the ring shatters),
pendulum (a pendulum wave tuned to the tempo, realigning every four bars, each bob flashing as it passes the
bottom on a hit). Palette, trail, hit source and the opening line are knobs too.
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2, librosa, soundfile as sf
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

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
        self.scene = K.pick('scene', ['circle', 'square', 'rings', 'pendulum'], r)
        # what the ball follows: the kick and snare most of the time (the groove you feel), sometimes the kick alone or
        # the lead line. Not the bass: a held bass note has no attack you can see a ball hit.
        self.source = K.pick('hits', ['drums', 'kick', 'melody'], r, weights=[0.6, 0.2, 0.2])
        self.pal = [np.array(c, np.float32) for c in PALETTES[K.pick('palette', sorted(PALETTES), r)]]
        self.trail = K.pick('trail', ['long', 'short', 'ribbon'], r)
        self.hook = K.pick('hook', ['song', 'hits', 'none'], r)
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

    def setup_circle(self):
        self.R = 400.0; self.pts = self.wall_path(lambda i: self.R - 20, self.r); self.balls = 1
        drops = [h for h in self.hits if self.kick[h] > 0.9 and self.bass[h] > 0.8]
        self.split = drops[len(drops) // 2] if len(drops) > 4 else None

    def setup_square(self):
        self.S0 = 900.0; n = max(1, len(self.hits)); self.shrink = 0.55 / n
        self.pts = self.wall_path(lambda i: self.side(i) / 2 - 30, self.r)

    def side(self, i):
        k = sum(1 for h in self.hits if h <= i); return self.S0 * (1 - self.shrink * k)

    def setup_rings(self):
        self.rings = [190 + 62 * j for j in range(5)]; self.gap = 0.55; self.spin = [0.9 * (-1) ** j * (1 + 0.15 * j) for j in range(5)]
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
        self.shards = []

    def gap_angle(self, j, i): return (self.spin[min(j, 4)] * i / FPS + j * 1.3) % (2 * math.pi)

    def setup_pendulum(self):
        self.N = 15; cycle = 16 * self.spb                                     # they all line up again every four bars
        self.periods = [cycle / (20 + k) for k in range(self.N)]

    def pos(self, i):
        """Where the ball is at frame i: between the walls of the last hit and the next one, in a straight line."""
        pts = self.pts
        if not pts: return CX, CY, 0
        k = max(0, max((j for j, (h, _) in enumerate(pts) if h <= i), default=0))
        h0, a0 = pts[k]; h1, a1 = pts[min(k + 1, len(pts) - 1)]
        u = 0 if h1 == h0 else min(1, max(0, (i - h0) / (h1 - h0)))
        R0, R1 = self.radius_at(h0), self.radius_at(h1)
        p0 = self.wall_point(a0, R0, h0); p1 = self.wall_point(a1, R1, h1)
        return p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u, k

    def contact(self, h):
        """Where on the wall the ball hit at frame h."""
        a = next((a for hh, a in self.pts if hh == h), 0.0)
        return self.wall_point(a, self.radius_at(h), h)

    def radius_at(self, i):
        if self.scene == 'circle': return self.R - 20
        if self.scene == 'square': return self.side(i - 1) / 2 - 30
        return self.rings[min(self.level(i - 1), 4)] - 22

    def wall_point(self, a, R, i):
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
            top, gapy, A = H * 0.2, (H * 0.56) / (self.N - 1), 330
            pts = []
            for k in range(self.N):
                x = CX + A * math.sin(2 * math.pi * t / self.periods[k]); y = top + k * gapy; pts.append((x, y))
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]): cv2.line(layer, P(x0, y0), P(x1, y1), (70, 70, 90), 2, cv2.LINE_AA, 4)
            cv2.line(layer, P(CX, top - 40), P(CX, top + (self.N - 1) * gapy + 40), (50, 50, 64), 2, cv2.LINE_AA, 4)
            for k, (x, y) in enumerate(pts):
                near = abs(x - CX) < 40; c = self.pal[k % len(self.pal)]
                rad = 24 + (16 * fl if near else 0)
                cv2.circle(layer, P(x, y), int(rad * 16), tuple(float(v) for v in c * (1.5 if near and fl > 0.3 else 1.0)), -1, cv2.LINE_AA, 4)
                cv2.circle(self.trail_img, P(x, y), int(10 * 16), tuple(float(v) * 0.18 for v in c), -1, cv2.LINE_AA, 4)
        else:
            if self.scene == 'circle':
                cv2.circle(layer, P(CX, CY), int(self.R * 16), tuple(float(v) for v in col * (0.6 + 0.8 * fl)), 6, cv2.LINE_AA, 4)
            elif self.scene == 'square':
                s = self.side(i) / 2
                cv2.rectangle(layer, P(CX - s, CY - s), P(CX + s, CY + s), tuple(float(v) for v in col * (0.6 + 0.8 * fl)), 6, cv2.LINE_AA, 4)
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
            balls = [self.pos(i)]
            if self.scene == 'circle' and self.split and i >= self.split:      # on the drop it becomes two
                x, y, k = balls[0]; balls.append((2 * CX - x, 2 * CY - y, k))
            last = max((h for h in self.hits if h <= i), default=None)
            age = (i - last) / FPS if last is not None else 9.0
            if age < 0.3:                                                      # the impact: a ripple and sparks from where it hit
                cx, cy = self.contact(last); nrm = math.atan2(CY - cy, CX - cx); st = 0.6 + 0.4 * self.strength.get(last, 1.0)
                u = age / 0.3; c = tuple(float(v) for v in col * (1 - u))
                cv2.circle(layer, P(cx, cy), int((24 + 150 * st * u ** 0.6) * 16), c, max(1, int(5 * (1 - u))), cv2.LINE_AA, 4)
                rr = random.Random(int(last) * 7919)
                for _ in range(12):
                    q = nrm + rr.uniform(-1.25, 1.25); v = rr.uniform(500, 1100) * st
                    d = v * age                                                  # straight out; they fade, not fall
                    cv2.circle(layer, P(cx + d * math.cos(q), cy + d * math.sin(q)), int(max(1.0, 7 * (1 - u)) * 16), c, -1, cv2.LINE_AA, 4)
            for (x, y, k) in balls:
                rad = 26 * (1 + 0.25 * fl)
                if self.trail == 'ribbon' and getattr(self, '_last', None):
                    cv2.line(self.trail_img, P(*self._last), P(x, y), tuple(float(v) for v in col * 0.9), int(2 * rad), cv2.LINE_AA, 4)
                else: cv2.circle(self.trail_img, P(x, y), int(rad * 16), tuple(float(v) * 0.7 for v in col), -1, cv2.LINE_AA, 4)
                sq = max(0.0, 1 - age / 0.07) if age < 0.07 else 0.0           # squashed flat against the wall for an instant
                if sq > 0:
                    nrm_deg = math.degrees(math.atan2(CY - y, CX - x))
                    cv2.ellipse(layer, P(x, y), (int(rad * (1 - 0.38 * sq) * 16), int(rad * (1 + 0.3 * sq) * 16)), nrm_deg, 0, 360, (255, 255, 255), -1, cv2.LINE_AA, 4)
                else: cv2.circle(layer, P(x, y), int(rad * 16), (255, 255, 255), -1, cv2.LINE_AA, 4)
                if fl > 0.6:                                                   # the ring a hit throws out
                    cv2.circle(layer, P(x, y), int(rad * (1 + 3 * (1 - fl)) * 16), tuple(float(v) for v in col), 3, cv2.LINE_AA, 4)
            self._last = balls[0][:2]
        img = self.trail_img + layer
        img = img + cv2.GaussianBlur(img, (0, 0), 14) * (0.7 + 0.6 * fl)       # glow
        img = np.clip(img + np.array([14, 10, 18], np.float32), 0, 255).astype(np.uint8)
        im = Image.fromarray(img); d = ImageDraw.Draw(im)
        if self.hook != 'none' and t < 3.2:
            txt = ('every bounce is a note from\n"%s"' % self.title) if self.hook == 'song' else 'every hit is a beat.\nsound on.'
            d.multiline_text((W / 2, 230), txt, font=self.f_hook, fill=(255, 255, 255), anchor='mm', align='center', spacing=14)
        d.text((W / 2, H * 0.82), '%d' % hitk, font=self.f_count, fill=(220, 220, 230), anchor='mm')
        d.text((W / 2, H - 70), self.credit, font=self.f_small, fill=(170, 170, 185), anchor='mm')
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
    if why: sys.exit('not rendered, the ball would sit still: %s (%s %.1f-%.1f s)' % (why, v.slug, t0, t1))
    v.render(out)
