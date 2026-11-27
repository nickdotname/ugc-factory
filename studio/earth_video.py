#!/usr/bin/env python3
"""The earth-data account: the real planet, live, moving to a Close Quarters song.

    python studio/earth_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)

The nightly job's renderer for the "earth" style (studio/nightly.py). Everything drawn is real and recent, taken
that morning by studio/earthdata.py:
  satellites  every active satellite (CelesTrak orbits, propagated with SGP4) from the moment they were taken,
              time running faster on every kick; each snare lights up one constellation and says how many it has
  flights     every airliner in the air at that moment (ADSB.lol open data), flown on along its heading for about
              twenty minutes. The camera dives onto one of the busiest of 30 hubs (earthdata/cities.json; the knob
              `place`, not one dived to in the last 3 nights) and the opening line counts the planes within 200 km of
              it ("70 planes over Miami, tracked 27 Nov, 15:44 UTC"); each snare lights up one kind of plane among them
  quakes      every earthquake of magnitude 2.5+ in the last 30 days (USGS). The month is replayed with its clock
              bent so that the largest quakes land on the kicks; the date on screen is always the real one
The globe is drawn from Natural Earth outlines, lit by the real sun at the moment shown (the night side is dark).
Knobs: scene, palette, spin, hook (studio/knobs.py learns which get watched).
"""
import datetime as dt, json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import earthdata

W, H, FPS = 1080, 1920, 30
CX, CY = W / 2, 862.0                     # the globe sits between the opening line and the numbers
R0 = 455.0                                # its radius: 910 px across of a 1080 px frame
# Instagram covers the top 250 px, the bottom 420 px and the right 150 px: every word stays between these lines
SAFE_TOP, SAFE_BOTTOM = 280, H - 420
TX = 495                                  # text is centred a little left of the middle, clear of the buttons on the right
DATA = earthdata.DIR
TW, TH = 4096, 2048
# ocean, land, coast, grid, atmosphere, then the colours of the things drawn (five)
PALETTES = {
    'night': dict(ocean=(6, 12, 28), land=(28, 40, 56), coast=(90, 150, 190), grid=(16, 26, 46), atmo=(70, 140, 255), bg=(2, 3, 8),
                  ink=[(120, 230, 255), (255, 200, 90), (255, 110, 170), (150, 255, 160), (235, 235, 255)], text=(235, 240, 255)),
    'blueprint': dict(ocean=(18, 52, 110), land=(30, 74, 140), coast=(200, 225, 255), grid=(34, 72, 136), atmo=(150, 200, 255), bg=(10, 28, 64),
                      ink=[(255, 255, 255), (255, 220, 120), (140, 240, 255), (255, 160, 160), (200, 255, 200)], text=(240, 246, 255)),
    'ember': dict(ocean=(8, 5, 4), land=(40, 22, 14), coast=(200, 110, 50), grid=(24, 14, 10), atmo=(255, 120, 40), bg=(4, 2, 2),
                  ink=[(255, 170, 60), (255, 240, 170), (255, 90, 50), (255, 210, 110), (255, 255, 230)], text=(255, 236, 214)),
    'marble': dict(ocean=(6, 12, 28), land=(28, 40, 56), coast=(90, 150, 190), grid=(16, 26, 46), atmo=(90, 160, 255), bg=(1, 2, 6),
                   ink=[(120, 235, 255), (255, 214, 110), (255, 96, 150), (150, 255, 160), (240, 240, 255)], text=(240, 244, 255)),
    'paper': dict(ocean=(236, 230, 216), land=(206, 196, 176), coast=(80, 70, 60), grid=(222, 214, 198), atmo=(200, 180, 150), bg=(244, 239, 228),
                  ink=[(20, 20, 30), (200, 50, 40), (30, 90, 200), (20, 130, 90), (120, 60, 160)], text=(28, 26, 24)),
}
CITY_KM = 200.0                           # "N planes over <city>": every plane within this of the city centre, along the ground
REGION_KM = 2000.0                        # ... or, with no busy hub, over a whole region (18 degrees round its middle)
GROUPS = [('STARLINK', 'Starlink'), ('ONEWEB', 'OneWeb'), ('NAV', 'navigation (GPS & co.)'), ('GEO', 'geostationary'), ('OTHER', 'science, weather & the rest')]


def font(size, mono=False):
    for p in ((os.path.join(REPO, 'fonts', 'DejaVuSansMono-Bold.ttf'),) if mono else ()) + (
            os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf'), os.path.join(REPO, 'fonts', 'Poppins-Bold.ttf')):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def thin(frames, n, gap):
    out = []
    for f, st in sorted(frames, key=lambda h: -h[1]):
        if 0 < f < n and all(abs(f - g) >= gap for g, _ in out): out.append((f, st))
    return sorted(f for f, _ in out)


def unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)


def sun_dir(when):
    """Where the sun is overhead (to a fraction of a degree), as a unit vector in Earth's frame."""
    doy = when.timetuple().tm_yday + (when.hour + when.minute / 60) / 24
    dec = -23.44 * math.cos(2 * math.pi / 365 * (doy + 10))
    lon = -15 * (when.hour + when.minute / 60 + when.second / 3600 - 12)
    return unit(dec, lon)


def gmst(when):
    jd = (when - dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)).total_seconds() / 86400
    return math.radians((280.46061837 + 360.98564736629 * jd) % 360)


