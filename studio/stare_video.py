#!/usr/bin/env python3
"""Stare tests: illusions that happen in your own eyes after you hold them still, to a song (a ready page:
stare.lab, paused until its Instagram account exists; see docs/brain/ready-pages.md).

    python studio/stare_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/stare_video.py SONG_DIR SEED SHEET.png --frames 0,150,300

Three kinds, all drawn here (no footage):
  colour  a landscape in opposite colours with a dot in the middle; on a beat it turns black and white, and for a few
          seconds you see it in colour (a negative afterimage). The grey picture is the real picture's lightness only.
  spiral  a spiral turning at a steady speed; on a beat a still landscape replaces it and seems to swell or shrink
          (the motion aftereffect, the "waterfall illusion").
  chaser  twelve soft discs round a cross, one missing at a time, the gap stepping round on every 16th note; held
          still, the discs fade and a disc of the opposite colour runs round (the "lilac chaser"). At the end the gap
          stops and every disc is back.
The landscapes (studio/stare/scenes.py) are drawn from shapes with a seed: lake at sunset, beach, balloons over
hills, autumn wood, tulip field, aurora, desert. Everything on screen is true of the picture (the grey one really is
grey; the chaser really has no green disc). The stare lasts until a beat 8-14 s in; the last 9 frames fade back
into frame 0 so the reel loops. Knobs (studio/knobs.py): kind, scene, spin (spiral in or out), hold (stare length).
"""
import os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
from stare import scenes as S

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS
PW, PH = 1000, 1000                          # the picture: a square in the middle, clear of Instagram's top and bottom
PX, PY = (W - PW) // 2, 400                  # 400..1400: leaves room under it for the countdown and the credit
CX, CY = W // 2, PY + PH // 2                # the dot sits in the middle of the picture
BG = np.array((128, 128, 128), np.float32)   # mid grey round the picture, so nothing around it skews the afterimage
CHASER = {'lilac': ((236, 142, 236), 'green'), 'teal': ((60, 200, 200), 'pink'), 'gold': ((240, 200, 40), 'blue')}
HOOK = {'colour': 'stare at the dot\nuntil it turns grey', 'spiral': 'stare at the dot\nuntil the spiral stops',
        'chaser': 'stare at the cross.\ndon\'t follow the gap'}
MAX_LEN = 24.0                               # longer stretches are cut to this (the stare is the point, not the length)


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def opposite(rgb):
    """The same picture with its colours turned to their opposites and its lightness kept (so the grey that follows
    has the same light and dark): Lab with a and b negated and pushed a little further."""
    lab = cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)
    lab[..., 1] *= -1.35; lab[..., 2] *= -1.35
    lab[..., 0] = 22 + lab[..., 0] * 0.62          # a softer lightness range leaves room for the colour
    return np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255, 0, 255).astype(np.float32)


