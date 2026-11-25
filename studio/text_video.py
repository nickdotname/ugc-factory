#!/usr/bin/env python3
"""The notes account (@moth.ate.my.notes): one thought on a colour gradient, the way people post text on Instagram.

    python studio/text_video.py SONG_DIR SEED OUT.mp4 [--frames a,b,c]        (CQ_WINDOW="t0,t1")

The nightly job's renderer for the "notes" style. A card is one block from studio/notes/lines.txt set in the middle
of a soft gradient: lower case, centred, white with a soft shadow or black with none, in a rounded bold face or a
tall narrow one. Nothing else is on the card: no song label (the song is the sound, and the caption credits it). The
gradient drifts slowly and breathes a little with the kick, so it is a video and not a still.
Knobs: line (which thought), look (the gradient), ink (white / black), face (round / tall).
A line is not used twice: lines already in campaigns/notes_app/recipes.json are left out until all have been used.
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30
MAX_SEC = 11.0                          # a text post is read in a few seconds: the video is short so it loops
BANK = os.path.join(HERE, 'notes', 'lines.txt'); RECIPES = os.path.join(REPO, 'campaigns', 'notes_app', 'recipes.json')
PREFIX = 'n'            # line ids: n001, n002, ... (each voice's bank has its own letter)
# Which looks, inks and faces a page uses, with weights. The voice wrappers (text_her_video.py, text_him_video.py) set
# their own before running.
LOOK_W = {'dusk': 3, 'lagoon': 2, 'orchid': 3, 'sunset': 3}
INK_W = {'white': 3, 'black': 1}
FACE_W = {'round': 3, 'tall': 1}
FACES = {'round': ('Figtree.ttf', 800, 82, 1.20), 'tall': ('BarlowCondensed-Medium.ttf', None, 104, 1.12),
         'strong': ('Montserrat-ExtraBold.ttf', None, 90, 1.18)}   # file, weight, size, line pitch
# Gradients as a few soft blobs of colour: (x, y, colour), x and y in 0..1 of the frame.
LOOKS = {'dusk': [(0.0, -0.05, (48, 132, 250)), (0.9, 0.25, (112, 70, 245)), (0.15, 0.6, (128, 60, 240)), (1.0, 0.8, (214, 44, 220)), (0.4, 1.1, (190, 60, 235))],
         'sunset': [(0.5, -0.1, (176, 30, 62)), (0.0, 0.3, (232, 62, 52)), (1.05, 0.5, (246, 206, 80)), (0.4, 0.62, (238, 122, 40)), (0.0, 1.0, (214, 60, 48)), (0.9, 1.05, (232, 110, 40))],
         'orchid': [(0.5, -0.1, (196, 110, 248)), (1.0, 0.15, (150, 44, 232)), (0.0, 0.42, (240, 142, 244)), (0.85, 0.75, (232, 54, 190)), (0.25, 1.1, (232, 50, 140))],
         'lagoon': [(0.1, -0.1, (40, 200, 190)), (1.0, 0.2, (60, 120, 240)), (0.0, 0.55, (70, 210, 160)), (0.9, 0.8, (90, 90, 235)), (0.3, 1.1, (40, 150, 220))]}
LOOKS.update({
    # the light rainbow wash text pages use: yellow top left, teal top right, orange through red, violet bottom right
    'rainbow': [(0.0, -0.05, (240, 222, 80)), (1.05, 0.0, (70, 160, 210)), (0.55, 0.12, (150, 200, 110)), (0.1, 0.5, (240, 150, 50)),
                (0.95, 0.55, (180, 120, 170)), (0.2, 0.95, (232, 60, 70)), (0.95, 1.05, (160, 70, 200))],
    'citrus': [(0.3, -0.1, (232, 64, 72)), (0.0, 0.35, (236, 110, 52)), (1.05, 0.55, (246, 214, 92)), (0.45, 0.7, (238, 140, 56)), (0.2, 1.1, (232, 96, 48))],
    'meadow': [(0.6, -0.1, (80, 160, 230)), (1.05, 0.3, (110, 180, 240)), (0.0, 0.45, (70, 190, 170)), (0.8, 0.8, (90, 200, 110)), (0.2, 1.1, (200, 200, 60))],
})
BLACK_OK = {'sunset', 'lagoon', 'rainbow', 'citrus', 'meadow'}         # black text only where the gradient is light enough to carry it


def bank():
    """[(id, text)] in file order; ids are n001, n002, ... so they stay put as long as new lines go at the end."""
    blocks = open(BANK, encoding='utf-8').read().split('\n---\n')[1:]
    return [('%s%03d' % (PREFIX, k + 1), b.strip('\n')) for k, b in enumerate(blocks) if b.strip()]


def unused(lines):
    try: seen = [(e.get('knobs') or {}).get('line') for e in json.load(open(RECIPES)).get('nightly', [])]
    except Exception: seen = []
    seen = [s for s in seen if s]; ids = [i for i, _ in lines]
    left = [i for i in ids if i not in seen]
    if left: return left
    last = {i: k for k, i in enumerate(seen)}                 # all used: start again from the ones used longest ago
    return sorted(ids, key=lambda i: last.get(i, -1))[:max(1, len(ids) // 2)]


def wrap(text, font, width):
    """The card's rows: the block's own line breaks kept, long lines broken at spaces to fit the width. '' is a gap."""
    rows = []
    for line in text.split('\n'):
        if not line.strip(): rows.append(''); continue
        cur = ''
        for word in line.split(' '):
            trial = (cur + ' ' + word).strip()
            if cur and font.getlength(trial) > width: rows.append(cur); cur = word
            else: cur = trial
        rows.append(cur)
    for k in range(len(rows) - 1):                             # a row does not end on "i" or "a": it starts the next one
        if rows[k].count(' ') >= 2 and rows[k + 1] and rows[k].rsplit(' ', 1)[1] in ('i', 'a', 'my', 'the', 'and', 'to'):
            head, tail = rows[k].rsplit(' ', 1)
            if font.getlength(tail + ' ' + rows[k + 1]) <= width: rows[k], rows[k + 1] = head, tail + ' ' + rows[k + 1]
    # no widows: a last row of one short word takes a word from the row above
    for k in range(1, len(rows)):
        if rows[k] and rows[k - 1] and ' ' not in rows[k] and len(rows[k]) < 6 and rows[k - 1].count(' ') >= 2:
            head, tail = rows[k - 1].rsplit(' ', 1); rows[k - 1], rows[k] = head, tail + ' ' + rows[k]
    return rows


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0 = t0; self.t1 = t1 = min(t1, t0 + MAX_SEC)
        r = random.Random(seed * 9973 + 5)
        lines = bank(); text = dict(lines)
        self.line = K.pick('line', unused(lines), r)
        looks = sorted(LOOK_W); self.look = K.pick('look', looks, r, weights=[LOOK_W[k] for k in looks])
        inks = sorted(INK_W); self.ink = K.pick('ink', inks, r, weights=[INK_W[k] for k in inks])
        if self.ink == 'black' and self.look not in BLACK_OK: self.ink = 'white'; K.CHOSEN['ink'] = 'white'
        faces = sorted(FACE_W); self.face = K.pick('face', faces, r, weights=[FACE_W[k] for k in faces])
        self.text = text.get(self.line) or lines[0][1]
        a = audio.load(self.slug, t0, t1); self.n = a['n']
        self.kick = audio.hits(a['kicks'], self.n, 4.0); self.bass = np.convolve(a['bass'], np.ones(9) / 9, 'same')
        self.phase = r.uniform(0, 6.28)
        self.layer, self.shadow = self.typeset()

    def typeset(self):
        """The text as two layers the size of the frame: the letters, and (for white ink) their soft shadow."""
        file, weight, size, pitch = FACES[self.face]
        def font(sz):
            f = ImageFont.truetype(os.path.join(REPO, 'fonts', file), sz)
            if weight: f.set_variation_by_axes([weight])
            return f
        f = font(size); rows = wrap(self.text, f, 900)
        big = int(size * 1.18); fb = font(big); rb = wrap(self.text, fb, 900)
        if len(rb) <= 5: size, f, rows = big, fb, rb                             # a short thought is set larger
        while len(rows) > (11 if self.face == 'round' else 12) and size > 56:   # a long one: smaller type, never off the card
            size -= 6; f = font(size); rows = wrap(self.text, f, 900)
        step = size * pitch; heights = [step if row else step * 0.62 for row in rows]
        y = H * 0.47 - sum(heights) / 2 + size * 0.82                           # optically centred, clear of Instagram's own text
        ink = (255, 255, 255, 255) if self.ink == 'white' else (14, 12, 16, 255)
        layer = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
        shadow = Image.new('L', (W, H), 0); ds = ImageDraw.Draw(shadow)
        for row, h in zip(rows, heights):
            if row:
                d.text((W / 2, y), row, font=f, fill=ink, anchor='ms')
                ds.text((W / 2, y + 4), row, font=f, fill=255, anchor='ms')
            y += h
        shadow = shadow.filter(ImageFilter.GaussianBlur(7)) if self.ink == 'white' else None
        return np.asarray(layer).astype(np.float32), (np.asarray(shadow).astype(np.float32) / 255.0 if shadow is not None else None)

    def gradient(self, i):
        """The blobs drift on slow circles; computed small and blown up (it is all soft)."""
        t = i / FPS; gw, gh = 90, 160
        yy, xx = np.mgrid[0:gh, 0:gw].astype(np.float32); u = xx / (gw - 1); v = yy / (gh - 1)
        num = np.zeros((gh, gw, 3), np.float32); den = np.zeros((gh, gw, 1), np.float32)
        for k, (bx, by, c) in enumerate(LOOKS[self.look]):
            ax = bx + 0.07 * math.sin(0.23 * t + self.phase + 1.9 * k); ay = by + 0.05 * math.cos(0.19 * t + self.phase + 1.3 * k)
            w = 1.0 / (((u - ax) ** 2 + ((v - ay) * 1.3) ** 2) + 0.12) ** 2.0
            num += w[..., None] * np.array(c, np.float32); den += w[..., None]
        g = cv2.resize(num / den, (W, H), interpolation=cv2.INTER_CUBIC)
        return g * (1.0 + 0.035 * float(self.kick[i]) + 0.03 * float(self.bass[i]))

    def frame(self, i):
        g = self.gradient(i)
        if self.shadow is not None: g = g * (1 - 0.30 * self.shadow[..., None])   # a soft dark halo under white text
        a = self.layer[..., 3:4] / 255.0
        g = g * (1 - a) + self.layer[..., :3] * a
        rng = np.random.default_rng(i); g += rng.normal(0, 1.2, (H // 4, W // 4, 1)).repeat(4, 0).repeat(4, 1)   # a little grain: no banding
        return np.clip(g, 0, 255).astype(np.uint8)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '18'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n): p.stdin.write(self.frame(i).tobytes())
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


def run():
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW')
    t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 41.0)
    Video(song_dir, seed, t0, t1).render(out)


if __name__ == '__main__':
    run()
