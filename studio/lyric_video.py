"""Lyric and producer videos, drawn from a song's own project data.

    python studio/lyric_video.py <song_dir> <band|producer> <seed> <out.mp4> [--frames a,b,..]

Writes out.mp4 plus out.json, the recipe: every choice the seed made (scenes,
overlays, background, palette, pictures). The recipe is what lets the stats
compare ingredients instead of whole videos.

A song directory holds everything the renderer needs (see studio/README.md):
song.json, master.wav, stems/, lines.json, arrangement.json and, optionally,
media/<line number>/ pictures.

This is a standalone tool, deliberately outside src/: it needs numpy, OpenCV,
librosa and a song's stems, none of which the posting pipeline should depend
on. Its output is an ordinary video file that goes in through the dashboard
or `ugc ingest` like any other clip.
"""
import sys, os, random, subprocess, json
import numpy as np, soundfile as sf, cv2, librosa
from PIL import Image, ImageDraw, ImageFont

if len(sys.argv) < 5:
    sys.exit(__doc__)
SONG_DIR = os.path.abspath(sys.argv[1]); sys.argv = [sys.argv[0]] + sys.argv[2:]
SONG = json.load(open(os.path.join(SONG_DIR, 'song.json')))
MASTER = next((os.path.join(SONG_DIR, 'master' + e) for e in ('.wav', '.flac', '.ogg') if os.path.exists(os.path.join(SONG_DIR, 'master' + e))), os.path.join(SONG_DIR, 'master.wav'))
# A song with its Ableton arrangement (arrangement.json) gets the piano-roll and
# arrangement scenes drawn from the real notes. Without one, the same scenes are
# drawn from the four stems, and the beat grid comes from the detected tempo.
_arr = os.path.join(SONG_DIR, 'arrangement.json'); HAS_ARR = os.path.exists(_arr) and 'arrangement_rows' in SONG
D = json.load(open(_arr)) if HAS_ARR else dict(tempo=SONG['tempo'], tracks=[])
SPB = 60 / D['tempo']; TR = D['tracks']
OFF = SONG['offset_sec']            # master_time = beat * SPB + OFF
PROJECT = SONG.get('project', SONG['slug'])
MUSIC_ROWS = SONG.get('arrangement_rows', [])
STEMS_START = SONG.get('stems_start_sec', 0.0)
LINES = [(e, [(w, t) for w, t in ws]) for e, ws in json.load(open(os.path.join(SONG_DIR, 'lines.json')))]
stem_path = lambda name: next((os.path.join(SONG_DIR, 'stems', name + e) for e in ('.flac', '.ogg') if os.path.exists(os.path.join(SONG_DIR, 'stems', name + e))), os.path.join(SONG_DIR, 'stems', name + '.flac'))


