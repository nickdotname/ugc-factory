#!/usr/bin/env python3
"""Put every lyric word on the moment it is sung, and say how sure that is.

    python studio/force_align.py <song_dir> <lyrics.txt> [--vox vocals.flac] [--heard heard.json] [--dry]

The lyrics file is trusted for WHAT is sung and never for WHEN: any m:ss stamps in it are ignored.

Two independent listeners are used, and a word only counts as placed when they agree:

  1. A transcription of the vocal (Whisper) is matched to the lyrics in order across the whole song. That
     says roughly where each passage is, to within a second or so, but its word times are loose.
  2. A speech model that scores every 20 ms of the vocal for every letter (wav2vec2, CTC) then has the
     known letters laid along it by exact search (forced alignment), each word held near where step 1
     found it. That gives each word its own start and end to within a few hundredths of a second.

Every word then gets a verdict from three checks: the letter model actually heard those letters there,
the start is not on silence, and it agrees with the transcription where the transcription heard the same
word. A line's score is the share of its words that pass, and a section's is the share of its lines that
are clean. Renderers only put word-by-word lyrics on sections that pass (studio/nightly.yaml, min_confidence).

Rewrites lines.json and the sections in song.json (adds per-line scores as line_conf), keeps the letter
scores in emissions.npz and the transcription in heard.json so a re-run is quick, and prints the audit.

Needs: torch, transformers (facebook/wav2vec2-large-960h-lv60-self), faster-whisper for a first run.
"""
import argparse, difflib, json, os, re, sys
import numpy as np, soundfile as sf, librosa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prep_song import sections

FRAME = 0.02                                   # the letter model's step
LEAD = 0.04                                    # words are shown this much before they start: late reads as wrong, early does not
MIN_FIT = -6.0                                 # how far (in log-probability per frame) a word's letters may sit below what the model heard there
NAME = 'facebook/wav2vec2-large-960h-lv60-self'
NUM = {'0': 'ZERO', '1': 'ONE', '2': 'TWO', '3': 'THREE', '4': 'FOUR', '5': 'FIVE', '6': 'SIX', '7': 'SEVEN', '8': 'EIGHT', '9': 'NINE'}
SUB = {'yo': 'your', 'ya': 'you', 'cuz': 'because', 'cause': 'because', 'em': 'them', 'til': 'until', 'till': 'until', 'gonna': 'goingto', 'wanna': 'wantto',
       'gotta': 'gotto', 'imma': 'imgoingto', 'aint': 'isnot', 'mr': 'mister', 'ok': 'okay', 'yea': 'yeah', 'tryna': 'tryingto', 'outta': 'outof', 'kinda': 'kindof'}


def norm(w):
    w = re.sub(r"[^a-z0-9]", "", w.lower()); w = SUB.get(w, w)
    return w[:-2] + 'ing' if w.endswith('in') and len(w) > 4 else w


def spell(w):
    w = ''.join(NUM.get(c, c) for c in w.upper())
    return re.sub(r"[^A-Z']", "", w).strip("'")


def read_lyrics(path):
    lines = []
    for raw in open(path).read().splitlines():
        raw = re.sub(r"^\d+:\d\d\s*", "", raw.replace('[?]', ' ').strip())      # a stamp, if there is one, is thrown away
        if raw.split(): lines.append(raw.split())
    return lines


def transcribe(y16, prompt, model='medium.en'):
    from faster_whisper import WhisperModel
    seg, _ = WhisperModel(model, device='cpu', compute_type='int8').transcribe(
        y16, word_timestamps=True, vad_filter=False, beam_size=5, condition_on_previous_text=False, initial_prompt=prompt[:900])
    return [[x.word.strip(), round(x.start, 2), round(x.end, 2)] for s in seg for x in s.words]


def match(L, heard):
    """Lyric words to heard words, in order, across the whole song. -> {lyric index: heard index} for words that are the same."""
    Hn = [norm(h[0]) for h in heard]; n, m = len(L), len(Hn)

    def sim(x, y):
        if x == y: return 1.0
        if not x or not y: return 0.0
        if x[:4] == y[:4] and min(len(x), len(y)) >= 4: return 0.7
        r = difflib.SequenceMatcher(None, x, y).ratio(); return r if r >= 0.72 else 0.0

    GL, GH = -0.55, -0.35
    S = np.zeros((n + 1, m + 1), np.float32); B = np.zeros((n + 1, m + 1), np.int8)
    S[1:, 0] = np.arange(1, n + 1) * GL; S[0, 1:] = np.arange(1, m + 1) * GH; B[1:, 0] = 1; B[0, 1:] = 2
    cache = {}
    for i in range(1, n + 1):
        li = L[i - 1]; row = S[i]; prev = S[i - 1]
        for j in range(1, m + 1):
            key = (li, Hn[j - 1]); s = cache.get(key)
            if s is None: s = cache[key] = sim(*key)
            d = prev[j - 1] + (2.0 * s if s else -0.9); u = prev[j] + GL; l = row[j - 1] + GH
            if d >= u and d >= l: row[j] = d; B[i, j] = 0
            elif u >= l: row[j] = u; B[i, j] = 1
            else: row[j] = l; B[i, j] = 2
    pair = {}; i, j = n, m
    while i > 0 or j > 0:
        b = B[i, j]
        if b == 0:
            if L[i - 1] == Hn[j - 1]: pair[i - 1] = j - 1
            i -= 1; j -= 1
        elif b == 1: i -= 1
        else: j -= 1
    return pair


