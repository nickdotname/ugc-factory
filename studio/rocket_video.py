#!/usr/bin/env python3
"""rocket.league.lit: our own Rocket League clips to a Close Quarters song.

    python studio/rocket_video.py SONG_DIR SEED OUT.mp4          (CQ_WINDOW="t0,t1": where in the song to start looking)
    python studio/rocket_video.py SONG_DIR SEED SHEET.png --frames 0,60,120

Two formats (the knob `format`), so the learner finds out which one people watch:
  asis     one clip, played straight, with the song under it: the song is started so that a downbeat lands exactly
           on the clip's biggest moment (the goal, the hit). A small punch-in on the kicks; the game's own sound is
           muted (its menu music is not ours to post).
  montage  several clips cut on the bar lines, each cut placed so its clip's best moment lands on the downbeat,
           with a slow-motion run-in to it (knob `ramp`) and a zoom punch on the kicks.
Now and then a line flashes up for the first two seconds (studio/hook.py, 'rocket'), so the learner can see
whether one helps. Framing (knob `frame`): `blur` puts a landscape clip full-width over a blurred, darkened copy of itself; `crop` fills
the frame from the middle of it. Vertical clips fill the frame either way. The moments come from
studio/rocket_lib.py (loud bursts and sudden flashes in each clip).
"""
import json, math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish
import rocket_lib as lib
import hook as _hook

W, H, FPS = 1080, 1920, 30


