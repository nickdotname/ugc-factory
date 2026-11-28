#!/usr/bin/env python3
"""Add a new band dance video to the cut-out library (studio/lofi/index.json, release lofi-library).

    python studio/lofi_add.py fetch REEL_LINK OUT.mp4 [--account close_quarters_ig]   # our own reel, through the Graph API
    python studio/lofi_add.py match VIDEO                      # which song is playing, and from which second
    python studio/lofi_add.py cut VIDEO OUT_DIR --id plaza --who a,b [--clean-watermark]
    python studio/lofi_add.py index --id plaza --song SLUG --offset S --frames N --who a,b --source NAME [--trial]

`fetch` downloads one of our own reels by its link through the Graph API (the account's token from accounts.yaml), which
gives the posted video without the "@account" stamp a saved reel carries. Instagram leaves media_url out of a reel whose
sound it holds rights to; then the operator's phone file is the way in. Run from Actions (lofi-from-reel.yml): cloud
sessions cannot reach Instagram.

`match` finds the song by its music: a coarse chroma + onset match against every master in studio/songs, then the
exact second by cross-correlating the raw audio (it refuses anything under 0.4 correlation, so a video with other
music, or none, is not filed under a song it is not).

`cut` writes one cut-out tar per person (<id>_<who>1.tar): frames at 10 a second, 540x960, the person kept with a
person-segmentation model (mediapipe's selfie model, bundled in `pip install mediapipe==0.10.14`, Python 3.11; no
download) and everything else transparent. With two people in frame they are told apart left to right (--who a,b:
left is a, right is b; a = cap / long coat, b = curly hair) and followed frame to frame, so each becomes its own clip
and the cut-out styles can stage them apart (duo). --clean-watermark paints out thin near-white text over the people
(Instagram's moving "@account" stamp on a video saved from the app) before cutting: the original phone file is
always better, because the stamp also costs a Reel its reach.

`index` adds the clips to studio/lofi/index.json; upload the tars to the lofi-library release beside the others.
`trial: true` on a clip makes every video built from it go out as a trial reel (src/cli.py), so new footage can be
tested on non-followers while the band account itself posts normal reels.
"""
import argparse, glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); SR = 22050


def match(video):
    import subprocess, tempfile
    import numpy as np, librosa
    from scipy.signal import fftconvolve
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, 'a.wav')
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', video, '-vn', '-ac', '1', '-ar', str(SR), wav], check=True)
        y, _ = librosa.load(wav, sr=SR)
    hop = 512

    def feat(x):
        c = librosa.feature.chroma_cqt(y=x, sr=SR, hop_length=hop); c = c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)
        o = librosa.onset.onset_strength(y=x, sr=SR, hop_length=hop); return c, (o - o.mean()) / (o.std() + 1e-9)
    cq, oq = feat(y); n = cq.shape[1]; best = []
    for sd in sorted(glob.glob(os.path.join(HERE, 'songs', '*', ''))):
        m = glob.glob(os.path.join(sd, 'master.*'))
        if not m: continue
        s, _ = librosa.load(m[0], sr=SR); cs, os_ = feat(s); top = (-9.0, 0)
        for k in range(0, cs.shape[1] - n, 2):
            w = os_[k:k + n]
            sc = float((cs[:, k:k + n] * cq).sum() / n) + 0.3 * float(np.dot(w - w.mean(), oq) / n / (w.std() + 1e-9))
            if sc > top[0]: top = (sc, k)
        best.append((top[0], os.path.basename(os.path.normpath(sd)), top[1] * hop / SR, m[0]))
    best.sort(reverse=True); score, slug, coarse, master = best[0]
    a = max(0.0, coarse - 10); s, _ = librosa.load(master, sr=SR, offset=a, duration=len(y) / SR + 20)
    c = fftconvolve(s, y[::-1], mode='valid'); k = int(np.argmax(np.abs(c)))
    r = float(np.corrcoef(s[k:k + len(y)], y)[0, 1]); off = round(a + k / SR, 3)
    print('song %s from %.3f s (correlation %.2f; next best %s)' % (slug, off, r, best[1][1] if len(best) > 1 else '-'))
    if r < 0.4: sys.exit('the music does not line up with any song closely enough (%.2f): not filed' % r)
    return slug, off


