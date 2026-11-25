#!/usr/bin/env python3
"""How well every lyric word sits on its singing, measured from the vocal stem itself, and the gate lyric videos pass.

    python studio/sync_check.py [slug ...] [--lines] [--json out.json]

No model and no lyrics text: it only listens to studio/songs/<slug>/stems/Vocals.* and compares it with lines.json.
For every word it measures two things at the moment the word really starts (its lines.json time + LEAD, because
lines.json times are already shown LEAD early, see studio/force_align.py):

  * offset: the signed distance to the nearest vocal onset (an attack in the vocal stem). Words that sit on their
    syllable are within a few tens of milliseconds of one; guessed or drifted words are not.
  * voiced: whether the vocal stem has energy in the 180 ms around the start. A word that starts on silence is
    plainly wrong on screen, whatever any model scored it.

It reports them per song, per section and per line, and looks for what is systematic: the lag (shift of every word
at once) that would put the words closest to the onsets. A song whose best lag is far from zero is early or late as a
whole (a stem/master offset, an intro trimmed from one file and not the other). It also checks that the vocal stem
lines up with the master, since the words are timed on the stem and the video plays the master.

The gate (`sections_ok`, used by studio/nightly.py, render_all.py and post_now.py for every lyric stretch; `window_ok`
for stretches that are not sections; `load_lines`, used by every renderer that shows lyrics). A section carries
word-by-word lyrics only when its words measure as sung on time:

  * median |offset| <= MAX_MED (45 ms): force-aligned sections measure 13-47 ms, Whisper-only timing 39-80 ms;
  * at least MIN_CONTRAST (1.4) times better than chance, i.e. than the same words shifted 150-400 ms (the onsets are
    dense, so a small distance alone can be luck): aligned sections run 1.45-3.6x, Whisper-only ones 1.0-1.37x;
  * at most MAX_SILENT (10%) of words starting on silence: aligned sections run 0-2%, guessed ones up to 42%;
  * at least MIN_WORDS (8) words, so the median means something.

A line is trusted when its section passes, line_conf from force_align (if any) is at least LINE_CONF, and its own
words sit a median LINE_MED (60 ms) or less from an onset with at most LINE_SILENT of them on silence. `load_lines`
gives an untrusted line every word at its first word's time, so it is shown whole for its span, never word by word.
"""
import argparse, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR, HOP = 22050, 128
LEAD = 0.04            # lines.json times are shown this much before the word (studio/force_align.py)
VOICE = (-0.02, 0.16)  # where a word's start must have vocal energy, around its real start
MAX_MED, MIN_CONTRAST, MAX_SILENT, MIN_WORDS = 0.045, 1.4, 0.10, 8
LINE_CONF, LINE_MED, LINE_SILENT = 0.5, 0.060, 0.34
RATE = 4.5           # vocal attacks per second of singing the onset picker is tuned to (about one per syllable)
LAGS = np.round(np.arange(-0.40, 0.4001, 0.01), 3)


def _stem(song_dir, name):
    return next((os.path.join(song_dir, 'stems', name + e) for e in ('.flac', '.wav', '.ogg') if os.path.exists(os.path.join(song_dir, 'stems', name + e))), None)


_CACHE = {}


def vocal(song_dir):
    """-> dict(onsets=seconds, rms, thr, dur) of the vocal stem, cached per file."""
    import soundfile as sf, librosa
    p = _stem(song_dir, 'Vocals')
    if not p: return None
    key = (p, os.path.getmtime(p))
    if key in _CACHE: return _CACHE[key]
    y, sr = sf.read(p, always_2d=True, dtype='float32'); y = y.mean(1)
    if sr != SR: y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=HOP)[0]
    thr = max(float(np.percentile(rms, 95)) * 0.06, 1e-4)                       # -24 dB under the loud singing, as force_align.py
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    loud = rms[:len(env)] >= thr; secs = max(1.0, loud.sum() * HOP / SR)
    def pick(delta):
        on = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, units='time', backtrack=False, delta=delta, wait=4)
        return np.array([t for t in on if rms[min(len(rms) - 1, int(t * SR / HOP))] >= thr * 0.5])   # an attack in the noise floor is not singing
    # The onset picker's threshold is relative to the loudest attack in the file, so one fixed value finds 1.4 attacks
    # a second in one song and 3.5 in another. Instead it is set so every song gets RATE attacks per second of singing,
    # about one per sung syllable: then a distance means the same thing in every song.
    lo, hi = 0.005, 0.5
    for _ in range(14):
        mid = (lo * hi) ** 0.5
        if len(pick(mid)) / secs > RATE: lo = mid
        else: hi = mid
    on = pick(hi)
    v = dict(onsets=np.asarray(on, float), rms=rms, thr=thr, dur=len(y) / SR)
    _CACHE[key] = v
    return v


