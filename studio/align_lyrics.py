#!/usr/bin/env python3
"""Time a song's lyrics to its vocal from the words alone, ignoring any m:ss stamps in the file.

    python studio/align_lyrics.py <song_dir> <lyrics.txt> [--words heard.json] [--model small.en]

The lyrics file is trusted for WHAT is sung and not for WHEN. The vocal stem is transcribed
with word timings; the known lyrics and the heard words are then matched IN ORDER across the
whole song (not passage by passage), so a line whose stamp is seconds out still lands where it
is sung. Words the transcription misheard take the time of whatever was heard in their place;
only words with nothing heard near them are spaced between their neighbours.

Rewrites lines.json and the sections in song.json, saves the transcription as heard.json (so a
re-run is instant), and prints: how many words were matched, how far each stamp in the file was
from where its line is really sung, and how many word starts land on actual singing.
"""
import argparse, difflib, json, os, re, sys
import numpy as np, soundfile as sf, librosa
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prep_song import sections

ap = argparse.ArgumentParser(); ap.add_argument('song'); ap.add_argument('lyrics'); ap.add_argument('--words'); ap.add_argument('--model', default='small.en')
ap.add_argument('--dry', action='store_true', help='report only, write nothing'); a = ap.parse_args()
find = lambda stem, exts: next((os.path.join(a.song, stem + e) for e in exts if os.path.exists(os.path.join(a.song, stem + e))), None)
vox_path = find(os.path.join('stems', 'Vocals'), ('.flac', '.ogg'))

# ---- the words, and (for the report only) the stamps ----------------------------------------
LINES, STAMP = [], []; cur = None
for raw in open(a.lyrics).read().splitlines():
    raw = raw.replace('[?]', ' ').strip(); m = re.match(r"^(\d+):(\d\d)\s*(.*)$", raw); st = None
    if m: st = int(m.group(1)) * 60 + int(m.group(2)); raw = m.group(3)
    if raw.split(): LINES.append(raw.split()); STAMP.append(st)
SUB = {'yo': 'your', 'ya': 'you', 'cuz': 'because', 'cause': 'because', 'em': 'them', 'til': 'until', 'till': 'until', 'gonna': 'goingto', 'wanna': 'wantto', 'gotta': 'gotto',
       'imma': 'imgoingto', 'aint': 'isnot', 'mr': 'mister', 'ok': 'okay', 'yeah': 'yeah', 'yea': 'yeah', 'ya': 'you', 'tryna': 'tryingto', 'outta': 'outof', 'kinda': 'kindof'}
def norm(w):
    w = re.sub(r"[^a-z0-9]", "", w.lower()); w = SUB.get(w, w)
    return w[:-2] + 'ing' if w.endswith('in') and len(w) > 4 and w + 'g' != w else w
flat = [w for l in LINES for w in l]; L = [norm(w) for w in flat]
last = None; WST = []; LSTART = []
for l, st in zip(LINES, STAMP):
    last = st if st is not None else last
    WST += [last] * len(l); LSTART += [True] + [False] * (len(l) - 1)

# ---- what is heard --------------------------------------------------------------------------
heard_path = a.words or os.path.join(a.song, 'heard.json')
if os.path.exists(heard_path): heard = json.load(open(heard_path))
else:
    from faster_whisper import WhisperModel
    y, sr = sf.read(vox_path, always_2d=True, dtype='float32'); y16 = librosa.resample(y.mean(1), orig_sr=sr, target_sr=16000)
    seg, _ = WhisperModel(a.model, device='cpu', compute_type='int8').transcribe(y16, word_timestamps=True, vad_filter=False, beam_size=5, condition_on_previous_text=False,
                                                                                 initial_prompt=' '.join(flat)[:900])
    heard = [[x.word.strip(), round(x.start, 2), round(x.end, 2)] for s in seg for x in s.words]
    if not a.dry: json.dump(heard, open(os.path.join(a.song, 'heard.json'), 'w'))
heard = [h for h in heard if norm(h[0])]; Hn = [norm(h[0]) for h in heard]

# ---- match them in order across the whole song ----------------------------------------------
def sim(x, y):
    if x == y: return 1.0
    if not x or not y: return 0.0
    if x[:4] == y[:4] and min(len(x), len(y)) >= 4: return 0.7
    r = difflib.SequenceMatcher(None, x, y).ratio(); return r if r >= 0.72 else 0.0
