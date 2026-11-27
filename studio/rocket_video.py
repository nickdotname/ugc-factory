#!/usr/bin/env python3
"""rocket.league.lit: our own Rocket League clips to a Close Quarters song.

    python studio/rocket_video.py SONG_DIR SEED OUT.mp4          (CQ_WINDOW="t0,t1": where in the song to start looking)
    python studio/rocket_video.py SONG_DIR SEED SHEET.png --frames 0,60,120
    python studio/rocket_video.py label ASSET at=8.9 event=goal clock=1:57 score="down 3-1"   (what a clip shows)
    python studio/rocket_video.py track [--force]                (the ball-following crop, for clips that have none)
    python studio/rocket_video.py goals                          (where the scoreboard changes, in each cached clip)

Two formats (the knob `format`), so the learner finds out which one people watch:
  asis     one clip, played straight, with the song under it. It starts one bar (1.5-2.5 s) before the clip's moment
           (`at` in the index: the goal, or the decisive touch), so the goal lands inside the first 2.5 s, on a
           downbeat, and the clip plays out to its end. A clip whose tail is too short for the cut gets the moment
           again at half speed (the replay). A small punch-in on the kicks; the game's own sound is muted (its menu
           music is not ours to post).
  montage  several clips cut on the bar lines, each cut placed so its clip's best moment lands on the downbeat,
           with a slow-motion run-in to it (knob `ramp`) and a zoom punch on the kicks.
The line (knob `line`, asis only): `situ` holds the situation from frame 0 to the end, a statement read off the
clip's scoreboard ("0:45 left. 3-3."), typed by us into the index (situation()); `none` shows nothing. No slogans,
no questions, no asks (docs/brain/reviews/2026-11-26/worlds.md).
Framing (knob `frame`): `blur` puts a landscape clip full-width over a blurred, darkened copy of itself; `crop` fills
the frame with a 9:16 window that follows the ball (the index's `track`; the middle when a clip has none). Vertical
clips fill the frame either way. The moments come from studio/rocket_lib.py (loud bursts and sudden flashes).

What the index says about a clip, besides rocket_lib's size and moments (all 17 labelled 2026-11-27 by reading
the scoreboard frame by frame):
  at      the second of the goal (when the scoreboard number changes) or of the decisive touch (a save; the shot,
          in the one clip with no scoreboard). `goals` finds the scoreboard change; it also fires on a flashing box,
          so look at a sheet before writing it in.
  event   goal / save / replay
  clock   the game clock at that moment, as shown ("0:45")
  score   the score just before it, from the side that scores or saves ("3-3", "down 3-1", "up 2-0")
  line    the situation in words when clock + score cannot say it (a replay); "" for none
  rank    not on screen in any clip so far: whoever records a clip and knows the playlist/rank adds it (rank="champ 2")
  track   where the 9:16 crop is centred, 0-1 of the width, twice a second (track())
"""
import json, math, os, random, re, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish
import rocket_lib as lib
import hook as _hook

W, H, FPS = 1080, 1920, 30
TRACK_HZ = 2                      # track samples a second
LINE_Y = 0.15                     # the situation line's top, as a fraction of the height (y 288: inside the safe area)


def font(size):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf')):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def situation(c):
    """The line held over a clip: where the game stands, read off its scoreboard ('' when nobody has labelled it)."""
    if c.get('line') is not None: return c['line']
    if not c.get('clock') or not c.get('score'): return ''
    return '%s left. %s.' % (c['clock'], c['score']) + (' %s.' % c['rank'] if c.get('rank') else '')


def moment(c):
    """The second the video is built around: the labelled goal or touch, else rocket_lib's loudest moment."""
    if c.get('at') is not None: return float(c['at'])
    return c['moments'][0][0] if c['moments'] else c['dur'] / 2


