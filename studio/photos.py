"""Real photos for carousels and fact reels, from Wikimedia Commons, and only ones anyone may reuse.

A spec names Commons files: the cover's  "image": {"file": "Blockbuster 6178.jpg"}  and each slide's as a
third item,  ["BIG WORD", "sentence", ["File one.jpg", "File two.jpg"]]  (one a slide on psychedelic.station,
one to three on nostalgia.hub.vhs). A name starting with "?" is a search instead of a file:
"?Big Ear radio telescope" is looked up on Commons once, by the fetch step, which keeps the first freely
licensed photo of a usable size that no other slide of any carousel already uses, and records the choice
in studio/photos/queries.json (so a bad pick is fixed by rewording the search or naming a file).

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
NO_CREDIT = re.compile(r'^(public domain|pd\b|pd-|cc0)', re.I)   # what a video can show with nowhere to put a credit
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'photos'); INDEX = os.path.join(STORE, 'index.json')
CACHE = STORE; QUERIES = os.path.join(STORE, 'queries.json')
UA = {'User-Agent': 'CloseQuartersCarousels/1.0 (https://closequarters.vip; contact via the site) python-urllib/3'}


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


def get(file, width=1400, slug=''):
    """(local path, credit) for a stored photo; outside the fetch step this never downloads. A "?search"
    name gives the photo its search was resolved to, or None until it has been."""
    if file.startswith('?'):
        file = _queries().get(slug + '|' + file[1:].strip())
        if not file: return None
    return stored(file) or (fetch(file, width) if os.environ.get('CQ_PHOTO_FETCH') else None)


def _queries():
    try: return json.load(open(QUERIES))
    except (OSError, ValueError): return {}


SKIP = re.compile(r'\b(logo|map|maps|diagram|chart|flag|coat of arms|icon|signature|seal|locator|wordmark|svg|stamp)\b', re.I)


STOP = set('the a an of on in at and or for to with from by over under above near its his her their 1950s 1960s 1970s 1990s 2000s photo photograph image'.split())


def _words(text):
    import unicodedata
    t = unicodedata.normalize('NFD', (text or '').lower()); t = ''.join(c for c in t if not unicodedata.combining(c))
    return [w for w in re.split(r'[^a-z0-9]+', t) if w and (len(w) > 2 or re.search(r'\d', w)) and w not in STOP]


def search(q, n=30, width=1400, uncredited=False):
    """Titles of freely licensed, photo-sized Commons images for a search, best match first. Commons' own search
    is loose ("Big Ear telescope" finds paragliders with big ears), so a result has to carry most of the search's
    words in its title, description or categories, and always the first one, which is written to be the key word."""
    p = dict(action='query', format='json', generator='search', gsrsearch=q + ' filetype:bitmap', gsrnamespace=6,
             gsrlimit=n, prop='imageinfo', iiprop='extmetadata|mime|size')
    pages = (json.loads(_open(API + '?' + urllib.parse.urlencode(p))).get('query') or {}).get('pages') or {}
    want = _words(q); out = []
    for pg in sorted(pages.values(), key=lambda pg: pg.get('index', 99)):
        ii = (pg.get('imageinfo') or [{}])[0]; meta = ii.get('extmetadata') or {}
        if not (NO_CREDIT if uncredited else FREE).match(_clean((meta.get('LicenseShortName') or {}).get('value'))): continue
        if ii.get('mime') not in ('image/jpeg', 'image/png'): continue
        w, h = ii.get('width') or 0, ii.get('height') or 0
        if min(w, h) < 500 or not 0.4 < w / max(h, 1) < 2.8: continue
        if SKIP.search(pg['title']) and not SKIP.search(q): continue
        have = set(_words(' '.join([pg['title'], _clean((meta.get('ObjectName') or {}).get('value')), _clean((meta.get('ImageDescription') or {}).get('value')),
                                    (meta.get('Categories') or {}).get('value') or ''])))
        sc = sum(t in have for t in want) / max(1, len(want)); first = bool(want) and want[0] in have
        if sc >= 0.6 or (sc >= 0.5 and first): out.append((-sc, pg.get('index', 99), pg['title']))
    return [t for _, _, t in sorted(out)]


def slide_photos(slide, slug=''):
    """[(path, credit)] for a spec slide's photos that are stored."""
    names = slide[2] if len(slide) > 2 and isinstance(slide[2], list) else []
    return [p for p in (get(n, slug=slug) for n in names) if p]


