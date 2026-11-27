#!/usr/bin/env python3
"""Lo-fi cut-out lyric videos for close__quarters, from the band's own dance footage.

    python studio/lofi_video.py SONG_DIR SEED OUT.mp4            (CQ_WINDOW="t0,t1": the stretch to play)
    python studio/lofi_video.py SONG_DIR SEED SHEET.png --frames 0,60,120

The band filmed themselves dancing to the songs on their phones. Each clip's place in the song was found by
landmark fingerprints of the music playing quietly behind them (studio/lofi_lib.py), and the people were cut out of
every tenth of a second with a person-segmentation model; studio/lofi/index.json lists the clips and the
lofi-library release holds the cut-outs. Here they are dropped onto flat colour, a melting rainbow or a split screen
inside a Y2K media-player window on the EDUCATION desktop, held three frames each so they move like stop-motion,
with the line underneath as karaoke and the word at the end of each phrase in WordArt bursting over the window. Now
and then one of them climbs out of the window frame.

Knobs (studio/knobs.py), so the learner finds out what gets watched: chrome (the window style), wall (the desktop),
theme (its colours), pop (how often someone climbs out), tint (how often the cut-out is recoloured), pace (a new
scene every bar or every two). If the stretch asked for is not covered by footage the renderer moves it to the
nearest one that is, keeping its length. A `short` cut from nightly (6-9 s, CQ_LOOP=1, CQ_LYRICS=none: the footage
carries without words) loops: its last 9 frames fade into frame 0.
"""
import io, json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import knobs as K
import lofi_lib as LIB

W, H, FPS = 1080, 1920, 30
PW, PH = 480, 360                               # the picture inside the player, drawn small and blown up 2x
WX0, WY0 = 40, 400                              # the player window
PX0, PY0 = WX0 + 20, WY0 + 60
WX1, WY1 = WX0 + 1000, PY0 + PH * 2 + 84


def _font(*names):
    roots = ['/usr/share/fonts', os.path.join(REPO, 'fonts')]
    for name in names:
        for root in roots:
            for base, _, files in os.walk(root):
                if name in files: return os.path.join(base, name)
    sys.exit('no usable font found; looked for ' + ', '.join(names))
SANS_B = _font('LiberationSans-Bold.ttf', 'DejaVuSans-Bold.ttf')
SANS = _font('LiberationSans-Regular.ttf', 'DejaVuSans.ttf')
INTER_XB = _font('Inter-ExtraBold.otf', 'Montserrat-ExtraBold.ttf')
INTER_SB = _font('Inter-SemiBold.otf', 'Montserrat-ExtraBold.ttf')
WORDART = _font('Fraunces.ttf', 'Anton-Regular.ttf')
_F = {}
def F(path, size):
    if (path, size) not in _F:
        f = ImageFont.truetype(path, size)
        if path == WORDART:
            try: f.set_variation_by_axes([72, 900, 100, 1])       # Fraunces: optical size, black, fully soft, wonky
            except Exception: pass
        _F[(path, size)] = f
    return _F[(path, size)]

# ------------------------------------------------------------------ the song and its footage
SONG_DIR = sys.argv[1] if len(sys.argv) > 1 else ''
SLUG = os.path.basename(os.path.normpath(SONG_DIR))
SONG = json.load(open(os.path.join(SONG_DIR, 'song.json'))) if SONG_DIR else {}
BEATS = np.array(SONG.get('beat_times') or [0.0])
MASTER = next((os.path.join(SONG_DIR, 'master' + e) for e in ('.ogg', '.flac', '.wav') if os.path.exists(os.path.join(SONG_DIR, 'master' + e))), '')
_OWN = os.path.join(HERE, 'lofi', 'lines', SLUG + '.json')      # lyrics aligned just for the footage's stretch (studio/lofi/lines/)
_LP = _OWN if os.path.exists(_OWN) else os.path.join(SONG_DIR, 'lines.json')
import sync_check                                   # lines whose sync is not proven come whole, never word by word
LINES = [[e, [list(x) for x in ws]] for e, ws in sync_check.load_lines(SONG_DIR, _OWN if _LP == _OWN else None)] if SONG_DIR and os.path.exists(_LP) else []
SHOW_LYRICS = os.environ.get('CQ_LYRICS') != 'none' and bool(LINES)     # nightly says none where the words do not measure as in sync (own lines too)
CLIPS = {}                                       # who -> [(clip id, song time of frame 1, frames)], filled in main()

