#!/usr/bin/env python3
"""Make an information carousel: a cover with a headline over psychedelic art, then one fact a slide.

    python studio/carousel.py studio/carousels/<name>.json <seed> <out_dir>

Writes 01.jpg, 02.jpg ... at 1080x1350 (Instagram's tall post). The art is generated here (no
photos): the seed picks the pattern and colours. The .json holds the words: a headline, the
slides as [big word, sentence], a sources line and a music credit.
"""
import sys, os, json, random
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

spec = json.load(open(sys.argv[1])); seed = int(sys.argv[2]); out = sys.argv[3]; os.makedirs(out, exist_ok=True)
W, H = 1080, 1350; rng = random.Random(seed); HERE = os.path.dirname(os.path.abspath(__file__))
def font(names, size):
    for n in names:
        for d in ('/usr/share/fonts/truetype/google-fonts/ofl/anton/', '/usr/share/fonts/truetype/google-fonts/', '/usr/share/fonts/truetype/dejavu/', os.path.join(HERE, '..', 'fonts') + '/'):
            if os.path.exists(d + n): return ImageFont.truetype(d + n, size)
    return ImageFont.truetype(os.path.join(HERE, '..', 'fonts', 'Montserrat-ExtraBold.ttf'), size)
HEAD = ['Anton-Regular.ttf', 'Montserrat-ExtraBold.ttf']; BODY = ['Poppins-SemiBold.ttf', 'Poppins-Bold.ttf', 'DejaVuSans-Bold.ttf']
PALS = [[(.5, .5, .5), (.5, .5, .5), (1, 1, 1), (0, .33, .67)], [(.5, .5, .5), (.5, .5, .5), (1, 1, .5), (.8, .9, .3)], [(.5, .5, .5), (.5, .5, .5), (2, 1, 0), (.5, .2, .25)], [(.8, .5, .4), (.2, .4, .2), (2, 1, 1), (0, .25, .25)]]
pal = rng.choice(PALS)

def art(w, h, s, kind=None, sym=None):
    r = random.Random(s); kind = kind or r.choice(['kaleido', 'rings', 'marble', 'tunnel']); sym = sym or r.choice([5, 6, 8, 12]); sc = r.uniform(2.5, 4.5); T = r.uniform(0, 20)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32); X = (xs - w / 2) / (w / 2); Y = (ys - h / 2) / (w / 2); R = np.sqrt(X * X + Y * Y) + 1e-6; A = np.arctan2(Y, X)
    if kind == 'kaleido': a = np.abs(((A / (6.28318 / sym)) % 1) - .5) * 2; f = np.sin(R * sc * 3 - T + a * 5) * .5 + np.sin(a * 9 + R * sc * 2 + T) * .5
    elif kind == 'rings': f = np.sin((R + np.sin(A * sym + T) * .06) * sc * 6 - T)
    elif kind == 'tunnel': d = 1 / (R + .12); f = np.sin(d * sc * .8 + T) * .6 + np.sin(A * sym + d * 1.5) * .4
    else: u = X * sc + np.sin(Y * sc * 1.3 + T) * 1.2; v = Y * sc + np.cos(u * 1.1 - T) * 1.2; f = np.sin(u + np.sin(v * 1.7) * 2) * .5 + np.cos(v * .8) * .5
    t = np.floor((f * .3 + R * .12 + T * .05) * 10) / 10 if r.random() < .5 else f * .3 + R * .12 + T * .05
    a_, b_, c_, d_ = [np.array(v, np.float32) for v in pal]; img = a_ + b_ * np.cos(6.28318 * (c_ * t[..., None] + d_))
    img *= (.75 + .25 * np.cos(f * 16))[..., None]
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)

def wrap(d, text, f, maxw):
    rows, cur = [], ''
    for wd in text.split():
        if cur and d.textlength(cur + ' ' + wd, font=f) > maxw: rows.append(cur); cur = wd
        else: cur = (cur + ' ' + wd).strip()
    return rows + [cur]
def fit(d, text, names, maxw, maxh, hi, lo=40, lead=1.08):
    for size in range(hi, lo - 1, -4):
        f = font(names, size); rows = wrap(d, text, f, maxw)
        if len(rows) * size * lead <= maxh: return f, rows, size
    return f, rows, size
def tag(d, x, y, text, f, bg=(255, 230, 60), fg=(0, 0, 0)):
    w = d.textlength(text, font=f); d.rectangle([x, y, x + w + 24, y + f.size + 14], fill=bg); d.text((x + 12, y + 4), text, font=f, fill=fg)

