"""Public-domain footage for glitch.archive: creeks, forests, cities, space, old film.

    python studio/footage.py fetch [--max N]     (GitHub Actions: find, cut and upload new clips)
    python studio/footage.py pull [THEME ...]    (download the library's clips into studio/footage/cache)

Only footage anyone may reuse with no credit is taken: Wikimedia Commons files marked public domain or CC0, the
Prelinger Archives films on archive.org marked public domain, films published before 1931 (US public domain by
date) from the Internet Archive and the Library of Congress, and NASA video and NASA Scientific Visualization
Studio animations (not copyrighted, by US law); and, for New York as it looks today (theme nyc_now, NOW), Pexels
videos under the Pexels licence (free to use and adapt, no credit; places only, stored in our own crop and grade).
Every clip's source page, licence and title (and for old films
the year) are kept in the index. From
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
UA = {'User-Agent': 'CloseQuartersFootage/1.0 (https://closequarters.vip; contact via the site) python-urllib/3'}
NO_CREDIT = re.compile(r'^(public domain|pd\b|pd-|cc0)', re.I)
CLIP_SEC, PER_FILM, MAX_H = 10.0, 3, 960
MIN_H = 360          # a piece from a copy less tall than this (the 320x240 dupes of old films) looks smeared on a phone: not kept
PER_QUERY = 1        # films a query may give before every other query has had its turn (so one popular query cannot use up --max)
# Old ephemeral films include burlesque reels, tobacco and alcohol ads, war footage and racist caricature. None of
# that is taken: a title, subject or description with any of these words rules the whole film out.
BLOCK = re.compile(r'strip|burlesque|nud|naked|sex|venereal|cigar|tobacco|smok|beer|whisk|liquor|alcohol|drunk|'
                   r'war\b|wartime|combat|battle|army|navy|bomb|atomic|nuclear|weapon|gun|rifle|kill|death|dead|corpse|'
                   r'propaganda|nazi|hitler|racis|minstrel|blackface|savage|native|indian|negro|oriental|chinese|japanese|jap\b|'
                   r'crime|police|prison|drug|narcot|marijuana|reefer|venus|hygiene|birth|disease|surgery|hospital|accident|crash|riot|'
                   r'commercial|advertis|\bad\b|\bads\b|\bspot\b|sponsor|brand|'
                   r'jew|cake.?walk|darkt?own|\bcoons?\b|mammy|pickaninny|sambo|uncle tom|harem|slave|'   # old films' caricature
                   r'schleiertanz|veil.?dance|florida enchantment', re.I)   # dancers in body stockings that read as nude on a phone
# Ordinary words that contain a blocked stem ("skill" holds kill, "Essex" sex, "patriotic" riot, "smokestack" smok):
# they are blanked out before BLOCK looks, so a film about a factory chimney or Indiana is not thrown away for them.
SAFE = re.compile(r'skill|begun|burgundy|essex|sussex|middlesex|jewel|patriot|chariot|marriott|alternative|indiana|'
                  r'birthday|birthplace|deadline|hospitality|\bsmoke(stacks?|s)?\b|brand.?new|nudge|drugstore|navy blue|bombay|'
                  r'postwar|prewar|post-war|pre-war', re.I)          # smoke from a chimney or a train stays; smoking does not
# The parts of BLOCK that rule a film out even when only its long description says so. A silent comedy's description
# that mentions a policeman or a fight is fine (Keystone chases, Keaton's Cops); caricature, nudity and sex never are.
HARD = re.compile(r'strip|burlesque|nud|naked|sex|venereal|nazi|hitler|racis|minstrel|blackface|savage|negro|pickaninny|sambo|'
                  r'mammy|darkt?own|\bcoons?\b|cake.?walk|uncle tom|harem|slave|lynch|\bjew|oriental|chinese|japanese|jap\b|chinaman|'
                  r'indian|native|schleiertanz|veil.?dance|florida enchantment', re.I)   # A Florida Enchantment (1914) has blackface scenes


# Cartoons from before 1931 are public domain, but some of their characters are still live trademarks that their
# owners defend (Disney's, Felix, Betty Boop, Popeye). The 'toons' theme leaves every film with one of them alone.
# Steamboat Willie (1928) is PD and its title has no "Mickey" in it, but Mickey is the trademark Disney defends hardest
# and the film is rights-matched on every platform; Barnacle Bill (1930) has the proto-Betty Boop in it, and Fleischer
# Studios disputes that Betty is PD at all. Both named here, by title, so no caller has to know.
TRADEMARK = re.compile(r'mickey|minnie|disney|oswald|felix|betty.?boop|popeye|silly.?symphon|pluto|goofy|donald|woody|bugs bunny|looney|merrie|'
                       r'steamboat.?willie|barnacle.?bill', re.I)


def blocked(text, rule=None):
    """Whether the text holds a word the library never takes (rule: BLOCK, or HARD for a description)."""
    return bool((rule or BLOCK).search(SAFE.sub(' ', text or '')))


def _read_json(path):
    with open(path) as f: return json.load(f)


def _save_index(idx):
    with open(INDEX, 'w') as f: json.dump(idx, f, indent=1)


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
    try: return _read_json(INDEX)
    except (OSError, ValueError): return {'clips': [], 'seen': []}


def _clean(html): return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html or '')).strip()


# ---------------------------------------------------------------- sources: each yields (key, title, url of a playable file, duration, licence, page)
# A query in queries.json goes to every source its theme lists in BY_THEME, unless it starts with a source's name and
# ">" ("loc>Edison", "commons>incategory:Videos_of_films_from_1923"), when it goes to that source alone.
# fetch() fills SEEN before asking, so a source can skip a film it already has before spending a request on it.
SEEN = set()


def _yr(v):
    m = re.search(r'\b(18[89]\d|19\d\d|20\d\d)\b', str(v or ''))
    return int(m.group(1)) if m else None


def _secs(v):
    """A file's length as the Internet Archive writes it: '66.87' or '01:06:12'."""
    v = str(v or '')
    if re.match(r'^[\d.]+$', v): return float(v)
    if re.match(r'^\d+(:\d+){1,2}(\.\d+)?$', v): return float(sum(float(x) * 60 ** k for k, x in enumerate(reversed(v.split(':')))))
    return 0.0