def _dur(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True).stdout
    try: return float(out)
    except ValueError: return 240.0

_cache = {}
def person(who, T):
    """The RGBA cut-out of `who` at song time T (10 per second), or None where none of their clips reach."""
    for cid, off, n, fps in CLIPS.get(who, ()):
        if off <= T <= off + (n - 0.5) / fps:
            k = int(np.clip(math.floor((T - off) * fps), 0, n - 1)) + 1
            key = (cid, k)
            if key not in _cache:
                try: p = LIB.frame(cid, k)
                except Exception as exc: print('no cut-outs for %s: %r' % (cid, exc)); return None
                if p is None: return None
                _cache[key] = p
                if len(_cache) > 80: _cache.pop(next(iter(_cache)))
            return _cache[key]
    return None

def has(who, T): return person(who, T) is not None
def present(T): return [w for w in sorted(CLIPS) if has(w, T)]

# ------------------------------------------------------------------ backgrounds
FLATS = [(74, 12, 208), (226, 40, 150), (20, 150, 230), (120, 30, 220), (255, 110, 40), (40, 200, 120)]
SPLITS = [((228, 38, 140), (74, 14, 212)), ((20, 150, 230), (255, 110, 40)), ((40, 200, 120), (120, 30, 220))]
THEMES = {'purple': dict(base=(24, 6, 48), acc=(120, 40, 200), icon=(255, 90, 200)), 'teal': dict(base=(0, 40, 80), acc=(0, 140, 170), icon=(80, 230, 200)),
          'mono': dict(base=(10, 10, 14), acc=(70, 70, 90), icon=(255, 220, 60)), 'wine': dict(base=(70, 0, 40), acc=(200, 40, 110), icon=(255, 200, 80))}

