"""Math In Time (the math-explainer account), shared by every scene: beat clock, themes, typesetting, smooth (sub-pixel) compositing, glow,
camera moves and smooth shakes. Each video picks a theme, typeface, background and shake strength, so the
account never looks the same twice; the choices go through knobs so the learner can tell which work."""
import sys, os, io, math, json, subprocess, random
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
import matplotlib; matplotlib.use('Agg'); matplotlib.rcParams['mathtext.fontset'] = 'cm'
import matplotlib.pyplot as plt
_HERE = os.path.dirname(os.path.abspath(__file__)); _STUDIO = os.path.dirname(_HERE); _REPO = os.path.dirname(_STUDIO)
sys.path.insert(0, _HERE); import beat as audio
sys.path.insert(0, _STUDIO); import knobs as K

W, H, FPS = 1080, 1920, 30
def _font(*names):
    """The first of these fonts found: the repo's fonts/ first, then the system's (CI installs fonts-inter and fonts-dejavu-core)."""
    roots = [os.path.join(_REPO, 'fonts'), '/usr/share/fonts', '/Library/Fonts', os.path.expanduser('~/Library/Fonts')]
    for n in names:
        for r in roots:
            if os.path.exists(os.path.join(r, n)): return os.path.join(r, n)
            for d, _, fs in os.walk(r) if os.path.isdir(r) else ():
                if n in fs: return os.path.join(d, n)
    return os.path.join(_REPO, 'fonts', 'Montserrat-ExtraBold.ttf')

FONTS = {'poppins': _font('Poppins-Bold.ttf'), 'inter': _font('Inter-ExtraBold.otf', 'Montserrat-ExtraBold.ttf'), 'montserrat': _font('Montserrat-ExtraBold.ttf')}
INTER = _font('Inter-SemiBold.otf', 'Poppins-Bold.ttf'); MONO = _font('DejaVuSansMono-Bold.ttf')
DEJAVU = _font('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')

def conf(slug, b0):
    """Which song, where in it, and which look: the nightly sets these through the environment (studio/math_video.py);
    run by hand, a scene uses its own song and moment, and --seed N."""
    seed = int(sys.argv[sys.argv.index('--seed') + 1]) if '--seed' in sys.argv else 1
    return os.environ.get('CQ_MATH_SONG', slug), float(os.environ.get('CQ_MATH_B0', b0)), int(os.environ.get('CQ_MATH_SEED', seed))

def beats(default=44):
    """How many beats the scene has: 44 (eleven bars, the full explainer) or 24 (six bars: the question on frame 0, the
    resolve by the end, and the last 9 frames fading into frame 0 so it loops). math_video.py's `beats` knob sets it
    through the environment; by hand, --beats N."""
    if '--beats' in sys.argv: return int(sys.argv[sys.argv.index('--beats') + 1])
    return int(os.environ.get('CQ_MATH_BEATS', default))

def short(): return beats() == 24

def credit(slug):
    s = json.load(open(os.path.join(audio.SONGS, slug, 'song.json')))
    return '\u266a %s \u2014 %s' % (s.get('title', slug), s.get('artist', 'Close Quarters'))

def seconds(clock): return int(round(clock.beats * clock.spb))

THEMES = {   # background, grid, text, muted, and three accents (curve / fill / highlight)
    'midnight': dict(bg=(10, 13, 22), grid=(26, 31, 46), fg=(240, 244, 250), muted=(140, 150, 170), a=(255, 209, 102), b=(46, 196, 182), c=(255, 99, 146), d=(90, 200, 255)),
    'chalk':    dict(bg=(18, 30, 24), grid=(30, 46, 38), fg=(236, 240, 230), muted=(150, 170, 155), a=(250, 230, 120), b=(120, 200, 230), c=(255, 140, 150), d=(160, 235, 170)),
    'synth':    dict(bg=(18, 8, 32), grid=(44, 22, 70), fg=(245, 235, 255), muted=(170, 150, 200), a=(255, 90, 220), b=(80, 220, 255), c=(255, 200, 90), d=(140, 120, 255)),
    'mono':     dict(bg=(6, 6, 8), grid=(24, 24, 28), fg=(245, 245, 245), muted=(150, 150, 155), a=(190, 255, 90), b=(120, 120, 130), c=(255, 255, 255), d=(190, 255, 90)),
    'paper':    dict(bg=(244, 239, 228), grid=(226, 218, 200), fg=(28, 34, 48), muted=(110, 110, 120), a=(220, 70, 50), b=(40, 120, 200), c=(230, 140, 30), d=(30, 150, 120)),
}

