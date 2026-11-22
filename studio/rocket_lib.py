#!/usr/bin/env python3
"""rocket.league.lit's clip library: our own Rocket League clips (Dylan's and Nick's recordings).

    python studio/rocket_lib.py add DIR [DIR ...]     (find the moments in each new clip, upload it, record it)
    python studio/rocket_lib.py pull                  (download the library into studio/rocket/cache)

Each clip is uploaded as an asset of the GitHub release "rocket-library" and recorded in studio/rocket/index.json
with its size, length and its moments: the seconds where something happens (a goal explosion, a big hit, a
flip reset landing), found from loud bursts in its sound and sudden changes in its picture. The renderer
(studio/rocket_video.py) lands those moments on the song's downbeats.
"""
import hashlib, json, os, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'rocket')
INDEX = os.path.join(DIR, 'index.json'); CACHE = os.path.join(DIR, 'cache')
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'rocket-library'


def index():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {'clips': []}


def probe(path):
    r = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path],
                                  capture_output=True, text=True).stdout or '{}')
    v = next((s for s in r.get('streams', []) if s.get('codec_type') == 'video'), {})
    rot = int((v.get('tags') or {}).get('rotate', 0) or next((sd.get('rotation', 0) for sd in v.get('side_data_list', []) if 'rotation' in sd), 0))
    w, h = int(v.get('width', 0)), int(v.get('height', 0))
    if abs(rot) in (90, 270): w, h = h, w
    return dict(w=w, h=h, dur=float(r.get('format', {}).get('duration', 0)), audio=any(s.get('codec_type') == 'audio' for s in r.get('streams', [])))


def moments(path, dur, has_audio, n=4):
    """The clip's big moments, in seconds: loud bursts in the sound and sudden flashes or cuts in the picture."""
    fps = 10; frames = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', path, '-vf', 'fps=%d,scale=96:-2,format=gray' % fps, '-f', 'rawvideo', '-'],
                                      capture_output=True).stdout
    p = probe(path); w = 96; h = int(round(w * p['h'] / max(1, p['w']) / 2) * 2) or 54
    k = len(frames) // (w * h); v = np.frombuffer(frames[:k * w * h], np.uint8).reshape(k, h, w).astype(np.float32)
    score = np.zeros(k)
    if k > 2:
        diff = np.abs(np.diff(v, axis=0)).mean((1, 2)); bright = v.mean((1, 2))
        score[1:] += diff / (np.median(diff) + 1e-3) * 0.6
        score += np.clip(bright - np.median(bright), 0, None) / 10
    if has_audio:
        a = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', path, '-ac', '1', '-ar', '8000', '-f', 'f32le', '-'], capture_output=True).stdout
        y = np.frombuffer(a, np.float32)
        if len(y):
            hop = 8000 // fps; rms = np.array([np.sqrt(np.mean(y[j * hop:(j + 1) * hop] ** 2) + 1e-9) for j in range(min(k, len(y) // hop))])
            score[:len(rms)] += rms / (np.median(rms) + 1e-4)
    score = np.convolve(score, np.ones(3) / 3, 'same'); out = []
    for j in np.argsort(-score):
        t = j / fps
        if 1.0 < t < dur - 0.5 and all(abs(t - o) > 2.5 for o, _ in out): out.append((round(float(t), 2), round(float(score[j]), 2)))
        if len(out) >= n: break
    return sorted(out, key=lambda m: -m[1])


def add(dirs):
    idx = index(); have = {c['sha'] for c in idx['clips']}; files = []
    for d in dirs:
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(('.mp4', '.mov', '.m4v')): continue
            path = os.path.join(d, name); sha = hashlib.sha1(open(path, 'rb').read()).hexdigest()
            if sha in have: continue
            p = probe(path)
            if p['dur'] < 2 or not p['w']: print('skip', name, p); continue
            asset = sha[:16] + '.mp4'
            out = os.path.join(CACHE, asset); os.makedirs(CACHE, exist_ok=True)
            # one shape for everything: H.264, at most 1920 on the long side, sound kept (the renderer decides what to hear)
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', path, '-vf', "scale='if(gt(iw,ih),min(1920,iw),-2)':'if(gt(iw,ih),-2,min(1920,ih))'",
                            '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', out], check=True)
            m = moments(out, p['dur'], p['audio'])
            idx['clips'].append(dict(asset=asset, sha=sha, source=name, w=p['w'], h=p['h'], dur=round(p['dur'], 2), moments=m)); have.add(sha); files.append(out)
            print('+ %-50s %4.1fs %dx%d moments %s' % (name[:50], p['dur'], p['w'], p['h'], [t for t, _ in m]))
    if files:
        if subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True).returncode:
            subprocess.run(['gh', 'api', '-X', 'POST', 'repos/%s/releases' % REPO, '-f', 'tag_name=' + RELEASE, '-f', 'name=Rocket League clip library',
                            '-f', 'body=Our own Rocket League clips for rocket.league.lit. What each is: studio/rocket/index.json'], check=True, capture_output=True)
        rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
        for f in files:
            subprocess.run(['gh', 'api', '-X', 'POST', '-H', 'Content-Type: video/mp4', '--input', f,
                            'https://uploads.github.com/repos/%s/releases/%d/assets?name=%s' % (REPO, rel['id'], os.path.basename(f))], check=True, capture_output=True)
    json.dump(idx, open(INDEX, 'w'), indent=1); print('%d new, %d in the library' % (len(files), len(idx['clips'])))


def pull():
    """Download the clips not cached yet (REST only, so it works anywhere gh is signed in)."""
    os.makedirs(CACHE, exist_ok=True); want = index()['clips']
    miss = {c['asset'] for c in want if not os.path.exists(os.path.join(CACHE, c['asset']))}
    if miss:
        rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
        for a in rel['assets']:
            if a['name'] in miss:
                with open(os.path.join(CACHE, a['name']), 'wb') as fh:
                    fh.write(subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream', 'repos/%s/releases/assets/%d' % (REPO, a['id'])],
                                            capture_output=True, check=True).stdout)
    return [c for c in want if os.path.exists(os.path.join(CACHE, c['asset']))]


if __name__ == '__main__':
    if sys.argv[1:2] == ['add']: add(sys.argv[2:])
    elif sys.argv[1:2] == ['pull']: print(len(pull()), 'clips cached')
    else: print(__doc__)
