#!/usr/bin/env python3
"""low-poly story page: a "what if" story told in big words, on the beat, over a blocky low-poly town.

    python studio/lowpoly_video.py SONG_DIR SEED OUT.mp4        (CQ_WINDOW="t0,t1" picks the stretch of the song)
    python studio/lowpoly_video.py SONG_DIR SEED SHEET.png --frames 0,60,200   (a contact sheet; renders only those frames' shots)

The stories are ours (studio/lowpoly/stories.txt). Each shot of a story starts on a beat and its caption chunks land
one per beat (two per beat when the song is slow), so the words keep time with the song; the shots are rendered in
Blender (studio/lowpoly/scene.py, run as a separate process: bpy is heavy) and the words drawn on top here.
Knobs (studio/knobs.py): story (which one; nightly.py's FRESH rule keeps it from repeating), caption (yellow or
white-pink word style), pace (a chunk every beat or every half beat), voice (on: the story is read aloud by
studio/voice.py, the caption chunks land on the spoken words, a shot lasts at least as long as its narration, the
song ducks under the voice and its singer is muted; off, or no narrator on this host: silent words on the beat).
The "what if" chunk is on screen from frame 0 either way, so the cover carries the question.
"""
import json, os, random, re, shutil, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import beat as audio
import knobs as K
import polish as _polish

W, H, FPS = 1080, 1920, 30
RW, RH = 720, 1280                         # Blender renders at this size; frames are scaled up under the words
SAFE_TOP, SAFE_BOTTOM = 250, H - 420
STYLES = {'yellow': ((255, 236, 60), (255, 236, 60)), 'pop': ((255, 255, 255), (255, 92, 170))}


def stories():
    out, cur = {}, None
    for line in open(os.path.join(HERE, 'lowpoly', 'stories.txt'), encoding='utf-8'):
        line = line.rstrip('\n')
        if line.startswith('#') or not line.strip(): continue
        if line.startswith('==='): cur = line[3:].strip(); out[cur] = []; continue
        if line.startswith('@') and cur:
            head, *chunks = [x.strip() for x in line[1:].split('|')]
            words = head.split(); kind = words[0]
            place = next((w for w in words[1:] if w in ('kitchen', 'bathroom', 'bedroom')), None)
            eff = ' '.join(w for w in words[1:] if w not in ('kitchen', 'bathroom', 'bedroom'))
            out[cur].append(dict(kind=kind, place=place, effect=eff, chunks=[c for c in chunks if c]))
    return out


