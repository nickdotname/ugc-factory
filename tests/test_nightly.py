"""studio/nightly.py: how tonight's knobs are chosen (2026-11-26 learner hygiene).

nightly.py is a script (it parses argv, warms librosa and renders at import), so its definitions are loaded on their
own: every import, function and UPPER_CASE constant at the top level, nothing that runs the job."""
import ast, os, random, sys

STUDIO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'studio')
sys.path.insert(0, STUDIO)


def load():
    src = open(os.path.join(STUDIO, 'nightly.py')).read()
    ns = {'__name__': 'nightly_defs', '__file__': os.path.join(STUDIO, 'nightly.py')}
    for node in ast.parse(src).body:
        keep = isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) or (
            isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets))
        if not keep: continue
        try: exec(compile(ast.Module([node], []), 'nightly.py', 'exec'), ns)
        except NameError: pass                       # a constant built from the parsed args or the yaml: not needed here
    return ns


N = load()


def draws(fn, n=400):
    out = {}
    for seed in range(n):
        v = fn(seed); out[v] = out.get(v, 0) + 1
    return out


def test_explore_is_one_in_ten():
    assert N['EXPLORE'] == 0.1


def test_picture_styles_start_from_a_short_cut_until_data_says_otherwise():
    cuts = ['full', 'tight', 'short']
    assert set(N['CUT_PRIOR']) == set(cuts)
    assert N['CUT_PRIOR']['short'][1] > N['CUT_PRIOR']['tight'][1] > N['CUT_PRIOR']['full'][1]
    got = draws(lambda s: N['thompson'](cuts, N['CUT_PRIOR'], random.Random(s)))
    assert got['short'] > got['tight'] > got['full']
    # a style whose own posts say the whole stretch wins overrides the prior: 12 posts at a 0.9 mean score
    data = dict(N['CUT_PRIOR'], full=[12, 11.0, 0.9])
    got = draws(lambda s: N['thompson'](cuts, data, random.Random(s)))
    assert got['full'] > got['short'] + got['tight']


def test_frozen_knobs_are_fixed_on_every_video_and_lapse_by_date():
    frozen = N['frozen_for']('math', {}, today='2026-11-27')
    assert frozen == N['FROZEN']['math'] and 'theme' in frozen
    assert N['frozen_for']('math', {}, today='2026-12-11') == {}                   # the freeze ends on FREEZE_UNTIL
    assert N['frozen_for']('math', {'freeze': {'theme': 'mono', 'chip': 'tag'}}, today='2026-11-27') == dict(frozen, theme='mono', chip='tag')
    assert N['frozen_for']('race', {}, today='2026-11-27') == {}                   # nothing frozen for other styles
    menu = {'theme': ['chalk', 'mono', 'synth'], 'topic': ['zeta', 'fourier'], 'glow': ['0.6', '1.0']}
    frees, topics = 0, set()
    for seed in range(60):
        kn, env, how = N['choose']('math', menu, {}, seed, frozen)
        assert kn['theme'] == 'chalk' and kn['glow'] == '1.0'                     # learned or free alike
        if how == 'free': frees += 1; assert 'topic' not in kn
        else: topics.add(kn['topic'])
    assert frees and topics == {'zeta', 'fourier'}                                # the subject is still the learner's
    kn, _, how = N['choose']('math', menu, {}, 3, None)
    assert how == 'free' or kn['theme'] in menu['theme']                         # without a freeze nothing is pinned


def test_every_frozen_knob_is_one_the_renderer_offers():
    """A frozen value is forced through CQ_KNOBS, which only takes an option on the renderer's own menu."""
    import glob, json
    menus = {}
    for f in glob.glob(os.path.join(os.path.dirname(STUDIO), 'campaigns', '*', 'recipes.json')):
        try: rec = json.load(open(f))
        except (OSError, ValueError): continue
        for style, m in (rec.get('menu') or {}).items():
            for knob, opts in m.items(): menus.setdefault(style, {}).setdefault(knob, set()).update(opts)
    for style, knobs in N['FROZEN'].items():
        if style not in menus: continue                                           # not rendered on this checkout
        for knob, value in knobs.items():
            assert value in menus[style].get(knob, ()), (style, knob, value)
