#!/usr/bin/env python3
"""Line an Ableton project's hits (studio/als_hits.py) up with the released song, and say what each track is.

    python studio/project_sync.py SLUG HITS.json[.gz]

1. Where the project sits in the master. Every hit in the project (MIDI notes and audio-clip attacks) is compared
   with the attacks in the song's separated stems: the shift that puts the most of them within a few milliseconds
   of each other is where project time zero sounds in the master, and a straight-line fit through the matched pairs
   gives the exact shift and any tiny speed difference (a master bounced or resampled a hair off tempo).
2. What each track is. "Kick 2" says what it is; "14-Audio" does not. Each track's hits are compared with each
   stem's attacks: a track whose hits land on the drum stem's kicks is a kick, on the bass stem's notes is bass, and
   so on. Drum-rack pads are labelled the same way, one pad at a time.

Writes studio/songs/SLUG/project_hits.json (every hit, in project beats, per track, with its role) and the fit into
song.json as project / project_offset_sec / project_scale / project_fit. studio/mathviz/beat.py's project() turns
them into hit times for a stretch of the song.
"""
import gzip, json, os, sys
import numpy as np, soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'mathviz'))
import beat as audio

TOL = 0.025                       # a project hit "lands" on a stem attack within 25 ms (the attacks are found to a few ms)


def events(track, tempo):
    spb = 60.0 / tempo
    if track['notes']: return np.array([n[0] * spb for n in track['notes']]), np.array([n[3] / 127 for n in track['notes']]), [n[2] for n in track['notes']]
    return np.array([h[0] * spb for h in track['hits']]), np.array([h[1] for h in track['hits']]), None


def backbeat(t, tempo):
    """Share of these hits (seconds of project time) that fall on beats 2 and 4 of a bar."""
    if not len(t): return 0.0
    q = (np.asarray(t) * tempo / 60.0) % 4
    return float(np.mean((np.abs(q - 1) < 0.08) | (np.abs(q - 3) < 0.08)))


def near(a, b, tol):
    """For each time in a, is there one in b within tol (b sorted)?"""
    if not len(a) or not len(b): return np.zeros(len(a), bool), np.full(len(a), np.inf)
    i = np.clip(np.searchsorted(b, a), 1, len(b) - 1)
    d = np.minimum(np.abs(b[i] - a), np.abs(b[i - 1] - a))
    j = np.where(np.abs(b[i] - a) < np.abs(b[i - 1] - a), i, i - 1)
    return d <= tol, b[j] - a


