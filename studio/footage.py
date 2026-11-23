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
                   r'commercial|advertis|\bad\b|\bads\b|\bspot\b|sponsor|brand|'
                   r'jew|cake.?walk|darkt?own|\bcoons?\b|mammy|pickaninny|sambo|uncle tom|harem|slave', re.I)   # old films' caricature


def _open(url, tries=4, raw=False):
    for k in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
            return r if raw else json.loads(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if k == tries - 1: raise
            time.sleep((5, 20, 60)[min(k, 2)])


class Later(Exception):
    """The source asked us to slow down: leave this film for the next run instead of marking it seen."""


def _safe(url):
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, urllib.parse.quote(u.path, safe='/%~:@!$&()*+,;='), u.query, u.fragment))


def download(url, path, max_mb=400, tries=5):
    """A whole file to disk, politely: Wikimedia's video servers refuse the many ranged requests ffmpeg makes
    (429 Too Many Requests), so their files are fetched once, waiting as long as they ask between tries."""
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(_safe(url), headers=UA), timeout=120) as r, open(path, 'wb') as fh:
                if int(r.headers.get('Content-Length') or 0) > max_mb << 20: raise ValueError('larger than %d MB' % max_mb)
                while True:
                    b = r.read(1 << 20)
                    if not b: return path
                    fh.write(b)
                    if fh.tell() > max_mb << 20: raise ValueError('larger than %d MB' % max_mb)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504): raise
            if k == tries - 1: raise Later('%s after %d tries' % (exc.code, tries))
            wait = exc.headers.get('Retry-After') if exc.headers else None
            time.sleep(min(300, int(wait)) if wait and wait.isdigit() else 30 * (k + 1))
        except (urllib.error.URLError, TimeoutError) as exc:
            if k == tries - 1: raise Later(str(exc))
            time.sleep(15 * (k + 1))


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
        got = _open(_safe(it['href'])) if it.get('href') else []
        assets = [a if isinstance(a, str) else a.get('href', '') for a in got]
        pick = next((a for a in assets if a.endswith('~mobile.mp4')), None) or next((a for a in assets if a.endswith('~orig.mp4')), None)
        if pick: yield 'nasa:' + nid, data.get('title', nid), _safe(pick.replace('http://', 'https://')), 0.0, 'Public Domain (NASA)', 'https://images.nasa.gov/details/' + nid


# Films published before 1931 are in the US public domain whatever their licence field says. A modern restoration's
# new colouring or reconstruction can carry its own copyright, so those versions are left alone.
NEWER = re.compile(r'restor|remaster|coloriz|colouris|colorised|coloured|4k|upscal|\bai\b|remix|trailer|documentary', re.I)


def silent(q, n=8):
    """Films and cartoons from before 1931 on the Internet Archive (vintage.media.archive)."""
    terms = ' AND '.join('(title:(%s) OR subject:(%s))' % (w, w) for w in q.split()[:2])
    p = {'q': 'mediatype:movies AND year:[1890 TO 1930] AND %s' % terms, 'fl[]': ['identifier', 'title', 'year', 'subject', 'description'],
         'rows': n, 'output': 'json', 'sort[]': 'downloads desc'}
    docs = (_open('https://archive.org/advancedsearch.php?' + urllib.parse.urlencode(p, doseq=True)).get('response') or {}).get('docs') or []
    for d in docs:
        blob = ' '.join(str(d.get(k) or '') for k in ('title', 'subject', 'description'))
        try: year = int(str(d.get('year') or '9999')[:4])
        except ValueError: continue
        if year > 1930 or BLOCK.search(blob) or NEWER.search(blob): continue
        md = _open('https://archive.org/metadata/%s' % d['identifier']); files = md.get('files') or []
        mp4 = [f for f in files if f.get('name', '').endswith('.mp4')]
        mp4.sort(key=lambda f: ('512kb' in f['name'], int(f.get('size') or 0)))
        if not mp4: continue
        f = mp4[0]; dur = float(f.get('length') or 0) if re.match(r'^[\d.]+$', str(f.get('length') or '')) else 0.0
        yield 'silent:' + d['identifier'], d.get('title', d['identifier']), 'https://archive.org/download/%s/%s' % (d['identifier'], urllib.parse.quote(f['name'])), dur, \
            'Public Domain (published %d)' % year, 'https://archive.org/details/' + d['identifier']


SOURCES = {'commons': commons, 'prelinger': prelinger, 'nasa': nasa, 'silent': silent}
BY_THEME = {'space': ['nasa', 'commons'], 'archive': ['prelinger'], 'city': ['commons', 'prelinger'], 'water': ['commons', 'prelinger'], 'nature': ['commons', 'nasa'],
            'silent': ['silent'], 'nyc': ['commons', 'prelinger', 'silent']}


