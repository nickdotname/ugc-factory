"""The archive cluster's formats after docs/brain/reviews/2026-11-26/archive.md: glitch.archive as the NASA + own-footage
page, fact reels of at most 12 s, liminal tapes with something wrong in the room, and the caption banks."""
import ast, json, os, re, sys

import pytest
import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDIO = os.path.join(REPO, 'studio')
sys.path.insert(0, STUDIO); sys.path.insert(0, os.path.join(STUDIO, 'mathviz'))
NIGHTLY = yaml.safe_load(open(os.path.join(STUDIO, 'nightly.yaml')))['targets']
BAIT = re.compile(r"\b(comment|tag a|tag your|tag someone|like this|follow|share this|send this|save this|drop your|be honest)\b", re.I)


def target(camp, style):
    return next(t for t in NIGHTLY if t['campaign'] == camp and t['style'] == style)


def bank(camp):
    text = open(os.path.join(REPO, 'campaigns', camp, 'captions.txt'), encoding='utf-8').read()
    return [b.strip().split('\n')[0] for b in text.split('\n---\n') if b.strip()]


def script_defs(name):
    """A studio script's top-level imports, functions and UPPER_CASE constants, without running it (they parse argv)."""
    src = open(os.path.join(STUDIO, name)).read(); ns = {'__name__': name[:-3] + '_defs', '__file__': os.path.join(STUDIO, name)}
    for node in ast.parse(src).body:
        keep = isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)) or (
            isinstance(node, ast.Assign) and all(n.id.isupper() for t in node.targets
                                                  for n in (t.elts if isinstance(t, ast.Tuple) else [t]) if isinstance(n, ast.Name)))
        if not keep: continue
        try: exec(compile(ast.Module([node], []), name, 'exec'), ns)
        except (NameError, KeyError, ImportError): pass
    return ns


# ---------------------------------------------------------------- glitch.archive
class TestGlitch:
    G = None

    @classmethod
    def setup_class(cls):
        cls.G = pytest.importorskip('glitch_video')

    def test_sources_are_nasa_and_our_own_footage(self):
        G = self.G
        assert set(G.THEMES) == {'space', 'rocket', 'nyc'} and G.OWN == ('space',)
        ok = dict(asset='x.mp4', title='Launch Replays of Antares Rocket with Cygnus OA-8 from Wallops.webm', key='k', query='q')
        assert G.usable(dict(ok, theme='space'))
        for theme in ('archive', 'silent', 'water', 'nature', 'city', 'toons', 'nyc_now'):
            assert not G.usable(dict(ok, theme=theme)), theme
        assert G.usable(dict(ok, theme='nyc', source='own'))                       # Nick's own clips
        assert not G.usable(dict(ok, theme='nyc', source='commons'))               # an old New York film is not ours

    def test_every_space_clip_has_a_short_readable_name(self):
        G = self.G
        idx = json.load(open(os.path.join(STUDIO, 'footage', 'index.json')))['clips']
        names = {G.name(e) for e in idx if e.get('theme') == 'space' and G.usable(e)}
        assert 'Antares launch, NASA' in names and 'Artemis II launch, NASA' in names
        for n in names: assert 6 <= len(n) <= 42 and '.webm' not in n and 'SVS' not in n, n
        assert G.name(dict(theme='rocket', asset='a.mp4')) == 'Rocket League, our clip'

    def test_mosh_is_a_transition_by_default_and_duotone_off(self):
        G = self.G
        assert G.MODES == ['transition', 'bed'] and G.TRANSITION == 15          # half a second at 30 fps
        assert G.TONE_ODDS[G.TONES.index('duotone')] == 0
        assert G.MIN_SHOT >= 60 and G.FIRST_SHOT >= G.MIN_SHOT                  # shots of 2 s and more; the first longer
        t = target('glitch_archive', 'glitch')
        for old in ('water', 'nature', 'city', 'archive', 'mixed'): assert old in t['retire']['source']
        assert 'duotone' in t['retire']['tone'] and t['join'] <= 20


def test_glitch_captions_name_no_old_films_and_ask_nothing():
    lines = bank('glitch_archive')
    assert len(lines) >= 12
    for ln in lines:
        assert not BAIT.search(ln), ln
        assert not re.search(r'public domain|old reel|archive|creek|tape', ln, re.I), ln


# ---------------------------------------------------------------- fact reels (nostalgia, psychedelic.station)
def _specs():
    import glob
    for f in sorted(glob.glob(os.path.join(STUDIO, 'carousels', '**', '*.json'), recursive=True)):
        if os.path.basename(f) in ('posted.json', 'reeled.json'): continue
        sp = json.load(open(f))
        if sp.get('slides') and sp.get('theme') != 'band': yield sp


def test_fact_reels_are_twelve_seconds_at_most_with_two_slides():
    F = script_defs('post_factreel.py')
    assert F['MAX_S'] <= 12 and F['SLIDES'] == 2
    n = 0
    for sp in _specs():
        for part in (1, 2):
            for pointer in (True, False):
                cards, dur = F['plan_cards'](sp, part, pointer)
                facts = [c for c in cards[1:] if 'carousel' not in c[3]]
                assert dur <= 12.0 and 1 <= len(facts) <= 2, (sp['slug'], part, dur)
                assert cards[0][0] == 0 and cards[-1][1] == dur                 # headline from frame 0, nothing after the last card
                for c in facts: assert c[1] - c[0] >= F['read_time'](c[3]) - 0.01   # the reading-time rule holds
                if not pointer: assert not any('carousel' in c[3] for c in cards), sp['slug']
                n += 1
        one = F['plan_cards'](sp, 1, False)[0]; two = F['plan_cards'](sp, 2, False)[0]
        told = [c[3] for c in one[1:]]
        assert two[1][3] not in told                                            # part 2 picks up where part 1 stopped
    assert n


def test_a_reel_points_at_a_carousel_only_when_it_is_up():
    F = script_defs('post_factreel.py')
    F['posted'] = [dict(slug='a', account='nostalgia_ig', post='p1')]
    assert F['carousel_up']('a', 'nostalgia_ig')                              # posted (its outbox item may be archived)
    assert not F['carousel_up']('a', 'psychedelic_station_ig') and not F['carousel_up']('b', 'nostalgia_ig')
