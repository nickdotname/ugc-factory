"""Math In Time: "how many folds to reach the Moon?" in pixel art. A sheet of paper 0.1 mm thick doubles with every
fold; each fold lands on the music (one a beat, then faster, then slow again for the last ones), the camera pulls back
past a house, a skyscraper, the clouds, Everest, the edge of space and the space station, until fold 42 passes the
Moon (0.1 mm x 2^42 = 439,805 km; the Moon is 384,400 km away). The "sun" target runs on to fold 51 (225 million km,
past the Sun's 150 million).
python studio/mathviz/fold.py out.mp4 [--seed N] [--frames a,b,c]

Everything is drawn on a 270 x 480 canvas in a few flat colours with ordered dithering, then blown up 4x with no
smoothing: pixel art, with a 5x7 pixel font of our own. Knobs: target (moon / sun), room (night / day)."""
import sys, os, math, random
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

LW, LH, PX = 270, 480, 4
SLUG, B0, SEED = conf('talk', 96)
_r = random.Random(SEED)
TARGET = K.pick('target', ['moon', 'sun'], _r, weights=[3, 1])
ROOM = K.pick('room', ['night', 'day'], _r)
CL = Clock(SLUG, B0, 44)
CREDIT = credit(SLUG)

T0 = 1e-4                                               # a sheet of paper: 0.1 mm
N = 42 if TARGET == 'moon' else 51
DIST = {'moon': '384,400 KM', 'sun': '150,000,000 KM'}  # how far the target is: the last line, where the paper's height was
def thick(n): return T0 * 2.0 ** n

# when fold n lands (in beats): the first 8 one a beat, the last 4 one every two beats, the rest evenly in between
_mid = N - 12
FOLD_AT = [4 + j for j in range(8)] + [round((12 + j * 14 / _mid) * 4) / 4 for j in range(_mid)] + [28 + 2 * j for j in range(4)]
END = FOLD_AT[-1]

# ---------------------------------------------------------------- the pixel font (5x7, our own)
G = {
 'A': ".###.#...##...#######...##...##...#", 'B': "####.#...##...#####.#...##...#####.", 'C': ".###.#...##....#....#....#...#.###.",
 'D': "####.#...##...##...##...##...#####.", 'E': "######....#....####.#....#....#####", 'F': "######....#....####.#....#....#....",
 'G': ".###.#...##....#.####...##...#.####", 'H': "#...##...##...#######...##...##...#", 'I': ".###...#....#....#....#....#...###.",
 'J': "..###...#....#....#....#.#..#..##..", 'K': "#...##..#.#.#..##...#.#..#..#.#...#", 'L': "#....#....#....#....#....#....#####",
 'M': "#...###.###.#.##.#.##...##...##...#", 'N': "#...##...###..##.#.##..###...##...#", 'O': ".###.#...##...##...##...##...#.###.",
 'P': "####.#...##...#####.#....#....#....", 'Q': ".###.#...##...##...##.#.##..#..##.#", 'R': "####.#...##...#####.#.#..#..#.#...#",
 'S': ".#####....#.....###.....#....#####.", 'T': "#####..#....#....#....#....#....#..", 'U': "#...##...##...##...##...##...#.###.",
 'V': "#...##...##...##...##...#.#.#...#..", 'W': "#...##...##...##.#.##.#.##.#.#.#.#.", 'X': "#...##...#.#.#...#...#.#.#...##...#",
 'Y': "#...##...#.#.#...#....#....#....#..", 'Z': "#####....#...#...#...#...#....#####",
 '0': ".###.#...##..###.#.###..##...#.###.", '1': "..#...##....#....#....#....#...###.", '2': ".###.#...#....#...#...#...#...#####",
 '3': "####.....#....#.###.....#....#####.", '4': "...#...##..#.#.#..#.#####...#....#.", '5': "######....####.....#....##...#.###.",
 '6': "..##..#...#....####.#...##...#.###.", '7': "#####....#...#...#...#....#....#...", '8': ".###.#...##...#.###.#...##...#.###.",
 '9': ".###.#...##...#.####....#...#..##..", '.': "..........................##...##..", ',': "....................##....#...#....",
 '?': ".###.#...#....#...#...#.........#..", '!': "..#....#....#....#....#.........#..", ':': "......##...##........##...##.......",
 '/': "....#....#...#...#...#...#....#....", '-': "...............#####...............", '+': ".......#....#..#####..#....#.......",
 'x': ".....#...#.#.#...#...#.#.#...#.....", '=': "..........#####.....#####..........", "'": "..#....#...#.......................",
 ' ': "...................................",
}