class Reader:
    """Frames of one clip at any time (seconds), read in order and cached by frame number."""
    def __init__(self, path):
        self.cap = cv2.VideoCapture(path); self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1; self.pos = -1; self.last = None

    def at(self, t):
        k = int(np.clip(round(t * self.fps), 0, self.n - 1))
        if k < self.pos or k > self.pos + 90:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, k); self.pos = k - 1
        while self.pos < k:
            ok, f = self.cap.read()
            if not ok: break
            self.pos += 1; self.last = f
        return self.last if self.last is not None else np.zeros((1080, 1920, 3), np.uint8)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); r = random.Random(seed); self.r = r
        self.format = K.pick('format', ['asis', 'montage'], r, weights=[4, 1])     # review 2026-11-26: the as-is clips win
        self.frame_kind = K.pick('frame', ['blur', 'crop'], r, weights=[2, 1])
        self.ramp = K.pick('ramp', ['slowmo', 'none'], r) if self.format == 'montage' else 'none'
        clips = lib.pull()
        if not clips: sys.exit('the Rocket League library is empty: add clips with studio/rocket_lib.py')
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.song = song
        spb = 60 / song['tempo']; bar = 4 * spb
        while bar < 1.4: bar *= 2
        self.bar = bar
        downbeat = lambda t: audio.time_of_beat(song, math.ceil(audio.beat_of_time(song, t) / 4) * 4)   # the first bar line at or after t
        self.line = ''
        if self.format == 'asis':
            c = r.choice(clips); m = moment(c)
            want = min(14.0, max(6.0, t1 - t0))                              # the cut nightly asked for, 6-14 s
            start = max(0.0, m - min(2.5, max(1.5, bar)))                      # one bar of run-in: the goal by 2.5 s
            lead = m - start; play = min(c['dur'] - start - 0.05, want)
            hit = downbeat(t0 + lead)                                         # the song time that lands on the moment
            self.t0 = hit - lead
            self.plan = [(0.0, play, c, start, lead, 1.0)]                    # (video from, to, clip, clip start, moment offset, speed)
            if play < want - 1.0:                                             # a short tail: the moment again at half speed
                rs = max(0.0, m - 1.2); self.plan.append((play, play + 2 * min(2.4, c['dur'] - rs - 0.05), c, rs, 1.2, 0.5))
            self.t1 = self.t0 + self.plan[-1][1]
            if situation(c): self.line = situation(c) if K.pick('line', ['situ', 'none'], r, weights=[3, 1]) == 'situ' else ''
        else:
            self.t0 = downbeat(t0); n_bars = max(4, min(10, int(round((t1 - t0) / bar))))
            self.t1 = self.t0 + n_bars * bar
            pool = [c for c in clips if c['moments'] or c.get('at') is not None] or clips; r.shuffle(pool); self.plan = []
            for k in range(n_bars):                                       # one clip a bar; its moment lands half a bar in, on the snare
                c = pool[k % len(pool)]; ms = [moment(c)] + [t for t, _ in c['moments'] if abs(t - moment(c)) > 1]
                m = ms[(k // len(pool)) % len(ms)]
                lead = bar / 2; pre = lead - 0.25 if self.ramp == 'slowmo' else lead   # clip seconds shown before the moment
                self.plan.append((k * bar, (k + 1) * bar, c, m - pre, lead, 1.0))
        a = audio.load(self.slug, self.t0, self.t1); self.n = a['n']
        self.kick = audio.hits(a['kicks'], self.n, 8.0); self.snare = audio.hits(a['snares'], self.n, 10.0)
        self.readers = {}
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.f_credit = font(30)

    def reader(self, c):
        if c['asset'] not in self.readers: self.readers[c['asset']] = Reader(os.path.join(lib.CACHE, c['asset']))
        return self.readers[c['asset']]

    def source_time(self, seg, tv):
        """Where in the clip we are tv seconds into the video: straight through (at the segment's speed), or
        (montage slowmo) at half speed for the half second before the moment and full speed from it, so the hit
        still lands where the plan puts it."""
        a, b, c, cs, lead, speed = seg; u = tv - a
        if self.format == 'montage' and self.ramp == 'slowmo':
            if u < lead - 0.5: return cs + u
            if u < lead: return cs + (lead - 0.5) + (u - (lead - 0.5)) * 0.5
            return cs + (lead - 0.25) + (u - lead)
        return cs + u * speed

    @staticmethod
    def ball_x(c, t):
        """The crop's centre at clip time t (0-1 of the width), from the index's track; the middle without one."""
        tr = c.get('track')
        if not tr: return 0.5
        return float(np.interp(t * TRACK_HZ, np.arange(len(tr)), tr))

    def fit(self, f, zoom, cx=0.5):
        h, w = f.shape[:2]
        if h >= w or self.frame_kind == 'crop':                               # fill the frame: a 9:16 window on the ball
            s = max(W / w, H / h) * zoom; f2 = cv2.resize(f, (int(w * s) + 1, int(h * s) + 1), interpolation=cv2.INTER_LINEAR)
            y0 = (f2.shape[0] - H) // 2; x0 = int(np.clip(cx * f2.shape[1] - W / 2, 0, f2.shape[1] - W))
            return f2[y0:y0 + H, x0:x0 + W]
        bg = cv2.resize(f, (int(w * H / h), H), interpolation=cv2.INTER_AREA); x0 = (bg.shape[1] - W) // 2
        bg = cv2.GaussianBlur(cv2.resize(bg[:, x0:x0 + W], (W // 8, H // 8)), (0, 0), 3); bg = cv2.resize(bg, (W, H)) * 0.45
        s = W / w * zoom; fg = cv2.resize(f, (int(w * s), int(h * s)), interpolation=cv2.INTER_LINEAR)
        y0 = (H - fg.shape[0]) // 2 - 60; x0 = (fg.shape[1] - W) // 2
        out = bg.astype(np.uint8); fg = fg[:, max(0, x0):max(0, x0) + W]
        out[max(0, y0):y0 + fg.shape[0], :fg.shape[1]] = fg[max(0, -y0):H - y0]
        return out

    def frame(self, i):
        tv = i / FPS; seg = next((s for s in self.plan if s[0] <= tv < s[1]), self.plan[-1])
        st = self.source_time(seg, tv); f = self.reader(seg[2]).at(st)
        since = tv - seg[0]
        zoom = 1.0 + 0.045 * self.kick[i] + (0.06 * math.exp(-since * 8) if (self.format == 'montage' or seg[5] != 1.0) and i > 0 else 0)
        img = self.fit(f, zoom, self.ball_x(seg[2], st)).astype(np.float32)
        if since < 0.07 and seg[0] > 0: img = img * 0.5 + 127                 # a flash on the cut (and into the replay)
        if self.snare[i] > 0.7: img *= 1.08
        im = Image.fromarray(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(im)
        tw = d.textlength(self.credit, font=self.f_credit)
        d.rounded_rectangle([W / 2 - tw / 2 - 18, H - 470, W / 2 + tw / 2 + 18, H - 424], 20, fill=(0, 0, 0))
        d.text((W / 2, H - 447), self.credit, font=self.f_credit, fill=(245, 245, 245), anchor='mm')
        return _hook.draw_hold(np.asarray(im), self.line, 1.0, LINE_Y)       # full strength from frame 0 (the cover)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.plan[0][2]['asset'], [round(p[4], 2) for p in self.plan], repr(self.line)); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 90 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(dict(K.record(), clips=sorted({s[2]['asset'] for s in self.plan}),
                       plan=dict(hook=self.line, hook_angle='situ' if self.line else 'none', hook_mode='hold',
                                 replay=len(self.plan) > 1 and self.format == 'asis')), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'rocket')      # bloom, grain, grade, vignette: studio/polish.py


# ------------------------------------------------------------ labelling the library (studio/rocket/index.json)

def score_change(path, fps=10):
    """The second the scoreboard's number changes (a goal), or None. Each team's box is read as its white pixels; the
    change is where the 0.8 s before and the 0.8 s after differ most. Right on 13 of the 14 goals in the library
    (one 0.7 s late, on a box that flashes white); it also fires on a clip with no scoreboard: look before trusting it."""
    cap = cv2.VideoCapture(path); rate = cap.get(cv2.CAP_PROP_FPS) or 30; step = max(1, int(round(rate / fps))); k = 0; boxes = []
    while True:
        ok, f = cap.read()
        if not ok: break
        if k % step == 0:
            h, w = f.shape[:2]; g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)[int(h * .012):int(h * .075)]
            boxes.append([(cv2.resize(g[:, int(w * a):int(w * b)], (24, 32), interpolation=cv2.INTER_AREA) > 200).astype(np.float32)
                          for a, b in ((.41, .45), (.55, .59))])
        k += 1
    best, n = (0.09, None), 8
    for side in (0, 1):
        v = np.array([b[side] for b in boxes])
        for i in range(n, len(v) - n):
            d = float(np.abs(np.median(v[i - n:i], 0) - np.median(v[i:i + n], 0)).mean())
            if d > best[0]: best = (d, round(i * step / rate, 1))
    return best[1]


def track(path):
    """Where to centre a 9:16 crop of a landscape clip so the ball stays in it: [x, ...] (0-1 of the width), TRACK_HZ
    a second. The ball is a grey circle (Hough circles above the car, the least saturated first); the path through the
    candidates that jumps least is kept (Viterbi), median-filtered and smoothed; the crop sits halfway between the ball
    and the middle, where ball cam keeps the car. Checked by eye on four clips: the ball is in the window most of the time."""
    cap = cv2.VideoCapture(path); rate = cap.get(cv2.CAP_PROP_FPS) or 30; step = max(1, int(round(rate / 6))); k = 0; pts = []
    while True:
        ok, f = cap.read()
        if not ok: break
        if k % step == 0:
            sm = cv2.resize(f, (640, int(f.shape[0] * 640 / f.shape[1]))); g = cv2.medianBlur(cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY), 5)
            sat = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)[..., 1]; gh = g.shape[0]; g[:int(gh * .1)] = 0; g[int(gh * .72):] = 0   # not the scoreboard, not the car
            cs = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, dp=1.2, minDist=30, param1=120, param2=26, minRadius=7, maxRadius=80); cand = []
            for x, y, rad in (cs[0][:8] if cs is not None else []):
                m = np.zeros_like(sat); cv2.circle(m, (int(x), int(y)), max(2, int(rad * .8)), 1, -1)
                if m.any(): cand.append((float(sat[m > 0].mean()), float(x) / 640))
            pts.append([x for sv, x in sorted(cand)[:4] if sv < 110] or [None])
        k += 1
    if not pts: return []
    cost = [0.0 if c is not None else 0.5 for c in pts[0]]; back = [[0] * len(pts[0])]
    for prev, cand in zip(pts, pts[1:]):
        nc, nb = [], []
        for j, c in enumerate(cand):
            v, i = min((cost[i] + (0.15 if c is None or p is None else abs(c - p) * 3) + (0.5 if c is None else 0.08 * j), i) for i, p in enumerate(prev))
            nc.append(v); nb.append(i)
        cost = nc; back.append(nb)
    j = int(np.argmin(cost)); path = []
    for n in range(len(pts) - 1, -1, -1): path.append(pts[n][j]); j = back[n][j]
    last, xs = 0.5, []
    for x in path[::-1]: last = x if x is not None else last; xs.append(last)
    xs = np.array(xs); xs = np.array([np.median(xs[max(0, i - 3):i + 4]) for i in range(len(xs))])
    xs = np.convolve(np.pad(xs, 4, mode='edge'), np.ones(9) / 9, 'valid')
    every = rate / step / TRACK_HZ
    return [round(0.5 + 0.5 * (float(np.interp(q * every, np.arange(len(xs)), xs)) - 0.5), 3) for q in range(int(len(xs) / every) + 1)]