def grey(rgb):
    lab = cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)
    L = 22 + lab[..., 0] * 0.62
    g = cv2.cvtColor(np.dstack([L, np.zeros_like(L), np.zeros_like(L)]), cv2.COLOR_Lab2RGB) * 255
    return np.clip(g, 0, 255).astype(np.float32)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir))
        t1 = min(t1, t0 + MAX_LEN); self.t0, self.t1 = t0, t1
        r = random.Random(seed)
        self.kind = K.pick('kind', ['colour', 'colour', 'spiral', 'chaser'], r)
        self.scene = K.pick('scene', sorted(S.SCENES), r)
        self.spin = K.pick('spin', ['in', 'out'], r)
        self.hold = K.pick('hold', ['short', 'long'], r)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; self.spb = a['spb']
        self.kick = audio.hits(a['kicks'], n, 7.0)
        import json
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.title = song.get('title', self.slug)
        self.credit = '♪ %s — %s' % (self.title.lower(), song.get('artist', 'Close Quarters').lower())

        bf = [int(round(f)) for _, f in a['beats'] if 0 <= f < n]
        want = (8.0, 11.0) if self.hold == 'short' else (11.0, 14.0)
        after = 4.5 if self.kind != 'chaser' else 3.0                  # what follows the stare needs a few seconds
        ok = [f for f in bf if want[0] * FPS <= f <= want[1] * FPS and f + after * FPS <= n]
        if not ok: ok = [f for f in bf if 7.5 * FPS <= f and f + after * FPS <= n]
        if not ok: print('not rendered: %.1f s is too short to stare and then look (%s)' % ((t1 - t0), self.slug)); sys.exit(3)
        self.switch = ok[len(ok) // 2] if self.hold == 'short' else ok[-1]
        if self.kind == 'chaser': self.switch = max(f for f in bf if f + after * FPS <= n)   # the chaser runs as long as it can
        self.end = n

        pic = S.draw(self.scene, PW, PH, seed)
        self.pic = pic.astype(np.float32); self.neg = opposite(pic); self.grey = grey(pic)
        self.dom = S.SCENES[self.scene][1]
        self.disc_name = K.pick('disc', sorted(CHASER), r) if self.kind == 'chaser' else None
        self.disc, self.ghost = CHASER[self.disc_name] if self.disc_name else (None, None)

        yy, xx = np.mgrid[0:PH, 0:PW].astype(np.float32)
        dx, dy = xx - PW / 2, yy - PH / 2
        self.rad = np.hypot(dx, dy); self.ang = np.arctan2(dy, dx)
        self.mask = np.clip((PW / 2 - 6 - self.rad) / 3.0, 0, 1)[..., None]       # the spiral's round edge

        # chaser: twelve blurred discs, drawn once each at full strength; a frame adds the eleven that are on
        if self.kind == 'chaser':
            self.discs = []
            for j in range(12):
                th = -np.pi / 2 + j * 2 * np.pi / 12
                m = np.zeros((PH, PW), np.float32)
                cv2.circle(m, (int(PW / 2 + 330 * np.cos(th)), int(PH / 2 + 330 * np.sin(th))), 46, 1.0, -1, cv2.LINE_AA)
                self.discs.append(cv2.GaussianBlur(m, (0, 0), 17))
            sixteenth = self.spb / 4 * FPS
            while sixteenth < 2.6: sixteenth *= 2               # never faster than ~11 steps a second
            self.step = sixteenth
            self.beat0 = bf[0] if bf else 0

        self.f_hook = font('Montserrat-ExtraBold.ttf', 64); self.f_mid = font('Figtree.ttf', 46); self.f_two = font('Montserrat-ExtraBold.ttf', 50)
        self.f_small = font('Figtree.ttf', 36); self.f_credit = font('DejaVuSansMono-Bold.ttf', 26)
        self._first = None

    def spiral(self, i):
        """A six-armed log spiral turning at one steady speed (adaptation needs steady motion, so not on the beat)."""
        w = 2 * np.pi * 0.55 * i / FPS * (1 if self.spin == 'out' else -1)
        v = np.sin(6 * self.ang + 9.0 * np.log(self.rad + 8.0) - 6 * w)
        v = np.clip(v * 3.0, -1, 1) * 0.5 + 0.5
        c1, c2 = np.array(self.dom, np.float32), np.array((250, 250, 245), np.float32)
        img = c2 * (1 - v[..., None]) + c1 * v[..., None]
        return img * self.mask + BG * (1 - self.mask)

    def chaser(self, i, gap=True):
        img = np.empty((PH, PW, 3), np.float32); img[:] = (176, 176, 176)
        miss = int((i - self.beat0) // self.step) % 12 if gap else -1
        cov = sum(d for j, d in enumerate(self.discs) if j != miss)
        col = np.array(self.disc, np.float32)
        return img * (1 - cov[..., None]) + col * cov[..., None]

    def picture(self, i):
        if self.kind == 'colour': return self.neg if i < self.switch else self.grey
        if self.kind == 'spiral': return self.spiral(i) if i < self.switch else self.pic
        return self.chaser(i, gap=i < self.switch)

    def draw(self, i, top=True):
        img = np.empty((H, W, 3), np.float32); img[:] = BG
        img[PY:PY + PH, PX:PX + PW] = self.picture(i)
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        stare = i < self.switch
        # the fixation mark: a dot (or a cross for the chaser), and a thin ring that fills while you stare
        k = float(self.kick[min(i, self.n - 1)])
        if self.kind == 'chaser':
            d.line([(CX - 18, CY), (CX + 18, CY)], fill=(20, 20, 20), width=5); d.line([(CX, CY - 18), (CX, CY + 18)], fill=(20, 20, 20), width=5)
        else:
            rr = 9
            d.ellipse([CX - rr - 3, CY - rr - 3, CX + rr + 3, CY + rr + 3], fill=(255, 255, 255))
            d.ellipse([CX - rr, CY - rr, CX + rr, CY + rr], fill=(10, 10, 10))
        if stare:
            u = i / max(1, self.switch)
            d.arc([CX - 34, CY - 34, CX + 34, CY + 34], -90, -90 + 360 * u, fill=(255, 255, 255), width=3)
        ink, sub = (250, 250, 250), (225, 225, 225)
        if stare:
            d.multiline_text((W / 2, 320), HOOK[self.kind], font=self.f_hook, fill=ink, anchor='mm', align='center', spacing=12)
            left = (self.switch - i) / FPS
            d.text((W / 2, 1436), '%d' % int(np.ceil(left)), font=font('DejaVuSansMono-Bold.ttf', int(54 + 10 * k)), fill=sub, anchor='mm')
        else:
            top_on = top; dt = (i - self.switch) / FPS
            if self.kind == 'colour':
                top = 'keep your eyes on the dot' if dt < 1.4 else 'the picture is black and white.\nthe colour is in your eyes'
            elif self.kind == 'spiral':
                top = 'keep your eyes on the dot' if dt < 1.4 else 'this picture is not moving'
            else:
                top = 'every disc is %s.\nthere was never a %s one' % (self.disc_name, self.ghost)
            if top_on: d.multiline_text((W / 2, 320), top, font=self.f_hook if '\n' not in top else self.f_two, fill=ink, anchor='mm', align='center', spacing=12)
        d.text((W / 2, 1484), self.credit, font=self.f_credit, fill=sub, anchor='mm')   # inside Instagram's safe area
        return np.asarray(im)

    def frame(self, i):
        tail = 9; o = self.draw(i, top=i < self.n - tail - 4)      # the last line clears just before the fade, so two lines never cross
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
            sheet.save(out); print('sheet', out, K.record()['knobs'], self.n, 'frames', 'switch', self.switch); return
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
        import json
        rec = K.record(); rec['pictures'] = 'drawn in code (studio/stare/scenes.py)'
        json.dump(rec, open(out[:-4] + '.json', 'w')); print('done', out, rec['knobs'])


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 52.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
