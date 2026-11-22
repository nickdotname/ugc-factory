"""Dylan and Nick reacting to their own song, for the close__quarters lyric videos and the dylancantor23
producer videos.

studio/band/manifest.json lists each photo with who it is and how big the reaction is (0 calm, 1 some,
2 big). A video that uses faces switches person on every lyric line (Dylan, Nick, Dylan ...), picks a
reaction as big as the line is loud, and makes the picture jump a little on every word, so a run of
stills reads as an animation. The photos are cut out (studio/band/*.png, transparent) and drawn as
crushed, pixelated sprites over the visuals, never as photos of a wall. Only some videos use faces (see lyric_video.py), so the stats can say
whether they help.
"""
import json, math, os, random
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'band')
MAN = json.load(open(os.path.join(DIR, 'manifest.json'))) if os.path.exists(os.path.join(DIR, 'manifest.json')) else []
WHO = ['dylan', 'nick']
_IMG = {}


def available():
    return {m['who'] for m in MAN} >= set(WHO)


def image(name):
    if name not in _IMG: _IMG[name] = np.asarray(Image.open(os.path.join(DIR, name)).convert('RGB'))
    return _IMG[name]


def levels(lines, bands, t0, fps):
    """A reaction size (0-2) for each line: how loud it is against the other lines in the clip."""
    e = []
    for end, ws in lines:
        a = max(0, int((ws[0][1] - t0) * fps)); b = max(a + 1, int((end - t0) * fps))
        seg = bands[:, a:b]; e.append(float(seg.mean()) if seg.size else 0.0)
    if not e: return []
    lo, hi = np.percentile(e, 33), np.percentile(e, 67)
    return [0 if x <= lo else 2 if x > hi else 1 for x in e]


def plan(lines, seed, first=None):
    """Who is on screen for each line: alternating, starting with a random one of the two."""
    r = random.Random(seed * 131 + 7); start = WHO.index(first) if first in WHO else r.randrange(2)
    return [WHO[(start + k) % 2] for k in range(len(lines))]


def pick(who, level, key, avoid=None):
    """A photo of `who` at this reaction size (or the nearest size there is), steady for the same key."""
    pool = [m['file'] for m in MAN if m['who'] == who]
    for d in (0, 1, 2):
        near = [m['file'] for m in MAN if m['who'] == who and abs(m['level'] - level) == d]
        if near: pool = near; break
    if avoid in pool and len(pool) > 1: pool = [p for p in pool if p != avoid]
    return random.Random(str(key)).choice(pool)


def pose(words, T):
    """(which word the line is on, seconds since that word started), for the jump on each word."""
    i = max([j for j, (_, t) in enumerate(words) if t <= T] or [0])
    return i, max(0.0, T - words[i][1])


_SPR = {}
def _crushed(name, block, levels=7):
    """The cut-out as a crushed, pixelated sprite at 1/block scale: few colours, ordered dither, hard
    pixel edges and a one-pixel black outline. Cached; scaled up later with nearest-neighbour."""
    k = (name, block, levels)
    if k not in _SPR:
        im = Image.open(os.path.join(DIR, name)).convert('RGBA'); w, h = im.size
        sm = im.resize((max(1, w // block), max(1, h // block)), Image.BOX); a = np.asarray(sm).astype(np.float32)
        rgb, al = a[..., :3], a[..., 3]
        rgb = np.clip((rgb - 128) * 1.15 + 128, 0, 255)                       # a harder, older-camera contrast
        g = rgb.mean(2, keepdims=True); rgb = np.clip(g + (rgb - g) * 1.2, 0, 255)    # and louder colour
        bay = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16 - .5) * .6
        yy, xx = np.indices(rgb.shape[:2]); d = bay[yy % 4, xx % 4][..., None] * (255 / (levels - 1))
        rgb = np.round((rgb + d) / (255 / (levels - 1))) * (255 / (levels - 1))
        on = al > 127; edge = np.zeros_like(on)
        edge[1:] |= on[:-1]; edge[:-1] |= on[1:]; edge[:, 1:] |= on[:, :-1]; edge[:, :-1] |= on[:, 1:]
        edge &= ~on
        out = np.zeros(rgb.shape[:2] + (4,), np.uint8); out[on, :3] = np.clip(rgb[on], 0, 255); out[on, 3] = 255
        out[edge] = (0, 0, 0, 255)
        _SPR[k] = Image.fromarray(out)
    return _SPR[k]


def paste_sprite(frame, name, cx, bottom, height, since, T, beat_phase=0.0, block=9, shift=3):
    """Put the person on `frame` (an RGB array) as a pixel sprite: centred on cx, feet at `bottom`,
    `height` tall, jumping on each word and leaning a touch with the beat. Returns the new array."""
    spr = _crushed(name, block); sw, sh = spr.size
    pop = 1 + 0.08 * math.exp(-since * 9)
    th = int(height * pop); tw = int(sw * th / sh)
    big = spr.resize((tw, th), Image.NEAREST)
    ang = 3.0 * math.sin(T * 2.3) * math.exp(-since * 3) + 1.2 * math.sin(beat_phase * math.tau)
    if abs(ang) > 0.1: big = big.rotate(ang, resample=Image.NEAREST, expand=True)
    im = Image.fromarray(frame); x = int(cx - big.width / 2); y = int(bottom - big.height - 26 * math.exp(-since * 9))
    if shift:                                                  # a red/blue split, like a bad video signal
        al = np.asarray(big)[..., 3]
        ghost = np.zeros(al.shape + (4,), np.uint8); ghost[..., 0] = 255; ghost[..., 2] = 120; ghost[..., 3] = (al > 0) * 90
        im.paste(Image.fromarray(ghost), (x - shift * 2, y), Image.fromarray(ghost))
        ghost[..., 0] = 40; ghost[..., 1] = 200; ghost[..., 2] = 255
        im.paste(Image.fromarray(ghost), (x + shift * 2, y), Image.fromarray(ghost))
    im.paste(big, (x, y), big)
    return np.asarray(im)
