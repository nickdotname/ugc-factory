#!/usr/bin/env python3
"""Builds studio/reveal/shapes.json: one closed outline per country for the reveal page (studio/reveal_video.py).

Source: Natural Earth 1:110m Admin 0 countries (public domain, naturalearthdata.com), as bundled in the
geopandas 0.14 wheel (geopandas/datasets/naturalearth_lowres). Run once by hand:
    pip download --no-deps geopandas==0.14.4 && unzip geopandas-*.whl 'geopandas/datasets/*'
    pip install pyshp && python studio/reveal/build_shapes.py geopandas/datasets/naturalearth_lowres/naturalearth_lowres.shp
Each country's largest landmass is kept (projected at its own latitude so it is not stretched), y up, centred,
scaled so its longer side is 1. Disputed-border countries are left out on purpose.
"""
import json, math, os, sys
import numpy as np, shapefile

# name in Natural Earth -> what the video calls it
KEEP = {'United States of America': 'the USA', 'Brazil': 'Brazil', 'Australia': 'Australia', 'Mexico': 'Mexico',
        'Italy': 'Italy', 'Japan': 'Japan', 'United Kingdom': 'Great Britain', 'France': 'France', 'Spain': 'Spain',
        'Germany': 'Germany', 'Egypt': 'Egypt', 'South Africa': 'South Africa', 'Madagascar': 'Madagascar',
        'Iceland': 'Iceland', 'Turkey': 'Turkey', 'Norway': 'Norway', 'Sweden': 'Sweden', 'Argentina': 'Argentina',
        'Greenland': 'Greenland', 'Vietnam': 'Vietnam', 'Thailand': 'Thailand', 'Peru': 'Peru', 'Mongolia': 'Mongolia',
        'Ireland': 'Ireland', 'New Zealand': 'New Zealand', 'Cuba': 'Cuba', 'Sri Lanka': 'Sri Lanka',
        'Portugal': 'Portugal', 'Greece': 'Greece', 'Chile': 'Chile', 'Canada': 'Canada', 'Finland': 'Finland',
        'Poland': 'Poland', 'Colombia': 'Colombia', 'Saudi Arabia': 'Saudi Arabia', 'Libya': 'Libya',
        'Somalia': 'Somalia', 'Nigeria': 'Nigeria', 'Kenya': 'Kenya', 'Bolivia': 'Bolivia', 'Venezuela': 'Venezuela',
        'Iran': 'Iran', 'Philippines': None, 'Malaysia': None}


def main(shp):
    r = shapefile.Reader(shp); f = [x[0] for x in r.fields[1:]]; out = {}
    for sr in r.shapeRecords():
        rec = dict(zip(f, sr.record)); name = KEEP.get(rec['name'])
        if not name: continue
        s = sr.shape; parts = list(s.parts) + [len(s.points)]; best = None
        for a, b in zip(parts[:-1], parts[1:]):
            p = np.array(s.points[a:b], float); lat0 = p[:, 1].mean()
            q = np.c_[p[:, 0] * math.cos(math.radians(lat0)), p[:, 1]]
            area = 0.5 * abs(np.sum(q[:, 0] * np.roll(q[:, 1], -1) - np.roll(q[:, 0], -1) * q[:, 1]))
            if best is None or area > best[0]: best = (area, q)
        q = best[1]
        if np.allclose(q[0], q[-1]): q = q[:-1]
        if rec['name'] == 'New Zealand':          # the largest part is the South Island; the name says which
            name = 'New Zealand (South Island)'
        q = q - (q.max(0) + q.min(0)) / 2; q = q / (q.max(0) - q.min(0)).max()
        out[name] = {'kind': 'country', 'pts': [[round(x, 4), round(y, 4)] for x, y in q]}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shapes.json')
    json.dump({'source': 'Natural Earth 1:110m Admin 0 (public domain)', 'shapes': out}, open(path, 'w'), separators=(',', ':'))
    print(len(out), 'shapes ->', path)


if __name__ == '__main__':
    main(sys.argv[1])
