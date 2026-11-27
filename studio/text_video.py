#!/usr/bin/env python3
"""The notes account (@moth.ate.my.notes): one thought on a colour gradient, the way people post text on Instagram.

    python studio/text_video.py SONG_DIR SEED OUT.mp4 [--frames a,b,c]        (CQ_WINDOW="t0,t1")

The nightly job's renderer for the "notes" style and, through the voice wrappers (text_her_video.py and the others), for
the other text pages. A card is one block from studio/notes/lines.txt set in the middle of a soft gradient: lower case,
centred, white with a soft shadow or black with none, in a rounded bold face or a tall narrow one. `look: notes` is a
literal notes-app page instead: cream, system-ish type, the handle as the note's title, a "today 2:14 am" line. Nothing
else is on the card: no song label (the song is the sound, and the caption credits it). The gradient drifts slowly and
breathes a little with the kick, so it is a video and not a still.

Two beats (knob `reveal`, beat 3 : none 1): the block's setup is on frame 0 and its payoff lands on the first downbeat
after 2.0-2.5 s with a six-frame rise, so there is something to wait for. The setup is the rows before the block's first
blank line, or the first line of a several-line block, or what is before a "/" in a one-liner, or (a one-liner of 8+
words) everything before its last clause. A card with no place to split is one beat and records no `reveal`. One beat
runs 7 s at most, two beats 9 s; the last 9 frames fade the gradient (not the text) back to frame 0's, so the loop has
no seam.

Knobs: line (which thought), reveal, look, ink (white / black), face (round / tall / strong). `kind` (song / friend /
self / list / two-beat) is read off the line, not chosen, and recorded so the learner can see the kinds of writing. The
.json beside the video carries plan.caption, the card's own text (its first beat when the block was written with a
pause), which src/cli.py puts first in the post's caption. A line is not used twice: lines already in
campaigns/notes_app/recipes.json are left out until all have been (nightly.py also chooses the line, off everything
posted and everything rendered tonight).
"""
import json, math, os, random, re, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K

W, H, FPS = 1080, 1920, 30
MAX_SEC = {'none': 7.0, 'beat': 9.0}    # a text post is read in a few seconds: short, so a re-read is a second loop
TAIL = 9                                # frames of the loop fade at the end
RISE = 6                                # frames the payoff takes to land
SAFE = (96, 924)                        # the x range Instagram's own buttons and caption leave clear; the text sits in it
BANK = os.path.join(HERE, 'notes', 'lines.txt'); RECIPES = os.path.join(REPO, 'campaigns', 'notes_app', 'recipes.json')
PREFIX = 'n'            # line ids: n001, n002, ... (each voice's bank has its own letter)
HANDLE = 'moth.ate.my.notes'            # the note's title in the notes look
# Which looks, inks and faces a page uses, with weights. The voice wrappers (text_her_video.py, ...) set their own
# before running; no look is shared between two pages (docs/brain/reviews/2026-11-26/notes.md §9.6).
LOOK_W = {'dusk': 3, 'orchid': 3, 'notes': 2}
INK_W = {'white': 3, 'black': 1}
FACE_W = {'round': 3, 'tall': 1}
REVEAL_W = {'beat': 3, 'none': 1}
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
    # wet tarmac at night with one streetlight in it: the skate page's dark look
    'asphalt': [(0.5, -0.1, (26, 27, 31)), (0.0, 0.35, (44, 46, 54)), (1.05, 0.45, (34, 33, 40)), (0.75, 0.85, (92, 74, 52)), (0.15, 1.1, (38, 36, 42))],
    # a warm, nearly flat cream: a paper card for the college page (black ink only)
    'paper': [(0.5, -0.1, (246, 240, 226)), (0.0, 0.4, (240, 231, 212)), (1.05, 0.5, (250, 246, 236)), (0.4, 1.1, (236, 226, 206))],
    'notes': [(0.5, 0.5, (247, 243, 232))],                                    # a flat page; drawn by notes_page()
})
BLACK_OK = {'sunset', 'lagoon', 'rainbow', 'citrus', 'meadow', 'paper', 'notes'}   # black text only where the gradient is light enough to carry it
BLACK_ONLY = {'paper', 'notes'}                                                   # and nothing else there
NOTES = dict(ink=(28, 27, 30), grey=(138, 136, 130), title=60, time=38, body=72, pitch=1.32, x=120, top=600, rows=9)
KINDS = ('song', 'friend', 'self', 'list', 'two-beat')
SONG_RE = re.compile(r"\b(songs?|playlists?|album|music|speakers?|headphones|earbuds|aux|volume|lyrics?|chorus|the sound|this sound|on repeat|sing(s|ing)?|tracks?|melody|concert|setlist|loop)\b")
FRIEND_RE = re.compile(r"\b(he|she|they|him|her|them|his|hers|their|bestie|ex|boyfriend|girlfriend|bro|the boys|the girls|friends?|roommate|crush|situationship|talking stage|homie|mutuals|my (man|girl|guy)|the (gc|group chat))\b")
CLAUSE = ('. ', '? ', '! ', ': ', ', ')
JOIN = (' and ', ' but ', ' so ', ' like ', ' because ', ' then ')     # where an unpunctuated one-liner turns


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


