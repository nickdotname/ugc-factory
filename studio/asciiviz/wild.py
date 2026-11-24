"""ASCII scene (colour): a moving picture set in bold letters. The picture is one bold subject: a public-domain clip
(NASA, Wikimedia Commons CC0 / public domain: studio/footage/index.json has every source) chosen by hand because it
still reads at 108 letters across, or, once the Kaggle job has made them, one of our own single-subject clips (koi,
jellyfish, a macaw...: studio/retro/prompts.json "subjects", themes subject-...); letters.py turns each frame into type. The kick pushes the camera in, the snare
throws sparks off the bright letters. The code in the panel is the typesetter itself: that is what draws this."""
import os, sys
import numpy as np, cv2
import paint as P
from paint import E

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
FILE = 'letters.py'
DOTS = False
GLOW = 0.7
# subject -> clips of the footage library: (asset, where the subject sits across the frame 0..1, first frame, last frame)
SUBJECTS = {     # subject -> clips: (asset, centre of the subject across and down the frame 0..1, zoom, first frame, last frame)
    'earth': [('754dd0028974d6b9.mp4', 0.5, 0.5, 1.2, 0, 0), ('a6b84ed1cb0f808f.mp4', 0.5, 0.5, 1.2, 0, 0)],       # NASA, Galileo flyby
    'sunrise': [('72d8e7fec5ae2478.mp4', 0.53, 0.5, 1.25, 0, 0), ('391e8aae40196e4b.mp4', 0.55, 0.5, 1.25, 0, 0)],
    'creek': [('9c711c1ef3fa2527.mp4', 0.42, 0.5, 1.0, 0, 0)],
    'zinnias': [('b77d5f07517d152d.mp4', 0.5, 0.45, 1.1, 0, 112)],          # the flowers only: the clip cuts to a person at frame 114
}
FRAMES = []; INFO = {}


def setup(e):
    P.setup(e)
    import footage as lib, retro_gen, knobs as K, random
    r = random.Random(e.get('seed', 7) * 7919 + 3)
    own = {}                                                     # our own single-subject clips, when the library has any
    for c in retro_gen.index().get('clips', []):
        if c['theme'].startswith('subject-'): own.setdefault(c['theme'][8:], []).append((c['asset'], 0.5, 0.5, 1.0, 0, 0))
    subjects = dict(SUBJECTS, **own)
    subject = K.pick('subject', sorted(subjects), r, weights=[3 if k in own else 1 for k in sorted(subjects)])
    want = os.environ.get('CQ_CLIP', '')
    clips = [c for c in subjects[subject] if not want or want in c[0]] or subjects[subject]
    asset, fx, fy, zoom, a, b = clips[r.randrange(len(clips))]
    if subject in own:
        retro_gen.pull(('subject-' + subject,)); path = os.path.join(retro_gen.CACHE, asset)
    else:
        lib.pull(assets=(asset,)); path = os.path.join(lib.CACHE, asset)
    INFO.update(subject=subject, asset=asset, fx=fx, fy=fy, zoom=zoom)
    cap = cv2.VideoCapture(path); FRAMES[:] = []
    while True:
        ok, f = cap.read()
        if not ok: break
        FRAMES.append(f)
    if b: FRAMES[:] = FRAMES[a:b]
    if not FRAMES: sys.exit('could not read ' + asset)


def picture(i):
    """This frame of the clip (played forward then back, so it never jumps), pushed in on the kick."""
    n = len(FRAMES); k = i % (2 * n - 2); f = FRAMES[k if k < n else 2 * n - 2 - k]
    h, w = f.shape[:2]; ar = E['cols'] * E['cw'] / (E['rows'] * E['ch'])
    z = INFO['zoom'] * (1.0 + 0.05 * float(E['kick'][i]) + 0.03 * i / max(1, E['n']))
    ch = min(h, w / ar) / z; cw = ch * ar
    x0 = int(np.clip(INFO['fx'] * w - cw / 2, 0, w - cw)); y0 = int(np.clip(INFO['fy'] * h - ch / 2, 0, h - ch))
    return f[y0:y0 + int(ch), x0:x0 + int(cw), ::-1]


def particles(i, rows, cols): return []


def stats(i, sparks):
    return 'subject %s    frame %d    sparks %d' % (INFO.get('subject', '?'), i, sparks)


CODE = P.source(os.path.join(HERE, 'letters.py'))