def texture(pal, TW=TW, TH=TH):
    """The planet flattened (equirectangular): land, ocean, a 30-degree grid and the coastlines, sampled per frame."""
    tex = np.zeros((TH, TW, 3), np.uint8); tex[:] = pal['ocean']
    px = lambda c: np.round(np.stack([(c[:, 0] + 180) / 360 * TW, (90 - c[:, 1]) / 180 * TH], -1) * 4).astype(np.int32)
    for lat in range(-60, 61, 30): cv2.line(tex, (0, int((90 - lat) / 180 * TH)), (TW, int((90 - lat) / 180 * TH)), pal['grid'], 3)
    for lon in range(-180, 180, 30): cv2.line(tex, (int((lon + 180) / 360 * TW), 0), (int((lon + 180) / 360 * TW), TH), pal['grid'], 3)
    for f in json.load(open(os.path.join(DATA, '110m_land.geojson')))['features']:
        g = f['geometry']
        for poly in (g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]):
            cv2.fillPoly(tex, [px(np.array(poly[0]))], pal['land'], cv2.LINE_AA, 2)
            for hole in poly[1:]: cv2.fillPoly(tex, [px(np.array(hole))], pal['ocean'], cv2.LINE_AA, 2)
    for f in json.load(open(os.path.join(DATA, '50m_coastline.geojson')))['features']:
        g = f['geometry']
        for line in (g['coordinates'] if g['type'] == 'MultiLineString' else [g['coordinates']]):
            cv2.polylines(tex, [px(np.array(line))], False, pal['coast'], 3, cv2.LINE_AA, 2)
    return tex


