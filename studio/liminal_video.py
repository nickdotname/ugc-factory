#!/usr/bin/env python3
"""Liminal spaces for a stretch of a song: empty corridors that go on for ever, on a VHS tape.

    python studio/liminal_video.py studio/songs/<slug> <seed> out.mp4          (window from CQ_WINDOW="start,end")
    python studio/liminal_video.py studio/songs/<slug> <seed> out.png --frames 0,200

No footage: every frame is ray-cast from nothing. The seed picks the place (yellow back rooms, a tiled
pool hall, a dead mall, a hotel corridor at night), its light, the tape's date stamp and how far the
camera drifts. The corridor repeats, and the camera moves exactly a whole number of repeats in the
clip, so the last frame runs straight on into the first: the video loops with no seam. The lights
hum with the music and flicker on the hardest drum hits. A recipe .json is written beside the video.
"""
import sys, os, json, random, subprocess
import numpy as np, soundfile as sf, cv2
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hook as _hook
import cards as _cards

SONG_DIR = os.path.abspath(sys.argv[1]); seed = int(sys.argv[2]); out = sys.argv[3]
SONG = json.load(open(os.path.join(SONG_DIR, 'song.json')))
def _find(stem, exts): return next((os.path.join(SONG_DIR, stem + e) for e in exts if os.path.exists(os.path.join(SONG_DIR, stem + e))), os.path.join(SONG_DIR, stem + exts[0]))
MASTER = _find('master', ('.wav', '.flac', '.ogg')); stem_path = lambda name: _find(os.path.join('stems', name), ('.flac', '.ogg'))
T0, T1 = [float(x) for x in os.environ['CQ_WINDOW'].split(',')]
FPS, W, H = 30, 1080, 1920
w, h = 360, 640                      # tape resolution: drawn small and blown up, which is the look
N = max(1, int(round((T1 - T0) * FPS))); rng = random.Random(seed)
FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts')

# ---- what the music is doing ----------------------------------------------------------------
def env(name, smooth):
    p = stem_path(name)
    if not os.path.exists(p): return np.zeros(N)
    a, sr = sf.read(p, dtype='float32', always_2d=True); a = a.mean(1)[int(T0 * sr):int(T1 * sr)]; hop = sr / FPS
    e = np.array([np.sqrt(np.mean(a[int(i * hop):int((i + 1) * hop)] ** 2) + 1e-9) for i in range(N)])
    e = np.clip(e / (np.percentile(e, 98) + 1e-9), 0, 1.5); o = np.zeros(N); v = 0.0
    for i in range(N): v = e[i] if e[i] > v else v * smooth + e[i] * (1 - smooth); o[i] = v
    return o
DRUM, BASS, VOX = env('Drums', .6), env('Bass', .9), env('Vocals', .85)
hit = np.clip(np.diff(DRUM, prepend=0), 0, None); hit = hit / (hit.max() + 1e-9)

# ---- the place -------------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import knobs as K
PLACES = ['backrooms', 'backrooms', 'pool', 'mall', 'hotel', 'office', 'parking', 'school']
if os.environ.get('CQ_PLACE'): K.FORCED.setdefault('place', os.environ['CQ_PLACE'])
place = K.pick('place', PLACES, rng)
P = dict(backrooms=dict(width=3.2, height=2.6, period=4.0, fog=(.42, .38, .22), fogd=.11, gap=(1.2, 2.6)),
         pool=dict(width=4.4, height=3.2, period=3.0, fog=(.62, .78, .80), fogd=.08, gap=(0.9, 2.4)),
         mall=dict(width=6.0, height=4.2, period=6.0, fog=(.55, .50, .52), fogd=.06, gap=(1.0, 4.5)),
         hotel=dict(width=2.2, height=2.5, period=3.2, fog=(.10, .07, .05), fogd=.16, gap=(1.6, 2.4)),
         office=dict(width=2.6, height=2.7, period=3.6, fog=(.50, .52, .55), fogd=.10, gap=(1.4, 1.5)),
         parking=dict(width=7.0, height=2.4, period=5.0, fog=(.40, .30, .16), fogd=.08, gap=(1.0, 2.4)),
         school=dict(width=3.0, height=2.9, period=4.0, fog=(.55, .56, .50), fogd=.09, gap=(2.6, 2.3)))[place]