def emissions(y16, cache):
    """log P(letter) for every 20 ms of the vocal."""
    if cache and os.path.exists(cache):
        z = np.load(cache)
        if int(z['n']) == len(y16): return z['E'].astype(np.float32)
    import torch
    from transformers import Wav2Vec2ForCTC
    torch.set_num_threads(os.cpu_count() or 2)
    model = Wav2Vec2ForCTC.from_pretrained(NAME).eval()
    y = y16 / (np.abs(y16).max() + 1e-9)
    CH, OV = 20 * 16000, 2 * 16000; out = []; s = 0
    with torch.no_grad():
        while s < len(y):
            a, b = max(0, s - OV), min(len(y), s + CH + OV); seg = y[a:b]
            lp = torch.log_softmax(model(torch.from_numpy(((seg - seg.mean()) / (seg.std() + 1e-9)).astype(np.float32))[None]).logits[0], -1).numpy()
            f0 = (s - a) // 320; f1 = f0 + min(CH, len(y) - s) // 320
            out.append(lp[f0:f1]); s += CH
    E = np.concatenate(out).astype(np.float32)
    if cache: np.savez_compressed(cache, E=E.astype(np.float16), n=len(y16))
    return E


def lay(E, tokens, lo, hi, blank):
    """Exact best path of `tokens` (with optional blanks between) through E, each token kept inside frames lo..hi.
    -> first frame, last frame and mean probability of every token."""
    T, N = len(E), len(tokens); S = 2 * N + 1
    st = np.full(S, blank, np.int64); st[1::2] = tokens
    slo = np.zeros(S, np.int64); shi = np.full(S, T - 1, np.int64)
    slo[1::2] = lo; shi[1::2] = hi
    slo[2::2] = lo; shi[0:-1:2] = hi                       # a blank lives between its neighbours' limits
    slo[0] = 0; shi[-1] = T - 1
    skip = np.zeros(S, bool); skip[3::2] = tokens[1:] != tokens[:-1]        # may jump the blank unless the letter repeats
    NEG = -1e30; v = np.full(S, NEG, np.float64); v[0] = E[0, blank]; v[1] = E[0, st[1]] if slo[1] <= 0 else NEG
    back = np.zeros((T, S), np.int8)
    for t in range(1, T):
        a = v; b = np.concatenate(([NEG], v[:-1])); c = np.concatenate(([NEG, NEG], v[:-2])); c = np.where(skip, c, NEG)
        best = np.maximum(np.maximum(a, b), c); k = np.where(best == a, 0, np.where(best == b, 1, 2)).astype(np.int8)
        v = best + E[t, st]; v[(t < slo) | (t > shi)] = NEG; back[t] = k
    if max(v[S - 1], v[S - 2]) < NEG / 2: return None
    s = int(S - 1 if v[S - 1] >= v[S - 2] else S - 2)
    path = np.zeros(T, np.int64)
    for t in range(T - 1, -1, -1):
        path[t] = s; s -= int(back[t, s])
    first = np.full(N, -1); last = np.full(N, -1); gap = np.zeros(N); cnt = np.zeros(N)
    top = E.max(1)
    for t in range(T):
        s = path[t]
        if s % 2:
            k = s // 2
            if first[k] < 0: first[k] = t
            last[k] = t; gap[k] += E[t, st[s]] - top[t]; cnt[k] += 1       # 0 when the model's first choice is this letter
    return first, last, gap / np.maximum(1, cnt)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('song'); ap.add_argument('lyrics'); ap.add_argument('--vox'); ap.add_argument('--heard')
    ap.add_argument('--dry', action='store_true'); ap.add_argument('--reach', type=float, default=1.0, help='seconds a word may sit from where the transcription put it')
    a = ap.parse_args()
    find = lambda stem, exts: next((os.path.join(a.song, stem + e) for e in exts if os.path.exists(os.path.join(a.song, stem + e))), None)
    vox = a.vox or find(os.path.join('stems', 'Vocals'), ('.flac', '.wav', '.ogg'))
    y, sr = sf.read(vox, always_2d=True, dtype='float32'); y = y.mean(1); dur = len(y) / sr
    y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)

    LINES = read_lyrics(a.lyrics); flat = [w for l in LINES for w in l]; n = len(flat); L = [norm(w) for w in flat]
    line_of = [li for li, l in enumerate(LINES) for _ in l]

    hp = a.heard or os.path.join(a.song, 'heard.json')
    if os.path.exists(hp): heard = json.load(open(hp))
    else:
        heard = transcribe(y16, ' '.join(flat))
        if not a.dry: json.dump(heard, open(os.path.join(a.song, 'heard.json'), 'w'))
    heard = [h for h in heard if norm(h[0])]
    pair = match(L, heard)
    # an anchor is a word heard as itself next to another word heard as itself: one lone match can be the wrong repeat
    solid = {i for i in pair if (i - 1 in pair and pair[i - 1] == pair[i] - 1) or (i + 1 in pair and pair[i + 1] == pair[i] + 1)}

    E = emissions(y16, None if a.dry and not os.path.exists(os.path.join(a.song, 'emissions.npz')) else os.path.join(a.song, 'emissions.npz'))
    T = len(E)
    from transformers import Wav2Vec2Processor
    vocab = Wav2Vec2Processor.from_pretrained(NAME).tokenizer.get_vocab(); BLANK, SEP = vocab['<pad>'], vocab['|']

    # where each word may start: near its anchor, or between the anchors either side of it
    reach = int(a.reach / FRAME); wlo = np.zeros(n, np.int64); whi = np.full(n, T - 1, np.int64)
    for i in solid:
        f = int(heard[pair[i]][1] / FRAME); wlo[i] = max(0, f - reach); whi[i] = min(T - 1, f + reach)
    order = sorted(solid); prev_lo = 0
    for i in range(n):                                   # forward: not before the anchor behind
        if i in solid: prev_lo = wlo[i]
        else: wlo[i] = prev_lo
    nxt_hi = T - 1
    for i in range(n - 1, -1, -1):                       # backward: not after the anchor ahead
        if i in solid: nxt_hi = whi[i]
        else: whi[i] = nxt_hi
    for i in range(1, n): wlo[i] = max(wlo[i], wlo[i - 1])
    for i in range(n - 2, -1, -1): whi[i] = min(whi[i], whi[i + 1])

    tok, own = [], []
    for i, w in enumerate(flat):
        letters = [vocab[c] for c in spell(w) if c in vocab] or [SEP]
        for c in letters: tok.append(c); own.append(i)
        tok.append(SEP); own.append(-1)
    tok = np.array(tok); own = np.array(own); N = len(tok)
    lo = np.zeros(N, np.int64); hi = np.full(N, T - 1, np.int64)
    for k in range(N):
        i = own[k] if own[k] >= 0 else own[k - 1]
        lo[k] = wlo[i]; hi[k] = min(T - 1, whi[i] + int(3.0 / FRAME))       # a word may run on for a while after it starts
    first_tok = np.array([k for k in range(N) if own[k] >= 0 and (k == 0 or own[k - 1] != own[k])])
    hi[first_tok] = whi[own[first_tok]]                                   # but its first letter has to start in time
    res = lay(E, tok, lo, hi, BLANK)
    if res is None: sys.exit('could not lay the lyrics along the vocal: the transcription and the lyrics disagree too much')
    first, last, prob = res

    start = np.zeros(n); end = np.zeros(n); p = np.zeros(n)
    for i in range(n):
        ks = np.where(own == i)[0]; start[i] = first[ks[0]] * FRAME; end[i] = (last[ks[-1]] + 1) * FRAME; p[i] = float(np.mean(prob[ks]))
    if os.environ.get('FA_DEBUG'): np.save(os.path.join(a.song, 'fa_debug.npy'), np.stack([start, end, p]))

    # ---- the three checks ------------------------------------------------------------------
    hop = 128; sr2 = 22050; y22 = librosa.resample(y, orig_sr=sr, target_sr=sr2) if sr != sr2 else y
    rms = librosa.feature.rms(y=y22, frame_length=1024, hop_length=hop)[0]; thr = max(np.percentile(rms, 95) * 0.06, 1e-4)
    env = librosa.onset.onset_strength(y=y22, sr=sr2, hop_length=hop)
    peaks = librosa.onset.onset_detect(onset_envelope=env, sr=sr2, hop_length=hop, units='time', backtrack=False, delta=0.12, wait=4)
    sung = np.array([rms[int(start[i] * sr2 / hop):int(start[i] * sr2 / hop) + int(0.16 * sr2 / hop)].max(initial=0) >= thr for i in range(n)])
    heard_ok = np.array([i not in pair or abs(heard[pair[i]][1] - start[i]) <= 0.45 for i in range(n)])
    letters_ok = (p >= MIN_FIT) & ((end - start) >= 0.03) & ((end - start) <= 3.0)
    ok = letters_ok & sung & heard_ok

    # systematic offset between letter-model starts and the vocal's own attacks, from clean words only
    offs = []
    for i in np.where(ok)[0]:
        j = np.searchsorted(peaks, start[i]); c = [peaks[k] for k in (j - 1, j) if 0 <= k < len(peaks)]
        if c:
            d = min(c, key=lambda q: abs(q - start[i])) - start[i]
            if abs(d) < 0.12: offs.append(d)
    bias = float(np.median(offs)) if len(offs) > 20 else 0.0
    shown = np.maximum(0.0, start + bias - LEAD)
    for i in range(1, n): shown[i] = max(shown[i], shown[i - 1] + 0.03)

    # ---- report ----------------------------------------------------------------------------
    d_heard = np.array([abs(heard[pair[i]][1] - start[i]) for i in pair])
    near = np.array([min(abs(peaks - (start[i] + bias))) if len(peaks) else 9 for i in range(n)])
    print('%d words: %d pass all three checks (%.0f%%)' % (n, int(ok.sum()), 100 * ok.mean()))
    print('   letters heard where placed: %.0f%%   start is on singing: %.0f%%   agrees with transcription: %.0f%% of the %d words it also heard' % (
        100 * letters_ok.mean(), 100 * sung.mean(), 100 * np.mean(d_heard <= 0.45) if len(d_heard) else 0, len(d_heard)))
    print('   against the vocal\'s own attacks: %.0f%% of starts within 60 ms, %.0f%% within 120 ms (offset corrected %+d ms)' % (
        100 * np.mean(near < 0.06), 100 * np.mean(near < 0.12), int(1000 * bias)))

    # ---- back into lines (long ones are broken at commas, as before) -------------------------
    lines = []; q = 0
    for l in LINES:
        k = len(l); lines.append(dict(words=[(l[j], round(float(shown[q + j]), 2)) for j in range(k)], end=round(float(end[q + k - 1] + bias), 2), ok=[bool(x) for x in ok[q:q + k]])); q += k
    out = []
    for Ln in lines:
        ws = Ln['words']; k = len(ws); parts = max(1, -(-k // 9)); size = -(-k // parts); cuts = [0]
        while cuts[-1] + size < k:
            target = cuts[-1] + size
            nearc = [x for x in range(max(cuts[-1] + 3, target - 2), min(k - 2, target + 3)) if ws[x - 1][0].endswith((',', '.', '?', '!'))]
            cuts.append(nearc[0] if nearc else target)
        cuts.append(k)
        for x, z in zip(cuts, cuts[1:]):
            if z > x: out.append(dict(words=ws[x:z], end=Ln['end'] if z == k else None, conf=round(float(np.mean(Ln['ok'][x:z])), 2)))
    for i, Ln in enumerate(out):
        nxt = out[i + 1]['words'][0][1] if i + 1 < len(out) else dur; lastw = Ln['words'][-1][1]
        e = Ln['end'] if Ln['end'] and Ln['end'] > lastw else lastw + 0.6
        Ln['end'] = round(min(max(e, lastw + 0.25), nxt if nxt - lastw < 1.6 else lastw + 0.9, dur), 2)
    song = json.load(open(os.path.join(a.song, 'song.json'))); secs = []
    for k, s in enumerate(sections(out), 1):
        st = round(max(0, out[s[0]]['words'][0][1] - 0.35), 2); en = round(min(dur, out[s[-1]]['end'] + 0.3), 2)
        clean = float(np.mean([out[x]['conf'] >= 0.8 for x in s])); words = float(np.mean([c for x in s for c in [out[x]['conf']] * len(out[x]['words'])]))
        secs.append(dict(id='s%02d' % k, start=st, end=en, lines=[s[0], s[-1]], confidence=round(min(clean, words), 2)))
        print('%s  %6.1f-%6.1f  %4.1fs  clean lines %3.0f%%  words %3.0f%%  %s' % (secs[-1]['id'], st, en, en - st, 100 * clean, 100 * words, ' '.join(w for w, _ in out[s[0]]['words'])[:50]))
    if not a.dry:
        json.dump([[Ln['end'], [[w, t] for w, t in Ln['words']]] for Ln in out], open(os.path.join(a.song, 'lines.json'), 'w'))
        song['sections'] = secs; song['aligned'] = 'forced'; song['line_conf'] = [Ln['conf'] for Ln in out]
        json.dump(song, open(os.path.join(a.song, 'song.json'), 'w'), indent=1)
    return dict(words=n, ok=float(ok.mean()), within60=float(np.mean(near < 0.06)), within120=float(np.mean(near < 0.12)))


if __name__ == '__main__':
    main()
