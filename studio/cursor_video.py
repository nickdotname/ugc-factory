#!/usr/bin/env python3
"""The band, rebuilt out of mouse cursors, dancing through a 3D Windows 98 world.

    python studio/cursor_video.py SONG_DIR SEED OUT.mp4            (CQ_WINDOW="t0,t1": the stretch to play)
    python studio/cursor_video.py SONG_DIR SEED SHEET.png --frames 0,60,120

The figure is one of the band's dance cut-outs (studio/lofi/index.json, studio/lofi_lib.py) sampled on a grid, every
sample drawn as a cursor (arrow, hand or hourglass), so a person made of a few hundred cursors moves the way they
danced; where the song has footage of its own the figure is in sync with it, elsewhere any clip is used. Around it,
textured planes projected with a pinhole camera make one of three worlds:

  stairs    a staircase whose risers are Win98 title bars, the song's lines running up the walls
  corridor  a floor of tiled windows, icons drifting past, a glowing doorway at the end
  cube      a turning cube of MS Paint windows with bright polygons sparking inside it on the beat

The lyric lines pop up as error dialogs, cascading. Knobs: world, glow (the doorway's colour), cursor (the sprite
mix), drift (how fast the camera moves)."""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import knobs as K
import lofi_lib as LIB

W, H, FPS = 1080, 1920, 30
RW, RH = 720, 1280                                  # drawn at this size and scaled up: soft, like an old render
FOC = RH * 0.95


def _font(*names):
    for name in names:
        for root in ('/usr/share/fonts', os.path.join(REPO, 'fonts')):
            for base, _, files in os.walk(root):
                if name in files: return os.path.join(base, name)
    sys.exit('no font: ' + ', '.join(names))
SANS_B = _font('LiberationSans-Bold.ttf', 'DejaVuSans-Bold.ttf'); SANS = _font('LiberationSans-Regular.ttf', 'DejaVuSans.ttf')
SERIF_B = _font('LiberationSerif-Bold.ttf', 'DejaVuSerif-Bold.ttf', 'LiberationSans-Bold.ttf')
_F = {}
def F(p, s):
    if (p, s) not in _F: _F[(p, s)] = ImageFont.truetype(p, s)
    return _F[(p, s)]

SONG_DIR = sys.argv[1] if len(sys.argv) > 1 else ''
SLUG = os.path.basename(os.path.normpath(SONG_DIR))
SONG = json.load(open(os.path.join(SONG_DIR, 'song.json'))) if SONG_DIR else {}
BEATS = np.array(SONG.get('beat_times') or [0.0])
MASTER = next((os.path.join(SONG_DIR, 'master' + e) for e in ('.ogg', '.flac', '.wav') if os.path.exists(os.path.join(SONG_DIR, 'master' + e))), '')
_OWN = os.path.join(HERE, 'lofi', 'lines', SLUG + '.json'); _LP = _OWN if os.path.exists(_OWN) else os.path.join(SONG_DIR, 'lines.json')
LINES = json.load(open(_LP)) if SONG_DIR and os.path.exists(_LP) else []
SHOW_LYRICS = (os.environ.get('CQ_LYRICS') != 'none' or _LP == _OWN) and bool(LINES)
TITLE = SONG.get('title', SLUG)

def kick(T):
    b = np.searchsorted(BEATS, T); return math.exp(-max(0.0, T - BEATS[max(0, b - 1)]) * 7)

# ------------------------------------------------------------------ textures
def titlebar(text, w=640, h=64, active=True):
    im = Image.new('RGB', (w, h), (192, 192, 192)); d = ImageDraw.Draw(im)
    for k in range(64):
        c = tuple(int(a + (b - a) * k / 63) for a, b in zip((0, 0, 128), (16, 132, 208)) if active) if active else (128, 128, 128)
        d.rectangle([4 + (w - 8) * k / 64, 4, 4 + (w - 8) * (k + 1) / 64, h - 4], fill=c)
    d.text((16, h * 0.18), text, font=F(SERIF_B, int(h * 0.55)), fill=(255, 255, 255))
    bx = w - h + 6; d.rectangle([bx, 10, bx + h - 18, h - 10], fill=(192, 192, 192), outline=(0, 0, 0))
    d.line([bx + 8, 18, bx + h - 26, h - 18], fill=(0, 0, 0), width=4); d.line([bx + h - 26, 18, bx + 8, h - 18], fill=(0, 0, 0), width=4)
    return np.asarray(im)