def _ia_terms(q):
    """Plain words must all be found, in any field (title, subject, creator, description), in any order; a query
    holding ':' is Internet Archive search syntax and is kept as it is."""
    if ':' in q: return q
    words = [w for w in q.split() if w.lower() not in STOP] or q.split()
    return ' AND '.join(w if re.match(r'^\w+$', w) else '"%s"' % w.replace('"', '') for w in words)


STOP = {'the', 'a', 'an', 'of', 'and', 'with', 'in', 'on', 'de', 'la', 'le', 'les', 'que', 'der', 'die', 'das'}


def _ia_search(q, rows):
    p = {'q': q, 'fl[]': ['identifier', 'title', 'year', 'date', 'subject', 'description', 'licenseurl'], 'rows': rows, 'output': 'json', 'sort[]': 'downloads desc'}
    return (_open('https://archive.org/advancedsearch.php?' + urllib.parse.urlencode(p, doseq=True)).get('response') or {}).get('docs') or []


def _ia_file(ident):
    """The best video file of an item: an h.264 copy between MIN_H and 1080 lines tall, the tallest; failing that the
    largest mp4 that is not the 512kb or iPod copy; failing that whatever mp4 there is."""
    files = _open('https://archive.org/metadata/%s' % ident).get('files') or []
    mp4 = [f for f in files if f.get('name', '').lower().endswith(('.mp4', '.m4v'))]
    if not mp4: return None, 0.0
    h = lambda f: int(float(f.get('height') or 0))
    tall = [f for f in mp4 if MIN_H <= h(f) <= 1080]
    small = lambda f: bool(re.search(r'512kb|ipod|_small|\.ia\.mp4$', f['name'], re.I))
    f = max(tall, key=h) if tall else max(mp4, key=lambda f: (not small(f), int(f.get('size') or 0)))
    return 'https://archive.org/download/%s/%s' % (ident, urllib.parse.quote(f['name'])), _secs(f.get('length'))


def _doc_text(d, *keys):
    return ' '.join(' '.join(map(str, v)) if isinstance(v, list) else str(v or '') for v in (d.get(k) for k in keys))


