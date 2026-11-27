"""Math In Time: a pathfinding race. Three search algorithms solve the same maze side by side, one cell each at the
same rate: depth-first wanders, breadth-first floods, A* heads for the exit. Each lights its route on the beat it gets
out, then the numbers: how much of the maze each had to look at, and how long its route was.
python studio/mathviz/paths.py out.mp4 [--seed N] [--frames a,b,c]

The mazes are generated (a randomised depth-first carve with a few extra openings, so routes differ in length), and
every lit cell is a real step of the algorithm named over it. Which three race and the look are knobs."""
import sys, os, math, random, heapq
from collections import deque
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit import *

SLUG, B0, SEED = conf('talk', 32)
ST = Style(SEED)
CL = Clock(SLUG, B0, 44)
CREDIT = credit(SLUG)
BG = background(ST); FONT = FONTS[ST.font]
def mix(c1, c2, t): return tuple(int(a * (1 - t) + b * t) for a, b in zip(c1, c2))

MAZE = K.pick('maze', ['bfs-dfs-astar', 'dijkstra-greedy-astar', 'dfs-greedy-astar'], random.Random(SEED))
NAMES = MAZE.split('-')
LABEL = {'bfs': 'breadth-first', 'dfs': 'depth-first', 'astar': 'A*', 'greedy': 'greedy best-first', 'dijkstra': "Dijkstra"}
COLS, ROWS = 47, 15                           # odd: walls on even cells, rooms on odd


