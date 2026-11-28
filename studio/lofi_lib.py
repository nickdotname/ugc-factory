#!/usr/bin/env python3
"""The footage behind the lo-fi cut-out videos (studio/lofi_video.py): the band dancing to their own songs.

    python studio/lofi_lib.py pack ID FRAMES_DIR MASKS_DIR OUT.tar   # cut-outs as RGBA webp, one per tenth of a second
    python studio/lofi_lib.py pull                                   # download every clip's cut-outs into the cache

studio/lofi/index.json lists the clips: which song, where in it the clip starts (song seconds at its first frame,
found by landmark fingerprints of the music playing quietly behind the dancing), how many frames at what rate, and
who is in it. The cut-outs themselves (540x960 RGBA webp, made once with a person-segmentation model) are one tar per
clip in the lofi-library release; they are downloaded on first use into studio/lofi/cache/ (not in git)."""
import io, json, os, subprocess, sys, tarfile
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, 'lofi'); INDEX = os.path.join(DIR, 'index.json'); CACHE = os.path.join(DIR, 'cache')
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory')


def index():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {'release': 'lofi-library', 'clips': []}


def clips_for(slug):
    return [c for c in index()['clips'] if c['song'] == slug]


INBOX = os.path.join(DIR, 'inbox')   # new clips wait here until lofi-inbox.yml moves them into the release


def _fetch(asset):
    """Download one tar from the release (REST only, so it works wherever gh is signed in) and unpack it; a clip still
    in studio/lofi/inbox/ (added in a PR, not yet moved to the release) is unpacked from there."""
    os.makedirs(CACHE, exist_ok=True); rel = index().get('release', 'lofi-library')
    local = os.path.join(INBOX, asset)
    if os.path.exists(local):
        with tarfile.open(local) as tf: tf.extractall(CACHE)
        return
    info = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, rel)], capture_output=True, text=True, check=True).stdout)
    a = next((x for x in info['assets'] if x['name'] == asset), None)
    if a is None: raise FileNotFoundError('%s is not in the %s release' % (asset, rel))
    data = subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream', 'repos/%s/releases/assets/%d' % (REPO, a['id'])], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tf: tf.extractall(CACHE)


_have = set()
def frame(cid, k):
    """Frame k (1-based) of clip cid as an RGBA image, or None where the clip has no cut-out for it."""
    if cid not in _have:
        c = next((x for x in index()['clips'] if x['id'] == cid), None)
        if c is None: return None
        if not os.path.isdir(os.path.join(CACHE, cid)): _fetch(c['asset'])
        _have.add(cid)
    p = os.path.join(CACHE, cid, '%04d.webp' % k)
    return Image.open(p).convert('RGBA') if os.path.exists(p) else None


def pack(cid, frames_dir, masks_dir, out):
    """Every frame that has a mask, as an RGBA webp named by its frame number, in one tar."""
    n = 0
    with tarfile.open(out, 'w') as tf:
        for name in sorted(os.listdir(masks_dir)):
            k = name[:-4]; src = os.path.join(frames_dir, k + '.jpg')
            if not name.endswith('.png') or not os.path.exists(src): continue
            im = Image.open(src).convert('RGB'); m = Image.open(os.path.join(masks_dir, name)).convert('L')
            m = m.point(lambda v: 0 if v < 40 else (255 if v > 200 else int((v - 40) * 255 / 160)))
            im.putalpha(m); buf = io.BytesIO(); im.save(buf, 'WEBP', quality=82, method=4)
            ti = tarfile.TarInfo('%s/%s.webp' % (cid, k)); ti.size = buf.tell(); buf.seek(0); tf.addfile(ti, buf); n += 1
    print('packed', n, 'frames of', cid, 'into', out, '%.1f MB' % (os.path.getsize(out) / 1e6))


def pull():
    for c in index()['clips']:
        if not os.path.isdir(os.path.join(CACHE, c['id'])): _fetch(c['asset'])
    return index()['clips']


if __name__ == '__main__':
    if sys.argv[1:2] == ['pack']: pack(*sys.argv[2:6])
    elif sys.argv[1:2] == ['pull']: print(len(pull()), 'clips cached')
    else: print(__doc__)