def kind_of(text):
    """What sort of writing a block is: a list, a line about the sound (song), a card written with a pause (two-beat),
    a line about someone else (friend), or about oneself (self). Read off the line, so the learner can compare kinds."""
    rows = [r for r in text.split('\n') if r.strip()]
    if sum(bool(re.match(r'\s*(-|\d+[.)])\s', r)) for r in rows) >= 2: return 'list'
    low = text.lower()
    if SONG_RE.search(low): return 'song'
    if '\n\n' in text.strip(): return 'two-beat'
    if FRIEND_RE.search(low): return 'friend'
    return 'self'


def beats(text):
    """(setup, payoff, gap): the card's two beats, or (text, None, False) when there is no place to split. The setup is
    everything before the block's first blank line (gap: a blank row stays between them), else the first line of a
    several-line block, else what is before a "/" in a one-liner, else (8+ words) everything before the last clause
    (the last ". " / ", " / ": " ...; with no punctuation at all, before the last "and" / "but" / "so" / "like")."""
    text = text.strip('\n')
    if '\n\n' in text:
        a, b = text.split('\n\n', 1); return a.rstrip(), b.strip('\n'), True
    if '\n' in text:
        a, b = text.split('\n', 1); return a, b, False
    if ' / ' in text:
        a, b = text.split(' / ', 1); return a.strip(), b.strip(), False
    if len(text.split()) >= 8:
        cut = max(text.rfind(p) for p in CLAUSE)
        if cut > 0:
            a, b = text[:cut + 1].strip(), text[cut + 2:].strip()
            if len(a.split()) >= 3 and len(b.split()) >= 2: return a, b, False
        else:
            cut = max(text.rfind(p) for p in JOIN)
            a, b = text[:cut].strip(), text[cut + 1:].strip()
            if cut > 0 and len(a.split()) >= 4 and len(b.split()) >= 3: return a, b, False
    return text, None, False


def caption_of(text):
    """What the post's caption opens with: the card's first beat when the block was written with a pause, a "/" or
    several lines (the payoff stays on the video), else the whole card on one line."""
    head, tail, gap = beats(text)
    if tail is not None and ('\n' in text.strip('\n') or ' / ' in text): return ' '.join(head.replace(' / ', ' ').split())
    return ' '.join(text.replace(' / ', ' ').split())


