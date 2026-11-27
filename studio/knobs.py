"""Every choice a video makes that the learner can steer, in one place.

A renderer asks for each choice through this module instead of rolling its own dice:

    field = knobs.pick('field', ['kaleido', 'tunnel', 'bryce', 'bryce'], rng)     # repeats = the default odds
    grain = knobs.flag('grain', 0.5, rng)

and gets the renderer's own random pick, unless the nightly job chose that knob for this video
(CQ_KNOBS='{"field": "tunnel", "grain": "true"}'), in which case it gets that. The dice are rolled either
way, so forcing one knob never changes what the others come out as.

Every knob asked for is recorded with its whole menu: the renderer writes knobs.record() into the
video's .json, nightly.py keeps it in recipes.json, learn.py scores every knob's options from the posts'
numbers, and nightly.py chooses the next videos' knobs from those scores (Thompson sampling: options that
have done well are chosen more, options with few posts still get tried, consistent losers are retired).
A new knob, or a new option on an old one, needs no other change: it shows up on the menu the first
time it is rendered and is tried from then on.

A pick is recorded the moment it is made, so a knob a renderer asks for and then does not use (illusion_video
picks a `shape` for every kind, but only some kinds draw one; tests8 picked `flashes`/`read` tests it never
showed) would be scored against posts it had no part in. When a renderer finds a pick it will not use, it
says so and the knob is left out of the record:

    shape = knobs.pick('shape', SHAPES, r)
    if kind not in ('cloud', 'wheel'): knobs.drop('shape')        # this video has no shape to learn from

A knob whose value is None or '' is also ignored by learn.py.
"""
import json, os

try:
    FORCED = {str(k): str(v) for k, v in json.loads(os.environ.get('CQ_KNOBS') or '{}').items()}
except ValueError:
    FORCED = {}
MENU, CHOSEN = {}, {}


def name_of(v):
    """How an option is written down: True -> 'true', None -> 'none', 0.5 -> '0.5'."""
    if v is None: return 'none'
    if isinstance(v, bool): return 'true' if v else 'false'
    return str(v)


def pick(name, options, rng, weights=None):
    """One of options: the forced one if nightly chose it, else a random draw (weights, or repeats, set the odds)."""
    opts = list(options)
    v = rng.choices(opts, weights=weights)[0] if weights else rng.choice(opts)
    want = FORCED.get(name)
    if want is not None:
        v = next((o for o in opts if name_of(o) == want), v)
    MENU[name] = list(dict.fromkeys(name_of(o) for o in opts))
    CHOSEN[name] = name_of(v)
    return v


def flag(name, p, rng):
    """True with probability p, unless nightly chose."""
    return pick(name, [True, False], rng, weights=[p, 1 - p])


def drop(name):
    """Forget a pick the renderer did not use, so it is not written into the video's record and never scored."""
    MENU.pop(name, None); CHOSEN.pop(name, None)


def record():
    """What goes in the video's .json: the knobs chosen and every knob's menu."""
    return dict(knobs=dict(CHOSEN), menu={k: list(v) for k, v in MENU.items()})
