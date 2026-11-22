"""Real photos for carousels and fact reels, from Wikimedia Commons, and only ones anyone may reuse.

A spec names a Commons file:   "image": {"file": "Blockbuster 6178.jpg"}
get() asks Commons for the file's licence and author, refuses anything that is not public domain, CC0,
CC BY or CC BY-SA, downloads a 1600px copy into a cache, and returns the local path with a credit line,
e.g. "photo: Steve Morgan / CC BY-SA 4.0 / Wikimedia Commons". The credit goes on the slide that shows
the photo and on the sources slide. If anything fails, get() returns None and the post is made without it.

Placing the photo inside our own slide design, with our own words over it, is what keeps the post
original under Instagram's rules for reused content.
"""
import hashlib, json, os, re, urllib.parse, urllib.request

API = 'https://commons.wikimedia.org/w/api.php'
FREE = re.compile(r'^(public domain|pd\b|pd-|cc0|cc by(-sa)?\b|cc-by)', re.I)
CACHE = os.environ.get('CQ_PHOTO_CACHE', os.path.join(os.path.expanduser('~'), '.cache', 'cq-photos'))
UA = {'User-Agent': 'CloseQuartersClipEngine/0.1 (carousel photos; contact closequarters.vip)'}


def _clean(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html or '')).strip()


def credit_for(meta):
    lic = _clean((meta.get('LicenseShortName') or {}).get('value'))
    who = _clean((meta.get('Artist') or {}).get('value'))[:60]
    if re.match(r'^(public domain|pd)', lic, re.I):
        return 'photo: %s (public domain) / Wikimedia Commons' % who if who else 'photo: public domain / Wikimedia Commons'
    return 'photo: %s / %s / Wikimedia Commons' % (who or 'unknown', lic)


def get(file, width=1600):
    """(local path, credit) for a Commons file, or None."""
    title = file if file.startswith('File:') else 'File:' + file
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(title.encode()).hexdigest()[:16]
    meta_path = os.path.join(CACHE, key + '.json')
    try:
        if os.path.exists(meta_path):
            m = json.load(open(meta_path))
            if os.path.exists(m['path']): return m['path'], m['credit']
        q = urllib.parse.urlencode(dict(action='query', format='json', titles=title, prop='imageinfo',
                                        iiprop='url|extmetadata|mime', iiurlwidth=width))
        info = json.load(urllib.request.urlopen(urllib.request.Request(API + '?' + q, headers=UA), timeout=30))
        page = next(iter(info['query']['pages'].values()))
        ii = page['imageinfo'][0]; meta = ii.get('extmetadata') or {}
        lic = _clean((meta.get('LicenseShortName') or {}).get('value'))
        if not FREE.match(lic):
            print('photo refused, licence %r: %s' % (lic, title)); return None
        url = ii.get('thumburl') or ii['url']
        ext = '.png' if 'png' in (ii.get('mime') or '') else '.jpg'
        path = os.path.join(CACHE, key + ext)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, open(path, 'wb') as f:
            f.write(r.read())
        credit = credit_for(meta)
        json.dump(dict(path=path, credit=credit, title=title, licence=lic), open(meta_path, 'w'))
        return path, credit
    except Exception as exc:                                   # no photo is better than no post
        print('photo unavailable (%s): %r' % (title, exc)); return None


def for_spec(spec):
    """(path, credit) for a spec's "image", or None."""
    im = spec.get('image') if isinstance(spec, dict) else None
    if not im: return None
    if im.get('path') and os.path.exists(im['path']): return im['path'], im.get('credit', '')
    return get(im['file']) if im.get('file') else None


def fit_image(path, w, h, zoom=1.0, focus=(0.5, 0.42)):
    """The photo scaled to cover w x h (cropped, never stretched), as an RGB uint8 array. focus is where
    in the photo the crop centres (x, y as fractions); faces tend to sit a little above the middle."""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert('RGB'); sw, sh = im.size
    s = max(w / sw, h / sh) * zoom; nw, nh = max(w, int(sw * s + 0.5)), max(h, int(sh * s + 0.5))
    im = im.resize((nw, nh), Image.LANCZOS)
    x0 = int(min(max(focus[0] * nw - w / 2, 0), nw - w)); y0 = int(min(max(focus[1] * nh - h / 2, 0), nh - h))
    return np.asarray(im.crop((x0, y0, x0 + w, y0 + h)))