WID, HEI, PER = P['width'], P['height'], P['period']
pace = K.pick('pace', ['slow', 'walk', 'walk'], rng)
laps = max(1, round((T1 - T0) * {'backrooms': .45, 'pool': .5, 'mall': .3, 'hotel': .55, 'office': .45, 'parking': .35, 'school': .5}[place] * (.55 if pace == 'slow' else 1) / PER * 2))   # whole repeats per clip
SPEED = laps * PER / (N / FPS)
year = rng.randint(1994, 2003); month = rng.randint(1, 12); day = rng.randint(1, 28)
hour, minute = rng.choice([2, 3, 3, 4, 11, 1]), rng.randint(0, 59)
side_bias = rng.uniform(-.25, .25)          # camera a little off centre
look = rng.uniform(-.06, .06)               # and turned a little
warm = rng.uniform(-.04, .04)
tint = K.pick('tint', ['neutral', 'neutral', 'warm', 'cold', 'green'], rng)
warm += {'neutral': 0, 'warm': .07, 'cold': -.07, 'green': 0}[tint]
tape_wear = K.pick('tape', ['clean', 'worn', 'worn', 'chewed'], rng)
label = K.pick('label', ['PLAY ▶', 'PLAY ▶', 'REC ●', 'none'], rng)
stamp = K.pick('stamp', ['date', 'date', 'none'], rng)

# camera rays, made once
yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
fov = 1.15
dx = (xx - w / 2) / (w / 2) * np.tan(fov / 2) * (w / h); dy = -(yy - h / 2) / (h / 2) * np.tan(fov / 2); dz = np.ones_like(dx)
c, s = np.cos(look), np.sin(look); dx, dz = dx * c + dz * s, -dx * s + dz * c
n = np.sqrt(dx * dx + dy * dy + dz * dz); dx, dy, dz = dx / n, dy / n, dz / n
EYE = {'mall': 1.7, 'parking': 1.4}.get(place, 1.55)

def noise2(u, v, k):
    """cheap value noise that tiles with the corridor"""
    return (np.sin(u * 12.9898 * k + v * 78.233) * 43758.5453) % 1.0

def surfaces(cx, cz):
    """distance and hit point on each of floor, ceiling, left, right wall. -> t, kind, (u, v) texture coords"""
    big = np.float32(1e9)
    tf = np.where(dy < -1e-4, (0 - EYE) / np.minimum(dy, -1e-4), big)
    tc = np.where(dy > 1e-4, (HEI - EYE) / np.maximum(dy, 1e-4), big)
    tl = np.where(dx < -1e-4, (-WID / 2 - cx) / np.minimum(dx, -1e-4), big)
    tr = np.where(dx > 1e-4, (WID / 2 - cx) / np.maximum(dx, 1e-4), big)
    T = np.stack([tf, tc, tl, tr]); kind = T.argmin(0); t = T.min(0)
    px, py, pz = cx + dx * t, EYE + dy * t, cz + dz * t
    return t, kind, px, py, pz

def light_at(pz, flick):
    """fluorescent panels every PER along the ceiling centre; how lit a point at depth z is"""
    zr = (pz % PER) / PER
    d = np.minimum(zr, 1 - zr)                              # distance to nearest panel, in repeats
    k = np.floor(pz / PER + .5).astype(np.int64)
    f = flick[(k % len(flick))]
    return (0.55 + 0.45 * np.exp(-(d * PER) ** 2 / 2.2)) * f

