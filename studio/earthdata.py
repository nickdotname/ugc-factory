"""Open data about the planet for the earth-data account: satellites, flights, earthquakes.

    python studio/earthdata.py fetch     (GitHub Actions, daily: download the newest data, upload it)
    python studio/earthdata.py pull      (download the newest data into studio/earthdata/cache)

  satellites  every active satellite's orbit (two-line elements) from CelesTrak, propagated with SGP4
  flights     every airliner in the air right now (ADSB.lol, open data under the ODbL), asked for by aircraft type
              (A320s, 737s, 787s, regional jets, turboprops...); if it is down, yesterday's copy stays.
              (Not OpenSky or ADS-B Exchange: their live data is for non-commercial use only.)
  quakes      every earthquake of magnitude 2.5+ in the last 30 days (USGS)
The newest copy of each lives as an asset of the GitHub release "earth-data" (replaced every day) and
studio/earthdata/latest.json says when each was taken and how many records it has. Coastlines and land are
Natural Earth (public domain), kept in this folder.
  maps        NASA's Blue Marble (day, topography and bathymetry) and Black Marble 2016 (night lights), public domain,
              fetched once and kept in the same release as map_day.jpg / map_night.jpg; the renderer's "marble" look
              lays the real sun's day and night over them. Never fetched again once they are there.
"""
import json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); DIR = os.path.join(HERE, 'earthdata'); CACHE = os.path.join(DIR, 'cache')
LATEST = os.path.join(DIR, 'latest.json'); REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory'); RELEASE = 'earth-data'
UA = {'User-Agent': 'CloseQuartersEarthData/1.0 (https://closequarters.vip; contact via the site)'}
SOURCES = {
    'tle.txt': ['https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle'],
    'quakes.json': ['https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_month.geojson'],
    'flights.json': ['adsb.lol'],
}
# Aircraft types, grouped as the videos name them. Every type here is asked for once a day.
FAMILIES = [('Airbus A320 family', 'A318 A319 A320 A321 A19N A20N A21N'), ('Boeing 737', 'B732 B733 B734 B735 B736 B737 B738 B739 B37M B38M B39M B3XM'),
            ('Boeing 777', 'B772 B773 B77L B77W B778 B779'), ('Boeing 787', 'B788 B789 B78X'), ('Airbus A350', 'A359 A35K'),
            ('Airbus A330', 'A332 A333 A338 A339'), ('Boeing 747', 'B744 B748 B74S'), ('Airbus A380', 'A388'),
            ('Boeing 757 & 767', 'B752 B753 B762 B763 B764'), ('regional jets', 'E170 E175 E75L E75S E190 E195 E290 E295 CRJ2 CRJ7 CRJ9 CRJX BCS1 BCS3'),
            ('turboprops', 'AT43 AT45 AT72 AT75 AT76 DH8A DH8B DH8C DH8D')]
ADSB = 'https://api.adsb.lol/v2/type/%s'
# Pictures of the planet (NASA Earth Observatory, public domain). First URL that answers with a real JPEG wins.
NASA = 'https://assets.science.nasa.gov/content/dam/science/esd/eo/images/'
MAPS = {
    'map_day.jpg': [NASA + 'bmng/bmng-topography-bathymetry/october/world.topo.bathy.200410.3x5400x2700.jpg',
                    NASA + 'bmng/bmng-topography-bathymetry/july/world.topo.bathy.200407.3x5400x2700.jpg'],
    'map_night.jpg': [NASA + 'imagerecords/144000/144898/BlackMarble_2016_3km.jpg',
                      NASA + 'imagerecords/144000/144898/BlackMarble_2016_01deg.jpg'],
}