def font(size):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf')):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class Reader:
    """Frames of one clip at any time (seconds), read in order and cached by frame number."""
    def __init__(self, path):
        self.cap = cv2.VideoCapture(path); self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1; self.pos = -1; self.last = None

    def at(self, t):
        k = int(np.clip(round(t * self.fps), 0, self.n - 1))
        if k < self.pos or k > self.pos + 90:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, k); self.pos = k - 1
        while self.pos < k:
            ok, f = self.cap.read()
            if not ok: break
            self.pos += 1; self.last = f
        return self.last if self.last is not None else np.zeros((1080, 1920, 3), np.uint8)


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); r = random.Random(seed); self.r = r
        self.format = K.pick('format', ['asis', 'montage'], r); self.frame_kind = K.pick('frame', ['blur', 'crop'], r, weights=[2, 1])
        self.ramp = K.pick('ramp', ['slowmo', 'none'], r)
        clips = lib.pull()
        if not clips: sys.exit('the Rocket League library is empty: add clips with studio/rocket_lib.py')
        song = json.load(open(os.path.join(song_dir, 'song.json'))); self.song = song
        spb = 60 / song['tempo']; bar = 4 * spb
        while bar < 1.4: bar *= 2
        self.bar = bar
        downbeat = lambda t: audio.time_of_beat(song, math.ceil(audio.beat_of_time(song, t) / 4) * 4)   # the first bar line at or after t
        if self.format == 'asis':
            c = r.choice(clips); m = c['moments'][0][0] if c['moments'] else c['dur'] / 2
            dur = min(c['dur'], max(8.0, t1 - t0 + 6)); start = max(0.0, min(m - dur * 0.55, c['dur'] - dur))   # the moment a little past the middle
            hit = downbeat(t0 + (m - start))                                  # the song time that lands on the moment
            self.t0 = hit - (m - start); self.t1 = self.t0 + dur
            self.plan = [(0.0, dur, c, start, m - start)]                     # (video from, to, clip, clip start, moment offset)
        else:
            self.t0 = downbeat(t0); n_bars = max(4, min(10, int(round((t1 - t0) / bar))))
            self.t1 = self.t0 + n_bars * bar
            pool = [c for c in clips if c['moments']] or clips; r.shuffle(pool); self.plan = []
            for k in range(n_bars):                                       # one clip a bar; its moment lands half a bar in, on the snare
                c = pool[k % len(pool)]; m = c['moments'][(k // len(pool)) % max(1, len(c['moments']))][0] if c['moments'] else c['dur'] / 2
                lead = bar / 2; pre = lead - 0.25 if self.ramp == 'slowmo' else lead   # clip seconds shown before the moment
                self.plan.append((k * bar, (k + 1) * bar, c, m - pre, lead))
        a = audio.load(self.slug, self.t0, self.t1); self.n = a['n']
        self.kick = audio.hits(a['kicks'], self.n, 8.0); self.snare = audio.hits(a['snares'], self.n, 10.0)
        self.readers = {}
        self.hook = _hook.pick('rocket', seed)                                 # the line flashed for the first two seconds ('' = none)
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        self.f_credit = font(30)

    def reader(self, c):
        if c['asset'] not in self.readers: self.readers[c['asset']] = Reader(os.path.join(lib.CACHE, c['asset']))
        return self.readers[c['asset']]

    def source_time(self, seg, tv):
        """Where in the clip we are tv seconds into the video: straight through, or (slowmo) at half speed for the half
        second before the moment and full speed from it, so the hit still lands where the plan puts it."""
        a, b, c, cs, lead = seg; u = tv - a
        if self.format == 'montage' and self.ramp == 'slowmo':
            if u < lead - 0.5: return cs + u
            if u < lead: return cs + (lead - 0.5) + (u - (lead - 0.5)) * 0.5
            return cs + (lead - 0.25) + (u - lead)
        return cs + u

    def fit(self, f, zoom):
        h, w = f.shape[:2]
        if h >= w or self.frame_kind == 'crop':                               # fill the frame from the middle
            s = max(W / w, H / h) * zoom; f2 = cv2.resize(f, (int(w * s) + 1, int(h * s) + 1), interpolation=cv2.INTER_LINEAR)
            y0 = (f2.shape[0] - H) // 2; x0 = (f2.shape[1] - W) // 2
            return f2[y0:y0 + H, x0:x0 + W]
        bg = cv2.resize(f, (int(w * H / h), H), interpolation=cv2.INTER_AREA); x0 = (bg.shape[1] - W) // 2
        bg = cv2.GaussianBlur(cv2.resize(bg[:, x0:x0 + W], (W // 8, H // 8)), (0, 0), 3); bg = cv2.resize(bg, (W, H)) * 0.45
        s = W / w * zoom; fg = cv2.resize(f, (int(w * s), int(h * s)), interpolation=cv2.INTER_LINEAR)
        y0 = (H - fg.shape[0]) // 2 - 60; x0 = (fg.shape[1] - W) // 2
        out = bg.astype(np.uint8); fg = fg[:, max(0, x0):max(0, x0) + W]
        out[max(0, y0):y0 + fg.shape[0], :fg.shape[1]] = fg[max(0, -y0):H - y0]
        return out

    def frame(self, i):
        tv = i / FPS; seg = next((s for s in self.plan if s[0] <= tv < s[1]), self.plan[-1])
        f = self.reader(seg[2]).at(self.source_time(seg, tv))
        since = tv - seg[0]
        zoom = 1.0 + 0.045 * self.kick[i] + (0.06 * math.exp(-since * 8) if self.format == 'montage' and i > 0 else 0)
        img = self.fit(f, zoom).astype(np.float32)
        if self.format == 'montage' and since < 0.07 and seg[0] > 0: img = img * 0.5 + 127      # a flash on the cut
        if self.snare[i] > 0.7: img *= 1.08
        im = Image.fromarray(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(im)
        tw = d.textlength(self.credit, font=self.f_credit)
        d.rounded_rectangle([W / 2 - tw / 2 - 18, H - 470, W / 2 + tw / 2 + 18, H - 424], 20, fill=(0, 0, 0))
        d.text((W / 2, H - 447), self.credit, font=self.f_credit, fill=(245, 245, 245), anchor='mm')
        return _hook.draw(np.asarray(im), self.hook, tv)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            ims = [Image.fromarray(self.frame(min(f, self.n - 1))).resize((360, 640)) for f in fs]
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for k, im in enumerate(ims): sheet.paste(im, (360 * k, 0))
            sheet.save(out); print('sheet', out, K.record()['knobs'], [round(p[4], 2) for p in self.plan]); return
        tmp = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '20'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', tmp], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i).tobytes())
            if i % 90 == 0: print(i, '/', self.n, flush=True)
        p.stdin.close(); p.wait()
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(tmp); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(dict(K.record(), clips=sorted({s[2]['asset'] for s in self.plan}),
                       plan=dict(hook=self.hook, hook_angle=_hook.angle('rocket', self.hook), hook_mode='flash')), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'rocket')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
