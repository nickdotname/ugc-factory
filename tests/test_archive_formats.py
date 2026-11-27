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
            isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets))
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
