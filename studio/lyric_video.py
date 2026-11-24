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
CAPTION_FONTS = {'inter': INTER_XB, 'anton': _font('Anton-Regular.ttf', 'Inter-ExtraBold.otf', 'Montserrat-ExtraBold.ttf'), 'montserrat': _font('Montserrat-ExtraBold.ttf')}
CAP = INTER_XB                      # the lyric's typeface: a knob, set once the plan is made
CHROME = 'win95'                    # the window style the band desktop is drawn in: a knob too
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import knobs as K


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
if not HAS_ARR and len(SONG.get('beat_times') or []) > 2:      # the beats measured from the drums (studio/beatmap.py), so the punches follow the band
    _BT = np.asarray(SONG['beat_times'], float); _BI = np.arange(len(_BT), dtype=float)
    b2t = lambda b: float(np.interp(b, _BI, _BT, left=_BT[0] + (b - 0) * SPB, right=_BT[-1] + (b - _BI[-1]) * SPB))
    t2b = lambda t: float(np.interp(t, _BT, _BI, left=(t - _BT[0]) / SPB, right=_BI[-1] + (t - _BT[-1]) / SPB))


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
    if CHROME == 'xp':                                            # Luna blue: rounded frame, gradient title bar, red close box
        d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=(0, 84, 227) if active else (122, 150, 223))
        d.rectangle([x0 + 4, y0 + 30, x1 - 4, y0 + 54], fill=(0, 72, 200) if active else (110, 136, 210))
        d.rectangle([x0 + 7, y0 + 56, x1 - 7, y1 - 7], fill=(236, 233, 216))
        d.text((x0 + 22, y0 + 13), title, font=F(SANS_B, 30), fill=(10, 24, 80)); d.text((x0 + 20, y0 + 11), title, font=F(SANS_B, 30), fill=(255, 255, 255))
        bx = x1 - 52; d.rounded_rectangle([bx, y0 + 11, bx + 38, y0 + 47], radius=6, fill=(226, 80, 40), outline=(255, 255, 255), width=2)
        d.line([bx + 11, y0 + 20, bx + 27, y0 + 38], fill=(255, 255, 255), width=4); d.line([bx + 27, y0 + 20, bx + 11, y0 + 38], fill=(255, 255, 255), width=4)
        return
    if CHROME == 'mac':                                           # platinum: striped title bar, centred title, close box on the left
        d.rectangle([x0, y0, x1, y1], fill=(221, 221, 221), outline=(0, 0, 0), width=3)
        d.rectangle([x0 + 3, y0 + 3, x1 - 3, y0 + 48], fill=(204, 204, 204)); d.line([x0, y0 + 50, x1, y0 + 50], fill=(0, 0, 0), width=3)
        f = F(SANS_B, 28); tw = d.textlength(title, font=f); cx = (x0 + x1) / 2
        if active:
            for yy in range(y0 + 12, y0 + 42, 5):
                d.line([x0 + 60, yy, cx - tw / 2 - 16, yy], fill=(120, 120, 120), width=2); d.line([cx + tw / 2 + 16, yy, x1 - 14, yy], fill=(120, 120, 120), width=2)
        d.rectangle([x0 + 16, y0 + 12, x0 + 44, y0 + 40], fill=(221, 221, 221), outline=(0, 0, 0), width=2)
        d.text((cx - tw / 2, y0 + 10), title, font=f, fill=(0, 0, 0)); return
    d.rectangle([x0, y0, x1, y1], fill=(192, 192, 192))
    d.line([x0, y0, x1, y0], fill=(255, 255, 255), width=3); d.line([x0, y0, x0, y1], fill=(255, 255, 255), width=3)
    d.line([x0, y1, x1, y1], fill=(64, 64, 64), width=3); d.line([x1, y0, x1, y1], fill=(64, 64, 64), width=3)
    d.rectangle([x0 + 6, y0 + 6, x1 - 6, y0 + 52], fill=(0, 0, 128) if active else (128, 128, 128))
    d.text((x0 + 18, y0 + 12), title, font=F(SANS_B, 30), fill=(255, 255, 255))
    bx = x1 - 50
    d.rectangle([bx, y0 + 12, bx + 36, y0 + 46], fill=(192, 192, 192), outline=(0, 0, 0))
    d.line([bx + 9, y0 + 20, bx + 27, y0 + 38], fill=(0, 0, 0), width=3); d.line([bx + 27, y0 + 20, bx + 9, y0 + 38], fill=(0, 0, 0), width=3)


def inset(d, x0, y0, x1, y1, fill):
    if CHROME in ('xp', 'mac'):
        d.rectangle([x0, y0, x1, y1], fill=fill, outline=(127, 157, 185) if CHROME == 'xp' else (110, 110, 110), width=3); return
    d.rectangle([x0, y0, x1, y1], fill=fill)
    d.line([x0, y0, x1, y0], fill=(64, 64, 64), width=3); d.line([x0, y0, x0, y1], fill=(64, 64, 64), width=3)
    d.line([x0, y1, x1, y1], fill=(255, 255, 255), width=3); d.line([x1, y0, x1, y1], fill=(255, 255, 255), width=3)


