#!/usr/bin/env python3
"""Every hit in an Ableton project, read from the arrangement itself.

    python studio/als_hits.py PROJECT.als OUT.json

Two kinds of hit, both in the project's own beats:
  notes  the notes of every MIDI clip in the arrangement (loops unrolled, disabled notes and clips left out)
  hits   the attacks inside every audio clip (a frozen drum rack, a sampled kick, a bounced 808...), found in the
         audio file the clip plays and carried through the clip's warp markers, start offset and loop to where they
         sound in the arrangement
Every track gets a role from its name and, for drum racks, from the pads its notes play: kick, snare, hats, drums
(a whole kit), bass, melody, vocal or other. Muted tracks (and tracks in a muted group) are kept but marked off.

Run it where the project folder is: it opens the audio files the clips point at (numpy and ffmpeg needed).
studio/project_sync.py then lines the project up with the released master and writes the song's arrangement.json.
"""
import gzip, json, os, re, subprocess, sys
import xml.etree.ElementTree as ET
import numpy as np

SR, HOP = 22050, 64
ROLES = [('kick', r'kick|kik|\bbd\b|bass ?drum'), ('snare', r'snare|snr|clap|\brim'),
         ('hats', r'\bhh\b|\bhats?\b|hihat|hi-hat|cymbal|\bride\b|crash|shaker|tamb|\bperc|\bopen\b'),
         ('bass', r'808|bass|\bsub\b|\bsubs\b|reese'),
         ('drums', r'drum|\bkit\b|break|lex_luger|rattle|machine|\bbeat\b|\bloop'),
         ('vocal', r'vox|vocal|voice|recording|verse|hook|adlib|\brap\b|sing|chorus'),
         ('melody', r'serum|operator|analog|wavetable|piano|string|flute|keys|\bpad\b|lead|bell|electric|kontakt|'
                    r'synth|organ|guitar|gtr|rhodes|pluck|arp|choir|brass|sax|horn|mellow|drift|meld|simpler|sampler')]
GM = {35: 'kick', 36: 'kick', 37: 'snare', 38: 'snare', 39: 'snare', 40: 'snare',
      42: 'hats', 44: 'hats', 46: 'hats', 49: 'hats', 51: 'hats', 52: 'hats', 53: 'hats', 55: 'hats', 57: 'hats', 59: 'hats'}


def val(el, path, default=None, cast=float):
    e = el.find(path)
    return cast(e.get('Value')) if e is not None and e.get('Value') is not None else default


def role_of(name):
    n = re.sub(r'^\d+[-\s]*', '', name.lower())
    for role, pat in ROLES:
        if re.search(pat, n): return role
    return 'other'


# ---------------------------------------------------------------- MIDI
def midi_notes(tr):
    notes = []
    for c in tr.findall('.//ArrangerAutomation/Events/MidiClip'):
        if val(c, 'Disabled', 'false', str) == 'true': continue
        s, e = val(c, 'CurrentStart'), val(c, 'CurrentEnd')
        L = c.find('Loop'); ls_, le = val(L, 'LoopStart'), val(L, 'LoopEnd'); rel = val(L, 'StartRelative', 0.0)
        lon = val(L, 'LoopOn', 'false', str) == 'true'
        raw = []
        for kt in c.iter('KeyTrack'):
            key = val(kt, 'MidiKey', 0, lambda v: int(float(v)))
            for n in kt.iter('MidiNoteEvent'):
                if n.get('IsEnabled') == 'false': continue
                raw.append((float(n.get('Time')), float(n.get('Duration')), key, float(n.get('Velocity'))))
        first = ls_ + rel
        for nt, nd, k, v in raw:
            if lon and le > ls_:
                ll = le - ls_
                # the clip plays from `first` to the loop end, then the loop over and over
                cands = []
                if first <= nt < le: cands.append(s + nt - first)
                if ls_ <= nt < le:
                    a = s + (le - first) + (nt - ls_)
                    while a < e: cands.append(a); a += ll
                for a in cands:
                    if s - 1e-6 <= a < e - 1e-6: notes.append((round(a, 4), round(min(nd, e - a), 4), k, v))
            else:
                a = s + nt - first
                if s - 1e-6 <= a < e - 1e-6: notes.append((round(a, 4), round(min(nd, e - a), 4), k, v))
    return sorted(set(notes))


# ---------------------------------------------------------------- audio
_cache = {}


def decode(path):
    if path not in _cache:
        r = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True)
        _cache[path] = np.frombuffer(r.stdout, np.float32) if r.returncode == 0 else None
    return _cache[path]


