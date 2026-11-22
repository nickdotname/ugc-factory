"""The line on screen for the first two seconds of a video: a reason to keep watching.

    text = hook.pick(style, seed)          # '' some of the time, so its effect can be measured
    frame = hook.draw(frame, text, t)      # t = seconds into the video; draws nothing after ~2.6s

The band and producer styles also try two ways of showing the line (mode(style, seed)):
    'flash'  a yellow box for the first two seconds, as before
    'hold'   a caption that stays on for the whole video, in the place that style leaves free (draw_hold)
Each recipe records the line ("hook"), its angle ("hook_angle": relatable / share / comment / curious /
plain) and the way it was shown ("hook_mode"), so the stats can say which of each keeps people and gets shared.
"""
import os, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Every line here has to be true of ANY video of its style. Nothing about a particular instrument, a build,
# a drop or an effect on the eye: the line is chosen without knowing what is in the clip. Lines that depend on
# what is playing belong in WHEN, which the renderer only draws from once it has checked the audio.
# For band and producer the lines are grouped by what they ask of the viewer, so the stats can compare angles
# even while each single line has only been posted a few times.
ANGLES = {
    'band': {
        'relatable': ["pov: you found your new favourite band", "songs that sound like 2am", "when the lyrics say what you couldn't",
                      "this is for the overthinkers", "the song you didn't know you needed", "main character walk home song"],
        'share':     ["send this to the friend who'd get it", "send this to your music friend", "play this for someone tonight",
                      "your sign to start a band with your friends"],
        'comment':   ["which line hit hardest?", "rate this song 1-10", "tag who this reminds you of", "wait for the last line. thoughts?"],
        'curious':   ["read along", "nobody is talking about this band", "underrated song alert", "lyrics on screen. sound on"],
        'plain':     ["your pc in 2001:", "class is in session"],
    },
    'producer': {
        'relatable': ["pov: 3am in the studio", "musicians will understand", "this is what a song looks like inside",
                      "every layer. one screen.", "when the mix finally sits right"],
        'share':     ["send this to your producer friend", "show this to someone who makes beats", "save this for your next session"],
        'comment':   ["which part would you solo?", "rate the mix 1-10", "producers: what would you change?", "which stem is carrying?"],
        'curious':   ["the song, pulled apart", "hear it. now see it.", "watch the vocals", "sound on"],
        'plain':     ["lesson of the day"],
    },
}
HOOKS = {
    'producer': [l for ls in ANGLES['producer'].values() for l in ls],
    'band': [l for ls in ANGLES['band'].values() for l in ls],
    'liminal': ["you've been here before", "don't turn around", "3am. the music is still on", "sound on", "have you seen this place?", "no one else is here"],
    'psy': ["sound on", "don't blink", "watch the centre", "let it loop", "what do you see?", "headphones on"],
}
SHOW, FADE = 2.2, 0.4
_FONT = {}

# Where a held line sits (fraction of the height) in each style: band, under the stack of windows and above
# Instagram's own caption; producer, between the lyrics at the top and the first lane.
HOLD_Y = {'band': 0.775, 'producer': 0.205}
NONE_SHARE = {'band': 0.12, 'producer': 0.12}     # the rest keep the old quarter: enough "no line" posts to compare against

def pick(style, seed):
    if os.environ.get('CQ_HOOK'): return '' if os.environ['CQ_HOOK'] == 'none' else os.environ['CQ_HOOK']          # the nightly job leaning towards a line that has worked
    r = random.Random(seed * 7919 + 11)
    if r.random() < NONE_SHARE.get(style, 0.25): return ''
    if style in ANGLES:                                   # an angle first, then a line in it, so every angle gets tried
        r2 = random.Random(seed * 104729 + 3)
        if os.environ.get('CQ_HOOK_ANGLE') in ANGLES[style]: return r2.choice(ANGLES[style][os.environ['CQ_HOOK_ANGLE']])
        return r2.choice(r2.choice(list(ANGLES[style].values())))
    return r.choice(HOOKS.get(style, HOOKS['psy']))

