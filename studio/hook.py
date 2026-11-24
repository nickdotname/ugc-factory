"""The line on screen for the first two seconds of a video: a reason to keep watching.

    text = hook.pick(style, seed)          # '' some of the time, so its effect can be measured
    frame = hook.draw(frame, text, t)      # t = seconds into the video; draws nothing after ~2.6s

The band and producer styles also try two ways of showing the line (mode(style, seed)):
    'flash'  a yellow box for the first two seconds, as before
    'hold'   a caption that stays on for the whole video, in the place that style leaves free (draw_hold)
Each recipe records the line ("hook"), its angle ("hook_angle": relatable / curious / plain /
statement for band) and the way it was shown ("hook_mode"), so the stats can say which of each keeps people and gets shared.
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
                      "this is for the overthinkers", "the song you didn't know you needed", "main character walk home song",
                      "your sign to start a band with your friends"],
        'curious':   ["read along", "underrated song alert", "lyrics on screen. sound on"],
        'plain':     ["your pc in 2001:", "class is in session"],
        # Hot takes said, not asked (2026-11-24): the old 'debate' and 'comment' lines ("change my mind", "agree?",
        # "pick one", "skip or replay?", "which line hit hardest?") asked for comments, which is engagement bait
        # (CLAUDE.md), and they were the weakest angle on close__quarters anyway: median 67 views over 8 posts against
        # 76-106 for the others, and about one comment each. Opinions only: nothing here claims a fact or a number.
        'statement': ["rock and rap in one song. on purpose.", "this would've been huge in 2007",
                      "too weird for the radio", "your parents would hate this song",
                      "an album about college, in 15 lessons", "this song is perfect. no notes."],
    },
    'producer': {
        'relatable': ["pov: 3am in the studio", "musicians will understand", "this is what a song looks like inside",
                      "every layer. one screen.", "when the mix finally sits right"],
        'comment':   ["which part would you solo?", "producers: what would you change?", "which stem is carrying?"],
        'curious':   ["the song, pulled apart", "hear it. now see it.", "watch the vocals", "sound on"],
        'plain':     ["lesson of the day"],
    },
}
# rocket.league.lit: our own clips, any of which may be a goal, a save or a demo, so nothing names what happens.
# A line only now and then (NONE_SHARE); which angle earns its place is left to the learner.
ANGLES['rocket'] = {
    'debate':  ["clean or lucky?", "this was pure luck. change my mind", "bronze players could do this",
                "rocket league peaked in 2016. agree?",
                "ball cam on or off? defend yourself", "controller or keyboard? pick a side", "this game is dead. right?"],
    'comment': ["guess our rank", "how many hours to pull this off?", "what rank is this?"],
    'curious': ["wait for it", "rocket league, but on beat", "sound on", "watch the ball", "this is why we can't stop playing",
                "rocket league players will get it"],
}
HOOKS = {
    'producer': [l for ls in ANGLES['producer'].values() for l in ls],
    'band': [l for ls in ANGLES['band'].values() for l in ls],
    'liminal': ["you've been here before", "don't turn around", "3am. the music is still on", "sound on", "have you seen this place?", "no one else is here"],
    # psychedelic.station (2026-11-24): every line true of any psy video (each is drawn by code from the song's own
    # stems; the colours step on the drum hits in every field). Statements that open a question, not instructions.
    'psy': ["this song is drawing this", "no camera. no AI. just this song", "the picture jumps on every drum hit",
            "it never draws the same frame twice", "the bass is moving the picture", "made from the song's own drum track"],
    'rocket': [l for ls in ANGLES['rocket'].values() for l in ls],
}
SHOW, FADE = 2.2, 0.4
_FONT = {}

# Where a held line sits (fraction of the height) in each style: band, under the stack of windows and above
# Instagram's own caption; producer, between the lyrics at the top and the first lane.
HOLD_Y = {'band': 0.775, 'producer': 0.205}
NONE_SHARE = {'band': 0.12, 'producer': 0.12, 'rocket': 0.5, 'psy': 0.5}   # psy: posts with no line were watched more (68 vs 41 median views, n=18/10)     # the rest keep the old quarter: enough "no line" posts to compare against
# (rocket: a line on about two videos in five at first; the learner's 'none' angle can lower that)
# An angle a style opens with some of the time, whatever the learner has found so far: (angle, share). The
# close__quarters trial reels open on a hot take half the time (said as a statement, not a question: statement
# lines out-pull question lines on Reels, and asking for comments is bait); the rest are left to the learner.
LEAD = {'band': ('statement', 0.5)}

def lead(style, seed):
    """The angle this video must open with ('' if it is free to choose)."""
    ang, share = LEAD.get(style, ('', 0))
    return ang if ang and random.Random(seed * 49979687 + 17).random() < share else ''

def pick(style, seed):
    if os.environ.get('CQ_HOOK'): return '' if os.environ['CQ_HOOK'] == 'none' else os.environ['CQ_HOOK']          # the nightly job leaning towards a line that has worked
    r = random.Random(seed * 7919 + 11)
    r2 = random.Random(seed * 104729 + 3)
    if style in ANGLES and lead(style, seed) and not os.environ.get('CQ_HOOK_ANGLE'): return r2.choice(ANGLES[style][lead(style, seed)])
    if r.random() < NONE_SHARE.get(style, 0.25): return ''
    if style in ANGLES:                                   # an angle first, then a line in it, so every angle gets tried
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