def onsets(y, jump_db=8.0, min_gap=0.05):
    """Attack times (s) and strengths in one audio file. The level is followed in 3 ms steps against a held envelope
    that falls 0.6 dB a step (about 200 dB a second, faster than any real decay): a sustained or decaying sound stays
    under it, ripples and all, and only a fresh attack jumps clear of it. Each attack is placed where the level first
    passes a quarter of the way from what came before it to its peak."""
    if y is None or len(y) < SR // 10: return np.zeros(0), np.zeros(0)
    n = len(y) // HOP
    e = np.sqrt(np.mean(y[:n * HOP].reshape(n, HOP) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(e + 1e-9)
    floor = np.percentile(db, 99.5) - 45                               # attacks quieter than this are noise
    held = np.empty(n); jump = np.empty(n); h = floor - 10
    for i in range(n):
        h -= 0.6; jump[i] = db[i] - h; h = max(h, db[i]); held[i] = h
    gap = int(min_gap * SR / HOP); out_t, out_s = [], []; last = -gap
    for i in np.nonzero((jump >= jump_db) & (db >= floor))[0]:
        if i - last < gap: continue
        j0 = max(0, i - 3); before = e[j0:i + 1].min(); top = e[i:i + 10].max()
        k = j0 + int(np.argmax(e[j0:i + 10] >= before + 0.25 * (top - before)))
        out_t.append(k * HOP / SR); out_s.append(float(top)); last = i
    s = np.array(out_s)
    return np.array(out_t), (s / s.max() if len(s) else s)


def audio_hits(tr, proj_dir, tempo):
    hits = []
    for c in tr.findall('.//ArrangerAutomation/Events/AudioClip'):
        if val(c, 'Disabled', 'false', str) == 'true': continue
        ref = c.find('.//SampleRef/FileRef')
        if ref is None: continue
        path = val(ref, 'Path', '', str)
        if not path or not os.path.exists(path):
            rel = val(ref, 'RelativePath', '', str)
            path = os.path.join(proj_dir, rel) if rel else ''
        if not path or not os.path.exists(path): continue
        t, st = onsets(decode(path))
        if not len(t): continue
        s, e = val(c, 'CurrentStart'), val(c, 'CurrentEnd')
        L = c.find('Loop'); ls_, le = val(L, 'LoopStart'), val(L, 'LoopEnd'); rel = val(L, 'StartRelative', 0.0)
        lon = val(L, 'LoopOn', 'false', str) == 'true'
        warped = val(c, 'IsWarped', 'true', str) == 'true'
        wm = sorted((float(m.get('SecTime')), float(m.get('BeatTime'))) for m in c.iter('WarpMarker'))
        if warped and len(wm) >= 2:
            sec = np.array([m[0] for m in wm]); bt = np.array([m[1] for m in wm])
            slope_lo = (bt[1] - bt[0]) / max(1e-9, sec[1] - sec[0]); slope_hi = (bt[-1] - bt[-2]) / max(1e-9, sec[-1] - sec[-2])
            pos = np.interp(t, sec, bt)                                  # the attacks in the clip's own beats
            pos = np.where(t < sec[0], bt[0] + (t - sec[0]) * slope_lo, pos)
            pos = np.where(t > sec[-1], bt[-1] + (t - sec[-1]) * slope_hi, pos)
            unit = 1.0
        else:
            pos = t; unit = 60.0 / tempo                                 # unwarped: the clip runs in seconds
        first = ls_ + rel; span = (e - s) * unit                         # how much of the clip plays, in its own units
        for p, k in zip(pos, st):
            cands = []
            if lon and le > ls_:
                ll = le - ls_
                if first <= p < le: cands.append(p - first)
                if ls_ <= p < le:
                    q = (le - first) + (p - ls_)
                    while q < span: cands.append(q); q += ll
            elif p >= first:
                cands.append(p - first)
            for q in cands:
                a = s + q / unit
                if s - 1e-6 <= a < e - 1e-6: hits.append((round(a, 4), round(float(k), 3)))
    return sorted(set(hits))


# ---------------------------------------------------------------- the project
def load(path):
    root = ET.fromstring(gzip.open(path, 'rb').read()); ls = root.find('LiveSet')
    t = ls.find('.//MainTrack//Tempo/Manual')
    if t is None: t = ls.find('.//MasterTrack//Tempo/Manual')
    tempo = float(t.get('Value')); proj_dir = os.path.dirname(os.path.abspath(path))
    tracks, muted_groups = [], set()
    for tr in ls.find('Tracks'):
        tid = tr.get('Id'); name = val(tr, 'Name/EffectiveName', '', str)
        on = val(tr, 'DeviceChain/Mixer/Speaker/Manual', 'true', str) == 'true'
        group = val(tr, 'TrackGroupId', -1, lambda v: int(float(v)))
        if tr.tag == 'GroupTrack':
            if not on or str(group) in muted_groups: muted_groups.add(str(tid))
            continue
        on = on and str(group) not in muted_groups
        notes = midi_notes(tr) if tr.tag == 'MidiTrack' else []
        hits = audio_hits(tr, proj_dir, tempo) if tr.tag == 'AudioTrack' else []
        if not notes and not hits: continue
        role = role_of(name)
        keys = sorted(set(n[2] for n in notes))
        if notes and role in ('drums', 'other') and len(keys) > 1:
            role = 'drums'                                               # a drum rack: kept whole, split per pad below
        tracks.append(dict(name=name, kind=tr.tag, on=on, role=role, notes=notes, hits=hits,
                           pads={str(k): GM.get(k, 'perc') for k in keys} if role == 'drums' and notes else {}))
    return dict(project=os.path.basename(path), tempo=tempo, tracks=tracks)


if __name__ == '__main__':
    if len(sys.argv) < 3: sys.exit(__doc__)
    out = load(sys.argv[1]); json.dump(out, open(sys.argv[2], 'w'), separators=(',', ':'))
    for t in out['tracks']:
        print('%-4s %-26s %-6s %-3s notes %5d  hits %5d' % (t['kind'][:4], t['name'][:26], t['role'], 'on' if t['on'] else 'OFF', len(t['notes']), len(t['hits'])))