def save(idx):
    """index.json, every list of numbers on one line."""
    txt = json.dumps(idx, indent=1, ensure_ascii=False)
    txt = re.sub(r'\[[\s\d.,-]*\]', lambda m: re.sub(r'\s+', '', m.group(0)).replace(',', ', '), txt)
    open(lib.INDEX, 'w').write(txt + '\n')


def label(asset, pairs):
    idx = lib.index(); c = next(c for c in idx['clips'] if c['asset'].startswith(asset))
    for kv in pairs:
        k, v = kv.split('=', 1); c[k] = float(v) if k == 'at' else v
    save(idx); print(c['asset'], {k: c.get(k) for k in ('at', 'event', 'clock', 'score', 'line')}, '->', repr(situation(c)))


if __name__ == '__main__':
    if sys.argv[1:2] == ['label']: label(sys.argv[2], sys.argv[3:]); sys.exit()
    if sys.argv[1:2] in (['track'], ['goals']):
        lib.pull(); idx = lib.index()
        for c in idx['clips']:
            path = os.path.join(lib.CACHE, c['asset'])
            if not os.path.exists(path): continue
            if sys.argv[1] == 'goals': print(c['asset'], 'scoreboard changes at', score_change(path), 'labelled', c.get('at'))
            elif c['w'] > c['h'] and ('--force' in sys.argv or not c.get('track')): c['track'] = track(path); print(c['asset'], len(c['track']))
        if sys.argv[1] == 'track': save(idx)
        sys.exit()
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
