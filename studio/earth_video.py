#!/usr/bin/env python3
"""The earth-data account: the real planet, live, moving to a Close Quarters song.

    python studio/earth_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)

The nightly job's renderer for the "earth" style (studio/nightly.py). Everything drawn is real and recent, taken
that morning by studio/earthdata.py:
  satellites  every active satellite (CelesTrak orbits, propagated with SGP4) from the moment they were taken,
              time running faster on every kick; each snare lights up one constellation and says how many it has
  flights     every airliner in the air at that moment (ADSB.lol open data), flown on along its heading for about
              twenty minutes; each snare lights up one kind of plane (every A320, every 737...) and says how many
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
CX, CY = W / 2, H * 0.47
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
    'paper': dict(ocean=(236, 230, 216), land=(206, 196, 176), coast=(80, 70, 60), grid=(222, 214, 198), atmo=(200, 180, 150), bg=(244, 239, 228),
                  ink=[(20, 20, 30), (200, 50, 40), (30, 90, 200), (20, 130, 90), (120, 60, 160)], text=(28, 26, 24)),
}
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
        self.scene = K.pick('scene', scenes, r)
        self.pname = K.pick('palette', sorted(PALETTES), r); self.pal = PALETTES[self.pname]
        self.spin = K.pick('spin', ['slow', 'fast'], r)
        self.hook = K.pick('hook', ['fact', 'question'], r)
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
        sans = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        if os.path.exists(sans): self.f_small = ImageFont.truetype(sans, 28)
        self.tex = texture(self.pal, *((8192, 4096) if self.scene == 'flights' else (TW, TH)))   # sharper coasts for the close-up
        self.trail = np.zeros((H, W, 3), np.float32); self.keep = {'satellites': 0.22, 'flights': 0.15, 'quakes': 0.2}[self.scene]
        yy = np.arange(H, dtype=np.float32)[:, None, None]
        self.band = 0.75 * np.clip((yy - H * 0.70) / (H * 0.08), 0, 1)
        rs = np.random.default_rng(7); self.stars = (rs.uniform(0, W, 260), rs.uniform(0, H, 260), rs.uniform(0.2, 1, 260))
        self.taken = dt.datetime.now(dt.timezone.utc)
        try:
            meta = json.load(open(earthdata.LATEST)); key = {'satellites': 'tle.txt', 'flights': 'flights.json', 'quakes': 'quakes.json'}[self.scene]
            self.taken = dt.datetime.strptime(meta[key]['taken'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
        except (OSError, KeyError, ValueError): pass
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
        top = [c for c, _ in sorted(((c, (self.family == c).sum()) for c in set(self.family) if c), key=lambda x: -x[1])[:6]]
        self.highlight = {f: top[j % len(top)] for j, f in enumerate(self.snares)} if top else {}
        self.total = len(rows)
        # the camera comes down over whichever of these skies is busiest at the moment the data was taken
        places = [(38, -92), (48, 6), (32, 115), (25, 50), (45, -40)]               # North America, Europe, East Asia, the Gulf, the Atlantic tracks
        P = unit(self.lat, self.lon)
        busy = [int((P @ unit(np.array(la), np.array(lo)) > math.cos(math.radians(18))).sum()) for la, lo in places]
        top = sorted(range(len(places)), key=lambda k: -busy[k])[:2]
        self.lat0, self.lon0 = places[top[0] if self.r.random() < 0.7 else top[1]]

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
        self.lat0, self.lon0 = self.r.choice([(10, 160), (0, -150), (5, 120), (-10, -80)])   # the Pacific's Ring of Fire
        self.highlight = {}

    # ---------------------------------------------------------------- drawing
    def view(self, i):
        if self.scene == 'flights':                                                 # swing in and settle over the busy sky
            p = 0.5 - 0.5 * math.cos(math.pi * min(1, i / (self.n * 0.7)))
            lon0 = math.radians(self.lon0 - (1 - p) * (20 if self.spin == 'slow' else 40)); lat0 = math.radians(self.lat0 - (1 - p) * 10)
        else:
            lon0 = math.radians(self.lon0 + (4.0 if self.spin == 'slow' else 11.0) * i / FPS); lat0 = math.radians(self.lat0)
        c = np.array([math.cos(lat0) * math.cos(lon0), math.cos(lat0) * math.sin(lon0), math.sin(lat0)])
        e = np.array([-math.sin(lon0), math.cos(lon0), 0.0])
        nn = np.cross(c, e)
        return e, nn, c

    def radius(self, i):
        R = 380.0
        if self.scene == 'flights': R = 380 + 820 * (0.5 - 0.5 * math.cos(math.pi * min(1, i / (self.n * 0.7))))   # in close to the busy sky
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
        light = np.clip((wx * sun[0] + wy * sun[1] + wz * sun[2]) * 3 + 0.6, 0.4 if self.pname != 'paper' else 0.72, 1.0)
        col *= light[..., None] * (1 - 0.25 * rr[..., None] ** 2)
        a = np.clip((1 - np.sqrt(rr)) * R + 0.5, 0, 1)[..., None]
        rim = np.exp(-np.maximum(np.sqrt(rr) - 1, 0) * R / 22.0)[..., None] * (np.sqrt(rr) > 1)[..., None]
        sub = img[y0:y1, x0:x1]
        img[y0:y1, x0:x1] = sub * (1 - a) + col * a + rim * np.array(self.pal['atmo'], np.float32) * (0.55 + 0.4 * self.kick[i])

    def project(self, U, rad, view, R):
        e, nn, c = view
        px = (U @ e) * rad; py = -(U @ nn) * rad; pz = (U @ c) * rad
        vis = ~((pz < 0) & (px * px + py * py < 1))
        return CX + px * R, CY + py * R, vis

    def splat(self, layer, sx, sy, cols, size=1.0):
        """Points onto a float image, each spread over the four pixels around it (smooth sub-pixel motion)."""
        ok = (sx > 1) & (sx < W - 2) & (sy > 1) & (sy < H - 2)
        sx, sy, cols = sx[ok], sy[ok], cols[ok]
        ix, iy = np.floor(sx).astype(int), np.floor(sy).astype(int); fx, fy = sx - ix, sy - iy
        for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            for ch in range(3): np.add.at(layer[..., ch], (iy + dy, ix + dx), cols[:, ch] * w * size)

    def frame(self, i):
        pal = self.pal; paper = self.pname == 'paper'
        ink = np.array(pal['ink'], np.float32); ink = 255 - ink if paper else ink     # on paper the ink is taken away from the page
        view = self.view(i); R = self.radius(i)
        img = np.empty((H, W, 3), np.float32); img[:] = pal['bg']
        if not paper:
            sx, sy, sb = self.stars
            for x, y, b in zip(sx, sy, sb): img[int(y), int(x)] = 255 * b * 0.6
        layer = np.zeros((H, W, 3), np.float32); labels = []; info = None
        if self.scene == 'satellites':
            U, rad, ok, when = self.sat_positions(i); sun = sun_dir(when)
            sx, sy, vis = self.project(U, rad, view, R); vis &= ok
            last = [f for f in self.highlight if f <= i]; hl = self.highlight[max(last)] if last else None
            fl = self.snare[i]
            cols = ink[self.grp] * (0.85 + 0.6 * self.kick[i])
            if hl is not None: cols *= 0.5; cols[self.grp == hl] = ink[hl] * (1.3 + 1.2 * fl) + 70 * fl
            self.splat(layer, sx[vis], sy[vis], cols[vis], 2.6)
            if self.iss >= 0 and vis[self.iss]:
                labels.append((sx[self.iss], sy[self.iss], 'ISS'))
            info = ('%s SATELLITES' % format(self.total, ','), when)
            if hl is not None: labels.append((None, None, '%s · %s' % (dict(GROUPS)[GROUPS[hl][0]], format(self.counts[hl], ','))))
        elif self.scene == 'flights':
            tau = float(self.sim[i]); when = self.taken + dt.timedelta(seconds=tau); sun = sun_dir(when)
            U = self.flight_positions(tau); sx, sy, vis = self.project(U, np.full(len(U), 1.004), view, R)
            last = [f for f in self.highlight if f <= i]; hl = self.highlight[max(last)] if last else None
            h = np.clip((self.alt - 2000) / 10000, 0, 1)
            cols = (ink[0][None] * h[:, None] + ink[1][None] * (1 - h[:, None])) * (0.6 + 0.5 * self.kick[i])
            if hl is not None: cols *= 0.5; cols[self.family == hl] = ink[2] * (1.6 + 1.5 * self.snare[i]) + 60 * self.snare[i]
            tail = self.flight_positions(tau - 300); tx, ty, tv = self.project(tail, np.full(len(U), 1.004), view, R)
            for k in np.linspace(0.15, 0.85, 4):                                    # the five minutes behind it, as a fading tail
                self.splat(layer, (sx + (tx - sx) * k)[vis & tv], (sy + (ty - sy) * k)[vis & tv], cols[vis & tv] * (1 - k) * 0.6, 1.0)
            self.splat(layer, sx[vis], sy[vis], cols[vis], 3.2 * (R / 380) ** 0.5)
            info = ('%s AIRLINERS IN THE AIR' % format(self.total, ','), when)
            if hl is not None: labels.append((None, None, '%s · %s' % (hl, format(int((self.family == hl).sum()), ','))))
        else:
            when = dt.datetime.fromtimestamp(float(self.clock[i]), dt.timezone.utc); sun = sun_dir(when)
            shown = self.qframe <= i
            sx, sy, vis = self.project(self.qU, np.full(len(self.qU), 1.0), view, R)
            age = (i - self.qframe) / FPS
            for k in np.nonzero(shown & vis)[0]:
                m, a = self.qm[k], age[k]
                deep = min(1.0, self.qd[k] / 300)
                col = ink[1] * (1 - deep) + ink[0] * deep
                dot = (1.2 + (m - 2.5) * 1.1) * R / 380
                cv2.circle(layer, (int(sx[k] * 4), int(sy[k] * 4)), int(dot * 4), tuple(float(v) * (0.5 + 0.5 * math.exp(-a)) for v in col), -1, cv2.LINE_AA, 2)
                life = 1.6 if m >= 5 else 0.6
                if 0 <= a < life and m >= 4.3:                                      # the ripple: wide for the big ones, a blip for the rest
                    rr = ((4 + 30 * a) * (10 ** (0.3 * (m - 5))) if m >= 5 else 3 + 14 * a) * R / 380
                    cv2.circle(layer, (int(sx[k] * 4), int(sy[k] * 4)), int(rr * 4), tuple(float(v) * (1 - a / life) * (1.3 if m >= 5 else 0.6) for v in col), 2 + int(m >= 6), cv2.LINE_AA, 2)
            info = ('%s EARTHQUAKES' % format(int(shown.sum()), ','), when)
            near = [f for f in self.big if 0 <= i - f < FPS * 1.4]
            if near:
                k = self.big[max(near)]
                if vis[k]: labels.append((sx[k], sy[k], 'M%.1f' % self.qm[k]))
                labels.append((None, None, 'M%.1f · %s' % (self.qm[k], self.qplace[k][:46])))
        self.globe(img, i, view, R, sun)
        self.trail *= 0.8; self.trail += layer * self.keep                      # crisp points now, a fainter streak behind them
        lit = layer + self.trail; glow = cv2.GaussianBlur(lit, (0, 0), 5)
        img = (img - (lit + glow * 0.6)) if paper else (img + lit + glow * (0.6 + 0.5 * self.kick[i]))
        img = img * (1 - self.band) + np.array(pal['bg'], np.float32) * self.band          # a quiet band behind the numbers
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        txt = pal['text']; dim = tuple(int(v * 0.72 + (255 if paper else 0) * 0.28) for v in txt)
        stroke = dict(stroke_width=3, stroke_fill=pal['bg'])
        t = i / FPS
        if t < 3.4:
            d.multiline_text((W / 2, 250), self.hook_text(), font=self.f_hook, fill=txt, anchor='mm', align='center', spacing=14, **stroke)
        if info:
            d.text((W / 2, H * 0.80), info[0], font=self.f_big, fill=txt, anchor='mm', **stroke)
            d.text((W / 2, H * 0.80 + 56), info[1].strftime('%d %b %Y  %H:%M:%S UTC').upper() if self.scene != 'quakes' else info[1].strftime('%d %b %Y  %H:%M UTC').upper(),
                   font=self.f_mono, fill=dim, anchor='mm', **stroke)
        for x, y, s in labels:
            if x is None: d.text((W / 2, H * 0.80 + 112), s, font=self.f_lab, fill=tuple(pal['ink'][2] if not paper else pal['ink'][1]), anchor='mm', **stroke)
            else:
                d.line([(x + 8, y - 8), (x + 40, y - 40)], fill=txt, width=2); d.text((x + 46, y - 44), s, font=self.f_lab, fill=txt, anchor='ls', **stroke)
        d.text((W / 2, H - 112), self.credit, font=self.f_small, fill=dim, anchor='mm')
        d.text((W / 2, H - 72), {'satellites': 'orbits: CelesTrak', 'flights': 'positions: ADSB.lol (ODbL), flown on by heading', 'quakes': 'data: USGS'}[self.scene] + ' · map: Natural Earth',
               font=self.f_small, fill=dim, anchor='mm')
        return np.asarray(im)

    def hook_text(self):
        when = self.taken.strftime('%H:%M UTC')
        return {('satellites', 'fact'): 'every active satellite,\nright now',
                ('satellites', 'question'): 'how many satellites\nare above you?',
                ('flights', 'fact'): 'every airliner in the sky\nat %s' % when,
                ('flights', 'question'): 'how many airliners are\nin the air right now?',
                ('quakes', 'fact'): 'every earthquake\non Earth this month',
                ('quakes', 'question'): 'how often does\nthe Earth shake?'}[(self.scene, self.hook)]

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