def flat_bg(col, t, salt):
    """A flat saturated colour with the faint blocky shimmer of a low-bitrate video."""
    g = np.random.default_rng(int(t * 8) + salt).normal(0, 1, (PH // 24 + 1, PW // 24 + 1)).astype(np.float32)
    g = cv2.resize(g, (PW, PH), interpolation=cv2.INTER_NEAREST)
    return np.clip(np.array(col, np.float32)[None, None] * (1 + 0.022 * g[..., None]), 0, 255)

def rainbow_bg(t, seed):
    """A melting thermal-camera rainbow: rings and rays out of a bright point near the top, in big soft pixels."""
    gx, gy = 48, 36
    y, x = np.mgrid[0:gy, 0:gx].astype(np.float32)
    cx, cy = gx * (0.5 + 0.1 * math.sin(t * 0.6 + seed)), gy * (0.15 + 0.05 * math.sin(t * 0.4))
    d = np.sqrt((x - cx) ** 2 + ((y - cy) * 1.25) ** 2) / gx; a = np.arctan2(y - cy, x - cx)
    v = (d * 2.4 - t * 0.35 + 0.11 * np.sin(a * 7 + t * 0.8 + seed) + 0.06 * np.sin(x * 0.5 + y * 0.4 - t * 2)) % 1.0
    hue = (0.15 - v * 0.95) % 1.0; glow = np.exp(-(d / 0.12) ** 2)
    hsv = np.stack([hue * 179, 215 - 150 * glow, np.full_like(v, 245) - 35 * d], -1).clip(0, 255).astype(np.uint8)
    rgb = cv2.resize(cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB), (PW, PH), interpolation=cv2.INTER_NEAREST)
    return cv2.GaussianBlur(rgb, (0, 0), 2.0).astype(np.float32)

def split_bg(cols, t):
    """Two halves of colour with a marching zig-zag between them."""
    a, b = (np.array(c, np.float32) for c in cols)
    yy, xx = np.mgrid[0:PH, 0:PW].astype(np.float32)
    edge = PW / 2 + 14 * np.abs(((yy + t * 60) / 28) % 2 - 1) - 7
    return np.where((xx < edge)[..., None], a, b)

_yy, _xx = np.mgrid[0:240, 0:135].astype(np.float32)
_ST = np.random.default_rng(5).random((90, 3))
def wallpaper(kind, T, th):
    beat = np.searchsorted(BEATS, T); ph = (T - BEATS[max(0, beat - 1)]) / 0.5; d = math.exp(-ph * 4)
    if kind == 'plasma':
        v = np.sin(_xx * .09 + T * .8) + np.sin(_yy * .06 - T * .6) + np.sin((_xx + _yy) * .05 + T * .4) + np.sin(np.hypot(_xx - 67, _yy - 120) * .08 - T)
        v = np.floor((v + 4) / 8 * 6) / 5
    elif kind == 'tiles': v = (((_xx + T * 6) // 12 + (_yy + T * 4) // 12) % 2) * .45 + .1 + d * .3
    elif kind == 'rings': v = (((np.hypot(_xx - 67, _yy - 120) * .1 - T * 1.0) % 1) < .5) * .55 + .1
    elif kind == 'grad': v = np.floor((_yy / 240 + .08 * np.sin(_xx * .08 + T * 1.2) + .05 * d) * 9) / 9
    else:
        v = np.zeros((240, 135), np.float32); z = (_ST[:, 2] - T * .22) % 1 + .04
        px = (67 + (_ST[:, 0] * 2 - 1) / z * 30).astype(int); py = (120 + (_ST[:, 1] * 2 - 1) / z * 55).astype(int); ok = (px >= 0) & (px < 135) & (py >= 0) & (py < 240)
        v[py[ok], px[ok]] = np.clip(1.2 - z[ok], .3, 1)
    v = np.clip(v, 0, 1)[..., None]; img = np.array(th['base'], np.float32) * (1 - v) + np.array(th['acc'], np.float32) * v
    return cv2.resize(img.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)

# ------------------------------------------------------------------ cut-outs
def duotone(im, lo, mid, hi):
    a = np.asarray(im).astype(np.float32); l = (0.3 * a[..., 0] + 0.59 * a[..., 1] + 0.11 * a[..., 2]) / 255
    l = np.clip((l - 0.08) * 1.35, 0, 1)[..., None]
    lo, mid, hi = (np.array(c, np.float32) for c in (lo, mid, hi))
    rgb = np.where(l < 0.5, lo + (mid - lo) * (l / 0.5), mid + (hi - mid) * ((l - 0.5) / 0.5))
    return Image.fromarray(np.concatenate([rgb, a[..., 3:4]], -1).astype(np.uint8), 'RGBA')
TONES = [((40, 0, 95), (200, 40, 210), (255, 185, 250)), ((0, 30, 80), (0, 170, 200), (200, 255, 250))]

def paste(canvas, im, cx, base_y, height):
    s = height / im.height; im2 = im.resize((max(1, int(im.width * s)), max(1, int(height))), Image.BILINEAR)
    canvas.alpha_composite(im2, (int(cx - im2.width / 2), int(base_y - im2.height)))

# ------------------------------------------------------------------ WordArt
WA = [dict(fill=[(0, (225, 255, 248)), (0.42, (95, 215, 196)), (0.5, (25, 95, 120)), (0.78, (120, 230, 210)), (1, (230, 255, 250))], line=(14, 28, 70), deep=(20, 70, 95)),
      dict(fill=[(0, (255, 250, 200)), (0.45, (255, 190, 40)), (0.52, (170, 70, 10)), (0.8, (255, 210, 90)), (1, (255, 250, 220))], line=(70, 20, 10), deep=(120, 40, 10)),
      dict(fill=[(0, (255, 225, 250)), (0.45, (255, 90, 200)), (0.52, (120, 10, 110)), (0.8, (255, 140, 230)), (1, (255, 235, 252))], line=(40, 0, 50), deep=(90, 0, 80))]

def wordart(word, size, pal):
    """90s WordArt: a chrome gradient fill, a dark outline and a stepped 3D extrusion."""
    f = F(WORDART, size); bb = f.getbbox(word); w, h = bb[2] - bb[0] + 40, bb[3] - bb[1] + 40
    m = Image.new('L', (w, h), 0); ImageDraw.Draw(m).text((20 - bb[0], 20 - bb[1]), word, font=f, fill=255)
    M = np.asarray(m).astype(np.float32) / 255; out = np.zeros((h, w, 4), np.float32); deep = np.array(pal['deep'], np.float32)
    for k in range(6, 0, -1):
        sh = np.roll(np.roll(M, k, 0), k // 2, 1)
        out[..., :3] = np.where(sh[..., None] > 0.5, deep * (0.7 + 0.05 * k), out[..., :3]); out[..., 3] = np.maximum(out[..., 3], sh)
    ol = cv2.dilate(M, np.ones((5, 5), np.uint8))
    out[..., :3] = np.where(ol[..., None] > 0.3, np.array(pal['line'], np.float32), out[..., :3]); out[..., 3] = np.maximum(out[..., 3], ol)
    yy = np.linspace(0, 1, h)[:, None]; grad = np.zeros((h, 1, 3), np.float32)
    for (p0, c0), (p1, c1) in zip(pal['fill'], pal['fill'][1:]):
        sel = (yy >= p0) & (yy <= p1); u = (yy - p0) / max(1e-6, p1 - p0)
        grad = np.where(sel[..., None], np.array(c0, np.float32) + (np.array(c1, np.float32) - np.array(c0, np.float32)) * u[..., None], grad)
    out[..., :3] = out[..., :3] * (1 - M[..., None]) + grad * M[..., None]; out[..., 3] *= 255
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), 'RGBA').filter(ImageFilter.GaussianBlur(0.6))

# The word that ends each phrase (a comma or full stop), and a few strong line-enders, shown as WordArt.
STOP = {'fuck', 'fucking', 'fucks', 'bitch', 'bitches', 'pussy', 'shit', 'ass', 'like', 'that', 'it', "it's", 'its', 'the', 'a', 'my',
        'me', 'to', 'in', 'on', 'i', "i'm", "don't", 'they', 'be', 'and', 'with', 'you', "you're"}
WEAK = {'should', 'would', 'could', 'about', 'there', 'their', 'where', 'something', 'making', 'longer', 'because', 'through'}
RHYMES, _last = {}, -9.0
for _e, _ws in LINES:
    for _k, (_w, _t) in enumerate(_ws):
        _c = _w.strip(',.?!').lower()
        if _c in STOP or len(_c) < 3: continue
        if (_w[-1] in ',.?!' or (_k == len(_ws) - 1 and len(_c) >= 6 and _c not in WEAK)) and _t - _last > 0.9: RHYMES[_t] = _w; _last = _t
LINE_SPAN = []
for _i, (_e, _ws) in enumerate(LINES):
    _n = LINES[_i + 1][1][0][1] if _i + 1 < len(LINES) else _e + 1
    LINE_SPAN.append((_ws[0][1], min(_n, _e + 0.6), _i))

def karaoke(d, T):
    ln = next((l for l in LINE_SPAN if l[0] - 0.05 <= T < l[1]), None)
    if not ln: return
    ws = LINES[ln[2]][1]; f = F(INTER_XB, 60); y = WY1 + 36; rows, cur = [], []
    for w, t in ws:
        if cur and d.textlength(' '.join(x for x, _ in cur + [(w, t)]), font=f) > W - 120: rows.append(cur); cur = []
        cur.append((w, t))
    rows.append(cur)
    for r, row in enumerate(rows[:2]):
        x = (W - d.textlength(' '.join(w for w, _ in row), font=f)) / 2
        for w, t in row:
            d.text((x, y + r * 76), w, font=f, fill=(255, 230, 60) if t <= T + 0.03 else (255, 255, 255), stroke_width=5, stroke_fill=(0, 0, 0))
            x += d.textlength(w + ' ', font=f)

def burst(im, word, age, salt):
    """A WordArt word bursting out over the window's lower edge."""
    word = word.strip(',.?!').lower(); r = random.Random(salt); pop = 1 + 0.45 * math.exp(-age * 12)
    size = int(min(230, (W * 0.8) / max(1.6, len(word) * 0.52)) * pop)
    art = wordart(word, size, r.choice(WA)).rotate(r.uniform(-9, 9), expand=True, resample=Image.BICUBIC)
    im.alpha_composite(art, (int(W / 2 - art.width / 2 + r.uniform(-60, 60)), int(PY0 + PH * 2 - art.height * 0.55)))

# ------------------------------------------------------------------ the desktop and the player
def chrome_win(d, x0, y0, x1, y1, title, style):
    if style == 'mac':
        d.rectangle([x0, y0, x1, y1], fill=(221, 221, 221), outline=(0, 0, 0), width=3)
        d.rectangle([x0 + 3, y0 + 3, x1 - 3, y0 + 48], fill=(204, 204, 204)); d.line([x0, y0 + 50, x1, y0 + 50], fill=(0, 0, 0), width=3)
        f = F(SANS_B, 28); tw = d.textlength(title, font=f); cx = (x0 + x1) / 2
        for yy in range(y0 + 12, y0 + 42, 5):
            d.line([x0 + 60, yy, cx - tw / 2 - 16, yy], fill=(120, 120, 120), width=2); d.line([cx + tw / 2 + 16, yy, x1 - 14, yy], fill=(120, 120, 120), width=2)
        d.rectangle([x0 + 16, y0 + 12, x0 + 44, y0 + 40], fill=(221, 221, 221), outline=(0, 0, 0), width=2)
        d.text((cx - tw / 2, y0 + 10), title, font=f, fill=(0, 0, 0)); return
    d.rectangle([x0, y0, x1, y1], fill=(192, 192, 192))
    d.line([x0, y0, x1, y0], fill=(255, 255, 255), width=3); d.line([x0, y0, x0, y1], fill=(255, 255, 255), width=3)
    d.line([x0, y1, x1, y1], fill=(64, 64, 64), width=3); d.line([x1, y0, x1, y1], fill=(64, 64, 64), width=3)
    for k in range(46):                                          # the Win98 title-bar gradient
        c = tuple(int(a + (b - a) * k / 45) for a, b in zip((0, 0, 128), (16, 132, 208)))
        d.rectangle([x0 + 6 + (x1 - x0 - 12) * k / 46, y0 + 6, x0 + 6 + (x1 - x0 - 12) * (k + 1) / 46, y0 + 52], fill=c)
    d.text((x0 + 18, y0 + 12), title, font=F(SANS_B, 30), fill=(255, 255, 255))
    for j, bx in enumerate((x1 - 50, x1 - 90, x1 - 126)):
        d.rectangle([bx, y0 + 12, bx + 34, y0 + 46], fill=(192, 192, 192), outline=(0, 0, 0))
        if j == 0: d.line([bx + 9, y0 + 20, bx + 25, y0 + 38], fill=(0, 0, 0), width=3); d.line([bx + 25, y0 + 20, bx + 9, y0 + 38], fill=(0, 0, 0), width=3)

def desktop(T, st):
    th = THEMES[st['theme']]; im = Image.fromarray(wallpaper(st['wall'], T, th)); d = ImageDraw.Draw(im)
    top = 70 if st['chrome'] == 'mac' else 20
    for q, nm in enumerate(['EDUCATION.cd', 'lessons.txt', 'Recycle Bin']):
        x = 60 + q * 230; d.rectangle([x + 40, top + 16, x + 110, top + 80], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
        d.rectangle([x + 52, top + 28, x + 98, top + 48], fill=th['icon']); fw = d.textlength(nm, font=F(SANS, 26))
        d.text((x + 75 - fw / 2, top + 88), nm, font=F(SANS, 26), fill=(255, 255, 255))
    # under Instagram's top 250 px, whatever the chrome (with the mac menu bar it used to start at 210)
    d.text((54, 262), SONG.get('album', 'EDUCATION'), font=F(INTER_XB, 70), fill=(255, 255, 255))
    d.text((56, 344), 'lesson %d of %d: %s' % (SONG.get('track', 1), SONG.get('tracks_total', 15), SONG.get('title', SLUG)), font=F(INTER_SB, 38), fill=(225, 240, 255))
    name = SLUG.replace('-', '_')
    chrome_win(d, WX0, WY0, WX1, WY1, (name + '.avi - Media Player') if st['chrome'] != 'mac' else (name + '.mov'), st['chrome'])
    by = PY0 + PH * 2 + 14                                       # the transport: play, a seek bar that moves, the time
    d.rectangle([PX0, by, PX0 + 56, by + 52], fill=(192, 192, 192), outline=(0, 0, 0), width=2)
    d.polygon([(PX0 + 20, by + 12), (PX0 + 20, by + 40), (PX0 + 42, by + 26)], fill=(0, 0, 0))
    sx0, sx1 = PX0 + 76, WX1 - 190; kx = sx0 + (sx1 - sx0) * min(1.0, T / st['length'])
    d.rectangle([sx0, by + 20, sx1, by + 32], fill=(255, 255, 255), outline=(64, 64, 64), width=2)
    d.rectangle([kx - 9, by + 8, kx + 9, by + 44], fill=(192, 192, 192), outline=(0, 0, 0), width=2)
    d.text((WX1 - 172, by + 12), '%d:%02d / %d:%02d' % (int(T) // 60, int(T) % 60, int(st['length']) // 60, int(st['length']) % 60), font=F(SANS_B, 26), fill=(0, 0, 0))
    if st['chrome'] == 'mac':
        d.rectangle([0, 0, W, 58], fill=(238, 238, 238)); d.line([0, 58, W, 58], fill=(0, 0, 0), width=3); x = 30
        for item in ('✱', 'File', 'Edit', 'View', 'Special'):
            d.text((x, 12), item, font=F(SANS_B, 30), fill=(0, 0, 0)); x += d.textlength(item, font=F(SANS_B, 30)) + 36
        d.text((W - 170, 12), '4:19 PM', font=F(SANS, 30), fill=(0, 0, 0))
    else:
        d.rectangle([0, H - 84, W, H], fill=(192, 192, 192)); d.line([0, H - 84, W, H - 84], fill=(255, 255, 255), width=3)
        d.rectangle([10, H - 72, 190, H - 14], fill=(192, 192, 192), outline=(0, 0, 0), width=2); d.text((40, H - 62), 'Start', font=F(SANS_B, 32), fill=(0, 0, 0))
        d.rectangle([W - 220, H - 72, W - 12, H - 14], fill=(192, 192, 192), outline=(64, 64, 64), width=2); d.text((W - 190, H - 60), '4:19 PM', font=F(SANS, 30), fill=(0, 0, 0))
    return im

def picture(T, t, sc):
    kind = sc['kind']
    bg = rainbow_bg(t, sc['seed']) if kind == 'rainbow' else split_bg(sc['split'], t) if kind == 'split' else flat_bg(sc['col'], t, int(sc['seed'] * 100))
    pic = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8)).convert('RGBA')
    beat = np.searchsorted(BEATS, T); ph = (T - BEATS[max(0, beat - 1)]) / 0.5; bounce = 1 + 0.03 * math.exp(-ph * 5)
    if kind == 'split':
        for who, x in zip(present(T)[:2], (0.27, 0.73)): paste(pic, person(who, T), PW * x, PH * 1.04, PH * 0.95 * bounce)
    elif kind != 'pop':
        p = person(sc['who'], T)
        if p is not None: paste(pic, duotone(p, *sc['tone']) if sc['duo'] else p, PW * sc['x'], PH * 1.04, PH * 0.98 * bounce)
    small = pic.convert('RGB'); buf = io.BytesIO(); small.save(buf, 'JPEG', quality=40)   # the blocks of a low-bitrate upload
    return Image.open(buf).convert('RGB').resize((PW * 2, PH * 2), Image.BILINEAR)

def popout(im, T, sc):
    """One of the band climbing out of the player, over the window frame, as blocky as the picture."""
    p = person(sc['who'], T)
    if p is None: return
    p = duotone(p, *sc['tone']) if sc['duo'] else p
    bb = p.getchannel('A').point(lambda v: 255 if v > 60 else 0).getbbox()
    if not bb: return
    p = p.crop((0, bb[1], p.width, p.height)); h = PH * 2 * 1.12; s = h / p.height
    p = p.resize((int(p.width * s / 2), int(h / 2)), Image.BILINEAR).resize((int(p.width * s), int(h)), Image.NEAREST)
    a = np.asarray(p).copy(); y0 = int(PY0 + PH * 2 - h + 6); x0 = int(PX0 + PW * 2 * sc['x'] - p.width / 2)
    a[int(PY0 + PH * 2 - y0):, :, 3] = 0
    im.alpha_composite(Image.fromarray(a, 'RGBA'), (x0, y0))

# ------------------------------------------------------------------ the plan
def bars(T0, T1, every):
    downs = [b for i, b in enumerate(BEATS) if i % 4 == 0]
    return [b for j, b in enumerate(downs) if j % every == 0 and T0 + 0.5 < b < T1 - 0.3]

def plan(T0, T1, seed, st):
    r = random.Random(seed * 7 + 1); cuts = [T0] + bars(T0, T1, st['pace']) + [T1]; scenes, last = [], None
    for a, b in zip(cuts, cuts[1:]):
        here = present((a + b) / 2); opts = ['flat', 'flat', 'rainbow'] + (['pop'] if st['pop'] > 0 else []) + (['split', 'split'] if len(here) >= 2 else [])
        kind = r.choice([o for o in opts if o != last] or opts)
        if len(here) >= 2 and 'split' not in [s['kind'] for s in scenes]: kind = 'split'
        pops = [s['kind'] for s in scenes].count('pop')
        if kind == 'pop' and ('pop' in [s['kind'] for s in scenes[-3:]] or pops >= st['pop'] or r.random() > 0.7):
            kind = r.choice([o for o in ('flat', 'rainbow') if o != last] or ['flat'])
        last = kind
        scenes.append(dict(t0=a, t1=b, kind=kind, who=r.choice(here or sorted(CLIPS)), col=r.choice(FLATS), duo=r.random() < st['tint'],
                           seed=r.random() * 10, x=r.uniform(0.35, 0.65), split=r.choice(SPLITS), tone=r.choice(TONES)))
    return scenes

def loop_wanted(T0, T1):
    """Whether this cut replays as a loop: nightly says so on a `short` cut (CQ_LOOP=1); by hand, any cut under 10 s does."""
    return os.environ.get('CQ_LOOP', '1' if T1 - T0 < 10 else '0') == '1'

LOOP_TAIL = 9
def looped(draw, n, loop):
    """draw(i), with the last 9 of n frames faded into frame 0 when `loop` (as illusion_video.py does): no seam on the replay."""
    first = []
    def frame(i):
        o = draw(i); tail = n - i
        if not loop or tail > LOOP_TAIL: return o
        if not first: first.append(draw(0).astype(np.float32))
        a = (LOOP_TAIL + 1 - tail) / (LOOP_TAIL + 1)                     # 0.1 on the first of the nine, 0.9 on the last
        return (o.astype(np.float32) * (1 - a) + first[0] * a).astype(np.uint8)
    return frame

def fit_window(T0, T1, seed):
    """The stretch to play: the one asked for if footage covers it, else the nearest covered one of the same length."""
    L = T1 - T0
    def cover(a, b): ts = np.arange(a, b, 0.25); return float(np.mean([bool(present(t)) for t in ts])) if len(ts) else 0.0
    if cover(T0, T1) >= 0.9: return T0, T1
    runs, t, start = [], 0.0, None
    end = max(off + n / fps for v in CLIPS.values() for _, off, n, fps in v)
    while t <= end + 0.25:
        on = bool(present(t))
        if on and start is None: start = t
        if not on and start is not None: runs.append((start, t)); start = None
        t += 0.25
    runs = [(a, b) for a, b in runs if b - a >= 6]
    if not runs: sys.exit('no footage for %s' % SLUG)
    a, b = min(runs, key=lambda r_: abs((r_[0] + r_[1]) / 2 - (T0 + T1) / 2))
    L = min(L, b - a - 0.2); downs = [x for i, x in enumerate(BEATS) if i % 4 == 0 and a <= x <= b - L]
    s = min(downs, key=lambda x: abs(x - T0)) if downs else a + 0.1     # as near the asked-for start as the footage allows
    return s, s + L

def frame(i, T0, st, scenes):
    T = T0 + i / FPS; t = i / FPS
    sc = next((s for s in scenes if s['t0'] <= T < s['t1']), scenes[-1])
    im = desktop(T, st).convert('RGBA'); im.paste(picture(T, t, sc), (PX0, PY0))
    if sc['kind'] == 'pop': popout(im, T, sc)
    if SHOW_LYRICS:
        hit = [(t0, w) for t0, w in RHYMES.items() if t0 <= T < t0 + 0.75]
        if hit and hit[-1][1].strip(',.?!').lower() not in STOP: burst(im, hit[-1][1], T - hit[-1][0], int(hit[-1][0] * 100))
        karaoke(ImageDraw.Draw(im), T)
    elif t < 1.6:                                                # no checked lyrics: the song's name, once, at the start
        burst(im, SONG.get('title', SLUG), t, 7)
    return np.asarray(im.convert('RGB'))

def main():
    seed, out = int(sys.argv[2]), sys.argv[3]
    for c in LIB.clips_for(SLUG):
        CLIPS.setdefault(c['who'], []).append((c['id'], c['offset'], c['frames'], c['fps']))
    if not CLIPS: sys.exit('no footage for %s in studio/lofi/index.json' % SLUG)
    w = os.environ.get('CQ_WINDOW'); T0, T1 = (float(x) for x in w.split(',')) if w else (CLIPS[sorted(CLIPS)[0]][0][1] + 1, CLIPS[sorted(CLIPS)[0]][0][1] + 21)
    T0, T1 = fit_window(T0, T1, seed)
    r = random.Random(seed)
    st = dict(chrome=K.pick('chrome', ['win95', 'mac'], r), wall=K.pick('wall', ['plasma', 'rings', 'grad', 'stars', 'tiles'], r),
              theme=K.pick('theme', sorted(THEMES), r), pop=int(K.pick('pop', [0, 1, 3], r, weights=[1, 2, 2])),
              tint=float(K.pick('tint', [0.0, 0.4], r)), pace=int(K.pick('pace', [1, 2], r, weights=[3, 1])), length=_dur(MASTER))
    scenes = plan(T0, T1, seed, st)
    n = int((T1 - T0) * FPS); draw = looped(lambda i: frame(i, T0, st, scenes), n, loop_wanted(T0, T1))
    if '--frames' in sys.argv:
        fs = [min(int(x), n - 1) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
        ims = [Image.fromarray(draw(f)).resize((360, 640)) for f in fs]
        sheet = Image.new('RGB', (360 * len(ims), 640))
        for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
        sheet.save(out); print('sheet', out, round(T0, 2), round(T1, 2), K.record()['knobs'], [s['kind'] for s in scenes]); return
    tmp = out[:-4] + '.part.mp4'
    p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                          '-ss', '%.3f' % T0, '-t', '%.3f' % (T1 - T0), '-i', MASTER,
                          '-af', 'afade=t=in:d=0.04,afade=t=out:st=%.2f:d=0.5' % max(0, T1 - T0 - 0.5),
                          '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                          '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'),
                          '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(draw(i).tobytes())
        if i % 90 == 0: print(i, '/', n, flush=True)
    p.stdin.close(); p.wait()
    if p.returncode: sys.exit('encode failed')
    os.replace(tmp, out)
    json.dump(dict(K.record(), plan=dict(hook='', window=[round(T0, 2), round(T1, 2)], scenes=[s['kind'] for s in scenes],
                                          people=sorted({s['who'] for s in scenes}))), open(out[:-4] + '.json', 'w'))
    print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    main()
