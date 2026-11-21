"""The line on screen for the first two seconds of a video: a reason to keep watching.

    text = hook.pick(style, seed)          # '' about a quarter of the time, so its effect can be measured
    frame = hook.draw(frame, text, t)      # t = seconds into the video; draws nothing after ~2.6s

The choice is recorded in each video's recipe as "hook", so the stats can say which lines hold people.
"""
import os, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HOOKS = {
    'producer': ["wait for the bass", "every lane is a real track", "watch the vocal lane", "this is the actual session", "which stem would you solo?", "sound on. watch the drums"],
    'band': ["read along", "wait for the last line", "your pc in 2001:", "lyrics on screen. sound on", "which line is the best one?", "class is in session"],
    'psy': ["watch the centre", "stare for 10 seconds", "don't blink", "sound on", "it moves with the bass", "look away at the end"],
}
SHOW, FADE = 2.2, 0.4
_FONT = {}

def pick(style, seed):
    if os.environ.get('CQ_HOOK'): return os.environ['CQ_HOOK']          # the nightly job leaning towards a line that has worked
    r = random.Random(seed * 7919 + 11)
    return '' if r.random() < 0.25 else r.choice(HOOKS.get(style, HOOKS['psy']))

def _font(size):
    if size not in _FONT:
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, '..', 'fonts', 'Anton-Regular.ttf'), os.path.join(here, '..', 'fonts', 'Montserrat-ExtraBold.ttf')):
            if os.path.exists(p): _FONT[size] = ImageFont.truetype(p, size); break
    return _FONT[size]

def draw(frame, text, t):
    if not text or t >= SHOW + FADE: return frame
    H, W = frame.shape[:2]; size = int(W * 0.105 * (1 + 0.25 * max(0.0, 1 - t / 0.18))); f = _font(size); txt = text.upper()
    while f.getlength(txt) > W * 0.86 and size > 40: size -= 6; f = _font(size)
    tw = f.getlength(txt); x = (W - tw) / 2; y = H * 0.115; pad = size * 0.28
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    d.rectangle([x - pad, y - pad * 0.6, x + tw + pad, y + size * 1.18 + pad * 0.4], fill=(255, 230, 60, 255)); d.text((x, y), txt, font=f, fill=(0, 0, 0, 255))
    a = 1.0 if t < SHOW else max(0.0, 1 - (t - SHOW) / FADE); m = (np.asarray(lay, np.float32)[..., 3:] / 255) * a
    return (frame * (1 - m) + np.asarray(lay, np.float32)[..., :3] * m).astype(np.uint8)
