#!/usr/bin/env python3
"""A nostalgia carousel: every slide is an old desktop window on a dithered teal screen.

    python studio/carousel_retro.py studio/carousels/<name>.json <seed> <out_dir>

Same words file as carousel.py (headline, slides as [big word, sentence], sources, music, handle),
same output (01.jpg ... at 1080x1350). The look is drawn here, no screenshots or logos: a bevelled
grey window with a title bar, a desktop colour picked by the seed, pixel icons, a VHS date stamp on
the cover.
"""
import sys, os, json, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

spec = json.load(open(sys.argv[1])); seed = int(sys.argv[2]); out = sys.argv[3]; os.makedirs(out, exist_ok=True)
W, H = 1080, 1350; rng = random.Random(seed); HERE = os.path.dirname(os.path.abspath(__file__)); FD = os.path.join(HERE, '..', 'fonts')
def font(name, size):
    for p in (os.path.join(FD, name), '/usr/share/fonts/truetype/dejavu/' + name, '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()
HEAD, BODY, MONO = 'Anton-Regular.ttf', 'Poppins-Bold.ttf', 'DejaVuSansMono-Bold.ttf'
DESK = rng.choice([(0, 128, 128), (58, 110, 165), (96, 64, 128), (0, 96, 64), (128, 80, 104)])
TITLE = rng.choice([((0, 0, 128), (16, 132, 208)), ((128, 0, 64), (208, 80, 144)), ((0, 80, 0), (48, 160, 96))])
GREY, LIGHT, DARK = (192, 192, 192), (255, 255, 255), (96, 96, 96)
name = spec['slug'].replace('-', '_')[:14]

def desktop():
    a = np.zeros((H, W, 3), np.uint8); a[:] = DESK
    y, x = np.mgrid[0:H, 0:W]; a[((x // 3 + y // 3) % 2 == 0)] = np.clip(np.array(DESK) + 10, 0, 255)      # dither, like 256 colours
    im = Image.fromarray(a); d = ImageDraw.Draw(im)
    for k, label in enumerate(['my files', 'recycle', 'rewind']):                                          # pixel icons down the left
        x0, y0 = 40, 60 + k * 170
        d.rectangle([x0 + 20, y0, x0 + 92, y0 + 64], fill=(240, 220, 120) if k != 1 else (200, 200, 210), outline=(0, 0, 0), width=3)
        d.text((x0 + 56 - d.textlength(label, font=font(BODY, 22)) / 2, y0 + 76), label, font=font(BODY, 22), fill=LIGHT)
    return im, d

def window(d, box, title):
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=GREY); d.line([(x0, y0), (x1, y0)], fill=LIGHT, width=4); d.line([(x0, y0), (x0, y1)], fill=LIGHT, width=4)
    d.line([(x0, y1), (x1, y1)], fill=(0, 0, 0), width=4); d.line([(x1, y0), (x1, y1)], fill=(0, 0, 0), width=4)
    for k in range(52):                                                                                    # title bar, fading left to right
        t = k / 51; c = tuple(int(TITLE[0][j] * (1 - t) + TITLE[1][j] * t) for j in range(3))
        d.rectangle([x0 + 8 + (x1 - x0 - 16) * k / 52, y0 + 8, x0 + 8 + (x1 - x0 - 16) * (k + 1) / 52, y0 + 64], fill=c)
    d.text((x0 + 22, y0 + 14), title, font=font(BODY, 32), fill=LIGHT)
    for k, ch in enumerate('x□_'):          # k=0 is the rightmost button
        bx = x1 - 64 - k * 52; d.rectangle([bx, y0 + 16, bx + 40, y0 + 56], fill=GREY, outline=(0, 0, 0), width=2)
        if ch == '□': d.rectangle([bx + 11, y0 + 25, bx + 29, y0 + 46], outline=(0, 0, 0), width=3)       # drawn: the font has no box glyph
        else: d.text((bx + 12, y0 + 14), ch, font=font(BODY, 28), fill=(0, 0, 0))
    d.rectangle([x0 + 18, y0 + 82, x1 - 18, y1 - 18], fill=LIGHT); d.line([(x0 + 18, y0 + 82), (x1 - 18, y0 + 82)], fill=DARK, width=3)
    d.line([(x0 + 18, y0 + 82), (x0 + 18, y1 - 18)], fill=DARK, width=3)
    return (x0 + 50, y0 + 112, x1 - 50, y1 - 50)

def wrap(d, text, f, maxw):
    rows, cur = [], ''
    for wd in text.split():
        if cur and d.textlength(cur + ' ' + wd, font=f) > maxw: rows.append(cur); cur = wd
        else: cur = (cur + ' ' + wd).strip()
    return rows + [cur]
def fit(d, text, name_, maxw, maxh, hi, lo=34, lead=1.12):
    for size in range(hi, lo - 1, -4):
        f = font(name_, size); rows = wrap(d, text, f, maxw)
        if len(rows) * size * lead <= maxh: return f, rows, size
    return f, rows, size
def button(d, x, y, text):
    f = font(BODY, 34); w = d.textlength(text, font=f) + 60
    d.rectangle([x, y, x + w, y + 66], fill=GREY, outline=(0, 0, 0), width=3); d.line([(x + 3, y + 3), (x + w - 3, y + 3)], fill=LIGHT, width=3)
    d.text((x + 30, y + 12), text, font=f, fill=(0, 0, 0)); return w

# ---- cover: the headline in a text window, and the topic's real photo in a picture viewer when there is one
HERE_ = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE_); import photos
PHOTO = photos.for_spec(spec)                                  # (path, credit) or None
im, d = desktop()
if PHOTO:
    import numpy as np
    px0, py0, px1, py1 = window(d, (60, 120, W - 130, 700), '%s.jpg - Image Viewer' % name)
    ph = photos.fit_image(PHOTO[0], px1 - px0 + 32, py1 - py0 + 14)
    im.paste(Image.fromarray(ph), (px0 - 16, py0 - 8)); d = ImageDraw.Draw(im)
    d.text((70, H - 70), PHOTO[1][:80], font=font(BODY, 22), fill=LIGHT)
    ix0, iy0, ix1, iy1 = window(d, (150, 640, W - 60, H - 190), '%s.txt' % name)
else:
    ix0, iy0, ix1, iy1 = window(d, (150, 230, W - 60, H - 190), '%s.txt' % name)
f, rows, size = fit(d, spec['headline'].upper(), HEAD, ix1 - ix0, iy1 - iy0 - 120, 120 if not PHOTO else 96)
y = iy0 + 10
for r_ in rows: d.text((ix0, y), r_, font=f, fill=(0, 0, 0)); y += size * 1.12
button(d, ix1 - 300, iy1 - 66, 'swipe  >')
yr = rng.randint(1994, 2003); fm = font(MONO, 46)
d.text((60, H - 130), 'PLAY ▶   %s %02d %d' % ('JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()[rng.randint(0, 11)], rng.randint(1, 28), yr), font=fm, fill=LIGHT)
im.save(os.path.join(out, '01.jpg'), quality=92)

# ---- one fact a slide --------------------------------------------------------------------------------
n = len(spec['slides'])
for i, (big, text) in enumerate(spec['slides'], 1):
    im, d = desktop()
    ix0, iy0, ix1, iy1 = window(d, (150, 150, W - 60, H - 150), '%s.txt  —  %d of %d' % (name, i, n))
    fb, rb, sb = fit(d, big.upper(), HEAD, ix1 - ix0, 300, 210, 90); y = iy0
    for r_ in rb: d.text((ix0, y), r_, font=fb, fill=TITLE[0]); y += sb * 1.05
    ft, rt, st = fit(d, text, BODY, ix1 - ix0, iy1 - y - 150, 58, 34, 1.32); y += 36
    for r_ in rt: d.text((ix0, y), r_, font=ft, fill=(0, 0, 0)); y += st * 1.32
    if i < n: button(d, ix1 - 240, iy1 - 66, 'next >')
    d.text((ix0, iy1 - 52), '@' + spec['handle'], font=font(BODY, 28), fill=DARK)
    im.save(os.path.join(out, '%02d.jpg' % (i + 1)), quality=92)

# ---- last: follow, sources, music ------------------------------------------------------------------
im, d = desktop()
ix0, iy0, ix1, iy1 = window(d, (150, 230, W - 60, H - 190), 'save_this.txt')
f, rows, size = fit(d, 'SAVE THIS. FOLLOW FOR MORE OF WHAT WE GREW UP WITH', HEAD, ix1 - ix0, 430, 120); y = iy0
for r_ in rows: d.text((ix0, y), r_, font=f, fill=(0, 0, 0)); y += size * 1.12
y += 20; button(d, ix0, y, '@' + spec['handle']); y += 120
fs = font(BODY, 28)
for r_ in wrap(d, spec['sources'] + ('. Cover ' + PHOTO[1] if PHOTO else ''), fs, ix1 - ix0): d.text((ix0, y), r_, font=fs, fill=DARK); y += 40
d.text((ix0, y + 20), spec.get('music', ''), font=font(BODY, 30), fill=TITLE[0])
im.save(os.path.join(out, '%02d.jpg' % (n + 2)), quality=92); print('wrote', n + 2, 'slides to', out)
