"""Landscapes drawn from shapes for the stare page (studio/stare_video.py): flat, bright, big areas of strong colour,
which is what makes a good afterimage. Each scene takes a seed, so no two pictures are the same.

    draw(name, w, h, seed) -> uint8 RGB array        SCENES[name] = (drawer, the scene's main colour)
"""
import math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 2                                       # drawn at twice the size and shrunk: smooth edges


def vgrad(d, w, y0, y1, c0, c1):
    for y in range(int(y0), int(y1)):
        u = (y - y0) / max(1, y1 - y0)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * u) for a, b in zip(c0, c1)))
    d.rectangle([0, int(y1), w, 10 ** 5], fill=tuple(c1))           # and below it, so no gap is ever left under a ridge


def ridge(r, w, base, amp, rough, n=60):
    ph = [r.uniform(0, 6.3) for _ in range(4)]
    pts = []
    for j in range(n + 1):
        x = w * j / n
        y = base - amp * (0.55 * math.sin(x / w * 3.1 + ph[0]) + 0.3 * math.sin(x / w * 7.3 + ph[1])
                          + rough * (0.15 * math.sin(x / w * 17 + ph[2]) + 0.08 * math.sin(x / w * 41 + ph[3])))
        pts.append((x, y))
    return pts


def hills(d, r, w, h, base, amp, col, rough=0.0):
    d.polygon(ridge(r, w, base, amp, rough) + [(w, h), (0, h)], fill=col)


def tree(d, x, y, s, trunk, crown):
    d.rectangle([x - s * 0.08, y - s * 0.5, x + s * 0.08, y], fill=trunk)
    d.ellipse([x - s * 0.42, y - s * 1.25, x + s * 0.42, y - s * 0.4], fill=crown)


def sunset(d, r, w, h):
    vgrad(d, w, 0, h * 0.62, (70, 30, 140), (255, 140, 40))
    sx = w * r.uniform(0.3, 0.7); d.ellipse([sx - w * 0.13, h * 0.42, sx + w * 0.13, h * 0.68], fill=(255, 220, 80))
    hills(d, r, w, h, h * 0.58, h * 0.16, (150, 40, 90), 1.0)
    hills(d, r, w, h, h * 0.62, h * 0.08, (90, 20, 80), 1.0)
    vgrad(d, w, h * 0.64, h, (255, 120, 60), (60, 20, 110))
    for j in range(9):                                                   # the sun's road on the water
        y = h * (0.67 + 0.035 * j); hw = w * (0.12 - 0.008 * j)
        d.rectangle([sx - hw, y, sx + hw, y + h * 0.008], fill=(255, 210, 90))


def beach(d, r, w, h):
    vgrad(d, w, 0, h * 0.5, (20, 120, 230), (130, 210, 255))
    d.ellipse([w * 0.72, h * 0.07, w * 0.9, h * 0.25], fill=(255, 245, 160))
    vgrad(d, w, h * 0.5, h * 0.7, (0, 150, 190), (40, 220, 200))
    d.polygon(ridge(r, w, h * 0.72, h * 0.02, 0.5) + [(w, h), (0, h)], fill=(250, 215, 120))
    for _ in range(2):                                                   # palms
        x = w * r.uniform(0.1, 0.9); y = h * r.uniform(0.82, 0.92); top = (x + r.uniform(-60, 60) * SS, y - h * 0.38)
        d.line([(x, y), top], fill=(120, 70, 30), width=int(16 * SS))
        for a in range(7):
            th = math.pi * (0.1 + 0.8 * a / 6)
            d.polygon([top, (top[0] + math.cos(th) * 200 * SS - 20, top[1] - math.sin(th) * 90 * SS + 60),
                       (top[0] + math.cos(th) * 200 * SS + 20, top[1] - math.sin(th) * 90 * SS + 90)], fill=(20, 150, 50))


def balloons(d, r, w, h):
    vgrad(d, w, 0, h * 0.7, (40, 110, 230), (170, 215, 255))
    hills(d, r, w, h, h * 0.72, h * 0.08, (60, 170, 60), 0.5)
    hills(d, r, w, h, h * 0.84, h * 0.06, (20, 120, 40), 0.5)
    cols = [(230, 40, 40), (255, 200, 0), (250, 120, 0), (200, 40, 160), (0, 170, 220)]
    for _ in range(r.randint(3, 5)):
        x = w * r.uniform(0.15, 0.85); y = h * r.uniform(0.15, 0.6); s = w * r.uniform(0.06, 0.13)
        c1, c2 = r.sample(cols, 2)
        d.ellipse([x - s, y - s * 1.15, x + s, y + s * 0.9], fill=c1)
        for k in (-0.5, 0.0, 0.5):
            d.ellipse([x + k * s - s * 0.18, y - s * 1.13, x + k * s + s * 0.18, y + s * 0.88], fill=c2)
        d.polygon([(x - s * 0.55, y + s * 0.7), (x + s * 0.55, y + s * 0.7), (x + s * 0.2, y + s * 1.25), (x - s * 0.2, y + s * 1.25)], fill=c1)
        d.rectangle([x - s * 0.2, y + s * 1.35, x + s * 0.2, y + s * 1.6], fill=(120, 70, 30))


