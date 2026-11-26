"""The finishing pass every drawn video goes through: light that glows, a little film, the edges darker.

    import polish
    a = polish.look(a, 'physics', i)          # a: HxWx3 uint8 RGB, returns the same

What the best pages in each niche have and flat numpy frames lack is mostly here: bright things bleed
light (bloom), the picture has a fine moving grain so flat colour does not band or look like a
screenshot after Instagram's re-encode, the corners fall off a touch (vignette), colours get a grade,
and on some styles the red and blue split very slightly at the edges like a real lens. Each style
has its own recipe in LOOKS; a style not listed passes through untouched. CQ_POLISH=0 turns it off.

Costs about 25-40 ms a frame at 1080x1920 on a runner core (bloom at a quarter size).
Never used on the illusion pages: grain and glow change what the eye does with them.
"""
import os
import numpy as np, cv2

# bloom: how much light spills (0..1); thr: how bright a pixel must be to glow; grain: noise strength;
# vig: how dark the corners get; ca: red/blue split at the edges in pixels; sat: saturation;
# lift/gain: per-channel shadows and highlights (the grade); white: how much white (type) glows, 1 = as much as colour.
LOOKS = {
    'physics':  dict(bloom=.45, thr=.55, grain=.022, vig=.28, ca=1.2, sat=1.08, white=.5),
    'stopit':   dict(bloom=.22, thr=.7, grain=.018, vig=.18, ca=0, sat=1.04, gain=(1.0, .99, .96), white=.15),
    'race':     dict(bloom=.35, thr=.55, grain=.018, vig=.22, ca=.8, sat=1.06, white=.15),
    'math':     dict(bloom=.28, thr=.6, grain=.014, vig=.2, ca=0, sat=1.04, white=.15),
    'surface':  dict(bloom=.18, thr=.75, grain=.012, vig=.16, ca=0, sat=1.0, white=.15),
    'alife':    dict(bloom=.6, thr=.45, grain=.025, vig=.34, ca=1.0, sat=1.1),
    'reveal':   dict(bloom=.6, thr=.5, grain=.02, vig=.3, ca=.8, sat=1.06, white=.15),
    'fluid':    dict(bloom=.4, thr=.6, grain=.02, vig=.25, ca=0, sat=1.06),
    'lowpoly':  dict(bloom=.25, thr=.7, grain=.02, vig=.22, ca=0, sat=1.05, lift=(.012, .008, .02), gain=(1.02, 1.0, .97)),
    'rocket':   dict(bloom=.3, thr=.7, grain=.018, vig=.25, ca=.6, sat=1.1),
    'measure':  dict(bloom=.15, thr=.8, grain=.015, vig=.15, ca=0, sat=1.0, white=.15),
    'type':     dict(bloom=.12, thr=.85, grain=.016, vig=.14, ca=0, sat=1.0, white=.15),
    'zoom':     dict(bloom=.1, thr=.85, grain=.012, vig=.18, ca=0, sat=1.02),
    'infinite': dict(bloom=.2, thr=.75, grain=.018, vig=.2, ca=0, sat=1.04),
    'tinycode': dict(bloom=.55, thr=.45, grain=.02, vig=.25, ca=.8, sat=1.05, white=.15),
    'psy':      dict(bloom=.3, thr=.65, grain=.0, vig=0, ca=0, sat=1.0),
}

_cache = {}
def _vig(h, w, k):
    key = ('v', h, w, k)
    if key not in _cache:
        y, x = np.mgrid[0:h, 0:w].astype(np.float32); x = (x - w / 2) / (w / 2); y = (y - h / 2) / (h / 2)
        r2 = x * x * .6 + y * y * .4
        _cache[key] = (1 - k * np.clip(r2, 0, 1.6) ** 1.4)[..., None].astype(np.float32)
    return _cache[key]

def _ca(a, px):
    """Red pushed out and blue pulled in from the centre by up to `px` pixels at the corners."""
    h, w = a.shape[:2]; s = 1 + px / (.5 * np.hypot(w, h))
    out = a.copy()
    for ch, z in ((0, s), (2, 1 / s)):
        M = np.float32([[z, 0, (1 - z) * w / 2], [0, z, (1 - z) * h / 2]])
        out[..., ch] = cv2.warpAffine(a[..., ch], M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out

def look(a, style, i=0, seed=0, strength=1.0):
    L = LOOKS.get(style)
    if not L or os.environ.get('CQ_POLISH', '1') == '0' or strength <= 0: return a
    h, w = a.shape[:2]
    if L.get('ca'): a = _ca(a, L['ca'] * strength)
    f = a.astype(np.float32) * (1 / 255)
    if L.get('bloom'):                                       # light that spills: two blurs of the bright parts, small and wide
        lum = f @ np.array([.2126, .7152, .0722], np.float32)
        bright = f * np.clip((lum - L['thr']) / (1 - L['thr'] + 1e-6), 0, 1)[..., None]
        if L.get('white', 1) < 1:                            # white type stays crisp: only coloured light glows fully
            sat = (f.max(-1) - f.min(-1)) / (f.max(-1) + 1e-4); bright = bright * (L['white'] + (1 - L['white']) * np.clip(sat * 2, 0, 1))[..., None]
        q = cv2.resize(bright, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
        b = cv2.GaussianBlur(q, (0, 0), 6) * .6 + cv2.GaussianBlur(cv2.resize(q, (w // 8, h // 8), interpolation=cv2.INTER_AREA), (0, 0), 10).repeat(2, 0).repeat(2, 1)[:q.shape[0], :q.shape[1]] * .7
        b = cv2.resize(b, (w, h), interpolation=cv2.INTER_LINEAR) * (L['bloom'] * strength)
        f = 1 - (1 - f) * (1 - np.clip(b, 0, 1))               # screen, so it never clips harshly
    if L.get('sat', 1) != 1 or 'lift' in L or 'gain' in L:
        g = f.mean(-1, keepdims=True); f = g + (f - g) * (1 + (L.get('sat', 1) - 1) * strength)
        if 'gain' in L: f = f * np.array(L['gain'], np.float32)
        if 'lift' in L: f = f + np.array(L['lift'], np.float32) * (1 - f)
    if L.get('vig'): f = f * _vig(h, w, L['vig'] * strength)
    if L.get('grain'):                                       # film grain: strongest in the mid-tones, a new pattern every frame
        r = np.random.default_rng((seed * 1000003 + i) & 0x7fffffff)
        n = r.standard_normal((h // 2, w // 2), dtype=np.float32)
        n = cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR)[..., None]
        lum = f.mean(-1, keepdims=True); f = f + n * (L['grain'] * strength) * (.35 + 2.6 * lum * (1 - lum))
    return (np.clip(f, 0, 1) * 255 + .5).astype(np.uint8)

def wrap(fn, style):
    """Video.frame = polish.wrap(Video.frame, 'physics'): every frame, the sheet's and the video's, gets the look."""
    def g(self, i, *a, **k):
        img = fn(self, i, *a, **k)
        return look(img, style, int(i), int(getattr(self, 'seed', 0) or 0)) if isinstance(img, np.ndarray) and img.dtype == np.uint8 and img.ndim == 3 else img
    return g
