#!/usr/bin/env python3
"""Render a video for every lyric section of a song.

    python studio/render_all.py studio/songs/<slug> --styles producer band --seeds 1 --out studio/out/<slug> [--jobs 2]

One video per section x style x seed, named <slug>_<section>_<style>_<seed>.mp4, each with
its recipe .json beside it. Already-rendered files are skipped, so it can be re-run after
adding seeds or fixing lyrics (delete the files you want redone). --join 50 makes longer
videos by gluing neighbouring sections together (up to 50 seconds each). Sections whose word
timing the prep step was unsure about (confidence below --min-conf), or whose words do not measure as in sync
with the vocal (studio/sync_check.py), are left out.
"""
import argparse, json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
ap = argparse.ArgumentParser(); ap.add_argument('song'); ap.add_argument('--styles', nargs='+', default=['producer', 'band'])
ap.add_argument('--seeds', type=int, default=1); ap.add_argument('--out', required=True); ap.add_argument('--jobs', type=int, default=2)
ap.add_argument('--min-conf', type=float, default=0.45); ap.add_argument('--seed-base', type=int, default=0)
ap.add_argument('--join', type=float, default=0, help='merge neighbouring sections into videos up to this many seconds')
a = ap.parse_args(); song = json.load(open(os.path.join(a.song, 'song.json'))); os.makedirs(a.out, exist_ok=True)
here = os.path.dirname(os.path.abspath(__file__)); jobs = []
secs = []
sys.path.insert(0, here); import sync_check
SYNC = sync_check.sections_ok(a.song)
for sec in song['sections']:
    if sec.get('confidence', 1) < a.min_conf: print('skip', sec['id'], 'confidence', sec['confidence']); continue
    if not SYNC.get(sec['id']): print('skip', sec['id'], 'words not in sync with the vocal (studio/sync_check.py)'); continue
    last = secs[-1] if secs else None
    # --join: glue a section onto the one before it when they touch and the result stays short enough
    if a.join and last and sec['start'] - last['end'] < 4 and sec['end'] - last['start'] <= a.join:
        last['end'] = sec['end']; last['id'] = last['id'].split('-')[0] + '-' + sec['id']
    else: secs.append(dict(sec))
for si, sec in enumerate(secs):
    for style in a.styles:
        for n in range(a.seeds):
            seed = a.seed_base + 1 + n + 17 * si + (500 if style == 'band' else 0)
            out = os.path.join(a.out, '%s_%s_%s_%d.mp4' % (song['slug'], sec['id'], style, seed))
            if not os.path.exists(out): jobs.append((sec, style, seed, out))
def run(j):
    sec, style, seed, out = j
    env = dict(os.environ, CQ_WINDOW='%s,%s' % (sec['start'], sec['end']), CQ_CRF=os.environ.get('CQ_CRF', '26'), CQ_PRESET=os.environ.get('CQ_PRESET', 'medium'), CQ_MAXRATE=os.environ.get('CQ_MAXRATE', '3M'))
    r = subprocess.run([sys.executable, os.path.join(here, 'lyric_video.py'), a.song, style, str(seed), out], env=env, capture_output=True, text=True)
    for ext in ('.wav',):
        if os.path.exists(out[:-4] + ext): os.remove(out[:-4] + ext)
    if r.returncode == 0 and os.path.exists(out[:-4] + '.json'):
        rec = json.load(open(out[:-4] + '.json')); rec['section'] = sec['id']; json.dump(rec, open(out[:-4] + '.json', 'w'), indent=1)
    print(('ok   ' if r.returncode == 0 else 'FAIL ') + os.path.basename(out) + ('' if r.returncode == 0 else '\n' + r.stderr[-600:]), flush=True)
with ThreadPoolExecutor(a.jobs) as ex: list(ex.map(run, jobs))