def fetch(link, out, account='close_quarters_ig'):
    import re, urllib.parse, urllib.request, yaml
    code = re.search(r'/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)', link)
    if not code: sys.exit('not a reel link: %s' % link)
    code = code.group(1)
    acc = next(a for a in yaml.safe_load(open(os.path.join(os.path.dirname(HERE), 'accounts.yaml')))['accounts'] if a.get('name') == account)
    token = os.environ.get(acc.get('api_key_secret') or 'IG_TOKEN', '')
    if not token: sys.exit('%s is not set (the token for %s)' % (acc.get('api_key_secret'), account))
    url = 'https://graph.facebook.com/v21.0/%s/media?%s' % (acc['channel_id'], urllib.parse.urlencode(
        {'fields': 'id,permalink,shortcode,media_type,media_url,timestamp', 'limit': 100, 'access_token': token}))
    for _ in range(20):                                  # newest first, 100 a page: the reel is in the first few pages
        page = json.load(urllib.request.urlopen(url, timeout=60))
        for m in page.get('data', []):
            if m.get('shortcode') == code or code in (m.get('permalink') or ''):
                if not m.get('media_url'): sys.exit('Instagram gives no media_url for this reel (its sound is licensed): use the phone file')
                urllib.request.urlretrieve(m['media_url'], out); print('fetched %s (%s, %s) -> %s' % (code, m.get('media_type'), m.get('timestamp'), out)); return out
        url = (page.get('paging') or {}).get('next')
        if not url: break
    sys.exit('no reel %s on %s' % (code, account))


def clean_watermark(rgb, person):
    """Paint out thin near-white strokes (a saved-from-Instagram stamp) where they lie over a person."""
    import cv2, numpy as np
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV); v, s = hsv[..., 2], hsv[..., 1]
    hat = cv2.morphologyEx(v, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11)))
    text = ((hat > 40) & (s < 80) & (v > 140)).astype(np.uint8)
    text &= cv2.dilate(person.astype(np.uint8), np.ones((15, 15), np.uint8))
    if not text.any(): return rgb
    text = cv2.dilate(text, np.ones((3, 3), np.uint8))
    return cv2.inpaint(rgb, text * 255, 4, cv2.INPAINT_TELEA)


def _fine_mask(seg, rgb, box):
    """The model again on a padded crop around one person, scaled up: the full-frame mask is 256 px across and gives
    blocky hair and holes in dark clothes; on a crop the same model sees the person at four times the detail."""
    import cv2, numpy as np
    x0, y0, x1, y1 = box; h, w = rgb.shape[:2]
    px, py = int((x1 - x0) * 0.35) + 12, int((y1 - y0) * 0.12) + 12
    x0, y0, x1, y1 = max(0, x0 - px), max(0, y0 - py), min(w, x1 + px), min(h, y1 + py)
    crop = rgb[y0:y1, x0:x1]; s = 640 / max(crop.shape[:2])
    big = cv2.resize(crop, (max(8, int(crop.shape[1] * s)), max(8, int(crop.shape[0] * s))), interpolation=cv2.INTER_CUBIC)
    m = cv2.resize(seg.process(big).segmentation_mask, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
    out = np.zeros((h, w), np.float32); out[y0:y1, x0:x1] = m
    return out


def _fill(mask):
    """A body mask with its holes filled (dark trousers read as background in places)."""
    import cv2, numpy as np
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    inv = (1 - m).astype(np.uint8); n, lab, st, _ = cv2.connectedComponentsWithStats(inv)
    h, w = m.shape
    for i in range(1, n):
        x, y, bw, bh, a = st[i]
        if x > 0 and y > 0 and x + bw < w and y + bh < h: m[lab == i] = 1      # enclosed: a hole, not the outside
    return m.astype(bool)


def _look(rgb, region):
    """What a person looks like (hue x saturation histogram of their pixels): Dylan's scarf, grey shirt and long coat
    against Nick's black shirt and bare arms tell them apart better than where they stand, since they cross."""
    import cv2, numpy as np
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1], region.astype(np.uint8), [18, 8], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


