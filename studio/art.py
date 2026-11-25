"""Public-domain paintings and prints for the museum-zoom page (studio/zoom_video.py).

    python studio/art.py fetch [--max N]     (GitHub Actions: find, download and upload new works)
    python studio/art.py pull                (download the library into studio/art/cache)

Only works their museum releases as public domain / CC0, at full size:
  met        The Metropolitan Museum of Art Open Access (isPublicDomain, primaryImage is the full-size file)
  cleveland  The Cleveland Museum of Art Open Access (share_license_status CC0, the "print" image, ~3400 px)
  aic        The Art Institute of Chicago (is_public_domain, IIIF at up to 3000 px)
Each image is kept at up to 6000 px on its long side, uploaded to the GitHub release "art-library" and recorded in
studio/art/index.json with title, artist, date, museum, licence and the museum's page. Rendering only reads that
library. The queries are in studio/art/queries.json ("met>Bruegel" asks one museum, a plain query asks all three).

What is never taken: nudes, scenes of violence or martyrdom, battles, and caricature (BLOCK, on the title, the
artist's note and the museum's tags), and any picture that is mostly skin or too small to zoom into.
"""
import json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'art')
INDEX = os.path.join(DIR, 'index.json'); QUERIES = os.path.join(DIR, 'queries.json'); CACHE = os.path.join(DIR, 'cache')
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'art-library'
UA = {'User-Agent': 'CloseQuartersArt/1.0 (https://closequarters.vip) python-urllib/3'}
MIN_SIDE, MAX_SIDE, PER_QUERY = 2400, 6000, 4

BLOCK = re.compile(r'nud|naked|venus|bath|susanna|leda\b|dana[eë]|bathsheba|nymph|odalisque|toilet|bacchan|satyr|cupid|'
                   r'eros\b|psyche|lucretia|cleopatra|judith|holofernes|salome|martyr|crucifi|flagellat|lament|pieta|pietà|'
                   r'entomb|deposition|massacre|execution|behead|torture|murder|rape|abduct|battle|war\b|siege|slaughter|'
                   r'corpse|death|dead|dying|wound|hunt|harem|slave|blackamoor|caricature|erotic|shunga|lovers|seduc|'
                   r'kiss|embrace|breast|courtesan|brothel|bordello|toilette|abuse', re.I)


def _open(url, raw=False, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = r.read()
                return data if raw else json.loads(data)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404) or k == tries - 1: raise
            time.sleep(5 * (k + 1))
        except (urllib.error.URLError, TimeoutError):
            if k == tries - 1: raise
            time.sleep(5 * (k + 1))


def _yr(v):
    m = re.search(r'\b(1[0-9]\d\d)\b', str(v or ''))
    return int(m.group(1)) if m else None


def index():
    try:
        with open(INDEX) as f: return json.load(f)
    except (OSError, ValueError): return {'works': [], 'seen': []}


# ---------------------------------------------------------------- sources: each yields dict(key, title, artist, date, museum, licence, page, url)
def met(q, n=PER_QUERY):
    ids = (_open('https://collectionapi.metmuseum.org/public/collection/v1/search?' + urllib.parse.urlencode(dict(hasImages='true', q=q))) or {}).get('objectIDs') or []
    got = 0
    for oid in ids[:80]:
        if got >= n: return
        key = 'met:%d' % oid
        if key in SEEN: continue
        o = _open('https://collectionapi.metmuseum.org/public/collection/v1/objects/%d' % oid); time.sleep(0.1)
        tags = ' '.join(t.get('term', '') for t in o.get('tags') or [])
        if not o.get('isPublicDomain') or not o.get('primaryImage'): continue
        if blocked('%s %s %s %s' % (o.get('title'), tags, o.get('objectName'), o.get('classification'))): continue
        got += 1
        yield dict(key=key, title=o.get('title') or '', artist=o.get('artistDisplayName') or '', date=o.get('objectDate') or '',
                   museum='The Met', licence='Public Domain (The Met Open Access, CC0)', page=o.get('objectURL') or '', url=o['primaryImage'])


def cleveland(q, n=PER_QUERY):
    res = (_open('https://openaccess-api.clevelandart.org/api/artworks/?' + urllib.parse.urlencode(dict(q=q, cc0=1, has_image=1, limit=60))) or {}).get('data') or []
    got = 0
    for o in res:
        if got >= n: return
        key = 'cleveland:%s' % o.get('id')
        img = ((o.get('images') or {}).get('print') or {}).get('url')
        if key in SEEN or not img or o.get('share_license_status') != 'CC0': continue
        if blocked('%s %s %s' % (o.get('title'), o.get('type'), ' '.join(o.get('culture') or []))): continue
        got += 1
        who = ((o.get('creators') or [{}])[0] or {}).get('description') or ''
        yield dict(key=key, title=o.get('title') or '', artist=re.sub(r'\s*\(.*$', '', who), date=o.get('creation_date') or '',
                   museum='The Cleveland Museum of Art', licence='CC0 (Cleveland Museum of Art Open Access)', page=o.get('url') or '', url=img)


