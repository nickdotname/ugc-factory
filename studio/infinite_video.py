#!/usr/bin/env python3
"""Infinite zoom to a song: one dive through a chain of top-down pictures (studio/zoom/index.json, made by
studio/zoom_gen.py with SDXL on Kaggle), from the widest view down to the closest, one layer a bar, looping.
(Not studio/zoom_video.py, which is zoom.into.art's dive into a painting.)

    python studio/infinite_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/infinite_video.py SONG_DIR SEED SHEET.png --frames 0,150,300
    CQ_ZOOM_DIR=dir (0.jpg = closest .. N.jpg = widest) renders a local chain instead of the library.

Layer k+1's middle half is exactly layer k, so zooming in 2x lands on the next picture with no cut: each frame is
drawn from the layer it is in plus the sharper one inside it. The dive moves at a steady exponential pace with a
small push on each kick; the seam (closest picture back to the widest) is a quick crossfade, so the clip loops.
Nothing on screen but a small song credit; the prompts forbid text and faces.
Knobs (studio/knobs.py): chain (theme), pace (layers a bar), grade.
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import zoom_gen

W, H, FPS = 1080, 1920, 30; audio.FPS = FPS


def font(name, size):
    p = os.path.join(REPO, 'fonts', name)
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed)
        if os.environ.get('CQ_ZOOM_DIR'):
            d = os.environ['CQ_ZOOM_DIR']; n = len([f for f in os.listdir(d) if f.endswith('.jpg')])
            paths = [os.path.join(d, '%d.jpg' % k) for k in range(n)]; self.theme = 'local'
        else:
            lib = zoom_gen.pull()
            if not lib: sys.exit('the zoom library is empty: run zoom.yml first')
            self.theme = K.pick('chain', sorted({c['theme'] for c in lib}), r)
            c = r.choice([c for c in lib if c['theme'] == self.theme]); paths = [os.path.join(zoom_gen.CACHE, a) for a in c['assets']]
        self.L = [cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB) for p in paths]           # 0 closest .. N widest
        self.N = len(self.L) - 1
        self.pace = float(K.pick('pace', ['1', '0.5'], r, weights=[3, 2]))                 # layers a bar
        self.grade = K.pick('grade', ['none', 'warm', 'film'], r, weights=[3, 2, 1])
        a = audio.load(self.slug, t0, t1); self.spb = a['spb']; self.kick = audio.hits(a['kicks'], a['n'], 6.0)
        bar = 4 * self.spb * FPS; self.cyc = int(round(self.N / self.pace * bar))
        reps = max(1, int(round(a['n'] / self.cyc))); self.n = self.cyc * reps
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        sans = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        self.f_small = ImageFont.truetype(sans, 28) if os.path.exists(sans) else font('Poppins-Bold.ttf', 26)

    def view(self, depth):
        """the picture at zoom depth (0 = the widest layer whole, N = the closest layer whole)"""
        k = min(self.N, int(math.floor(depth))); f = depth - k; s = 2.0 ** f
        outer = self.L[self.N - k]; h, w = outer.shape[:2]
        cw, ch = w / s, h / s; x0, y0 = (w - cw) / 2, (h - ch) / 2
        M = np.array([[W / cw, 0, -x0 * W / cw], [0, H / ch, -y0 * H / ch]], np.float32)
        img = cv2.warpAffine(outer, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT).astype(np.float32)
        if self.N - k - 1 >= 0:                                              # the sharper inner picture where it sits
            inner = self.L[self.N - k - 1]; iw, ih = W * s / 2, H * s / 2; ix, iy = (W - iw) / 2, (H - ih) / 2
            ihh, iww = inner.shape[:2]
            Mi = np.array([[iw / iww, 0, ix], [0, ih / ihh, iy]], np.float32)
            layer = cv2.warpAffine(inner, Mi, (W, H), flags=cv2.INTER_AREA if s < 1.5 else cv2.INTER_LINEAR).astype(np.float32)
            e = max(2.0, 0.04 * iw)
            xs = np.clip(np.minimum(np.arange(W) - ix, ix + iw - np.arange(W)) / e, 0, 1)
            ys = np.clip(np.minimum(np.arange(H) - iy, iy + ih - np.arange(H)) / e, 0, 1)
            m = (ys[:, None] * xs[None, :])[..., None]
            img = img * (1 - m) + layer * m
        return img

    def frame(self, i):
        j = i % self.cyc; k = float(self.kick[min(i, self.n - 1)])
        d = min(self.N - 1e-4, self.N * j / self.cyc + 0.05 * k)
        img = self.view(d)
        tail = 10
        if j >= self.cyc - tail:                                             # the seam: the closest picture melts into the widest
            a = (j - (self.cyc - tail)) / tail; img = img * (1 - a) + self.view(0.12 * a) * a
        if self.grade == 'warm': img = img * np.array([1.04, 1.0, 0.93], np.float32)
        elif self.grade == 'film': img = img * 0.94 + 10; img[..., 2] *= 0.95
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); dr = ImageDraw.Draw(im)
        dr.text((W / 2, H * 0.83), self.credit, font=self.f_small, fill=(245, 245, 245), anchor='mm', stroke_width=2, stroke_fill=(30, 30, 30))
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], 'loop', self.cyc, 'of', self.n); return
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
        json.dump(K.record(), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 44.0)
    Video(sys.argv[1], int(sys.argv[2]), t0, t1).render(sys.argv[3])
