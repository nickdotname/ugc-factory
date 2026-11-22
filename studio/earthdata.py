"""Open data about the planet for the earth-data account: satellites, flights, earthquakes.

    python studio/earthdata.py fetch     (GitHub Actions, daily: download the newest data, upload it)
    python studio/earthdata.py pull      (download the newest data into studio/earthdata/cache)

  satellites  every active satellite's orbit (two-line elements) from CelesTrak, propagated with SGP4
  flights     every aircraft broadcasting its position right now (OpenSky Network; adsb.lol as a fallback)
  quakes      every earthquake of magnitude 2.5+ in the last 30 days (USGS)
The newest copy of each lives as an asset of the GitHub release "earth-data" (replaced every day) and
studio/earthdata/latest.json says when each was taken and how many records it has. Coastlines and land are
Natural Earth (public domain), kept in this folder.
"""
import json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'earthdata'); CACHE = os.path.join(DIR, 'cache')
LATEST = os.path.join(DIR, 'latest.json'); REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'earth-data'
UA = {'User-Agent': 'CloseQuartersEarthData/1.0 (https://closequarters.vip; closequartersandloosechange@gmail.com)'}
SOURCES = {
    'tle.txt': ['https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle'],
    'quakes.json': ['https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_month.geojson'],
    'flights.json': ['https://opensky-network.org/api/states/all', 'https://api.adsb.lol/v2/mil'],
}


def get(url, tries=3):
    for k in range(tries):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
        except Exception as exc:
            if k == tries - 1: raise
            print('  retry', url, exc); time.sleep(20 * (k + 1))


def count(name, raw):
    if name == 'tle.txt': return sum(1 for l in raw.decode(errors='ignore').splitlines() if l.startswith('1 '))
    j = json.loads(raw)
    if name == 'quakes.json': return len(j.get('features', []))
    return len(j.get('states') or j.get('ac') or [])


def fetch():
    latest = json.load(open(LATEST)) if os.path.exists(LATEST) else {}
    os.makedirs(CACHE, exist_ok=True); got = []
    for name, urls in SOURCES.items():
        for url in urls:
            try: raw = get(url); n = count(name, raw)
            except Exception as exc: print('  %s from %s failed: %s' % (name, url, exc)); continue
            if n < 10: print('  %s from %s: only %d records' % (name, url, n)); continue
            open(os.path.join(CACHE, name), 'wb').write(raw); got.append(name)
            latest[name] = dict(source=url, taken=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), records=n)
            print('%s: %d records from %s' % (name, n, url)); break
    if got:
        if subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode:
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Earth data (newest)', '--notes',
                            'Satellites (CelesTrak), flights (OpenSky / adsb.lol), earthquakes (USGS). Replaced daily; see studio/earthdata/latest.json.'], check=True)
        subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + [os.path.join(CACHE, n) for n in got], check=True)
    json.dump(latest, open(LATEST, 'w'), indent=1)


def pull():
    os.makedirs(CACHE, exist_ok=True)
    rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
    for a in rel.get('assets', []):
        out = os.path.join(CACHE, a['name'])
        if os.path.exists(out) and os.path.getsize(out) == a['size'] and time.time() - os.path.getmtime(out) < 6 * 3600: continue
        with open(out, 'wb') as fh:
            fh.write(subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream', 'repos/%s/releases/assets/%d' % (REPO, a['id'])], capture_output=True, check=True).stdout)
    return {n: os.path.join(CACHE, n) for n in SOURCES if os.path.exists(os.path.join(CACHE, n))}


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'fetch': fetch()
    elif cmd == 'pull': print(pull())
    else: sys.exit(__doc__)
