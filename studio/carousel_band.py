#!/usr/bin/env python3
"""A carousel for close__quarters: Dylan and Nick, cut out and pixelated, with a line of meme text on each,
then a slide for the album.

    python studio/carousel_band.py studio/carousels/band/<name>.json <seed> <out_dir>

The spec's "slides" are [cut-out in studio/band/, text]. Writes 01.jpg ... at 1080x1350.
"""
import sys, os, json, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import faces
spec = json.load(open(sys.argv[1])); seed = int(sys.argv[2]); out = sys.argv[3]; os.makedirs(out, exist_ok=True)
W, H = 1080, 1350; rng = random.Random(seed); BAND = os.path.join(HERE, 'band'); FONTS = os.path.join(HERE, '..', 'fonts')
def font(name, size): return ImageFont.truetype(os.path.join(FONTS, name), size)

def wrap(d, text, f, maxw):
    rows, cur = [], ''
    for w in text.split():
        if cur and d.textlength(cur + ' ' + w, font=f) > maxw: rows.append(cur); cur = w
        else: cur = (cur + ' ' + w).strip()
    return rows + [cur]

def meme(d, text, y, maxw=W - 90, hi=92, lo=54, top=True):
    """Big white letters with a black edge, the way the format is read."""
    for size in range(hi, lo - 1, -4):
        f = font('Anton-Regular.ttf', size); rows = wrap(d, text.upper(), f, maxw)
        if len(rows) <= 3: break
    hgt = len(rows) * size * 1.08; y = y if top else y - hgt
    for r in rows:
        d.text(((W - d.textlength(r, font=f)) / 2, y), r, font=f, fill=(255, 255, 255), stroke_width=max(4, size // 14), stroke_fill=(0, 0, 0)); y += size * 1.08

PALS = [((58, 18, 92), (0, 128, 128)), ((20, 40, 120), (190, 60, 140)), ((0, 90, 70), (230, 170, 40)), ((110, 20, 40), (30, 30, 90))]
c0, c1 = rng.choice(PALS)
def backdrop(k):
    """A dithered two-colour gradient with scanlines, like an old screen."""
    yy, xx = np.indices((H // 6, W // 6)); t = (yy / (H // 6) + 0.25 * np.sin(xx / 9 + k)).clip(0, 1)
    bay = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16)[yy % 4, xx % 4]
    q = (np.floor(t * 6 + bay) / 6)[..., None]
    a = (np.array(c0) * (1 - q) + np.array(c1) * q).astype(np.uint8)
    a = np.asarray(Image.fromarray(a).resize((W, H), Image.NEAREST)).copy(); a[::4] = (a[::4] * .8).astype(np.uint8)
    return a

n = len(spec['slides'])
for i, (pic, text) in enumerate(spec['slides'], 1):
    a = faces.paste_sprite(backdrop(i), pic, W / 2, H - 100, 920, 1.0, 0.0, block=9)
    im = Image.fromarray(a); d = ImageDraw.Draw(im)
    meme(d, text, 60)
    tag = '@' + spec['handle']; ft = font('Poppins-Bold.ttf', 30)
    d.text((W - 40 - d.textlength(tag, font=ft), H - 70), tag, font=ft, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    if i < n: d.text((40, H - 70), '%d/%d  swipe >' % (i, n + 1), font=ft, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    im.save(os.path.join(out, '%02d.jpg' % i), quality=92)

# ---- last: the album ---------------------------------------------------------------------------------
a = backdrop(99)
for k, pic in enumerate(spec.get('cta_photos') or ['dylan_10.png', 'nick_05.png']):
    a = faces.paste_sprite(a, pic, W * (0.3 if k == 0 else 0.7), 690, 560, 1.0, 0.0, block=8)
im = Image.fromarray(a); d = ImageDraw.Draw(im)
meme(d, spec.get('cta', 'EDUCATION by Close Quarters is out now'), 720, hi=96)
fb = font('Poppins-Bold.ttf', 44); t = 'link in bio to stream it'
d.text(((W - d.textlength(t, font=fb)) / 2, 1080), t, font=fb, fill=(255, 230, 60))
ft = font('Poppins-Bold.ttf', 30); tag = '@' + spec['handle']
d.text(((W - d.textlength(tag, font=ft)) / 2, H - 110), tag, font=ft, fill=(200, 200, 210))
im.save(os.path.join(out, '%02d.jpg' % (n + 1)), quality=92); print('wrote', n + 1, 'slides to', out)