def nearest(onsets, s):
    """Signed distance from each time in s to its nearest onset (onset - s)."""
    s = np.asarray(s, float)
    if not len(onsets): return np.full(len(s), 9.0)
    j = np.clip(np.searchsorted(onsets, s), 1, len(onsets) - 1) if len(onsets) > 1 else np.zeros(len(s), int)
    a, b = onsets[np.maximum(j - 1, 0)] - s, onsets[j] - s
    return np.where(np.abs(a) <= np.abs(b), a, b)


def voiced(v, s):
    rms, thr = v['rms'], v['thr']; out = []
    for t in np.asarray(s, float):
        a, b = int((t + VOICE[0]) * SR / HOP), int((t + VOICE[1]) * SR / HOP)
        out.append(bool(a < len(rms) and rms[max(0, a):max(a + 1, b)].max(initial=0) >= thr))
    return np.array(out, bool)


def words(song_dir, path=None):
    """-> list of (line index, word, shown time) from lines.json (or another lines file of the song, like studio/lofi/lines/)."""
    try: L = json.load(open(path or os.path.join(song_dir, 'lines.json')))
    except (OSError, ValueError): return []
    return [(i, w, float(t)) for i, (_, ws) in enumerate(L) for w, t in ws]


def stats(v, times):
    """Measures for a set of shown times. -> dict(n, med (s, of |offset|), signed (median offset), silent (share), lag (best shift))."""
    s = np.asarray(times, float) + LEAD
    if not len(s): return dict(n=0, med=None, signed=None, silent=None, within45=None, lag=None, chance=None, contrast=None)
    d = nearest(v['onsets'], s); on = voiced(v, s)
    curve = [float(np.median(np.abs(nearest(v['onsets'], s + g)))) for g in LAGS] if len(s) >= MIN_WORDS else None
    lag = float(LAGS[int(np.argmin(curve))]) if curve else None
    med = float(np.median(np.abs(d)))
    # what the same words would measure if they were all wrong by 150-400 ms: the chance level for this passage's density of attacks
    base = float(np.median([c for g, c in zip(LAGS, curve) if abs(g) >= 0.15])) if curve else None
    return dict(n=int(len(s)), med=round(med, 4), signed=round(float(np.median(d)), 4), silent=round(float(1 - on.mean()), 3),
                within45=round(float(np.mean(np.abs(d) <= 0.045)), 3), lag=lag, chance=None if base is None else round(base, 4),
                contrast=None if base is None else round(base / max(med, 0.005), 2))


def passes(st):
    return bool(st['n'] >= MIN_WORDS and st['med'] is not None and st['med'] <= MAX_MED and st['silent'] <= MAX_SILENT
                and st['contrast'] is not None and st['contrast'] >= MIN_CONTRAST)