def ptext(c, s, x, y, sc, col, shadow=(14, 12, 30), align='l', box=None):
    """Pixel text at (x, y) on the low-res canvas, sc pixels per font pixel, with a hard drop shadow (and an optional
    dark box behind, like an old game's dialogue)."""
    s = s.upper(); w = len(s) * 6 * sc - sc
    if align == 'c': x = x - w // 2
    elif align == 'r': x = x - w
    if box is not None: c[max(0, y - 2 * sc):y + 9 * sc, max(0, x - 3 * sc):x + w + 3 * sc] = box
    for pass_, colr, off in ((0, shadow, sc), (1, col, 0)):
        if colr is None: continue
        for j, ch in enumerate(s):
            g = G.get(ch, G[' '])
            for r in range(7):
                for q in range(5):
                    if g[r * 5 + q] == '#':
                        yy, xx = y + r * sc + off, x + j * 6 * sc + q * sc + off
                        c[max(0, yy):max(0, yy + sc), max(0, xx):max(0, xx + sc)] = colr
    return w

BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16
BY = np.tile(BAYER, (LH // 4 + 1, LW // 4 + 1))[:LH, :LW]

def dgrad(c, y0, y1, c0, c1):
    """A vertical gradient between two colours, dithered so it stays in flat pixel colours."""
    y0, y1 = int(max(0, y0)), int(min(LH, y1))
    if y1 <= y0: return
    t = np.linspace(0, 1, y1 - y0)[:, None]
    m = (t > BY[y0:y1]).astype(np.float32)[..., None]
    c[y0:y1] = np.array(c0, np.float32) * (1 - m) + np.array(c1, np.float32) * m

def disc(c, cx, cy, r, col, shade=None):
    yy, xx = np.ogrid[0:LH, 0:LW]; d = (xx - cx) ** 2 + (yy - cy) ** 2
    c[d <= r * r] = col
    if shade is not None:                                  # a dithered terminator: the lit side up and to the left
        s = ((xx - cx + r * 0.45) ** 2 + (yy - cy + r * 0.45) ** 2) / (r * r * 1.9)
        m = (d <= r * r) & (s > 0.55 + 0.5 * BY[:, :LW][:LH])
        c[m] = shade

# ---------------------------------------------------------------- the world
GROUND = LH - 110                                       # where the desk top / the ground is on screen
TOPROW = 150                                            # where the camera keeps the top of the stack
WALL = {'night': ((46, 34, 92), (36, 26, 74)), 'day': ((222, 196, 150), (204, 178, 132))}[ROOM]
MARKS = [(0.75, 'DESK'), (10, 'A HOUSE'), (330, 'A SKYSCRAPER'), (2000, 'THE CLOUDS'), (8849, 'EVEREST'), (100e3, 'SPACE'),
         (408e3, 'SPACE STATION'), (384.4e6, 'THE MOON')] + ([(41e9, 'VENUS'), (78e9, 'MARS'), (149.6e9, 'THE SUN')] if TARGET == 'sun' else [])

def folded(k):
    """(folds so far, how far the current fold has got 0..1) at beat k."""
    n = sum(1 for b in FOLD_AT if k >= b)
    if n == 0: return 0, 1.0
    return n, float(np.clip((k - FOLD_AT[n - 1]) / 0.35, 0, 1))

def height(k):
    n, u = folded(k); e = float(ease_out(u))
    return thick(n - 1) + (thick(n) - thick(n - 1)) * e if n else thick(0)

def view(k):
    """Metres the screen shows between the ground and the camera's top row: eased in log space, never under 6 cm."""
    return max(0.06, height(k) * 1.25)

def fmt(m):
    if m < 0.01: return '%.1f MM' % (m * 1000)
    if m < 1: return '%.1f CM' % (m * 100)
    if m < 1000: return '%d M' % round(m)
    if m < 1e9: return '{:,} KM'.format(int(round(m / 1000)))
    return '%.1f AU' % (m / 149.6e9)

STARS = [(random.Random(7 + j).randrange(LW), random.Random(99 + j).randrange(LH), random.Random(3 + j).random()) for j in range(140)]

def scene(c, k, kick):
    V = view(k); ppm = (GROUND - TOPROW) / V                       # pixels per metre
    Y = lambda m: GROUND - m * ppm
    out = 1.0 - float(np.clip((math.log10(V) - math.log10(2.5)) / 0.4, 0, 1))      # 1 = indoors, 0 = outside
    sky = float(np.clip((math.log10(V) - 3.3) / 1.7, 0, 1))                        # 0 = blue sky, 1 = space
    # the outside: a dithered sky that goes black with height, stars, the ground or the Earth
    top_c = tuple(int(a * (1 - sky) + b * sky) for a, b in zip((88, 150, 230), (4, 4, 14)))
    low_c = tuple(int(a * (1 - sky) + b * sky) for a, b in zip((170, 210, 250), (16, 18, 46)))
    dgrad(c, 0, GROUND, top_c, low_c)
    if sky > 0.3:
        for x, y, b in STARS:
            if y < GROUND and b < sky: c[y, x] = (255, 255, 255) if (b + 0.3 * kick) > 0.5 else (150, 150, 190)
    if V < 3e5:
        c[GROUND:] = (70, 150, 70) if V < 2e4 else (40, 90, 170)
        dgrad(c, GROUND, GROUND + 6, (110, 190, 110) if V < 2e4 else (120, 190, 255), c[GROUND + 7, 0].tolist())
    else:                                                          # the Earth, a disc that shrinks as we leave it
        R = max(30, 6.371e6 * ppm); cy = GROUND + R - 4
        c[GROUND:] = (4, 4, 14); disc(c, LW / 2, cy, R + 3, (90, 160, 255)); disc(c, LW / 2, cy, R, (40, 90, 170), shade=(22, 50, 110))
    # the things you pass, each with its marker on the ruler
    for m, name in MARKS:
        y = Y(m)
        if not (TOPROW - 140 < y < GROUND - 2): continue
        if name == 'A HOUSE': c[int(y):GROUND, 168:196] = (200, 90, 70); c[int(y) - 6:int(y), 164:200] = (120, 60, 60)
        elif name == 'A SKYSCRAPER':
            c[int(y):GROUND, 196:214] = (60, 70, 90)
            for wy in range(int(y) + 3, GROUND - 2, 4): c[wy, 199:211:3] = (255, 230, 120) if ROOM == 'night' else (150, 200, 230)
        elif name == 'EVEREST':
            for x in range(150, 262):
                h = (GROUND - y) * max(0.0, 1 - abs(x - 206) / 56.0); c[int(GROUND - h):GROUND, x] = (120, 110, 120)
                if h > (GROUND - y) * 0.75: c[int(GROUND - h):int(GROUND - (GROUND - y) * 0.75), x] = (240, 240, 250)
        elif name == 'THE CLOUDS':
            for j in range(6):
                cx = (j * 53 + int(k * 6)) % (LW + 60) - 30; disc(c, cx, y, 9, (245, 245, 255)); disc(c, cx + 10, y + 3, 7, (230, 230, 245))
        elif name == 'SPACE STATION':
            c[int(y) - 1:int(y) + 2, 196:222] = (200, 200, 210); c[int(y) - 4:int(y) + 5, 205:213] = (90, 110, 200)
        elif name == 'THE MOON': disc(c, 205, y, 20, (205, 205, 200), shade=(120, 120, 120)); disc(c, 198, y - 5, 3, (160, 160, 158)); disc(c, 212, y + 6, 4, (160, 160, 158))
        elif name == 'THE SUN': disc(c, 205, y, 26 + 2 * kick, (255, 236, 140)); disc(c, 205, y, 20, (255, 250, 210))
        elif name in ('VENUS', 'MARS'): disc(c, 205, y, 8, (230, 200, 140) if name == 'VENUS' else (210, 100, 60))
    # the room, fading out as the camera leaves it
    if out > 0:
        room = c.copy(); dgrad(room, 0, GROUND - 40, WALL[0], WALL[1])
        for x in range(0, LW, 18): room[0:GROUND - 40, x] = np.array(WALL[1]) * 0.85
        dgrad(room, GROUND - 40, GROUND, (60, 120, 90), (46, 100, 74))          # the cutting mat
        for x in range(10, LW, 26): room[GROUND - 40:GROUND, x] = (90, 160, 120)
        for yy in range(GROUND - 34, GROUND, 9): room[yy, :] = (90, 160, 120)
        room[GROUND:] = (140, 96, 56); room[GROUND + 1::3] = (118, 80, 46)      # the desk's grain
        mask = (out > BY[:LH, :LW])[..., None]
        c[:] = np.where(mask, room, c)
    # the stack of paper
    top = Y(height(k)); x0, x1 = 112, 158
    top = min(top, GROUND - 3)
    c[int(top):GROUND, x0:x1] = (238, 236, 228)
    c[int(top):GROUND, x1 - 2:x1] = (196, 194, 186)
    if GROUND - top > 12:
        for yy in range(int(top) + 4, GROUND, 4): c[yy, x0:x1 - 2] = (214, 212, 204)              # the layers
    n, u = folded(k)
    if 0 < u < 1:                                                    # the fold: a flap swings over and throws dust
        a = u * math.pi; L = 22
        fx = x1 - L * (1 - math.cos(a)) / 2; fy = top - 10 * math.sin(a)
        c[int(fy):int(fy) + 3, int(min(fx, x1 - 2)):x1] = (255, 255, 255)
        g = random.Random(n)
        for _ in range(10):
            dx, dy = g.uniform(-30, 30) * u, -g.uniform(4, 22) * u
            px, py = int((x0 + x1) / 2 + dx), int(top + dy)
            if 0 <= px < LW and 0 <= py < LH: c[py, px] = (255, 255, 220)
    # the ruler, with the markers on it
    c[TOPROW - 4:GROUND, 14:22] = (244, 200, 80); c[TOPROW - 4:GROUND, 22] = (160, 120, 40)
    step = 10 ** math.floor(math.log10(V / 3));
    for j in range(0, 60):
        y = Y(j * step)
        if y < TOPROW - 4: break
        c[int(y), 14:19 if j % 5 else 22] = (90, 60, 20)
    for m, name in MARKS:
        y = Y(m)
        if TOPROW < y < GROUND - 4:
            c[int(y) - 1:int(y) + 2, 22:34] = (120, 130, 150); disc(c, 35, y, 2, (150, 160, 190))
            ptext(c, name, 40, int(y) - 3, 1, (220, 225, 240))
    return Y(height(k))

def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = np.zeros((LH, LW, 3), np.float32)
    scene(c, k, kick)
    n, u = folded(k)
    # the count and the height, top left, once folding starts
    if 3.5 <= k < END + 3:
        ptext(c, 'FOLD %03d' % n, 12, 104, 2, (120, 200, 255))
        ptext(c, fmt(height(k)), 12, 124, 2, (255, 214, 90))
    # the question, then the answer
    if k < 4:
        ptext(c, 'HOW MANY FOLDS', LW // 2, 56, 2, (255, 255, 255), align='c', box=(14, 12, 30))
        ptext(c, 'TO REACH THE %s?' % TARGET.upper(), LW // 2, 76, 2, (255, 255, 255), align='c', box=(14, 12, 30))
    elif k >= END + 0.5:
        ptext(c, 'FOLD %d:' % N, LW // 2, 56, 3, (255, 214, 90), align='c', box=(14, 12, 30))
        ptext(c, 'PAST THE %s' % TARGET.upper(), LW // 2, 84, 2, (255, 255, 255), align='c', box=(14, 12, 30))
        if k >= END + 3:                                         # where the count was: what it means
            ptext(c, '0.1 MM, DOUBLED', LW // 2, 108, 2, (255, 214, 90), align='c', box=(14, 12, 30))
            ptext(c, '%d TIMES.' % N, LW // 2, 128, 2, (255, 214, 90), align='c', box=(14, 12, 30))
        if k >= 40: ptext(c, 'THE %s: %s AWAY' % (TARGET.upper(), DIST[TARGET]), LW // 2, 152, 1, (200, 210, 230), align='c', box=(14, 12, 30))
    big = cv2.resize(np.clip(c, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(np.float32)
    paste(big, text(CREDIT, F(DEJAVU, 28), (230, 230, 240), stroke=3), W / 2, 1490)
    return np.clip(big, 0, 255).astype(np.uint8)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