def commons(q, n=30):
    p = dict(action='query', format='json', generator='search', gsrsearch='%s filetype:video' % q, gsrnamespace=6, gsrlimit=n,
             prop='videoinfo', viprop='url|size|mime|extmetadata|derivatives')
    pages = (_open('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(p)).get('query') or {}).get('pages') or {}
    for pg in pages.values():
        if 'commons:' + pg['title'] in SEEN: continue
        vi = (pg.get('videoinfo') or [{}])[0]; meta = vi.get('extmetadata') or {}
        lic = _clean((meta.get('LicenseShortName') or {}).get('value'))
        desc = _clean((meta.get('ImageDescription') or {}).get('value')) + ' ' + _clean((meta.get('Categories') or {}).get('value'))
        if not NO_CREDIT.match(lic) or blocked(pg['title'] + ' ' + desc): continue
        ders = [d for d in vi.get('derivatives') or [] if d.get('type', '').startswith('video/')]
        ders.sort(key=lambda d: abs((d.get('height') or 0) - 720))
        src = ders[0]['src'] if ders else vi.get('url')
        if src: yield 'commons:' + pg['title'], pg['title'][5:], src, float(vi.get('duration') or 0), lic, vi.get('descriptionurl', '')


def prelinger(q, n=6):
    """Prelinger Archives films marked public domain. The licence is asked for in the search itself and the words are
    searched in every field (the films' titles rarely say "skyline" or "subway"; their shot lists do), so a query
    is not spent on films that would be thrown away."""
    docs = _ia_search('collection:prelinger AND mediatype:movies AND licenseurl:*publicdomain* AND (%s)' % _ia_terms(q), 60)
    got = 0
    for d in docs:
        key = 'prelinger:' + d['identifier']
        if got >= n: return
        if key in SEEN or 'publicdomain' not in (d.get('licenseurl') or '') or blocked(_doc_text(d, 'title', 'subject', 'description')): continue
        url, dur = _ia_file(d['identifier'])
        if not url: continue
        got += 1
        yield key, d.get('title', d['identifier']), url, dur, 'Public Domain (Prelinger Archives)', 'https://archive.org/details/' + d['identifier']


TALK = re.compile(r'briefing|press conference|news conference|interview|remarks|panel|lecture|award|ceremony|testimony|'
                  r'town hall|q ?& ?a|podcast|webinar|speech|talks? (about|with)|explains|message from|tour of', re.I)


def nasa(q, n=12):
    """NASA's Image and Video Library (not copyrighted, by US law). Talking heads (briefings, interviews) are skipped:
    nothing in them moves the way a video needs."""
    items = ((_open('https://images-api.nasa.gov/search?' + urllib.parse.urlencode(dict(q=q, media_type='video'))).get('collection') or {}).get('items') or [])
    got = 0
    for it in items:
        if got >= n: return
        data = (it.get('data') or [{}])[0]; nid = data.get('nasa_id')
        text = '%s %s %s' % (data.get('title', ''), data.get('description', ''), ' '.join(data.get('keywords') or []))
        if not nid or 'nasa:' + nid in SEEN or blocked(text) or TALK.search(data.get('title', '')): continue
        got_ = _open(_safe(it['href'])) if it.get('href') else []
        assets = [a if isinstance(a, str) else a.get('href', '') for a in got_]
        pick = next((a for suf in ('~large.mp4', '~medium.mp4', '~orig.mp4', '~mobile.mp4') for a in assets if a.endswith(suf)), None)
        if pick:
            got += 1
            yield 'nasa:' + nid, data.get('title', nid), _safe(pick.replace('http://', 'https://')), 0.0, 'Public Domain (NASA)', 'https://images.nasa.gov/details/' + nid


# Films published before 1931 are in the US public domain whatever their licence field says. A modern restoration's
# new colouring or reconstruction can carry its own copyright, so those versions are left alone.
NEWER = re.compile(r'restor|remaster|coloriz|colouris|colorised|coloured|4k|upscal|\bai\b|remix|trailer|documentary', re.I)


def silent(q, n=6):
    """Films and cartoons from before 1931 on the Internet Archive (vintage.media.archive). The title and subjects
    must pass the whole block list; the long description only its hard part (caricature, nudity), so a comedy whose
    summary mentions a policeman is not lost. Up to 60 hits are looked at, films already in the library skipped
    before any further request."""
    docs = _ia_search('mediatype:movies AND year:[1890 TO 1930] AND (%s)' % _ia_terms(q), 60)
    got = 0
    for d in docs:
        key = 'silent:' + d['identifier']
        if got >= n: return
        year = _yr(d.get('year')) or _yr(d.get('date'))
        head, desc = _doc_text(d, 'title', 'subject'), _doc_text(d, 'description')
        if key in SEEN or not year or year > 1930 or blocked(head) or blocked(desc, HARD) or NEWER.search(head + ' ' + desc): continue
        url, dur = _ia_file(d['identifier'])
        if not url: continue
        got += 1
        yield key, d.get('title', d['identifier']), url, dur, 'Public Domain (published %d)' % year, 'https://archive.org/details/' + d['identifier']


def loc(q, n=6):
    """The Library of Congress's films from before 1931 (the National Screening Room: Edison, Biograph, the Paper
    Print collection, early actualities of New York), scanned at 1080p, far sharper than most archive.org copies.
    Pre-1931, so US public domain; the Library itself says it knows of no restrictions on the vast majority. Its API
    allows 20 requests a minute (more blocks the address for an hour), so every request waits 3.5 s."""
    base = 'https://www.loc.gov/film-and-videos/?'
    try: res = _open(base + urllib.parse.urlencode(dict(q=q, dates='1890/1930', fo='json', c=60, at='results')), tries=2).get('results') or []
    except urllib.error.HTTPError as exc:                   # the date range is only a pre-filter: the year is checked below either way
        if exc.code == 429: raise
        time.sleep(3.5); res = _open(base + urllib.parse.urlencode(dict(q=q, fo='json', c=60, at='results')), tries=2).get('results') or []
    time.sleep(3.5)
    got = 0
    for r in res:
        if got >= n: return
        rid = (r.get('id') or r.get('url') or '').rstrip('/').split('/')[-1]; key = 'loc:' + rid
        year = _yr(r.get('date'))
        head, desc = _doc_text(r, 'title', 'subject'), _doc_text(r, 'description')
        vids = [x.get('video') for x in r.get('resources') or [] if (x.get('video') or '').endswith('.mp4')]
        if not rid or key in SEEN or not vids or not year or year > 1930: continue
        if blocked(head) or blocked(desc, HARD) or NEWER.search(head): continue
        if re.search(r'permission|educational use only', _doc_text(r, 'rights', 'rights_advisory'), re.I): continue
        got += 1
        page = r.get('url') or r.get('id'); page = 'https:' + page if page.startswith('//') else page.replace('http://', 'https://')
        yield key, r.get('title', rid), vids[0].replace('http://', 'https://'), float((r.get('resources') or [{}])[0].get('duration') or 0), \
            'Public Domain (published %d; Library of Congress)' % year, page


LABELS = re.compile(r'label|title|caption|colou?r.?bar|legend|text|print|_web|preview|thumb|frames?/', re.I)


def svs(q, n=5):
    """NASA's Scientific Visualization Studio: data made into pictures (Earth from orbit, ocean currents, storms,
    the Sun, the Moon), mostly 1080p or 4K. Public domain unless a page says otherwise; some come with licensed
    music, and our pieces never keep the sound. Only the SVS studio's own visualisations are asked for (Goddard's
    produced videos carry presenters and logos), and versions without labels or colour bars are preferred."""
    res = _open('https://svs.gsfc.nasa.gov/api/search/?' + urllib.parse.urlencode(dict(search=q, studio='SVS', limit=40))).get('results') or []
    got = 0
    for r in res:
        if got >= n: return
        key = 'svs:%s' % r.get('id')
        if not r.get('id') or key in SEEN or blocked('%s %s' % (r.get('title', ''), r.get('description', ''))): continue
        page = _open('https://svs.gsfc.nasa.gov/api/%s/' % r['id']); time.sleep(1)
        if re.search(r'©|copyright', _clean(page.get('description')), re.I): continue
        movies = [it.get('instance') or {} for g in page.get('media_groups') or [] for it in g.get('items') or []]
        movies = [m for m in movies if (m.get('filename') or '').lower().endswith('.mp4') and (m.get('height') or 0) >= 720]
        if not movies: continue
        best = min(movies, key=lambda m: (bool(LABELS.search(m.get('filename', ''))), abs((m.get('height') or 0) - 1080)))
        got += 1
        yield key, page.get('title') or r.get('title', key), best['url'].replace('http://', 'https://'), 0.0, 'Public Domain (NASA SVS)', 'https://svs.gsfc.nasa.gov/%s/' % r['id']


def pexels(q, n=40):
    """Pexels videos (the Pexels licence: free to use and adapt, commercially too, no credit needed), upright ones
    first since that is the shape we post. Needs a free API key in PEXELS_API_KEY; without one it finds nothing.
    Clips whose title is about a person (a portrait, a model, someone walking) are left out: places only."""
    key = os.environ.get('PEXELS_API_KEY')
    if not key: print('  pexels: no PEXELS_API_KEY, skipped'); return
    for orient in ('portrait', 'landscape'):
        url = 'https://api.pexels.com/videos/search?' + urllib.parse.urlencode(dict(query=q, per_page=n, orientation=orient, size='medium'))
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=dict(UA, Authorization=key)), timeout=60).read())
        for v in r.get('videos') or []:
            slug = urllib.parse.urlsplit(v.get('url') or '').path.strip('/').split('/')[-1]; title = re.sub(r'-?\d+$', '', slug).replace('-', ' ').strip()
            if blocked(title) or PEOPLE.search(title) or LOGO.search(title): continue
            files = [f for f in v.get('video_files') or [] if f.get('file_type') == 'video/mp4' and f.get('height') and f.get('link')]
            if not files: continue
            f = min(files, key=lambda f: abs(max(f['height'], f.get('width') or 0) - 1280))
            yield 'pexels:%s' % v['id'], title or slug, f['link'], float(v.get('duration') or 0), 'Pexels License', v.get('url', '')