def font(size):
    for p in (os.path.join(REPO, 'fonts', 'Montserrat-ExtraBold.ttf'), os.path.join(REPO, 'fonts', 'Anton-Regular.ttf')):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class Video:
    def __init__(self, song_dir, seed, t0, t1):
        self.slug = os.path.basename(os.path.normpath(song_dir)); self.t0, self.t1 = t0, t1
        r = random.Random(seed); self.seed = seed
        bank = stories()
        self.story = K.pick('story', sorted(bank), r)
        self.cap = K.pick('caption', sorted(STYLES), r)
        a = audio.load(self.slug, t0, t1); self.n = n = a['n']; spb = a['spb']
        self.pace = K.pick('pace', ['beat', 'half'], r, weights=[3, 1] if spb < 0.55 else [1, 2])
        beats = [int(round(fr)) for _b, fr in a['beats'] if 0 <= fr < n]
        if self.pace == 'half':
            beats = sorted(set(beats + [int(round((x + y) / 2)) for x, y in zip(beats, beats[1:])]))
        while beats and beats[0] < 4: beats.pop(0)
        beats = [0] + beats
        self.kick = audio.hits(a['kicks'], n, 6.0)
        self.song_dir = song_dir
        self.voice = K.pick('voice', ['on', 'off'], r, weights=[3, 1])   # read aloud or silent: the learner compares
        self.voices, self.vdir = [], None                                  # [(wav, offset_s, dur_s)] of the narration
        story = bank[self.story]
        shots, captions = self.plan_spoken(story, beats, n) if self.voice == 'on' else (None, None)
        if shots is None:
            if self.voice == 'on': self.voice = K.CHOSEN['voice'] = 'off'   # no narrator here: recorded as it really went out
            shots, captions = self.plan_beats(story, beats, n)
        for j, s in enumerate(shots): s['end'] = shots[j + 1]['start'] if j + 1 < len(shots) else n
        last = ('street', None)                                         # a close-up stays where the story is
        for s in shots:
            if s['kind'] == 'room': last = ('room', s['place'])
            elif s['kind'] != 'face': last = ('street', None)
            s['setting'], s['place'] = last[0], s['place'] or last[1]
        self.shots, self.captions = shots, captions
        song = json.load(open(os.path.join(song_dir, 'song.json')))
        self.credit = '♪ %s — %s' % (song.get('title', self.slug).lower(), song.get('artist', 'Close Quarters').lower())
        sans = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        self.f_credit = ImageFont.truetype(sans, 30) if os.path.exists(sans) else font(30)

    @staticmethod
    def plan_beats(story, beats, n):
        """Silent words: the chunks on the beats, spread so the story fills the clip: every chunk gets the same whole
        number of beats, and a shot is never shorter than two of them. -> (shots, [(frame, chunk)])"""
        total = sum(max(1, len(s['chunks'])) for s in story)
        step = max(1, (len(beats) - 1) // max(1, total))
        shots, captions, k = [], [], 0
        for s in story:
            if k >= len(beats) - 1: break
            first = k
            for c in s['chunks']:
                if k >= len(beats): break
                captions.append((beats[k], c)); k += step
            k = max(k, first + 2)
            shots.append(dict(s, start=beats[first], beats=beats[first:min(k, len(beats))]))
        return shots, captions

    def plan_spoken(self, story, beats, n, gap=0.3, speed=1.0):
        """The story read aloud, one narr.speak() per shot: a shot starts on the first beat after the last one's words
        end, lasts at least as long as its narration, and its chunks appear as their first word is spoken (the first
        chunk from frame 0, for the cover). A story too long for the clip is read again a little faster (1.3x at most)
        before its last shots are left out. -> (shots, captions), or (None, None) when there is no narrator here."""
        import voice as narr
        self.vdir = self.vdir or tempfile.mkdtemp(prefix='lowpoly-voice-')
        story = [s for s in story if s['chunks']]
        try:
            spoken = [narr.speak(' '.join(s['chunks']), voice=narr.VOICES['lowpoly_stories'], speed=speed, out_wav=os.path.join(self.vdir, 'v%02d.wav' % j))
                      for j, s in enumerate(story)]
        except narr.VoiceUnavailable as exc:
            print('no voice tonight: %s' % exc, flush=True); self.cleanup(); return None, None
        need = sum(d for _w, d, _t in spoken) + gap * len(spoken) + 0.5 * len(spoken)   # the half second: waiting for a beat
        if need * FPS > n and speed == 1.0:
            return self.plan_spoken(story, beats, n, gap, speed=min(1.3, round(need * FPS / n + 0.02, 2)))
        shots, captions, cursor = [], [], 0; self.voices = []
        for s, (wav, dur, words) in zip(story, spoken):
            start = next((b for b in beats if b >= cursor), None)
            if start is None or start + dur * FPS > n: break                             # cut off mid-sentence is worse than left out
            self.voices.append((wav, start / FPS, dur))
            counts = [len([w for w in c.split() if re.search(r'\w', w)]) for c in s['chunks']]
            lined_up = sum(counts) == len(words); k = 0
            for c, cnt in zip(s['chunks'], counts):
                at = words[min(k, len(words) - 1)][1] if lined_up and words else dur * k / max(1, sum(counts))
                captions.append((0 if not captions else start + int(round(at * FPS)), c)); k += cnt
            cursor = int(np.ceil((start / FPS + dur + gap) * FPS))
            shots.append(dict(s, start=start, beats=[b for b in beats if start <= b < cursor] or [start]))
        if not shots: self.cleanup(); self.voices = []; return None, None
        if len(shots) < len(story): print('voice: %d of %d shots fit the clip at %.2fx' % (len(shots), len(story), speed), flush=True)
        return shots, captions

    def cleanup(self):
        if self.vdir: shutil.rmtree(self.vdir, ignore_errors=True); self.vdir = None

    def render_frames(self, only=None):
        """Blender renders the shots (only those holding the given frames, for a sheet) into a temporary folder."""
        sys.path.insert(0, os.path.join(HERE, 'lowpoly'))
        import fetch; fetch.pull()                                       # the CC0 kits (houses, cars); box houses if they are missing
        tmp = tempfile.mkdtemp(prefix='lowpoly-')
        shots = [s for s in self.shots if only is None or any(s['start'] <= f < s['end'] for f in only)]
        plan = dict(w=RW, h=RH, fps=FPS, seed=self.seed, shots=[dict(start=s['start'], end=s['end'], kind=s['kind'], place=s['place'], setting=s['setting'],
                                                                     effect=s['effect'], beats=s['beats'], only=sorted(only) if only else None) for s in shots])
        json.dump(plan, open(os.path.join(tmp, 'plan.json'), 'w'))
        r = subprocess.run([sys.executable, os.path.join(HERE, 'lowpoly', 'scene.py'), os.path.join(tmp, 'plan.json'), tmp], capture_output=True, text=True)
        if r.returncode: sys.exit('blender failed: ' + r.stderr[-600:])
        return tmp

    def frame(self, i, tmp):
        p = os.path.join(tmp, '%05d.png' % i)
        im = Image.open(p).convert('RGB') if os.path.exists(p) else Image.new('RGB', (RW, RH), (120, 170, 230))
        im = ImageEnhance.Color(im).enhance(1.45); im = ImageEnhance.Contrast(im).enhance(1.08)
        im = im.resize((W, H), Image.BICUBIC)
        d = ImageDraw.Draw(im)
        cur = [(f, c) for f, c in self.captions if f <= i]
        if cur:
            f, c = cur[-1]; age = i - f
            s = 1.0 + 0.18 * max(0.0, 1 - age / 4)
            words = c.upper().split()
            fnt = font(int(118 * s))
            while fnt.getlength(' '.join(words)) > W - 160 and fnt.size > 64: fnt = font(fnt.size - 6)
            lines, row = [], ''
            for w in words:
                t = (row + ' ' + w).strip()
                if fnt.getlength(t) <= W - 160 or not row: row = t
                else: lines.append(row); row = w
            lines.append(row)
            main, accent = STYLES[self.cap]
            y = H * 0.58 - (len(lines) - 1) * fnt.size * 0.55
            for j, ln in enumerate(lines):
                fill = accent if (self.cap == 'pop' and j == len(lines) - 1 and len(lines) > 1) else main
                d.text((W / 2, y), ln, font=fnt, fill=fill, anchor='mm', stroke_width=12, stroke_fill=(0, 0, 0)); y += fnt.size * 1.1
        d.text((W / 2, SAFE_BOTTOM - 24), self.credit, font=self.f_credit, fill=(255, 255, 255), anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))
        return np.asarray(im)

    def render(self, out):
        if '--frames' in sys.argv:
            fs = [int(x) for x in sys.argv[sys.argv.index('--frames') + 1].split(',')]
            tmp = self.render_frames(set(fs)); ims = []
            for i in fs:
                fr = self.frame(min(i, self.n - 1), tmp); ims.append(Image.fromarray(fr).resize((360, 640)))
                if '--full' in sys.argv: Image.fromarray(fr).save(out[:-4] + '_f%d.png' % i)
            sheet = Image.new('RGB', (360 * len(ims), 640))
            for j, im in enumerate(ims): sheet.paste(im, (360 * j, 0))
            sheet.save(out); shutil.rmtree(tmp, ignore_errors=True); self.cleanup()
            print('sheet', out, K.record()['knobs'], [(s['kind'], s['effect'], s['start'], s['end']) for s in self.shots], [(round(o, 2), d) for _w, o, d in self.voices]); return
        tmp = self.render_frames()
        part = out[:-4] + '.part.mp4'
        p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', os.environ.get('CQ_PRESET', 'veryfast'), '-crf', os.environ.get('CQ_CRF', '19'),
                              '-maxrate', os.environ.get('CQ_MAXRATE', '10M'), '-bufsize', os.environ.get('CQ_BUFSIZE', '20M'), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', part], stdin=subprocess.PIPE)
        for i in range(self.n):
            p.stdin.write(self.frame(i, tmp).tobytes())
        p.stdin.close(); p.wait(); shutil.rmtree(tmp, ignore_errors=True)
        aud = out[:-4] + '.m4a'; audio.audio_clip(self.slug, self.t0, self.t1, aud)
        if self.voices:                                                     # the narration over the song, the singer muted under it
            import voice as narr
            song = json.load(open(os.path.join(self.song_dir, 'song.json'))); mixed = out[:-4] + '.voice.m4a'
            try:
                narr.mix(aud, self.voices, mixed, stems=narr.stems_of(self.song_dir), t0=self.t0 - float(song.get('stems_start_sec') or 0))
                os.replace(mixed, aud)
            except RuntimeError as exc:                                     # the clip goes out silent rather than not at all
                print('::warning::voice mix failed, silent clip: %s' % exc, flush=True); self.voice = K.CHOSEN['voice'] = 'off'
        self.cleanup()
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', part, '-i', aud, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', out])
        os.remove(part); os.remove(aud)
        if r.returncode: sys.exit('mux failed')
        json.dump(dict(K.record()), open(out[:-4] + '.json', 'w')); print('done', out, K.record()['knobs'])


Video.frame = _polish.wrap(Video.frame, 'lowpoly')      # bloom, grain, grade, vignette: studio/polish.py

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW'); t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 45.0)
    Video(song_dir, seed, t0, t1).render(out)