def autumn(d, r, w, h):
    vgrad(d, w, 0, h * 0.6, (30, 110, 220), (150, 205, 250))
    hills(d, r, w, h, h * 0.62, h * 0.07, (110, 160, 60), 0.4)
    crowns = [(230, 60, 20), (250, 150, 0), (255, 200, 30), (200, 30, 30)]
    for row, (y0, s0) in enumerate([(0.66, 0.11), (0.78, 0.16), (0.95, 0.24)]):
        for _ in range(7 - row * 2):
            tree(d, w * r.uniform(0.02, 0.98), h * (y0 + r.uniform(-0.02, 0.02)), w * s0 * r.uniform(0.8, 1.2), (80, 45, 25), r.choice(crowns))


def tulips(d, r, w, h):
    vgrad(d, w, 0, h * 0.45, (30, 120, 235), (160, 210, 255))
    d.rectangle([0, h * 0.45, w, h], fill=(40, 140, 40))
    cols = [(235, 30, 50), (255, 210, 0), (240, 90, 170), (255, 120, 0), (150, 40, 190)]
    r.shuffle(cols); vx, vy = w * r.uniform(0.4, 0.6), h * 0.45
    k = 11
    for j in range(k):                                                   # stripes running to the horizon
        x0, x1 = -w * 0.6 + j * w * 2.2 / k, -w * 0.6 + (j + 0.62) * w * 2.2 / k
        d.polygon([(vx + (x0 - vx) * 0.02, vy), (vx + (x1 - vx) * 0.02, vy), (x1, h), (x0, h)], fill=cols[j % len(cols)])
    mx = w * r.choice([0.2, 0.8]); my = h * 0.45                         # a windmill on the horizon
    d.polygon([(mx - 30 * SS, my), (mx + 30 * SS, my), (mx + 18 * SS, my - 120 * SS), (mx - 18 * SS, my - 120 * SS)], fill=(110, 60, 40))
    for a in range(4):
        th = a * math.pi / 2 + 0.4
        d.line([(mx, my - 120 * SS), (mx + math.cos(th) * 110 * SS, my - 120 * SS + math.sin(th) * 110 * SS)], fill=(250, 245, 230), width=int(14 * SS))


def aurora(d, r, w, h):
    vgrad(d, w, 0, h * 0.75, (5, 10, 50), (20, 40, 110))
    for _ in range(120):
        x, y = r.uniform(0, w), r.uniform(0, h * 0.6); s = r.choice([1, 1, 2]) * SS
        d.ellipse([x - s, y - s, x + s, y + s], fill=(255, 255, 230))
    for band, col in enumerate([(40, 255, 140), (60, 230, 200), (210, 60, 255)]):
        base = h * (0.18 + 0.12 * band); ph = r.uniform(0, 6.3)
        for j in range(0, w, 3 * SS):
            y = base + h * 0.06 * math.sin(j / w * 5 + ph); hh = h * (0.12 + 0.05 * math.sin(j / w * 13 + ph))
            d.line([(j, y), (j, y + hh)], fill=col, width=3 * SS)
    hills(d, r, w, h, h * 0.75, h * 0.18, (235, 240, 255), 1.0)
    hills(d, r, w, h, h * 0.85, h * 0.07, (30, 50, 90), 0.6)


def desert(d, r, w, h):
    vgrad(d, w, 0, h * 0.55, (10, 60, 200), (90, 170, 255))
    d.ellipse([w * 0.15, h * 0.08, w * 0.3, h * 0.23], fill=(255, 250, 200))
    hills(d, r, w, h, h * 0.58, h * 0.1, (240, 140, 50), 0.3)
    hills(d, r, w, h, h * 0.7, h * 0.12, (220, 90, 30), 0.3)
    hills(d, r, w, h, h * 0.86, h * 0.1, (180, 60, 20), 0.3)
    x, y = w * r.uniform(0.6, 0.85), h * 0.8                             # a cactus
    for (a, b, c, e) in [(-0.02, -0.3, 0.02, 0), (-0.09, -0.2, -0.06, -0.1), (0.06, -0.24, 0.09, -0.14)]:
        d.rounded_rectangle([x + a * w, y + b * h, x + c * w, y + e * h], radius=12 * SS, fill=(30, 140, 60))
    d.rectangle([x - 0.09 * w, y - 0.12 * h, x + 0.0 * w, y - 0.1 * h], fill=(30, 140, 60))
    d.rectangle([x, y - 0.16 * h, x + 0.09 * w, y - 0.14 * h], fill=(30, 140, 60))


SCENES = {'sunset': (sunset, (240, 90, 40)), 'beach': (beach, (0, 150, 200)), 'balloons': (balloons, (220, 40, 40)),
          'autumn': (autumn, (230, 100, 0)), 'tulips': (tulips, (220, 30, 60)), 'aurora': (aurora, (20, 190, 110)),
          'desert': (desert, (220, 100, 30))}


def draw(name, w, h, seed):
    r = random.Random(seed)
    im = Image.new('RGB', (w * SS, h * SS)); d = ImageDraw.Draw(im)
    SCENES[name][0](d, r, w * SS, h * SS)
    im = im.filter(ImageFilter.GaussianBlur(1.2 * SS)).resize((w, h), Image.LANCZOS)   # soft edges: afterimages are blurry anyway
    return np.asarray(im)