def button(d, x0, y0, x1, y1, text):
    if CHROME in ('xp', 'mac'):
        d.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=(244, 243, 238) if CHROME == 'xp' else (238, 238, 238), outline=(0, 60, 116) if CHROME == 'xp' else (0, 0, 0), width=3)
        f = F(SANS_B, 30); w = d.textlength(text, font=f); d.text(((x0 + x1 - w) / 2, y0 + 10), text, font=f, fill=(0, 0, 0)); return
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
    ws = LINES[k][1]; allw = [w for w, _ in ws]; f = F(CAP, size)
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
_KEEP = [i for i, L in enumerate(LINES) if L[0] > T0 - 0.2 and L[1][0][1] < T1] or [0]
LINE0 = _KEEP[0]                    # the song's number for this clip's first line: pictures are filed by the song's numbers
LINES = [LINES[i] for i in _KEEP]
has = lambda k, s: any(s in w.lower() for w, _ in LINES[k][1])
# strong drum hits (for flashes)
dy, dsr = sf.read(stem_path('Drums'), always_2d=True, dtype='float32'); dy = dy.mean(1)
oe = librosa.onset.onset_strength(y=dy, sr=dsr, hop_length=256); pk = librosa.util.peak_pick(oe, pre_max=6, post_max=6, pre_avg=20, post_avg=20, delta=np.percentile(oe, 97) * 0.5, wait=int(0.6 * dsr / 256))
HITS = STEMS_START + pk * 256 / dsr