PEOPLE = re.compile(r'\b(man|woman|men|women|girl|boy|person|people|model|couple|portrait|selfie|kid|child|baby|dancing|posing|smiling|walking|tourists?)\b', re.I)
LOGO = re.compile(r'i heart|i love ny|\blogo|billboard|times square ad', re.I)      # the I-heart-NY mark is a trademark; ad screens are other people's brands
NOW = {'nyc_now'}        # themes of a place as it looks today: upright 720x1280 pieces in our own grade, short clips kept whole
SOURCES = {'commons': commons, 'prelinger': prelinger, 'nasa': nasa, 'silent': silent, 'loc': loc, 'svs': svs, 'pexels': pexels}
BY_THEME = {'space': ['nasa', 'svs', 'commons'], 'archive': ['prelinger'], 'city': ['commons', 'prelinger'], 'water': ['commons', 'prelinger'], 'nature': ['commons', 'nasa'],
            'silent': ['silent', 'loc'], 'toons': ['silent'], 'nyc': ['commons', 'prelinger', 'silent', 'loc'],
            'nyc_now': ['pexels']}       # Commons' no-credit files of today's New York are news clips (a 2026 protest, a street fair), not places
# A clip of theme nyc must name a New York place in its title, and must not be news: "New York" queries on Commons
# also return a Florida rail opening, steam engines, Russian films of 1909-1913 and a 2026 political protest.
NYC_WORDS = re.compile(r'new york|n\.y\.|\bnyc\b|manhattan|brooklyn|bronx|queens|staten island|harlem|bowery|broadway|fifth avenue|wall street|'
                       r'times square|herald square|union square|madison square|bryant park|central park|coney island|grand central|'
                       r'flatiron|empire state|chrysler|hudson|east river|battery|ellis island|statue of liberty|elevated|manhatta\b|speedy', re.I)