def sync(slug, hits_path):
    sd = os.path.join(audio.SONGS, slug); song = json.load(open(os.path.join(sd, 'song.json')))
    P = json.load(gzip.open(hits_path) if hits_path.endswith('.gz') else open(hits_path))
    tempo = P['tempo']; s0 = float(song.get('stems_start_sec') or 0)
    stems = {}
    for name in ('Drums', 'Bass', 'Other', 'Vocals'):
        path = os.path.join(sd, 'stems', name + '.ogg')
        if not os.path.exists(path): continue
        y, sr = audio.read(path, 0, sf.info(path).duration)
        t, st = audio.onsets(y, sr)
        kinds = audio.drum_kinds(y, sr, t) if name == 'Drums' else None
        stems[name] = dict(t=t + s0, kinds=np.array(kinds) if kinds else None)
    allon = np.sort(np.concatenate([v['t'] for k, v in stems.items() if k != 'Vocals']))

    # 1. the shift: a histogram of (stem attack - project hit) over every pair, 5 ms bins
    ev = np.unique(np.round(np.concatenate([events(t, tempo)[0] for t in P['tracks'] if t['on'] and t['role'] != 'vocal'] or [np.zeros(0)]), 3))
    best, score = 0.0, -1
    lo, hi = -600.0, 600.0; edges = np.arange(lo, hi + 0.005, 0.005); hist = np.zeros(len(edges) - 1)
    for chunk in np.array_split(ev, max(1, len(ev) // 400)):
        d = (allon[None, :] - chunk[:, None]).ravel(); d = d[(d > lo) & (d < hi)]
        hist += np.histogram(d, edges)[0]
    sm = np.convolve(hist, [1, 2, 1], 'same'); k = int(np.argmax(sm)); best = edges[k] + 0.0025
    # 2. refine: a straight line through the matched pairs (shift and speed), twice, narrowing the window
    a, b = 1.0, best
    for tol in (0.04, TOL):
        ok, dd = near(a * ev + b, allon, tol)
        if ok.sum() < 20: break
        x = ev[ok]; yv = a * ev[ok] + b + dd[ok]
        a, b = np.polyfit(x, yv, 1)
        if abs(a - 1) > 0.01: a, b = 1.0, float(np.median(yv - x))
    ok, dd = near(a * ev + b, allon, TOL)
    span = (a * ev + b > allon.min() - 1) & (a * ev + b < allon.max() + 1)
    fit = dict(offset_sec=round(float(b), 4), scale=round(float(a), 6), matched=round(float(ok[span].mean()) if span.any() else 0, 3),
               median_ms=round(float(np.median(np.abs(dd[ok])) * 1000), 1) if ok.any() else None, hits=int(span.sum()))

    # 3. what each track is
    out = []
    for tr in P['tracks']:
        t, st, keys = events(tr, tempo)
        m = a * t + b
        role = tr['role']; stats = {}
        for name, v in stems.items():
            okk, _ = near(m, v['t'], TOL); inside = (m > v['t'].min()) & (m < v['t'].max())
            stats[name] = round(float(okk[inside].mean()), 3) if inside.sum() >= 8 else 0.0
        best_stem = max(stats, key=stats.get) if stats else None
        if role == 'melody' and stats.get('Bass', 0) >= 0.5 and stats['Bass'] > stats.get('Other', 0) + 0.2:
            role = 'bass'                                               # a synth named for its plug-in, playing the bass line
        if role in ('other', 'drums') and best_stem and stats[best_stem] >= 0.5:
            if best_stem == 'Drums' and not keys:
                okk, dd2 = near(m, stems['Drums']['t'], TOL)
                idx = np.searchsorted(stems['Drums']['t'], m[okk] + dd2[okk])
                ks = stems['Drums']['kinds'][np.clip(idx, 0, len(stems['Drums']['kinds']) - 1)]
                if len(ks):
                    vals, cnt = np.unique(ks, return_counts=True); top = vals[np.argmax(cnt)]
                    role = {'kick': 'kick', 'snare': 'snare', 'hat': 'hats'}[top] if cnt.max() >= 0.6 * len(ks) else 'drums'
                    if role in ('kick', 'drums') and backbeat(t, tempo) >= 0.55: role = 'snare'
            elif best_stem != 'Drums':
                role = {'Bass': 'bass', 'Other': 'melody', 'Vocals': 'vocal'}[best_stem]
        pads = {}
        if keys and role == 'drums' and 'Drums' in stems:                 # each drum-rack pad on its own
            for key in sorted(set(keys)):
                sel = np.array([k == key for k in keys]); mk = m[sel]
                okk, dd2 = near(mk, stems['Drums']['t'], TOL)
                gm = tr.get('pads', {}).get(str(key), 'perc'); heard = None
                if okk.sum() >= 4:
                    idx = np.searchsorted(stems['Drums']['t'], mk[okk] + dd2[okk])
                    vals, cnt = np.unique(stems['Drums']['kinds'][np.clip(idx, 0, len(stems['Drums']['kinds']) - 1)], return_counts=True)
                    heard = {'kick': 'kick', 'snare': 'snare', 'hat': 'hats'}[vals[np.argmax(cnt)]]
                tk = t[sel]; per_beat = len(tk) / max(1.0, (tk.max() - tk.min()) * tempo / 60) if len(tk) > 1 else 0
                if backbeat(tk, tempo) >= 0.55: pads[str(key)] = 'snare'          # on 2 and 4: a snare or clap, whatever else rings with it
                elif heard == 'hats' or gm == 'hats' or per_beat >= 1.8: pads[str(key)] = 'hats'
                elif heard == 'kick' or gm == 'kick': pads[str(key)] = 'kick'
                else: pads[str(key)] = heard or gm
        rec = dict(name=tr['name'], role=role, on=tr['on'], match=stats)
        if keys is not None: rec['notes'] = [[n[0], n[2], n[3]] for n in tr['notes']]; rec['pads'] = pads
        else: rec['hits'] = tr['hits']
        out.append(rec)
    json.dump(dict(project=P['project'], tempo=tempo, offset_sec=fit['offset_sec'], scale=fit['scale'], tracks=out),
              open(os.path.join(sd, 'project_hits.json'), 'w'), separators=(',', ':'))
    song.update(project=P['project'], project_offset_sec=fit['offset_sec'], project_scale=fit['scale'], project_fit=fit)
    json.dump(song, open(os.path.join(sd, 'song.json'), 'w'), indent=1, ensure_ascii=False)
    return fit, out


if __name__ == '__main__':
    if len(sys.argv) < 3: sys.exit(__doc__)
    fit, tracks = sync(sys.argv[1], sys.argv[2])
    print(sys.argv[1], fit)
    for t in tracks:
        n = len(t.get('notes') or t.get('hits') or [])
        print('  %-28s %-6s %-3s %5d  %s %s' % (t['name'][:28], t['role'], 'on' if t['on'] else 'OFF', n,
                                                ' '.join('%s %.2f' % (k[0], v) for k, v in t['match'].items()), t.get('pads') or ''))