class Style:
    def __init__(self, seed):
        r = random.Random(seed)
        self.theme = K.pick('theme', sorted(THEMES), r); T = THEMES[self.theme]
        self.font = K.pick('font', sorted(FONTS), r); self.pattern = K.pick('grid', ['grid', 'dots', 'none'], r)   # (self.grid is the theme's grid colour)
        self.shake = float(K.pick('shake', [0.6, 1.0, 1.3], r)); self.glow = float(K.pick('glow', [0.6, 1.0], r))
        self.chip = K.pick('chip', ['pill', 'tag'], r)
        for k, v in T.items(): setattr(self, k, v)
        self.light = self.theme == 'paper'
    def hx(self, c): return '#%02x%02x%02x' % c

class Clock:
    """Time in beats, from the song's measured beat map (studio/beatmap.py): b0 and the length are in beats, and
    beat(i) is the exact (fractional) beat at video frame i, so a scene choreographed in beats stays on the music
    even where the band speeds up or slows down."""
    def __init__(self, slug, b0, beats, loop=False):
        s = json.load(open(os.path.join(audio.SONGS, slug, 'song.json'))); self.song = s
        self.slug = slug; self.spb = 60 / s['tempo']; self.b0 = b0; self.beats = beats
        self.loop = bool(loop)                                      # a short scene loops: render() fades its last 9 frames into frame 0
        self.t0 = audio.time_of_beat(s, b0); self.t1 = audio.time_of_beat(s, b0 + beats)
        a = audio.load(slug, self.t0, self.t1); self.n = a['n']
        k = audio.hits(a['kicks'], self.n, 7.0); self.kick = np.convolve(k, [0.25, 0.5, 0.25], 'same')   # a touch softened: no one-frame pops
        self.snare = audio.hits(a['snares'], self.n, 10.0); self.bass = a['bass']
        self.kick_beats = [self.beat(f) for f in a['kicks']]; self.snare_beats = [self.beat(f) for f in a['snares']]
        self.kick_frames = [int(f) for f in a['kicks']]; self.snare_frames = [int(f) for f in a['snares']]   # the same hits, as video frames
        self.hat = audio.hits(a['hats'], self.n, 14.0); self.vox = a['vocals']
    def beat(self, i): return audio.beat_of_time(self.song, self.t0 + i / FPS) - self.b0

_FC = {}
def F(path, size):
    if (path, size) not in _FC: _FC[(path, size)] = ImageFont.truetype(path, size)
    return _FC[(path, size)]

SS = 2   # sprites are drawn at twice their size and scaled down when placed: crisp at every scale, no shimmer
_MC = {}
def tex(s, size, color):
    """Formula sprite. Typeset in the middle of a canvas far larger than the formula, then crop to the ink:
    matplotlib's tight bounding box cuts the hooks off big symbols (the integral sign above all), this never does."""
    k = (s, size, color)
    if k not in _MC:
        px = size * SS
        fig = plt.figure(figsize=(max(6.0, px * len(s) / 90), max(4.0, px / 14)), dpi=100)
        fig.text(0.5, 0.5, s, fontsize=px, color=color, ha='center', va='center')
        buf = io.BytesIO(); fig.savefig(buf, dpi=100, transparent=True); plt.close(fig)
        a = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert('RGBA'))
        ys, xs = np.nonzero(a[..., 3])
        assert 0 < ys.min() and ys.max() < a.shape[0] - 1 and 0 < xs.min() and xs.max() < a.shape[1] - 1, 'formula touches the canvas edge: ' + s
        m = 10 * SS
        _MC[k] = _prep(Image.fromarray(a[max(0, ys.min() - m):ys.max() + m + 1, max(0, xs.min() - m):xs.max() + m + 1].copy()))
    return _MC[k]