def carve(seed):
    r = random.Random(seed); g = np.ones((ROWS, COLS), bool)            # True = wall
    st = [(1, 1)]; g[1, 1] = False
    while st:
        y, x = st[-1]; nb = [(y + dy, x + dx, dy, dx) for dy, dx in ((0, 2), (0, -2), (2, 0), (-2, 0))
                             if 0 < y + dy < ROWS - 1 and 0 < x + dx < COLS - 1 and g[y + dy, x + dx]]
        if not nb: st.pop(); continue
        ny, nx, dy, dx = r.choice(nb); g[y + dy // 2, x + dx // 2] = False; g[ny, nx] = False; st.append((ny, nx))
    for _ in range(int(COLS * ROWS * 0.035)):                             # a few loops, so there is a shortest route to find
        y, x = r.randrange(1, ROWS - 1), r.randrange(1, COLS - 1)
        if g[y, x] and ((y % 2 == 1) != (x % 2 == 1)): g[y, x] = False
    return g

G = carve(SEED * 13 + 1); START, GOAL = (1, 1), (ROWS - 2, COLS - 2)

def nbrs(p):
    y, x = p
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        q = (y + dy, x + dx)
        if not G[q]: yield q

def search(kind):
    """The cells in the order the algorithm looks at them, and the route it ends up with."""
    h = lambda p: abs(p[0] - GOAL[0]) + abs(p[1] - GOAL[1])
    prev = {START: None}; order = []
    if kind in ('bfs', 'dfs'):
        dq = deque([START])
        while dq:
            p = dq.popleft() if kind == 'bfs' else dq.pop(); order.append(p)
            if p == GOAL: break
            for q in nbrs(p):
                if q not in prev: prev[q] = p; dq.append(q)
    else:
        cost = {START: 0}; pq = [(0, 0, START)]; seen = set(); t = 0
        while pq:
            _, _, p = heapq.heappop(pq)
            if p in seen: continue
            seen.add(p); order.append(p)
            if p == GOAL: break
            for q in nbrs(p):
                c = cost[p] + 1
                if q not in cost or c < cost[q]:
                    cost[q] = c; prev[q] = p; t += 1
                    pr = {'astar': c + h(q), 'greedy': h(q), 'dijkstra': c}[kind]
                    heapq.heappush(pq, (pr, t, q))
    route = []; p = GOAL
    while p is not None and p in prev: route.append(p); p = prev[p]
    return order, route[::-1]

RES = {nm: search(nm) for nm in NAMES}
OPEN = int((~G).sum())
RACE0, RACE1 = 7.0, 31.0
slow = max(len(RES[nm][0]) for nm in NAMES)
RATE = slow / (RACE1 - RACE0)                  # cells looked at per beat, the same in every lane
FIN = {nm: RACE0 + len(RES[nm][0]) / RATE for nm in NAMES}
ORDER = sorted(NAMES, key=lambda nm: FIN[nm]); PLACE = {nm: k + 1 for k, nm in enumerate(ORDER)}
HITS = {round(FIN[nm] * 2) / 2: 0.7 for nm in NAMES}; HITS.update({RACE0: 0.9, 35: 0.6})
LANE_Y0, LANE_H, GAP = 470, 325, 20                  # the last lane ends at 1485: inside Instagram's safe area
CELL = min((W - 140) / COLS, (LANE_H - 60) / ROWS)
LANE_COL = {nm: c for nm, c in zip(NAMES, (ST.b, ST.c, ST.d))}

def lane(c, k, nm, kb, kick):
    y0 = LANE_Y0 + k * (LANE_H + GAP); x0 = (W - COLS * CELL) / 2; my0 = y0 + 52
    c[y0:y0 + LANE_H, 60:W - 60] = c[y0:y0 + LANE_H, 60:W - 60] * 0.4 + np.array(mix(ST.bg, ST.fg, 0.05), np.float32) * 0.6
    order, route = RES[nm]
    n = 0 if kb < RACE0 else min(len(order), int((kb - RACE0) * RATE))
    img = np.zeros((ROWS, COLS, 3), np.float32) + np.array(mix(ST.bg, ST.fg, 0.10), np.float32)
    img[G] = np.array(mix(ST.bg, ST.fg, 0.55), np.float32)
    col = np.array(LANE_COL[nm], np.float32)
    for j, (y, x) in enumerate(order[:n]):
        age = (n - j) / RATE                                  # beats since it was looked at
        img[y, x] = col * (0.45 + 0.55 * math.exp(-age * 1.5))
    if n: y, x = order[n - 1]; img[y, x] = np.array(ST.fg, np.float32)
    done = kb >= FIN[nm]
    if done:
        m = int(min(1, (kb - FIN[nm]) / 1.0) * len(route))  # the route lights up over one beat
        for (y, x) in route[:m]: img[y, x] = np.array(ST.a, np.float32) * (1 + 0.25 * kick)
    img[START] = np.array(ST.a, np.float32); img[GOAL] = np.array(ST.a, np.float32)
    big = cv2.resize(img, (int(COLS * CELL), int(ROWS * CELL)), interpolation=cv2.INTER_NEAREST)
    yy, xx = int(my0), int(x0); c[yy:yy + big.shape[0], xx:xx + big.shape[1]] = big
    lab = text(LABEL[nm], F(FONT, 40), ST.fg); paste(c, lab, 80 + lab.shape[1] / 4, y0 + 28)
    s = text('%d cells checked' % n, F(MONO, 28), ST.muted); paste(c, s, W - 80 - s.shape[1] / 4, y0 + 28)
    if done:
        e = float(ease_back((kb - FIN[nm]) / 0.4)); p = PLACE[nm]
        paste(c, text({1: '1st', 2: '2nd', 3: '3rd'}[p], F(FONT, 80), ST.a if p == 1 else ST.fg, stroke=4), W - 150, y0 + LANE_H / 2 + 26, e, min(1, e))

def frame(i):
    k = CL.beat(i); kick = float(CL.kick[i])
    c = BG.copy()
    if k < 4.6:
        a = 1 - float(ease_out((k - 4.0) / 0.5))
        for j, (s, sz, col, y) in enumerate((('3 ways to escape', 80, ST.fg, 325), ('the same maze.', 60, ST.muted, 405))):
            e = 1.0 if j == 0 else float(ease_back((k - 1.2 * j) / 0.45));   # the title is on frame 0: the cover paste(c, text(s, F(FONT, sz), col), W / 2, y, e, a * min(1, e))
        e = float(ease_back((k - 2.4) / 0.45))
        paste(c, text('which gets out first?', F(FONT, 84), ST.a, stroke=3), W / 2, 1660, e * (1 + 0.04 * kick), a * min(1, e))
    else:
        paste(c, text('which gets out first?', F(FONT, 58), ST.a), W / 2, 330, 1, window(k, 4.4, 34.5))
    for j, nm in enumerate(NAMES): lane(c, j, nm, k, kick)
    if k >= 34:
        f = float(ease_out((k - 34) / 0.8)); c[:] = c * (1 - 0.9 * f) + BG * 0.9 * f
    if 4 <= k < 7.6:
        n = int(k - 4); lab = ['3', '2', '1', 'GO'][min(3, n)]; e = float(ease_back((k - 4 - n) / 0.3))
        paste(c, text(lab, F(FONT, 240), ST.c if lab == 'GO' else ST.fg, stroke=6), W / 2, 1000, e * (1 + 0.06 * kick), min(1, e) * (1 - float(ease_out((k - 4 - n - 0.7) / 0.3))))
    if k >= 34.3:
        best = min(NAMES, key=lambda nm: len(RES[nm][1]))
        rows = [('maze checked before getting out:', ST.muted, 46, INTER)]
        rows += [('%s  %d%%' % (LABEL[nm], round(100 * len(RES[nm][0]) / OPEN)), LANE_COL[nm], 66, FONT) for nm in ORDER]
        longest = max(NAMES, key=lambda nm: len(RES[nm][1]))
        if len(RES[longest][1]) > len(RES[best][1]) * 1.05:
            rows += [('%s’s route: %.1fx longer' % (LABEL[longest], len(RES[longest][1]) / len(RES[best][1])), ST.fg, 50, FONT)]
        if k >= 39: rows = [('A* knows roughly where the exit is.', ST.fg, 50, FONT), ('your maps app runs on the same idea.', ST.muted, 44, INTER)]
        for j, (s, col, sz, fnt) in enumerate(rows):
            t0 = 34.3 if k < 39 else 39.0
            e = float(ease_back((k - t0 - 0.5 * j) / 0.4)); paste(c, text(s, F(fnt, sz), col, stroke=3 if fnt == FONT else 0), W / 2, 820 + 100 * j, e, min(1, e))
        least, most = (round(100 * len(RES[nm][0]) / OPEN) for nm in (min(NAMES, key=lambda nm: len(RES[nm][0])), max(NAMES, key=lambda nm: len(RES[nm][0]))))
        paste(c, text('same maze: %d%% of it searched vs %d%%' % (least, most), F(INTER, 40), ST.muted), W / 2, 1560, 1, float(ease_out((k - 41.5) / 0.6)))
    amp, ph = shake_at(k, HITS, ST)
    o = finish(c, k, amp, ph, 1 + 0.008 * kick, W / 2, H / 2, ST)
    return overlay_fixed(o, ST, k, CL.beats, CREDIT)

if __name__ == '__main__':
    render(frame, CL, sys.argv[1])
