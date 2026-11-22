#!/usr/bin/env python3
"""Measure each song's real beat grid from its drums and store it in song.json.

    python studio/beatmap.py [SLUG ...]

The tempo prep_song.py stored came from a generic beat tracker and was often a few BPM off (152 for a song played
at 156), so anything timed to "beat 32" drifted a whole beat away from the music within a few bars. This finds the
grid the drums actually sit on: the tempo (to 0.01 BPM) at which the kick and snare hits line up best on eighth
notes, the phase from where most of them land, and beat one of the bar from where the kicks land most. When no
single tempo fits (a tempo change, a live or swung part), it follows the drums beat by beat instead. It writes
tempo, offset_sec (the first downbeat), beat_times (every beat, in seconds into the master) and beat_fit (how
well the grid fits) into song.json. studio/mathviz/beat.py reads beat_times when they are there.
"""
import json, os, sys
import numpy as np, soundfile as sf, librosa

HERE = os.path.dirname(os.path.abspath(__file__)); SONGS = os.path.join(HERE, 'songs')
sys.path.insert(0, os.path.join(HERE, 'mathviz')); import beat


def fit(hits, guess):
    best = None
    for bpm in np.arange(guess - 6, guess + 6, 0.01):
        g = 30.0 / bpm; z = np.exp(2j * np.pi * hits / g).mean(); R = abs(z)
        if best is None or R > best[0]: best = (R, bpm, z)
    R, bpm, z = best; g = 30.0 / bpm; ph = (np.angle(z) / (2 * np.pi)) * g % g
    dev = np.abs(((hits - ph + g / 2) % g) - g / 2)
    return bpm, ph, R, float(np.median(dev) * 1000)


def song_map(slug):
    sd = os.path.join(SONGS, slug); song = json.load(open(os.path.join(sd, 'song.json')))
    path = os.path.join(sd, 'stems', 'Drums.ogg'); dur = sf.info(path).duration
    y, sr = beat.read(path, 0, dur); t, st = beat.onsets(y, sr); kinds = beat.drum_kinds(y, sr, t)
    kicks = np.array([x for x, k in zip(t, kinds) if k == 'kick']); snares = np.array([x for x, k in zip(t, kinds) if k == 'snare'])
    main = np.sort(np.r_[kicks, snares]); off0 = float(song.get('stems_start_sec') or 0)
    bpm, ph, R, med = fit(main, float(song.get('tempo') or 120))
    spb = 60.0 / bpm
    if R >= 0.35 and med <= 9.0:                                  # one steady grid: the record was made to a click
        # which eighth is the beat: the one more kicks and snares land on
        on = np.abs(((main - ph + spb / 2) % spb) - spb / 2) < spb / 4
        b0 = ph if on.mean() >= 0.5 else ph + spb / 2
        beats = np.arange(b0 % spb, dur, spb)
        how = 'grid'
    else:                                                         # follow the drums beat by beat
        env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=64)
        _, bf = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=64, bpm=bpm, tightness=300, units='time')
        beats = np.array(bf, float)
        for j, b in enumerate(beats):                             # each tracked beat onto the drum hit it stands for, if one is close
            if len(main):
                k = np.argmin(np.abs(main - b))
                if abs(main[k] - b) < 0.04: beats[j] = main[k]
        spb = float(np.median(np.diff(beats))) if len(beats) > 2 else spb; bpm = 60 / spb
        how = 'tracked'
    # beat one of the bar: of the four positions, the one most kicks fall on
    if len(kicks) and len(beats) > 8:
        idx = np.searchsorted(beats, kicks); idx = np.clip(idx, 1, len(beats) - 1)
        near = np.where(np.abs(beats[idx] - kicks) < np.abs(beats[idx - 1] - kicks), idx, idx - 1)
        close = np.abs(beats[near] - kicks) < spb / 6
        votes = np.bincount(near[close] % 4, minlength=4); down = int(np.argmax(votes))
    else: down = 0
    beats = beats[down:] if down < len(beats) else beats
    # how well the beats sit on the hits, over the whole song
    dev = [np.min(np.abs(main - b)) * 1000 for b in beats if len(main)]
    song.update(tempo=round(bpm, 2), offset_sec=round(float(beats[0]) + off0, 3),
                beat_times=[round(float(b) + off0, 4) for b in beats],
                beat_fit=dict(method=how, R=round(float(R), 2), median_ms=round(med, 1),
                              beats_on_a_hit=round(float(np.mean(np.array(dev) < 15)), 2) if dev else 0.0))
    json.dump(song, open(os.path.join(sd, 'song.json'), 'w'), indent=1)
    return song


if __name__ == '__main__':
    slugs = sys.argv[1:] or sorted(d for d in os.listdir(SONGS) if os.path.exists(os.path.join(SONGS, d, 'stems', 'Drums.ogg')))
    for s in slugs:
        j = json.load(open(os.path.join(SONGS, s, 'song.json'))); old = j.get('tempo')
        try: j = song_map(s)
        except Exception as exc: print('%-24s failed: %s' % (s, exc)); continue
        print('%-24s tempo %s -> %.2f  first downbeat %.3f s  %s' % (s, old, j['tempo'], j['offset_sec'], j['beat_fit']))