def credits(spec):
    """Every credit a carousel shows, once each, for its sources slide."""
    out = []
    for p in [for_spec(spec)] + [x for s in spec.get('slides', []) for x in slide_photos(s, spec.get('slug', ''))]:
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


def resolve(specs):
    """Turn every unresolved "?search" in the specs into a Commons file, recorded in queries.json. Each photo
    is used once across all carousels, so two slides never show the same picture."""
    import time
    qs = _queries()
    used = {('File:' + n if not n.startswith('File:') else n) for sp in specs for n in
            [(sp.get('image') or {}).get('file') or ''] + [x for sl in sp.get('slides', []) if len(sl) > 2 and isinstance(sl[2], list) for x in sl[2]]
            if n and not n.startswith('?')} | {v for v in qs.values() if v}
    made = 0
    for sp in specs:
        for sl in sp.get('slides', []):
            for n in (sl[2] if len(sl) > 2 and isinstance(sl[2], list) else []):
                if not n.startswith('?'): continue
                key = sp.get('slug', '') + '|' + n[1:].strip()
                if qs.get(key): continue
                try: found = search(n[1:].strip(), uncredited=sp.get('uncredited', False))
                except Exception as exc: print('search failed %r: %r' % (n, exc)); continue
                pick = next((t for t in found if t not in used), None)
                for t in [pick] if pick else []:
                    try:
                        if not fetch(t): pick = None
                    except Exception as exc: print('could not fetch %s: %r' % (t, exc)); pick = None
                print('%-60s -> %s' % (key[:60], pick or 'nothing usable'))
                qs[key] = pick or ''
                if pick: used.add(pick); made += 1
                json.dump(qs, open(QUERIES, 'w'), indent=1, ensure_ascii=False, sort_keys=True)
                time.sleep(1.0)
    print('resolved %d searches' % made)


def song_pictures(slug):
    """{line number: [photo paths]} for a song's lyric lines: studio/songs/<slug>/pictures.json names searches
    per line, resolved (public domain and CC0 only, since a video has nowhere to put a credit) by the fetch step."""
    here = os.path.dirname(os.path.abspath(__file__))
    try: spec = json.load(open(os.path.join(here, 'songs', slug, 'pictures.json')))
    except (OSError, ValueError): return {}
    out = {}
    for k, qs in (spec.get('lines') or {}).items():
        got = [p[0] for p in (get('?' + q, slug='song:' + slug) for q in qs) if p]
        if got: out[int(k)] = got
    return out


def _song_specs():
    """The songs' picture searches, shaped like carousel specs so resolve() can treat them the same way."""
    import glob
    here = os.path.dirname(os.path.abspath(__file__)); out = []
    for f in sorted(glob.glob(os.path.join(here, 'songs', '*', 'pictures.json'))):
        sp = json.load(open(f)); slug = os.path.basename(os.path.dirname(f))
        out.append(dict(slug='song:' + slug, uncredited=True, slides=[['', '', ['?' + q for q in qs]] for _, qs in sorted((sp.get('lines') or {}).items(), key=lambda kv: int(kv[0]))]))
    return out


def _specs():
    import glob
    here = os.path.dirname(os.path.abspath(__file__)); out = []
    for f in sorted(glob.glob(os.path.join(here, 'carousels', '**', '*.json'), recursive=True)):
        if os.path.basename(f) in ('posted.json', 'reeled.json'): continue
        out.append(json.load(open(f)))
    return out


if __name__ == '__main__' and sys.argv[1:2] == ['fetch']:
    import time
    want = []
    for sp in _specs():
        im = sp.get('image') or {}
        if im.get('file'): want.append(im['file'])
        for sl in sp.get('slides', []):
            if len(sl) > 2 and isinstance(sl[2], list): want += [x for x in sl[2] if not x.startswith('?')]
    todo = [w for w in dict.fromkeys(want) if not stored(w)]
    print('%d photos named, %d to fetch' % (len(set(want)), len(todo)))
    got = 0
    for w in todo:
        try:
            if fetch(w): got += 1
        except Exception as exc: print('could not fetch %s: %r' % (w, exc))
        time.sleep(2)
    print('fetched %d' % got)
    resolve(_specs() + _song_specs())