def cut(video, out_dir, cid, who, clean=False):
    import io, subprocess, tarfile, tempfile
    import cv2, numpy as np
    from PIL import Image
    try: import mediapipe as mp
    except ImportError: sys.exit('needs mediapipe==0.10.14 (Python 3.11): pip install mediapipe==0.10.14')
    seg = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=0)
    os.makedirs(out_dir, exist_ok=True); labels = who.split(',')
    with tempfile.TemporaryDirectory() as td:
        full = os.path.join(td, 'full'); os.makedirs(full)               # the frames at the video's own size, for the final crop
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', video, '-vf', 'fps=10', os.path.join(full, '%04d.png')], check=True)
        H0, W0 = cv2.imread(os.path.join(full, '0001.png')).shape[:2]   # as displayed (a phone video's rotation is applied)
        WW, HH = (int(round(W0 * 960 / max(W0, H0))) // 2 * 2, int(round(H0 * 960 / max(W0, H0))) // 2 * 2)   # the working size: longest side 960
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', video, '-vf', 'fps=10,scale=%d:%d' % (WW, HH), os.path.join(td, '%04d.png')], check=True)
        names = sorted(f for f in os.listdir(td) if f.endswith('.png'))
        cuts = {w: {} for w in labels}                                  # who -> frame -> (alpha 540x960, box, split)
        tars = {w: tarfile.open(os.path.join(out_dir, '%s_%s1.tar' % (cid, w)), 'w') for w in labels}
        pos, vel, ref = {}, {w: 0.0 for w in labels}, {}; held = {w: {} for w in labels}; kept = {w: 0 for w in labels}; cols = np.arange(WW)[None, :]
        for name in names:
            rgb = cv2.cvtColor(cv2.imread(os.path.join(td, name)), cv2.COLOR_BGR2RGB)
            m = seg.process(rgb).segmentation_mask
            body = cv2.morphologyEx((m > 0.5).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
            n, lab, st, cen = cv2.connectedComponentsWithStats(body)
            blobs = sorted([i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 0.004 * body.size], key=lambda i: -st[i, cv2.CC_STAT_AREA])[:len(labels)]
            regions = []; split = False
            if len(labels) == 2 and len(blobs) == 1 and len(pos) == 2:       # touching: split between where they are heading
                guess = sorted(pos[w] + vel[w] for w in labels); mid = int(sum(guess) / 2); whole = lab == blobs[0]
                prof = np.convolve(whole.sum(0), np.ones(9) / 9, "same")
                bx0, bw = st[blobs[0], cv2.CC_STAT_LEFT], st[blobs[0], cv2.CC_STAT_WIDTH]      # search inside the shape, never its empty edges
                lo, hi = max(bx0 + bw // 5, mid - 70), min(bx0 + bw - bw // 5, mid + 70)
                if hi <= lo: lo, hi = bx0 + bw // 3, bx0 + 2 * bw // 3 + 1
                cut_x = lo + int(np.argmin(prof[lo:hi]))                 # the narrowest column near the middle: the gap between them
                regions = [whole & (cols < cut_x), whole & (cols >= cut_x)]
                split = prof[cut_x] > 0.35 * prof.max()                 # no real gap there (overlapping, not just touching): hold a clean frame
            else:
                regions = [lab == i for i in blobs]
            regions = [r for r in regions if r.any()]
            xs = [float(np.mean(np.nonzero(r)[1])) for r in regions]
            parts = {}; looks = [_look(rgb, r) for r in regions]
            if not ref and len(regions) == len(labels):                     # the first frame with everyone apart: left to right as --who says
                for w, j in zip(labels, np.argsort(xs)): parts[w] = regions[j]; ref[w] = looks[j]
            elif ref:                                                       # then by how each one looks, where they stand breaking a near tie
                pred = {w: pos.get(w, WW / 2) + vel[w] for w in labels}
                dist = lambda w, j: cv2.compareHist(ref[w], looks[j], cv2.HISTCMP_BHATTACHARYYA) + 0.15 * abs(xs[j] - pred[w]) / WW
                if len(regions) == 2 and len(labels) == 2:
                    a, b = labels; keep = dist(a, 0) + dist(b, 1) <= dist(a, 1) + dist(b, 0)
                    parts = {a: regions[0], b: regions[1]} if keep else {a: regions[1], b: regions[0]}
                elif regions:
                    w = min(labels, key=lambda w: dist(w, 0)); parts[w] = regions[0]
            for w, r in parts.items():
                x = float(np.mean(np.nonzero(r)[1])); vel[w] = 0.6 * vel[w] + 0.4 * (x - pos[w]) if w in pos else 0.0; pos[w] = x
            src = rgb                                                  # the stamp is painted out on the full-size frame, at the end
            for w in labels:
                if w not in parts: continue
                ys, xs_ = np.nonzero(parts[w]); box = (int(xs_.min()), int(ys.min()), int(xs_.max()) + 1, int(ys.max()) + 1)
                fine = _fine_mask(seg, src, box)
                near = cv2.dilate(parts[w].astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
                other = np.zeros_like(near)
                for o in labels:
                    if o != w and o in parts: other |= parts[o]
                solid = _fill((fine > 0.5) & near & ~other)
                soft = np.clip((fine - 0.25) / 0.5, 0, 1) * near * ~other
                alpha = (np.maximum(soft, cv2.GaussianBlur(solid.astype(np.float32), (3, 3), 0) * cv2.erode(solid.astype(np.uint8), np.ones((3, 3), np.uint8))) * 255).astype(np.uint8)
                cuts[w][name[:-4]] = (alpha, box, split, body)
        # Framed like the other clips (a person 85% of the frame's height, standing on its bottom edge, centred): the crop
        # follows each one sideways, smoothed, and is taken from the full-size frame so nothing is blown up much.
        for w in labels:
            ks = sorted(cuts[w])
            if not ks: continue
            # per frame, so the clip's own cuts between wide and close shots keep the person the same size; a 5-frame
            # median steadies it without dragging across a cut
            med = lambda v: np.array([np.median(v[max(0, i - 2):i + 3]) for i in range(len(v))], np.float32)
            tops = med(np.array([cuts[w][k][1][1] for k in ks], np.float32)); bots = med(np.array([cuts[w][k][1][3] for k in ks], np.float32))
            cxs = med(np.array([(cuts[w][k][1][0] + cuts[w][k][1][2]) / 2 for k in ks], np.float32))
            area = {}
            for k, top, bot, c in zip(ks, tops, bots, cxs):
                alpha, box, split, body = cuts[w][k]
                ch = min(float(HH), max(80.0, bot - top) / 0.85); cw = min(float(WW), ch * 9 / 16); ch = cw * 16 / 9
                y0w = min(max(0.0, bot + 0.04 * ch - ch), max(0.0, HH - ch))
                rgb = cv2.cvtColor(cv2.imread(os.path.join(full, k + '.png')), cv2.COLOR_BGR2RGB); H, Wd = rgb.shape[:2]; f = H / HH
                a_full = cv2.resize(alpha, (Wd, H), interpolation=cv2.INTER_LINEAR)
                if clean: rgb = clean_watermark(rgb, cv2.resize(body.astype(np.uint8), (Wd, H), interpolation=cv2.INTER_NEAREST).astype(bool))
                x0 = int(round(min(max(0.0, c - cw / 2), WW - cw) * f)); y0 = int(round(y0w * f)); x1 = min(Wd, x0 + int(round(cw * f))); y1 = min(H, y0 + int(round(ch * f)))
                im = Image.fromarray(rgb[y0:y1, x0:x1]).convert('RGB'); im.putalpha(Image.fromarray(a_full[y0:y1, x0:x1]))
                im = im.resize((540, 960), Image.LANCZOS); area[k] = float(np.asarray(im)[..., 3].mean())
                buf = io.BytesIO(); im.save(buf, 'WEBP', quality=82, method=4); held[w][k] = (buf.getvalue(), split)
            typical = float(np.median(list(area.values())))
            for k, v in area.items():                                    # all but gone (a flash at a cut in the source): hold too
                if v < 0.25 * typical: held[w][k] = (held[w][k][0], True)
        for w in labels:                    # a frame cut down a straight line while they touch holds the nearest clean one instead
            good = sorted(k for k, (_, sp) in held[w].items() if not sp)
            for name in names:                                          # a frame the model lost them in: hold too, never a blank
                if name[:-4] not in held[w] and good: held[w][name[:-4]] = (b'', True)
            for k in sorted(held[w]):
                data, sp = held[w][k]
                if sp and good: data = held[w][min(good, key=lambda g: abs(int(g) - int(k)))][0]
                ti = tarfile.TarInfo('%s_%s1/%s.webp' % (cid, w, k)); ti.size = len(data); tars[w].addfile(ti, io.BytesIO(data)); kept[w] += 1
            print('%s_%s1: %d of %d frames held over a crossing' % (cid, w, sum(sp for _, sp in held[w].values()), len(held[w])))
        for t in tars.values(): t.close()
    for w in labels: print('%s_%s1: %d frames -> %s' % (cid, w, kept[w], os.path.join(out_dir, '%s_%s1.tar' % (cid, w))))
    return len(names)


def add_index(cid, song, offset, frames, who, source, trial, outdoors=False):
    p = os.path.join(HERE, 'lofi', 'index.json'); idx = json.load(open(p))
    for w in who.split(','):
        entry = dict(id='%s_%s1' % (cid, w), song=song, offset=offset, frames=frames, fps=10, who=w, asset='%s_%s1.tar' % (cid, w), source=source)
        if trial: entry['trial'] = True
        if outdoors: entry['outdoors'] = True          # the cut-out style's 'our living room' line stays off it
        idx['clips'] = [c for c in idx['clips'] if c['id'] != entry['id']] + [entry]
    json.dump(idx, open(p, 'w'), indent=1); open(p, 'a').write('\n'); print('index:', len(idx['clips']), 'clips')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['fetch', 'match', 'cut', 'index']); ap.add_argument('--account', default='close_quarters_ig'); ap.add_argument('video', nargs='?'); ap.add_argument('out', nargs='?')
    for k in ('id', 'who', 'song', 'source'): ap.add_argument('--' + k)
    ap.add_argument('--offset', type=float); ap.add_argument('--frames', type=int)
    ap.add_argument('--trial', action='store_true'); ap.add_argument('--outdoors', action='store_true'); ap.add_argument('--clean-watermark', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'fetch': fetch(a.video, a.out, a.account)
    elif a.cmd == 'match': match(a.video)
    elif a.cmd == 'cut': cut(a.video, a.out, a.id, a.who or 'a,b', a.clean_watermark)
    else: add_index(a.id, a.song, a.offset, a.frames, a.who or 'a,b', a.source, a.trial, a.outdoors)
