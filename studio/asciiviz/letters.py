"""A picture set in type: any frame (a video clip, or a picture a scene painted) turned into rows of bold letters.

Each letter cell takes the letter whose weight matches the picture's brightness there, in the picture's own colour;
where the picture has a clear edge the cell is a stroke along it (/ | \\ -). The picture is smoothed and its
contrast evened out first, so a flat patch becomes a run of one letter (BBBB, @@@@, 0000), and a letter only changes
when the picture under it really has, so the type does not shimmer.
"""
import numpy as np, cv2

SUB = 4                                   # picture pixels per letter cell, each way


# ----
def cells(v, rows, cols):
    """Mean of each letter cell."""
    return v.reshape(rows, SUB, cols, SUB).mean((1, 3))


class Typesetter:
    def __init__(self, rows, cols, levels):
        self.rows, self.cols, self.levels = rows, cols, levels
        self.level = None; self.lo = self.hi = None

    def set(self, bgr):
        """A frame -> (level 0..levels-1 per cell, stroke per cell or -1, colour per cell, brightness per cell)."""
        R, C = self.rows, self.cols
        big = cv2.resize(bgr, (C * SUB, R * SUB), interpolation=cv2.INTER_AREA)
        big = cv2.bilateralFilter(big, 9, 40, 7)                              # flat patches flat, edges kept
        lab = cv2.cvtColor(big, cv2.COLOR_BGR2LAB)
        lab[..., 0] = cv2.createCLAHE(1.3, (4, 4)).apply(lab[..., 0])         # detail in the dark and the bright parts alike
        big = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * 1.35, 0, 255)                     # letters are thin: they need stronger colour
        big = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        rgb = cv2.resize(big, (C, R), interpolation=cv2.INTER_AREA).astype(np.float32)[..., ::-1]
        L = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]) / 255.0
        lo, hi = np.percentile(L, 2), np.percentile(L, 98)
        self.lo = lo if self.lo is None else 0.9 * self.lo + 0.1 * lo         # the exposure drifts, it does not jump
        self.hi = hi if self.hi is None else 0.9 * self.hi + 0.1 * hi
        L = np.clip((L - self.lo) / max(self.hi - self.lo, 0.05), 0, 1)
        # which letter: the brightness in steps, and a cell keeps its letter until the picture moves half a step past it
        want = L ** 0.9 * (self.levels - 1)
        if self.level is None: self.level = np.rint(want)
        self.level = np.where(np.abs(want - self.level) > 0.75, np.rint(want), self.level)
        level = np.clip(self.level, 1, self.levels - 1).astype(int)           # never blank: the whole page is type
        # strokes: where one direction clearly rules the cell (the structure tensor), in the darker half of the picture
        g = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        jxx, jyy, jxy = cells(gx * gx, R, C), cells(gy * gy, R, C), cells(gx * gy, R, C)
        strength = np.sqrt(jxx + jyy); one_way = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
        ang = (np.degrees(0.5 * np.arctan2(2 * jxy, jxx - jyy)) + 180) % 180
        stroke = np.where((ang < 22.5) | (ang >= 157.5), 0, np.where(ang < 67.5, 1, np.where(ang < 112.5, 2, 3)))   # | \ - /
        stroke = np.where((strength > 0.34) & (one_way > 0.6) & (L < 0.62), stroke, -1)
        # colour: the picture's own hue at full strength, its darkness kept but lifted, so a dark part is still readable
        v = rgb.max(-1, keepdims=True) / 255.0
        return level, stroke, rgb / (v + 1e-3) * (0.30 + 0.70 * v ** 0.8), L