def texture(kind, px, py, pz, T, flick):
    out = np.zeros(kind.shape + (3,), np.float32)
    fl, ce, wl = kind == 0, kind == 1, kind >= 2
    u_w = pz; v_w = py; u_f = px; v_f = pz
    zmod = pz % PER
    door = wl & (zmod > P['gap'][0]) & (zmod < P['gap'][0] + 1.0) & (py < P['gap'][1]) if place in ('backrooms', 'hotel', 'mall', 'school') else np.zeros_like(wl)
    if place == 'backrooms':
        wall = np.array([.80, .70, .38]); stripe = (np.sin(u_w * 40) > .6) * .05 + (np.sin(u_w * 6 + v_w * 3) > .95) * .03
        out[wl] = (wall * (1 - stripe[..., None]))[wl]
        carpet = np.array([.55, .48, .28]) * (0.85 + .15 * noise2(np.floor(u_f * 30), np.floor(v_f * 30), 1))[..., None]
        out[fl] = carpet[fl]
        tile = ((np.abs((px * 1.6) % 1 - .5) > .47) | (np.abs((pz * 1.6) % 1 - .5) > .47))
        ceil = np.where(tile[..., None], [.62, .60, .50], [.86, .84, .74])
        panel = (np.abs(px) < .45) & (np.abs(((pz % PER) / PER) - .5) > .42)
        ceil = np.where(panel[..., None], [1.6, 1.55, 1.3], ceil); out[ce] = ceil[ce]
        out[door] = [.05, .04, .02]
    elif place == 'pool':
        gl = ((np.abs((u_w * 6) % 1 - .5) > .45) | (np.abs((v_w * 6) % 1 - .5) > .45))
        out[wl] = np.where(gl[..., None], [.62, .70, .72], [.92, .96, .97])[wl]
        water = (px > -WID / 2 + .9) & (px < WID / 2 - .9)
        caust = (np.sin(px * 7 + T * 1.3) * np.sin(pz * 6 - T * 1.1) + np.sin((px + pz) * 9 + T * 2)) * .5
        flr = np.where(water[..., None], np.stack([.18 + .06 * caust, .52 + .10 * caust, .62 + .1 * caust], -1),
                       np.where(((np.abs((px * 5) % 1 - .5) > .45) | (np.abs((pz * 5) % 1 - .5) > .45))[..., None], [.6, .66, .66], [.9, .93, .93]))
        out[fl] = flr[fl]
        sky = (np.abs(px) < 1.1) & ((pz % PER) / PER > .25) & ((pz % PER) / PER < .75)
        out[ce] = np.where(sky[..., None], [1.5, 1.55, 1.55], [.80, .84, .84])[ce]
    elif place == 'mall':
        out[wl] = np.where(((py > 3.2) | (np.abs(zmod - 3) > 2.6))[..., None], [.86, .74, .74], [.90, .84, .80])[wl]
        shop = wl & (np.abs(zmod - 3.2) < 2.0) & (py < 3.0)
        grate = (np.sin(py * 60) > .3)
        out[shop] = np.where(grate[..., None], [.30, .30, .32], [.12, .12, .14])[shop]
        chk = ((np.floor(px * 1.2) + np.floor(pz * 1.2)) % 2 == 0)
        out[fl] = np.where(chk[..., None], [.86, .84, .82], [.42, .62, .60])[fl]
        out[ce] = np.where(((pz % PER) / PER > .3)[..., None] & (np.abs(px) < 2)[..., None], [1.45, 1.42, 1.35], [.78, .76, .74])[ce]
        door = np.zeros_like(wl)
    elif place == 'office':                                                # a cubicle aisle: fabric partitions, grey carpet, a ceiling grid
        part = py < 1.55
        fabric = np.array([.40, .47, .60]) * (.9 + .1 * noise2(np.floor(u_w * 40), np.floor(v_w * 40), 2))[..., None]
        trim = (np.abs(py - 1.55) < .04) | ((np.abs((pz % 1.8) - .9) < .03) & part)
        out[wl] = np.where(part[..., None], fabric, np.array([.80, .80, .76]))[wl]
        out[wl & trim] = [.30, .30, .32]
        out[fl] = (np.array([.40, .42, .46]) * (.85 + .15 * noise2(np.floor(px * 25), np.floor(pz * 25), 3))[..., None])[fl]
        tile = ((np.abs((px * 1.6) % 1 - .5) > .46) | (np.abs((pz * 1.6) % 1 - .5) > .46))
        ceil = np.where(tile[..., None], [.55, .55, .55], [.88, .88, .86])
        panel = (np.abs(px) < .5) & (np.abs(((pz % PER) / PER) - .5) > .40)
        out[ce] = np.where(panel[..., None], [1.7, 1.7, 1.6], ceil)[ce]
        door = np.zeros_like(wl)
    elif place == 'parking':                                               # an underground car park under sodium lights
        con = np.array([.55, .53, .50]) * (.85 + .15 * noise2(np.floor(u_w * 8), np.floor(v_w * 8), 4))[..., None]
        pillar = (np.abs(zmod - PER / 2) < .35)
        out[wl] = np.where(pillar[..., None], [.70, .68, .62], con)[wl]
        out[wl & (py < .9) & pillar] = [.85, .70, .10]                      # yellow and black at bumper height
        stripes = wl & (py < .9) & pillar & (np.sin((py + pz) * 14) > 0); out[stripes] = [.08, .08, .08]
        flr = np.array([.36, .35, .34]) * (.85 + .15 * noise2(np.floor(px * 6), np.floor(pz * 6), 5))[..., None]
        bay = (np.abs((pz % 2.6) - 1.3) < .05) & (np.abs(px) > 1.2); centre = (np.abs(px) < .06) & ((pz % 1.0) < .55)
        out[fl] = np.where((bay | centre)[..., None], [.92, .85, .35], flr)[fl]
        lamp = (np.abs(px) < .3) & (np.abs(((pz % PER) / PER) - .5) > .46)
        out[ce] = np.where(lamp[..., None], [2.0, 1.4, .6], np.array([.42, .41, .40]))[ce]
        door = np.zeros_like(wl)
    elif place == 'school':                                                # a school corridor lined with lockers
        lk = (py > .15) & (py < 1.95) & ~((zmod > P['gap'][0]) & (zmod < P['gap'][0] + 1.0))
        col = np.array([[.18, .32, .62], [.62, .14, .14]])[(np.floor(pz / 16) % 2).astype(int)]
        seam = (np.abs((pz * 2.6) % 1 - .5) > .46) | (np.abs(py - 1.0) < .02)
        vent = (np.abs(py - 1.75) < .08) & (np.sin(py * 140) > .2)
        out[wl] = np.where(lk[..., None], col * (1 - .55 * (seam | vent))[..., None], np.array([.86, .84, .76]))[wl]
        out[wl & (py < .15)] = [.25, .22, .2]
        chk = ((np.floor(px * 1.8) + np.floor(pz * 1.8)) % 2 == 0)
        out[fl] = np.where(chk[..., None], [.84, .82, .74], [.30, .40, .35])[fl]
        tile = ((np.abs((px * 1.6) % 1 - .5) > .46) | (np.abs((pz * 1.6) % 1 - .5) > .46))
        panel = (np.abs(px) < .45) & (np.abs(((pz % PER) / PER) - .5) > .42)
        out[ce] = np.where(panel[..., None], [1.6, 1.6, 1.5], np.where(tile[..., None], [.6, .6, .56], [.88, .87, .82]))[ce]
        out[door] = [.45, .30, .18]
        door = np.zeros_like(wl)
    else:  # hotel
        out[wl] = np.where((py < .9)[..., None], [.48, .36, .26], [.82, .74, .58])[wl]
        out[door] = [.30, .18, .10]
        plate = door & (np.abs(zmod - (P['gap'][0] + .5)) < .07) & (np.abs(py - 1.55) < .05)
        out[plate] = [.9, .75, .35]
        diam = (np.abs((px * 2.2) % 1 - .5) + np.abs((pz * 2.2) % 1 - .5)) < .32
        out[fl] = np.where(diam[..., None], [.62, .42, .12], [.42, .08, .10])[fl]
        out[ce] = [.70, .64, .54]
        sconce = wl & (np.abs(zmod - .4) < .12) & (np.abs(py - 1.9) < .1)
        out[sconce] = [2.0, 1.6, 1.0]
        door = np.zeros_like(wl)
    if place in ('backrooms', 'mall'): out[door] = [.04, .035, .03]
    return out

