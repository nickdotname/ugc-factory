"""What the music is doing at each video frame: stem loudness, kicks, snares, beats."""
import json, os
import numpy as np, soundfile as sf, librosa

SONGS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'songs')
FPS = 30


def load(slug, t0, t1):
    sd = os.path.join(SONGS, slug); song = json.load(open(os.path.join(sd, 'song.json')))
    n = int(round((t1 - t0) * FPS)); out = dict(song=song, n=n, t0=t0, t1=t1)
    for stem in ('Vocals', 'Drums', 'Bass', 'Other'):
        y, sr = sf.read(os.path.join(sd, 'stems', stem + '.ogg'), start=int(t0 * 44100), stop=int(t1 * 44100) + 4410, dtype='float32')
        if y.ndim > 1: y = y.mean(1)
        hop = sr // FPS
        rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop, center=True)[0][:n]
        rms = np.pad(rms, (0, max(0, n - len(rms))))
        out[stem.lower()] = np.clip(rms / (np.percentile(rms, 97) + 1e-6), 0, 1.2)
        if stem == 'Drums':
            on = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop, units='frames', backtrack=False, delta=0.12)
            spec = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
            f = librosa.fft_frequencies(sr=sr, n_fft=2048)
            low = spec[f < 150].sum(0); mid = spec[(f > 1500) & (f < 6000)].sum(0)
            kicks, snares = [], []
            for o in on:
                if o >= n: continue
                (kicks if low[o] / (np.median(low) + 1e-6) > mid[o] / (np.median(mid) + 1e-6) else snares).append(o)
            out['kicks'] = np.array(kicks, int); out['snares'] = np.array(snares, int); out['onsets'] = np.array([o for o in on if o < n], int)
    spb = 60 / song['tempo']
    b0 = int(np.ceil((t0 - song['offset_sec']) / spb))
    out['beats'] = [(b, (b * spb + song['offset_sec'] - t0) * FPS) for b in range(b0, b0 + 400) if b * spb + song['offset_sec'] < t1]
    out['spb'] = spb
    return out


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
