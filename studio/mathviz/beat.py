"""What the music is doing at each video frame: stem loudness, kicks, snares, beats."""
import json, os
import numpy as np, soundfile as sf, librosa

SONGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'songs')
FPS = 30


def read(path, t0, t1, pad=0.15):
    """A stretch of a stem, by time. The stems are stored at their own sample rate (22.05 kHz), not the master's:
    reading them at 44.1 kHz offsets put every hit in the wrong place, so the rate is always taken from the file."""
    sr = sf.info(path).samplerate
    y, _ = sf.read(path, start=max(0, int(round(t0 * sr))), stop=int(round((t1 + pad) * sr)), dtype='float32', always_2d=True)
    return y.mean(1), sr


def onsets(y, sr, min_gap=0.06, sens=0.45):
    """Hits in a signal, to a few milliseconds: (times in seconds, strengths 0..1). Found as peaks of the spectral
    flux at ~3 ms resolution, then moved back to where each attack starts (the energy minimum before the peak), which
    is where the ear puts the hit; a peak-picked frame alone can land 10-30 ms late."""
    hop = 64 if sr <= 24000 else 128
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, n_fft=1024, center=True)
    if not len(env) or env.max() <= 0: return np.zeros(0), np.zeros(0)
    k = lambda sec: max(1, int(round(sec * sr / hop)))
    pk = librosa.util.peak_pick(env, pre_max=k(0.02), post_max=k(0.02), pre_avg=k(0.1), post_avg=k(0.1),
                                delta=sens * np.percentile(env, 95), wait=k(min_gap))
    if not len(pk): return np.zeros(0), np.zeros(0)
    # each peak, refined on the waveform itself: the hit starts where the signal's 1 ms envelope first climbs past a
    # quarter of the loudest point of the next 40 ms (searched from 20 ms before the flux peak)
    e = np.sqrt(np.convolve(y * y, np.ones(max(1, sr // 1000)) / max(1, sr // 1000), 'same'))
    t = []
    for p_ in pk:
        c = int(p_ * hop); a = max(0, c - int(0.02 * sr)); b = min(len(e), c + int(0.04 * sr))
        seg = e[a:b]
        if len(seg) < 4: t.append(c / sr); continue
        floor = np.percentile(seg, 10); top = seg.max()
        t.append((a + int(np.argmax(seg > floor + 0.25 * (top - floor)))) / sr)
    t = np.array(t)
    st = np.clip(env[pk] / (np.percentile(env[pk], 90) + 1e-9), 0, 1.5)
    keep = np.r_[True, np.diff(t) > min_gap * 0.6]                # two peaks refined onto one attack count once
    return t[keep], st[keep]


def drum_kinds(y, sr, times):
    """kick, snare or hat for each drum hit, from where its energy sits in the 40 ms after it starts."""
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=128)); f = librosa.fft_frequencies(sr=sr, n_fft=1024)
    lo, mid, hi = S[f < 150].sum(0), S[(f > 180) & (f < 2500)].sum(0), S[f > 5000].sum(0)
    nlo, nmid, nhi = (b / (np.median(b[b > 0]) + 1e-9) if (b > 0).any() else b for b in (lo, mid, hi))
    kinds = []
    for t in times:
        a = int(t * sr / 128); b = a + max(2, int(0.04 * sr / 128))
        L, M, Hh = nlo[a:b].max(initial=0), nmid[a:b].max(initial=0), nhi[a:b].max(initial=0)
        kinds.append('kick' if L >= max(M, 0.8 * Hh) else 'hat' if Hh > 2.0 * max(L, M) else 'snare')
    return kinds


def stretch(sd, stem, t0, t1, off=0.0):
    """A stem over a stretch of the song. Four songs' stems stop at 100 s (only their first half was prepared), and
    the band filmed themselves past that: where a stem does not reach, the master stands in, filtered towards what
    the stem would hold (the lows for the bass, the middle for the rest), so the video still moves to the music."""
    p = os.path.join(sd, 'stems', stem + '.ogg')
    if os.path.exists(p):
        y, sr = read(p, t0 - off, t1 - off)
        if len(y) >= 0.9 * (t1 - t0) * sr: return y, sr
    m = next(os.path.join(sd, 'master' + e) for e in ('.ogg', '.flac', '.wav') if os.path.exists(os.path.join(sd, 'master' + e)))
    y, sr = read(m, t0, t1)
    band = {'Bass': (None, 160.0), 'Other': (300.0, 4000.0)}.get(stem)
    if band and len(y) > 64:
        from scipy.signal import butter, sosfiltfilt
        lo, hi = band
        sos = butter(4, hi, 'low', fs=sr, output='sos') if lo is None else butter(2, [lo, hi], 'band', fs=sr, output='sos')
        y = sosfiltfilt(sos, y).astype(np.float32)
    return y, sr


def load(slug, t0, t1):
    sd = os.path.join(SONGS, slug); song = json.load(open(os.path.join(sd, 'song.json')))
    n = int(round((t1 - t0) * FPS)); out = dict(song=song, n=n, t0=t0, t1=t1)
    off = float(song.get('stems_start_sec') or 0.0)                 # where the stems' time zero sits in the master
    for stem in ('Vocals', 'Drums', 'Bass', 'Other'):
        y, sr = stretch(sd, stem, t0, t1, off)
        hop = sr / FPS
        rms = np.array([np.sqrt(np.mean(y[int(i * hop):int((i + 1) * hop)] ** 2) + 1e-12) for i in range(n)])   # exactly one value per video frame
        out[stem.lower()] = np.clip(rms / (np.percentile(rms, 97) + 1e-6), 0, 1.2)
        if stem == 'Drums':
            t, st = onsets(y, sr)
            keep = t < (t1 - t0); t, st = t[keep], st[keep]
            kinds = drum_kinds(y, sr, t)
            fr = lambda sel: np.array([int(round(x * FPS)) for x, k in zip(t, kinds) if k in sel], int)
            out['kicks'] = fr(('kick',)); out['snares'] = fr(('snare',)); out['hats'] = fr(('hat',))
            out['onsets'] = fr(('kick', 'snare'))                         # the hits you feel; hats are kept apart
            out['hit_times'] = [(float(x), k, float(s)) for x, k, s in zip(t, kinds, st)]
    spb = 60 / song['tempo']
    b0 = int(np.ceil(beat_of_time(song, t0)))
    out['beats'] = [(b, (time_of_beat(song, b) - t0) * FPS) for b in range(b0, b0 + 400) if time_of_beat(song, b) < t1]
    out['spb'] = spb
    return out


def project(slug, t0, t1, merge=0.03, heard=0.03):
    """The song's own hits, from its Ableton project rather than from listening to the mix: project_hits.json, made by
    studio/als_hits.py (every MIDI note and every attack in every audio clip of the arrangement) and lined up with the
    master by studio/project_sync.py. Returns {role: [(seconds from t0, strength 0..1)]} for kick, snare, hats, drums
    (kit loops and untyped pads), bass and melody, plus 'lead': the one melodic track with the most notes in this
    stretch (MIDI first), which is what a single moving thing can follow. Layered tracks playing the same hit (two kick
    layers, a doubled synth) count once. None when the song has no project."""
    path = os.path.join(SONGS, slug, 'project_hits.json')
    if not os.path.exists(path): return None
    P = json.load(open(path)); spb = 60.0 / P['tempo']; a, b = P.get('scale', 1.0), P['offset_sec']
    out = {r: [] for r in ('kick', 'snare', 'hats', 'drums', 'bass', 'melody')}; leads = []
    for tr in P['tracks']:
        if not tr['on']: continue
        # a track is trusted only if its hits are heard: enough of them land on an attack in the separated stems (a
        # MIDI note is exact, so a lower bar; an audio track's attacks were found by ear, so a higher one)
        if max((tr.get('match') or {'x': 1.0}).values()) < (0.5 if 'notes' in tr else 0.6): continue
        mine = []
        if 'notes' in tr:
            for beat, key, vel in tr['notes']:
                t = a * beat * spb + b - t0
                if 0 <= t < t1 - t0:
                    role = tr['role'] if tr['role'] != 'drums' else {'perc': 'drums'}.get(tr['pads'].get(str(key), 'perc'), tr['pads'].get(str(key)))
                    if role in out: out[role].append((t, vel / 127.0)); mine.append((t, vel / 127.0))
        else:
            for beat, st in tr['hits']:
                t = a * beat * spb + b - t0
                if 0 <= t < t1 - t0 and tr['role'] in out: out[tr['role']].append((t, float(st))); mine.append((t, float(st)))
        if tr['role'] == 'melody' and mine: leads.append(('notes' in tr, len(mine), mine))
    def dedupe(h):
        h = sorted(h); res = []
        for t, st in h:
            if res and t - res[-1][0] < merge: res[-1] = (res[-1][0], max(res[-1][1], st))
            else: res.append((t, st))
        return res
    out = {k: dedupe(v) for k, v in out.items()}
    out['lead'] = dedupe(max(leads, key=lambda l: (l[0], l[1]))[2]) if leads else []
    if heard:
        # each hit kept only if it is heard in this stretch of the released song: an attack in the stem it belongs to
        # within 30 ms. The time kept is still the project's; the stems only confirm that the part is audible here
        # (a muted clip, a fader pulled down, a part cut in the final mix all drop out)
        sd = os.path.join(SONGS, slug); s0 = float(json.load(open(os.path.join(sd, 'song.json'))).get('stems_start_sec') or 0)
        att = {}
        for stem in ('Drums', 'Bass', 'Other'):
            f = os.path.join(sd, 'stems', stem + '.ogg')
            if os.path.exists(f): y, sr = read(f, t0 - s0, t1 - s0); att[stem] = onsets(y, sr)[0]
        where = {'kick': ('Drums',), 'snare': ('Drums',), 'hats': ('Drums',), 'drums': ('Drums',), 'bass': ('Bass', 'Drums'),
                 'melody': ('Other', 'Bass', 'Drums'), 'lead': ('Other', 'Bass', 'Drums')}
        for role, hs in out.items():
            ref = np.sort(np.concatenate([att[k] for k in where[role] if k in att] or [np.zeros(0)]))
            if len(ref): out[role] = [(t, st) for t, st in hs if np.min(np.abs(ref - t)) <= heard]
    return out


# The song's beats, as measured from its drums by studio/beatmap.py (beat_times, seconds into the master; beat 0 is
# the first downbeat). Songs without a measured map fall back to a straight grid from tempo and offset_sec.
def _grid(song):
    bt = song.get('beat_times')
    if bt and len(bt) > 2: return np.asarray(bt, float)
    spb = 60 / song['tempo']; return song['offset_sec'] + spb * np.arange(0, 4000)


def time_of_beat(song, b):
    g = _grid(song); spb = 60 / song['tempo']
    if b < 0: return float(g[0] + b * spb)
    if b > len(g) - 1: return float(g[-1] + (b - len(g) + 1) * spb)
    i = int(np.floor(b)); f = b - i
    return float(g[i] + f * (g[min(i + 1, len(g) - 1)] - g[i])) if i + 1 < len(g) else float(g[i])


def beat_of_time(song, t):
    g = _grid(song); spb = 60 / song['tempo']
    if t <= g[0]: return float((t - g[0]) / spb)
    if t >= g[-1]: return float(len(g) - 1 + (t - g[-1]) / spb)
    i = int(np.searchsorted(g, t) - 1); return float(i + (t - g[i]) / (g[i + 1] - g[i]))


def hits(frames, n, decay=6.0):
    """A 0..1 envelope that jumps to 1 on each hit and decays."""
    e = np.zeros(n); t = np.arange(n) / FPS
    for f in frames:
        m = np.arange(n) >= f
        e[m] = np.maximum(e[m], np.exp(-decay * (t[m] - f / FPS)))
    return e


def audio_clip(slug, t0, t1, out):
    sd = os.path.join(SONGS, slug)
    os.system('ffmpeg -loglevel error -y -ss %.3f -t %.3f -i %s -af "afade=t=in:d=0.15,afade=t=out:st=%.3f:d=0.6" -c:a aac -b:a 192k %s'
              % (t0, t1 - t0, os.path.join(sd, 'master.ogg'), t1 - t0 - 0.6, out))