def window_tex(title, w=420, h=320, paint=False, seed=0):
    im = Image.new('RGB', (w, h), (192, 192, 192)); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], outline=(255, 255, 255), width=3)
    im.paste(Image.fromarray(titlebar(title, w - 8, 34)), (4, 4))
    if paint:
        x = 6
        for m in ('File', 'Edit', 'View', 'Image', 'Options', 'Help'):
            d.text((x, 42), m, font=F(SANS, 15), fill=(0, 0, 0)); x += d.textlength(m, font=F(SANS, 15)) + 12
        d.rectangle([6, 64, 52, h - 40], fill=(200, 200, 200), outline=(128, 128, 128))
        for k in range(16): d.rectangle([10 + (k % 2) * 20, 70 + (k // 2) * 22, 26 + (k % 2) * 20, 86 + (k // 2) * 22], outline=(90, 90, 90))
        d.rectangle([58, 64, w - 10, h - 40], fill=(1, 2, 3))     # the canvas: see-through (alpha 0 below)
        r = random.Random(seed)
        for k in range(28): d.rectangle([8 + k * 14, h - 32, 20 + k * 14, h - 20], fill=tuple(r.randrange(256) for _ in range(3)), outline=(0, 0, 0))
        a = np.asarray(im).copy(); alpha = np.where((a == (1, 2, 3)).all(-1), 0, 255).astype(np.uint8)
        return np.dstack([a, alpha])
    else:
        d.rectangle([12, 52, w - 12, h - 52], fill=(255, 255, 255), outline=(128, 128, 128))
        r = random.Random(seed)
        for k in range(6): d.rectangle([24, 66 + k * 26, 24 + r.randrange(80, w - 60), 76 + k * 26], fill=(200, 200, 210))
        d.rectangle([w - 110, h - 44, w - 20, h - 14], fill=(192, 192, 192), outline=(0, 0, 0)); d.text((w - 82, h - 40), 'OK', font=F(SANS_B, 18), fill=(0, 0, 0))
    return np.asarray(im)

def text_strip(text, h=48, w=1400, fg=(70, 70, 70), bg=(232, 232, 232)):
    im = Image.new('RGB', (w, h), bg); d = ImageDraw.Draw(im); x = 10
    while x < w: d.text((x, 6), text, font=F(SANS, int(h * 0.62)), fill=fg); x += d.textlength(text + '   ', font=F(SANS, int(h * 0.62)))
    return np.asarray(im)

# ------------------------------------------------------------------ the camera
class Cam:
    def __init__(self, pos, pitch=0.0, yaw=0.0): self.p = np.array(pos, np.float32); self.pitch = pitch; self.yaw = yaw
    def view(self, P):
        P = np.asarray(P, np.float32) - self.p
        cy, sy = math.cos(self.yaw), math.sin(self.yaw); x = P[..., 0] * cy - P[..., 2] * sy; z = P[..., 0] * sy + P[..., 2] * cy
        cp, sp = math.cos(self.pitch), math.sin(self.pitch); y = P[..., 1] * cp - z * sp; z2 = P[..., 1] * sp + z * cp
        return np.stack([x, y, z2], -1)
    def project(self, V):
        z = np.maximum(V[..., 2], 1e-3)
        return np.stack([RW / 2 + FOC * V[..., 0] / z, RH / 2 - FOC * V[..., 1] / z], -1)

def quad(canvas, cam, corners, tex, shade=1.0):
    """Texture `tex` onto the 3D quad corners (tl, tr, br, bl), clipped to what is in front of the camera."""
    V = cam.view(corners)
    if (V[:, 2] < 0.05).any(): return
    S = cam.project(V).astype(np.float32)
    x0, y0 = S.min(0); x1, y1 = S.max(0)
    if x1 < 0 or y1 < 0 or x0 > RW or y0 > RH or (x1 - x0) * (y1 - y0) < 4: return
    h, w = tex.shape[:2]
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), S)
    rgb = tex[..., :3]; alpha = tex[..., 3] if tex.shape[2] == 4 else np.full((h, w), 255, np.uint8)
    warped = cv2.warpPerspective(np.ascontiguousarray(rgb), M, (RW, RH), flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.ascontiguousarray(alpha), M, (RW, RH), flags=cv2.INTER_NEAREST)
    m = mask > 127
    canvas[m] = (warped[m].astype(np.float32) * shade).astype(np.uint8)

# ------------------------------------------------------------------ the figure, in cursors
def sprite(kind, s):
    """A cursor sprite (RGBA) about s pixels tall."""
    im = Image.new('RGBA', (int(s * 0.8) + 4, s + 4), (0, 0, 0, 0)); d = ImageDraw.Draw(im); u = s / 19
    if kind == 'arrow':
        pts = [(0, 0), (0, 16), (4, 12), (7, 18), (9, 17), (6, 11), (11, 11)]
        d.polygon([(2 + x * u, 2 + y * u) for x, y in pts], fill=(255, 255, 255), outline=(0, 0, 0))
    elif kind == 'hand':
        d.rounded_rectangle([2 + 3 * u, 2, 2 + 6 * u, 2 + 10 * u], radius=u, fill=(255, 255, 255), outline=(0, 0, 0))
        d.rounded_rectangle([2, 2 + 8 * u, 2 + 13 * u, 2 + 18 * u], radius=2 * u, fill=(255, 255, 255), outline=(0, 0, 0))
    else:
        d.polygon([(2 + u, 2), (2 + 11 * u, 2), (2 + 6 * u, 2 + 9 * u)], fill=(255, 255, 255), outline=(0, 0, 0))
        d.polygon([(2 + 6 * u, 2 + 9 * u), (2 + 11 * u, 2 + 18 * u), (2 + u, 2 + 18 * u)], fill=(255, 255, 255), outline=(0, 0, 0))
        d.line([(2 + u, 2), (2 + 11 * u, 2)], fill=(0, 0, 0), width=max(1, int(u))); d.line([(2 + u, 2 + 18 * u), (2 + 11 * u, 2 + 18 * u)], fill=(0, 0, 0), width=max(1, int(u)))
    return im
_SPR = {}
def spr(kind, s):
    s = max(6, int(s));
    if (kind, s) not in _SPR: _SPR[(kind, s)] = sprite(kind, s)
    return _SPR[(kind, s)]

CLIPS = []
def cutout(T, t):
    """The dance cut-out for this moment: the song's own footage at T if there is any, else a clip looped by time."""
    own = [c for c in CLIPS if c['song'] == SLUG and c['offset'] <= T <= c['offset'] + (c['frames'] - 1) / c['fps']]
    if own:
        c = own[0]; k = int((T - c['offset']) * c['fps']) + 1
    else:
        c = CLIPS[int(t // 8) % len(CLIPS)] if CLIPS else None
        if c is None: return None
        k = int((t * c['fps']) % max(1, c['frames'] - 1)) + 1
    try: return LIB.frame(c['id'], k)
    except Exception as exc:                                   # a clip whose cut-outs cannot be fetched: leave it out
        print('no cut-outs for %s: %r' % (c['id'], exc)); CLIPS.remove(c); return None

def figure(img, T, t, cx, base, height, mix, rng_seed):
    """The cut-out as a crowd of cursors: cx, base = where its feet are on screen, height in pixels."""
    p = cutout(T, t)
    if p is None or height < 30: return
    a = np.asarray(p.getchannel('A'))
    ys, xs = np.nonzero(a > 128)
    if len(ys) == 0: return
    top = ys.min(); s = height / (a.shape[0] - top)
    step = max(3, int(11 / max(0.4, s)))                      # sample spacing in the cut-out, so the cursors overlap a little
    g = a[top::step, ::step] > 128
    gy, gx = np.nonzero(g)
    r = random.Random(rng_seed + int(t * 10))
    size = max(7, step * s * 1.8)
    pil = Image.fromarray(img)
    for y, x in zip(gy, gx):
        jx, jy = r.uniform(-0.35, 0.35) * step * s, r.uniform(-0.35, 0.35) * step * s
        sx = cx + (x * step - a.shape[1] / 2) * s + jx; sy = base - height + y * step * s + jy
        k = r.choices(['arrow', 'hand', 'hourglass'], weights=mix)[0]
        im = spr(k, size * r.uniform(0.85, 1.15)); pil.paste(im, (int(sx - im.width / 2), int(sy - im.height / 2)), im)
    img[:] = np.asarray(pil.convert('RGB'))

# ------------------------------------------------------------------ worlds
_TEX = {}
def tex(key, fn):
    if key not in _TEX: _TEX[key] = fn()
    return _TEX[key]

def world_stairs(T, t, st):
    img = np.full((RH, RW, 3), 236, np.uint8)
    speed = 0.35 * st['drift']; step_h, step_d, wid = 0.32, 0.7, 3.2
    climb = t * speed; cam = Cam((0, 1.1 + climb * step_h / step_d, -5.5 + climb), pitch=-0.3)
    first = int(climb) - 2
    line = next((' '.join(w for w, _ in ws) for e, ws in LINES if ws[0][1] <= T < e + 0.5), TITLE) if SHOW_LYRICS else TITLE
    wall = tex(('wall', line), lambda: text_strip(line))
    strip = np.rot90(wall).copy()
    for side in (-1, 1):                                      # the song's lines run up the walls
        for k in range(10):
            x = side * wid / 2; z0 = first * step_d + k * 1.4; near, far = (z0, z0 + 1.4) if side < 0 else (z0 + 1.4, z0)
            quad(img, cam, [(x, 7, near), (x, 7, far), (x, -1, far), (x, -1, near)], strip, 0.95)
    bar = tex(('bar', TITLE), lambda: titlebar(TITLE + '.exe', 900, 64))
    for i in range(first + 18, first - 1, -1):                # far to near, so near steps cover far ones
        y0, z0 = i * step_h, i * step_d
        quad(img, cam, [(-wid / 2, y0 + step_h, z0), (wid / 2, y0 + step_h, z0), (wid / 2, y0, z0), (-wid / 2, y0, z0)], bar)
        quad(img, cam, [(-wid / 2, y0 + step_h, z0 + step_d), (wid / 2, y0 + step_h, z0 + step_d), (wid / 2, y0 + step_h, z0), (-wid / 2, y0 + step_h, z0)],
             tex('tread', lambda: np.full((32, 32, 3), 214, np.uint8)), 1.0)
    i = first + 6; fy, fz = (i + 1) * step_h, i * step_d + step_d * 0.5
    V = cam.view([(0, fy, fz), (0, fy + 1.75, fz)]); S = cam.project(V)
    figure(img, T, t, S[0][0], S[0][1], S[0][1] - S[1][1], st['mix'], 1)
    return img

def world_corridor(T, t, st):
    img = np.zeros((RH, RW, 3), np.uint8)
    yy = np.linspace(0, 1, RH)[:, None, None]; img[:] = (np.array([0, 18, 6]) * (1 - yy) + np.array([0, 40, 12]) * yy).astype(np.uint8)
    cam = Cam((0, 1.4, t * 0.6 * st['drift']), pitch=-0.12)
    z_cam = cam.p[2]; door_z = z_cam + 14
    glow = np.array(st['glow'], np.float32); D = cam.project(cam.view([(-0.7, 2.4, door_z), (0.7, 0, door_z)]))
    (dx0, dy0), (dx1, dy1) = D; cxy = ((dx0 + dx1) / 2, (dy0 + dy1) / 2)
    gy_, gx_ = np.mgrid[0:RH, 0:RW].astype(np.float32)
    dist = np.maximum(np.maximum(np.abs(gx_ - cxy[0]) - abs(dx1 - dx0) / 2, 0), np.maximum(np.abs(gy_ - cxy[1]) - abs(dy1 - dy0) / 2, 0))
    img[:] = np.clip(img + glow * np.exp(-dist / (40 + 30 * kick(T)))[..., None] * 0.9, 0, 255).astype(np.uint8)
    cv2.rectangle(img, (int(dx0), int(dy0)), (int(dx1), int(dy1)), (0, 0, 0), -1)
    k0 = int(z_cam // 1.6) - 1
    for k in range(k0 + 12, k0, -1):                           # the floor: windows lying flat, tiled
        for col in range(-2, 2):
            z = k * 1.6; x = col * 1.7
            quad(img, cam, [(x, 0, z + 1.6), (x + 1.7, 0, z + 1.6), (x + 1.7, 0, z), (x, 0, z)], tex(('floorwin', (k + col) % 4), lambda: window_tex(TITLE + ' - Notepad', seed=(k + col) % 4)), 0.9)
    r = random.Random(3)
    for n in range(40):                                        # icons drifting in the dark on both sides
        side = -1 if n % 2 else 1; x = side * r.uniform(1.8, 5); y = r.uniform(0.5, 5); z = (r.uniform(0, 30) - t * (0.8 + r.random())) % 30 + z_cam + 1
        V = cam.view([(x, y, z)])[0]
        if V[2] < 0.3: continue
        sx, sy = cam.project(V); s = int(FOC * 0.35 / V[2])
        if 4 < s < 200 and 0 < sx < RW and 0 < sy < RH:
            c = tuple(int(v) for v in r.choice([(250, 250, 250), (240, 220, 90), (90, 200, 120), (120, 160, 240)]))
            cv2.rectangle(img, (int(sx - s / 2), int(sy - s / 2)), (int(sx + s / 2), int(sy + s / 2)), c, -1)
            cv2.rectangle(img, (int(sx - s / 2), int(sy - s / 2)), (int(sx + s / 2), int(sy + s / 2)), (0, 0, 0), max(1, s // 12))
    fz = z_cam + 4.2; S = cam.project(cam.view([(0, 0, fz), (0, 1.75, fz)]))
    figure(img, T, t, S[0][0], S[0][1], S[0][1] - S[1][1], st['mix'], 2)
    return img

def world_cube(T, t, st):
    img = np.zeros((RH, RW, 3), np.uint8)
    cam = Cam((0, 0.35, -6.0), pitch=0.0); ang = t * 0.35 * st['drift'] + 0.5
    def rot(p):
        x, y, z = p; c, s = math.cos(ang), math.sin(ang); return (x * c - z * s, y, x * s + z * c)
    faces = []
    for k in range(4):                                         # four Paint windows standing round a square
        a0 = k * math.pi / 2
        p0 = (math.cos(a0) * 1.25 - math.sin(a0) * 1.25, 1.25, math.sin(a0) * 1.25 + math.cos(a0) * 1.25)
        p1 = (math.cos(a0) * -1.25 - math.sin(a0) * 1.25, 1.25, math.sin(a0) * -1.25 + math.cos(a0) * 1.25)
        cs = [rot(p0), rot(p1), rot((p1[0], -1.25, p1[2])), rot((p0[0], -1.25, p0[2]))]
        faces.append((np.mean([cam.view([c])[0][2] for c in cs]), cs, k))
    faces.sort(key=lambda f: -f[0])
    r = random.Random(int(T * 2)); bump = kick(T)
    for n, (z, cs, k) in enumerate(faces):
        if n == 2:                                             # the sparks inside, drawn between the back and the front walls
            for q in range(14):
                pts = [rot((r.uniform(-1, 1) * (0.6 + bump), r.uniform(-1, 1) * (0.6 + bump), r.uniform(-1, 1) * 0.6)) for _ in range(3)]
                S = cam.project(cam.view(pts)).astype(np.int32)
                col = r.choice([(255, 0, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0), (255, 60, 60), (255, 255, 255)])
                if r.random() < 0.6: cv2.fillPoly(img, [S], col)
                cv2.polylines(img, [S], True, (255, 255, 255), 1, cv2.LINE_AA)
            S = cam.project(cam.view([(0, -1.25, 0), (0, 0.9, 0)]))
            figure(img, T, t, S[0][0], S[0][1], S[0][1] - S[1][1], st['mix'], 3)
        quad(img, cam, cs, tex(('paint', k), lambda: window_tex('Plexus', 460, 460, paint=True, seed=k)), 1.0 if n >= 2 else 0.8)
    return img

WORLDS = {'stairs': world_stairs, 'corridor': world_corridor, 'cube': world_cube}

# ------------------------------------------------------------------ lyric dialogs
def dialogs(pil, T):
    if not SHOW_LYRICS: return
    shown = [(ws[0][1], ' '.join(w for w, _ in ws)) for e, ws in LINES if ws[0][1] <= T < e + 2.0][-3:]
    d = ImageDraw.Draw(pil)
    for n, (t0, text) in enumerate(shown):
        x0, y0 = 90 + n * 40, 1180 + n * 46; w = 900 - n * 0
        f = F(SANS, 34); words, rows, cur = text.split(), [], ''
        for wd in words:
            c = (cur + ' ' + wd).strip()
            if d.textlength(c, font=f) < w - 170 or not cur: cur = c
            else: rows.append(cur); cur = wd
        rows.append(cur); h = 120 + 44 * len(rows[:3])
        pop = min(1.0, (T - t0) / 0.08)
        if pop < 1: continue
        d.rectangle([x0, y0, x0 + w, y0 + h], fill=(192, 192, 192), outline=(0, 0, 0), width=2)
        d.line([x0 + 2, y0 + 2, x0 + w - 2, y0 + 2], fill=(255, 255, 255), width=2); d.line([x0 + 2, y0 + 2, x0 + 2, y0 + h - 2], fill=(255, 255, 255), width=2)
        pil.paste(Image.fromarray(titlebar(TITLE, w - 8, 44)), (x0 + 4, y0 + 4))
        d.ellipse([x0 + 30, y0 + 70, x0 + 90, y0 + 130], fill=(220, 0, 0), outline=(0, 0, 0), width=2)
        d.line([x0 + 46, y0 + 86, x0 + 74, y0 + 114], fill=(255, 255, 255), width=6); d.line([x0 + 74, y0 + 86, x0 + 46, y0 + 114], fill=(255, 255, 255), width=6)
        for k, row in enumerate(rows[:3]): d.text((x0 + 120, y0 + 66 + k * 44), row, font=f, fill=(0, 0, 0))

# ------------------------------------------------------------------ the edit
def bars(T0, T1, every=2):
    downs = [b for i, b in enumerate(BEATS) if i % 4 == 0]
    return [b for j, b in enumerate(downs) if j % every == 0 and T0 + 1.0 < b < T1 - 0.5]

def frame(i, T0, st, plan):
    T = T0 + i / FPS; t = i / FPS
    w = next((p for p in plan if p[0] <= T < p[1]), plan[-1])
    img = WORLDS[w[2]](T, t - (w[0] - T0) + w[3], st)
    big = Image.fromarray(cv2.resize(img, (W, H), interpolation=cv2.INTER_LINEAR)).convert('RGBA')
    dialogs(big, T)
    return np.asarray(big.convert('RGB'))

def main():
    seed, out = int(sys.argv[2]), sys.argv[3]
    CLIPS.extend(LIB.index()['clips'])
    w = os.environ.get('CQ_WINDOW'); T0, T1 = (float(x) for x in w.split(',')) if w else (60.0, 80.0)
    r = random.Random(seed)
    lead = K.pick('world', ['stairs', 'corridor', 'cube', 'mix'], r, weights=[1, 1, 1, 2])
    st = dict(glow=dict(green=(40, 255, 90), purple=(190, 60, 255), red=(255, 50, 40))[K.pick('glow', ['green', 'purple', 'red'], r)],
              mix={'arrows': [6, 2, 1], 'mixed': [3, 3, 2], 'busy': [2, 2, 4]}[K.pick('cursor', ['arrows', 'mixed', 'busy'], r)],
              drift=float(K.pick('drift', [0.6, 1.0, 1.6], r)))
    cuts = [T0] + bars(T0, T1) + [T1]; plan = []
    order = [lead] * (len(cuts) - 1) if lead != 'mix' else [r.choice(list(WORLDS)) for _ in cuts[1:]]
    for k, (a, b) in enumerate(zip(cuts, cuts[1:])):
        if lead == 'mix' and k and order[k] == order[k - 1]: order[k] = r.choice([x for x in WORLDS if x != order[k - 1]])
        plan.append((a, b, order[k], r.uniform(0, 20)))
    if '--frames' in sys.argv:
        fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
        ims = [Image.fromarray(frame(f, T0, st, plan)).resize((360, 640)) for f in fs]
        sheet = Image.new('RGB', (360 * len(ims), 640))
        for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
        sheet.save(out); print('sheet', out, K.record()['knobs'], [p[2] for p in plan]); return
    tmp = out[:-4] + '.part.mp4'; n = int((T1 - T0) * FPS)
    p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                          '-ss', '%.3f' % T0, '-t', '%.3f' % (T1 - T0), '-i', MASTER, '-af', 'afade=t=in:d=0.04,afade=t=out:st=%.2f:d=0.5' % max(0, T1 - T0 - 0.5),
                          '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                          '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(frame(i, T0, st, plan).tobytes())
        if i % 90 == 0: print(i, '/', n, flush=True)
    p.stdin.close(); p.wait()
    if p.returncode: sys.exit('encode failed')
    os.replace(tmp, out)
    json.dump(dict(K.record(), plan=dict(hook='', worlds=[q[2] for q in plan])), open(out[:-4] + '.json', 'w')); print('done', out)


if __name__ == '__main__':
    main()
