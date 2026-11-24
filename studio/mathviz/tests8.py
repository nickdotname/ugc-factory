"""8-bit play-along tests built from the song itself, in pixel art (a 270x480 canvas blown up 4x):

  flashes  COUNT THE FLASHES: a jar of fireflies blinks on every snare of a stretch; the answer comes after.
           The count is exact because it comes from the song's own snare hits (the beat map).
  read     CAN YOU READ AS FAST AS HE RAPS? The verse one word at a time, exactly as it is sung, with a gauge of
           its words per minute against the average adult's silent reading speed (238 WPM, Brysbaert 2019).
           Needs the song's word timings; without them the flashes test is made instead.

The audio is the song, untouched. A small pixel creature reacts to the kicks. Knobs: test, sky (the palette)."""
import sys, os, math, random, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *
from pixel import G, ptext, dgrad, disc, LW, LH

SLUG, B0, SEED = conf('fixation', 96)
_r = random.Random(SEED)
_LINES_P = os.path.join(audio.SONGS, SLUG, 'lines.json')
HAVE_WORDS = os.environ.get('CQ_LYRICS') != 'none' and os.path.exists(_LINES_P)
TEST = K.pick('test', ['flashes', 'read'], _r, weights=[1, 2 if HAVE_WORDS else 0.0001])
if TEST == 'read' and not HAVE_WORDS: TEST = 'flashes'
SKY = K.pick('sky', ['night', 'dusk', 'deep'], _r)
SKIES = {'night': ((34, 26, 84), (20, 16, 52)), 'dusk': ((92, 44, 110), (40, 24, 72)), 'deep': ((12, 30, 70), (6, 12, 34))}
COUNT = 16                                              # beats of counting / reading
CL = Clock(SLUG, B0, 4 + COUNT + 8)
CREDIT = credit(SLUG)
STARS = [(random.Random(11 + j).randrange(LW), random.Random(77 + j).randrange(300), random.Random(5 + j).random()) for j in range(110)]

if TEST == 'read':                                      # the words sung in the stretch, on the beat clock
    WORDS = [(CL.beat(int(round((t - CL.t0) * FPS))), w) for e, ws in json.load(open(_LINES_P)) for w, t in ws if CL.t0 <= t < CL.t1]
    WORDS = [(b, w) for b, w in WORDS if 3.5 <= b < 4 + COUNT]
else:
    WORDS = []
SNARES = [b for b in CL.snare_beats if 4 <= b < 4 + COUNT]
ANSWER = len(SNARES)

def wpm_at(b):
    """Words per minute over the last two seconds of song before beat b."""
    spb = CL.spb; recent = [x for x, _ in WORDS if b - 2 / spb <= x <= b]
    return len(recent) * 30.0

PEAK = max([wpm_at(b) for b, _ in WORDS] or [0])

