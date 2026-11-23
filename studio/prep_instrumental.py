#!/usr/bin/env python3
"""Turn one instrumental song (no vocals to time) into a song directory the picture styles can render.

    python studio/prep_instrumental.py --master song.wav --out studio/songs/<slug> --title "Recess (Rewind)" --track 4

prep_song.py cuts a song into sections from its sung lines; an instrumental has none, so here the sections come from
the beat grid instead: runs of whole bars, 14-24 seconds long, laid end to end over the loud part of the song.
They are marked confidence 0, which keeps the lyric styles (band, producer, type, lyric) off them: only the
picture styles, which take any stretch, ever use them (studio/nightly.py, stretches()). lines.json is empty.

Writes master.ogg, stems/ (Drums, Bass, Other from the master's percussive part, low end and the rest; Vocals
silent), lines.json and song.json, then runs beatmap.py for the real grid before laying out the sections.
"""
import argparse, json, os, subprocess, sys
import numpy as np, soundfile as sf, librosa
from scipy.signal import butter, sosfiltfilt

HERE = os.path.dirname(os.path.abspath(__file__)); SR = 22050


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ('master', 'out', 'title'): ap.add_argument('--' + k, required=True)
    ap.add_argument('--track', type=int, default=1); ap.add_argument('--tracks-total', type=int, default=15)
    ap.add_argument('--artist', default='Close Quarters'); ap.add_argument('--album', default='EDUCATION')
    a = ap.parse_args(); slug = os.path.basename(os.path.normpath(a.out)); st = os.path.join(a.out, 'stems')
    os.makedirs(st, exist_ok=True)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', a.master, '-c:a', 'libvorbis', '-q:a', '5', os.path.join(a.out, 'master.ogg')], check=True)
    y, s = sf.read(a.master, always_2d=True, dtype='float32'); y = librosa.resample(y.mean(1), orig_sr=s, target_sr=SR); dur = len(y) / SR
    harm, perc = librosa.effects.hpss(y, margin=2.0)
    bass = sosfiltfilt(butter(4, 170, 'low', fs=SR, output='sos'), harm).astype('float32')
    for name, sig in (('Vocals', np.zeros_like(y) + 1e-5), ('Drums', perc), ('Bass', bass), ('Other', harm - bass)):
        tmp = os.path.join(st, name + '.wav'); sf.write(tmp, sig, SR)
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-ac', '1', '-ar', str(SR), '-c:a', 'libvorbis', '-q:a', '3', os.path.join(st, name + '.ogg')], check=True)
        os.remove(tmp)
    tempo, beats = librosa.beat.beat_track(y=perc, sr=SR, units='time'); tempo = float(np.atleast_1d(tempo)[0])
    if tempo < 95: tempo *= 2
    json.dump([], open(os.path.join(a.out, 'lines.json'), 'w'))
    song = dict(slug=slug, title=a.title, artist=a.artist, album=a.album, track=a.track, tracks_total=a.tracks_total, key='', instrumental=True,
                tempo=round(tempo, 2), offset_sec=round(float(beats[0]) if len(beats) else 0.0, 3), stems_start_sec=0.0, sections=[])
    json.dump(song, open(os.path.join(a.out, 'song.json'), 'w'), indent=1)
    subprocess.run([sys.executable, os.path.join(HERE, 'beatmap.py'), slug], check=True)
    song = json.load(open(os.path.join(a.out, 'song.json')))
    bt = song.get('beat_times') or list(np.arange(song['offset_sec'], dur, 60 / song['tempo']))
    bar = 4 * 60 / song['tempo']; n = max(4, int(round(18 / bar)))                   # whole bars, about 18 seconds
    while n * bar > 24: n -= 1
    while n * bar < 14: n += 1
    hop = SR // 2; env = np.array([np.sqrt(np.mean(y[i:i + hop] ** 2)) for i in range(0, len(y), hop)])
    loud = lambda t0, t1: float(env[int(t0 * 2):int(t1 * 2) + 1].mean()) if t1 > t0 else 0.0
    floor = 0.35 * np.percentile(env, 90); secs, rep, k = [], [], 0
    downs = bt[::4]
    while k + n < len(downs):
        t0, t1 = round(float(downs[k]), 2), round(float(downs[k + n]), 2)
        if loud(t0, t1) >= floor:
            secs.append(dict(id='s%02d' % (len(secs) + 1), start=t0, end=t1, lines=[], confidence=0.0))
            rep.append('%s  %6.1f-%6.1f  %4.1fs  instrumental' % (secs[-1]['id'], t0, t1, t1 - t0))
        k += n
    song['sections'] = secs
    json.dump(song, open(os.path.join(a.out, 'song.json'), 'w'), indent=1)
    open(os.path.join(a.out, 'report.txt'), 'w').write('\n'.join(rep) + '\n'); print('\n'.join(rep))


if __name__ == '__main__': main()
