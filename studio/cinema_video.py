#!/usr/bin/env python3
"""Text-mode cinema: a real public-domain film clip played back as coloured ASCII, in a terminal, to one song.

    python studio/cinema_video.py SONG_DIR SEED OUT.mp4 [--frames a,b,c]     (CQ_WINDOW="t0,t1"; CQ_FILM=theme or query)

Each frame of the clip (a rocket launch, a 1920s fairground, the Brooklyn Bridge, a Méliès trick film) is cut into a
grid of letter cells; every cell takes the letter whose ink matches its brightness and the colour of the film under
it. The kick pushes the camera in, the snare flashes the brightest letters white, the bass lifts the glow. Around it, a
terminal: the command that is "playing" the file, a progress bar, the song credit.
Knobs: cell (letter size), ramp (which letters), look (true colour, phosphor green, amber), crt (scanlines on/off).
"""
import json, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import footage

W, H, FPS = 1080, 1920, 30
MONO = next(p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', os.path.join(REPO, 'fonts', 'DejaVuSansMono.ttf')) if os.path.exists(p))
RAMPS = {'classic': " .'`^,:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
         'blocks': " .:-=+*#%@",
         'dots': " .·:•●"}
LOOKS = {'phosphor': [(10, 40, 20), (60, 220, 120), (210, 255, 220)], 'amber': [(40, 20, 0), (255, 160, 30), (255, 235, 190)]}


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed)
        self.cell = int(K.pick('cell', [12, 14, 18], r, weights=[2, 3, 1]))
        self.ramp_name = K.pick('ramp', ['classic', 'blocks', 'dots'], r, weights=[4, 2, 1])
        self.look = K.pick('look', ['colour', 'phosphor', 'amber'], r, weights=[4, 2, 1])
        self.crt = K.pick('crt', ['on', 'off'], r) == 'on'
        want = os.environ.get('CQ_FILM', '')
        clips = [c for c in footage.pull(('space', 'archive', 'silent', 'nyc', 'city')) if c.get('motion', 0) >= 4]
        pick = [c for c in clips if want and want in (c['theme'], c['query'])] or clips
        c = pick[r.randrange(len(pick))]; self.clip = c
        K.MENU['source'] = sorted({x['query'] for x in clips}); K.CHOSEN['source'] = c['query']
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']
        self.kick = audio.hits(a['kicks'], n, 5.0); self.snare = audio.hits(a['snares'], n, 9.0)
        self.bass = np.convolve(a['bass'], np.ones(3) / 3, 'same')
        cap = cv2.VideoCapture(os.path.join(footage.CACHE, c['asset'])); self.frames = []
        while len(self.frames) < n:
            ok, f = cap.read()
            if not ok:
                if not self.frames: sys.exit('could not read ' + c['asset'])
                self.frames += self.frames[::-1]; continue
            self.frames.append(f)
        # the letter atlas: one tile per character, sorted by how much ink it has
        self.cw = self.cell; self.ch = int(self.cell * 1.75)
        f = ImageFont.truetype(MONO, int(self.ch * 0.86)); chars = RAMPS[self.ramp_name]
        tiles = []
        for ch in chars:
            im = Image.new('L', (self.cw, self.ch)); ImageDraw.Draw(im).text((self.cw / 2, self.ch / 2), ch, font=f, fill=255, anchor='mm')
            tiles.append(np.asarray(im, np.float32) / 255)
        order = np.argsort([t.sum() for t in tiles]); self.atlas = np.stack([tiles[k] for k in order])
        self.AX, self.AY = 0, 220                                   # the picture sits under the terminal's title bar
        self.cols = W // self.cw; self.rows = (H - 220 - 330) // self.ch
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — close quarters' % song.get('title', self.slug).lower()
        year = ''.join(ch for ch in (c.get('licence') or '') if ch.isdigit())[-4:]
        self.fname = '%s%s.mp4' % (c['query'].replace(' ', '_').lower(), '_' + year if year else '')
        self.f_ui = ImageFont.truetype(MONO, 26); self.f_small = ImageFont.truetype(MONO, 22)

    def letters(self, i):
        f = self.frames[min(i, len(self.frames) - 1)]; h, w = f.shape[:2]
        zoom = 1.0 + 0.07 * self.kick[i]
        aspect = (self.cols * self.cw) / (self.rows * self.ch)
        cw_, ch_ = (h * aspect, h) if w / h > aspect else (w, w / aspect)
        cw_, ch_ = cw_ / zoom, ch_ / zoom
        x0, y0 = int((w - cw_) / 2), int((h - ch_) / 2)
        small = cv2.resize(f[y0:y0 + int(ch_), x0:x0 + int(cw_)], (self.cols, self.rows), interpolation=cv2.INTER_AREA).astype(np.float32)
        rgb = small[..., ::-1]
        L = rgb @ np.array([0.299, 0.587, 0.114], np.float32) / 255
        lo, hi = max(np.percentile(L, 2), 0.04), max(np.percentile(L, 99.5), 0.25)
        L = np.clip((L - lo) / (hi - lo), 0, 1)
        L = np.where(L < 0.06, 0, L) ** 0.75                        # dark film grain stays blank, not noise; midtones lifted
        grey = rgb.mean(-1, keepdims=True)
        bw = np.abs(rgb - grey).mean() < 6
        if self.look != 'colour' or bw:
            g = np.array(LOOKS['phosphor' if (bw and self.look == 'colour') else self.look], np.float32)
            u = L[..., None]; col = np.where(u < 0.5, g[0] + (g[1] - g[0]) * u * 2, g[1] + (g[2] - g[1]) * (u - 0.5) * 2)
        else:
            col = np.clip(grey + 1.5 * (rgb - grey), 0, 255) * (0.55 + 0.6 * L[..., None]) + 30 * L[..., None]
        if self.snare[i] > 0.5: col = np.where((L > 0.85)[..., None], 255.0, col)
        idx = np.clip((L * (len(self.atlas) - 1)).round().astype(int), 0, len(self.atlas) - 1)
        mask = self.atlas[idx].transpose(0, 2, 1, 3).reshape(self.rows * self.ch, self.cols * self.cw)
        big = np.repeat(np.repeat(col, self.ch, 0), self.cw, 1)
        layer = mask[..., None] * big + 0.10 * big                  # each letter on a faint wash of its own colour (an ANSI background)
        small = cv2.resize(layer, (layer.shape[1] // 3, layer.shape[0] // 3), interpolation=cv2.INTER_AREA)
        glow = cv2.resize(cv2.GaussianBlur(small, (0, 0), 3), layer.shape[1::-1]) * (0.7 + 0.6 * self.bass[i])
        out = np.clip(layer + glow, 0, 255)
        if self.crt: out[1::3] *= 0.72
        return out

    def frame(self, i):
        img = np.full((H, W, 3), (12, 12, 14), np.float32)
        a = self.letters(i); img[self.AY:self.AY + a.shape[0], :a.shape[1]] = a
        im = Image.fromarray(img.astype(np.uint8)); d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, 150], fill=(28, 28, 32))
        for k, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]): d.ellipse([28 + k * 38, 58, 52 + k * 38, 82], fill=c)
        d.text((W / 2, 70), 'tty — 80×%d — play' % self.rows, font=self.f_small, fill=(150, 150, 160), anchor='mm')
        d.text((28, 175), '$ play --ascii %s' % self.fname, font=self.f_ui, fill=(126, 231, 135), anchor='lm')
        by = H - 250; p = (i + 1) / self.n
        bar = int(36 * p); d.text((28, by), '[' + '#' * bar + '.' * (36 - bar) + '] %3d%%' % int(100 * p), font=self.f_ui, fill=(200, 200, 210))
        d.text((28, by + 50), 'frame %04d  %d×%d letters  %s' % (i, self.cols, self.rows, (self.clip.get('licence') or 'public domain').lower()[:30]), font=self.f_small, fill=(120, 120, 130))
        d.text((28, by + 100), self.credit, font=self.f_ui, fill=(230, 230, 235))
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(f)).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs']); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                              '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n): p.stdin.write(self.frame(i).tobytes())
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(dict(K.record(), footage=[self.clip['key']]), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