def adsb():
    """Every airliner ADSB.lol hears, one aircraft type at a time (its public API has no single worldwide query)."""
    seen = {}
    for fam, types in FAMILIES:
        for t in types.split():
            try: j = json.loads(get(ADSB % t, tries=4))
            except Exception as exc: print('  adsb.lol %s: %s' % (t, exc)); continue
            for a in j.get('ac') or []:
                if a.get('lat') is None or a.get('alt_baro') in (None, 'ground'): continue
                seen[a.get('hex')] = dict(lat=round(a['lat'], 4), lon=round(a['lon'], 4), alt_ft=a.get('alt_geom') or a.get('alt_baro'),
                                          kt=a.get('gs'), track=a.get('track'), type=t, family=fam, reg=a.get('r') or '')
            time.sleep(3)                                                     # it rate-limits at about one request every two seconds
    return json.dumps(dict(time=int(time.time()), source='ADSB.lol (ODbL 1.0)', ac=list(seen.values()))).encode()


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
    return len(j.get('ac') or [])


def fetch():
    latest = json.load(open(LATEST)) if os.path.exists(LATEST) else {}
    os.makedirs(CACHE, exist_ok=True); got = []
    for name, urls in SOURCES.items():
        for url in urls:
            try: raw = adsb() if url == 'adsb.lol' else get(url); n = count(name, raw)
            except Exception as exc: print('  %s from %s failed: %s' % (name, url, exc)); continue
            if n < 10: print('  %s from %s: only %d records' % (name, url, n)); continue
            open(os.path.join(CACHE, name), 'wb').write(raw); got.append(name)
            latest[name] = dict(source=url, taken=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), records=n)
            print('%s: %d records from %s' % (name, n, url)); break
    try:
        have = {a['name'] for a in json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout).get('assets', [])}
    except (subprocess.CalledProcessError, ValueError): have = set()
    got += maps(have)
    if got:
        if subprocess.run(['gh', 'release', 'view', RELEASE, '-R', REPO], capture_output=True).returncode:
            subprocess.run(['gh', 'release', 'create', RELEASE, '-R', REPO, '--title', 'Earth data (newest)', '--notes',
                            'Satellites (CelesTrak), airliners (ADSB.lol, ODbL 1.0), earthquakes (USGS). Replaced daily; see studio/earthdata/latest.json.'], check=True)
        subprocess.run(['gh', 'release', 'upload', RELEASE, '-R', REPO, '--clobber'] + [os.path.join(CACHE, n) for n in got], check=True)
    json.dump(latest, open(LATEST, 'w'), indent=1)


def maps(have):
    """The two NASA maps, fetched once: only the ones the release does not have yet. Returns the files got."""
    got = []
    for name, urls in MAPS.items():
        if name in have: continue
        for url in urls:
            try: raw = get(url, tries=2)
            except Exception as exc: print('  %s from %s failed: %s' % (name, url, exc)); continue
            if len(raw) < 300000 or raw[:3] != b'\xff\xd8\xff': print('  %s from %s: not a map (%d bytes)' % (name, url, len(raw))); continue
            open(os.path.join(CACHE, name), 'wb').write(raw); got.append(name); print('%s: %d bytes from %s' % (name, len(raw), url)); break
    return got


def pull():
    os.makedirs(CACHE, exist_ok=True)
    rel = json.loads(subprocess.run(['gh', 'api', 'repos/%s/releases/tags/%s' % (REPO, RELEASE)], capture_output=True, text=True, check=True).stdout)
    for a in rel.get('assets', []):
        out = os.path.join(CACHE, a['name'])
        fresh = a['name'] in MAPS or time.time() - os.path.getmtime(out) < 6 * 3600 if os.path.exists(out) else False   # the maps never change
        if os.path.exists(out) and os.path.getsize(out) == a['size'] and fresh: continue
        with open(out, 'wb') as fh:
            fh.write(subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream', 'repos/%s/releases/assets/%d' % (REPO, a['id'])], capture_output=True, check=True).stdout)
    return {n: os.path.join(CACHE, n) for n in list(SOURCES) + list(MAPS) if os.path.exists(os.path.join(CACHE, n))}


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'fetch': fetch()
    elif cmd == 'pull': print(pull())
    else: sys.exit(__doc__)
