#!/usr/bin/env python3
"""Ink marbling by math, to a song (a ready page: marbled.by.math, paused until its Instagram account exists; see
docs/brain/ready-pages.md).

    python studio/ebru_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/ebru_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

Paper marbling (ebru) done with the equations of mathematical marbling, nothing filmed and nothing simulated by
guesswork. Every move is an exact, area-keeping map of the bath:
  drop   ink of radius r lands at C; every point P outside moves to C + (P-C) * sqrt(1 + r^2/|P-C|^2), so the older ink
         is pushed out into rings and keeps its area.
  comb   a straight stroke: each tine drags the ink along its line by a * l / (d + l), d = distance from the tine
         (a shear: areas kept). Tines can alternate direction (back and forth, "gelgit").
  wave   the bath is shifted sideways by A * sin(2 pi y / w): a wavy comb.
  stir   a turn round a centre by an angle that falls off with the distance from a ring: a vortex.
A frame is drawn backwards: each pixel is traced back through the moves to the drop it came from (exact, at 1.5x, so
the edges are clean). While a move is under way, the last exact picture is warped by that move only.

Drops land on the song's beats (and 8ths when the song is slow); strokes take two beats each and start on a beat. The
counter (drops, strokes) is counted, and the last line is true of every video: no move changes a drop's area.
Knobs (studio/knobs.py): pattern (stone, gelgit, nonpareil, tulip, stir, wave), palette, bath.
"""
import json, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
PW = PH = 1000                               # the tray: a square in the middle, clear of Instagram's top and bottom
PX, PY = (W - PW) // 2, 400
SS = 1.5                                     # exact pictures are traced at 1.5x and averaged down
MAX_LEN = 24.0

# inks and the bath they float on (Lab-ish balance checked by eye on contact sheets)
PALETTES = {
    'classic':  [(34, 52, 110), (196, 142, 48), (164, 46, 52), (238, 230, 210), (40, 96, 92)],
    'ocean':    [(16, 48, 92), (40, 140, 160), (230, 222, 196), (120, 186, 196), (12, 28, 52)],
    'sunset':   [(232, 120, 60), (204, 56, 72), (250, 200, 90), (90, 40, 90), (248, 236, 214)],
    'forest':   [(46, 86, 52), (170, 150, 70), (120, 60, 40), (226, 218, 190), (24, 44, 34)],
    'indigo':   [(26, 34, 84), (70, 90, 160), (220, 224, 236), (140, 160, 210), (12, 16, 40)],
    'candy':    [(240, 130, 170), (110, 190, 220), (250, 230, 120), (170, 120, 210), (252, 248, 240)],
}
BATHS = {'cream': (240, 232, 214), 'ink': (22, 22, 30), 'stone': (198, 196, 188)}
HOOK = {
    'stone': 'every drop pushes\nthe others aside',
    'gelgit': '%d drops of ink.\nthen one comb, back and forth',
    'nonpareil': '%d drops of ink.\nthen two combs',
    'tulip': 'rings of ink.\none straight line through them',
    'stir': '%d drops of ink.\nthen one slow stir',
    'wave': '%d drops of ink.\nthen a wavy comb',
}
END = ['nothing was mixed.\nevery drop was only moved', 'every drop still covers\nexactly the area it landed with']


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)


def ease_out(u): u = min(max(u, 0.0), 1.0); return 1 - (1 - u) ** 3


# ---- the moves. Each has the inverse map (where a point at the end of the move was before it), with amount s 0..1.
def inv_drop(op, x, y, s):
    cx, cy, r = op['c'][0], op['c'][1], op['r'] * np.sqrt(ease_out(s))   # the drop's area grows evenly
    dx, dy = x - cx, y - cy; d2 = dx * dx + dy * dy
    inside = d2 < r * r
    k = np.sqrt(np.maximum(1.0 - (r * r) / np.maximum(d2, 1e-6), 0.0))
    return cx + dx * k, cy + dy * k, inside


def comb_shift(op, x, y, s):
    mx, my = op['m']; nx, ny = -my, mx                      # stroke direction, and across it
    q = (x - op['p'][0]) * nx + (y - op['p'][1]) * ny          # signed distance across the stroke (unchanged by it)
    z = np.zeros_like(x)
    for off, sign in op['tines']:
        z += sign * op['a'] * op['l'] / (np.abs(q - off) + op['l'])
    z *= ease(s)
    return z * mx, z * my


def inv_comb(op, x, y, s):
    ux, uy = comb_shift(op, x, y, s); return x - ux, y - uy, None


def inv_wave(op, x, y, s):
    a = op['A'] * ease(s)
    if op['axis'] == 'x': return x - a * np.sin(2 * np.pi * y / op['w'] + op['ph']), y, None
    return x, y - a * np.sin(2 * np.pi * x / op['w'] + op['ph']), None


