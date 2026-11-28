#!/usr/bin/env python3
"""Impossible objects that are real: built in 3D, shown from the one angle where they close, then turned on the beat
(a ready page: one.angle.only, paused until its Instagram account exists; see docs/brain/ready-pages.md).

    python studio/angle_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/angle_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

Every object is a real solid made of boxes, drawn by a small z-buffer renderer in this file (orthographic camera,
flat light, no footage). Each is a path of square beams along the x, y and z axes whose end lies exactly on the line
of sight through its start: from the view along (1, 1, 1) the far start and the near end land on the same spot, so the
path looks closed and impossible. The near end block is cut along two planes that contain the line of sight (the way
the real Penrose-triangle sculptures are cut), so from the magic angle it shows exactly what a true corner would.
  triangle  three beams (x, y, z): the Penrose triangle
  cubes     the same path as a chain of separate cubes (Reutersvard's version)
Orient (six ways: three turns of the picture, each mirrored) and size (beam length in beam widths) vary the look.
The question holds while a bar fills, then on the beat the camera swings round and the gap opens (the distance
between the two ends is computed from the model, in beam widths), holds, swings back and the shape closes again.
Choreographed in beats; a stretch too short exits 3. The last 9 frames fade into frame 0.
Knobs (studio/knobs.py): kind, orient (a-f), palette (clay, slate, mint, sand), turn (left / right), size.
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
MAX_LEN = 24.0
SS = 2                                     # supersampling for the solid (edges stay clean without outlines)

PALETTES = {   # ground (top, bottom), the solid's colour, text
    'clay':  dict(bg=((236, 230, 220), (214, 206, 194)), body=(214, 118, 74), txt=(36, 32, 30)),
    'slate': dict(bg=((34, 38, 46), (18, 20, 26)), body=(150, 170, 196), txt=(236, 238, 242)),
    'mint':  dict(bg=((226, 238, 232), (196, 218, 208)), body=(70, 150, 132), txt=(24, 40, 36)),
    'sand':  dict(bg=((246, 236, 214), (226, 210, 180)), body=(64, 92, 160), txt=(30, 30, 44)),
}
ASK = {'triangle': ['can this be built?', 'could you make\nthis triangle?', 'is this shape possible?'],
       'cubes': ['can these cubes\nbe stacked like this?', 'is this possible?', 'could you build this?']}
TURNED = 'it was never closed.'
BACK = 'it only closes\nfrom this one angle.'

AX = np.eye(3)


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)


# ---------------------------------------------------------------- solids
def box_faces(lo, hi):
    """The six faces of an axis-aligned box, each (vertices, outward normal), vertices counter-clockwise outside."""
    x0, y0, z0 = lo; x1, y1, z1 = hi
    v = lambda x, y, z: np.array([x, y, z], float)
    return [([v(x1, y0, z0), v(x1, y1, z0), v(x1, y1, z1), v(x1, y0, z1)], AX[0]),
            ([v(x0, y0, z0), v(x0, y0, z1), v(x0, y1, z1), v(x0, y1, z0)], -AX[0]),
            ([v(x0, y1, z0), v(x0, y1, z1), v(x1, y1, z1), v(x1, y1, z0)], AX[1]),
            ([v(x0, y0, z0), v(x1, y0, z0), v(x1, y0, z1), v(x0, y0, z1)], -AX[1]),
            ([v(x0, y0, z1), v(x1, y0, z1), v(x1, y1, z1), v(x0, y1, z1)], AX[2]),
            ([v(x0, y0, z0), v(x0, y1, z0), v(x1, y1, z0), v(x1, y0, z0)], -AX[2])]


def clip(faces, n, d):
    """A convex solid cut to the half-space n.p <= d: faces clipped, plus the cap the cut leaves."""
    out, cut = [], []
    for vs, nrm in faces:
        res = []
        for k in range(len(vs)):
            a, b = vs[k], vs[(k + 1) % len(vs)]
            da, db = n @ a - d, n @ b - d
            if da <= 1e-9: res.append(a)
            if (da < -1e-9 and db > 1e-9) or (da > 1e-9 and db < -1e-9):
                q = a + (b - a) * (da / (da - db)); res.append(q); cut.append(q)
            elif abs(da) <= 1e-9: cut.append(a)
        if len(res) >= 3: out.append((res, nrm))
    if len(cut) >= 3:
        c = np.mean(cut, 0); nn = n / np.linalg.norm(n)
        u = np.cross(nn, AX[0] if abs(nn[0]) < .9 else AX[1]); u /= np.linalg.norm(u); w = np.cross(nn, u)
        cut = sorted(cut, key=lambda p: math.atan2((p - c) @ w, (p - c) @ u))
        uniq = [p for k, p in enumerate(cut) if np.linalg.norm(p - cut[k - 1]) > 1e-7]
        if len(uniq) >= 3:
            if np.cross(uniq[1] - uniq[0], uniq[2] - uniq[0]) @ nn < 0: uniq = uniq[::-1]
            out.append((uniq, nn))
    return out


V0 = np.ones(3) / math.sqrt(3)              # the magic line of sight (object to eye)
UP = AX[2] - (AX[2] @ V0) * V0; UP /= np.linalg.norm(UP)
RIGHT = np.cross(UP, V0)
RIGHT_0, UP_0 = RIGHT, UP


def _flat(pts):
    """Where points land seen along V0 (the magic view), as 2D float32 for cv2."""
    pts = np.asarray(pts, float)
    return np.c_[pts @ RIGHT_0, pts @ UP_0].astype(np.float32)


def behind(solid, box):
    """`solid` (near) minus the prism that `box` (far, but in front in the picture) sweeps along V0: the part of the
    near piece the eye should not see because the far beam passes in front of it from the magic angle. The cut
    planes all contain V0, so from that angle they are edge-on, which is how the real Penrose sculptures are cut.
    Returns convex pieces (they may overlap; the z-buffer does not mind)."""
    sv = [p for vs, _ in solid for p in vs]
    lo, hi = box
    bv = [np.array([x, y, z]) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    h1 = cv2.convexHull(_flat(sv)).reshape(-1, 2); h2 = cv2.convexHull(_flat(bv)).reshape(-1, 2)
    area, _ = cv2.intersectConvexConvex(h1, h2)
    if area < 1e-6: return [solid]
    h = h2.astype(float); m = h.mean(0); pieces = []
    for k in range(len(h)):
        a, b = h[k], h[(k + 1) % len(h)]
        e = b - a; n2 = np.array([e[1], -e[0]])
        if n2 @ (m - a) > 0: n2 = -n2                          # outward
        n3 = n2[0] * RIGHT_0 + n2[1] * UP_0; d = n2 @ a
        piece = clip(solid, -n3, -d)                           # keep n3.p >= d: outside this side of the prism
        if len(piece) >= 4: pieces.append(piece)
    return pieces


ORIENT = {'a': (0, 1, 2), 'b': (1, 2, 0), 'c': (2, 0, 1), 'd': (1, 0, 2), 'e': (0, 2, 1), 'f': (2, 1, 0)}


def build(kind, L, orient='a', t=1.0):
    """Solids (lists of faces) and the two end points (far start, near end) of an impossible path. orient renames
    the axes: the three cyclic ones turn the picture by 120 degrees, the other three mirror it."""
    o = ORIENT[orient]
    moves = [(o[0], +1, L), (o[1], +1, L), (o[2], +1, L)]          # x, then y, then z: the end lands on (L, L, L)
    pts = [np.zeros(3)]
    for ax, sg, ln in moves: pts.append(pts[-1] + sg * ln * AX[ax])
    end = pts[-1]
    k = end[0]
    assert np.allclose(end, k), (kind, end)               # the end sits on the line of sight through the start
    assert k > 0
    D = end.copy()
    far, mid, near = [], [], []                      # boxes (lo, hi): the first run without its start block, the rest
    if kind == 'cubes':
        pitch = 1.6 * t
        for i, (ax, sg, ln) in enumerate(moves):
            m = int(round(ln / pitch)); step = sg * (ln / m) * AX[ax]
            for j in range(0 if i == 0 else 1, m + 1):
                c = pts[i] + j * step; bx = (c, c + t)
                (far if i == 0 and j > 0 else near if i == len(moves) - 1 else mid).append(bx)
    else:
        for i, (ax, sg, ln) in enumerate(moves):
            a, b = pts[i].copy(), pts[i + 1].copy()
            if i == 0:
                mid.append((a, a + t)); a = a + sg * t * AX[ax]          # the start block on its own
            lo = np.minimum(a, b); hi = np.maximum(a, b) + t
            (far if i == 0 else near if i == len(moves) - 1 else mid).append((lo, hi))
    # the near end sits on the far start: wherever the first run crosses in front of the last run in the picture,
    # the last run is cut away along the line of sight
    solids = [box_faces(*bx) for bx in far + mid]
    for bx in near:
        pieces = [box_faces(*bx)]
        for fb in far: pieces = [q for p_ in pieces for q in behind(p_, fb)]
        solids += pieces
    return solids, np.zeros(3) + t / 2, D + t / 2


# ---------------------------------------------------------------- camera and renderer
def rot(axis, a):
    c, s = math.cos(a), math.sin(a); x, y, z = axis
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])




class Camera:
    def __init__(self, centre, scale, cx, cy):
        self.c, self.s, self.cx, self.cy = centre, scale, cx, cy

    def set(self, yaw, pitch):
        """yaw turns the object about its vertical (world z); pitch tips the camera over the top."""
        self.R = rot(RIGHT, pitch) @ rot(AX[2], yaw)

    def project(self, p):
        q = (np.asarray(p, float) - self.c) @ self.R.T
        return np.stack([self.cx + self.s * (q @ RIGHT), self.cy - self.s * (q @ UP), q @ V0], -1)


def shade(col, n_cam):
    """Flat light fixed to the camera: the three faces seen from the magic angle get three clear tones."""
    l = 0.45 * RIGHT + 0.75 * UP + 0.50 * V0; l /= np.linalg.norm(l)
    k = 0.62 + 0.45 * float(n_cam @ l)                     # top ~1.0, right side ~0.75, left side ~0.47
    return tuple(int(min(255, c * k)) for c in col)


def render_solids(img, solids, cam, col):
    """Z-buffer every visible face into img (H x W x 3), supersampled SS times."""
    Hs, Ws = img.shape[0] * SS, img.shape[1] * SS
    big = cv2.resize(img, (Ws, Hs), interpolation=cv2.INTER_NEAREST)
    zb = np.full((Hs, Ws), -1e18, np.float64)
    for faces in solids:
        for vs, n in faces:
            nc = cam.R @ n
            if nc @ V0 <= 1e-6: continue                      # facing away (or edge-on)
            P = cam.project(np.array(vs)); P[:, :2] *= SS
            x0, y0 = np.floor(P[:, :2].min(0)).astype(int); x1, y1 = np.ceil(P[:, :2].max(0)).astype(int) + 1
            x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, Ws), min(y1, Hs)
            if x1 <= x0 or y1 <= y0: continue
            m = np.zeros((y1 - y0, x1 - x0), np.uint8)
            cv2.fillPoly(m, [np.round((P[:, :2] - [x0, y0]) * 16).astype(np.int32)], 1, cv2.LINE_8, 4)
            # depth is linear in screen x, y on a flat face (orthographic camera)
            A = np.c_[P[:3, 0], P[:3, 1], np.ones(3)]
            try: a, b, c = np.linalg.solve(A, P[:3, 2])
            except np.linalg.LinAlgError: continue
            yy, xx = np.mgrid[y0:y1, x0:x1]
            z = a * xx + b * yy + c
            sub = zb[y0:y1, x0:x1]
            win = (m > 0) & (z > sub + 1e-7)
            sub[win] = z[win]
            big[y0:y1, x0:x1][win] = shade(col, nc)
    img[:] = cv2.resize(big, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------- the video
class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.seed = seed
        self.slug = os.path.basename(os.path.normpath(song_dir))
        t1 = min(t1, t0 + MAX_LEN)
        r = random.Random(seed)
        self.kind = K.pick('kind', ['triangle', 'triangle', 'cubes'], r)
        self.orient = K.pick('orient', sorted(ORIENT), r)
        self.pal_name = K.pick('palette', sorted(PALETTES), r)
        self.turn = K.pick('turn', ['left', 'right'], r)
        L = {'triangle': [4, 5, 6, 7], 'cubes': [5, 6, 8]}[self.kind]
        self.size = K.pick('size', L, r)
        self.pal = PALETTES[self.pal_name]
        self.solids, self.A, self.D = build(self.kind, float(self.size), self.orient)
        self.ask = r.choice(ASK[self.kind])
        a = audio.load(self.slug, t0, t1); n = a['n']
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())
        self.kick = audio.hits(a['kicks'], n, 7.0)
        B = [int(round(f)) for _, f in a['beats'] if 0 <= f < n]
        if len(B) < 12: print('not rendered: %.1f s is too short (%s)' % (t1 - t0, self.slug)); sys.exit(3)
        step = (B[-1] - B[0]) / max(1, len(B) - 1)
        u = max(1, int(math.ceil(12 / step)))                       # one move takes at least 0.4 s

        def at_or_after(f):
            nb = [b for b in B if b >= f]; return nb[0] if nb else None
        ask = at_or_after(int(4.4 * FPS))
        if ask is None: print('not rendered: too short to ask (%s)' % self.slug); sys.exit(3)
        i0 = B.index(ask)
        if i0 + 4 * u >= len(B): print('not rendered: too short to turn (%s)' % self.slug); sys.exit(3)
        self.t_turn = (B[i0], B[i0 + 3 * u])                        # the swing round takes three moves
        hold = at_or_after(self.t_turn[1] + int(2.6 * FPS))
        if hold is None or B.index(hold) + 3 * u >= len(B):
            print('not rendered: too short to turn back (%s)' % self.slug); sys.exit(3)
        j = B.index(hold)
        self.t_back = (B[j], B[j + 3 * u])
        self.n = n = min(n, self.t_back[1] + int(2.2 * FPS) + 9)
        self.t0, self.t1 = t0, t0 + n / FPS
        self.yaw = math.radians(r.choice([22, 26, 30])) * (1 if self.turn == 'left' else -1)
        self.pitch = math.radians(r.choice([16, 22]))
        # fit the object into the frame below the question, at every angle the camera will pass through
        verts = np.array([p for f in self.solids for vs, _ in f for p in vs])
        centre = (verts.min(0) + verts.max(0)) / 2
        cam = Camera(centre, 1.0, 0, 0); lo, hi = np.full(2, 1e9), np.full(2, -1e9); lo0 = hi0 = None
        for s_ in np.linspace(0, 1, 9):
            self._aim(cam, s_); q = cam.project(verts)[:, :2]
            lo, hi = np.minimum(lo, q.min(0)), np.maximum(hi, q.max(0))
            if s_ == 0: lo0, hi0 = q.min(0), q.max(0)
        mid = (hi0 + lo0) / 2                                    # centred on the magic view
        sc = min(760 / (hi0 - lo0)[0], 740 / (hi0 - lo0)[1],      # and the whole swing stays inside the frame
                 510 / max(hi[0] - mid[0], mid[0] - lo[0]), 480 / max(hi[1] - mid[1], mid[1] - lo[1]))
        self.cam = Camera(centre, sc, 540 - sc * mid[0], 1000 - sc * mid[1])
        self.gap = float(np.linalg.norm(self.D - self.A))           # beam widths (t = 1)
        self.f_ask = font('Fraunces.ttf', 70); self.f_lab = font('DejaVuSansMono-Bold.ttf', 34)
        self.f_credit = font('DejaVuSansMono-Bold.ttf', 26)
        self._first = None; self._bg = None

    def background(self):
        if self._bg is None:
            a, b = (np.array(c, np.float32) for c in self.pal['bg'])
            g = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
            self._bg = np.repeat((a * (1 - g) + b * g), W, 1).astype(np.uint8)
        return self._bg.copy()

    def _aim(self, cam, s):
        cam.set(self.yaw * s, self.pitch * s)

    def swing(self, i):
        """How far round the camera is (0 = the magic angle, 1 = turned)."""
        p = lambda t: ease((i - t[0]) / max(1, t[1] - t[0]))
        return min(max(p(self.t_turn) - p(self.t_back), 0.0), 1.0)

    def draw(self, i, top=True):
        img = self.background()
        s = self.swing(i)
        self._aim(self.cam, s)
        render_solids(img, self.solids, self.cam, self.pal['body'])
        im = Image.fromarray(img); d = ImageDraw.Draw(im); txt = self.pal['txt']
        turned = self.t_turn[1] <= i < (self.t_back[0] + self.t_back[1]) // 2
        if s > 0.6 and i < self.t_back[1]:            # the gap the magic angle hides, measured off the model
            pa, pd = self.cam.project(self.A)[:2], self.cam.project(self.D)[:2]
            k = min(1.0, (s - 0.6) / 0.4)
            q = pa + (pd - pa) * k
            col = tuple(int(c) for c in txt)
            L = np.linalg.norm(pd - pa); nd = int(L / 22)
            for j in range(0, nd, 2):
                u0, u1 = j / max(1, nd), (j + 1) / max(1, nd)
                if u0 > k: break
                d.line([tuple(pa + (pd - pa) * u0), tuple(pa + (pd - pa) * min(u1, k))], fill=col, width=5)
            for p in (pa, q):
                d.ellipse((p[0] - 9, p[1] - 9, p[0] + 9, p[1] + 9), fill=col)
            if turned:
                lab = 'gap: %.1f beam widths' % self.gap
                d.text((W / 2, 1480), lab, font=self.f_lab, fill=col, anchor='mm', stroke_width=3, stroke_fill=tuple(self.pal['bg'][1]))
        if top:
            if i < self.t_turn[0]: t = self.ask
            elif i < (self.t_back[0] + self.t_back[1]) // 2: t = TURNED if i >= self.t_turn[1] else self.ask
            else: t = BACK
            d.multiline_text((W / 2, 300), t, font=self.f_ask, fill=txt, anchor='mm', align='center', spacing=14)
            if i < self.t_turn[0]:     # a bar fills while you decide
                u = i / max(1, self.t_turn[0]); k = float(self.kick[min(i, len(self.kick) - 1)])
                x0, x1 = 340, 740; y = 420
                d.rounded_rectangle((x0, y - 5, x1, y + 5), 5, fill=tuple(int(c * 0.25 + b * 0.75) for c, b in zip(txt, self.pal['bg'][0])))
                d.rounded_rectangle((x0, y - 5 - 2 * k, x0 + (x1 - x0) * u, y + 5 + 2 * k), 5, fill=self.pal['body'])
        d.text((W / 2, 1590), self.credit, font=self.f_credit, fill=tuple(int(c * 0.6 + b * 0.4) for c, b in zip(txt, self.pal['bg'][1])), anchor='mm')
        return np.asarray(im)

    def frame(self, i):
        tail = 9; o = self.draw(i, top=i < self.n - tail - 4)
        if i >= self.n - tail:
            if self._first is None: self._first = self.draw(0).astype(np.float32)
            a = (i - (self.n - tail) + 1) / (tail + 1)
            o = (o.astype(np.float32) * (1 - a) + self._first * a).astype(np.uint8)
        return o

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', 'turn', self.t_turn, 'back', self.t_back); return
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
        rec = K.record(); rec['pictures'] = 'drawn in code (impossible objects built in 3D, turned)'
        json.dump(rec, open(out[:-4] + '.json', 'w')); print('done', out, rec['knobs'])


Video.frame = _polish.wrap(Video.frame, 'measure')      # light grain and vignette: studio/polish.py

if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 52.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