def nasa_map(path, tw, th, night=False):
    """One of NASA's equirectangular maps (180 W at the left edge, 90 N at the top, as ours), at the size wanted."""
    im = cv2.imread(path, cv2.IMREAD_REDUCED_COLOR_2 if os.path.getsize(path) > 12e6 else cv2.IMREAD_COLOR)
    if im is None or abs(im.shape[1] / im.shape[0] - 2) > 0.02: return None
    im = cv2.cvtColor(cv2.resize(im, (tw, th), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    if night:                                                                 # lights brighter and warmer, the dark parts darker
        f = im.astype(np.float32) / 255; f = np.clip((f - 0.03) / 0.97, 0, 1) ** 1.25
        im = (np.clip(f * np.array([1.25, 1.05, 0.8], np.float32) * 1.15, 0, 1) * 255).astype(np.uint8)
    return im


def cities():
    """The 30 big hubs (studio/earthdata/cities.json): [(name, lat, lon)]."""
    try: return [(c['name'], float(c['lat']), float(c['lon'])) for c in json.load(open(os.path.join(DATA, 'cities.json')))['cities']]
    except (OSError, KeyError, ValueError): return []


def recent_places(days=3, path=None):
    """The places this account's earth videos were about in the last few nights (recipes.json, read only): a city is
    not dived to again until the others have had their turn (nightly's fresh-subject rule keys on `scene`, not `place`)."""
    path = path or os.path.join(REPO, 'campaigns', 'earth_data', 'recipes.json')
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    try: rows = json.load(open(path)).get('nightly') or []
    except (OSError, ValueError): return set()
    return {(e.get('knobs') or {}).get('place') for e in rows if e.get('style') == 'earth' and (e.get('date') or '') >= since} - {None}


def within(lat, lon, la, lo, km):
    """Which of the points (lat, lon arrays) lie within km of (la, lo), along the ground."""
    return unit(np.asarray(lat, float), np.asarray(lon, float)) @ unit(np.array(la), np.array(lo)) > math.cos(km / 6371.0)


def taken_of(name):
    """When studio/earthdata.py took this file (latest.json), or None."""
    try: return dt.datetime.strptime(json.load(open(earthdata.LATEST))[name]['taken'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
    except (OSError, KeyError, ValueError, TypeError): return None


def usable(path):
    """Is this day's file there and in the shape this script reads (an older flights file was another source's)?"""
    if not path or not os.path.exists(path) or os.path.getsize(path) < 1000: return False
    if path.endswith('flights.json'):
        try: return len(json.load(open(path)).get('ac') or []) > 500
        except ValueError: return False
    return True


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.r = r
        self.files = earthdata.pull()
        scenes = [s for s, f in (('satellites', 'tle.txt'), ('flights', 'flights.json'), ('quakes', 'quakes.json')) if usable(self.files.get(f))]
        if not scenes: sys.exit('no earth data (run: python studio/earthdata.py pull)')
        self.scene = K.pick('scene', scenes, r, weights=[{'flights': 4, 'quakes': 2, 'satellites': 1}[s] for s in scenes])   # review 2026-11-26: the flights dive is the proven part
        marble = all(usable(self.files.get(n)) for n in ('map_day.jpg', 'map_night.jpg'))
        # paper has had the most watched posts (4 of 10, small sample); marble only once NASA's maps are in the release
        looks = ['paper', 'paper', 'night', 'ember', 'ember'] + (['marble', 'marble'] if marble else [])   # blueprint dropped, ember x2 (review 2026-11-26)
        self.pname = K.pick('palette', looks, r); self.pal = PALETTES[self.pname]
        self.spin = K.pick('spin', ['slow', 'fast'], r)
        self.hook = K.pick('hook', ['fact', 'question'], r, weights=[1, 2])   # the question opener made the 1112-view post
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        ht = a.get('hit_times') or []
        f_of = lambda x: int(round(x * FPS))
        self.kicks = thin([(f_of(x), st) for x, k, st in ht if k == 'kick'], n, 6)
        self.snares = thin([(f_of(x), st) for x, k, st in ht if k == 'snare'], n, 6)
        if len(self.kicks) < 4: self.kicks = thin([(f_of(x), st) for x, k, st in ht if k in ('kick', 'snare')], n, 6)
        self.kick = audio.hits(np.array(self.kicks), n, 7.0); self.snare = audio.hits(np.array(self.snares), n, 8.0)
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.f_hook, self.f_big, self.f_lab, self.f_mono, self.f_small = font(66), font(46), font(34), font(30, True), font(28)
        self.f_tiny = font(24); self._fits = {}
        sans = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        if os.path.exists(sans): self.f_small = ImageFont.truetype(sans, 28); self.f_tiny = ImageFont.truetype(sans, 23)
        size = (8192, 4096) if self.scene == 'flights' else (TW, TH)              # sharper coasts for the close-up
        self.tex_night = None
        if self.pname == 'marble':
            self.tex = nasa_map(self.files['map_day.jpg'], *size); self.tex_night = nasa_map(self.files['map_night.jpg'], *size, night=True)
            if self.tex is None or self.tex_night is None: self.tex = texture(PALETTES['night'], *size); self.tex_night = None
        else: self.tex = texture(self.pal, *size)
        self.trail = np.zeros((H, W, 3), np.float32); self.keep = {'satellites': 0.22, 'flights': 0.15, 'quakes': 0.2}[self.scene]
        yy = np.arange(H, dtype=np.float32)[:, None, None]
        ss = lambda v: v * v * (3 - 2 * v)                                          # smooth edges: no hard bars on the close-ups
        ramp = lambda a, b: ss(np.clip((yy - a) / (b - a), 0, 1))
        self.band = 0.78 * ramp(1240, 1300) * (1 - ramp(1500, 1640))              # behind the numbers
        self.band = self.band + 0.5 * ramp(150, 270) * (1 - ramp(400, 540))       # and, lightly, behind the opening line
        rs = np.random.default_rng(7); self.stars = (rs.uniform(0, W, 260), rs.uniform(0, H, 260), rs.uniform(0.2, 1, 260))
        self.taken = taken_of({'satellites': 'tle.txt', 'flights': 'flights.json', 'quakes': 'quakes.json'}[self.scene]) or dt.datetime.now(dt.timezone.utc)
        self.place, self.zoom, self.ring, self.ring_top = None, R0 + 735, None, None                    # the city named on screen, how close the dive gets, its 200 km ring
        getattr(self, 'setup_' + self.scene)()

    # ---------------------------------------------------------------- the clock: faster on every kick
    def warp(self, per_sec, boost=2.5):
        rate = per_sec * (1 + boost * self.kick) / FPS
        return np.concatenate([[0], np.cumsum(rate)[:-1]])

    # ---------------------------------------------------------------- satellites
    def setup_satellites(self):
        from sgp4.api import Satrec, SatrecArray
        lines = [l.rstrip() for l in open(self.files['tle.txt'], errors='ignore')]
        sats, names = [], []
        for k in range(len(lines) - 2):
            if lines[k + 1].startswith('1 ') and lines[k + 2].startswith('2 '):
                try: sats.append(Satrec.twoline2rv(lines[k + 1], lines[k + 2])); names.append(lines[k].strip())
                except Exception: pass
        self.arr = SatrecArray(sats); self.names = names
        mm = np.array([s.no_kozai * 1440 / (2 * math.pi) for s in sats])         # revolutions a day
        grp = np.full(len(sats), 4)
        up = np.array([n.upper() for n in names])
        grp[np.char.startswith(up, 'STARLINK')] = 0; grp[np.char.startswith(up, 'ONEWEB')] = 1
        nav = np.array([any(t in n for t in ('NAVSTAR', 'GPS', 'GLONASS', 'COSMOS 2', 'GSAT0', 'GALILEO', 'BEIDOU', 'QZS')) for n in up]) & (mm < 3)
        grp[nav] = 2; grp[(mm > 0.9) & (mm < 1.1) & (grp == 4)] = 3
        self.grp = grp; self.iss = int(np.argmax(np.char.startswith(up, 'ISS (ZARYA)'))) if (np.char.startswith(up, 'ISS (ZARYA)')).any() else -1
        self.sim = self.warp(90.0)                                                  # one video second = 90 s of orbit (more on kicks)
        sub = sun_dir(self.taken); self.lat0 = self.r.uniform(10, 35)
        self.lon0 = math.degrees(math.atan2(sub[1], sub[0])) + self.r.uniform(-60, 10)   # the day side, mostly
        order = [0, 3, 1, 2, 4]; self.highlight = {f: order[j % 5] for j, f in enumerate(self.snares)}
        self.counts = {g: int((grp == g).sum()) for g in range(5)}
        self.total = len(sats)

    def sat_positions(self, i):
        when = self.taken + dt.timedelta(seconds=float(self.sim[i]))
        jd = when.timestamp() / 86400 + 2440587.5; jd0 = math.floor(jd - 0.5) + 0.5
        e, rv, _ = self.arr.sgp4(np.array([jd0]), np.array([jd - jd0]))
        p = rv[:, 0, :]; ok = (e[:, 0] == 0) & np.isfinite(p).all(1)
        g = gmst(when); c, s = math.cos(g), math.sin(g)
        x = c * p[:, 0] + s * p[:, 1]; y = -s * p[:, 0] + c * p[:, 1]; z = p[:, 2]
        d = np.sqrt(x * x + y * y + z * z); d[d == 0] = 1
        U = np.stack([x, y, z], -1) / d[:, None]
        alt = np.clip(d - 6371.0, 150, 40000)
        rad = 1 + 0.09 * np.sqrt(alt / 550.0)                                       # heights squeezed so GEO still fits near the frame
        return U, rad, ok, when

    # ---------------------------------------------------------------- flights
    def setup_flights(self):
        j = json.load(open(self.files['flights.json']))
        rows = [a for a in j.get('ac') or [] if isinstance(a.get('alt_ft'), (int, float)) and (a.get('kt') or 0) > 80]
        self.lat = np.array([a['lat'] for a in rows], float); self.lon = np.array([a['lon'] for a in rows], float)
        self.spd = np.array([a['kt'] * 0.514444 for a in rows], float); self.hdg = np.radians(np.array([a.get('track') or 0 for a in rows], float))
        self.alt = np.array([a['alt_ft'] * 0.3048 for a in rows], float); self.family = np.array([a.get('family') or '' for a in rows])
        if j.get('time'): self.taken = dt.datetime.fromtimestamp(j['time'], dt.timezone.utc)
        self.sim = self.warp(60.0, 2.0)                                             # one video second = a minute of flying (about 20 in all)
        self.total = len(rows)
        # the camera comes down over one of the busiest hubs at the moment the data was taken and counts the planes
        # within 200 km of it: one not dived to in the last nights, the busier the likelier (the city is the knob `place`)
        hubs = cities()
        busy = [(name, la, lo, int(within(self.lat, self.lon, la, lo, CITY_KM).sum())) for name, la, lo in hubs]
        top = max([b[3] for b in busy] or [0])
        opts = [b for b in busy if b[3] >= max(20, 0.4 * top)]
        if opts:
            old = recent_places(); opts = [b for b in opts if b[0] not in old] or opts
            name = K.pick('place', [b[0] for b in opts], self.r, weights=[b[3] for b in opts])
            _, self.lat0, self.lon0, _ = next(b for b in opts if b[0] == name); km = CITY_KM
        else:                                                                       # a thin file (no hub busy): the busiest of these skies
            places = [(38, -92, 'North America'), (48, 6, 'Europe'), (32, 115, 'East Asia'), (25, 50, 'the Gulf'), (45, -40, 'the North Atlantic')]
            sky = [int(within(self.lat, self.lon, la, lo, REGION_KM).sum()) for la, lo, _ in places]
            k = sorted(range(len(places)), key=lambda k: -sky[k])[0]
            self.lat0, self.lon0, name = places[k]; km = REGION_KM
            near = [h for h in hubs if within(h[1], h[2], self.lat0, self.lon0, 300.0)]   # named after the nearest hub within 300 km, else the region
            if near:
                name, self.lat0, self.lon0 = max(near, key=lambda h: unit(np.array(h[1]), np.array(h[2])) @ unit(np.array(self.lat0), np.array(self.lon0))); km = CITY_KM
            name = K.pick('place', [name], self.r)
        self.place = name; self.local = within(self.lat, self.lon, self.lat0, self.lon0, km); self.count = int(self.local.sum())
        if km == CITY_KM: self.ring = (self.lat0, self.lon0, km); self.zoom = 3000.0     # in close enough to see the ring
        # each snare lights up one kind of plane among the counted ones, and says how many of them there are
        fams = [c for c, _ in sorted(((c, int((self.family[self.local] == c).sum())) for c in set(self.family[self.local]) if c), key=lambda x: -x[1])[:6] if _ >= 3]   # a kind with 3+ in the ring
        self.highlight = {f: fams[j % len(fams)] for j, f in enumerate(self.snares)} if fams else {}

    def flight_positions(self, tau):
        """Each plane flown on along its great circle for tau seconds at its speed (where it is headed, not where it went)."""
        d = self.spd * tau / 6371000.0
        la, lo = np.radians(self.lat), np.radians(self.lon)
        la2 = np.arcsin(np.sin(la) * np.cos(d) + np.cos(la) * np.sin(d) * np.cos(self.hdg))
        lo2 = lo + np.arctan2(np.sin(self.hdg) * np.sin(d) * np.cos(la), np.cos(d) - np.sin(la) * np.sin(la2))
        return unit(np.degrees(la2), np.degrees(lo2))

    # ---------------------------------------------------------------- earthquakes
    def setup_quakes(self):
        f = json.load(open(self.files['quakes.json']))['features']
        q = sorted(((x['properties']['time'] / 1000, x['properties']['mag'] or 0, x['geometry']['coordinates'], x['properties'].get('place') or '') for x in f), key=lambda z: z[0])
        self.qt = np.array([z[0] for z in q]); self.qm = np.array([z[1] for z in q], float)
        self.qU = unit(np.array([z[2][1] for z in q]), np.array([z[2][0] for z in q])); self.qd = np.array([z[2][2] for z in q], float); self.qplace = [z[3] for z in q]
        n = self.n; start, end = self.qt.min(), self.qt.max() + 3600
        # bend the month's clock: the biggest quakes on the kicks, in the order they happened
        m = min(len(self.kicks), int((self.qm >= 5.0).sum()))
        big = sorted(np.argsort(-self.qm)[:m]) if m else []
        ks = [self.kicks[int(round(j))] for j in np.linspace(0, len(self.kicks) - 1, m)] if m else []
        start = start + 0.08 * (end - start)                                       # the first days already on the globe at the first frame
        big = [b for b in big if self.qt[b] > start]; ks = ks[len(ks) - len(big):] if big else []
        fx = [0] + list(ks) + [n - 1]; tx = [start] + [self.qt[b] for b in big] + [end]
        keep = [0] + [k for k in range(1, len(fx)) if fx[k] > fx[k - 1] and tx[k] > tx[k - 1]]
        self.clock = np.interp(np.arange(n), [fx[k] for k in keep], [tx[k] for k in keep])
        self.big = {ks[j]: big[j] for j in range(len(big))}
        self.qframe = np.interp(self.qt, self.clock, np.arange(n))                  # the frame each quake appears in
        self.total = len(q)
        places = [(10, 140), (38, -125), (-12, -78), (-15, 175), (30, 70), (52, -165)]   # the Ring of Fire, the Himalaya, Alaska
        busy = [int((self.qU @ unit(np.array(la), np.array(lo)) > math.cos(math.radians(45))).sum()) for la, lo in places]
        top = sorted(range(len(places)), key=lambda k: -busy[k])[:2]
        self.lat0, self.lon0 = places[top[0] if self.r.random() < 0.6 else top[1]]   # open on the busiest side of the planet
        self.highlight = {}
        # the globe turns to face the strongest quakes as they strike: a few of them, at least two seconds apart
        way = []
        for f in sorted(self.big, key=lambda f: -self.qm[self.big[f]]):
            if len(way) < 6 and all(abs(f - g) >= 2 * FPS for g, _, _ in way) and f > FPS:
                lat, lon = np.degrees(np.arcsin(self.qU[self.big[f], 2])), np.degrees(np.arctan2(self.qU[self.big[f], 1], self.qU[self.big[f], 0]))
                way.append((f, float(np.clip(lat, -35, 35)), float(lon)))
        self.way = [(0, float(self.lat0), float(self.lon0))] + sorted(way)

    # ---------------------------------------------------------------- drawing
    def view(self, i):
        if self.scene == 'flights':                                                 # swing in and settle over the busy sky
            p = 0.5 - 0.5 * math.cos(math.pi * min(1, i / (self.n * 0.7)))
            lon0 = math.radians(self.lon0 - (1 - p) * (20 if self.spin == 'slow' else 40)); lat0 = math.radians(self.lat0 - (1 - p) * 10)
        elif self.scene == 'quakes' and len(self.way) > 1:
            k = max(j for j, w in enumerate(self.way) if w[0] <= i)
            (fa, la, oa), (fb, lb, ob) = self.way[k], self.way[min(k + 1, len(self.way) - 1)]
            p = 1.0 if fb <= fa else min(1.0, max(0.0, (i - fa) / max(1, fb - fa - 8)))
            p = p * p * (3 - 2 * p); d = (ob - oa + 180) % 360 - 180               # the short way round
            drift = (2.0 if self.spin == 'slow' else 5.0) * (i - fb) / FPS if k == len(self.way) - 1 else 0
            lon0 = math.radians(oa + d * p + drift); lat0 = math.radians(la + (lb - la) * p)
        else:
            lon0 = math.radians(self.lon0 + (4.0 if self.spin == 'slow' else 11.0) * i / FPS); lat0 = math.radians(self.lat0)
        c = np.array([math.cos(lat0) * math.cos(lon0), math.cos(lat0) * math.sin(lon0), math.sin(lat0)])
        e = np.array([-math.sin(lon0), math.cos(lon0), 0.0])
        nn = np.cross(c, e)
        return e, nn, c

    def radius(self, i):
        R = R0
        if self.scene == 'flights': R = R0 + (self.zoom - R0) * (0.5 - 0.5 * math.cos(math.pi * min(1, i / (self.n * 0.7))))   # in close to the busy sky
        return R * (1 + 0.035 * self.snare[i])

    def globe(self, img, i, view, R, sun):
        e, nn, c = view
        m = 90                                                                      # room for the atmosphere's glow
        x0, x1 = max(0, int(CX - R - m)), min(W, int(CX + R + m)); y0, y1 = max(0, int(CY - R - m)), min(H, int(CY + R + m))
        ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        x = (xs - CX) / R; y = (ys - CY) / R; rr = x * x + y * y
        z = np.sqrt(np.clip(1 - rr, 0, 1))
        wx = x * e[0] - y * nn[0] + z * c[0]; wy = x * e[1] - y * nn[1] + z * c[1]; wz = x * e[2] - y * nn[2] + z * c[2]
        lat = np.arcsin(np.clip(wz, -1, 1)); lon = np.arctan2(wy, wx)
        tw, th = self.tex.shape[1], self.tex.shape[0]
        mx = ((lon / (2 * np.pi) + 0.5) * tw).astype(np.float32); my = ((0.5 - lat / np.pi) * th).astype(np.float32)
        col = cv2.remap(self.tex, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP).astype(np.float32)
        day = 0.5 + 0.5 * np.tanh((wx * sun[0] + wy * sun[1] + wz * sun[2]) * 6)   # a soft terminator, where the sun really is
        if self.tex_night is not None:                                          # NASA's day, NASA's city lights on the night side
            lights = cv2.remap(self.tex_night, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP).astype(np.float32)
            col = col * (0.06 + 0.94 * day[..., None]) + lights * (1 - day[..., None]) * 1.1
        else:
            lo = 0.82 if self.pname == 'paper' else 0.42
            col *= (lo + (1 - lo) * day)[..., None]
        col *= (1 - 0.25 * rr[..., None] ** 2)
        a = np.clip((1 - np.sqrt(rr)) * R + 0.5, 0, 1)[..., None]
        rim = np.exp(-np.maximum(np.sqrt(rr) - 1, 0) * R / 22.0)[..., None] * (np.sqrt(rr) > 1)[..., None]
        sub = img[y0:y1, x0:x1]
        glow = rim * np.array(self.pal['atmo'], np.float32) * (0.55 + 0.4 * self.kick[i])
        if self.pname == 'paper': glow = -rim * np.array([46, 50, 58], np.float32) * (0.6 + 0.3 * self.kick[i])   # a soft shadow, not a white ring
        img[y0:y1, x0:x1] = sub * (1 - a) + col * a + glow

    def project(self, U, rad, view, R):
        e, nn, c = view
        px = (U @ e) * rad; py = -(U @ nn) * rad; pz = (U @ c) * rad
        vis = ~((pz < 0) & (px * px + py * py < 1))
        return CX + px * R, CY + py * R, vis

    def ring_mark(self, marks, view, R, col, a):
        """The circle the planes were counted in (CITY_KM round the city, on the ground) and a dot on the city."""
        la, lo, km = self.ring; b = np.radians(np.arange(0, 361, 4.0)); d = km / 6371.0; p, q = math.radians(la), math.radians(lo)
        la2 = np.arcsin(math.sin(p) * math.cos(d) + math.cos(p) * math.sin(d) * np.cos(b))
        lo2 = q + np.arctan2(np.sin(b) * math.sin(d) * math.cos(p), math.cos(d) - math.sin(p) * np.sin(la2))
        sx, sy, vis = self.project(unit(np.degrees(la2), np.degrees(lo2)), np.ones(len(b)), view, R)
        cx, cy, cv = self.project(unit(np.array([la]), np.array([lo])), np.ones(1), view, R)
        c = tuple(float(v) * a for v in col)
        if vis.all(): cv2.polylines(marks, [np.round(np.stack([sx, sy], -1) * 4).astype(np.int32)], True, c, 3, cv2.LINE_AA, 2)
        if cv[0]: cv2.circle(marks, (int(cx[0] * 4), int(cy[0] * 4)), 4 * 5, c, -1, cv2.LINE_AA, 2)
        self.ring_top = (float(cx[0]), float(sy.min())) if vis.all() else None

    def splat(self, layer, sx, sy, cols, size=1.0):
        """Points onto a float image, each spread over the four pixels around it (smooth sub-pixel motion)."""
        ok = (sx > 1) & (sx < W - 2) & (sy > 1) & (sy < H - 2)
        sx, sy, cols = sx[ok], sy[ok], cols[ok]
        ix, iy = np.floor(sx).astype(int), np.floor(sy).astype(int); fx, fy = sx - ix, sy - iy
        for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            for ch in range(3): np.add.at(layer[..., ch], (iy + dy, ix + dx), cols[:, ch] * w * size)

    def planes(self, layer, sx, sy, tx, ty, ok, cols, size):
        """Each plane as a small arrowhead pointing the way it flies (its own heading, projected), as a flight map draws them."""
        ok = ok & (sx > -10) & (sx < W + 10) & (sy > -10) & (sy < H + 10)
        dx, dy = (sx - tx)[ok], (sy - ty)[ok]; L = np.hypot(dx, dy); L[L == 0] = 1; dx, dy = dx / L, dy / L
        x, y, c = sx[ok], sy[ok], cols[ok]
        nose = np.stack([x + dx * size * 1.3, y + dy * size * 1.3], -1)
        left = np.stack([x - dx * size * 0.8 - dy * size * 0.75, y - dy * size * 0.8 + dx * size * 0.75], -1)
        tail = np.stack([x - dx * size * 0.35, y - dy * size * 0.35], -1)
        right = np.stack([x - dx * size * 0.8 + dy * size * 0.75, y - dy * size * 0.8 - dx * size * 0.75], -1)
        poly = np.round(np.stack([nose, left, tail, right], 1) * 4).astype(np.int32)
        key = np.round(c / 24).astype(int); key = key[:, 0] * 10000 + key[:, 1] * 100 + key[:, 2]    # one fill per colour
        for k in np.unique(key):
            m = key == k
            cv2.fillPoly(layer, list(poly[m]), tuple(float(v) for v in c[m][0]), cv2.LINE_AA, 2)

    def frame(self, i):
        pal = self.pal; paper = self.pname == 'paper'
        ink = np.array(pal['ink'], np.float32); ink = 255 - ink if paper else ink     # on paper the ink is taken away from the page
        view = self.view(i); R = self.radius(i)
        img = np.empty((H, W, 3), np.float32); img[:] = pal['bg']
        if not paper:
            sx, sy, sb = self.stars
            for x, y, b in zip(sx, sy, sb): img[int(y), int(x)] = 255 * b * 0.6
        layer = np.zeros((H, W, 3), np.float32); marks = np.zeros_like(layer); labels = []; info = None   # marks: drawn crisp, never smeared into the trail
        if self.scene == 'satellites':
            U, rad, ok, when = self.sat_positions(i); sun = sun_dir(when)
            sx, sy, vis = self.project(U, rad, view, R); vis &= ok
            last = [f for f in self.highlight if f <= i]; hl = self.highlight[max(last)] if last else None
            fl = self.snare[i]
            cols = ink[self.grp] * (0.85 + 0.6 * self.kick[i])
            if hl is not None: cols *= 0.3; cols[self.grp == hl] = ink[2] * (1.4 + 1.2 * fl) + 70 * fl   # in the label's colour
            self.splat(layer, sx[vis], sy[vis], cols[vis], 2.6)
            if self.iss >= 0 and vis[self.iss]:
                labels.append((sx[self.iss], sy[self.iss], 'ISS'))
            info = ('%s ACTIVE SATELLITES' % format(self.total, ','), when)
            if hl is not None: labels.append((None, None, '%s · %s' % (dict(GROUPS)[GROUPS[hl][0]], format(self.counts[hl], ','))))
        elif self.scene == 'flights':
            tau = float(self.sim[i]); when = self.taken + dt.timedelta(seconds=tau); sun = sun_dir(when)
            U = self.flight_positions(tau); sx, sy, vis = self.project(U, np.full(len(U), 1.004), view, R)
            last = [f for f in self.highlight if f <= i]; hl = self.highlight[max(last)] if last else None
            h = np.clip((self.alt - 2000) / 10000, 0, 1)
            cols = (ink[0][None] * h[:, None] + ink[1][None] * (1 - h[:, None])) * (0.85 + 0.4 * self.kick[i])
            if self.ring: cols[~self.local] *= 1 - 0.45 * float(np.clip((R - 800) / 1500, 0, 1))   # close in, the uncounted planes step back
            if hl is not None: cols *= 0.65; cols[(self.family == hl) & self.local] = ink[2] * (1.6 + 1.5 * self.snare[i]) + 60 * self.snare[i]   # only the counted ones
            tail = self.flight_positions(tau - 300); tx, ty, tv = self.project(tail, np.full(len(U), 1.004), view, R)
            for k in np.linspace(0.15, 0.85, 4):                                    # the five minutes behind it, as a fading tail
                self.splat(layer, (sx + (tx - sx) * k)[vis & tv], (sy + (ty - sy) * k)[vis & tv], cols[vis & tv] * (1 - k) * 0.6, 1.0)
            near = float(np.clip((R - 500) / 300, 0, 1))                          # close in, each plane is drawn as a plane
            self.splat(layer, sx[vis], sy[vis], cols[vis], (5.4 if paper else 3.2) * (R / 380) ** 0.5 * (1 - 0.7 * near))   # ink on paper needs more weight than light on black
            if near > 0:                                                            # drawn on their own sheet and added: a fill would wipe the dots under it
                glyph = np.zeros_like(layer); self.planes(glyph, sx, sy, tx, ty, vis & tv, cols, 3.0 + 4.0 * near); layer += glyph * near
            info = ('%s AIRLINERS TRACKED' % format(self.total, ','), when)
            if hl is not None: labels.append((None, None, '%s · %s over %s' % (hl, format(int(((self.family == hl) & self.local).sum()), ','), self.place)))
            if self.ring and near > 0.5: self.ring_mark(marks, view, R, ink[2], near)
        else:
            when = dt.datetime.fromtimestamp(float(self.clock[i]), dt.timezone.utc); sun = sun_dir(when)
            shown = self.qframe <= i
            sx, sy, vis = self.project(self.qU, np.full(len(self.qU), 1.0), view, R)
            age = (i - self.qframe) / FPS
            for k in np.nonzero(shown & vis)[0]:
                m, a = self.qm[k], age[k]
                deep = min(1.0, self.qd[k] / 300)
                col = ink[1] * (1 - deep) + ink[0] * deep
                dot = (1.6 + (m - 2.5) * 1.4) * R / 380
                cv2.circle(layer, (int(sx[k] * 4), int(sy[k] * 4)), int(dot * 4), tuple(float(v) * (0.5 + 0.5 * math.exp(-a)) for v in col), -1, cv2.LINE_AA, 2)
                life = 1.6 if m >= 5 else 0.6
                if 0 <= a < life and m >= 4.3:                                      # the ripple: wide for the big ones, a blip for the rest
                    rr = ((4 + 30 * a) * (10 ** (0.3 * (m - 5))) if m >= 5 else 3 + 14 * a) * R / 380
                    cv2.circle(layer, (int(sx[k] * 4), int(sy[k] * 4)), int(rr * 4), tuple(float(v) * (1 - a / life) * (1.3 if m >= 5 else 0.6) for v in col), 2 + int(m >= 6), cv2.LINE_AA, 2)
            info = ('%s QUAKES OF M2.5+' % format(int(shown.sum()), ','), when)
            near = [f for f in self.big if 0 <= i - f < FPS * 1.4]
            if near:
                k = self.big[max(near)]
                if vis[k]:                                                          # named only when it is on our side of the globe
                    labels.append((sx[k], sy[k], 'M%.1f' % self.qm[k])); labels.append((None, None, 'M%.1f · %s' % (self.qm[k], self.qplace[k][:46])))
        self.globe(img, i, view, R, sun)
        moving = self.scene == 'flights' and i < self.n * 0.7                  # no streaks smeared across the screen while the camera dives in
        self.trail *= 0.35 if moving else 0.8; self.trail += layer * self.keep                      # crisp points now, a fainter streak behind them
        lit = layer + self.trail; glow = cv2.GaussianBlur(lit, (0, 0), 5); lit = lit + marks
        img = (img - (lit + glow * 0.6)) if paper else (img + lit + glow * (0.6 + 0.5 * self.kick[i]))
        img = img * (1 - self.band) + np.array(pal['bg'], np.float32) * self.band          # a quiet band behind the numbers
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        txt = pal['text']; dim = tuple(int(v * 0.72 + (255 if paper else 0) * 0.28) for v in txt)
        stroke = dict(stroke_width=3, stroke_fill=pal['bg'])
        # every word between SAFE_TOP and SAFE_BOTTOM and left of the right-hand 150 px (Instagram's buttons)
        hk = self.hook_text(); f = self.fit(hk, 64, 840)
        d.multiline_text((TX, SAFE_TOP + 66), hk, font=f, fill=txt, anchor='mm', align='center', spacing=12, **stroke)
        if info:
            when = info[1].strftime('%d %b %Y  %H:%M:%S UTC') if self.scene != 'quakes' else info[1].strftime('%d %b %Y  %H:%M UTC')
            d.text((TX, 1325), info[0], font=self.fit(info[0], 58, 840), fill=txt, anchor='mm', **stroke)
            d.text((TX, 1375), when.upper(), font=self.f_mono, fill=dim, anchor='mm', **stroke)
        if self.ring and self.scene == 'flights' and float(np.clip((R - 500) / 300, 0, 1)) > 0.5 and self.ring_top:   # the city's name over its ring
            x, y = self.ring_top
            if SAFE_TOP + 170 < y < SAFE_BOTTOM - 200: d.text((x, y - 14), self.place, font=self.f_lab, fill=txt, anchor='ms', **stroke)
        for x, y, s in labels:
            if x is None: d.text((TX, 1418), s, font=self.fit(s, 36, 840), fill=tuple(pal['ink'][2]), anchor='mm', **stroke)
            else:
                f = self.f_lab; tw = d.textlength(s, font=f); left = x + 46 + tw > W - 160      # flip to the left near the buttons
                if y - 44 < SAFE_TOP + 150 or y > SAFE_BOTTOM - 140: continue                   # never over the words
                if left: d.line([(x - 8, y - 8), (x - 40, y - 40)], fill=txt, width=2); d.text((x - 46, y - 44), s, font=f, fill=txt, anchor='rs', **stroke)
                else: d.line([(x + 8, y - 8), (x + 40, y - 40)], fill=txt, width=2); d.text((x + 46, y - 44), s, font=f, fill=txt, anchor='ls', **stroke)
        src = {'satellites': 'orbits: CelesTrak', 'flights': 'ADSB.lol (ODbL) at %s UTC, flown on by heading%s' % (self.taken.strftime('%H:%M'), ', ring %d km' % CITY_KM if self.ring else ''),
               'quakes': 'data: USGS'}[self.scene] + (' · map: NASA' if self.tex_night is not None else ' · map: Natural Earth')
        d.text((TX, 1455), self.credit, font=self.f_small, fill=dim, anchor='mm', **stroke)
        d.text((TX, 1486), src, font=self.f_tiny, fill=dim, anchor='mm', **stroke)
        return np.asarray(im)

    def fit(self, text, size, maxw):
        """The bold face at the largest size up to `size` whose widest line fits in maxw."""
        key = (text, size, maxw)
        if key not in self._fits:
            probe = ImageDraw.Draw(Image.new('L', (1, 1)))
            while size > 26 and max(probe.textlength(l, font=font(size)) for l in text.split('\n')) > maxw: size -= 2
            self._fits[key] = font(size)
        return self._fits[key]

    def hook_text(self):
        """The opening line: on screen from frame 0 to the end, and true of this video's own data."""
        at = '%s, %s UTC' % (self.taken.strftime('%-d %b'), self.taken.strftime('%H:%M'))
        if self.scene == 'satellites':
            return {'fact': 'every active satellite\n%s' % at, 'question': 'how crowded is\nlow Earth orbit?'}[self.hook]
        if self.scene == 'flights':                                                 # ADSB.lol hears most planes, not all: "tracked"
            return '%s planes over %s,\n%s' % (format(self.count, ','), self.place, {'fact': 'tracked %s' % at,
                    'question': 'tracked at %s UTC. which ones?' % self.taken.strftime('%H:%M')}[self.hook])
        days = max(1, round((self.qt.max() - self.qt.min()) / 86400))
        return {'fact': '%d days of earthquakes\nin %d seconds' % (days, max(1, round(self.n / FPS))),
                'question': 'how often does\nthe Earth shake?'}[self.hook]

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]; want = set(fs); ims = []
            for i in range(max(fs) + 1):
                fr = self.frame(i)
                if i in want: ims.append(Image.fromarray(fr).resize((360, 640)))
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '8M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '16M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 60 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