def frame(i):
    T = i / FPS; cz = SPEED * T; cx = side_bias + .06 * np.sin(2 * np.pi * i / N)
    flick = np.ones(16, np.float32)
    r = random.Random(seed * 1000 + i // 2)
    if hit[i] > .7 or r.random() < .03: flick[r.randrange(16)] = r.choice([.25, .5, .7])
    hum = 1 + .05 * BASS[i] + .04 * DRUM[i]
    t, kind, px, py, pz = surfaces(cx, cz)
    col = texture(kind, px, py, pz, T, flick) * light_at(pz, flick)[..., None] * hum
    fog = np.exp(-P['fogd'] * t)[..., None]
    col = col * fog + np.array(P['fog'], np.float32) * (1 - fog) * (.75 + .25 * hum)
    col *= 1 + np.array([warm, .05 if tint == 'green' else 0, -warm], np.float32)
    return np.clip(col, 0, 1.2)

# ---- the tape --------------------------------------------------------------------------------
MON = 'JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()
def _font(name, size):
    p = os.path.join(FONTS, name)
    try: return ImageFont.truetype(p, size)
    except OSError:
        for q in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
            if os.path.exists(q): return ImageFont.truetype(q, size)
        return ImageFont.load_default()
FMONO = _font('DejaVuSansMono-Bold.ttf', 58)
plan = dict(place=place, laps=laps, year=year, pace=pace, tint=tint, tape=tape_wear, label=label, stamp=stamp, hook='' if _cards.CARDS else _hook.pick('liminal', seed), lyrics=None)

def tape(rgb, i):
    a = (np.clip(rgb, 0, 1) ** (1 / 1.1) * 255).astype(np.uint8)
    a = cv2.resize(a, (W // 2, H // 2), interpolation=cv2.INTER_LINEAR)
    a = cv2.GaussianBlur(a, (0, 0), 1.1)
    b = a.astype(np.int16); sh, noise, roll = {'clean': (2, 4, .02), 'worn': (3, 7, .06), 'chewed': (5, 11, .16)}[tape_wear]
    b[:, sh:, 0] = a[:, :-sh, 0]; b[:, :-sh, 2] = a[:, sh:, 2]          # colour bleeding sideways
    r = np.random.default_rng(seed * 7 + i)
    b += r.normal(0, noise, b.shape[:2])[..., None].astype(np.int16)
    b[::2] = (b[::2] * .9).astype(np.int16)                               # scanlines
    if tape_wear == 'chewed' and r.random() < .05: b = np.roll(b, int(r.integers(-6, 7)), 0)   # the picture jumps
    if r.random() < roll:                                                 # a tracking line rolls through
        y0 = r.integers(0, b.shape[0] - 12); b[y0:y0 + 10] = np.roll(b[y0:y0 + 10], r.integers(8, 30), 1) + 25
    yv, xv = np.ogrid[:b.shape[0], :b.shape[1]]
    vig = 1 - .45 * (((xv - b.shape[1] / 2) / (b.shape[1] / 2)) ** 2 + ((yv - b.shape[0] / 2) / (b.shape[0] / 2)) ** 2) / 2
    b = (b * vig[..., None]).clip(0, 255).astype(np.uint8)
    a = cv2.resize(b, (W, H), interpolation=cv2.INTER_LINEAR)
    im = Image.fromarray(a); d = ImageDraw.Draw(im)
    secs = (i // FPS) % 60
    if label != 'none': d.text((70, 110), label, font=FMONO, fill=(240, 60, 50) if label.startswith('REC') and (i // 15) % 2 == 0 else (240, 240, 240))
    if stamp != 'none':
        d.text((70, H - 230), '%s %02d %d' % (MON[month - 1], day, year), font=FMONO, fill=(240, 240, 240))
        d.text((70, H - 160), '%s %d:%02d:%02d' % ('AM' if hour < 12 else 'PM', hour % 12 or 12, minute, secs), font=FMONO, fill=(240, 240, 240))
    a = np.asarray(im)
    if _cards.CARDS: return _cards.draw(np.ascontiguousarray(a), i / FPS)
    return _hook.draw(a, plan['hook'], i / FPS, y=0.43)

def finish(i): return tape(frame(i), i)

if len(sys.argv) > 5 and sys.argv[4] == '--frames':
    fs = [int(x) for x in sys.argv[5].split(',')]
    ims = [Image.fromarray(finish(f)).resize((W // 3, H // 3)) for f in fs]
    sheet = Image.new('RGB', (sum(im.width for im in ims), ims[0].height))
    for k, im in enumerate(ims): sheet.paste(im, (k * im.width, 0))
    sheet.save(out); print(out, plan); sys.exit(0)

# ---- encode ------------------------------------------------------------------------------------
wav = out + '.wav'
_sr = sf.info(MASTER).samplerate; _n = int(0.12 * _sr); _a = int(T0 * _sr)
_x, _ = sf.read(MASTER, start=_a, stop=int(T1 * _sr), always_2d=True, dtype='float32')
_pre, _ = sf.read(MASTER, start=max(0, _a - _n), stop=_a, always_2d=True, dtype='float32')
if len(_pre) == _n:                                    # the end fades into the sound just before the start, so the loop has no seam
    _r = np.linspace(0, 1, _n)[:, None]; _x[-_n:] = _x[-_n:] * (1 - _r) + _pre * _r
sf.write(wav, _x * min(1.0, 0.98 / (np.abs(_x).max() + 1e-9)), _sr)
tmp = out + '.part.mp4'
p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                      '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'medium'),
                      '-crf', os.environ.get('CQ_CRF', '23'), '-maxrate', os.environ.get('CQ_MAXRATE', '6M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '12M'),
                      '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
for i in range(N): p.stdin.write(np.ascontiguousarray(finish(i)).tobytes())
p.stdin.close(); p.wait(); os.remove(wav)
if p.returncode: sys.exit('ffmpeg failed')
os.replace(tmp, out)
json.dump(dict(seed=seed, window=[T0, T1], song=os.path.basename(SONG_DIR), style='liminal', plan=plan, **K.record()), open(os.path.splitext(out)[0] + '.json', 'w'), indent=1)
print(out)