def text(s, font, fill, stroke=0, stroke_fill=(8, 10, 16)):
    k = (s, font.path, font.size, fill, stroke)
    if k not in _MC:
        f2 = F(font.path, font.size * SS); bb = f2.getbbox(s, stroke_width=stroke * SS); m = 12 * SS
        im = Image.new('RGBA', (bb[2] - bb[0] + 2 * m, bb[3] - bb[1] + 2 * m), (0, 0, 0, 0))   # sized to the real ink box: nothing hangs off
        ImageDraw.Draw(im).text((m - bb[0], m - bb[1]), s, font=f2, fill=fill, stroke_width=stroke * SS, stroke_fill=stroke_fill); _MC[k] = _prep(im)
    return _MC[k]

def chip(st, n, s, color):
    k = ('chip', st.theme, st.chip, n, s, color)
    if k not in _MC:
        f = F(FONTS[st.font], 50 * SS); fn = F(FONTS[st.font], 44 * SS); tw = f.getlength(s)
        pad = 46 * SS; h = 92 * SS
        im = Image.new('RGBA', (int(tw) + 130 * SS, h + 4), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        panel = tuple(int(v) for v in (np.array(st.bg) * 0.88 + 255 * 0.12 if st.light else np.array(st.bg) * 0.6 + np.array(st.fg) * 0.08)) + (235,)
        if st.chip == 'pill':
            d.rounded_rectangle([0, 0, im.width - 1, h], radius=pad, fill=panel, outline=color + (255,), width=3 * SS)
            d.ellipse([10 * SS, 10 * SS, 82 * SS, 82 * SS], fill=color + (255,)); d.text((46 * SS, 46 * SS), str(n), font=fn, fill=st.bg, anchor='mm')
            d.text((104 * SS, 46 * SS), s, font=f, fill=st.fg, anchor='lm')
        else:                                   # a plain tag: the step number in the accent colour, then the words, underlined
            d.text((10 * SS, 46 * SS), '%d.' % n, font=fn, fill=color, anchor='lm'); d.text((84 * SS, 46 * SS), s, font=f, fill=st.fg, anchor='lm')
            d.rectangle([84 * SS, 84 * SS, 84 * SS + tw, 90 * SS], fill=color + (255,))
        _MC[k] = _prep(im)
    return _MC[k]

def chips(c, st, k, seq, y=330):
    """The numbered steps: each pops in on its beat and is gone by the next one's, so two never overlap."""
    for a, b, n, words, color in seq:
        if a <= k < b:
            e = float(ease_back((k - a) / 0.45)); out = 1 - float(ease_out((k - (b - 0.3)) / 0.3))
            paste(c, chip(st, n, words, color), W / 2, y, e, min(1, e) * out)

def _prep(im):
    a = np.asarray(im).astype(np.float32) / 255.0
    return np.dstack([a[..., :3] * a[..., 3:4], a[..., 3]])          # premultiplied RGBA, float

def ease_out(x): x = np.clip(x, 0, 1); return 1 - (1 - x) ** 3
def ease_in_out(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)
def ease_back(x):
    x = np.clip(x, 0, 1); c = 1.5; return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2
def window(k, a, b, fade=0.5): return float(ease_out((k - a) / fade) * (1 - ease_out((k - b) / fade)))

def paste(canvas, sp, cx, cy, scale=1.0, alpha=1.0):
    """Place a sprite centred on (cx, cy) at any scale and sub-pixel position, blended smoothly."""
    if alpha <= 0.004 or scale <= 0.01: return
    s = scale / SS; h, w = sp.shape[:2]; bw, bh = w * s, h * s
    x0, y0 = int(math.floor(cx - bw / 2)) - 1, int(math.floor(cy - bh / 2)) - 1; x1, y1 = int(math.ceil(cx + bw / 2)) + 1, int(math.ceil(cy + bh / 2)) + 1
    X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if X1 <= X0 or Y1 <= Y0: return
    M = np.array([[s, 0, cx - bw / 2 - X0], [0, s, cy - bh / 2 - Y0]], np.float32)
    patch = cv2.warpAffine(sp, M, (X1 - X0, Y1 - Y0), flags=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    patch *= alpha
    reg = canvas[Y0:Y1, X0:X1]
    reg *= (1 - patch[..., 3:4]); reg += patch[..., :3] * 255

def background(st):
    yy, xx = np.mgrid[0:H, 0:W]
    bg = np.zeros((H, W, 3), np.float32) + np.array(st.bg, np.float32)
    if st.pattern == 'grid': m = ((xx - 30) % 65 < 2) | ((yy - 40) % 65 < 2)
    elif st.pattern == 'dots': m = (((xx - 30) % 65) < 4) & (((yy - 40) % 65) < 4)
    else: m = np.zeros((H, W), bool)
    bg[m] = st.grid
    if not st.light:
        vig = 1.3 * (1 - 0.5 * (((xx - W / 2) / W) ** 2 + ((yy - H / 2) / H) ** 2)); bg *= vig[..., None]
    return np.clip(bg, 0, 255)

def _roi(P, pad):
    x0 = max(0, int(math.floor(P[:, 0].min() - pad))); y0 = max(0, int(math.floor(P[:, 1].min() - pad)))
    x1 = min(W, int(math.ceil(P[:, 0].max() + pad)) + 1); y1 = min(H, int(math.ceil(P[:, 1].max() + pad)) + 1)
    return x0, y0, x1, y1

def _blend(canvas, roi, mask, color, alpha=1.0):
    x0, y0, x1, y1 = roi; a = mask[..., None] * alpha; reg = canvas[y0:y1, x0:x1]
    reg *= (1 - a); reg += a * np.array(color, np.float32)

# Everything below works on the smallest box around what it draws, never the whole frame: fast enough for 64
# rectangles or 40 circles a frame, and still drawn at 1/16 pixel precision so slow moves never step.
def poly(canvas, pts, color, width, glow=0.0, closed=False):
    """An anti-aliased line through float points, with an optional glow."""
    P = np.asarray(pts, np.float64).reshape(-1, 2)
    roi = _roi(P, width * 9 + 4 if glow > 0 else width + 3); x0, y0, x1, y1 = roi
    if x1 <= x0 or y1 <= y0: return
    p = np.round((P - (x0, y0)) * 16).astype(np.int32)
    if glow > 0:
        g = np.zeros((y1 - y0, x1 - x0, 3), np.float32); cv2.polylines(g, [p], closed, color, width * 3, cv2.LINE_AA, shift=4)
        canvas[y0:y1, x0:x1] += cv2.GaussianBlur(g, (0, 0), width * 2.2) * 0.55 * glow
    m = np.zeros((y1 - y0, x1 - x0), np.float32); cv2.polylines(m, [p], closed, 1.0, width, cv2.LINE_AA, shift=4)
    _blend(canvas, roi, m, color)

def fill_many(canvas, polys, color, alpha):
    """Several filled shapes as one layer: overlaps do not double up and it costs one blend."""
    if not len(polys) or alpha <= 0.002: return
    Ps = [np.asarray(q, np.float64).reshape(-1, 2) for q in polys]
    roi = _roi(np.concatenate(Ps), 2); x0, y0, x1, y1 = roi
    if x1 <= x0 or y1 <= y0: return
    m = np.zeros((y1 - y0, x1 - x0), np.float32)
    cv2.fillPoly(m, [np.round((P - (x0, y0)) * 16).astype(np.int32) for P in Ps], 1.0, cv2.LINE_AA, shift=4)
    _blend(canvas, roi, m, color, alpha)

def fill(canvas, pts, color, alpha): fill_many(canvas, [pts], color, alpha)

def outline_many(canvas, polys, color, width):
    Ps = [np.asarray(q, np.float64).reshape(-1, 2) for q in polys]
    if not Ps: return
    roi = _roi(np.concatenate(Ps), width + 3); x0, y0, x1, y1 = roi
    m = np.zeros((y1 - y0, x1 - x0), np.float32)
    cv2.polylines(m, [np.round((P - (x0, y0)) * 16).astype(np.int32) for P in Ps], True, 1.0, width, cv2.LINE_AA, shift=4)
    _blend(canvas, roi, m, color)

def circle(canvas, c, r, color, width):
    roi = _roi(np.array([[c[0], c[1]]]), r + abs(width) + 3); x0, y0, x1, y1 = roi
    if x1 <= x0 or y1 <= y0: return
    m = np.zeros((y1 - y0, x1 - x0), np.float32)
    cv2.circle(m, (int(round((c[0] - x0) * 16)), int(round((c[1] - y0) * 16))), int(round(r * 16)), 1.0, width, cv2.LINE_AA, shift=4)
    _blend(canvas, roi, m, color)

def shake_at(k, hits, st):
    """How hard the frame is shaking at beat k: each hit rings out smoothly, it does not jitter."""
    amp = 0.0; phase = 0.0
    for hb, a in hits.items():
        d = k - hb
        if 0 <= d < 1.5:
            e = a * st.shake * math.exp(-d * 4.0)
            if e > amp: amp, phase = e, d
    return amp, phase

def finish(canvas, k, sh_amp, sh_phase, zoom=1.0, cx=W / 2, cy=H / 2, st=None):
    """Bloom, then the camera: a zoom about (cx, cy) and a damped, smooth shake."""
    f = canvas
    if st is not None and not st.light:
        bright = cv2.resize(np.clip(f - 150, 0, 255), (W // 4, H // 4), interpolation=cv2.INTER_AREA)   # bloom at quarter size: same look, a tenth of the cost
        f = np.clip(f + cv2.resize(cv2.GaussianBlur(bright, (0, 0), 3.5), (W, H), interpolation=cv2.INTER_LINEAR) * 0.5 * st.glow, 0, 255)
    dx = dy = ang = 0.0
    if sh_amp > 0.01:
        tt = sh_phase                                          # beats since the hit
        dx = 26 * sh_amp * math.sin(2 * math.pi * 3.1 * tt); dy = 18 * sh_amp * math.sin(2 * math.pi * 2.3 * tt + 1.1)
        ang = 1.2 * sh_amp * math.sin(2 * math.pi * 1.7 * tt + 0.4)
    z = zoom * (1 + 0.05 * sh_amp)
    if abs(z - 1) > 1e-4 or sh_amp > 0.01:
        M = cv2.getRotationMatrix2D((cx, cy), ang, z); M[0, 2] += dx; M[1, 2] += dy
        f = cv2.warpAffine(f, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return f

CREDIT_AT = (40, 268)   # top left, just inside Instagram's safe area (y 250-1500): at y 1885 it sat under the caption, and
                        # every scene's bottom band (1300-1800) is full of its own type, so the credit lives in the top band

def overlay_fixed(f, st, k, beats, credit):
    """What stays still while the camera moves: the progress bar and the song credit."""
    f[0:8] = np.array(st.grid, np.float32); f[0:8, :int(W * min(1, k / beats))] = np.array(st.a, np.float32)
    sp = text(credit, F(DEJAVU, 28), st.muted); paste(f, sp, CREDIT_AT[0] + sp.shape[1] / (2 * SS), CREDIT_AT[1])
    return np.clip(f, 0, 255).astype(np.uint8)

LOOP_TAIL = 9   # frames: a looping scene's last 9 frames fade into frame 0 (as illusion, reveal and retro do), so the replay has no seam

def render(frame, clock, out, style=None):
    import polish                                                    # bloom, grain, vignette (studio/polish.py); races get their own look
    _look = 'race' if 'race' in os.path.basename(sys.argv[0]) else 'math'; _raw = frame
    _polished = lambda i: polish.look(_raw(i), _look, i)
    if getattr(clock, 'loop', False):
        first = []
        def frame(i):
            o = _polished(i); tail = clock.n - i
            if tail > LOOP_TAIL: return o
            if not first: first.append(_polished(0).astype(np.float32))
            a = (LOOP_TAIL + 1 - tail) / (LOOP_TAIL + 1)                     # 0.1 on the first of the nine, 0.9 on the last
            return (o.astype(np.float32) * (1 - a) + first[0] * a).astype(np.uint8)
    else: frame = _polished
    if '--frames' in sys.argv:
        fs = [min(int(x), clock.n - 1) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]   # past the end: the last frame
        ims = [Image.fromarray(frame(f)).resize((360, 640)) for f in fs]
        sheet = Image.new('RGB', (360 * min(4, len(ims)), 640 * ((len(ims) + 3) // 4)))
        for j, im in enumerate(ims): sheet.paste(im, ((j % 4) * 360, (j // 4) * 640))
        sheet.save(out); print('sheet', out, [round(clock.beat(f), 1) for f in fs], K.record()['knobs']); return
    tmp = out[:-4] + '.part.mp4'
    p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '18'),
                          '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    for i in range(clock.n):
        p.stdin.write(frame(i).tobytes())
        if i % 60 == 0: print(i, '/', clock.n, flush=True)
    p.stdin.close(); p.wait()
    aud = out[:-4] + '.m4a'; audio.audio_clip(clock.slug, clock.t0, clock.t1, aud)
    r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
    os.remove(tmp); os.remove(aud)
    if r.returncode: sys.exit('mux failed')
    json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])
