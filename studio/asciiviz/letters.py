"""A picture set in type: any frame (a clip, or a picture a scene painted) turned into rows of bold letters.

The picture is smoothed so a flat patch stays flat, then cut into letter cells. Each cell is one material: its colour
family says which letters it may use (water is ~ = z S, a leaf is v V Y W, anything orange is o O 0 Q), its brightness
says how heavy a letter of that family, and where a clear edge crosses the cell it becomes a stroke along the edge
(/ | \\ -). So a fin is a run of one letter, an outline is a line of strokes, and the page behind the letters carries a
dim wash of the same colour, so there is no hole in the picture. A cell keeps its letter until the picture under it
has really changed, so the type does not shimmer.
"""
import numpy as np, cv2

SUB = 4                                   # picture pixels per letter cell, each way
FAMILIES = {                              # one set of letters per material, lightest first
    'grey': ".:;!lIH#M",
    'red': ".:coeO0Q@",
    'gold': ".:=+xXK$&",
    'green': ".,;ivVYW",
    'blue': ".-~=zsSZ8",
    'pink': ".:*^aqdB%",
}
HUES = [('red', 14), ('gold', 38), ('green', 100), ('blue', 250), ('pink', 330)]      # the middle of each family, degrees
STROKES = "|\\-/"
CHARS = ''.join(FAMILIES.values()) + STROKES


# ----
def cells(v, rows, cols):
    """Mean of each letter cell."""
    return v.reshape(rows, SUB, cols, SUB, *v.shape[2:]).mean((1, 3))


def family(rgb):
    """Which material a cell is: grey if it has little colour, else the family whose hue is nearest."""
    hsv = cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2HSV)
    far = [np.abs((hsv[..., 0] - h + 180) % 360 - 180) for _, h in HUES]
    return np.where(hsv[..., 1] < 0.20, 0, 1 + np.argmin(far, 0))


class Typesetter:
    def __init__(self, rows, cols, ink):
        """ink: how much of its cell each letter covers (0..1), from the font, so 'heavier' is measured, not guessed."""
        self.rows, self.cols = rows, cols
        self.sets = [sorted(f, key=lambda c: ink[c]) for f in FAMILIES.values()]
        top = max(ink[s[-1]] for s in self.sets)
        self.inks = [np.array([ink[c] for c in s]) / top for s in self.sets]
        self.char = None; self.want = None; self.fam = None; self.lo = self.hi = None

    def set(self, rgb):
        """A frame (RGB, any size) -> per cell: its letter, its colour, the wash behind it, and its brightness 0..1."""
        R, C = self.rows, self.cols
        big = cv2.resize(rgb, (C * SUB, R * SUB), interpolation=cv2.INTER_AREA)
        big = cv2.bilateralFilter(big, 7, 36, 5)                              # flat patches flat, edges kept
        cell = cells(big.astype(np.float32), R, C)
        L = (0.299 * cell[..., 0] + 0.587 * cell[..., 1] + 0.114 * cell[..., 2]) / 255.0
        lo, hi = np.percentile(L, 1), np.percentile(L, 99.5)
        self.lo = lo if self.lo is None else 0.9 * self.lo + 0.1 * lo         # the exposure drifts, it does not jump
        self.hi = hi if self.hi is None else 0.9 * self.hi + 0.1 * hi
        L = np.clip((L - self.lo) / max(self.hi - self.lo, 0.08), 0, 1)
        # the material: decided on a slightly blurred copy, and kept until the colour has clearly moved on
        fam = family(cv2.GaussianBlur(cell, (0, 0), 0.7))
        if self.fam is None: self.fam = fam
        keep = family(cell) == self.fam
        self.fam = np.where(keep, self.fam, fam)
        # the letter: the one in the family whose ink is nearest the brightness; a cell holds on to its letter until
        # the brightness has moved more than a letter's worth
        want = 0.10 + 0.90 * L ** 0.85
        char = np.empty((R, C), '<U1')
        for k, (letters, inks) in enumerate(zip(self.sets, self.inks)):
            m = self.fam == k
            char[m] = np.array(letters)[np.abs(inks[None, :] - want[m][:, None]).argmin(1)]
        if self.char is not None:
            hold = (np.abs(want - self.want) < 0.09) & (self.fam == self.fam_was)
            char = np.where(hold, self.char, char); want = np.where(hold, self.want, want)
        self.char, self.want, self.fam_was = char, want, self.fam.copy()
        # strokes: where one direction clearly rules the cell (the structure tensor of the picture's edges)
        g = cv2.cvtColor(big, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        jxx, jyy, jxy = cells(gx * gx, R, C), cells(gy * gy, R, C), cells(gx * gy, R, C)
        strength = np.sqrt(jxx + jyy); one_way = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
        ang = (np.degrees(0.5 * np.arctan2(2 * jxy, jxx - jyy)) + 180) % 180
        stroke = np.where((ang < 22.5) | (ang >= 157.5), 0, np.where(ang < 67.5, 1, np.where(ang < 112.5, 2, 3)))
        # only the clear outlines: strong, one-way, and stronger than most of the picture's edges, so a busy texture
        # (grass, foam) stays letters and a silhouette gets its line
        edge = (strength > max(0.42, np.percentile(strength, 88))) & (one_way > 0.7)
        out = np.where(edge, np.array(list(STROKES))[stroke], char)
        # colour: the picture's own hue, stronger (letters are thin), its darkness kept but lifted so a dark part
        # still reads; behind the letters, the same colour at a quarter of the strength
        hsv = cv2.cvtColor(cell / 255.0, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1] * 1.3, 0, 1); v = hsv[..., 2].copy()
        hsv[..., 2] = 0.34 + 0.66 * v ** 0.7
        ink = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB) * 255
        hsv[..., 2] = 0.26 * v + 0.03
        wash = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB) * 255
        return out, np.where(edge[..., None], np.minimum(ink * 1.18, 255), ink), wash, L