# ---------------------------------------------------------------- cutting
def probe(url):
    net = ['-user_agent', UA['User-Agent']] if url.startswith('http') else []
    r = subprocess.run(['ffprobe', '-v', 'error'] + net + ['-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration', '-of', 'json', url],
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
    local = None
    if 'upload.wikimedia.org' in url:
        local = download(url, os.path.join(out_dir, '_film' + os.path.splitext(urllib.parse.urlsplit(url).path)[1][-5:]))
        url = local; time.sleep(3)
    try: return _cut(url, dur, out_dir, key)
    finally:
        if local and os.path.exists(local): os.remove(local)


def _cut(url, dur, out_dir, key):
    if dur <= 0: dur = probe(url)[0]
    if dur < CLIP_SEC + 2: return []
    starts = [dur * f for f in (0.18, 0.42, 0.66, 0.84)][:PER_FILM + 1]
    kept = []
    for s in starts:
        name = hashlib.sha1(('%s@%.1f' % (key, s)).encode()).hexdigest()[:16] + '.mp4'; out = os.path.join(out_dir, name)
        net = ['-user_agent', UA['User-Agent']] if url.startswith('http') else []
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y'] + net + ['-ss', '%.2f' % s, '-t', '%.1f' % CLIP_SEC, '-i', url, '-an',
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
    have = {}
    for e in idx.get('clips', []): have[e['theme']] = have.get(e['theme'], 0) + 1
    order.sort(key=lambda tq: min(have.get(tq[0], 0), 60))      # themes with the fewest clips (new ones) are fetched first
    for theme, q in order:
        if len(new) >= maximum: break
        for src in BY_THEME.get(theme, ['commons']):
            try: found = list(SOURCES[src](q))
            except Exception as exc: print('  %s %r: %s' % (src, q, exc)); continue
            print('  %s %r: %d usable' % (src, q, len(found)))
            for key, title, url, dur, lic, page in found:
                if key in seen or len(new) >= maximum: continue
                try: pieces = cut(url, dur, work, key)
                except Later as exc: print('  later %s: %s' % (key, exc)); continue
                except Exception as exc: print('  cut failed %s: %s' % (key, exc)); pieces = []
                seen.add(key)
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
    bad = [e for e in idx.get('clips', []) if e.get('source') != 'own' and (BLOCK.search(e.get('title', '') + ' ' + e.get('query', '')) or e.get('query') not in asked)]
    if not bad: print('nothing to remove'); return
    rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
    ids = {a['name']: a['id'] for a in rel.get('assets', [])}
    for e in bad:
        if e['asset'] in ids: subprocess.run(['gh', 'api', '-X', 'DELETE', 'repos/%s/releases/assets/%d' % (REPO, ids[e['asset']])], check=True)
        print('removed', e['title'])
    idx['clips'] = [e for e in idx['clips'] if e not in bad]; json.dump(idx, open(INDEX, 'w'), indent=1)


# ---------------------------------------------------------------- our own footage
DRIVE = re.compile(r'(?:/d/|id=|^)([A-Za-z0-9_-]{25,})')


def own(theme, items, licence='Own footage'):
    """Add our own clips (Google Drive links shared as "anyone with the link", or local files) to the library under
    `theme`. Unlike the archive films every clip is kept whole: up to 8 pieces of CLIP_SEC seconds from end to end,
    or the clip as it is when it is shorter than that. Already-added links are skipped."""
    idx = index(); seen = set(idx.get('seen', [])); new = []
    work = os.path.join(DIR, 'new'); os.makedirs(work, exist_ok=True)
    for item in items:
        item = item.strip()
        if not item or item.startswith('#'): continue
        m = DRIVE.search(item) if not os.path.exists(item) else None
        key = 'own:' + (m.group(1) if m else hashlib.sha1(open(item, 'rb').read()).hexdigest()[:16])
        if key in seen: continue
        src = item
        if m:
            src = os.path.join(work, '_own_' + m.group(1))
            r = subprocess.run(['curl', '-sSL', '-o', src, 'https://drive.usercontent.google.com/download?id=%s&export=download&confirm=t' % m.group(1)])
            if r.returncode or not os.path.exists(src) or os.path.getsize(src) < 50000: print('  could not download %s (is it shared as "anyone with the link"?)' % item); continue
        dur = probe(src)[0]
        starts = [0.0] if dur < CLIP_SEC + 2 else [k * CLIP_SEC for k in range(int((dur - 1) // CLIP_SEC))][:8]
        for s0 in starts:
            name = hashlib.sha1(('%s@%.1f' % (key, s0)).encode()).hexdigest()[:16] + '.mp4'; out = os.path.join(work, name)
            r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', '%.2f' % s0, '-t', '%.1f' % min(CLIP_SEC, max(1.0, dur - s0)), '-i', src, '-an',
                                '-vf', "scale=-2:'min(%d,ih)':flags=area,fps=30,format=yuv420p" % MAX_H, '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                                '-movflags', '+faststart', out], capture_output=True, text=True, timeout=600)
            if r.returncode or not os.path.exists(out): continue
            mo, lum = motion(out)
            if lum < 12: os.remove(out); continue                                  # black
            e = dict(asset=name, theme=theme, query='own', source='own', key=key, title=os.path.basename(item)[:120], licence=licence, page='',
                     start=round(s0, 1), motion=round(mo, 2))
            idx.setdefault('clips', []).append(e); new.append(e); print('+ %-6s %s @%.0fs' % (theme, item[:60], s0))
        seen.add(key)
        if m and os.path.exists(src): os.remove(src)
    idx['seen'] = sorted(seen)
    if new:
        subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode and \
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Footage library (public domain)', '--notes',
                            'Public-domain clips for glitch.archive. Sources and licences: studio/footage/index.json'], check=True)
        files = [os.path.join(work, e['asset']) for e in new]
        for k in range(0, len(files), 20): subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + files[k:k + 20], check=True)
    json.dump(idx, open(INDEX, 'w'), indent=1); print('%d new clips of our own' % len(new))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'purge': purge(); sys.exit()
    if cmd == 'fetch': fetch(int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 40)
    elif cmd == 'pull': print(len(pull(tuple(sys.argv[2:]))), 'clips cached')
    elif cmd == 'own':                     # footage.py own THEME FILE_OF_LINKS  (or links / paths after THEME)
        rest = sys.argv[3:]
        items = open(rest[0]).read().split() if len(rest) == 1 and rest[0].endswith('.txt') else rest
        own(sys.argv[2], items)
    else: sys.exit(__doc__)