NYC_NOT = re.compile(r'protest|rally|demonstrat|march\b|riot|visit|parade|fair\b|interview|documents|immigra|election|campaign|'
                     r'football|baseball|nfl|nba|concert|festival|sunrail|locomotive', re.I)


# A toons clip must be one cartoon from 1930 or before: compilations and "collections" run past 1930 (Krazy Kat
# 1929-1938) or gather later, still-copyrighted films; remixes and memes ("Sigmaboat willy") are someone's new work;
# subtitled copies carry a modern translation; instructional films are not cartoons.
TOON_NOT = re.compile(r'collection|compil|\b(19[0-9]{2})\s*[-–]\s*(19[0-9]{2})\b|\b\d+\s+\S*.?themed|golden.?age|sigma|meme|\bedit\b|remix|'
                      r'subtit|how to use|dial phone|best of|top \d+|\d{2,} cartoons', re.I)


def fits(e):
    """Whether an index entry belongs in its theme (nyc: a New York place, not news; toons: one cartoon from 1930 or
    before, nobody's live trademark, no compilation or remix). Our own clips always do."""
    if e.get('source') == 'own': return True
    if e.get('theme') == 'toons':
        if (e.get('year') or 0) > 1930: return False                   # indexed with a year past the PD line (Aristocr1940 said 1930)
        t = '%s %s' % (e.get('title', ''), e.get('key', ''))
        return not TRADEMARK.search(t) and not TOON_NOT.search(t)
    if e.get('theme') != 'nyc': return True
    t = e.get('title', '')
    return bool(NYC_WORDS.search(t)) and not NYC_NOT.search(t)