def wrap(text, font, width):
    """The card's rows: the block's own line breaks kept, long lines broken at spaces to fit the width. '' is a gap."""
    rows = []
    for line in text.replace(' / ', '\n').split('\n'):
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
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0 = t0
        r = random.Random(seed * 9973 + 5)
        lines = bank(); text = dict(lines); ids = unused(lines)
        want = K.FORCED.get('kind')                            # nightly may ask for a kind of writing; the line itself wins
        if want and 'line' not in K.FORCED: ids = [i for i in ids if kind_of(text[i]) == want] or ids
        self.line = K.pick('line', ids, r)
        self.text = text.get(self.line) or lines[0][1]
        self.kind = kind_of(self.text); K.MENU['kind'] = list(KINDS); K.CHOSEN['kind'] = self.kind   # recorded, not chosen
        looks = sorted(LOOK_W); self.look = K.pick('look', looks, r, weights=[LOOK_W[k] for k in looks])
        inks = sorted(INK_W); self.ink = K.pick('ink', inks, r, weights=[INK_W[k] for k in inks])
        if self.ink == 'black' and self.look not in BLACK_OK: self.ink = 'white'; K.CHOSEN['ink'] = 'white'
        if self.look in BLACK_ONLY: self.ink = 'black'; K.CHOSEN['ink'] = 'black'
        faces = sorted(FACE_W); self.face = K.pick('face', faces, r, weights=[FACE_W[k] for k in faces])
        if self.look == 'notes': self.face = 'round'; K.drop('ink'); K.drop('face')   # the notes page has one type and one ink
        self.head, self.tail, self.gap = beats(self.text)
        revs = sorted(REVEAL_W); self.reveal = K.pick('reveal', revs, r, weights=[REVEAL_W[k] for k in revs])
        if self.tail is None: self.reveal = 'none'; K.drop('reveal')           # nowhere to split: one beat, nothing to learn
        self.t1 = t1 = min(t1, t0 + MAX_SEC[self.reveal])
        a = audio.load(self.slug, t0, t1); self.n = a['n']
        self.kick = audio.hits(a['kicks'], self.n, 4.0); self.bass = np.convolve(a['bass'], np.ones(9) / 9, 'same')
        self.phase = r.uniform(0, 6.28); self.stamp = 'today %d:%02d am' % (r.choice((1, 1, 2, 2, 3, 12)), r.randrange(0, 60))
        self.at = self.landing(a, r) if self.reveal == 'beat' else None
        if self.reveal == 'beat' and self.at is None: self.reveal = 'none'; K.drop('reveal')   # too short for a payoff
        if self.reveal == 'none': self.head, self.tail, self.gap = self.text, None, False
        self.caption = caption_of(self.text)
        self._g0 = None; self.layers = self.typeset()

    def landing(self, a, r):
        """The frame the payoff lands on: the first downbeat 2.0-2.5 s in (a beat if there is no downbeat in reach),
        leaving it at least 2 s on screen; None when the video is too short for that."""
        want = r.uniform(2.0, 2.5) * FPS; last = self.n - 2 * FPS
        for grid in ([f for b, f in a['beats'] if b % 4 == 0], [f for b, f in a['beats']]):
            ok = [int(round(f)) for f in grid if want <= f <= last]
            if ok: return ok[0]
        return int(want) if want <= last else None

    def typeset(self):
        """The text as layers the size of the frame: [(letters, shadow)] for the setup and, with two beats, the payoff.
        Rows are laid out once for the whole card, so the setup never moves when the payoff lands."""
        notes = self.look == 'notes'
        file, weight, size, pitch = ('Figtree.ttf', 500, NOTES['body'], NOTES['pitch']) if notes else FACES[self.face]
        width = SAFE[1] - NOTES['x'] if notes else SAFE[1] - SAFE[0]        # inside Instagram's safe column (x 96-924)
        def font(sz):
            f = ImageFont.truetype(os.path.join(REPO, 'fonts', file), sz)
            if weight: f.set_variation_by_axes([weight])
            return f
        def lay(sz):
            f = font(sz)
            if self.tail is None: return f, wrap(self.head, f, width), None
            head = wrap(self.head, f, width) + ([''] if self.gap else [])
            return f, head + wrap(self.tail, f, width), len(head)
        f, rows, split = lay(size)
        if not notes:
            big = int(size * 1.18); fb, rb, sb = lay(big)
            if len(rb) <= 5: size, f, rows, split = big, fb, rb, sb                 # a short thought is set larger
        most = NOTES['rows'] if notes else (11 if self.face == 'round' else 12)
        while len(rows) > most and size > 48:                                     # a long one: smaller type, never off the card
            size -= 6; f, rows, split = lay(size)
        step = size * pitch; heights = [step if row else step * 0.62 for row in rows]
        y = NOTES['top'] + size * 0.82 if notes else H * 0.47 - sum(heights) / 2 + size * 0.82   # optically centred, clear of Instagram's own text
        ink = NOTES['ink'] + (255,) if notes else (255, 255, 255, 255) if self.ink == 'white' else (14, 12, 16, 255)
        parts, start = [], 0
        for end in ([split] if split is not None else []) + [len(rows)]:
            layer = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
            shadow = Image.new('L', (W, H), 0); ds = ImageDraw.Draw(shadow)
            yy = y + sum(heights[:start])
            for row, h in zip(rows[start:end], heights[start:end]):
                if row:
                    at, anchor = ((NOTES['x'], yy), 'ls') if notes else ((sum(SAFE) / 2, yy), 'ms')
                    d.text(at, row, font=f, fill=ink, anchor=anchor); ds.text((at[0], yy + 4), row, font=f, fill=255, anchor=anchor)
                yy += h
            start = end
            shadow = shadow.filter(ImageFilter.GaussianBlur(7)) if self.ink == 'white' else None
            parts.append((np.asarray(layer).astype(np.float32), None if shadow is None else np.asarray(shadow).astype(np.float32) / 255.0))
        return parts

    def notes_page(self):
        """The notes look's page: cream, the handle as the note's title, the time line under it."""
        im = Image.new('RGB', (W, H), LOOKS['notes'][0][2]); d = ImageDraw.Draw(im)
        t = ImageFont.truetype(os.path.join(REPO, 'fonts', 'Figtree.ttf'), NOTES['title']); t.set_variation_by_axes([700])
        s = ImageFont.truetype(os.path.join(REPO, 'fonts', 'Figtree.ttf'), NOTES['time']); s.set_variation_by_axes([500])
        d.text((NOTES['x'], 460), HANDLE, font=t, fill=NOTES['ink'], anchor='ls')
        d.text((NOTES['x'], 522), self.stamp, font=s, fill=NOTES['grey'], anchor='ls')
        return np.asarray(im).astype(np.float32)

    def gradient(self, i):
        """The blobs drift on slow circles; computed small and blown up (it is all soft)."""
        if self.look == 'notes':
            if self._g0 is None: self._g0 = self.notes_page()
            return self._g0
        t = i / FPS; gw, gh = 90, 160
        yy, xx = np.mgrid[0:gh, 0:gw].astype(np.float32); u = xx / (gw - 1); v = yy / (gh - 1)
        num = np.zeros((gh, gw, 3), np.float32); den = np.zeros((gh, gw, 1), np.float32)
        for k, (bx, by, c) in enumerate(LOOKS[self.look]):
            ax = bx + 0.07 * math.sin(0.23 * t + self.phase + 1.9 * k); ay = by + 0.05 * math.cos(0.19 * t + self.phase + 1.3 * k)
            w = 1.0 / (((u - ax) ** 2 + ((v - ay) * 1.3) ** 2) + 0.12) ** 2.0
            num += w[..., None] * np.array(c, np.float32); den += w[..., None]
        g = cv2.resize(num / den, (W, H), interpolation=cv2.INTER_CUBIC)
        return g * (1.0 + 0.035 * float(self.kick[i]) + 0.03 * float(self.bass[i]))

    @staticmethod
    def ink_on(g, layer, shadow, k=1.0, dy=0):
        """The letters over the gradient at opacity k, dropped dy pixels (the payoff rises into place)."""
        if dy: layer = np.roll(layer, dy, 0); shadow = None if shadow is None else np.roll(shadow, dy, 0)
        if shadow is not None: g = g * (1 - 0.30 * k * shadow[..., None])        # a soft dark halo under white text
        a = layer[..., 3:4] / 255.0 * k
        return g * (1 - a) + layer[..., :3] * a

    def frame(self, i):
        g = self.gradient(i)
        if i >= self.n - TAIL and self.look != 'notes':                           # the loop: the gradient eases back to frame 0's
            if self._g0 is None: self._g0 = self.gradient(0)
            a = (i - (self.n - TAIL) + 1) / (TAIL + 1); g = g * (1 - a) + self._g0 * a
        g = self.ink_on(g, *self.layers[0])
        if len(self.layers) > 1 and i >= self.at:
            k = min(1.0, (i - self.at + 1) / RISE); g = self.ink_on(g, *self.layers[1], k=k, dy=int(round(18 * (1 - k))))
        rng = np.random.default_rng(i); g = g + rng.normal(0, 1.2, (H // 4, W // 4, 1)).repeat(4, 0).repeat(4, 1)   # a little grain: no banding
        return np.clip(g, 0, 255).astype(np.uint8)

    def plan(self):
        """What the recipe keeps besides the knobs: the caption the post opens with, the kind, when the payoff lands."""
        return dict(caption=self.caption, kind=self.kind, reveal_sec=None if self.at is None else round(self.at / FPS, 2))

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.plan(), 'frames', self.n); return
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
        json.dump(dict(K.record(), plan=self.plan()), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


def run():
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW')
    t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 39.0)
    Video(song_dir, seed, t0, t1).render(out)


if __name__ == '__main__':
    run()
