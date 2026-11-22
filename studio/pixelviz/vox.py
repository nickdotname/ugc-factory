"""A tiny isometric voxel renderer for pixel-art worlds drawn entirely in code (no sprites, no image files).

A world is a 3D grid of voxels (material and colour). It is drawn once onto a low-resolution canvas (each voxel a
4x4-pixel isometric block: a 2:1 top face and its two front faces), with long shadows cast from a low sun, and the
moving parts (people, a ball, splashes) are drawn over it every frame with the same depth order. The canvas is then
blown up with hard pixel edges, which is what makes it read as pixel art.

Screen position of voxel (x, y, z): sx = OX + 2 (x - y), sy = OY + (x + y) - 2 z. Larger x + y is nearer the
viewer, so the depth key is (x + y) * 64 + z: nearer and higher wins.
"""
import math
import numpy as np

EMPTY, STONE, GRASS, WATER, ROOF, WOOD, CLAY, LINE, LEAF, ROCK, PERSON, FENCE, DIRT, DARK, NET, SPLASH, BALL = range(17)

# a 4x4 block: 0 = nothing, 1 = top face, 2 = left (+y) face, 3 = right (+x) face
SPRITE = np.array([[0, 1, 1, 0],
                   [1, 1, 1, 1],
                   [2, 2, 3, 3],
                   [2, 2, 3, 3]])
SPR = [(r - 0, c - 2, SPRITE[r, c]) for r in range(4) for c in range(4) if SPRITE[r, c]]
FACE = {1: 1.0, 2: 0.80, 3: 0.62}