n, m = len(L), len(Hn); S = np.zeros((n + 1, m + 1), np.float32); B = np.zeros((n + 1, m + 1), np.int8)
GL, GH = -0.55, -0.35                      # a lyric word nobody heard / a heard word that is not in the lyrics
S[1:, 0] = np.arange(1, n + 1) * GL; S[0, 1:] = np.arange(1, m + 1) * GH; B[1:, 0] = 1; B[0, 1:] = 2
uniq = {w: k for k, w in enumerate(sorted(set(L) | set(Hn)))}
for i in range(1, n + 1):
    li = L[i - 1]; row = S[i]; prev = S[i - 1]
    for j in range(1, m + 1):
        s = sim(li, Hn[j - 1])
        if s and WST[i - 1] is not None:                      # far from where the file says this passage is: possible, but it has to earn it
            s = max(0.05, s - min(0.6, 0.05 * max(0.0, abs(heard[j - 1][1] - WST[i - 1]) - 6.0)))
        d = prev[j - 1] + (2.0 * s if s else -0.9); u = prev[j] + GL; l = row[j - 1] + GH
        if d >= u and d >= l: row[j] = d; B[i, j] = 0
        elif u >= l: row[j] = u; B[i, j] = 1
        else: row[j] = l; B[i, j] = 2
pair = {}; i, j = n, m                      # lyric word -> heard word, where they are the same word
while i > 0 or j > 0:
    b = B[i, j]
    if b == 0:
        if sim(L[i - 1], Hn[j - 1]): pair[i - 1] = j - 1
        i -= 1; j -= 1
    elif b == 1: i -= 1
    else: j -= 1

