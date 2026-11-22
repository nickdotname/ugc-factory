"""Real photos for carousels and fact reels, from Wikimedia Commons, and only ones anyone may reuse.

A spec names Commons files: the cover's  "image": {"file": "Blockbuster 6178.jpg"}  and each slide's as a
third item,  ["BIG WORD", "sentence", ["File one.jpg", "File two.jpg"]]  (one a slide on psychedelic.station,
one to three on nostalgia.hub.vhs).

Wikimedia refuses requests from GitHub's servers at busy times, so photos are fetched ahead of time and
kept in the repo:  python studio/photos.py fetch  downloads every photo the specs name that is not stored
yet (slowly, with retries), into studio/photos/, and records its licence and credit in
studio/photos/index.json. Only public domain, CC0, CC BY and CC BY-SA are accepted. Rendering reads the
stored copy and never touches the network; a photo that is not stored is left out, never the post.

Placing the photo inside our own slide design, with our own words over it, is what keeps the post
original under Instagram's rules for reused content.
"""
import hashlib, json, os, re, sys, urllib.error, urllib.parse, urllib.request

API = 'https://commons.wikimedia.org/w/api.php'
FREE = re.compile(r'^(public domain|pd\b|pd-|cc0|cc by(-sa)?\b|cc-by)', re.I)
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'photos'); INDEX = os.path.join(STORE, 'index.json')
CACHE = STORE
UA = {'User-Agent': 'CloseQuartersCarousels/1.0 (https://closequarters.vip; closequartersandloosechange@gmail.com) python-urllib/3'}


def _clean(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html or '')).strip()


def credit_for(meta):
    lic = _clean((meta.get('LicenseShortName') or {}).get('value'))
    who = _clean((meta.get('Artist') or {}).get('value'))[:60]
    if re.match(r'^(public domain|pd)', lic, re.I):
        return 'photo: %s (public domain) / Wikimedia Commons' % who if who else 'photo: public domain / Wikimedia Commons'
    return 'photo: %s / %s / Wikimedia Commons' % (who or 'unknown', lic)


def _index():
    try: return json.load(open(INDEX))
    except (OSError, ValueError): return {}


def stored(file):
    """(local path, credit) for a photo already in studio/photos/, or None."""
    title = file if file.startswith('File:') else 'File:' + file
    e = _index().get(title)
    if e and os.path.exists(os.path.join(STORE, e['file'])): return os.path.join(STORE, e['file']), e['credit']
    return None


def _open(url, tries=4):
    import time
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or k == tries - 1: raise
            time.sleep((10, 45, 120)[min(k, 2)])


def fetch(file, width=1400):
    """Download one photo into the store if its licence allows it. Returns (path, credit) or None."""
    title = file if file.startswith('File:') else 'File:' + file
    have = stored(title)
    if have: return have
    q = urllib.parse.urlencode(dict(action='query', format='json', titles=title, prop='imageinfo', iiprop='url|extmetadata|mime', iiurlwidth=width))
    page = next(iter(json.loads(_open(API + '?' + q))['query']['pages'].values()))
    ii = page['imageinfo'][0]; meta = ii.get('extmetadata') or {}
    lic = _clean((meta.get('LicenseShortName') or {}).get('value'))
    if not FREE.match(lic):
        print('refused, licence %r: %s' % (lic, title)); return None
    data = _open(ii.get('thumburl') or ii['url'])
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(data)).convert('RGB'); im.thumbnail((width, width))
    name = hashlib.sha1(title.encode()).hexdigest()[:16] + '.jpg'
    os.makedirs(STORE, exist_ok=True); im.save(os.path.join(STORE, name), quality=86)
    idx = _index(); idx[title] = dict(file=name, credit=credit_for(meta), licence=lic, page='https://commons.wikimedia.org/wiki/' + urllib.parse.quote(title.replace(' ', '_')))
    json.dump(idx, open(INDEX, 'w'), indent=1, ensure_ascii=False, sort_keys=True)
    return os.path.join(STORE, name), idx[title]['credit']


def get(file, width=1400):
    """(local path, credit) for a stored photo; outside the fetch step this never downloads."""
    return stored(file) or (fetch(file, width) if os.environ.get('CQ_PHOTO_FETCH') else None)


def slide_photos(slide):
    """[(path, credit)] for a spec slide's photos that are stored."""
    names = slide[2] if len(slide) > 2 and isinstance(slide[2], list) else []
    return [p for p in (get(n) for n in names) if p]


def credits(spec):
    """Every credit a carousel shows, once each, for its sources slide."""
    out = []
    for p in [for_spec(spec)] + [x for s in spec.get('slides', []) for x in slide_photos(s)]:
        if p and p[1] not in out: out.append(p[1])
    return out


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


if __name__ == '__main__' and sys.argv[1:2] == ['fetch']:
    import glob, time
    here = os.path.dirname(os.path.abspath(__file__)); want = []
    for f in sorted(glob.glob(os.path.join(here, 'carousels', '**', '*.json'), recursive=True)):
        if os.path.basename(f) in ('posted.json', 'reeled.json'): continue
        sp = json.load(open(f)); im = sp.get('image') or {}
        if im.get('file'): want.append(im['file'])
        for sl in sp.get('slides', []):
            if len(sl) > 2 and isinstance(sl[2], list): want += sl[2]
    todo = [w for w in dict.fromkeys(want) if not stored(w)]
    print('%d photos named, %d to fetch' % (len(set(want)), len(todo)))
    got = 0
    for w in todo:
        try:
            if fetch(w): got += 1
        except Exception as exc: print('could not fetch %s: %r' % (w, exc))
        time.sleep(2)
    print('fetched %d' % got)