def stem_lag(song_dir):
    """Seconds the stems run late against the master (+) or early (-), from the onset envelopes of master vs. the stems'
    sum, over +-1 s. None if it cannot be told."""
    import soundfile as sf, librosa
    m = next((os.path.join(song_dir, 'master' + e) for e in ('.flac', '.wav', '.ogg') if os.path.exists(os.path.join(song_dir, 'master' + e))), None)
    ps = [_stem(song_dir, n) for n in ('Vocals', 'Drums', 'Bass', 'Other')]
    if not m or not all(ps): return None
    def load(p, n=None):
        y, sr = sf.read(p, always_2d=True, dtype='float32', frames=-1 if n is None else int(n * sf.info(p).samplerate)); y = y.mean(1)
        return librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y
    a = load(m, 120)
    b = None
    for p in ps:
        y = load(p, 120); b = y if b is None else b[:min(len(b), len(y))] + y[:min(len(b), len(y))]
    n = min(len(a), len(b)); hop = 64
    ea = librosa.onset.onset_strength(y=a[:n], sr=SR, hop_length=hop); eb = librosa.onset.onset_strength(y=b[:n], sr=SR, hop_length=hop)
    ea = (ea - ea.mean()) / (ea.std() + 1e-9); eb = (eb - eb.mean()) / (eb.std() + 1e-9)
    K = int(1.0 * SR / hop); best, arg = -1e9, 0
    for k in range(-K, K + 1):
        x, y = (ea[k:], eb[:len(eb) - k]) if k >= 0 else (ea[:len(ea) + k], eb[-k:])
        c = float(np.dot(x, y) / len(x))
        if c > best: best, arg = c, k
    return round(-arg * hop / SR, 4)                                                 # stems late (+): the stem's attack comes after the master's


def line_ok(st, conf=None):
    if conf is not None and conf < LINE_CONF: return False
    if not st['n']: return False
    return bool(st['med'] <= LINE_MED and st['silent'] <= LINE_SILENT)


def report(song_dir, with_stem=False, path=None):
    """Everything about one song. -> dict(song, sections[...], lines[...], ...). With `path` (a lines file of its own, which
    has no line_conf and no sections), the whole file is measured as one section."""
    song = json.load(open(os.path.join(song_dir, 'song.json'))); W = words(song_dir, path); v = vocal(song_dir)
    if path:
        n = len(json.load(open(path))); song = dict(song, line_conf=None, sections=[dict(id='own', start=0, end=0, lines=[0, n - 1], confidence=None)] if n else [])
    out = dict(slug=song.get('slug') or os.path.basename(os.path.normpath(song_dir)), aligned=song.get('aligned'), words=len(W))
    if not W or v is None:
        out.update(song=stats(v, []) if v else None, sections=[], lines=[]); return out
    T = np.array([t for _, _, t in W]); li = np.array([i for i, _, _ in W])
    out['song'] = stats(v, T)
    if with_stem: out['stem_lag'] = stem_lag(song_dir)
    conf = song.get('line_conf') or []
    L = []
    for k in range(int(li.max()) + 1):
        st = stats(v, T[li == k]); c = conf[k] if k < len(conf) else None
        L.append(dict(line=k, text=' '.join(w for i, w, _ in W if i == k), t=round(float(T[li == k][0]), 2) if st['n'] else None, conf=c, ok=line_ok(st, c), **st))
    out['lines'] = L
    S = []
    for s in song.get('sections', []):
        a, b = (s.get('lines') or [0, -1])
        st = stats(v, T[(li >= a) & (li <= b)])
        S.append(dict(id=s['id'], start=s['start'], end=s['end'], confidence=s.get('confidence'), ok=passes(st), span=[a, b],
                      lines_ok=sum(x['ok'] for x in L[a:b + 1]), lines=b - a + 1, **st))
    out['sections'] = S
    return out


_REP = {}


def _rep(song_dir, path=None):
    key = (os.path.abspath(song_dir), path)
    if key not in _REP:
        try: _REP[key] = report(song_dir, path=path)
        except Exception as e:                                                  # no stem, unreadable: nothing passes
            print('sync_check: %s: %s' % (song_dir, e), file=sys.stderr); _REP[key] = dict(sections=[], lines=[])
    return _REP[key]


def sections_ok(song_dir):
    """{section id: True/False} for a song: whether its measured sync passes the gate. Cached per process."""
    return {s['id']: s['ok'] for s in _rep(song_dir)['sections']}