def inv_stir(op, x, y, s):
    cx, cy = op['c']; dx, dy = x - cx, y - cy; r = np.hypot(dx, dy)
    th = -op['a'] * ease(s) * op['l'] / (np.abs(r - op['R']) + op['l'])
    c, sn = np.cos(th), np.sin(th)
    return cx + dx * c - dy * sn, cy + dx * sn + dy * c, None


INV = {'drop': inv_drop, 'comb': inv_comb, 'wave': inv_wave, 'stir': inv_stir}


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir))
        t1 = min(t1, t0 + MAX_LEN); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.pattern = K.pick('pattern', ['stone', 'gelgit', 'gelgit', 'nonpareil', 'nonpareil', 'tulip', 'tulip', 'stir', 'wave'], r)
        self.pal_name = K.pick('palette', sorted(PALETTES), r)
        self.bath_name = K.pick('bath', ['cream', 'cream', 'ink', 'stone'], r)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.kick = audio.hits(a['kicks'], n, 7.0)
        self.beats = [int(round(f)) for _, f in a['beats'] if 0 <= f < n]
        if len(self.beats) < 16: print('not rendered: %.1f s is too short to marble (%s)' % (t1 - t0, self.slug)); sys.exit(3)
        inks = list(PALETTES[self.pal_name]); bath = BATHS[self.bath_name]
        # an ink too close to the bath would vanish into it
        inks = [c for c in inks if sum(abs(p - q) for p, q in zip(c, bath)) > 90]
        self.inks = inks; self.bath = np.array(bath, np.float32)
        self.ops = self.plan(r)
        self.n_drops = sum(1 for o in self.ops if o['k'] == 'drop')
        self.n_strokes = sum(1 for o in self.ops if o['k'] != 'drop')
        self.end_line = END[r.randrange(len(END))]

        # paper: fine grain and a soft mottle, the same for the whole video
        g = np.random.default_rng(seed)
        fine = cv2.GaussianBlur(g.normal(0, 1, (PH, PW)).astype(np.float32), (0, 0), 0.8)
        soft = cv2.GaussianBlur(g.normal(0, 1, (PH // 8, PW // 8)).astype(np.float32), (0, 0), 3)
        soft = cv2.resize(soft, (PW, PH), interpolation=cv2.INTER_CUBIC)
        self.paper = (1 + 0.022 * fine / (fine.std() + 1e-6) + 0.03 * soft / (soft.std() + 1e-6))[..., None]

        ys, xs = np.mgrid[0:int(PH * SS), 0:int(PW * SS)].astype(np.float32)
        self.gx, self.gy = (xs + 0.5) / SS, (ys + 0.5) / SS
        fy, fx = np.mgrid[0:PH, 0:PW].astype(np.float32); self.fx, self.fy = fx + 0.5, fy + 0.5
        self.exact = {}                                         # k -> RGB tray after ops[:k] are complete
        self.f_hook = font('Fraunces.ttf', 62); self.f_cnt = font('DejaVuSansMono-Bold.ttf', 34)
        self.f_credit = font('DejaVuSansMono-Bold.ttf', 26)
        self._first = None

    # ---- the choreography
    def plan(self, r):
        n, B = self.n, self.beats
        step = B[1] - B[0] if len(B) > 1 else 15
        hold = int(2.6 * FPS)                                   # the finished pattern and the last line
        nstroke = {'stone': 0, 'gelgit': 2, 'nonpareil': 2, 'tulip': 1, 'stir': 1, 'wave': 2}[self.pattern]
        if self.pattern == 'stone': nstroke = 0
        stroke_beats = 2
        last = n - hold - nstroke * (stroke_beats * step + 4)
        drop_beats = [b for b in B if b < last]
        # slow songs drop on the 8ths too, so the bath fills
        if step > 16: drop_beats = sorted(set(drop_beats + [b + step // 2 for b in drop_beats if b + step // 2 < last]))
        slots = [0] + [b for b in drop_beats if b > 3]
        ops = []
        C = PW / 2
        if self.pattern == 'tulip':
            # set back from the far edge: the stroke runs down (or right) and carries the last bullseye with it
            centres = ([(C, y) for y in np.linspace(130, 730, r.choice([3, 4]))] if r.random() < 0.5 else
                       [(x, C) for x in np.linspace(130, 730, r.choice([3, 4]))])
            # drops land on the centres in turn, each pushing the older ones out into rings; a drop's radius is set so
            # the finished bullseye has the size wanted (n drops of radius r cover a disc of radius r * sqrt(n))
            per = max(1, len(slots) // len(centres))
            gap = 600 / max(1, len(centres) - 1) if len(centres) > 1 else 0
            target = 0.5 * gap * 1.05 if len(centres) > 1 else 400
            rad = target / np.sqrt(per)
            for i, f in enumerate(slots):
                ci, j = i % len(centres), i // len(centres)
                ops.append(dict(k='drop', c=centres[ci], r=rad * r.uniform(0.92, 1.08), ink=j % len(self.inks), f=f))
        else:
            big, small = 170, 55                               # big stones first, smaller ones after: the bath fills
            for i, f in enumerate(slots):
                u = i / max(1, len(slots) - 1)
                rad = big * (1 - u) + small * u
                m = -110 if self.pattern == 'stir' else 60        # a stir turns ink in from past the tray's corners
                ops.append(dict(k='drop', c=(r.uniform(m, PW - m), r.uniform(m, PH - m)), r=rad * r.uniform(0.8, 1.15),
                                ink=r.randrange(len(self.inks)), f=f))
        for i, o in enumerate(ops):                           # a drop grows until just before the next one lands
            nxt = ops[i + 1]['f'] if i + 1 < len(ops) else o['f'] + 8
            o['d'] = max(3, min(8, nxt - o['f'] - 1))
        # the first drops have already landed at frame 0 (one per centre, or four stones), so the cover is not empty
        pre = 4 if self.pattern != 'tulip' else max(1, len({o['c'] for o in ops}))
        for o in ops[:pre]: o['f'] = -o['d'] - 1
        # strokes, each two beats, starting on the first beat after the drops
        sb = [b for b in B if b >= (ops[-1]['f'] + ops[-1]['d'] + 2)] if ops else B
        strokes = []
        if self.pattern == 'gelgit':
            c = r.choice([70, 90, 110])
            strokes = [self.comb('v', c, True, r), self.comb('h', c, True, r)] if r.random() < 0.6 else \
                      [self.comb('v', c, True, r), self.comb('v', c, True, r, shift=c / 2)]
        elif self.pattern == 'nonpareil':
            strokes = [self.comb('v', r.choice([90, 120]), True, r), self.comb('h', r.choice([28, 34, 40]), False, r)]
        elif self.pattern == 'tulip':
            cs = [o['c'] for o in ops]; vertical = len(set(round(c[0]) for c in cs)) == 1
            strokes = [dict(k='comb', m=(0.0, 1.0) if vertical else (1.0, 0.0), p=(PW / 2, PH / 2), tines=[(0.0, 1)],
                            a=r.choice([260, 320]), l=r.choice([24, 32]))]
        elif self.pattern == 'stir':
            # (a stir round the centre of a bullseye would change nothing: rings turned round their own centre)
            strokes = [dict(k='stir', c=(PW / 2, PH / 2), R=r.choice([0.0, 150.0, 260.0]), a=r.choice([4.0, 5.5, -4.5]), l=170.0)]
        elif self.pattern == 'wave':
            strokes = [self.comb('v', r.choice([80, 100]), True, r),
                       dict(k='wave', axis=r.choice(['x', 'y']), A=r.choice([45, 60]), w=r.choice([260, 340]), ph=r.uniform(0, 6.28))]
        for j, s in enumerate(strokes):
            k = j * stroke_beats
            if k + stroke_beats >= len(sb): break
            s['f'] = sb[k]; s['d'] = max(10, sb[k + stroke_beats] - sb[k] - 2)
            ops.append(s)
        return ops

    def comb(self, axis, spacing, alternate, r, shift=0.0):
        # 'v': tines at fixed x, the stroke runs down (or up); 'h': tines at fixed y
        m = (0.0, r.choice([1.0, -1.0])) if axis == 'v' else (r.choice([1.0, -1.0]), 0.0)
        n = int(PW / spacing) + 3
        offs = [(-PW / 2 - spacing + shift + k * spacing, (1 if (k % 2 == 0 or not alternate) else -1)) for k in range(n)]
        # across = (-my, mx): for 'v' (m=(0,±1)) that is ∓x, for 'h' ±y; offsets are measured from the tray centre
        return dict(k='comb', m=m, p=(PW / 2, PH / 2), tines=offs, a=spacing * (0.75 if alternate else 0.9), l=spacing * 0.22)

    # ---- drawing
    def trace(self, k, x, y, s_last=1.0):
        """Labels of the tray points (x, y) after ops[:k], the last one at amount s_last: -1 = bath."""
        lab = np.full(x.shape, -1, np.int16); idx = np.arange(x.size); x = x.ravel().copy(); y = y.ravel().copy()
        for j in range(k - 1, -1, -1):
            op = self.ops[j]; s = s_last if j == k - 1 else 1.0
            nx, ny, inside = INV[op['k']](op, x, y, s)
            if inside is not None and inside.any():
                lab.ravel()[idx[inside]] = op['ink']
                keep = ~inside; idx, nx, ny = idx[keep], nx[keep], ny[keep]
            x, y = nx, ny
            if not idx.size: break
        return lab

    def colour(self, lab):
        pal = np.array(self.inks, np.float32)
        img = np.where(lab[..., None] >= 0, pal[np.maximum(lab, 0)], self.bath)
        # a faint darker rim where two inks meet, as real marbling has
        e = np.zeros(lab.shape, np.float32)
        e[:, 1:] += lab[:, 1:] != lab[:, :-1]; e[1:, :] += lab[1:, :] != lab[:-1, :]
        e = cv2.GaussianBlur(np.minimum(e, 1), (0, 0), 1.2 * SS)
        return img * (1 - 0.22 * np.minimum(e * 1.6, 1)[..., None])

    def exact_at(self, k):
        if k not in self.exact:
            lab = self.trace(k, self.gx, self.gy)
            self.exact[k] = cv2.resize(self.colour(lab), (PW, PH), interpolation=cv2.INTER_AREA)
        return self.exact[k]

    def tray(self, i):
        """The tray at frame i: the exact picture after every finished op, warped by the op under way."""
        k = sum(1 for o in self.ops if o['f'] <= i)          # ops started
        if k == 0: return np.empty((PH, PW, 3), np.float32) + self.bath, None
        op = self.ops[k - 1]; s = (i - op['f'] + 1) / (op['d'] + 1)
        if s >= 1: return self.exact_at(k), None
        base = self.exact_at(k - 1)
        x, y, inside = INV[op['k']](op, self.fx, self.fy, s)
        img = cv2.remap(base, (x - 0.5).astype(np.float32), (y - 0.5).astype(np.float32), cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(float(v) for v in self.bath))
        if op['k'] == 'drop':
            rr = op['r'] * np.sqrt(ease_out(s)); m = np.zeros((PH, PW), np.float32)
            cv2.circle(m, (int(op['c'][0] * 16), int(op['c'][1] * 16)), int(rr * 16), 1.0, -1, cv2.LINE_AA, 4)
            img = img * (1 - m[..., None]) + np.array(self.inks[op['ink']], np.float32) * m[..., None]
        return img, op

    def draw(self, i, top=True):
        img = np.empty((H, W, 3), np.float32); img[:] = (18, 18, 22)
        t, op = self.tray(i)
        img[PY:PY + PH, PX:PX + PW] = t * self.paper
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        # the comb's tines while a stroke is under way: short lines at the stroke's front
        if op is not None and op['k'] == 'comb':
            s = ease((i - op['f'] + 1) / (op['d'] + 1)); mx, my = op['m']; nx, ny = -my, mx
            front = -PW / 2 + s * PW * 1.1
            for off, sign in op['tines']:
                if self.pattern == 'gelgit' or self.pattern == 'wave': fr = front if sign > 0 else -front
                else: fr = front
                cx = PX + op['p'][0] + nx * off + mx * fr; cy = PY + op['p'][1] + ny * off + my * fr
                if PX + 4 < cx < PX + PW - 4 and PY + 4 < cy < PY + PH - 4:
                    d.line([(cx - mx * 26, cy - my * 26), (cx, cy)], fill=(30, 30, 34), width=4)
        drops = sum(1 for o in self.ops if o['k'] == 'drop' and o['f'] <= i)
        strokes = sum(1 for o in self.ops if o['k'] != 'drop' and o['f'] <= i)
        ink = (244, 240, 230)
        done = self.ops[-1]['f'] + self.ops[-1]['d'] + int(0.4 * FPS)
        if top:
            if i < done or i < self.n * 0.5:
                txt = HOOK[self.pattern] % self.n_drops if '%d' in HOOK[self.pattern] else HOOK[self.pattern]
            else:
                txt = self.end_line
            d.multiline_text((W / 2, 290), txt, font=self.f_hook, fill=ink, anchor='mm', align='center', spacing=14)
        k = float(self.kick[min(i, self.n - 1)])
        cnt = 'drops %d' % drops + ('   strokes %d' % strokes if self.n_strokes else '')
        d.text((W / 2, PY + PH + 52), cnt, font=self.f_cnt, fill=(int(200 + 44 * k),) * 3, anchor='mm')
        d.text((W / 2, PY + PH + 112), self.credit, font=self.f_credit, fill=(170, 170, 176), anchor='mm')
        return np.asarray(im)

    def frame(self, i):
        tail = 9; o = self.draw(i, top=i < self.n - tail - 4)
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
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', self.n_drops, 'drops', self.n_strokes, 'strokes'); return
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
        rec = K.record(); rec['pictures'] = 'drawn in code (mathematical marbling)'
        json.dump(rec, open(out[:-4] + '.json', 'w')); print('done', out, rec['knobs'])


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 52.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