# ---- cover: art (or the topic's real photo) on top, headline on black below -----------------
sys.path.insert(0, HERE); import photos
PHOTO = photos.for_spec(spec)                                  # (path, credit) or None
if PHOTO:
    # The real thing, tinted towards the art so it still reads as this account's post
    p_ = photos.fit_image(PHOTO[0], W, H).astype(np.float32); a_ = art(W, H, seed * 7 + 1).astype(np.float32)
    g = p_.mean(axis=2, keepdims=True); a = np.clip(p_ * .9 + (g / 255.0) * a_ * .22, 0, 255).astype(np.uint8)
    im = Image.fromarray(a); d = ImageDraw.Draw(im, 'RGBA')
else:
    a = art(W, H, seed * 7 + 1); im = Image.fromarray(a); d = ImageDraw.Draw(im, 'RGBA')
    ins = Image.fromarray(art(360, 360, seed * 7 + 2)); mask = Image.new('L', (360, 360), 0); ImageDraw.Draw(mask).ellipse([0, 0, 359, 359], fill=255)
    im.paste(ins, (40, 300), mask); d.ellipse([36, 296, 404, 664], outline=(255, 255, 255), width=8)       # the round inset
for y in range(620, H): d.line([(0, y), (W, y)], fill=(0, 0, 0, int(min(255, (y - 620) * 1.7))))     # fade to black
f, rows, size = fit(d, spec['headline'].upper(), HEAD, W - 80, 520, 112); y = H - 110 - len(rows) * size * 1.08
for r_ in rows: d.text(((W - d.textlength(r_, font=f)) / 2, y), r_, font=f, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0)); y += size * 1.08
tag(d, W - 190, H - 84, 'SWIPE', font(HEAD, 40)); d.text((40, H - 78), 'SWIPE FOR MORE', font=font(BODY, 24), fill=(255, 255, 255))
d.text((36, 30), 'PS', font=font(HEAD, 64), fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
if PHOTO:
    fc = font(BODY, 20); cw = d.textlength(PHOTO[1], font=fc)
    d.text((W - 30 - min(cw, W - 200), 44), PHOTO[1][:90], font=fc, fill=(255, 255, 255, 220), stroke_width=2, stroke_fill=(0, 0, 0))
im.save(os.path.join(out, '01.jpg'), quality=92)

# ---- one fact a slide ----------------------------------------------------------------------
n = len(spec['slides'])
for i, (big, text) in enumerate(spec['slides'], 1):
    a = (art(W, H, seed * 7 + 10 + i).astype(np.float32) * .28).astype(np.uint8); im = Image.fromarray(a); d = ImageDraw.Draw(im, 'RGBA')
    d.text((60, 60), '%d / %d' % (i, n), font=font(BODY, 34), fill=(255, 255, 255, 190)); d.text((W - 60 - d.textlength('@' + spec['handle'], font=font(BODY, 30)), 64), '@' + spec['handle'], font=font(BODY, 30), fill=(255, 255, 255, 170))
    fb, rb, sb = fit(d, big.upper(), HEAD, W - 120, 330, 260, 110); y = 250
    for r_ in rb: d.text((60, y), r_, font=fb, fill=(255, 230, 60)); y += sb * 1.05
    ft, rt, st = fit(d, text, BODY, W - 120, H - y - 220, 62, 36, 1.32); y += 40
    for r_ in rt: d.text((60, y), r_, font=ft, fill=(255, 255, 255)); y += st * 1.32
    if i < n: tag(d, W - 190, H - 84, 'SWIPE', font(HEAD, 40))
    im.save(os.path.join(out, '%02d.jpg' % (i + 1)), quality=92)

# ---- last: sources, music, follow ----------------------------------------------------------
a = (art(W, H, seed * 7 + 99).astype(np.float32) * .45).astype(np.uint8); im = Image.fromarray(a); d = ImageDraw.Draw(im, 'RGBA')
f, rows, size = fit(d, 'FOLLOW FOR MORE OF WHAT THEY LEFT OUT', HEAD, W - 120, 520, 150); y = 330
for r_ in rows: d.text(((W - d.textlength(r_, font=f)) / 2, y), r_, font=f, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0)); y += size * 1.08
h_ = '@' + spec['handle']; fh = font(BODY, 54); tag(d, (W - d.textlength(h_, font=fh)) / 2 - 12, y + 40, h_, fh)
fs = font(BODY, 28); y = H - 230
srcs = spec['sources'] + ('. Cover ' + PHOTO[1] if PHOTO else '')
y = H - 230 - (40 if PHOTO else 0)
for r_ in wrap(d, srcs, fs, W - 120): d.text((60, y), r_, font=fs, fill=(255, 255, 255, 200)); y += 40
d.text((60, y + 16), spec.get('music', ''), font=font(BODY, 32), fill=(255, 230, 60))
im.save(os.path.join(out, '%02d.jpg' % (n + 2)), quality=92); print('wrote', n + 2, 'slides to', out)
