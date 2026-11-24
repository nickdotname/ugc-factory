"""The air around a pixel world: a painted sky instead of a flat backdrop, drifting clouds, distant ridges for depth,
a moon or a low sun, birds, and weather (rain with splashes and one lightning strike on the song's big bar line, or
snow that settles on the tops of things as the clip goes on). The world itself is lit to match: blue at night, warm
at dusk. Everything is drawn in code into the same 270 x 480 pixel canvas as the world, so it stays pixel art."""
import math
import numpy as np

SKIES = {   # top colour, horizon colour, light on the world (multiplier), the moon or sun, its colour
    'night': ((8, 10, 28), (40, 46, 92), (0.64, 0.72, 1.0), 'moon', (250, 246, 220)),
    'dusk': ((34, 22, 66), (250, 128, 92), (1.06, 0.86, 0.80), 'sun', (255, 214, 150)),
    'dawn': ((56, 92, 156), (255, 196, 168), (1.02, 0.96, 0.98), 'sun', (255, 240, 210)),
}


def _noise(h, w, rng, octaves=4, base=24.0):
    """Smooth value noise, 0..1, tiling across x so it can scroll forever."""
    out = np.zeros((h, w), np.float32); amp = 1.0; tot = 0.0
    for o in range(octaves):
        s = base / (2 ** o); gh, gw = int(h / s) + 2, max(2, int(round(w / s)))
        g = rng.random((gh, gw)).astype(np.float32)
        ys = np.arange(h) / s; xs = np.arange(w) / w * gw
        y0 = ys.astype(int); fy = (ys - y0)[:, None]; x0 = xs.astype(int); fx = (xs - x0)[None, :]
        fy = fy * fy * (3 - 2 * fy); fx = fx * fx * (3 - 2 * fx)
        a = g[y0][:, x0 % gw]; b = g[y0][:, (x0 + 1) % gw]; c = g[y0 + 1][:, x0 % gw]; d = g[y0 + 1][:, (x0 + 1) % gw]
        out += amp * ((a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy); tot += amp; amp *= 0.5
    return out / tot


class Air:
    def __init__(self, kind, weather, w, h, top, rng, view=0):
        """kind: a key of SKIES; weather: clear, rain or snow; top: the canvas row where the world starts; view: the
        first canvas row the camera shows."""
        self.kind, self.weather, self.w, self.h = kind, weather, w, h
        c0, c1, self.light, self.body, self.body_col = SKIES[kind]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        hz = top + 0.42 * (h - top)                               # the horizon sits behind the middle of the world
        u = np.clip(yy / hz, 0, 1) ** 1.4
        sky = np.array(c0, np.float32) * (1 - u[..., None]) + np.array(c1, np.float32) * u[..., None]
        sky += (rng.random((h, w, 1)) - 0.5) * 5                         # a little grain, so the gradient is pixels too
        # the moon or the sun, up and to one side, with its glow
        self.bx, self.by = (w * (0.24 if rng.random() < 0.5 else 0.76), view + 12 + (top - view - 12) * 0.42)
        r = np.hypot(xx - self.bx, yy - self.by)
        glow = np.exp(-r / (26 if self.body == 'sun' else 18))[..., None]
        sky = sky + glow * np.array(self.body_col, np.float32) * (0.55 if self.body == 'sun' else 0.35)
        disc = r < (13 if self.body == 'sun' else 10)
        sky[disc] = self.body_col
        if self.body == 'moon':                                          # craters
            for k in range(6):
                a, d = rng.uniform(0, 6.28), rng.uniform(0, 7); cx, cy = self.bx + d * math.cos(a), self.by + d * math.sin(a)
                sky[np.hypot(xx - cx, yy - cy) < rng.uniform(1, 2.6)] *= 0.86
        # two ridges far away: the further one paler, both just darker than the sky they stand in
        for k, (lift, amp, shade) in enumerate([(0.0, 26, 0.80), (16, 20, 0.62)]):
            n = _noise(1, w, rng, octaves=3, base=60 - 20 * k)[0]
            ridge = hz - lift - 14 + (n - 0.5) * 2 * amp
            ridge = ridge + 3 * (rng.random(w) > 0.7)                    # trees on the skyline, a pixel or three tall
            m = yy > ridge[None, :]
            dep = np.clip((yy - ridge[None, :]) / 60.0, 0, 1)[..., None]  # mist gathers in the valleys below
            far = sky * shade + np.array(c0, np.float32) * (1 - shade) * 0.5
            mist = np.array(c1, np.float32) * 0.45 + np.array(c0, np.float32) * 0.35
            sky = np.where(m[..., None], far * (1 - 0.6 * dep) + mist * 0.6 * dep, sky)
        self.sky = np.clip(sky, 0, 255)
        self.stars = [(rng.uniform(0, w), rng.uniform(0, hz - 30), rng.uniform(0.3, 1), rng.uniform(0, 6.28))
                      for _ in range(110 if kind == 'night' else 30 if kind == 'dusk' else 0)]
        # clouds: a band of noise, scrolled sideways, cut at a threshold and lit from the body's side
        self.cloud = _noise(int(top + 40), w * 2, rng, octaves=5, base=36.0)
        self.cloud_col = (np.array(c1, np.float32) * 0.6 + np.array(self.body_col, np.float32) * 0.4) * (0.55 if kind == 'night' else 1.0)
        n = {'rain': 260, 'snow': 220}.get(weather, 0)
        self.drops = np.stack([rng.uniform(0, w, n), rng.uniform(0, h, n), rng.uniform(0.7, 1.3, n), rng.uniform(0, 6.28, n)], 1) if n else np.zeros((0, 4))
        self.birds = [(rng.uniform(-60, -10) - 14 * k, top * 0.5 + rng.uniform(-14, 14), rng.uniform(0, 6.28)) for k in range(7)] \
            if kind != 'night' else []

    def backdrop(self, i, E):
        """The sky for frame i (only seen where there is no world)."""
        t = i / 30.0; s = self.sky.copy(); h = self.cloud.shape[0]
        for (x, y, b, ph) in self.stars:
            tw = b * (0.55 + 0.45 * math.sin(t * 2 + ph)) + 0.5 * float(E['hat'][i]) * b
            s[int(y), int(x)] = np.minimum(255, s[int(y), int(x)] + 200 * tw)
        off = int(t * 4) % (self.w * 2)
        c = np.roll(self.cloud, -off, 1)[:, :self.w]
        fade = np.clip(np.linspace(0.2, 1.2, h), 0, 1)[:, None]          # thinner high up
        cov = np.clip((c - 0.61) * 7, 0, 1) * fade
        cov = np.where(cov > 0.5, np.where(cov > 0.85, 1.0, 0.7), np.where(cov > 0.2, 0.4, 0.0))   # stepped, like dithered pixel clouds
        lit = self.cloud_col * (0.75 + 0.35 * np.clip(1 - np.abs(np.arange(self.w) - self.bx) / self.w, 0, 1))[None, :, None]
        under = np.vstack([np.zeros((3, self.w)), cov[:-3]])            # each cloud is darker underneath, lit on top
        shade = np.where(cov - under > 0.1, 1.15, np.where(under - cov > 0.1, 0.8, 1.0))[..., None]
        s[:h] = s[:h] * (1 - cov[..., None] * 0.85) + lit * shade * cov[..., None] * 0.85
        for (x0, y0, ph) in self.birds:                                  # a flock crossing, wings on the hats
            x = x0 + t * 11; y = y0 + 2 * math.sin(t * 0.7 + ph)
            up = (int(t * 6 + ph * 3) % 2 == 0)
            for dx, dy in ((-2, -1 if up else 1), (-1, 0), (0, 0 if up else -0), (1, 0), (2, -1 if up else 1)):
                px, py = int(x + dx), int(y + dy)
                if 0 <= px < self.w and 0 <= py < self.h: s[py, px] = (24, 20, 30)
        if self.weather == 'rain' and E.get('big') is not None and 0 <= i - E['big'] < 5:
            s = s * 0.3 + np.array([210, 220, 255], np.float32) * 0.7      # lightning on the big bar line
        return s

    def light_world(self, rgb, solid, cv, i, E):
        """The world in this light, with the weather on it."""
        rgb[solid] *= np.array(self.light, np.float32)
        if self.weather == 'snow':                                       # snow settles on the tops as the clip goes on
            k = min(0.75, 0.2 + 0.7 * i / max(1, E['n']))
            top = solid & (cv.face == 1)
            rgb[top] = rgb[top] * (1 - k) + np.array([236, 242, 255], np.float32) * k * np.array(self.light, np.float32) ** 0.3
        if self.weather == 'rain':
            rgb[solid] *= 0.9
            if E.get('big') is not None and 0 <= i - E['big'] < 5: rgb[solid] = rgb[solid] * 1.5 + 30
            tops = np.argwhere(solid & (cv.face == 1))
            if len(tops):                                                # splashes
                r2 = np.random.default_rng(i)
                for y, x in tops[r2.choice(len(tops), min(len(tops), 70), replace=False)]: rgb[y, x] = rgb[y, x] * 0.4 + 150
        return rgb

    def front(self, rgb, i, E):
        """What falls in front of everything."""
        t = i / 30.0; d = self.drops
        if not len(d): return rgb
        if self.weather == 'rain':
            y = (d[:, 1] + t * 260 * d[:, 2]) % self.h; x = (d[:, 0] - t * 60 * d[:, 2]) % self.w
            for k in range(4):
                yy = (y - k * 2).astype(int) % self.h; xx = (x + k * 0.5).astype(int) % self.w
                rgb[yy, xx] = rgb[yy, xx] * 0.55 + np.array([170, 190, 230], np.float32) * 0.45 * (1 - k / 5)
        else:
            y = (d[:, 1] + t * 22 * d[:, 2]) % self.h; x = (d[:, 0] + 6 * np.sin(t * 1.3 * d[:, 2] + d[:, 3]) + t * 5) % self.w
            yy, xx = y.astype(int), x.astype(int)
            rgb[yy, xx] = rgb[yy, xx] * 0.2 + 225
            big = d[:, 2] > 1.15                                         # the near flakes are two pixels
            rgb[yy[big], (xx[big] + 1) % self.w] = rgb[yy[big], (xx[big] + 1) % self.w] * 0.3 + 200
        return rgb
