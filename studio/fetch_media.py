#!/usr/bin/env python3
"""Fetch free-to-use pictures and video for each lyric line.
Only public-domain / CC0 results are kept (no attribution required); every file is logged in credits.json anyway.
Sources: Openverse (images, license=cc0,pdm) and Wikimedia Commons (video, filtered to Public domain / CC0).
Usage:  python3 fetch_media.py queries.json [out_dir]        (standard library only)"""
import json, os, re, sys, time, urllib.parse, urllib.request
UA = {'User-Agent': 'CloseQuartersClipEngine/0.1 (lyric visuals; contact closequarters.vip)'}
PER_QUERY_IMG, PER_QUERY_VID, MAX_VID_MB = 3, 1, 25
def get(url, raw=False, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                b = r.read(); return b if raw else json.loads(b)
        except Exception as e:
            err = e; time.sleep(2 + 3 * i)
    print('   failed:', url[:90], err); return None
def safe(s): return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:40]
def images(q):
    j = get('https://api.openverse.org/v1/images/?' + urllib.parse.urlencode(dict(q=q, license='cc0,pdm', page_size=12, mature='false'))) or {}
    for r in j.get('results', []):
        u = r.get('url', '')
        if u.lower().split('?')[0].endswith(('.jpg', '.jpeg', '.png')) and (r.get('width') or 0) >= 500:
            yield dict(url=u, title=r.get('title'), creator=r.get('creator'), license=r.get('license'), page=r.get('foreign_landing_url'), source='openverse')
def videos(q):
    p = dict(action='query', format='json', generator='search', gsrsearch='filetype:video ' + q, gsrnamespace=6, gsrlimit=12, prop='imageinfo', iiprop='url|size|mime|extmetadata')
    j = get('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(p)) or {}
    for pg in (j.get('query', {}).get('pages', {}) or {}).values():
        ii = (pg.get('imageinfo') or [{}])[0]; lic = ii.get('extmetadata', {}).get('LicenseShortName', {}).get('value', '')
        if re.search(r'public domain|cc0|pd', lic, re.I) and ii.get('size', 1e12) <= MAX_VID_MB * 1e6 and ii.get('url', '').lower().endswith(('.webm', '.ogv', '.mp4')):
            yield dict(url=ii['url'], title=pg.get('title'), creator=re.sub('<[^>]+>', '', ii.get('extmetadata', {}).get('Artist', {}).get('value', '')), license=lic, page=ii.get('descriptionurl'), source='wikimedia')
def main():
    qfile = sys.argv[1]; cfg = json.load(open(qfile)); out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(qfile)), cfg['song'])
    os.makedirs(out, exist_ok=True); cpath = os.path.join(out, 'credits.json'); credits = json.load(open(cpath)) if os.path.exists(cpath) else {}
    for line in cfg['lines']:
        d = os.path.join(out, '%02d' % line['line']); os.makedirs(d, exist_ok=True); print(line['line'], line['text'])
        for q in line['queries']:
            for kind, gen, n in (('img', images, PER_QUERY_IMG), ('vid', videos, PER_QUERY_VID)):
                got = 0
                for r in gen(q):
                    if got >= n: break
                    ext = os.path.splitext(r['url'].split('?')[0])[1].lower(); name = '%s_%s_%d%s' % (kind, safe(q), got, ext); path = os.path.join(d, name)
                    if not os.path.exists(path):
                        b = get(r['url'], raw=True, tries=2)
                        if not b or len(b) < 15000: continue
                        open(path, 'wb').write(b); time.sleep(0.6)
                    credits[os.path.join('%02d' % line['line'], name)] = dict(query=q, **r); got += 1
                print('   %-28s %s x%d' % (q, kind, got))
            json.dump(credits, open(cpath, 'w'), indent=1)
    print('done ->', out, len(credits), 'files')
if __name__ == '__main__': main()