def sources_for(theme, q):
    """[(source, the query it is asked)]: 'loc>Edison' goes to loc alone; a plain query to every source of its theme."""
    src, sep, rest = q.partition('>')
    if sep and src in SOURCES: return [(src, rest.strip())]
    return [(s, q) for s in BY_THEME.get(theme, ['commons'])]

# ---------------------------------------------------------------- cutting
def probe(url):
    net = ['-user_agent', UA['User-Agent']] if url.startswith('http') else []
    r = subprocess.run(['ffprobe', '-v', 'error'] + net + ['-select_streams', 'v:0', '-show_entries', 'stream=width,height:format=duration', '-of', 'json', url],
                       capture_output=True, text=True, timeout=120)
    j = json.loads(r.stdout or '{}'); s = (j.get('streams') or [{}])[0]
    return float((j.get('format') or {}).get('duration') or 0), int(s.get('width') or 0), int(s.get('height') or 0)


def looks(path):
    """(how much moves, mean brightness, height in pixels, share of frames that are a title card) for a clip.
    A card is a frame that is mostly near-black and does not move: an intertitle (light letters on black), black
    leader between reels, or a fade. A piece that is more than a third cards is not worth keeping."""
    import numpy as np, cv2
    cap = cv2.VideoCapture(path); prev = None; diffs, lum, cards, h = [], [], 0, 0
    while True:
        ok, f = cap.read()
        if not ok: break
        h = f.shape[0]
        g = cv2.cvtColor(cv2.resize(f, (160, 160 * f.shape[0] // f.shape[1])), cv2.COLOR_BGR2GRAY).astype(np.float32)
        lum.append(g.mean()); d = np.abs(g - prev).mean() if prev is not None else None
        if d is not None: diffs.append(d)
        if (g < 45).mean() > 0.72 and (d is None or d < 1.0): cards += 1
        prev = g
    n = max(1, len(lum))
    return (float(np.median(diffs)) if diffs else 0.0), (float(np.mean(lum)) if lum else 0.0), h, cards / n


def motion(path):
    """How much moves in a clip, and how bright it is: still, black or blank pieces are not worth keeping."""
    return looks(path)[:2]


def cut(url, dur, out_dir, key, now=False):
    """Up to PER_FILM pieces of CLIP_SEC seconds from spread-out points of a film, re-encoded small and silent.
    now: a piece for a NOW theme, cropped upright to 720x1280 and put through our film grade (so what the library
    holds is our version of the clip, not a copy of the stock file), and a clip of 5-12 s is kept whole."""
    local = None
    if 'upload.wikimedia.org' in url:
        local = download(url, os.path.join(out_dir, '_film' + os.path.splitext(urllib.parse.urlsplit(url).path)[1][-5:]))
        url = local; time.sleep(3)
    try: return _cut(url, dur, out_dir, key, now)
    finally:
        if local and os.path.exists(local): os.remove(local)


def bars(url, at, size):
    """The crop that takes off a copy's black bars (a 4:3 film pillarboxed in a 16:9 scan, a letterboxed transfer), as
    an ffmpeg filter, or '' when there are none worth taking off. Looked for over 4 s of the film at `at`."""
    W, H = size
    if not W or not H: return ''
    net = ['-user_agent', UA['User-Agent']] if url.startswith('http') else []
    try:
        r = subprocess.run(['ffmpeg', '-hide_banner'] + net + ['-ss', '%.2f' % at, '-t', '4', '-i', url, '-an', '-vf', 'cropdetect=limit=24:round=2:reset=0', '-f', 'null', '-'],
                           capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired: return ''
    got = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', r.stderr or '')
    if not got: return ''
    w, h, x, y = map(int, got[-1])
    if w < W * 0.4 or h < H * 0.4 or (w > W * 0.96 and h > H * 0.96): return ''     # nothing to take off, or a dark shot fooled it
    return 'crop=%d:%d:%d:%d,' % (w, h, x, y)


GRADE = ("scale=720:1280:force_original_aspect_ratio=increase:flags=area,crop=720:1280,fps=30,"
         "curves=r='0/0.03 0.5/0.52 1/1':g='0/0.04 0.5/0.5 1/0.97':b='0/0.07 0.5/0.48 1/0.92',eq=saturation=0.88:contrast=1.04,format=yuv420p")


def _cut(url, dur, out_dir, key, now=False):
    d0, W, H = probe(url)
    if dur <= 0: dur = d0
    if dur < (5 if now else CLIP_SEC + 2): return []
    starts = [0.0] if dur < CLIP_SEC + 2 else [dur * f for f in ((0.05, 0.5) if now and dur < 3 * CLIP_SEC else (0.18, 0.42, 0.66, 0.84))][:PER_FILM + 1]
    crop = '' if now else bars(url, starts[0], (W, H))
    kept = []
    for s in starts:
        name = hashlib.sha1(('%s@%.1f' % (key, s)).encode()).hexdigest()[:16] + '.mp4'; out = os.path.join(out_dir, name)
        net = ['-user_agent', UA['User-Agent']] if url.startswith('http') else []
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y'] + net + ['-ss', '%.2f' % s, '-t', '%.1f' % CLIP_SEC, '-i', url, '-an',
                            '-vf', GRADE if now else crop + "scale=-2:'min(%d,ih)':flags=area,fps=30,format=yuv420p" % MAX_H, '-c:v', 'libx264', '-preset', 'medium', '-crf', '25', '-movflags', '+faststart', out],
                           capture_output=True, text=True, timeout=600)
        if r.returncode or not os.path.exists(out): print('    ffmpeg: %s' % (r.stderr or '').strip()[-200:]); continue
        m, lum, h, card = looks(out)
        if h and h < MIN_H: os.remove(out); return kept                            # the whole copy is too small: no piece of it will do
        if m < (0.5 if now else 1.2) or lum < (10 if now else 18) or lum > 240 or card > (1.0 if now else 0.34):   # a city at night is dark and slow: allowed
            os.remove(out); continue                                                 # nothing moves, black / blown out, or mostly intertitles
        kept.append((name, s, m))
        if len(kept) >= PER_FILM: break
    return kept


def fetch(maximum):
    """Find, cut and upload up to `maximum` new pieces. Every query is asked in turn and may give PER_QUERY films
    before the next is asked; only when all have had a turn do they give more. (Before, a popular query such as
    "Melies" could fill the whole run, and Keaton, Chaplin and Lloyd were never reached.)"""
    import random
    idx = index(); seen = set(idx.get('seen', [])); SEEN.clear(); SEEN.update(seen); qs = _read_json(QUERIES); new = []
    work = os.path.join(DIR, 'new'); os.makedirs(work, exist_ok=True)
    order = [(theme, q) for theme, ql in qs.items() for q in ql]; random.Random(time.strftime('%Y%W')).shuffle(order)
    have = {}
    for e in idx.get('clips', []): have[e['theme']] = have.get(e['theme'], 0) + 1
    order.sort(key=lambda tq: min(have.get(tq[0], 0), 60))      # themes with the fewest clips (new ones) are fetched first
    jobs = [(theme, q, src, sq) for theme, q in order for src, sq in sources_for(theme, q) if src in SOURCES]
    found = {}                                                  # job -> its source's iterator, asked lazily
    for turn in (PER_QUERY, 10 ** 6):
        for job in jobs:
            theme, q, src, sq = job
            if len(new) >= maximum: break
            if job not in found:
                found[job] = SOURCES[src](sq); print('  %s %r' % (src, sq))
            took = 0
            while took < turn and len(new) < maximum and found[job] is not None:
                try: key, title, url, dur, lic, page = next(found[job])
                except StopIteration: found[job] = None; break
                except Exception as exc: print('  %s %r: %s' % (src, sq, exc)); found[job] = None; break
                if key in seen: continue
                took += 1
                if theme == 'nyc' and not fits(dict(theme=theme, title=title)): seen.add(key); SEEN.add(key); continue   # not New York, or news
                if theme == 'toons' and not fits(dict(theme=theme, title=title, key=key)): continue                       # a live character, a compilation, a remix
                try: pieces = cut(url, dur, work, key, **({'now': True} if theme in NOW else {}))
                except Later as exc: print('  later %s: %s' % (key, exc)); continue
                except Exception as exc: print('  cut failed %s: %s' % (key, exc)); pieces = []
                seen.add(key); SEEN.add(key)
                if not pieces: print('  - %-8s %-22s %s (nothing usable)' % (theme, sq[:22], title[:50]))
                for name, s, m in pieces:
                    e = dict(asset=name, theme=theme, query=q, source=src, key=key, title=title[:120], licence=lic, page=page, start=round(s, 1),
                             motion=round(m, 2), year=_yr(lic) if 'published' in lic else (_yr(sq) if 'films_from_' in sq else None))
                    if e['year'] is None: del e['year']
                    idx.setdefault('clips', []).append(e); new.append(e); print('+ %-8s %-22s %s' % (theme, sq[:22], title[:60]))
                time.sleep(1)
    idx['seen'] = sorted(seen)
    if new:
        subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode and \
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Footage library (public domain)', '--notes',
                            'Public-domain clips for glitch.archive. Sources and licences: studio/footage/index.json'], check=True)
        files = [os.path.join(work, e['asset']) for e in new]
        for k in range(0, len(files), 20): subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + files[k:k + 20], check=True)
    _save_index(idx)
    per = {}
    for e in new: per[e['theme']] = per.get(e['theme'], 0) + 1
    print('%d new clips (%s), %d in the library' % (len(new), ', '.join('%s %d' % kv for kv in sorted(per.items())) or '-', len(idx.get('clips', []))))