def window_ok(song_dir, t0, t1, path=None):
    """Whether the words sung inside t0..t1 pass the gate (for stretches that are not a section, like footage windows)."""
    v = vocal(song_dir); W = [t for _, _, t in words(song_dir, path) if t0 <= t < t1]
    return bool(v is not None and passes(stats(v, W)))


def trusted_lines(song_dir, path=None):
    """Indices of the lines whose words may be shown one by one: the line measures well and its section passes."""
    r = _rep(song_dir, path); good = set()
    for sec in r['sections']:
        if sec['ok']:
            a, b = sec['span']; good |= {x['line'] for x in r['lines'][a:b + 1] if x['ok']}
    return good


def load_lines(song_dir, path=None):
    """lines.json as every lyric renderer should read it: [(end, [(word, time), ...]), ...], with the same handling of doubt
    everywhere. A line that is not trusted (trusted_lines) has every word at its first word's time, so it appears whole
    as it starts and never word by word on times nobody stands behind; words past the end of the vocal stem (where
    nothing was heard, so their times are guesses) are dropped."""
    p = path or os.path.join(song_dir, 'lines.json')
    try: raw = json.load(open(p))
    except (OSError, ValueError): return []
    ok = trusted_lines(song_dir, path); v = vocal(song_dir); end = v['dur'] - 0.3 if v else 1e9
    out = []
    for k, (e, ws) in enumerate(raw):
        ws = [(w, float(t)) for w, t in ws if float(t) < end]
        if not ws: continue
        if k not in ok: ws = [(w, ws[0][1]) for w, _ in ws]
        out.append((min(float(e), end + 0.3) if e > ws[-1][1] else ws[-1][1] + 0.6, ws))
    return out


def _ms(x): return '   -' if x is None else '%4d' % round(1000 * x)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('slugs', nargs='*'); ap.add_argument('--lines', action='store_true', help='print every line')
    ap.add_argument('--own', help='measure this lines file of the song instead of lines.json (e.g. studio/lofi/lines/<slug>.json)')
    ap.add_argument('--json'); ap.add_argument('--no-stem', action='store_true', help='skip the stem/master offset check')
    a = ap.parse_args(); root = os.path.join(HERE, 'songs')
    slugs = a.slugs or sorted(d for d in os.listdir(root) if os.path.exists(os.path.join(root, d, 'song.json')))
    allr = []
    print('song                     words  voiced  med_ms  signed  lag_ms  stem_ms  sections pass')
    for slug in slugs:
        r = report(os.path.join(root, slug) if not os.path.isdir(slug) else slug, with_stem=not a.no_stem, path=a.own); allr.append(r); s = r['song']
        if not r['words'] or not s: print('%-24s %5d   (no lyrics)' % (r['slug'], r['words'])); continue
        print('%-24s %5d  %5.0f%%   %s   %s   %s    %s     %d/%d' % (r['slug'], r['words'], 100 * (1 - s['silent']), _ms(s['med']), _ms(s['signed']), _ms(s['lag']),
              _ms(r.get('stem_lag')), sum(x['ok'] for x in r['sections']), len(r['sections'])))
        for x in r['sections']:
            print('    %s %6.1f-%6.1f  conf %.2f  words %3d  voiced %3.0f%%  med %s  chance %s  x%-4s lag %s  lines ok %d/%d  %s' % (
                x['id'], x['start'], x['end'], x['confidence'] or 0, x['n'], 100 * (1 - (x['silent'] or 0)), _ms(x['med']), _ms(x['chance']), x['contrast'], _ms(x['lag']), x['lines_ok'], x['lines'], 'PASS' if x['ok'] else 'fail'))
        if a.lines:
            for x in r['lines']:
                print('       %3d %6s  conf %4s  med %s  voiced %3.0f%%  %s  %s' % (x['line'], x['t'], x['conf'], _ms(x['med']), 100 * (1 - (x['silent'] or 0)), 'ok ' if x['ok'] else 'BAD', x['text'][:60]))
    if a.json:
        def clean(o):
            if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
            if isinstance(o, list): return [clean(v) for v in o]
            return o
        json.dump(clean(allr), open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
