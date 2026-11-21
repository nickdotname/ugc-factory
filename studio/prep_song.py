#!/usr/bin/env python3
"""Turn one song into a song directory lyric_video.py can render.

    python studio/prep_song.py --master song.wav --lyrics lyrics.txt --out studio/songs/<slug> \\
        --title "Full Ride" --track 8 [--vox vocals.flac --inst instrumental.flac] [--words words.json]

lyrics.txt is plain text, one lyric line per line. A line may start with the time it
begins (m:ss); lines without one are placed between the timed lines around them. Only
the words matter: the tool listens to the vocal and times every word itself.

What it writes: song.json (tempo, sections), lines.json (every word with its time),
stems/ (Vocals, Drums, Bass, Other, as small mono files for the visuals) and
report.txt (how confidently each section was timed). Sections are the 14-24 second
stretches a video is cut from; `render_all.py` renders one video per section.

--vox / --inst reuse an existing vocal / instrumental split; without them the tool
runs audio-separator. --words reuses word timings; without it the tool runs Whisper.
The drum, bass and "other" stems are estimated from the instrumental (percussive part,
low end, the rest). They drive waveforms on screen, not anything you hear.
"""
import argparse, difflib, json, os, re, subprocess, sys, tempfile
import numpy as np, soundfile as sf, librosa
from scipy.signal import butter, sosfiltfilt

SR = 22050
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())

def load_mono(path, sr=SR):
    y, s = sf.read(path, always_2d=True, dtype='float32'); return librosa.resample(y.mean(1), orig_sr=s, target_sr=sr)

def split_two(master, workdir):
    extra = ['--model_file_dir', os.environ['CQ_MODEL_DIR']] if os.environ.get('CQ_MODEL_DIR') else []
    subprocess.run(['audio-separator', master, '--model_filename', '2_HP-UVR.pth', '--output_dir', workdir, '--output_format', 'FLAC', *extra], check=True, capture_output=True)
    fs = os.listdir(workdir); vox = [f for f in fs if 'Vocals' in f][0]; inst = [f for f in fs if 'Instrumental' in f][0]
    return os.path.join(workdir, vox), os.path.join(workdir, inst)

def whisper_words(vox):
    from faster_whisper import WhisperModel
    m = WhisperModel('small.en', device='cpu', compute_type='int8')
    seg, _ = m.transcribe(load_mono(vox, 16000), word_timestamps=True, vad_filter=False, beam_size=5, condition_on_previous_text=False)
    return [[x.word.strip(), round(x.start, 2), round(x.end, 2)] for s in seg for x in s.words]

def parse_lyrics(text):
    """-> chunks: [(anchor_seconds, [line, ...])]; a line is a list of words."""
    chunks = []
    for raw in text.splitlines():
        raw = raw.replace('[?]', ' ').strip()
        if not raw: continue
        m = re.match(r"^(\d+):(\d\d)\s*(.*)$", raw)
        if m:
            words = m.group(3).split()
            if words: chunks.append((int(m.group(1)) * 60 + int(m.group(2)), [words]))
        elif chunks:
            chunks[-1][1].append(raw.split())
    return chunks

