"""studio/knobs.py: a renderer's choices, as the learner sees them."""
import importlib, os, random, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'studio'))


def fresh(monkeypatch, forced=None):
    monkeypatch.setenv('CQ_KNOBS', forced or '')
    import knobs
    return importlib.reload(knobs)


def test_a_dropped_pick_is_not_recorded(monkeypatch):
    """illusion_video picks a shape for every kind but only some kinds draw one: drop() keeps it off the record."""
    K = fresh(monkeypatch)
    r = random.Random(1)
    kind = K.pick('kind', ['cloud', 'cone'], r); K.pick('shape', ['ring', 'star'], r)
    assert set(K.record()['knobs']) == {'kind', 'shape'}
    K.drop('shape')
    rec = K.record()
    assert set(rec['knobs']) == {'kind'} and set(rec['menu']) == {'kind'} and rec['knobs']['kind'] == kind
    K.drop('never picked')                                                 # harmless


def test_a_forced_knob_still_wins_and_the_dice_still_roll(monkeypatch):
    K = fresh(monkeypatch, '{"pal": "lava", "glow": "1.0"}')
    r1, r2 = random.Random(7), random.Random(7)
    assert K.pick('pal', ['ice', 'lava', 'neon'], r1) == 'lava'
    assert K.pick('glow', [0.6, 1.0], r1) == 1.0                           # matched by name, typed as the menu is
    K.pick('pal', ['ice', 'lava', 'neon'], r2); K.pick('glow', [0.6, 1.0], r2)
    assert K.pick('other', list(range(50)), r1) == K.pick('other', list(range(50)), r2)   # forcing moved no other dice