def angle(style, text):
    if not text: return 'none'
    return next((a for a, ls in ANGLES.get(style, {}).items() if text in ls), 'other')

def mode(style, seed):
    if style not in HOLD_Y: return 'flash'
    if os.environ.get('CQ_HOOK_MODE') in ('flash', 'hold'): return os.environ['CQ_HOOK_MODE']
    return 'hold' if random.Random(seed * 15485863 + 5).random() < 0.5 else 'flash'

def _font(size):
    if size not in _FONT:
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, '..', 'fonts', 'Anton-Regular.ttf'), os.path.join(here, '..', 'fonts', 'Montserrat-ExtraBold.ttf')):
            if os.path.exists(p): _FONT[size] = ImageFont.truetype(p, size); break
    return _FONT[size]

def draw(frame, text, t, y=0.115):
    """y is where the box sits, as a fraction of the height: clear of whatever that style keeps at the top."""
    if not text or t >= SHOW + FADE: return frame
    H, W = frame.shape[:2]; size = int(W * 0.105 * (1 + 0.25 * max(0.0, 1 - t / 0.18))); f = _font(size); txt = text.upper()
    while f.getlength(txt) > W * 0.86 and size > 40: size -= 6; f = _font(size)
    tw = f.getlength(txt); x = (W - tw) / 2; y = H * y; pad = size * 0.28
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    d.rectangle([x - pad, y - pad * 0.6, x + tw + pad, y + size * 1.18 + pad * 0.4], fill=(255, 230, 60, 255)); d.text((x, y), txt, font=f, fill=(0, 0, 0, 255))
    a = 1.0 if t < SHOW else max(0.0, 1 - (t - SHOW) / FADE); m = (np.asarray(lay, np.float32)[..., 3:] / 255) * a
    return (frame * (1 - m) + np.asarray(lay, np.float32)[..., :3] * m).astype(np.uint8)

_SF = {}
def _sfont(size):
    if size not in _SF:
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, '..', 'fonts', 'Poppins-Bold.ttf'), os.path.join(here, '..', 'fonts', 'Montserrat-ExtraBold.ttf')):
            if os.path.exists(p): _SF[size] = ImageFont.truetype(p, size); break
        else: _SF[size] = _font(size)
    return _SF[size]

def draw_hold(frame, text, t, y):
    """The line as a native-looking caption that stays for the whole video: white sentence-case text with a dark
    outline on a soft dark pill, wrapped to two lines at most. It eases in over the first fifth of a second."""
    if not text: return frame
    H, W = frame.shape[:2]; size = int(W * 0.062); f = _sfont(size)
    words, lines, cur = text.split(), [], ''
    for w in words:
        c = (cur + ' ' + w).strip()
        if f.getlength(c) <= W * 0.84 or not cur: cur = c
        else: lines.append(cur); cur = w
    lines.append(cur)
    lh = size * 1.22; top = H * y; tw = max(f.getlength(l) for l in lines); pad = size * 0.45
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    d.rounded_rectangle([(W - tw) / 2 - pad, top - pad * 0.55, (W + tw) / 2 + pad, top + lh * len(lines) + pad * 0.35], radius=int(size * 0.5), fill=(0, 0, 0, 120))
    for i, l in enumerate(lines):
        d.text(((W - f.getlength(l)) / 2, top + i * lh), l, font=f, fill=(255, 255, 255, 255), stroke_width=max(2, size // 18), stroke_fill=(0, 0, 0, 255))
    a = min(1.0, t / 0.2); m = (np.asarray(lay, np.float32)[..., 3:] / 255) * a
    return (frame * (1 - m) + np.asarray(lay, np.float32)[..., :3] * m).astype(np.uint8)
