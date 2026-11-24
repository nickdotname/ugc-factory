"""ASCII scene (colour): a moving picture set in bold letters. The picture is one of our own clips (made by our video
model, studio/retro_gen.py); letters.py turns each frame into type. The kick pushes the camera in, the snare throws
sparks off the bright letters, the bass lifts the colour. The code in the panel is the typesetter itself."""
import os, sys
import numpy as np, cv2
import paint as P
from paint import E

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
FILE = 'letters.py'
DOTS = False
GLOW = 0.7
FRAMES = []; INFO = {}


def setup(e):
    P.setup(e)
    import retro_gen as lib
    clips = lib.pull(())
    want = os.environ.get('CQ_CLIP', '')
    pick = [c for c in clips if want and want in (c['asset'], c['theme'])] or clips
    c = pick[np.random.default_rng(e.get('seed', 7)).integers(len(pick))]; INFO.update(c)
    cap = cv2.VideoCapture(os.path.join(lib.CACHE, c['asset'])); FRAMES[:] = []
    while True:
        ok, f = cap.read()
        if not ok: break
        FRAMES.append(f)
    if not FRAMES: sys.exit('could not read ' + c['asset'])
    import knobs as K
    K.MENU['subject'] = sorted({x['theme'] for x in clips}); K.CHOSEN['subject'] = c['theme']


def picture(i):
    """This frame of the clip (played forward then back, so it never jumps), pushed in on the kick."""
    n = len(FRAMES); k = (i * 2 // 3) % (2 * n - 2); f = FRAMES[k if k < n else 2 * n - 2 - k]
    h, w = f.shape[:2]; ar = E['cols'] * E['cw'] / (E['rows'] * E['ch'])
    z = 1.0 + 0.05 * float(E['kick'][i]) + 0.03 * i / max(1, E['n'])
    ch = min(h, w / ar) / z; cw = ch * ar
    x0, y0 = int((w - cw) / 2), int((h - ch) * 0.45)
    return f[y0:y0 + int(ch), x0:x0 + int(cw)]


def particles(i, rows, cols): return []


def stats(i, sparks):
    return 'subject %s    frame %d    sparks %d' % (INFO.get('theme', '?'), i, sparks)


CODE = P.source(os.path.join(HERE, 'letters.py'))