def creature(c, x, y, kick, look, r=24, col=(120, 230, 170), dark=(70, 170, 120)):
    """A round pixel blob with eyes that bounces on the kick and looks at the action."""
    yy = y - int(6 * kick)
    disc(c, x, yy, r + 2, (20, 14, 40)); disc(c, x, yy, r, col, shade=dark)
    for ex in (-r // 3, r // 3):
        disc(c, x + ex, yy - r // 5, r // 4, (255, 255, 255)); disc(c, x + ex + look, yy - r // 5, r // 8 + 1, (20, 14, 40))
    c[yy + r // 3:yy + r // 3 + 2, x - r // 5:x + r // 5] = (20, 14, 40)

def window(c, kick):
    """A window in the wall with the moon in it."""
    x0, y0, x1, y1 = 150, 40, 250, 150
    c[y0 - 4:y1 + 4, x0 - 4:x1 + 4] = (90, 60, 50)
    t = np.linspace(0, 1, y1 - y0)[:, None, None]; c[y0:y1, x0:x1] = np.array([14, 20, 60], np.float32) * (1 - t) + np.array([60, 46, 120], np.float32) * t
    for j in range(14):
        r = random.Random(40 + j); c[r.randrange(y0, y1), r.randrange(x0, x1)] = (230, 230, 255)
    disc(c, 218, 78, 13, (240, 236, 210), shade=(190, 186, 170))
    c[y0:y1, (x0 + x1) // 2 - 1:(x0 + x1) // 2 + 1] = (90, 60, 50); c[(y0 + y1) // 2 - 1:(y0 + y1) // 2 + 1, x0:x1] = (90, 60, 50)

def jar(c, cx, cy, glow):
    """A big glass jar of fireflies, glowing by `glow` (0..1)."""
    if glow > 0.02:
        yy, xx = np.ogrid[0:LH, 0:LW]; d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        c += (np.array([255, 230, 120], np.float32) * np.clip(glow * (1 - d / 150), 0, 1)[..., None] * 0.8)
    w, h = 52, 78
    c[cy - h:cy + h, cx - w:cx + w] = c[cy - h:cy + h, cx - w:cx + w] * 0.55 + np.array([90, 150, 180], np.float32) * 0.45 * (1 + 0.6 * glow)
    c[cy - h:cy + h, cx - w - 2:cx - w] = (210, 235, 245); c[cy - h:cy + h, cx + w:cx + w + 2] = (210, 235, 245); c[cy + h:cy + h + 2, cx - w - 2:cx + w + 2] = (210, 235, 245)
    c[cy - h - 12:cy - h, cx - w + 4:cx + w - 4] = (150, 110, 70); c[cy - h - 12:cy - h - 10, cx - w + 4:cx + w - 4] = (200, 160, 110)
    c[cy - h + 6:cy + h - 6, cx - w + 6:cx - w + 9] = (230, 245, 250)          # a highlight on the glass
    for j in range(18):
        r = random.Random(j); fx, fy = cx + r.randrange(-w + 8, w - 8), cy + r.randrange(-h + 10, h - 8)
        col = (255, 252, 190) if glow > 0.25 else (130, 150, 80)
        c[fy:fy + 3, fx:fx + 3] = col

def boombox(c, cx, y, kick, bass, k):
    """A boombox on the floor: its speaker cones push out on the kick, the level bars follow the bass."""
    x0, x1, y1 = cx - 62, cx + 62, y + 56
    c[y - 14:y - 11, cx - 34:cx + 34] = (150, 150, 165); c[y - 14:y, cx - 34:cx - 31] = (150, 150, 165); c[y - 14:y, cx + 31:cx + 34] = (150, 150, 165)   # the handle
    c[y - 30:y, x1 - 12:x1 - 10] = (190, 190, 205)                                                  # the aerial
    c[y:y1, x0:x1] = (44, 40, 66); c[y:y + 3, x0:x1] = (88, 82, 124); c[y1 - 3:y1, x0:x1] = (24, 20, 40)
    c[y:y1, x0:x0 + 2] = (88, 82, 124); c[y:y1, x1 - 2:x1] = (24, 20, 40)
    for sx in (x0 + 24, x1 - 24):                                                                   # the two speakers
        disc(c, sx, y + 30, 20, (18, 14, 30)); disc(c, sx, y + 30, 17, (70, 66, 100))
        disc(c, sx, y + 30, 8 + int(round(5 * kick)), (200, 204, 228)); disc(c, sx, y + 30, 3, (18, 14, 30))
    c[y + 8:y + 24, cx - 20:cx + 20] = (14, 12, 26)                                                 # the tape window
    for wx in (cx - 10, cx + 10):
        disc(c, wx, y + 16, 5, (230, 230, 240)); a = k * 1.2 + wx
        c[int(y + 16 + 3 * math.sin(a)), int(wx + 3 * math.cos(a))] = (18, 14, 30)                  # the reels turn
    for j in range(8):                                                                              # the level bars
        h = int(2 + 12 * min(1.0, bass * (0.55 + 0.45 * math.sin(1.7 * j + 2.1 * k) ** 2) + 0.5 * kick))
        c[y + 46 - h:y + 46, cx - 19 + j * 5:cx - 16 + j * 5] = (255, 214, 90) if h > 9 else (120, 230, 170)


def room(c, k, kick, bass):
    """Everything in the room that is not the test: books and a plant on the shelf, a rug, the boombox playing
    the song, and a second creature on the floor nodding along."""
    for j, (bx, bh, col) in enumerate(((194, 30, (196, 84, 84)), (202, 36, (84, 140, 196)), (211, 26, (230, 190, 90)), (219, 33, (140, 100, 180)), (228, 29, (90, 170, 130)))):
        c[330 - bh:330, bx:bx + 7] = col; c[330 - bh + 4:330 - bh + 6, bx + 1:bx + 6] = (240, 236, 220)              # books
    c[310:330, 244:262] = (170, 96, 70); c[310:313, 242:264] = (200, 124, 92)                                         # a plant pot
    for j, (lx, ly) in enumerate(((253, 296), (246, 300), (260, 301), (249, 288), (257, 290))):
        sway = int(round(2 * math.sin(0.5 * k + j))); disc(c, lx + sway, ly, 6, (70, 150, 96), shade=(44, 110, 72))
    yy, xx = np.ogrid[0:LH, 0:LW]                                                                                     # the rug
    e = ((xx - 135) / 124.0) ** 2 + ((yy - 432) / 34.0) ** 2
    c[np.broadcast_to(e <= 1, c.shape[:2])] = (120, 52, 70)
    ring = np.broadcast_to((e <= 0.8) & (e > 0.62), c.shape[:2]); c[ring] = (230, 190, 110)
    c[np.broadcast_to(e <= 0.3, c.shape[:2])] = (160, 74, 92)
    boombox(c, 122, 372, kick, bass, k)
    creature(c, 226, 420 - int(3 * abs(math.sin(math.pi * k))), kick, -3, r=17, col=(190, 150, 240), dark=(130, 96, 190))                                       # nods on every beat


def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = np.zeros((LH, LW, 3), np.float32)
    top, low = SKIES[SKY]; dgrad(c, 0, 330, top, low)
    for x, y, b in STARS:
        if y < 330: c[y, x] = (255, 255, 255) if b + 0.25 * kick > 0.7 else (120, 120, 170)
    window(c, kick)
    c[330:] = (60, 40, 40); c[330:334] = (120, 88, 64)                    # the shelf
    for x in range(0, LW, 24): c[334:, x] = (50, 32, 32)
    room(c, k, kick, float(CL.bass[i]))
    if TEST == 'flashes':
        last = max([b for b in SNARES if b <= k] or [-99])
        glow = math.exp(-(k - last) * 5.0) if 4 <= k < 4 + COUNT else 0.0
        jar(c, LW // 2, 238, glow)
        creature(c, 40, 304, kick, 3)
        if k < 4:
            ptext(c, 'SOUND ON', 70, 40, 1, (200, 210, 240), align='c')
            ptext(c, 'COUNT THE', 70, 60, 2, (255, 255, 255), align='c', box=(14, 12, 30))
            ptext(c, 'FLASHES', 70, 82, 2, (255, 214, 90), align='c', box=(14, 12, 30))
        elif k < 4 + COUNT:
            ptext(c, 'KEEP COUNTING', 12, 20, 1, (220, 225, 240))
            f = (k - 4) / COUNT; c[32:36, 12:12 + int(120 * f)] = (255, 214, 90); c[32:36, 12 + int(120 * f):132] = (40, 34, 80)
        elif k < 4 + COUNT + 2:
            ptext(c, 'HOW MANY?', 70, 70, 2, (255, 214, 90), align='c', box=(14, 12, 30))
        else:
            ptext(c, '%d' % ANSWER, 70, 50, 5, (255, 214, 90), align='c', box=(14, 12, 30))
            ptext(c, 'FLASHES', 70, 96, 2, (255, 255, 255), align='c', box=(14, 12, 30))
            ptext(c, 'ONE ON EVERY SNARE', 70, 120, 1, (220, 225, 240), align='c', box=(14, 12, 30))
    else:
        creature(c, 40, 304, kick, 3)
        w = [x for x in WORDS if x[0] <= k + 0.03]
        if k < 4:
            ptext(c, 'CAN YOU READ', 74, 44, 1, (255, 255, 255), align='c', box=(14, 12, 30))
            ptext(c, 'AS FAST', 74, 62, 2, (255, 214, 90), align='c', box=(14, 12, 30))
            ptext(c, 'AS HE RAPS?', 74, 86, 1, (255, 255, 255), align='c', box=(14, 12, 30))
        elif k < 4 + COUNT:
            if w:
                word = w[-1][1].strip(',.?!"').upper()[:12]; sc = 4 if len(word) <= 7 else 3
                ptext(c, word, LW // 2, 196, sc, (255, 255, 255), align='c', box=(14, 12, 30))
            wp = wpm_at(k); gx0, gx1, gy = 40, 230, 262                # the gauge, with the average reader marked
            c[gy:gy + 10, gx0:gx1] = (30, 24, 60); fill = int((gx1 - gx0) * min(1.0, wp / 400))
            c[gy:gy + 10, gx0:gx0 + fill] = (255, 214, 90) if wp > 238 else (120, 230, 170)
            mx = gx0 + int((gx1 - gx0) * 238 / 400); c[gy - 4:gy + 14, mx:mx + 2] = (255, 255, 255)
            ptext(c, 'AVG 238', mx, gy + 18, 1, (200, 210, 240), align='c')
            ptext(c, '%d WPM' % wp, LW // 2, gy - 22, 2, (255, 255, 255), align='c')
        else:
            ptext(c, 'PEAK', LW // 2, 176, 2, (255, 255, 255), align='c', box=(14, 12, 30))
            ptext(c, '%d WPM' % PEAK, LW // 2, 200, 3, (255, 214, 90), align='c', box=(14, 12, 30))
            ptext(c, 'THE AVERAGE ADULT READS 238', LW // 2, 236, 1, (220, 225, 240), align='c', box=(14, 12, 30))
    big = cv2.resize(np.clip(c, 0, 255).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(np.float32)
    paste(big, text(CREDIT, F(DEJAVU, 30), (230, 230, 240), stroke=3), W / 2, 1376)
    return np.clip(big, 0, 255).astype(np.uint8)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