def pull(themes=(), assets=()):
    """Download the library's clips (all, the given themes, or just the given assets) that are not cached yet. Needs read access to the repo's releases."""
    os.makedirs(CACHE, exist_ok=True)
    want = [e for e in index().get('clips', []) if (not themes or e['theme'] in themes) and (not assets or e['asset'] in assets) and fits(e)]
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
    """Remove from the library (index and release) every clip the block list now rules out, found by a query no
    longer asked, or that does not belong in its theme (fits: an nyc clip that is not New York, or is news)."""
    idx = index(); asked = {q for ql in _read_json(QUERIES).values() for q in ql}
    bad = [e for e in idx.get('clips', []) if e.get('source') != 'own' and (blocked(e.get('title', '') + ' ' + e.get('query', '')) or e.get('query') not in asked or not fits(e))]
    if not bad: print('nothing to remove'); return
    rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
    ids = {a['name']: a['id'] for a in rel.get('assets', [])}
    for e in bad:
        if e['asset'] in ids: subprocess.run(['gh', 'api', '-X', 'DELETE', 'repos/%s/releases/assets/%d' % (REPO, ids[e['asset']])], check=True)
        print('removed', e['title'])
    idx['clips'] = [e for e in idx['clips'] if e not in bad]; _save_index(idx)


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
    _save_index(idx); print('%d new clips of our own' % len(new))


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