def aic(q, n=PER_QUERY):
    p = dict(q=q, limit=60, fields='id,title,artist_title,date_display,image_id,is_public_domain,classification_title,subject_titles,term_titles')
    res = (_open('https://api.artic.edu/api/v1/artworks/search?' + urllib.parse.urlencode(p)) or {}).get('data') or []
    got = 0
    for o in res:
        if got >= n: return
        key = 'aic:%s' % o.get('id')
        if key in SEEN or not o.get('is_public_domain') or not o.get('image_id'): continue
        if blocked('%s %s %s %s' % (o.get('title'), o.get('classification_title'), ' '.join(o.get('subject_titles') or []), ' '.join(o.get('term_titles') or []))): continue
        got += 1
        yield dict(key=key, title=o.get('title') or '', artist=o.get('artist_title') or '', date=o.get('date_display') or '',
                   museum='The Art Institute of Chicago', licence='CC0 (Art Institute of Chicago)', page='https://www.artic.edu/artworks/%s' % o['id'],
                   url='https://www.artic.edu/iiif/2/%s/full/3000,/0/default.jpg' % o['image_id'], alt='https://www.artic.edu/iiif/2/%s/full/1686,/0/default.jpg' % o['image_id'])


SOURCES = {'met': met, 'cleveland': cleveland, 'aic': aic}
SEEN = set()


def blocked(text):
    return bool(BLOCK.search(text or ''))


def skin(img):
    """The share of a picture that is skin-coloured (YCrCb box), for leaving out nudes no title warned of."""
    import numpy as np, cv2
    small = cv2.resize(img, (400, int(400 * img.shape[0] / img.shape[1])), interpolation=cv2.INTER_AREA)
    y = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
    m = (y[..., 1] > 138) & (y[..., 1] < 173) & (y[..., 2] > 77) & (y[..., 2] < 127) & (y[..., 0] > 80)
    return float(m.mean())


def keep(data, path):
    """Decode, check and save one image; (width, height) or None if it is not worth keeping."""
    import numpy as np, cv2
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None: return None
    h, w = img.shape[:2]
    if max(h, w) < MIN_SIDE or skin(img) > 0.30: return None
    s = min(1.0, MAX_SIDE / max(h, w))
    if s < 1: img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return img.shape[1], img.shape[0]


def fetch(maximum):
    idx = index(); seen = set(idx.get('seen', [])); SEEN.clear(); SEEN.update(seen)
    with open(QUERIES) as f: qs = json.load(f)
    work = os.path.join(DIR, 'new'); os.makedirs(work, exist_ok=True); new = []
    jobs = []
    for q in qs:
        src, sep, rest = q.partition('>')
        jobs += [(src, rest.strip())] if sep and src in SOURCES else [(s, q) for s in SOURCES]
    for src, q in jobs:
        if len(new) >= maximum: break
        print('  %s %r' % (src, q), flush=True)
        try:
            for o in SOURCES[src](q):
                if len(new) >= maximum: break
                seen.add(o['key']); SEEN.add(o['key'])
                try: data = _open(o['url'], raw=True)
                except urllib.error.HTTPError:
                    if not o.get('alt'): continue
                    data = _open(o['alt'], raw=True)
                name = re.sub(r'[^a-z0-9]+', '_', o['key'].lower()) + '.jpg'
                size = keep(data, os.path.join(work, name))
                if not size: print('  - %s (small or skin)' % o['title'][:60]); continue
                e = dict(o, asset=name, w=size[0], h=size[1], year=_yr(o['date'])); e.pop('url', None); e.pop('alt', None)
                idx.setdefault('works', []).append(e); new.append(e); print('+ %-10s %s, %s' % (src, e['title'][:50], e['artist'][:30]), flush=True)
                time.sleep(0.5)
        except Exception as exc:
            print('  %s %r: %s' % (src, q, exc))
    idx['seen'] = sorted(seen)
    if new:
        if subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode:
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Art library (public domain)', '--notes',
                            'Public-domain and CC0 paintings and prints for the museum-zoom page. Sources and licences: studio/art/index.json'], check=True)
        files = [os.path.join(work, e['asset']) for e in new]
        for k in range(0, len(files), 20): subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + files[k:k + 20], check=True)
    with open(INDEX, 'w') as f: json.dump(idx, f, indent=1, ensure_ascii=False); f.write('\n')
    print('%d new works, %d in the library' % (len(new), len(idx.get('works', []))))


def pull():
    os.makedirs(CACHE, exist_ok=True)
    want = [e for e in index().get('works', []) if not blocked('%s %s' % (e.get('title'), e.get('artist')))]
    missing = [e for e in want if not os.path.exists(os.path.join(CACHE, e['asset']))]
    if missing:
        rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
        ids = {a['name']: a['id'] for a in rel.get('assets', [])}
        for e in missing:
            if e['asset'] not in ids: continue
            with open(os.path.join(CACHE, e['asset']), 'wb') as fh:
                fh.write(subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream', 'repos/%s/releases/assets/%d' % (REPO, ids[e['asset']])], capture_output=True, check=True).stdout)
    return [e for e in want if os.path.exists(os.path.join(CACHE, e['asset']))]


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'fetch': fetch(int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 60)
    elif cmd == 'pull': print(len(pull()), 'works cached')
    else: sys.exit(__doc__)
