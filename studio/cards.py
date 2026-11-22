"""Text cards for fact reels over the liminal (VHS) visuals: a white monospace headline, then a sentence,
on a dark band, like an on-screen caption from a home tape. CQ_CARDS is a json list of [t0, t1, big, small].
psy_video.py keeps its own yellow-poster cards."""
import json, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts')
CARDS = json.load(open(os.environ['CQ_CARDS'])) if os.environ.get('CQ_CARDS') else []
_F = {}

def _font(name, size):
    if (name, size) not in _F:
        for p in (os.path.join(FONTS, name), '/usr/share/fonts/truetype/dejavu/' + name):
            if os.path.exists(p): _F[name, size] = ImageFont.truetype(p, size); break
        else: _F[name, size] = ImageFont.load_default()
    return _F[name, size]

def _wrap(d, text, f, width):
    out, cur = [], ''
    for w in text.split():
        t = (cur + ' ' + w).strip()
        if d.textlength(t, font=f) <= width or not cur: cur = t
        else: out.append(cur); cur = w
    return out + ([cur] if cur else [])

def active(t): return next((c for c in CARDS if c[0] <= t < c[1]), None)

def draw(a, t):
    c = active(t)
    if not c: return a
    H, W = a.shape[:2]; im = Image.fromarray(a); lay = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    big, small = c[2] or '', c[3] or ''
    fb = _font('DejaVuSansMono-Bold.ttf', 104); fs = _font('Poppins-Bold.ttf', 60 if big else 84)
    bl = _wrap(d, big.upper(), fb, W * .86); sl = _wrap(d, small, fs, W * .84)
    lh = 78 if big else 108
    h = len(bl) * 120 + (34 if bl and sl else 0) + len(sl) * lh; y = H * .5 - h / 2
    on = min(1.0, (t - c[0]) / .12)
    d.rectangle([0, y - 56, W, y + h + 56], fill=(4, 4, 10, int(200 * on)))
    for ln in bl:
        x = (W - d.textlength(ln, font=fb)) / 2
        d.text((x + 4, y), ln, font=fb, fill=(255, 40, 90, int(160 * on)))      # a red ghost, like a tape caption
        d.text((x - 4, y), ln, font=fb, fill=(40, 220, 255, int(160 * on)))
        d.text((x, y), ln, font=fb, fill=(250, 250, 245, int(255 * on))); y += 120
    y += 34 if bl and sl else 0
    for ln in sl:
        d.text(((W - d.textlength(ln, font=fs)) / 2, y), ln, font=fs, fill=(240, 240, 235, int(255 * on))); y += lh
    im.paste(lay, (0, 0), lay); return np.asarray(im)