def _font(*names):
    """First of these fonts that exists; the repo's own font as a last resort."""
    roots = ['/usr/share/fonts', '/Library/Fonts', '/System/Library/Fonts', os.path.expanduser('~/Library/Fonts'),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts')]
    for name in names:
        for root in roots:
            for base, _, files in os.walk(root):
                if name in files: return os.path.join(base, name)
    sys.exit('no usable font found; looked for ' + ', '.join(names))
SANS_B = _font('LiberationSans-Bold.ttf', 'Arial Bold.ttf', 'Montserrat-ExtraBold.ttf')
SANS = _font('LiberationSans-Regular.ttf', 'Arial.ttf', 'Montserrat-ExtraBold.ttf')
MONO = _font('DejaVuSansMono.ttf', 'Menlo.ttc', 'Courier New.ttf', 'Montserrat-ExtraBold.ttf')
INTER_XB = _font('Inter-ExtraBold.otf', 'Montserrat-ExtraBold.ttf')
INTER_SB = _font('Inter-SemiBold.otf', 'Montserrat-ExtraBold.ttf')


def cut(audio_path, start, end, out_wav, xfade=0.12, fade_in=0.01):
    info = sf.info(audio_path); sr = info.samplerate
    x, _ = sf.read(audio_path, start=int(start * sr), stop=int(end * sr), always_2d=True, dtype="float32")
    n = int(xfade * sr); a = int(start * sr)
    pre, _ = sf.read(audio_path, start=max(0, a - n), stop=a, always_2d=True, dtype="float32")
    ramp = np.linspace(0, 1, n)[:, None]
    if len(pre) == n:
        # the tail fades into the sound just before the start, so the loop runs straight on into the first sample
        x[-n:] = x[-n:] * (1 - ramp) + pre * ramp
    else:
        fi = int(fade_in * sr); x[:fi] *= np.linspace(0, 1, fi)[:, None]
    peak = np.abs(x).max()
    if peak > 0.98: x *= 0.98 / peak
    sf.write(out_wav, x, sr)
    return len(x) / sr


W, H, FPS = 1080, 1920, 30
PROBLEM = [37.46, 38.96, 49.68, 51.20]   # word "problem" in the master (whisper word timestamps)
DROP_BEAT = 288
F = lambda p, s: ImageFont.truetype(p, s)
b2t = lambda b: b * SPB + OFF
t2b = lambda t: (t - OFF) / SPB


def features(wav):
    y, sr = sf.read(wav, always_2d=True, dtype='float32'); y = librosa.resample(y.mean(1), orig_sr=sr, target_sr=22050)
    hop = 735
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    fr = librosa.fft_frequencies(sr=22050, n_fft=2048)
    edges = np.geomspace(40, 9000, 33)
    bands = np.array([S[(fr >= a) & (fr < b)].mean(0) for a, b in zip(edges[:-1], edges[1:])])
    bands = np.log1p(bands * 20); bands /= np.percentile(bands, 99) + 1e-9
    low = S[(fr >= 30) & (fr < 110)].mean(0); low /= np.percentile(low, 99) + 1e-9
    return np.clip(bands, 0, 1), np.clip(low, 0, 1.2)


def glitch(a, rng, amt):
    a = a.copy()
    for _ in range(int(6 * amt) + 2):
        y0 = rng.randrange(0, H - 60); h = rng.randrange(12, 110); dx = rng.randrange(-140, 140)
        a[y0:y0 + h] = np.roll(a[y0:y0 + h], int(dx * amt), axis=1)
    s = int(14 * amt)
    a[..., 0] = np.roll(a[..., 0], s, axis=1); a[..., 2] = np.roll(a[..., 2], -s, axis=1)
    return a

# ---------------------------------------------------------------- band look
PAL = [(255, 105, 97), (255, 179, 71), (253, 253, 150), (119, 221, 119), (100, 200, 255), (177, 156, 217),
       (255, 150, 200), (130, 240, 220), (240, 240, 240), (255, 130, 60), (160, 220, 90), (90, 150, 255)]


def win(d, x0, y0, x1, y1, title, active=True):
    d.rectangle([x0, y0, x1, y1], fill=(192, 192, 192))
    d.line([x0, y0, x1, y0], fill=(255, 255, 255), width=3); d.line([x0, y0, x0, y1], fill=(255, 255, 255), width=3)
    d.line([x0, y1, x1, y1], fill=(64, 64, 64), width=3); d.line([x1, y0, x1, y1], fill=(64, 64, 64), width=3)
    d.rectangle([x0 + 6, y0 + 6, x1 - 6, y0 + 52], fill=(0, 0, 128) if active else (128, 128, 128))
    d.text((x0 + 18, y0 + 12), title, font=F(SANS_B, 30), fill=(255, 255, 255))
    bx = x1 - 50
    d.rectangle([bx, y0 + 12, bx + 36, y0 + 46], fill=(192, 192, 192), outline=(0, 0, 0))
    d.line([bx + 9, y0 + 20, bx + 27, y0 + 38], fill=(0, 0, 0), width=3); d.line([bx + 27, y0 + 20, bx + 9, y0 + 38], fill=(0, 0, 0), width=3)


def inset(d, x0, y0, x1, y1, fill):
    d.rectangle([x0, y0, x1, y1], fill=fill)
    d.line([x0, y0, x1, y0], fill=(64, 64, 64), width=3); d.line([x0, y0, x0, y1], fill=(64, 64, 64), width=3)
    d.line([x0, y1, x1, y1], fill=(255, 255, 255), width=3); d.line([x1, y0, x1, y1], fill=(255, 255, 255), width=3)


def button(d, x0, y0, x1, y1, text):
    d.rectangle([x0, y0, x1, y1], fill=(192, 192, 192))
    d.line([x0, y0, x1, y0], fill=(255, 255, 255), width=3); d.line([x0, y0, x0, y1], fill=(255, 255, 255), width=3)
    d.line([x0, y1, x1, y1], fill=(0, 0, 0), width=3); d.line([x1, y0, x1, y1], fill=(0, 0, 0), width=3)
    f = F(SANS_B, 30); w = d.textlength(text, font=f); d.text(((x0 + x1 - w) / 2, y0 + 10), text, font=f, fill=(0, 0, 0))


def line_at(T):
    for k, (e, ws) in enumerate(LINES):
        if ws[0][1] - 0.05 <= T < e + 0.25: return k
    return None
def shown(k, T): return [w for w, s in LINES[k][1] if s <= T + 0.03]

def wrap(d, words, font, maxw):
    rows, cur = [], []
    for w in words:
        if cur and d.textlength(' '.join(cur + [w]), font=font) > maxw: rows.append(cur); cur = []
        cur.append(w)
    if cur: rows.append(cur)
    return rows

def karaoke(d, k, T, y, size=70, maxw=980, fill=(255, 255, 255), hl=(255, 230, 60), outline=True):
    ws = LINES[k][1]; allw = [w for w, _ in ws]; f = F(INTER_XB, size)
    rows = wrap(d, allw, f, maxw); i = 0
    for r in rows:
        tw = d.textlength(' '.join(r), font=f); x = (W - tw) / 2
        for w in r:
            st = ws[i][1]; nxt = ws[i + 1][1] if i + 1 < len(ws) else LINES[k][0]
            if st <= T + 0.03:
                c = hl if T < nxt else fill
                d.text((x, y), w, font=f, fill=c, stroke_width=6 if outline else 0, stroke_fill=(0, 0, 0))
            x += d.textlength(w + ' ', font=f); i += 1
        y += int(size * 1.18)

# ------------------------------------------------------------------ band scenes
STAGE = (36, 380, 1044, 1290)
def sc_notepad(d, k, T, title='lyrics.txt - Notepad', size=96):
    x0, y0, x1, y1 = STAGE; win(d, x0, y0, x1, y1, title)
    d.text((x0 + 20, y0 + 62), 'File   Edit   Search   Help', font=F(SANS, 28), fill=(0, 0, 0))
    inset(d, x0 + 14, y0 + 104, x1 - 14, y1 - 14, (255, 255, 255))
    f = F(MONO, size); ws = shown(k, T); rows = wrap(d, ws, f, x1 - x0 - 90); y = y0 + 140
    for r in rows:
        d.text((x0 + 44, y), ' '.join(r), font=f, fill=(0, 0, 0)); y += int(size * 1.25)
    if int(T * 4) % 2 and rows:
        cx = x0 + 44 + d.textlength(' '.join(rows[-1]) + ' ', font=f); d.rectangle([cx, y - int(size * 1.25) + 8, cx + 10, y - 12], fill=(0, 0, 0))
def dialog(d, dx, dy, text, title=PROJECT + '.exe', w=640):
    win(d, dx, dy, dx + w, dy + 270, title)
    d.ellipse([dx + 34, dy + 84, dx + 110, dy + 160], fill=(0, 0, 200), outline=(255, 255, 255), width=3)
    d.text((dx + 62, dy + 90), 'i', font=F(SANS_B, 56), fill=(255, 255, 255))
    d.text((dx + 140, dy + 100), text, font=F(SANS, 42), fill=(0, 0, 0))
    button(d, dx + w // 2 - 80, dy + 190, dx + w // 2 + 80, dy + 244, 'OK')
def sc_dialogs(d, k, T, text, many=False):
    ws = LINES[k][1]; n = len(shown(k, T))
    if many:
        r = random.Random(k); n = int((T - ws[0][1]) / (LINES[k][0] - ws[0][1]) * 16) + 1
        for i in range(n): dialog(d, r.randrange(-40, 520), r.randrange(240, 1300), text)
    else:
        for i in range(n): dialog(d, 60 + i * 62, 400 + i * 118, text if i == n - 1 or i >= 2 else '. . .')
def sc_messages(d, k, T):
    x0, y0, x1, y1 = STAGE; n = len(shown(k, T)); msgs = ['hey', 'u up?', 'where r u', 'call me', '???']
    win(d, x0, y0, x1, y1, 'Inbox (%d) - Messages' % max(0, 5 - n))
    inset(d, x0 + 14, y0 + 64, x1 - 14, y1 - 70, (255, 255, 255))
    for i, m in enumerate(msgs):
        y = y0 + 84 + i * 118
        if i < n - 1: continue
        sel = i == n - 1
        d.rectangle([x0 + 20, y, x1 - 20, y + 104], fill=(0, 0, 128) if sel else (255, 255, 255))
        c = (255, 255, 255) if sel else (0, 0, 0)
        d.rectangle([x0 + 40, y + 28, x0 + 104, y + 76], outline=c, width=3); d.line([x0 + 40, y + 28, x0 + 72, y + 54, x0 + 104, y + 28], fill=c, width=3)
        d.text((x0 + 130, y + 26), m, font=F(SANS_B, 46), fill=c)
        if sel: tw = d.textlength('DELETE', font=F(SANS_B, 40)); d.text((x1 - 50 - tw, y + 30), 'DELETE', font=F(SANS_B, 40), fill=(255, 90, 90))
    d.text((x0 + 22, y1 - 56), 'Deleting... %d of 5' % min(5, n), font=F(SANS, 32), fill=(0, 0, 0))
def sc_cmd(d, k, T):
    x0, y0, x1, y1 = STAGE; win(d, x0, y0, x1, y1, 'C:\\EDUCATION\\test.exe')
    d.rectangle([x0 + 10, y0 + 60, x1 - 10, y1 - 10], fill=(0, 0, 0)); f = F(MONO, 58); g = (60, 255, 90)
    d.text((x0 + 34, y0 + 84), 'C:\\EDUCATION> test.exe', font=F(MONO, 40), fill=(200, 200, 200))
    rows = wrap(d, shown(k, T), f, x1 - x0 - 90); y = y0 + 160
    for r in rows: d.text((x0 + 34, y), '> ' + ' '.join(r), font=f, fill=g); y += 84
    if any('confess' in w for w, _ in LINES[k][1]) and T > LINES[k][1][-1][1] + 0.2: d.text((x0 + 34, y + 30), 'confession.txt: FOUND', font=F(MONO, 44), fill=(255, 220, 0))
def sc_player(d, f, bands, big=True):
    x0, y0, x1, y1 = STAGE; win(d, x0, y0, x1, y1, 'EDUCATION.cd - Media Player')
    d.text((x0 + 22, y0 + 66), 'Now playing:  %d. %s  -  %s' % (SONG['track'], SONG['title'], SONG['artist']), font=F(SANS, 30), fill=(0, 0, 0))
    sx0, sy0, sx1, sy1 = x0 + 14, y0 + 112, x1 - 14, y1 - 14; inset(d, sx0, sy0, sx1, sy1, (0, 0, 0))
    fi = min(f, bands.shape[1] - 1); bw = (sx1 - sx0 - 12) / bands.shape[0]
    for b in range(bands.shape[0]):
        v = float(bands[b, max(0, fi - 1):fi + 1].mean()); hh = int(v * (sy1 - sy0 - 14))
        for seg in range(0, hh, 18):
            c = (0, 230, 0) if seg < (sy1 - sy0) * 0.6 else ((255, 220, 0) if seg < (sy1 - sy0) * 0.85 else (255, 60, 60))
            d.rectangle([sx0 + 7 + b * bw, sy1 - 6 - seg - 14, sx0 + 7 + (b + 1) * bw - 4, sy1 - 6 - seg], fill=c)
def sc_arr(d, beat, ppb=46):
    x0, y0, x1, y1 = STAGE; win(d, x0, y0, x1, y1, PROJECT + '.als - Arrangement')
    ix0, iy0, ix1, iy1 = x0 + 14, y0 + 64, x1 - 14, y1 - 14; inset(d, ix0, iy0, ix1, iy1, (38, 38, 42))
    if not HAS_ARR:                      # four stem lanes instead of the project's clips
        ph = ix0 + int((ix1 - ix0) * 0.38); rh = (iy1 - iy0 - 8) / 4
        for b in range(int(beat) - 10, int(beat) + 16):
            x = ph + (b - beat) * ppb
            if ix0 + 3 < x < ix1 - 3 and b % 4 == 0: d.line([x, iy0 + 3, x, iy1 - 3], fill=(86, 86, 92), width=1)
        for r, nm in enumerate(('Vocals', 'Drums', 'Bass', 'Other')):
            mid = iy0 + 4 + r * rh + rh / 2; col = PAL[(r * 3 + 1) % len(PAL)]
            d.text((ix0 + 10, mid - rh / 2 + 6), nm.upper(), font=F(MONO, 24), fill=(170, 170, 176))
            for x in range(ix0 + 4, ix1 - 4, 4):
                v = ev(nm, b2t(beat + (x - ph) / ppb)) * rh * 0.44
                d.line([x, mid - v, x, mid + v], fill=col if x > ph else tuple(int(c * .5) for c in col), width=3)
        d.line([ph, iy0 + 3, ph, iy1 - 3], fill=(255, 255, 255), width=3); return
    ph = ix0 + int((ix1 - ix0) * 0.38); rh = (iy1 - iy0 - 8) / len(MUSIC_ROWS); bx = lambda b: ph + (b - beat) * ppb
    for b in range(int(beat) - 10, int(beat) + 16):
        x = bx(b)
        if ix0 + 3 < x < ix1 - 3 and b % 4 == 0: d.line([x, iy0 + 3, x, iy1 - 3], fill=(86, 86, 92), width=1)
    for r, i in enumerate(MUSIC_ROWS):
        y = iy0 + 5 + r * rh; col = PAL[(i * 5) % len(PAL)]; t = TR[i]
        items = [(a, a + max(du, .2)) for a, du, _, _ in t['notes']] if t['notes'] else [(s, e) for s, e, _ in t['clips']]
        for s, e in items:
            xa, xb = max(bx(s), ix0 + 3), min(bx(e) - 2, ix1 - 3)
            if xb <= xa: continue
            d.rectangle([xa, y, xb, y + rh - 4], fill=(255, 255, 255) if s <= beat < e else (col if s > beat else tuple(int(v * .5) for v in col)))
    d.line([ph, iy0 + 3, ph, iy1 - 3], fill=(255, 255, 255), width=3)
NN = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
def sc_roll(d, beat, idx, title, col, ppb=120):
    x0, y0, x1, y1 = STAGE; win(d, x0, y0, x1, y1, title)
    ix0, iy0, ix1, iy1 = x0 + 14, y0 + 64, x1 - 14, y1 - 14; inset(d, ix0, iy0, ix1, iy1, (38, 38, 42))
    notes = [n for i in idx for n in TR[i]['notes']]; keys = list(range(min(n[2] for n in notes), max(n[2] for n in notes) + 1))
    kw = 96; kh = (iy1 - iy0 - 8) / len(keys); ph = ix0 + kw + 260; bx = lambda b: ph + (b - beat) * ppb
    for r, key in enumerate(reversed(keys)):
        y = iy0 + 4 + r * kh; blk = key % 12 in (1, 3, 6, 8, 10)
        d.rectangle([ix0 + kw, y, ix1 - 3, y + kh - 1], fill=(44, 44, 50) if blk else (54, 54, 60))
    for a, du, key, v in notes:
        if a + du < beat - 4 or a > beat + 8: continue
        r = len(keys) - 1 - keys.index(key); y = iy0 + 4 + r * kh
        xa, xb = max(bx(a), ix0 + kw), min(bx(a + max(du, .15)) - 3, ix1 - 3)
        if xb > xa: d.rectangle([xa, y + 2, xb, y + kh - 3], fill=(255, 255, 255) if a <= beat < a + du else col)
    act = {n[2] for n in notes if n[0] <= beat < n[0] + n[1]}
    for r, key in enumerate(reversed(keys)):
        y = iy0 + 4 + r * kh; blk = key % 12 in (1, 3, 6, 8, 10)
        d.rectangle([ix0 + 3, y, ix0 + kw, y + kh - 1], fill=col if key in act else ((20, 20, 20) if blk else (240, 240, 240)), outline=(90, 90, 90))
        if kh > 34: d.text((ix0 + 10, y + kh / 2 - 15), NN[key % 12] + str(key // 12 - 1), font=F(MONO, 26), fill=(130, 130, 130) if not blk else (200, 200, 200))
    d.line([ph, iy0 + 3, ph, iy1 - 3], fill=(255, 255, 255), width=3)
def sc_clock(d, k, T):
    x0, y0, x1, y1 = 120, 470, 960, 1010; win(d, x0, y0, x1, y1, 'Date/Time Properties')
    inset(d, x0 + 24, y0 + 80, x1 - 24, y1 - 110, (0, 0, 0))
    on = T >= [t for w, t in LINES[k][1] if '4:20' in w][0]; txt = '4:20' if on else '4:19'; f = F(MONO, 250); tw = d.textlength(txt, font=f)
    d.text(((x0 + x1 - tw) / 2, y0 + 110), txt, font=f, fill=(60, 255, 90) if on else (30, 90, 40))
    button(d, x0 + 300, y1 - 86, x0 + 540, y1 - 26, 'OK')

def env_of(name):
    y, sr = sf.read(stem_path(name), always_2d=True, dtype='float32'); y = np.abs(y).max(1)
    st = sr // 200; e = y[:len(y) // st * st].reshape(-1, st).max(1); return e / np.percentile(e, 99.5)
ENV = {n: env_of(n) for n in ('Vocals', 'Drums', 'Bass', 'Other') if os.path.exists(stem_path(n))}
ev = lambda n, T: float(ENV[n][min(len(ENV[n]) - 1, max(0, int((T - STEMS_START) * 200)))])
MEL_T, HAT_T = (b2t(SONG['melody_enters_beat']), b2t(SONG['hats_enter_beat'])) if HAS_ARR else (-1e9, -1e9)

def sc_paint(d, k, T):
    x0, y0, x1, y1 = STAGE; win(d, x0, y0, x1, y1, 'word.bmp - Paint')
    for i in range(8):
        d.rectangle([x0 + 16 + (i % 2) * 48, y0 + 70 + (i // 2) * 48, x0 + 58 + (i % 2) * 48, y0 + 112 + (i // 2) * 48], fill=(192, 192, 192), outline=(64, 64, 64), width=2)
    inset(d, x0 + 124, y0 + 66, x1 - 14, y1 - 74, (255, 255, 255))
    for i, c in enumerate(PAL): d.rectangle([x0 + 124 + i * 50, y1 - 60, x0 + 168 + i * 50, y1 - 18], fill=c, outline=(0, 0, 0))
    ws = shown(k, T)
    if ws:
        w = ws[-1].strip(',.'); size = 300
        while size > 60 and d.textlength(w, font=F(INTER_XB, size)) > x1 - x0 - 220: size -= 10
        f = F(INTER_XB, size); tw = d.textlength(w, font=f)
        d.text(((x0 + 124 + x1 - 14 - tw) / 2, (y0 + 66 + y1 - 74) / 2 - size * 0.62), w, font=f, fill=tuple(int(c * .8) for c in PAL[(len(ws) * 5 + k) % len(PAL)]))
def sc_wave(d, k, T):
    x0, y0, x1, y1 = STAGE; win(d, x0, y0, x1, y1, 'vocal.wav - Sound Recorder')
    ix0, iy0, ix1, iy1 = x0 + 14, y0 + 64, x1 - 14, y1 - 14; inset(d, ix0, iy0, ix1, iy1, (0, 0, 0))
    pps = 430; ph = ix0 + 300; mid = iy0 + 290
    for x in range(ix0 + 4, ix1 - 4, 4):
        v = ev('Vocals', T + (x - ph) / pps) * 260; d.line([x, mid - v, x, mid + v], fill=(60, 255, 90) if x > ph else (30, 120, 50), width=3)
    d.line([ph, iy0 + 4, ph, iy1 - 4], fill=(255, 255, 255), width=3)
    if k is not None:
        f = F(MONO, 52); ws = LINES[k][1]
        for i, (w, st) in enumerate(ws):
            x = ph + (st - T) * pps; nxt = ws[i + 1][1] if i + 1 < len(ws) else LINES[k][0]
            if ix0 < x < ix1 - 40:
                d.text((x, iy0 + 590 + (i % 3) * 78), w, font=f, fill=(255, 230, 60) if st <= T < nxt else ((90, 110, 90) if st < T else (60, 255, 90)))
OWN_TEXT = {'notepad', 'cmd', 'paint', 'wave'}
def draw(kind, d, k, T, f, bands, beat):
    if kind == 'notepad': sc_notepad(d, k, T)
    elif kind == 'cmd': sc_cmd(d, k, T)
    elif kind == 'paint': sc_paint(d, k, T)
    elif kind == 'wave': sc_wave(d, k, T)
    elif kind == 'player': sc_player(d, f, bands)
    elif kind == 'arr': sc_arr(d, beat, ppb=60)
    elif kind == 'roll_mel': sc_roll(d, beat, SONG['melody_tracks'], 'melody.mid - Piano Roll', (100, 200, 255))
    elif kind == 'roll_hat': sc_roll(d, beat, SONG['hat_tracks'], 'hats.mid - Piano Roll', (170, 255, 170))
    elif kind == 'messages': sc_messages(d, k, T)
    elif kind == 'clock': sc_arr(d, beat, ppb=60); sc_clock(d, k, T)
    elif kind in ('dialogs', 'flood'):
        sc_arr(d, beat, ppb=60); sc_dialogs(d, k, T, "It's not a problem.", many=kind == 'flood')

mode, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
R = random.Random(seed * 7919 + (1 if mode == 'band' else 2))
# CQ_WINDOW="start,end" renders a different stretch of the song than song.json names,
# which is how one song yields a video per lyric section.
T0, T1 = [float(x) for x in os.environ['CQ_WINDOW'].split(',')] if os.environ.get('CQ_WINDOW') else SONG['windows'][mode]
# only the lines inside the window matter to a render
LINES = [L for L in LINES if L[0] > T0 - 0.2 and L[1][0][1] < T1] or LINES[:1]
has = lambda k, s: any(s in w.lower() for w, _ in LINES[k][1])
# strong drum hits (for flashes)
dy, dsr = sf.read(stem_path('Drums'), always_2d=True, dtype='float32'); dy = dy.mean(1)
oe = librosa.onset.onset_strength(y=dy, sr=dsr, hop_length=256); pk = librosa.util.peak_pick(oe, pre_max=6, post_max=6, pre_avg=20, post_avg=20, delta=np.percentile(oe, 97) * 0.5, wait=int(0.6 * dsr / 256))
HITS = STEMS_START + pk * 256 / dsr

_yy, _xx = np.mgrid[0:240, 0:135].astype(np.float32); _RS = np.random.RandomState(5); _ST = _RS.rand(260, 3)
def make_bg(kind, T, base, acc):
    d = ev('Drums', T)
    if kind == 'plasma':
        v = np.sin(_xx * .09 + T * .8) + np.sin(_yy * .06 - T * .6) + np.sin((_xx + _yy) * .05 + T * .4) + np.sin(np.hypot(_xx - 67, _yy - 120) * .08 - T)
        v = np.floor((v + 4) / 8 * 6) / 5
    elif kind == 'tiles': v = (((_xx + T * 6) // 12 + (_yy + T * 4) // 12) % 2) * .45 + .1 + d * .35
    elif kind == 'rings': v = (((np.hypot(_xx - 67, _yy - 120) * .1 - t2b(T) * .5) % 1) < .5) * .55 + .1
    elif kind == 'grad': v = np.floor((_yy / 240 + .08 * np.sin(_xx * .08 + T * 1.2) + .05 * d) * 9) / 9
    else:
        v = np.zeros((240, 135), np.float32); z = (_ST[:, 2] - T * .22) % 1 + .04
        px = (67 + (_ST[:, 0] * 2 - 1) / z * 30).astype(int); py = (120 + (_ST[:, 1] * 2 - 1) / z * 55).astype(int); ok = (px >= 0) & (px < 135) & (py >= 0) & (py < 240)
        v[py[ok], px[ok]] = np.clip(1.2 - z[ok], .3, 1); acc = mixc(acc, (255, 255, 255), .7)
    v = np.clip(v, 0, 1)[..., None]; img = np.array(base, np.float32) * (1 - v) + np.array(acc, np.float32) * v
    return cv2.resize(img.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
mixc = lambda a, b, t: tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))
WALLS = ['plasma', 'tiles', 'rings', 'grad', 'stars']

MEDIA = os.environ.get('CQ_MEDIA', os.path.join(SONG_DIR, 'media')); PIC_STYLES = ['lowres', 'gif', 'jpeg', 'webcam', 'crt']
def media_for(k):
    d = os.path.join(MEDIA, '%02d' % k); return sorted(os.path.join(d, x) for x in os.listdir(d) if x.lower().endswith(('.jpg', '.jpeg', '.png', '.webm', '.ogv', '.mp4'))) if os.path.isdir(d) else []
_MC = {}; BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16
def media_frame(path, t):
    if path.lower().endswith(('.webm', '.ogv', '.mp4')):
        if path not in _MC:
            c = cv2.VideoCapture(path); fr_ = []
            while len(fr_) < 240:
                ok, x = c.read()
                if not ok: break
                fr_.append(cv2.cvtColor(cv2.resize(x, (492, int(492 * x.shape[0] / x.shape[1]))), cv2.COLOR_BGR2RGB))
            _MC[path] = (fr_, c.get(cv2.CAP_PROP_FPS) or 25)
        fr_, fps = _MC[path]; return fr_[int(t * fps) % len(fr_)] if fr_ else np.zeros((200, 300, 3), np.uint8)
    if path not in _MC: _MC[path] = np.asarray(Image.open(path).convert('RGB'))
    return _MC[path]
def digitize(src, style, t, w, h, c0, c1):
    """light 'old computer' treatments: the picture stays readable, it just loses quality"""
    f = {'lowres': 5, 'gif': 3, 'jpeg': 3, 'webcam': 4, 'crt': 2}[style]; lw, lh = w // f, h // f; sh, sw = src.shape[:2]; z = 1 + 0.1 * t; s = max(lw / sw, lh / sh) * z
    m = cv2.resize(src, (max(lw, int(sw * s) + 1), max(lh, int(sh * s) + 1)), interpolation=cv2.INTER_AREA); y0 = (m.shape[0] - lh) // 2; x0 = (m.shape[1] - lw) // 2; m = np.ascontiguousarray(m[y0:y0 + lh, x0:x0 + lw])
    if style == 'gif': m = np.asarray(Image.fromarray(m).quantize(24, dither=Image.FLOYDSTEINBERG).convert('RGB'))
    elif style == 'jpeg': m = cv2.imdecode(cv2.imencode('.jpg', m, [cv2.IMWRITE_JPEG_QUALITY, 9])[1], 1)
    elif style == 'webcam':
        n = np.random.RandomState(int(t * 12)).randint(-14, 15, m.shape[:2] + (1,)); m = np.clip(m.astype(np.int16) * .92 + 12 + n, 0, 255).astype(np.uint8)
    elif style == 'crt':
        m = cv2.GaussianBlur(m, (3, 3), 0); m = np.clip((m.astype(np.float32) - 128) * 1.15 + 132, 0, 255).astype(np.uint8)
    o = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST if style != 'crt' else cv2.INTER_LINEAR)
    if style == 'crt': o = o.copy(); o[::3] = (o[::3] * .72).astype(np.uint8)
    return Image.fromarray(o)
def sc_pic(d, path, style, T, st, c0, c1):
    x0, y0, x1, y1 = STAGE; win(d, x0, y0, x1, y1, os.path.basename(path).split('_', 1)[-1].rsplit('.', 1)[0][:22] + '.bmp - Viewer')
    d._image.paste(digitize(media_frame(path, T - st), style, T - st, x1 - x0 - 24, y1 - y0 - 76, c0, c1), (x0 + 12, y0 + 62))
OV_ALL = ['trail', 'track', 'invert', 'pip', 'pipwave', 'stamp']
def pick_ov(): 
    o = [x for x in OV_ALL if R.random() < 0.42]
    while len(o) < 2: o = list(set(o + [R.choice(OV_ALL)]))
    return o

PIC_P = float(os.environ.get('CQ_PIC_P', '0.6'))
def caption(a, k, T, y, size, maxw):
    im = Image.fromarray(a); karaoke(ImageDraw.Draw(im), k, T, y, size=size, maxw=maxw, outline=True); return np.asarray(im)

def plan_band():
    themes = [((0, 128, 128), 'teal'), ((58, 110, 165), 'blue'), ((85, 60, 130), 'purple'), ((20, 20, 24), 'black'), ((0, 110, 70), 'green')]
    theme = R.choice(themes); segs = []; prev = [None]
    def pick(k, st):
        pool = ['notepad', 'cmd', 'paint', 'paint', 'wave', 'player', 'arr']
        if HAS_ARR and st >= MEL_T + 0.3: pool += ['roll_mel'] * 2
        if HAS_ARR and st >= HAT_T + 0.3: pool += ['roll_hat'] * 2
        if has(k, 'problem'): pool += ['dialogs'] * 4 + ['flood'] * 4
        if has(k, 'messages'): pool += ['messages'] * 8
        if has(k, '4:20'): pool += ['clock'] * 8
        if has(k, 'confess'): pool += ['cmd'] * 4
        ms = media_for(k)
        if ms and R.random() < PIC_P and not str(prev[0]).startswith('pic'): c = 'pic|%s|%s' % (R.choice(ms), R.choice(PIC_STYLES)); prev[0] = c; return c
        c = R.choice([p for p in pool if p != prev[0]]); prev[0] = c; return c
    for k, (e, ws) in enumerate(LINES):
        st = ws[0][1]
        if st > T1: break
        if k > 0 and st - LINES[k - 1][0] > 1.0:
            g = R.choice([x for x in ['arr', 'player', 'wave'] if x != prev[0]]); segs.append([LINES[k - 1][0], g, None, pick_ov()]); prev[0] = g
        if e - st > 2.3 and len(ws) >= 6 and not has(k, 'messages'):
            m = ws[len(ws) // 2][1]; segs += [[st, pick(k, st), k, pick_ov()], [m, pick(k, m), k, pick_ov()]]
        else: segs.append([st, pick(k, st), k, pick_ov()])
    return dict(wall=R.choice(WALLS), acc=mixc(theme[0], R.choice(PAL), R.choice([.35, .5])) if theme[1] != 'black' else mixc((20, 20, 24), R.choice(PAL), .6), theme=theme[1], bg=theme[0], segs=segs, punch=R.choice([0.02, 0.035, 0.05]), scan=R.random() < 0.7, chroma=R.choice([0, 2, 4]))

def seg_at(plan, T):
    s = [i for i, x in enumerate(plan['segs']) if x[0] <= T + 0.03]; return s[-1] if s else 0

def mini_win(d, x0, y0, x1, y1, title):
    win(d, x0, y0, x1, y1, title); d.rectangle([x0 + 10, y0 + 58, x1 - 10, y1 - 10], fill=(0, 0, 0))
def overlays_pil(im, d, ov, k, T, f, bands):
    if 'pip' in ov:
        x0, y0, x1, y1 = 600, 1010, 1030, 1300; mini_win(d, x0, y0, x1, y1, 'levels.exe'); fi = min(f, bands.shape[1] - 1)
        for b in range(0, 32, 2):
            v = float(bands[b:b + 2, fi].mean()); d.rectangle([x0 + 20 + b * 12.3, y1 - 16 - v * 200, x0 + 40 + b * 12.3, y1 - 16], fill=(255, 60, 200))
    if 'pipwave' in ov:
        x0, y0, x1, y1 = 520, 330, 1050, 560; mini_win(d, x0, y0, x1, y1, 'vox.wav'); mid = (y0 + 58 + y1 - 10) / 2
        for x in range(x0 + 14, x1 - 14, 4):
            v = ev('Vocals', T + (x - x0 - 180) / 260) * 70; d.line([x, mid - v, x, mid + v], fill=(255, 230, 60), width=3)
    if 'stamp' in ov and k is not None:
        ws = shown(k, T)
        if ws:
            w = ws[-1].strip(',.').upper(); fnt = F(INTER_XB, 300); tw = int(d.textlength(w, font=fnt)) + 40
            lay = Image.new('RGBA', (tw, 380), (0, 0, 0, 0)); ImageDraw.Draw(lay).text((20, 10), w, font=fnt, fill=(255, 255, 255, 70))
            lay = lay.rotate(-14, expand=True, resample=Image.BICUBIC); im.paste(lay, (int((W - lay.width) / 2), 1040 - lay.height // 2), lay)
    # cursor
    cx = int(540 + 380 * np.sin(T * 1.3 + seed)); cy = int(900 + 330 * np.sin(T * 0.9 + 1.7 * seed))
    ImageDraw.Draw(im).polygon([(cx, cy), (cx, cy + 46), (cx + 12, cy + 35), (cx + 22, cy + 56), (cx + 30, cy + 52), (cx + 20, cy + 32), (cx + 36, cy + 32)], fill=(255, 255, 255), outline=(0, 0, 0))

SCAN = np.ones((H, 1, 1), np.float32); SCAN[::4] = 0.8; SCAN[1::4] = 0.9
def fx(a, T, f, plan, ov, st, box, ctx, rng):
    a = a.copy(); x0, y0, x1, y1 = box
    if 'trail' in ov:
        n = min(7, int((T - st) / 0.09)); reg = a[y0:y1, x0:x1].copy()
        for i in range(n, 0, -1):
            dx, dyy = i * 24, i * 22; hh = min(y1 - y0, H - y0 - dyy); ww = min(x1 - x0, W - x0 - dx)
            a[y0 + dyy:y0 + dyy + hh, x0 + dx:x0 + dx + ww] = reg[:hh, :ww]
        a[y0:y1, x0:x1] = reg
    if 'invert' in ov and np.any((T - HITS >= 0) & (T - HITS < 0.07)): a[y0:y1, x0:x1] = 255 - a[y0:y1, x0:x1]
    if 'track' in ov:
        g = cv2.cvtColor(a[::2, ::2], cv2.COLOR_RGB2GRAY); n = 10 + int(ev('Drums', T) * 22)
        pts = cv2.goodFeaturesToTrack(g, n, 0.02, 70)
        if pts is not None:
            pts = (pts.reshape(-1, 2) * 2).astype(int); pts = pts[np.argsort(pts[:, 0] + pts[:, 1] * 0.3)]
            for i, (px, py) in enumerate(pts):
                s = 26 + (i * 13) % 34; cv2.rectangle(a, (px - s, py - s), (px + s, py + s), (255, 255, 255), 2)
                if i: cv2.line(a, (int(pts[i - 1][0]), int(pts[i - 1][1])), (px, py), (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(a, f'{px}.{py % 100:02d}', (px + s + 6, py + s), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    ctx['clean'] = a.copy()
    if ctx.get('old') is not None and 0 <= T - st < 0.26:        # datamosh-style smear from the previous scene
        fr_ = 1 - (T - st) / 0.26; bs = 60; m = (np.random.RandomState(f).rand(H // bs, W // bs) < fr_ * 0.75)
        m = np.kron(m, np.ones((bs, bs), bool)); old = np.roll(ctx['old'], int(70 * (1 - fr_)), axis=1); a[m] = old[m]
    beat = t2b(T); ph = (beat % 2) * SPB; z = 1 + plan['punch'] * np.exp(-ph * 9)
    if z > 1.004:
        cw, ch = int(W / z), int(H / z); xx, yy = (W - cw) // 2, (H - ch) // 2; a = cv2.resize(a[yy:yy + ch, xx:xx + cw], (W, H), interpolation=cv2.INTER_LINEAR)
    c = plan['chroma']
    if c: a[..., 0] = np.roll(a[..., 0], c, axis=1); a[..., 2] = np.roll(a[..., 2], -c, axis=1)
    if plan['scan']: a = (a * SCAN).astype(np.uint8)
    return a

def face_for(k, T, bands, ctx):
    """(photo, seconds since the current word) for lyric line k: whoever's turn it is, as big a reaction as
    the line is loud, and a second reaction halfway through a long line."""
    if 'lvl' not in ctx: ctx['lvl'] = _faces.levels(LINES, bands, T0, FPS)
    who = FACE_WHO[k % len(FACE_WHO)]; lv = ctx['lvl'][k] if k < len(ctx['lvl']) else 1
    ws = LINES[k][1]; wi, since = _faces.pose(ws, T)
    half = 1 if len(ws) >= 6 and wi >= len(ws) // 2 else 0
    first = _faces.pick(who, lv, (seed, k, 0))
    return (_faces.pick(who, min(2, lv + 1), (seed, k, 1), avoid=first) if half else first), since, who
def sprite_for(a, k, T, bands, beat, ctx, bottom, height):
    """Whoever's line it is, cut out and pixelated, in front: Dylan left of centre, Nick right."""
    name, since, who = face_for(k, T, bands, ctx)
    cx = W * (0.36 if who == 'dylan' else 0.64)
    return _faces.paste_sprite(np.ascontiguousarray(a), name, cx, bottom, height, since, T, beat % 1, block=plan.get('face_block', 9))
def facecam(a, T, bands, beat, ctx):
    """In the producer view the one whose line it is stands over the lower lanes."""
    k = line_at(T)
    if k is None: k = ctx.get('cam_k')
    if k is None: return a
    ctx['cam_k'] = k
    return sprite_for(a, k, T, bands, beat, ctx, bottom=1545, height=640)

def band_frame(f, feat, plan, ctx, rng):
    bands, low = feat; T = T0 + f / FPS; beat = t2b(T); si = seg_at(plan, T); st, kind, k, ov = plan['segs'][si]
    if ctx.get('si') != si: ctx['old'] = ctx.get('clean'); ctx['si'] = si
    im = Image.fromarray(make_bg(plan['wall'], T, plan['bg'], plan['acc'])); d = ImageDraw.Draw(im)
    for q, nm in enumerate(['EDUCATION.cd', 'Subscribe.exe', 'Recycle Bin']):
        x = 60 + q * 230; d.rectangle([x + 40, 86, x + 110, 150], fill=(255, 255, 255), outline=(0, 0, 0), width=3)
        d.rectangle([x + 52, 98, x + 98, 118], fill=PAL[q * 3]); fw = d.textlength(nm, font=F(SANS, 26)); d.text((x + 75 - fw / 2, 158), nm, font=F(SANS, 26), fill=(255, 255, 255))
    d.text((54, 214), SONG['album'], font=F(INTER_XB, 76), fill=(255, 255, 255))
    d.text((56, 304), 'lesson %d of %d: %s' % (SONG['track'], SONG.get('tracks_total', SONG['track']), SONG['title']), font=F(INTER_SB, 40), fill=(225, 240, 255))
    face = kind.startswith('face+'); kind = kind[5:] if face else kind      # a scene with one of the band in front of it
    if kind.startswith('pic|'): _, pth, sty = kind.split('|'); sc_pic(d, pth, sty, T, st, (10, 10, 30), mixc(plan['bg'], (255, 255, 255), .75))
    else: draw(kind, d, k, T, f, bands, beat)
    overlays_pil(im, ImageDraw.Draw(im), ov, k, T, f, bands); d = ImageDraw.Draw(im)
    d.rectangle([0, H - 84, W, H], fill=(192, 192, 192)); d.line([0, H - 84, W, H - 84], fill=(255, 255, 255), width=3)
    button(d, 10, H - 72, 190, H - 14, 'Start'); inset(d, W - 220, H - 72, W - 12, H - 14, (192, 192, 192))
    d.text((W - 190, H - 60), '4:20 PM' if any('4:20' in w and t < T for e, ws in LINES for w, t in ws) else '4:19 PM', font=F(SANS, 30), fill=(0, 0, 0))
    a = fx(np.asarray(im), T, f, plan, ov, st, STAGE, ctx, rng)
    if face and k is not None: a = sprite_for(a, k, T, bands, beat, ctx, bottom=1330, height=860)
    # The lyric goes on last, over every overlay and effect, so nothing can cover it.
    kl = line_at(T)
    return caption(a, kl, T, 1340, 64, 980) if kl is not None else a

def plan_prod():
    pals = [[(255, 190, 110), (255, 90, 110), (150, 160, 255), (120, 220, 255)], [(255, 255, 255), (255, 210, 60), (90, 220, 160), (255, 120, 200)], [(120, 255, 170), (255, 150, 80), (110, 190, 255), (240, 240, 120)]]
    segs = []; prev = -1
    for k, (e, ws) in enumerate(LINES):
        if ws[0][1] > T1: break
        c = R.choice([x for x in (None, 0, 0, 1, 2, 3) if x != prev]); prev = c
        segs.append([ws[0][1], [c, R.choice([84, 110, 140])], k, [x for x in pick_ov() if x in ('track', 'invert', 'stamp')] or ['stamp']])
    pal_ = R.choice(pals); bg_ = R.choice([(11, 13, 16), (16, 12, 22), (8, 16, 18)])
    return dict(wall=R.choice(['plasma', 'rings', 'grad', 'stars']), acc=mixc(bg_, pal_[R.randrange(4)], .28), pal=pal_, segs=segs, bg=bg_, punch=R.choice([0.015, 0.03]), scan=R.random() < 0.5, chroma=R.choice([0, 2]))
PLN = [('VOCAL', 'Vocals'), ('DRUMS', 'Drums'), ('INSTRUMENTS', 'Other'), ('MELODY + HATS  (MIDI)', None) if HAS_ARR else ('BASS', 'Bass')]
def prod_frame(f, feat, plan, ctx, rng):
    bands, low = feat; T = T0 + f / FPS; beat = t2b(T); k = line_at(T); si = seg_at(plan, T); st, (foc, ppb), kk, ov = plan['segs'][si]
    if ctx.get('si') != si: ctx['old'] = ctx.get('clean'); ctx['si'] = si
    if foc == 3 and T < MEL_T: foc = 0
    im = Image.fromarray(make_bg(plan['wall'], T, plan['bg'], plan['acc'])); d = ImageDraw.Draw(im)
    sub = ('%s - %s   %d BPM   %s' % (SONG['artist'], SONG['title'], round(60 / SPB), SONG.get('key', ''))).rstrip(); f2 = F(INTER_SB, 32); w = d.textlength(sub, font=f2); d.text(((W - w) / 2, 150), sub, font=f2, fill=(150, 160, 175))
    total = 860; hs = [total * (0.55 if i == foc else 0.15) for i in range(4)] if foc is not None else [total / 4] * 4
    ph = 330; x_of = lambda b: ph + (b - beat) * ppb; y = 540; vis = W / ppb
    for li, (label, stem) in enumerate(PLN):
        h = int(hs[li]); col = tuple(plan['pal'][li]); d.text((40, y), label, font=F(MONO, 28), fill=col)
        if stem is None:
            info = 'enters in %.1f s' % (MEL_T - T) if T < MEL_T else 'real notes from the project file'
            tw = d.textlength(info, font=F(MONO, 28)); d.text((W - 40 - tw, y), info, font=F(MONO, 28), fill=(150, 160, 175))
        py0 = y + 40; py1 = py0 + h; d.rectangle([0, py0, W, py1], fill=(22, 25, 31))
        for b in range(int(beat - ph / ppb) - 1, int(beat + vis) + 1):
            x = x_of(b)
            if 0 <= x <= W and b % 4 == 0: d.line([x, py0, x, py1], fill=(46, 52, 62), width=2)
        if stem:
            mid = (py0 + py1) / 2
            for x in range(0, W, 4):
                v = ev(stem, b2t(beat + (x - ph) / ppb)) * (h * 0.46); d.line([x, mid - v, x, mid + v], fill=col if x > ph else tuple(int(c * .45) for c in col), width=3)
            if li == 0 and foc == 0:
                fw = F(INTER_XB, 44); lastx = {}
                for e, ws in LINES:
                    for wi, (wd, s0) in enumerate(ws):
                        x = x_of(t2b(s0))
                        if x < lastx.get(wi % 3, -1e9): continue      # fast lines: skip a word instead of printing over the last
                        if -200 < x < W:
                            lastx[wi % 3] = x + d.textlength(wd, font=fw) + 14
                            nxt = ws[wi + 1][1] if wi + 1 < len(ws) else e
                            d.text((x, py0 + 4 + (wi % 3) * ((h - 60) / 2)), wd, font=fw, fill=(255, 255, 255) if s0 <= T < nxt else ((110, 115, 125) if s0 < T else (225, 225, 230)), stroke_width=4, stroke_fill=(22, 25, 31))
        else:
            rows = [(i, kx) for i in SONG['melody_tracks'] for kx in sorted({n[2] for n in TR[i]['notes']}, reverse=True)] + [(i, kx) for i in SONG['hat_tracks'] for kx in sorted({n[2] for n in TR[i]['notes']}, reverse=True)]
            kh = (h - 10) / len(rows)
            for r, (ti, key) in enumerate(rows):
                c2 = col if ti in SONG['melody_tracks'] else tuple(plan['pal'][1])
                for a_, du, kx, v in TR[ti]['notes']:
                    if kx != key or a_ + du < beat - ph / ppb - 1 or a_ > beat + vis: continue
                    xa, xb = x_of(a_), x_of(a_ + max(du, .12)) - 3; ya = py0 + 5 + r * kh
                    d.rectangle([xa, ya + 1, max(xa + 3, xb), ya + kh - 2], fill=(255, 255, 255) if a_ <= beat < a_ + max(du, .2) else (c2 if a_ > beat else tuple(int(c * .45) for c in c2)))
        y = py1 + 22
    d.line([ph, 580, ph, y - 22], fill=(255, 255, 255), width=3)
    for hT in HITS:                                   # hit markers riding the timeline
        x = x_of(t2b(hT))
        if 0 < x < W: d.polygon([(x - 12, 566), (x + 12, 566), (x, 584)], fill=(255, 255, 255) if abs(hT - T) < 0.08 else (120, 126, 140))
    fi = min(f, bands.shape[1] - 1); bw = (W - 80) / bands.shape[0]
    for b in range(bands.shape[0]):
        v = float(bands[b, max(0, fi - 1):fi + 1].mean()); d.rectangle([40 + b * bw, 1800 - int(v * 90), 40 + (b + 1) * bw - 5, 1800], fill=(70, 80, 96))
    if 'stamp' in ov and k is not None: overlays_pil(im, ImageDraw.Draw(im), ['stamp'], k, T, f, bands)
    d = ImageDraw.Draw(im)
    a = fx(np.asarray(im), T, f, plan, [o for o in ov if o != 'stamp'], st, (0, 580, W, 1560), ctx, rng)
    if plan.get('faces'): a = facecam(a, T, bands, beat, ctx)
    return caption(a, k, T, 215, 76, 1000) if k is not None else a

plan = plan_band() if mode == 'band' else plan_prod()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import hook as _hook
plan['hook'] = _hook.pick(mode, seed)                       # the line shown for the first two seconds ('' = none)
plan['hook_angle'] = _hook.angle(mode, plan['hook']); plan['hook_mode'] = _hook.mode(mode, seed)   # flash: first two seconds; hold: the whole video
import faces as _faces                                      # Dylan and Nick reacting, line by line, on some videos
_fv = os.environ.get('CQ_FACES', '').lower()
plan['faces'] = _faces.available() and (_fv in ('1', 'true', 'yes') or (_fv not in ('0', 'false', 'no') and random.Random(seed * 37 + 5).random() < 0.4))
if plan['faces']:
    plan['face_block'] = random.Random(seed * 41).choice([8, 10, 12])        # how chunky the pixels are
    if mode == 'band':                                       # most lyric lines become a reaction window; the rest stay desktop scenes
        fr_ = random.Random(seed * 43)
        for sg in plan['segs']:
            if sg[2] is not None and fr_.random() < 0.75: sg[1] = 'face+' + sg[1]
FACE_WHO = _faces.plan(LINES, seed) if plan['faces'] else []
wav = out[:-4] + '.wav'; dur = cut(MASTER, T0, T1, wav); feat = features(wav); n = int(round(dur * FPS)); rng = random.Random(seed); ctx = {}
json.dump(json.loads(json.dumps(dict(mode=mode, seed=seed, song=SONG['slug'], window=[T0, T1], plan=plan)).replace(SONG_DIR + '/', '')), open(out[:-4] + '.json', 'w'), indent=1)
fr0 = (lambda f: band_frame(f, feat, plan, ctx, rng)) if mode == 'band' else (lambda f: prod_frame(f, feat, plan, ctx, rng))
fr = ((lambda f: _hook.draw_hold(np.asarray(fr0(f)), plan['hook'], f / FPS, _hook.HOLD_Y[mode])) if plan['hook_mode'] == 'hold' else
      (lambda f: _hook.draw(np.asarray(fr0(f)), plan['hook'], f / FPS, y=0.43)))      # flash sits mid-screen: both styles keep titles and lyrics at the top
if '--frames' in sys.argv:
    fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
    s = Image.new('RGB', (324 * len(fs), 576))
    for i, f in enumerate(fs):
        fr(max(0, f - 1)); s.paste(Image.fromarray(fr(min(f, n - 1))).resize((324, 576)), (324 * i, 0))
    s.save(out[:-4] + '_sheet.png'); print('frames', n, [(x[1], x[3]) for x in plan['segs']])
else:
    tmp = out[:-4] + '.tmp.mp4'
    p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', wav,
                          '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'), *(['-maxrate', os.environ['CQ_MAXRATE'], '-bufsize', os.environ.get('CQ_BUFSIZE', '6M')] if os.environ.get('CQ_MAXRATE') else []), '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    for f in range(n): p.stdin.write(fr(f).tobytes())
    p.stdin.close(); assert p.wait() == 0; os.replace(tmp, out); print('done', n, round(dur, 2))