class World:
    def __init__(self, nx, ny, nz, seed=0):
        self.nx, self.ny, self.nz = nx, ny, nz
        self.mat = np.zeros((nx, ny, nz), np.uint8)
        self.col = np.zeros((nx, ny, nz, 3), np.float32)
        self.rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------ building
    def put(self, mask, mat, color, noise=10.0, only_empty=False):
        """Fill every voxel where mask is True with a material and a colour (each voxel jittered a little: texture)."""
        if only_empty: mask = mask & (self.mat == EMPTY)
        n = int(mask.sum())
        if not n: return
        self.mat[mask] = mat
        c = np.array(color, np.float32)[None, :] + self.rng.normal(0, noise, (n, 1)) * np.array([1, 1, 1], np.float32)
        self.col[mask] = np.clip(c, 0, 255)

    def clear(self, mask): self.mat[mask] = EMPTY

    def grid(self):
        return np.meshgrid(np.arange(self.nx), np.arange(self.ny), np.arange(self.nz), indexing='ij')

    def box(self, x0, x1, y0, y1, z0, z1, mat, color, noise=10.0):
        x0, y0, z0 = max(0, x0), max(0, y0), max(0, z0)
        m = np.zeros(self.mat.shape, bool); m[x0:x1, y0:y1, z0:z1] = True
        self.put(m, mat, color, noise)

    def sphere(self, cx, cy, cz, r, mat, color, noise=14.0, squash=1.0):
        X, Y, Z = self.grid()
        self.put(((X - cx) ** 2 + (Y - cy) ** 2 + ((Z - cz) / squash) ** 2) <= r * r, mat, color, noise)

    def tree(self, x, y, z, r=3.2, trunk=3):
        self.box(x, x + 1, y, y + 1, z, z + trunk, WOOD, (95, 70, 48), 6)
        for k, (dx, dy, dz, rr) in enumerate([(0, 0, 0, r), (-1.2, 0.8, -0.8, r * 0.75), (1.0, -0.9, 0.6, r * 0.7)]):
            self.sphere(x + dx, y + dy, z + trunk + r * 0.7 + dz, rr, LEAF, [(62, 108, 52), (78, 128, 62), (54, 96, 50)][k], 16)

    def bricks(self, mat, every=3, dark=0.82):
        """Mortar lines on a stone material: darken every few rows, offset per course, so walls read as masonry."""
        X, Y, Z = self.grid(); m = self.mat == mat
        course = (Z % 2 == 0) & (((X + Y + (Z // 2) * 2) % every) == 0)
        self.col[m & course] *= dark

    # ------------------------------------------------------------------ light
    def shadows(self, sun=(1.5, 0.45), reach=40):
        """For every voxel whose top is open to the sky: is the sun (low, from behind-left) blocked on the way up?"""
        occ = self.mat != EMPTY
        top = occ.copy(); top[:, :, :-1] &= ~occ[:, :, 1:]
        xs, ys, zs = np.nonzero(top)
        lit = np.ones(len(xs), bool)
        for s in range(1, reach):
            px = np.round(xs - s * sun[0]).astype(int); py = np.round(ys - s * sun[1]).astype(int); pz = zs + s
            ok = (px >= 0) & (px < self.nx) & (py >= 0) & (py < self.ny) & (pz < self.nz)
            if not ok.any(): break
            hit = np.zeros(len(xs), bool); hit[ok] = occ[px[ok], py[ok], pz[ok]]
            lit &= ~hit
        self.lit = np.ones(self.mat.shape, bool); self.lit[xs, ys, zs] = lit
        return self.lit


class Canvas:
    """The low-resolution picture: colour, depth key and material per pixel."""
    def __init__(self, w, h, ox, oy, bg):
        self.w, self.h, self.ox, self.oy = w, h, ox, oy
        self.rgb = np.zeros((h, w, 3), np.float32); self.rgb[:] = bg
        self.key = np.full((h, w), -1, np.int64); self.mat = np.zeros((h, w), np.uint8)
        self.face = np.zeros((h, w), np.uint8)

    def copy(self):
        c = Canvas.__new__(Canvas); c.__dict__.update(self.__dict__)
        c.rgb = self.rgb.copy(); c.key = self.key.copy(); c.mat = self.mat.copy(); c.face = self.face.copy(); return c

    def screen(self, x, y, z):
        return self.ox + 2 * (np.asarray(x) - np.asarray(y)), self.oy + (np.asarray(x) + np.asarray(y)) - 2 * np.asarray(z)

    def draw(self, x, y, z, rgb, mat, lit=None, faces=(1, 2, 3)):
        """Draw voxels (arrays) with depth test. lit: False where the top face is in shadow."""
        x = np.asarray(x, np.float64); y = np.asarray(y, np.float64); z = np.asarray(z, np.float64)
        if x.size == 0: return
        rgb = np.asarray(rgb, np.float32).reshape(-1, 3); mat = np.broadcast_to(np.asarray(mat, np.uint8), x.shape)
        sx, sy = self.screen(x, y, z); sx = np.round(sx).astype(int); sy = np.round(sy).astype(int)
        key = (np.round(x + y).astype(np.int64) * 64 + np.round(z).astype(np.int64)) * 4
        shade = np.ones(x.shape, np.float32) if lit is None else np.where(lit, 1.0, 0.60).astype(np.float32)
        P, Q, K, C, M, F = [], [], [], [], [], []
        for (dr, dc, f) in SPR:
            if f not in faces: continue
            P.append(sy + dr); Q.append(sx + dc); K.append(key + f)
            C.append(rgb * (FACE[f] * (shade if f == 1 else np.ones(x.shape, np.float32)))[:, None]); M.append(mat); F.append(np.full(x.shape, f, np.uint8))
        P = np.concatenate(P); Q = np.concatenate(Q); K = np.concatenate(K); C = np.concatenate(C); M = np.concatenate(M); F = np.concatenate(F)
        ok = (P >= 0) & (P < self.h) & (Q >= 0) & (Q < self.w)
        P, Q, K, C, M, F = P[ok], Q[ok], K[ok], C[ok], M[ok], F[ok]
        order = np.argsort(K, kind='stable')                    # far to near: the nearest write lands last
        P, Q, K, C, M, F = P[order], Q[order], K[order], C[order], M[order], F[order]
        lin = P * self.w + Q
        _, last = np.unique(lin[::-1], return_index=True); idx = len(lin) - 1 - last
        P, Q, K, C, M, F = P[idx], Q[idx], K[idx], C[idx], M[idx], F[idx]
        win = K > self.key[P, Q]
        P, Q = P[win], Q[win]
        self.rgb[P, Q] = C[win]; self.key[P, Q] = K[win]; self.mat[P, Q] = M[win]; self.face[P, Q] = F[win]

    def world(self, wd):
        """Draw a whole world (only voxels with an open face)."""
        occ = wd.mat != EMPTY; pad = np.pad(occ, ((0, 1), (0, 1), (0, 1)))
        vis = occ & ~(pad[1:, :-1, :-1] & pad[:-1, 1:, :-1] & pad[:-1, :-1, 1:])
        xs, ys, zs = np.nonzero(vis)
        lit = wd.lit[xs, ys, zs] if hasattr(wd, 'lit') else None
        self.draw(xs, ys, zs, wd.col[xs, ys, zs], wd.mat[xs, ys, zs], lit)
        return int(occ.sum())

    def shadow_at(self, x, y, z, ground, sun=(1.5, 0.45), size=1, strength=0.55):
        """The shadow a small moving thing at (x, y, z) casts on the ground below, along the sun."""
        s = max(0.0, z - ground)
        gx, gy = x + s * sun[0], y + s * sun[1]
        sx, sy = self.screen(gx, gy, ground)
        for dr in range(0, 2):
            for dc in range(-size, size + 1):
                r, c = int(round(sy)) + dr, int(round(sx)) + dc
                if 0 <= r < self.h and 0 <= c < self.w and self.face[r, c] == 1: self.rgb[r, c] *= strength


def person(x, y, z, shirt, step=0.0, skin=(232, 190, 160), hair=(60, 45, 35), legs=(60, 64, 80)):
    """A one-voxel-wide person, three voxels tall (legs, shirt, head) plus hair; step lifts it a voxel on the beat."""
    xs = [x, x, x, x]; ys = [y, y, y, y]; zs = [z + step, z + 1 + step, z + 2 + step, z + 2.6 + step]
    return np.array(xs), np.array(ys), np.array(zs), np.array([legs, shirt, skin, hair], np.float32)


def upscale(rgb, scale):
    return np.repeat(np.repeat(rgb, scale, 0), scale, 1)