def align(chunks, words, dur):
    """Give every lyric word a time, using the heard words inside each chunk's window."""
    lines = []
    for ci, (t0, clines) in enumerate(chunks):
        t1 = chunks[ci + 1][0] if ci + 1 < len(chunks) else min(dur, t0 + 30)
        doc = [w for l in clines for w in l]; dn = [norm(w) for w in doc]
        heard = [w for w in words if t0 - 1.2 <= w[1] < t1 + 1.2]; hn = [norm(w[0]) for w in heard]
        times = [None] * len(doc); ends = [None] * len(doc)
        for a, b, n in difflib.SequenceMatcher(None, dn, hn, autojunk=False).get_matching_blocks():
            for i in range(n):
                if dn[a + i]: times[a + i] = heard[b + i][1]; ends[a + i] = heard[b + i][2]
        matched = sum(t is not None for t in times)
        # where the vocal actually is inside the window, for words nothing matched
        lo = heard[0][1] if heard else t0; hi = heard[-1][2] if heard else t1
        lo = max(lo, t0 - 0.6); hi = min(max(hi, lo + 0.3 * len(doc)), t1 + 0.6)
        i = 0
        while i < len(doc):
            if times[i] is not None: i += 1; continue
            j = i
            while j < len(doc) and times[j] is None: j += 1
            left = (ends[i - 1] if ends[i - 1] else times[i - 1] + 0.15) if i > 0 else lo
            right = times[j] if j < len(doc) else hi
            right = max(right, left + 0.05 * (j - i + 1))
            for q in range(i, j): times[q] = left + (right - left) * (q - i + (0 if i > 0 else 0)) / (j - i + (1 if j < len(doc) else 0) or 1)
            i = j
        for q in range(1, len(doc)): times[q] = max(times[q], times[q - 1] + 0.05)
        p = 0
        for l in clines:
            ws = [(doc[p + q], round(times[p + q], 2)) for q in range(len(l))]
            last_end = ends[p + len(l) - 1]
            lines.append(dict(words=ws, end=last_end, conf=matched / max(1, len(doc)))); p += len(l)
    prev = -1.0                         # one chunk's words must never start before the previous chunk's
    for L in lines:
        ws = []
        for w, t in L['words']:
            t = round(max(t, prev + 0.05), 2); ws.append((w, t)); prev = t
        L['words'] = ws
    # long lines read badly on screen: break them at commas, or in equal parts
    out = []
    for L in lines:
        ws = L['words']; n = len(ws); parts = max(1, -(-n // 9)); size = -(-n // parts); cuts = [0]
        while cuts[-1] + size < n:
            target = cuts[-1] + size
            near = [q for q in range(max(cuts[-1] + 3, target - 2), min(n - 2, target + 3)) if ws[q - 1][0].endswith((',', '.', '?', '!'))]
            cuts.append(near[0] if near else target)
        cuts.append(n)
        for a, b in zip(cuts, cuts[1:]):
            if b > a: out.append(dict(words=ws[a:b], end=L['end'] if b == n else None, conf=L['conf']))
    for i, L in enumerate(out):
        nxt = out[i + 1]['words'][0][1] if i + 1 < len(out) else dur
        last = L['words'][-1][1]; e = L['end'] if L['end'] and L['end'] > last else last + 0.6
        L['end'] = round(min(max(e, last + 0.25), nxt if nxt - last < 1.6 else last + 0.9, dur), 2)
    return out

def sections(lines, lo=13.0, hi=21.0, cap=25.0):
    secs = []; cur = []
    for i, L in enumerate(lines):
        cur.append(i); start = lines[cur[0]]['words'][0][1]; d = L['end'] - start
        gap = (lines[i + 1]['words'][0][1] - L['end']) if i + 1 < len(lines) else 99
        nxt_d = (lines[i + 1]['end'] - start) if i + 1 < len(lines) else 99
        if (d >= lo and gap > 0.7) or d >= hi or nxt_d > cap or gap > 6: secs.append(cur); cur = []
    if cur: secs.append(cur)
    merged = []
    for s in secs:
        d = lines[s[-1]]['end'] - lines[s[0]]['words'][0][1]
        if merged and d < 8 and lines[s[-1]]['end'] - lines[merged[-1][0]]['words'][0][1] <= cap + 2 and lines[s[0]]['words'][0][1] - lines[merged[-1][-1]]['end'] < 4: merged[-1] += s
        else: merged.append(s)
    return [s for s in merged if lines[s[-1]]['end'] - lines[s[0]]['words'][0][1] >= 7]

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for a in ('master', 'lyrics', 'out', 'title'): ap.add_argument('--' + a, required=True)
    ap.add_argument('--track', type=int, default=1); ap.add_argument('--tracks-total', type=int, default=15)
    ap.add_argument('--artist', default='Close Quarters'); ap.add_argument('--album', default='EDUCATION'); ap.add_argument('--key', default='')
    ap.add_argument('--vox'); ap.add_argument('--inst'); ap.add_argument('--words')
    a = ap.parse_args(); os.makedirs(os.path.join(a.out, 'stems'), exist_ok=True)
    slug = os.path.basename(os.path.normpath(a.out))
    if not (a.vox and a.inst): a.vox, a.inst = split_two(a.master, tempfile.mkdtemp())
    vox = load_mono(a.vox); inst = load_mono(a.inst); dur = len(inst) / SR
    harm, perc = librosa.effects.hpss(inst, margin=2.0)
    bass = sosfiltfilt(butter(4, 170, 'low', fs=SR, output='sos'), harm).astype('float32')
    for name, y in (('Vocals', vox), ('Drums', perc), ('Bass', bass), ('Other', harm - bass)):
        sf.write(os.path.join(a.out, 'stems', name + '.flac'), y, SR)
    tempo, beats = librosa.beat.beat_track(y=perc, sr=SR, units='time'); tempo = float(np.atleast_1d(tempo)[0])
    if tempo < 95: tempo *= 2      # beat trackers like to report half time; the grid only needs to be musical
    words = json.load(open(a.words)) if a.words else whisper_words(a.vox)
    lines = align(parse_lyrics(open(a.lyrics).read()), words, dur)
    json.dump([[L['end'], [[w, t] for w, t in L['words']]] for L in lines], open(os.path.join(a.out, 'lines.json'), 'w'))
    secs = []; rep = []
    for n, s in enumerate(sections(lines), 1):
        st = round(max(0, lines[s[0]]['words'][0][1] - 0.35), 2); en = round(min(dur, lines[s[-1]]['end'] + 0.3), 2)
        conf = round(float(np.mean([lines[i]['conf'] for i in s])), 2)
        secs.append(dict(id='s%02d' % n, start=st, end=en, lines=[s[0], s[-1]], confidence=conf))
        rep.append('%s  %6.1f-%6.1f  %4.1fs  conf %.2f  %s' % (secs[-1]['id'], st, en, en - st, conf, ' '.join(w for w, _ in lines[s[0]]['words'])[:60]))
    link = os.path.join(a.out, 'master.wav')
    if not os.path.lexists(link): os.symlink(os.path.abspath(a.master), link)
    json.dump(dict(slug=slug, title=a.title, artist=a.artist, album=a.album, track=a.track, tracks_total=a.tracks_total, key=a.key,
                   tempo=round(tempo, 2), offset_sec=round(float(beats[0]) if len(beats) else 0.0, 3), stems_start_sec=0.0, sections=secs),
              open(os.path.join(a.out, 'song.json'), 'w'), indent=1)
    open(os.path.join(a.out, 'report.txt'), 'w').write('\n'.join(rep) + '\n'); print('\n'.join(rep))

if __name__ == '__main__': main()