# ---- times: matched words take the heard time; the rest borrow from what was heard between --
times = [None] * n; ends = [None] * n; how = ['none'] * n
for i_, j_ in pair.items(): times[i_] = heard[j_][1]; ends[i_] = heard[j_][2]; how[i_] = 'matched'
anch = sorted(pair.items()); bounds = [(-1, -1)] + anch + [(n, m)]
for (i0, j0), (i1, j1) in zip(bounds, bounds[1:]):
    gapL = list(range(i0 + 1, i1)); gapH = list(range(j0 + 1, j1))
    if not gapL: continue
    left = heard[j0][2] if j0 >= 0 else (heard[0][1] - 0.3 * len(gapL) if heard else 0.0); right = heard[j1][1] if j1 < m else (heard[-1][2] + 0.3 * len(gapL) if heard else left + 1)
    if gapH and len(gapH) >= 0.5 * len(gapL):          # something else was heard here: the same words, misheard
        if len(gapH) >= 2 * len(gapL):                # far more heard than written (ad-libs, an intro): stay next to the line they belong to
            gapH = gapH[-len(gapL):] if (i0 < 0 or LSTART[gapL[0]]) and j1 < m else gapH[:len(gapL)]
        for k, i_ in enumerate(gapL):
            h = heard[gapH[min(len(gapH) - 1, k * len(gapH) // len(gapL))]]; times[i_] = h[1] + 0.001 * k; ends[i_] = h[2]; how[i_] = 'misheard'
    else:                                             # nothing usable heard: keep them tight against the nearer neighbour
        span = right - left; need = 0.28 * len(gapL)
        if span > need * 1.8 and i0 >= 0: left, right = left, left + need          # a long silence: they follow the line before
        elif span > need * 1.8: left, right = right - need, right
        for k, i_ in enumerate(gapL): times[i_] = left + (right - left) * (k + 0.5) / len(gapL); how[i_] = 'spaced'
# a word that was not itself matched may not drift away from the matched words of its own line
LINE_OF = [li for li, l in enumerate(LINES) for _ in l]
for k in range(n):
    if how[k] == 'matched': continue
    same = [q for q in range(max(0, k - 12), min(n, k + 13)) if how[q] == 'matched' and LINE_OF[q] == LINE_OF[k]]
    if not same: continue
    q = min(same, key=lambda q: abs(q - k)); reach = 0.45 * abs(q - k) + 0.25
    times[k] = float(np.clip(times[k], times[q] - reach, times[q] + reach)) if q > k else float(np.clip(times[k], times[q], times[q] + reach))
    if q > k: times[k] = min(times[k], times[q] - 0.05 * (q - k))
for k in range(1, n): times[k] = max(times[k], times[k - 1] + 0.04)
y, sr = sf.read(vox_path, always_2d=True, dtype='float32'); y = y.mean(1); dur = len(y) / sr

# ---- is everything a touch early or late? compare word starts with where the vocal actually kicks in
oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256); ofps = sr / 256; imp = np.zeros(len(oenv))
for t_, h_ in zip(times, how):
    if h_ == 'matched' and 0 <= int(t_ * ofps) < len(imp): imp[int(t_ * ofps)] += 1
lags = np.arange(-int(0.5 * ofps), int(0.5 * ofps) + 1); oz = (oenv - oenv.mean()) / (oenv.std() + 1e-9)
cc = [float(np.sum(imp[max(0, -g):len(imp) - max(0, g)] * oz[max(0, g):len(oz) - max(0, -g)])) for g in lags]
LAG = float(lags[int(np.argmax(cc))] / ofps); print('vocal attacks sit %+.2fs from the transcribed word starts (peak sharpness %.1f)' % (LAG, (max(cc) - np.mean(cc)) / (np.std(cc) + 1e-9)))

# ---- report ---------------------------------------------------------------------------------
hop = int(sr * 0.02); env = np.array([np.sqrt(np.mean(y[k:k + hop] ** 2)) for k in range(0, len(y) - hop, hop)]); thr = np.percentile(env, 55)
def voiced(ts): return float(np.mean([env[min(len(env) - 1, int((t + 0.05) / 0.02))] > thr for t in ts])) if ts else 0.0
cnt = {k: how.count(k) for k in ('matched', 'misheard', 'spaced')}
print('%d lyric words: %d matched, %d misheard-but-timed, %d spaced by guess' % (n, cnt['matched'], cnt['misheard'], cnt['spaced']))
print('word starts that land on singing: %.0f%%' % (100 * voiced(times)))
old_p = os.path.join(a.song, 'lines.json')
if os.path.exists(old_p):
    old = [t for e, ws in json.load(open(old_p)) for w, t in ws]
    if len(old) == n:
        d = np.abs(np.array(old) - np.array(times)); print('before this run: %.0f%% landed on singing; %d words move by more than 0.3s, %d by more than 1s' % (100 * voiced(old), int((d > .3).sum()), int((d > 1).sum())))
p = 0; offs = []
for l, st in zip(LINES, STAMP):
    if st is not None and how[p] != 'spaced': offs.append((st, times[p] - st, ' '.join(l)[:38]))
    p += len(l)
if offs:
    o = np.array([x[1] for x in offs]); print('stamps in the lyrics file vs where the line is sung: median %+.1fs, %d of %d off by more than 2s' % (np.median(o), int((np.abs(o) > 2).sum()), len(o)))
    for st, off, txt in sorted(offs, key=lambda x: -abs(x[1]))[:6]: print('   %d:%02d  %+6.1fs  %s' % (st // 60, st % 60, off, txt))

# ---- back into lines ------------------------------------------------------------------------
lines = []; p = 0
for l in LINES:
    k = len(l); ws = [(l[q], round(float(times[p + q]), 2)) for q in range(k)]; e = ends[p + k - 1]
    lines.append(dict(words=ws, end=round(float(e), 2) if e else None, conf=float(np.mean([h != 'spaced' for h in how[p:p + k]])))); p += k
out = []                                  # long lines read badly on screen: break them at commas, or in equal parts
for Ln in lines:
    ws = Ln['words']; k = len(ws); parts = max(1, -(-k // 9)); size = -(-k // parts); cuts = [0]
    while cuts[-1] + size < k:
        target = cuts[-1] + size
        near = [q for q in range(max(cuts[-1] + 3, target - 2), min(k - 2, target + 3)) if ws[q - 1][0].endswith((',', '.', '?', '!'))]
        cuts.append(near[0] if near else target)
    cuts.append(k)
    for x, z in zip(cuts, cuts[1:]):
        if z > x: out.append(dict(words=ws[x:z], end=Ln['end'] if z == k else None, conf=Ln['conf']))
for i_, Ln in enumerate(out):
    nxt = out[i_ + 1]['words'][0][1] if i_ + 1 < len(out) else dur; last = Ln['words'][-1][1]
    e = Ln['end'] if Ln['end'] and Ln['end'] > last else last + 0.6
    Ln['end'] = round(min(max(e, last + 0.25), nxt if nxt - last < 1.6 else last + 0.9, dur), 2)
song = json.load(open(os.path.join(a.song, 'song.json'))); secs = []
for k, s in enumerate(sections(out), 1):
    st = round(max(0, out[s[0]]['words'][0][1] - 0.35), 2); en = round(min(dur, out[s[-1]]['end'] + 0.3), 2); c = round(float(np.mean([out[q]['conf'] for q in s])), 2)
    secs.append(dict(id='s%02d' % k, start=st, end=en, lines=[s[0], s[-1]], confidence=c))
    print('%s  %6.1f-%6.1f  %4.1fs  conf %.2f  %s' % (secs[-1]['id'], st, en, en - st, c, ' '.join(w for w, _ in out[s[0]]['words'])[:56]))
if not a.dry:
    json.dump([[Ln['end'], [[w, t] for w, t in Ln['words']]] for Ln in out], open(os.path.join(a.song, 'lines.json'), 'w'))
    song['sections'] = secs; song['aligned'] = 'global'; json.dump(song, open(os.path.join(a.song, 'song.json'), 'w'), indent=1)
