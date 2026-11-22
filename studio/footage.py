"""Public-domain footage for glitch.archive: creeks, forests, cities, space, old film.

    python studio/footage.py fetch [--max N]     (GitHub Actions: find, cut and upload new clips)
    python studio/footage.py pull [THEME ...]    (download the library's clips into studio/footage/cache)

Only footage anyone may reuse with no credit is taken: Wikimedia Commons files marked public domain or CC0, the
Prelinger Archives films on archive.org marked public domain, and NASA video (not copyrighted, by US law). From
each film a few short pieces with real motion in them are cut (no sound, at most 960 px tall, a few MB each),
uploaded as assets of the GitHub release "footage-library", and recorded in studio/footage/index.json with their
source, licence and theme. Rendering (studio/glitch_video.py) only ever reads that library, so a source being
slow or down never stops a night's videos. The queries per theme are in studio/footage/queries.json.

The videos never show the footage as it was: every clip is moshed, tracked, sorted or smeared (glitch_video.py),
which is what Instagram means by original.
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'footage')
INDEX = os.path.join(DIR, 'index.json'); QUERIES = os.path.join(DIR, 'queries.json'); CACHE = os.path.join(DIR, 'cache')
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'footage-library'
UA = {'User-Agent': 'CloseQuartersFootage/1.0 (https://closequarters.vip; closequartersandloosechange@gmail.com) python-urllib/3'}
NO_CREDIT = re.compile(r'^(public domain|pd\b|pd-|cc0)', re.I)
CLIP_SEC, PER_FILM, MAX_H = 10.0, 3, 960
# Old ephemeral films include burlesque reels, tobacco and alcohol ads, war footage and racist caricature. None of
# that is taken: a title, subject or description with any of these words rules the whole film out.
BLOCK = re.compile(r'strip|burlesque|nud|naked|sex|venereal|cigar|tobacco|smok|beer|whisk|liquor|alcohol|drunk|'
                   r'war\b|wartime|combat|battle|army|navy|bomb|atomic|nuclear|weapon|gun|rifle|kill|death|dead|corpse|'
                   r'propaganda|nazi|hitler|racis|minstrel|blackface|savage|native|indian|negro|oriental|chinese|japanese|jap\b|'
                   r'crime|police|prison|drug|narcot|marijuana|reefer|venus|hygiene|birth|disease|surgery|hospital|accident|crash|riot|'
                   r'commercial|advertis|\bad\b|\bads\b|\bspot\b|sponsor|brand', re.I)


def _open(url, tries=4, raw=False):
    for k in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
            return r if raw else json.loads(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if k == tries - 1: raise
            time.sleep((5, 20, 60)[min(k, 2)])


def index():
    try: return json.load(open(INDEX))
    except (OSError, ValueError): return {'clips': [], 'seen': []}


def _clean(html): return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html or '')).strip()


# ---------------------------------------------------------------- sources: each yields (key, title, url of a playable file, duration, licence, page)
def commons(q, n=30):
    p = dict(action='query', format='json', generator='search', gsrsearch='%s filetype:video' % q, gsrnamespace=6, gsrlimit=n,
             prop='videoinfo', viprop='url|size|mime|extmetadata|derivatives')
    pages = (_open('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(p)).get('query') or {}).get('pages') or {}
    for pg in pages.values():
        vi = (pg.get('videoinfo') or [{}])[0]; meta = vi.get('extmetadata') or {}
        lic = _clean((meta.get('LicenseShortName') or {}).get('value'))
        desc = _clean((meta.get('ImageDescription') or {}).get('value')) + ' ' + _clean((meta.get('Categories') or {}).get('value'))
        if not NO_CREDIT.match(lic) or BLOCK.search(pg['title'] + ' ' + desc): continue
        ders = [d for d in vi.get('derivatives') or [] if d.get('type', '').startswith('video/')]
        ders.sort(key=lambda d: abs((d.get('height') or 0) - 720))
        src = ders[0]['src'] if ders else vi.get('url')
        if src: yield 'commons:' + pg['title'], pg['title'][5:], src, float(vi.get('duration') or 0), lic, vi.get('descriptionurl', '')


def prelinger(q, n=6):
    terms = ' AND '.join('(title:(%s) OR subject:(%s))' % (w, w) for w in q.split()[:2])
    p = {'q': 'collection:prelinger AND mediatype:movies AND %s' % terms, 'fl[]': ['identifier', 'title', 'licenseurl', 'subject', 'description'], 'rows': n, 'output': 'json', 'sort[]': 'downloads desc'}
    docs = (_open('https://archive.org/advancedsearch.php?' + urllib.parse.urlencode(p, doseq=True)).get('response') or {}).get('docs') or []
    for d in docs:
        lic = d.get('licenseurl') or ''
        blob = ' '.join(str(d.get(k) or '') for k in ('title', 'subject', 'description'))
        if 'publicdomain' not in lic or BLOCK.search(blob): continue
        md = _open('https://archive.org/metadata/%s' % d['identifier']); files = md.get('files') or []
        mp4 = [f for f in files if f.get('name', '').endswith('.mp4')]
        mp4.sort(key=lambda f: ('512kb' in f['name'], int(f.get('size') or 0)))           # the h.264 copy over the 512kb one
        if not mp4: continue
        f = mp4[0]; dur = float(f.get('length') or 0) if re.match(r'^[\d.]+$', str(f.get('length') or '')) else 0.0
        yield 'prelinger:' + d['identifier'], d.get('title', d['identifier']), 'https://archive.org/download/%s/%s' % (d['identifier'], urllib.parse.quote(f['name'])), dur, 'Public Domain (Prelinger Archives)', 'https://archive.org/details/' + d['identifier']


def nasa(q, n=5):
    items = ((_open('https://images-api.nasa.gov/search?' + urllib.parse.urlencode(dict(q=q, media_type='video'))).get('collection') or {}).get('items') or [])[:n]
    for it in items:
        data = (it.get('data') or [{}])[0]; nid = data.get('nasa_id')
        if not nid or BLOCK.search('%s %s' % (data.get('title', ''), data.get('description', ''))): continue
        got = _open(it['href']) if it.get('href') else []
        assets = [a if isinstance(a, str) else a.get('href', '') for a in got]
        pick = next((a for a in assets if a.endswith('~mobile.mp4')), None) or next((a for a in assets if a.endswith('~orig.mp4')), None)
        if pick: yield 'nasa:' + nid, data.get('title', nid), pick.replace('http://', 'https://'), 0.0, 'Public Domain (NASA)', 'https://images.nasa.gov/details/' + nid


SOURCES = {'commons': commons, 'prelinger': prelinger, 'nasa': nasa}
BY_THEME = {'space': ['nasa', 'commons'], 'archive': ['prelinger'], 'city': ['commons', 'prelinger'], 'water': ['commons', 'prelinger'], 'nature': ['commons', 'nasa']}


# ---------------------------------------------------------------- cutting
def probe(url):
    r = subprocess.run(['ffprobe', '-v', 'error', '-user_agent', UA['User-Agent'], '-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration', '-of', 'json', url],
                       capture_output=True, text=True, timeout=120)
    j = json.loads(r.stdout or '{}'); s = (j.get('streams') or [{}])[0]
    return float((j.get('format') or {}).get('duration') or 0), int(s.get('width') or 0), int(s.get('height') or 0)


def motion(path):
    """How much moves in a clip (0..1), and how bright it is: still, black or blank pieces are not worth keeping."""
    import numpy as np, cv2
    cap = cv2.VideoCapture(path); prev = None; diffs, lum = [], []
    while True:
        ok, f = cap.read()
        if not ok: break
        g = cv2.cvtColor(cv2.resize(f, (160, 160 * f.shape[0] // f.shape[1])), cv2.COLOR_BGR2GRAY).astype(np.float32)
        lum.append(g.mean())
        if prev is not None: diffs.append(np.abs(g - prev).mean())
        prev = g
    return (float(np.median(diffs)) if diffs else 0.0), (float(np.mean(lum)) if lum else 0.0)


def cut(url, dur, out_dir, key):
    """Up to PER_FILM pieces of CLIP_SEC seconds from spread-out points of a film, re-encoded small and silent."""
    if dur <= 0: dur = probe(url)[0]
    if dur < CLIP_SEC + 2: return []
    starts = [dur * f for f in (0.18, 0.42, 0.66, 0.84)][:PER_FILM + 1]
    kept = []
    for s in starts:
        name = hashlib.sha1(('%s@%.1f' % (key, s)).encode()).hexdigest()[:16] + '.mp4'; out = os.path.join(out_dir, name)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-user_agent', UA['User-Agent'], '-ss', '%.2f' % s, '-t', '%.1f' % CLIP_SEC, '-i', url, '-an',
                            '-vf', "scale=-2:'min(%d,ih)':flags=area,fps=30,format=yuv420p" % MAX_H, '-c:v', 'libx264', '-preset', 'medium', '-crf', '25', '-movflags', '+faststart', out],
                           capture_output=True, text=True, timeout=600)
        if r.returncode or not os.path.exists(out): print('    ffmpeg: %s' % (r.stderr or '').strip()[-200:]); continue
        m, lum = motion(out)
        if m < 1.2 or lum < 18 or lum > 240: os.remove(out); continue            # nothing moves, or it is black / blown out
        kept.append((name, s, m))
        if len(kept) >= PER_FILM: break
    return kept


def fetch(maximum):
    import random
    idx = index(); seen = set(idx.get('seen', [])); qs = json.load(open(QUERIES)); new = []
    work = os.path.join(DIR, 'new'); os.makedirs(work, exist_ok=True)
    order = [(theme, q) for theme, ql in qs.items() for q in ql]; random.Random(time.strftime('%Y%W')).shuffle(order)
    for theme, q in order:
        if len(new) >= maximum: break
        for src in BY_THEME.get(theme, ['commons']):
            try: found = list(SOURCES[src](q))
            except Exception as exc: print('  %s %r: %s' % (src, q, exc)); continue
            print('  %s %r: %d usable' % (src, q, len(found)))
            for key, title, url, dur, lic, page in found:
                if key in seen or len(new) >= maximum: continue
                seen.add(key)
                try: pieces = cut(url, dur, work, key)
                except Exception as exc: print('  cut failed %s: %s' % (key, exc)); continue
                for name, s, m in pieces:
                    e = dict(asset=name, theme=theme, query=q, source=src, key=key, title=title[:120], licence=lic, page=page, start=round(s, 1), motion=round(m, 2))
                    idx.setdefault('clips', []).append(e); new.append(e); print('+ %-8s %-22s %s' % (theme, q, title[:60]))
                time.sleep(1)
    idx['seen'] = sorted(seen)
    if new:
        subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode and \
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Footage library (public domain)', '--notes',
                            'Public-domain clips for glitch.archive. Sources and licences: studio/footage/index.json'], check=True)
        files = [os.path.join(work, e['asset']) for e in new]
        for k in range(0, len(files), 20): subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + files[k:k + 20], check=True)
    json.dump(idx, open(INDEX, 'w'), indent=1); print('%d new clips, %d in the library' % (len(new), len(idx.get('clips', []))))


def pull(themes=()):
    """Download the library's clips (all, or the given themes) that are not cached yet. Needs read access to the repo's releases."""
    os.makedirs(CACHE, exist_ok=True); want = [e for e in index().get('clips', []) if not themes or e['theme'] in themes]
    missing = [e for e in want if not os.path.exists(os.path.join(CACHE, e['asset']))]
    if not missing: return want
    rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
    ids = {a['name']: a['id'] for a in rel.get('assets', [])}
    for e in missing:
        if e['asset'] not in ids: continue
        with open(os.path.join(CACHE, e['asset']), 'wb') as fh:
            fh.write(subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream', 'repos/%s/releases/assets/%d' % (REPO, ids[e['asset']])], capture_output=True, check=True).stdout)
    return [e for e in want if os.path.exists(os.path.join(CACHE, e['asset']))]


def purge():
    """Remove from the library (index and release) every clip the block list now rules out, or found by a query no longer asked."""
    idx = index(); asked = {q for ql in json.load(open(QUERIES)).values() for q in ql}
    bad = [e for e in idx.get('clips', []) if BLOCK.search(e.get('title', '') + ' ' + e.get('query', '')) or e.get('query') not in asked]
    if not bad: print('nothing to remove'); return
    rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
    ids = {a['name']: a['id'] for a in rel.get('assets', [])}
    for e in bad:
        if e['asset'] in ids: subprocess.run(['gh', 'api', '-X', 'DELETE', 'repos/%s/releases/assets/%d' % (REPO, ids[e['asset']])], check=True)
        print('removed', e['title'])
    idx['clips'] = [e for e in idx['clips'] if e not in bad]; json.dump(idx, open(INDEX, 'w'), indent=1)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'purge': purge(); sys.exit()
    if cmd == 'fetch': fetch(int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 40)
    elif cmd == 'pull': print(len(pull(tuple(sys.argv[2:]))), 'clips cached')
    else: sys.exit(__doc__)