_yy, _xx = np.mgrid[0:240, 0:135].astype(np.float32); _RS = np.random.RandomState(5); _ST = _RS.rand(260, 3)
def make_bg(kind, T, base, acc):
    d = ev('Drums', T)
    if kind in ('clouds', 'hills'):                                # a sky, drawn rather than tinted: pixel clouds drifting
        sky = np.stack([np.interp(_yy, [0, 240], c) for c in ((40, 150), (100, 200), (215, 250))], -1)
        cl = np.sin(_xx * .07 + T * .25) + np.sin(_yy * .11 + _xx * .03) + np.sin((_xx - _yy) * .05 - T * .12) + .6 * np.sin(_xx * .19 - _yy * .07 + T * .3)
        img = np.where((cl > (1.5 if kind == 'clouds' else 2.0))[..., None], [250, 250, 255], sky)
        if kind == 'hills':
            hy = 150 + 16 * np.sin(_xx * .028 + .6) - 9 * np.sin(_xx * .013 + 2) - 6 * d
            g = np.clip((_yy - hy) / 90, 0, 1)[..., None]
            img = np.where((_yy > hy)[..., None], np.array([70, 170, 50]) * (1 - g) + np.array([30, 110, 30]) * g, img)
        img = img * (1 + .12 * d)
        return cv2.resize(np.clip(img, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST)
    if kind == 'bars':                                              # an equaliser behind everything
        lv = [ev(s_, T - .02 * k) for k, s_ in enumerate(['Bass', 'Drums', 'Other', 'Vocals'] * 4)]
        col = np.clip((_xx // 9).astype(int), 0, 15); hgt = np.array(lv)[col] * 200 + 12
        v = ((240 - _yy) < hgt) * (.35 + .5 * ((_yy // 4) % 2)) * ((_xx % 9) < 7)
    elif kind == 'plasma':
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
WALLS = ['plasma', 'tiles', 'rings', 'grad', 'stars', 'clouds', 'hills', 'bars']

MEDIA = os.environ.get('CQ_MEDIA', os.path.join(SONG_DIR, 'media')); PIC_STYLES = ['lowres', 'gif', 'jpeg', 'webcam', 'crt']
try:
    import photos as _photos; _SONG_PICS = _photos.song_pictures(os.path.basename(os.path.normpath(SONG_DIR)))   # pictures.json searches, resolved
except Exception as exc:
    print('no song pictures: %r' % exc); _SONG_PICS = {}
def media_for(k):
    k += LINE0                       # k counts this clip's lines; the pictures are filed under the song's line numbers
    d = os.path.join(MEDIA, '%02d' % k); own = sorted(os.path.join(d, x) for x in os.listdir(d) if x.lower().endswith(('.jpg', '.jpeg', '.png', '.webm', '.ogv', '.mp4'))) if os.path.isdir(d) else []
    return own + _SONG_PICS.get(k, [])
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
    themes = [((0, 128, 128), 'teal'), ((58, 110, 165), 'blue'), ((85, 60, 130), 'purple'), ((20, 20, 24), 'black'), ((0, 110, 70), 'green'),
              ((160, 60, 110), 'pink'), ((200, 110, 40), 'orange'), ((110, 115, 125), 'silver')]
    theme = dict((n, c) for c, n in themes); tn = K.pick('theme', [n for _, n in themes], R); theme = (theme[tn], tn); segs = []; prev = [None]
    pic_p = float(os.environ['CQ_PIC_P']) if os.environ.get('CQ_PIC_P') else K.pick('pictures', [0.35, 0.6, 0.85], R)   # how often a line with a picture shows it
    def pick(k, st):
        pool = ['notepad', 'cmd', 'paint', 'paint', 'wave', 'player', 'arr']
        if HAS_ARR and st >= MEL_T + 0.3: pool += ['roll_mel'] * 2
        if HAS_ARR and st >= HAT_T + 0.3: pool += ['roll_hat'] * 2
        if has(k, 'problem'): pool += ['dialogs'] * 4 + ['flood'] * 4
        if has(k, 'messages'): pool += ['messages'] * 8
        if has(k, '4:20'): pool += ['clock'] * 8
        if has(k, 'confess'): pool += ['cmd'] * 4
        ms = media_for(k)
        if ms and R.random() < pic_p and not str(prev[0]).startswith('pic'): c = 'pic|%s|%s' % (R.choice(ms), R.choice(PIC_STYLES)); prev[0] = c; return c
        c = R.choice([p for p in pool if p != prev[0]]); prev[0] = c; return c
    for k, (e, ws) in enumerate(LINES):
        st = ws[0][1]
        if st > T1: break
        if k > 0 and st - LINES[k - 1][0] > 1.0:
            g = R.choice([x for x in ['arr', 'player', 'wave'] if x != prev[0]]); segs.append([LINES[k - 1][0], g, None, pick_ov()]); prev[0] = g
        if e - st > 2.3 and len(ws) >= 6 and not has(k, 'messages'):
            m = ws[len(ws) // 2][1]; segs += [[st, pick(k, st), k, pick_ov()], [m, pick(k, m), k, pick_ov()]]
        else: segs.append([st, pick(k, st), k, pick_ov()])
    return dict(wall=K.pick('wall', WALLS, R), acc=mixc(theme[0], R.choice(PAL), R.choice([.35, .5])) if theme[1] != 'black' else mixc((20, 20, 24), R.choice(PAL), .6), theme=theme[1], bg=theme[0], segs=segs,
                punch=K.pick('punch', [0.02, 0.035, 0.05], R), scan=K.flag('scan', 0.7, R), chroma=K.pick('chroma', [0, 2, 4], R),
                chrome=K.pick('chrome', ['win95', 'win95', 'xp', 'mac'], R), caption=K.pick('caption', ['inter', 'inter', 'anton', 'montserrat'], R))

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
    return _faces.paste_sprite(np.ascontiguousarray(a), name, cx, bottom, height, since, T, beat % 1, block=plan.get('face_block', 6))
def facecam(a, T, bands, beat, ctx):
    """In the producer view the one whose line it is stands over the lower lanes."""
    k = line_at(T)
    if k is None: k = ctx.get('cam_k')
    if k is None: return a
    ctx['cam_k'] = k
    return sprite_for(a, k, T, bands, beat, ctx, bottom=1545, height=640)

def taskbar(d, clock):
    if CHROME == 'xp':
        for yy in range(H - 84, H): d.line([0, yy, W, yy], fill=(int(36 + 30 * (yy - H + 84) / 84 * 0), int(94 - 20 * (yy - H + 84) / 84), int(220 - 30 * (yy - H + 84) / 84)))
        d.rounded_rectangle([0, H - 80, 220, H - 4], radius=22, fill=(58, 152, 58)); d.text((46, H - 70), 'start', font=F(SANS_B, 44), fill=(255, 255, 255))
        d.rectangle([W - 230, H - 84, W, H], fill=(16, 140, 233)); d.text((W - 180, H - 62), clock, font=F(SANS, 32), fill=(255, 255, 255)); return
    if CHROME == 'mac':                                          # a menu bar along the top instead of a taskbar
        d.rectangle([0, 0, W, 58], fill=(238, 238, 238)); d.line([0, 58, W, 58], fill=(0, 0, 0), width=3)
        x = 30
        for item in ('✱', 'File', 'Edit', 'View', 'Special'):
            d.text((x, 12), item, font=F(SANS_B if item != '✱' else SANS, 30), fill=(0, 0, 0)); x += d.textlength(item, font=F(SANS_B, 30)) + 36
        d.text((W - 170, 12), clock, font=F(SANS, 30), fill=(0, 0, 0)); return
    d.rectangle([0, H - 84, W, H], fill=(192, 192, 192)); d.line([0, H - 84, W, H - 84], fill=(255, 255, 255), width=3)
    button(d, 10, H - 72, 190, H - 14, 'Start'); inset(d, W - 220, H - 72, W - 12, H - 14, (192, 192, 192))
    d.text((W - 190, H - 60), clock, font=F(SANS, 30), fill=(0, 0, 0))

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
    taskbar(d, '4:20 PM' if any('4:20' in w and t < T for e, ws in LINES for w, t in ws) else '4:19 PM')
    a = fx(np.asarray(im), T, f, plan, ov, st, STAGE, ctx, rng)
    if face and k is not None: a = sprite_for(a, k, T, bands, beat, ctx, bottom=1330, height=860)
    # The lyric goes on last, over every overlay and effect, so nothing can cover it.
    kl = line_at(T)
    return caption(a, kl, T, 1340, 64, 980) if kl is not None else a

def plan_prod():
    # What the video does with the song (2026-11-24). 'scroll' is the old stems view: the master under four scrolling
    # waveforms, nothing changing in 20 s (median 22 views). 'build' and 'strip' make the stems mean something: the
    # audio itself is rebuilt from them, one part alone and then the rest coming in on the bar (studio/README: stems/).
    # 'scroll' is kept off the menu (the captions now promise a part heard on its own); CQ_STORY=scroll still draws it.
    story = K.pick('story', ['build', 'strip'], R)
    if os.environ.get('CQ_STORY') in ('build', 'strip', 'scroll'): story = os.environ['CQ_STORY']
    if story != 'scroll': return plan_story(story)
    pals =[[(255, 190, 110), (255, 90, 110), (150, 160, 255), (120, 220, 255)], [(255, 255, 255), (255, 210, 60), (90, 220, 160), (255, 120, 200)], [(120, 255, 170), (255, 150, 80), (110, 190, 255), (240, 240, 120)]]
    segs = []; prev = -1
    for k, (e, ws) in enumerate(LINES):
        if ws[0][1] > T1: break
        c = R.choice([x for x in (None, 0, 0, 1, 2, 3) if x != prev]); prev = c
        segs.append([ws[0][1], [c, R.choice([84, 110, 140])], k, [x for x in pick_ov() if x in ('track', 'invert', 'stamp')] or ['stamp']])
    pal_ = pals[K.pick('colours', [0, 1, 2], R)]; bg_ = R.choice([(11, 13, 16), (16, 12, 22), (8, 16, 18)])
    pic_p = float(os.environ['CQ_PIC_P']) if os.environ.get('CQ_PIC_P') else K.pick('pictures', [0.0, 0.35, 0.6], R)
    pics = {}
    for k in range(len(LINES)):                                      # a line with a picture may show it as a card over the stems
        ms = media_for(k)
        if ms and R.random() < pic_p and (k - 1) not in pics: pics[k] = (R.choice(ms), R.choice(PIC_STYLES))
    return dict(wall=K.pick('wall', ['plasma', 'rings', 'grad', 'stars', 'bars', 'tiles'], R), acc=mixc(bg_, pal_[R.randrange(4)], .28), pal=pal_, segs=segs, bg=bg_,
                punch=K.pick('punch', [0.015, 0.03], R), scan=K.flag('scan', 0.5, R), chroma=K.pick('chroma', [0, 2], R),
                layout=K.pick('layout', ['lanes', 'lanes', 'mixer'], R), caption=K.pick('caption', ['inter', 'inter', 'anton', 'montserrat'], R), pics={str(k): v for k, v in pics.items()})
PLN = [('VOCAL', 'Vocals'), ('DRUMS', 'Drums'), ('INSTRUMENTS', 'Other'), ('MELODY + HATS  (MIDI)', None) if HAS_ARR else ('BASS', 'Bass')]
def pic_card(a, plan, k, T):
    """The line's picture as a card over the middle of the frame, sliding in as the line starts and out as it ends."""
    got = (plan.get('pics') or {}).get(str(k)) if k is not None else None
    if not got: return a
    path, sty = got; st, en = LINES[k][1][0][1], LINES[k][0]; t = T - st
    a_in = min(1.0, max(0.0, t / 0.18)); a_out = min(1.0, max(0.0, (en + 0.25 - T) / 0.18)); vis = min(a_in, a_out)
    if vis <= 0: return a
    cw, ch = 760, 600; x0 = (W - cw) // 2; y0 = 700 + int((1 - vis) * 60)
    im = Image.fromarray(a); d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0 - 10, y0 - 10, x0 + cw + 10, y0 + ch + 10], radius=22, fill=(12, 14, 18), outline=tuple(plan['pal'][k % 4]), width=6)
    pic = digitize(media_frame(path, t), sty, t, cw, ch, (10, 10, 30), (255, 255, 255))
    if vis < 1: pic = Image.blend(Image.new('RGB', pic.size, (12, 14, 18)), pic, vis)
    im.paste(pic, (x0, y0)); return np.asarray(im)

def mixer_frame(f, feat, plan, ctx, rng):
    """The song as a mixing desk: a channel strip per stem, its meter and fader riding the real level."""
    bands, low = feat; T = T0 + f / FPS; beat = t2b(T); k = line_at(T); si = seg_at(plan, T); st, (foc, ppb), kk, ov = plan['segs'][si]
    if ctx.get('si') != si: ctx['old'] = ctx.get('clean'); ctx['si'] = si
    im = Image.fromarray(make_bg(plan['wall'], T, plan['bg'], plan['acc'])); d = ImageDraw.Draw(im)
    sub = ('%s - %s   %d BPM   %s' % (SONG['artist'], SONG['title'], round(60 / SPB), SONG.get('key', ''))).rstrip(); f2 = F(INTER_SB, 32); w = d.textlength(sub, font=f2); d.text(((W - w) / 2, 470), sub, font=f2, fill=(150, 160, 175))
    strips = [('VOCAL', 'Vocals'), ('DRUMS', 'Drums'), ('INSTR', 'Other'), ('BASS', 'Bass')]
    x0, y0, y1 = 40, 600, 1560; sw = (W - 80) / 4; fade = ctx.setdefault('fader', [0.5] * 4); peak = ctx.setdefault('peak', [0.0] * 4)
    bar = int(beat // 4) + 1; d.text((40, 548), 'BAR %d.%d' % (bar, int(beat % 4) + 1), font=F(MONO, 30), fill=(200, 205, 215))
    for i, (label, stem) in enumerate(strips):
        lv = ev(stem, T); fade[i] += (lv - fade[i]) * 0.15; peak[i] = max(lv, peak[i] - 0.012)
        sx = x0 + i * sw; col = tuple(plan['pal'][i]); on = foc == i
        d.rounded_rectangle([sx + 6, y0, sx + sw - 6, y1], radius=18, fill=(22, 25, 31), outline=col if on else (46, 52, 62), width=5 if on else 3)
        f3 = F(MONO, 32); tw = d.textlength(label, font=f3); d.text((sx + (sw - tw) / 2, y0 + 20), label, font=f3, fill=(255, 255, 255) if on else col)
        kx, ky = sx + sw / 2, y0 + 120; d.ellipse([kx - 40, ky - 40, kx + 40, ky + 40], outline=col, width=5)
        a_ = -2.4 + 4.8 * (0.5 + 0.45 * np.sin(T * 0.7 + i * 1.3)); d.line([kx, ky, kx + 34 * np.sin(a_), ky - 34 * np.cos(a_)], fill=(255, 255, 255), width=5)
        my0, my1 = y0 + 200, y1 - 160; segs_n = 26; seg_h = (my1 - my0) / segs_n
        for sgi in range(segs_n):                                     # the meter: green, then yellow, then red
            frac = (sgi + 1) / segs_n; lit = frac <= min(1.0, lv); yy = my1 - (sgi + 1) * seg_h
            c = (90, 220, 120) if frac < .65 else (250, 210, 70) if frac < .85 else (255, 90, 80)
            d.rectangle([sx + 26, yy + 3, sx + 26 + sw * .28, yy + seg_h - 3], fill=c if lit else tuple(int(v * .18) for v in c))
        py_ = my1 - min(1.0, peak[i]) * (my1 - my0); d.rectangle([sx + 26, py_ - 4, sx + 26 + sw * .28, py_], fill=(255, 255, 255))
        tx = sx + sw * .66; d.rectangle([tx - 5, my0, tx + 5, my1], fill=(8, 9, 12))
        fy = my1 - min(1.0, fade[i]) * (my1 - my0)
        d.rounded_rectangle([tx - 42, fy - 26, tx + 42, fy + 26], radius=8, fill=(200, 204, 212), outline=(255, 255, 255) if on else (90, 95, 105), width=3); d.line([tx - 32, fy, tx + 32, fy], fill=(20, 20, 20), width=4)
        db = 20 * np.log10(max(lv, 1e-3)); val = '%+.1f' % max(-60.0, db); tw = d.textlength(val, font=f3); d.text((sx + (sw - tw) / 2, y1 - 120), val, font=f3, fill=(200, 205, 215))
        hist = ctx.setdefault('hist%d' % i, []); hist.append(lv); del hist[:-40]
        for j, hv in enumerate(hist): d.line([sx + 26 + j * (sw - 52) / 40, y1 - 40 - hv * 40, sx + 26 + j * (sw - 52) / 40, y1 - 40 + hv * 40], fill=col, width=3)
    fi = min(f, bands.shape[1] - 1); bw = (W - 80) / bands.shape[0]
    for b in range(bands.shape[0]):
        v = float(bands[b, max(0, fi - 1):fi + 1].mean()); d.rectangle([40 + b * bw, 1800 - int(v * 90), 40 + (b + 1) * bw - 5, 1800], fill=(70, 80, 96))
    if 'stamp' in ov and k is not None: overlays_pil(im, ImageDraw.Draw(im), ['stamp'], k, T, f, bands)
    a = fx(np.asarray(im), T, f, plan, [o for o in ov if o not in ('stamp', 'track')], st, (0, 580, W, 1560), ctx, rng)
    a = pic_card(a, plan, k, T)
    if plan.get('faces'): a = facecam(a, T, bands, beat, ctx)
    return caption(a, k, T, 262, 70, 1000) if k is not None else a

def prod_frame(f, feat, plan, ctx, rng):
    if plan.get('layout') == 'mixer': return mixer_frame(f, feat, plan, ctx, rng)
    bands, low = feat; T = T0 + f / FPS; beat = t2b(T); k = line_at(T); si = seg_at(plan, T); st, (foc, ppb), kk, ov = plan['segs'][si]
    if ctx.get('si') != si: ctx['old'] = ctx.get('clean'); ctx['si'] = si
    if foc == 3 and T < MEL_T: foc = 0
    im = Image.fromarray(make_bg(plan['wall'], T, plan['bg'], plan['acc'])); d = ImageDraw.Draw(im)
    sub = ('%s - %s   %d BPM   %s' % (SONG['artist'], SONG['title'], round(60 / SPB), SONG.get('key', ''))).rstrip(); f2 = F(INTER_SB, 32); w = d.textlength(sub, font=f2); d.text(((W - w) / 2, 470), sub, font=f2, fill=(150, 160, 175))
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
    a = pic_card(a, plan, k, T)
    if plan.get('faces'): a = facecam(a, T, bands, beat, ctx)
    return caption(a, k, T, 262, 70, 1000) if k is not None else a

# ------------------------------------------------------------ producer stories: build / strip
# One part of the song alone, then the rest coming in on the bar ('build'), or the full mix, then one part alone, then
# everything back ('strip'). The sound is rebuilt from the stems to match what is on screen, so the lanes are not
# decoration: a lane that is lit is what you hear. The full mix is always the master itself.
ST_NAME = {'Vocals': 'VOCAL', 'Drums': 'DRUMS', 'Bass': 'BASS', 'Other': 'INSTRUMENTS'}
ST_ORDER = ['Vocals', 'Drums', 'Bass', 'Other']
ALL = frozenset(ST_ORDER)
# The line over the first seconds. Every one is true of the video it is drawn on: it is chosen after the plan, from
# what the plan does ({s} = seconds until the full mix, computed). Statements, no asks.
STORY_LINES = {
    ('build', 'Vocals'): ["the vocal on its own first. then the whole song", "just the vocal. the band comes in one by one",
                          "acapella to full song in {s} seconds", "how this song stacks up, from the vocal"],
    ('build', 'Drums'): ["drums first. then the rest of the song", "built up from the drums, one part at a time",
                         "drums to full song in {s} seconds", "the beat on its own, then everything"],
    ('strip', 'Vocals'): ["full mix. then just the vocal", "now the same bars with only the vocal",
                          "what the vocal sounds like with nothing under it", "the song, then the vocal alone"],
    ('strip', 'Drums'): ["full mix. then just the drums", "the same bars with only the drums",
                         "the drum track on its own, then back in", "the song, then the drums alone"],
}

def _seg_energy(stem, a, b):
    if stem not in ENV: return 0.0
    e = ENV[stem]; i, j = int((a - STEMS_START) * 200), int((b - STEMS_START) * 200)
    return float(e[max(0, i):max(i + 1, j)].mean()) if j > 0 else 0.0

def plan_story(story):
    pals = [[(255, 196, 92), (255, 92, 120), (110, 170, 255), (90, 225, 170)],          # amber, coral, blue, mint
            [(250, 250, 250), (255, 210, 60), (90, 220, 160), (255, 120, 200)],
            [(150, 255, 180), (255, 150, 80), (120, 190, 255), (240, 230, 120)]]
    pal_ = pals[K.pick('colours', [0, 1, 2], R)]
    first = K.pick('first', ['Vocals', 'Drums'], R)
    L = T1 - T0; b0 = t2b(T0); bar = 4 * SPB
    sol, add = (8, 4) if bar < 2.6 else (4, 4)                     # beats: about four seconds alone, then a bar per part
    steps = 3 if story == 'build' else 1
    while (sol + add * (steps - 1)) * SPB > 0.55 * L and sol > 2: sol //= 2; add = max(2, add // 2)
    # the part has to be playing in that stretch: a solo of a silent stem is an empty video
    other = 'Drums' if first == 'Vocals' else 'Vocals'
    if _seg_energy(first, T0, b2t(b0 + sol)) < 0.12 and _seg_energy(other, T0, b2t(b0 + sol)) >= 0.12: first = other
    if story == 'build':
        rest = ['Drums', 'Bass'] if first == 'Vocals' else ['Bass', 'Other']
        sets = [{first}, {first, rest[0]}, {first, rest[0], rest[1]}, ALL]
        labels = [ST_NAME[first] + ' ONLY', '+ ' + ST_NAME[rest[0]], '+ ' + ST_NAME[rest[1]], 'FULL MIX']
        at = [b0, b0 + sol, b0 + sol + add, b0 + sol + 2 * add]
    else:
        lead_in = sol
        sets = [ALL, {first}, ALL]; labels = ['FULL MIX', ST_NAME[first] + ' ONLY', 'ALL BACK IN']
        at = [b0, b0 + lead_in, b0 + lead_in + sol]
    steps_ = [[round(b2t(b), 3), sorted(s), lab] for b, s, lab in zip(at, sets, labels) if b2t(b) < T1 - 0.5]
    drop = next((t for t, s, _ in steps_[1:] if len(s) == 4), None)
    rl = random.Random(seed * 613 + 1); line = rl.choice(STORY_LINES[(story, first)])
    if '{s}' in line:
        line = line.format(s=int(round(drop - T0))) if drop and drop - T0 >= 2 else rl.choice([l for l in STORY_LINES[(story, first)] if '{s}' not in l])
    return dict(story=story, first=first, steps=steps_, drop=drop, line=line, pal=pal_, bg=(12, 13, 17),
                punch=K.pick('punch', [0.015, 0.03], R), caption=K.pick('caption', ['inter', 'inter', 'anton', 'montserrat'], R), segs=[[T0, [None, 110], 0, []]])

def story_step(plan, T):
    s = [x for x in plan['steps'] if x[0] <= T + 1e-3]
    return s[-1] if s else plan['steps'][0]

def story_audio(plan, wav):
    """Rewrites the cut clip so that each step plays only its stems: the master where everything plays, the sum of the
    stems elsewhere, with 12 ms ramps at the bar lines. A part alone is lifted (at most +6 dB) towards the full mix's level."""
    x, sr = sf.read(wav, always_2d=True, dtype='float32'); n = len(x); out = x.copy()
    stems = {}
    for nm in ST_ORDER:
        if not os.path.exists(stem_path(nm)): continue
        info = sf.info(stem_path(nm)); a = int((T0 - STEMS_START) * info.samplerate)
        y, ssr = sf.read(stem_path(nm), start=max(0, a), stop=max(0, a) + int((T1 - T0) * info.samplerate) + 2, always_2d=True, dtype='float32')
        if ssr != sr: y = librosa.resample(y.T, orig_sr=ssr, target_sr=sr).T
        if y.shape[1] != x.shape[1]: y = np.repeat(y.mean(1, keepdims=True), x.shape[1], 1)
        y = y[:n]; stems[nm] = np.pad(y, ((0, n - len(y)), (0, 0)))
    if not stems: return
    ramp = int(0.012 * sr); full_rms = float(np.sqrt(np.mean(x ** 2))) + 1e-9
    gain_full = np.zeros(n, np.float32); g = {nm: np.zeros(n, np.float32) for nm in stems}
    edges = [int((t - T0) * sr) for t, _, _ in plan['steps']] + [n]
    for (t, on, _), a, b in zip(plan['steps'], edges, edges[1:]):
        a, b = max(0, a), min(n, b)
        if b <= a: continue
        if len(on) == 4: gain_full[a:b] = 1
        else:
            mix = sum(stems[nm][a:b] for nm in on if nm in stems)
            lift = min(2.0, max(1.0, 0.6 * full_rms / (float(np.sqrt(np.mean(mix ** 2))) + 1e-9))) if len(on) == 1 else 1.0
            for nm in on:
                if nm in g: g[nm][a:b] = lift
    k = np.ones(ramp, np.float32) / ramp                                   # smooth every switch over the ramp
    sm = lambda v: np.convolve(v, k, mode='same')
    gf = sm(gain_full); out = x * gf[:, None]
    for nm in stems: out += stems[nm] * sm(g[nm])[:, None]
    fo = int(0.03 * sr); out[-fo:] *= np.linspace(1, 0, fo)[:, None]       # the loop restarts on a different part: no click
    fi = int(0.008 * sr); out[:fi] *= np.linspace(0, 1, fi)[:, None]
    peak = np.abs(out).max()
    if peak > 0.98: out *= 0.98 / peak
    sf.write(wav, out, sr)

def _label(d, text, cx, y, font, fill, bgc, pad=(30, 14), radius=22):
    tw = d.textlength(text, font=font); asc, desc = font.getmetrics(); h = asc + desc
    d.rounded_rectangle([cx - tw / 2 - pad[0], y - pad[1], cx + tw / 2 + pad[0], y + h + pad[1] * 0.6], radius=radius, fill=bgc)
    d.text((cx - tw / 2, y), text, font=font, fill=fill)

LANE_Y0, LANE_H, LANE_GAP, HEAD_W, PH_X = 712, 170, 14, 238, 560
def story_frame(f, feat, plan, ctx, rng):
    bands, low = feat; T = T0 + f / FPS; beat = t2b(T)
    st, on, lab = story_step(plan, T); on = set(on); since = T - st
    if lab == 'ALL BACK IN' and since > 8 * SPB: lab = 'FULL MIX'                  # after two bars it is just the song again
    pal = plan['pal']; bg = plan['bg']
    a = np.empty((H, W, 3), np.uint8); a[:] = bg
    grad = np.linspace(0, 1, H)[:, None, None]; a[:] = (np.array(bg) * (1 - grad * .4) + np.array((24, 26, 34)) * grad * .4).astype(np.uint8)
    im = Image.fromarray(a); d = ImageDraw.Draw(im)
    # the song: title and tempo, small, below Instagram's top bar
    sub = '%s  ·  %s  ·  %d BPM' % (SONG['title'], SONG['artist'].lower(), round(60 / SPB)); f2 = F(INTER_SB, 34)
    d.text(((W - d.textlength(sub, font=f2)) / 2, 268), sub, font=f2, fill=(150, 158, 172))
    # the line over the first seconds, then the lyric (only while the vocal is in)
    hook_on = plan.get('hook') and T - T0 < 3.2
    if hook_on:
        al = min(1.0, max(0.0, (3.2 - (T - T0)) / 0.3)); fh = F(INTER_XB, 62)                 # fully there in frame 0
        rows = wrap(d, plan['hook'].split(), fh, 800); y = 336
        for r in rows:
            s_ = ' '.join(r); tw = d.textlength(s_, font=fh)
            d.text(((W - tw) / 2, y), s_, font=fh, fill=tuple(int(bg[i] + (255 - bg[i]) * al) for i in range(3)))
            y += 74
    k = line_at(T)
    if k is not None and 'Vocals' in on and not hook_on:
        allw = [w for w, _ in LINES[k][1]]; size = next((z for z in (66, 56, 48) if len(wrap(d, allw, F(CAP, z), 800)) <= 2), 42)
        karaoke(d, k, T, 338 + (66 - size), size=size, maxw=800, outline=False)          # two rows at most: the label is below
    # what is playing now, in words: the label pops when it changes
    pop = 1 + 0.22 * np.exp(-since * 14); fb = F(INTER_XB, int(66 * pop)); full = len(on) == 4
    acc = (255, 255, 255) if full else tuple(pal[ST_ORDER.index(sorted(on, key=ST_ORDER.index)[-1])])
    _label(d, lab, W / 2, 566 - int(66 * (pop - 1) / 2), fb, (14, 15, 20), acc)
    # the arrangement: four tracks, header on the left, the clip with its waveform scrolling under the playhead
    ppb = 74; vis0 = beat - PH_X / ppb
    for i, nm in enumerate(ST_ORDER):
        y0 = LANE_Y0 + i * (LANE_H + LANE_GAP); y1 = y0 + LANE_H; live = nm in on; col = tuple(pal[i])
        d.rounded_rectangle([12, y0, HEAD_W, y1], radius=12, fill=(30, 32, 40))
        d.rectangle([12, y0, 24, y1], fill=col if live else (70, 72, 80))
        fn = F(INTER_XB, 34 if len(ST_NAME[nm]) < 8 else 22); d.text((38, y0 + 18), ST_NAME[nm], font=fn, fill=(240, 240, 245) if live else (110, 114, 124))
        solo = live and len(on) == 1
        for bi, (txt, lit, lc) in enumerate((('M', not live, (255, 186, 40)), ('S', solo, (80, 170, 255)))):
            bx = 38 + bi * 64; by = y1 - 62
            d.rounded_rectangle([bx, by, bx + 52, by + 44], radius=8, fill=lc if lit else (52, 55, 64))
            d.text((bx + 15, by + 4), txt, font=F(INTER_XB, 32), fill=(20, 20, 24) if lit else (150, 154, 164))
        lv = ev(nm, T) if live else 0.0; mh = int((LANE_H - 24) * min(1.0, lv))          # the track's meter
        d.rectangle([HEAD_W - 30, y0 + 12, HEAD_W - 14, y1 - 12], fill=(16, 17, 22))
        if mh: d.rectangle([HEAD_W - 30, y1 - 12 - mh, HEAD_W - 14, y1 - 12], fill=(90, 220, 120) if lv < .8 else (250, 200, 70))
        # the clip: track colour when it plays, grey when muted, the waveform dark inside it, like the DAW draws it
        cx0 = HEAD_W + 12; body = col if live else (64, 67, 76); wave = (18, 19, 24) if live else (44, 46, 54)
        d.rounded_rectangle([cx0, y0, W + 20, y1], radius=10, fill=tuple(int(c * .82) for c in body) if live else body)
        d.rectangle([cx0, y0, W, y0 + 22], fill=body)                          # the clip's title bar
        d.text((cx0 + 12, y0 - 2), '%s.wav' % ST_NAME[nm].lower(), font=F(MONO, 22), fill=wave)
        mid = (y0 + 24 + y1) / 2; amp = (y1 - y0 - 34) / 2
        for x in range(cx0 + 4, W, 3):
            v = ev(nm, b2t(beat + (x - PH_X) / ppb)) * amp
            if v > 1: d.line([x, mid - v, x, mid + v], fill=wave, width=2)
        if live and since < 0.35 and st > plan['steps'][0][0] and nm not in prev_on(plan, st):     # a part coming in lights up
            fl = Image.new('RGBA', (W - cx0, LANE_H), (255, 255, 255, int(200 * (1 - since / 0.35))))
            im.paste(fl, (cx0, y0), fl)
    # bar lines and numbers, then the playhead over everything
    top, bot = LANE_Y0 - 10, LANE_Y0 + 4 * (LANE_H + LANE_GAP) - LANE_GAP
    for b in range(int(vis0) - 1, int(vis0 + W / ppb) + 2):
        x = PH_X + (b - beat) * ppb
        if b % 4 == 0 and HEAD_W + 12 < x < W:
            d.line([x, top, x, bot], fill=(0, 0, 0), width=2)
            d.text((x + 6, top - 34), str(b // 4 + 1), font=F(MONO, 24), fill=(110, 116, 128))
    d.polygon([(PH_X - 14, top - 8), (PH_X + 14, top - 8), (PH_X, top + 10)], fill=(255, 255, 255))
    d.line([PH_X, top, PH_X, bot], fill=(255, 255, 255), width=4)
    # the master meter under the tracks: the whole mix's spectrum, so the frame moves with the sound
    fi = min(f, bands.shape[1] - 1); bw = (W - 2 * 40) / bands.shape[0]
    for b in range(bands.shape[0]):
        v = float(bands[b, max(0, fi - 1):fi + 1].mean()); hh = int(v * 56) + 2
        d.rectangle([40 + b * bw, 1494 - hh, 40 + (b + 1) * bw - 6, 1494], fill=(70, 78, 96) if not full else tuple(int(c * .7) for c in pal[b % 4]))
    a = np.asarray(im)
    if plan.get('faces') and plan.get('drop') and T >= plan['drop']:          # a reaction when everything comes in
        a = _faces.paste_sprite(np.ascontiguousarray(a), ctx.setdefault('face', _faces.pick(FACE_WHO[0] if FACE_WHO else 'dylan', 2, (seed, 'drop'))),
                                W * 0.80, 1430, 420, T - plan['drop'], T, beat % 1, block=plan.get('face_block', 6))
    # the frame punches in on each new part (hardest on the full mix) and, once the drums are in, a little on the beat
    z = 1.0
    if since < 0.4: z += (0.05 if full else 0.025) * np.exp(-since * 10)
    if 'Drums' in on: z += plan['punch'] * np.exp(-((beat % 1) * SPB) * 9)
    if z > 1.003:
        cw, ch = int(W / z), int(H / z); xx, yy = (W - cw) // 2, (H - ch) // 2
        a = cv2.resize(a[yy:yy + ch, xx:xx + cw], (W, H), interpolation=cv2.INTER_LINEAR)
    return a

def prev_on(plan, st):
    i = [s[0] for s in plan['steps']].index(st)
    return set(plan['steps'][i - 1][1]) if i > 0 else set()

plan = plan_band() if mode == 'band' else plan_prod()
CHROME = plan.get('chrome', 'win95'); CAP = CAPTION_FONTS.get(plan.get('caption'), INTER_XB)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import hook as _hook
plan['hook'] = _hook.pick(mode, seed)                       # the line shown for the first two seconds ('' = none)
plan['hook_angle'] = _hook.angle(mode, plan['hook']); plan['hook_mode'] = _hook.mode(mode, seed)   # flash: first two seconds; hold: the whole video
if plan.get('story'):                                        # a story draws its own line, one that says what this video does
    plan['hook'] = '' if os.environ.get('CQ_HOOK') == 'none' else plan['line']
    plan['hook_angle'] = 'story' if plan['hook'] else 'none'; plan['hook_mode'] = 'story'
elif mode == 'producer' and plan['hook_mode'] == 'hold': plan['hook_mode'] = 'flash'   # a held line would sit on the lyric, now below the top 250 px
import faces as _faces                                      # Dylan and Nick reacting, line by line, on some videos
_fv = os.environ.get('CQ_FACES', '').lower()
plan['faces'] = _faces.available() and (_fv in ('1', 'true', 'yes') or (_fv not in ('0', 'false', 'no') and random.Random(seed * 37 + 5).random() < 0.4))
if plan['faces']:
    plan['face_block'] = random.Random(seed * 41).choice([5, 6, 7])          # how chunky the pixels are: chunky, but the face still reads
    if mode == 'band':                                       # most lyric lines become a reaction window; the rest stay desktop scenes
        fr_ = random.Random(seed * 43)
        for sg in plan['segs']:
            if sg[2] is not None and fr_.random() < 0.75: sg[1] = 'face+' + sg[1]
FACE_WHO = _faces.plan(LINES, seed) if plan['faces'] else []
wav = out[:-4] + '.wav'; dur = cut(MASTER, T0, T1, wav)
if plan.get('story'): story_audio(plan, wav)
feat = features(wav); n = int(round(dur * FPS)); rng = random.Random(seed); ctx = {}
json.dump(json.loads(json.dumps(dict(mode=mode, seed=seed, song=SONG['slug'], window=[T0, T1], plan=plan, **K.record())).replace(SONG_DIR + '/', '')), open(out[:-4] + '.json', 'w'), indent=1)
fr0 = (lambda f: band_frame(f, feat, plan, ctx, rng)) if mode == 'band' else (lambda f: story_frame(f, feat, plan, ctx, rng)) if plan.get('story') else (lambda f: prod_frame(f, feat, plan, ctx, rng))
fr = (fr0 if plan['hook_mode'] == 'story' else
      (lambda f: _hook.draw_hold(np.asarray(fr0(f)), plan['hook'], f / FPS, _hook.HOLD_Y[mode])) if plan['hook_mode'] == 'hold' else
      (lambda f: _hook.draw(np.asarray(fr0(f)), plan['hook'], f / FPS, y=0.43)))      # flash sits mid-screen: both styles keep titles and lyrics at the top
if '--frames' in sys.argv:
    fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
    s = Image.new('RGB', (324 * len(fs), 576))
    for i, f in enumerate(fs):
        fr(max(0, f - 1)); im_ = Image.fromarray(fr(min(f, n - 1))); s.paste(im_.resize((324, 576)), (324 * i, 0))
        if os.environ.get('CQ_FULL'): im_.save(os.path.join(os.environ['CQ_FULL'], '%s_f%d.png' % (os.path.basename(out)[:-4], f)))   # full-size frames, to judge detail
    s.save(out[:-4] + '_sheet.png'); print('frames', n, [(x[1], x[3]) for x in plan['segs']])
else:
    tmp = out[:-4] + '.tmp.mp4'
    p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', wav,
                          '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'), *(['-maxrate', os.environ['CQ_MAXRATE'], '-bufsize', os.environ.get('CQ_BUFSIZE', '6M')] if os.environ.get('CQ_MAXRATE') else []), '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    for f in range(n): p.stdin.write(fr(f).tobytes())
    p.stdin.close(); assert p.wait() == 0; os.replace(tmp, out); print('done', n, round(dur, 2))
