"""studio/footage.py without the network: the block list, query routing, the source adapters' filters and the
round-robin fetch (every query gets a turn before one query may give a second film)."""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'studio'))
import footage as F


def test_block_list_spares_harmless_words():
    for ok in ('Catskill mountains', 'Essex county fair', 'patriotic parade', 'factory smokestacks and smoke', 'Indiana farm', 'birthday party'):
        assert not F.blocked(ok), ok
    for bad in ('man smoking a cigar', 'burlesque review', 'Schleiertanz', 'war bonds'):
        assert F.blocked(bad), bad
    assert F.blocked('chased by police') and not F.blocked('chased by police', F.HARD)     # a comedy's summary may say so
    assert F.blocked('a minstrel show', F.HARD)


def test_query_routing():
    assert F.sources_for('silent', 'loc>Edison') == [('loc', 'Edison')]
    assert F.sources_for('silent', 'Melies') == [('silent', 'Melies'), ('loc', 'Melies')]
    assert F.sources_for('space', 'svs>aurora') == [('svs', 'aurora')]
    assert F._ia_terms('The Navigator Keaton') == 'Navigator AND Keaton'
    assert F._ia_terms('collection:silent_films AND year:[1895 TO 1899]').startswith('collection:')
    qs = json.loads(__import__("pathlib").Path(F.QUERIES).read_text())
    for theme, ql in qs.items():
        assert len(ql) == len(set(ql)), theme
        for q in ql:
            assert all(src in F.SOURCES for src, _ in F.sources_for(theme, q)), q


def fake_open(routes):
    def _open(url, tries=4, raw=False):
        for part, val in routes.items():
            if part in url: return val
        raise AssertionError('unexpected request ' + url)
    return _open


def test_silent_filters_and_picks_the_tall_copy(monkeypatch):
    docs = [dict(identifier='good', title='One Week', year='1920', description='Buster builds a house; a policeman watches'),
            dict(identifier='late', title='Talkie', year='1934'),
            dict(identifier='nodate', title='Undated'),
            dict(identifier='caric', title='Comedy', year='1915', description='a blackface routine'),
            dict(identifier='newer', title='One Week (restored 4K)', year='1920')]
    files = [dict(name='a_512kb.mp4', height='240', size='100'), dict(name='a.mp4', height='480', size='900', length='00:19:30'),
             dict(name='a.ogv', height='480')]
    monkeypatch.setattr(F, '_open', fake_open({'advancedsearch': {'response': {'docs': docs}}, 'metadata/good': {'files': files}}))
    F.SEEN.clear()
    got = list(F.silent('One Week'))
    assert [g[0] for g in got] == ['silent:good']
    key, title, url, dur, lic, page = got[0]
    assert url.endswith('/good/a.mp4') and dur == 1170.0 and lic == 'Public Domain (published 1920)'


def test_loc_keeps_pre_1931_films_with_a_video(monkeypatch):
    res = [dict(id='http://www.loc.gov/item/00694308/', url='https://www.loc.gov/item/00694308/', title="The stenographer's friend", date='1910',
                resources=[dict(video='https://tile.loc.gov/x/00016743.mp4', duration=445)]),
           dict(id='http://www.loc.gov/item/late/', title='Later', date='1948', resources=[dict(video='https://tile.loc.gov/y.mp4')]),
           dict(id='http://www.loc.gov/item/novid/', title='No video', date='1905', resources=[])]
    monkeypatch.setattr(F, '_open', fake_open({'loc.gov/film-and-videos': {'results': res}}))
    monkeypatch.setattr(F.time, 'sleep', lambda s: None)
    F.SEEN.clear()
    got = list(F.loc('Edison'))
    assert len(got) == 1 and got[0][0] == 'loc:00694308' and got[0][3] == 445.0 and 'published 1910' in got[0][4]


def test_svs_prefers_a_clean_1080p_file(monkeypatch):
    page = dict(title='Perpetual Ocean', description='Ocean surface currents', media_groups=[dict(items=[
        dict(instance=dict(url='http://svs.gsfc.nasa.gov/a/ocean_labels_1080p.mp4', filename='ocean_labels_1080p.mp4', height=1080)),
        dict(instance=dict(url='http://svs.gsfc.nasa.gov/a/ocean_1080p.mp4', filename='ocean_1080p.mp4', height=1080)),
        dict(instance=dict(url='http://svs.gsfc.nasa.gov/a/ocean_4k.mp4', filename='ocean_4k.mp4', height=2160)),
        dict(instance=dict(url='http://svs.gsfc.nasa.gov/a/ocean.jpg', filename='ocean.jpg', height=1080))])])
    monkeypatch.setattr(F, '_open', fake_open({'api/search': {'results': [dict(id=3827, title='Perpetual Ocean')]}, 'api/3827/': page}))
    monkeypatch.setattr(F.time, 'sleep', lambda s: None)
    F.SEEN.clear()
    got = list(F.svs('ocean currents'))
    assert got[0][0] == 'svs:3827' and got[0][2] == 'https://svs.gsfc.nasa.gov/a/ocean_1080p.mp4'


def test_fetch_gives_every_query_a_turn(monkeypatch, tmp_path):
    qf = tmp_path / 'q.json'; qf.write_text(json.dumps({'silent': ['a', 'b', 'c']}))
    monkeypatch.setattr(F, 'QUERIES', str(qf)); monkeypatch.setattr(F, 'INDEX', str(tmp_path / 'index.json')); monkeypatch.setattr(F, 'DIR', str(tmp_path))
    def films(q):
        for k in range(5): yield 'fake:%s%d' % (q, k), 'film %s%d' % (q, k), 'http://x/%s%d.mp4' % (q, k), 60.0, 'Public Domain (published 1920)', 'p'
    monkeypatch.setattr(F, 'SOURCES', {'fake': films}); monkeypatch.setattr(F, 'BY_THEME', {'silent': ['fake']})
    monkeypatch.setattr(F, 'cut', lambda url, dur, work, key: [(key.replace(':', '_') + '.mp4', 6.0, 3.0)])
    monkeypatch.setattr(F.time, 'sleep', lambda s: None)
    monkeypatch.setattr(F.subprocess, 'run', lambda *a, **k: type('R', (), {'returncode': 0})())
    F.fetch(4)
    idx = json.loads(__import__("pathlib").Path(F.INDEX).read_text())
    assert sorted(e['query'] for e in idx['clips']) in (['a', 'a', 'b', 'c'], ['a', 'b', 'b', 'c'], ['a', 'b', 'c', 'c'])
    assert all(e['year'] == 1920 for e in idx['clips'])


def test_nyc_clips_must_be_new_york_and_not_news():
    import footage as F
    ok = lambda title, src='commons': F.fits(dict(theme='nyc', source=src, title=title))
    assert ok('New Brooklyn to New York via Brooklyn Bridge, no. 2 (1899)')
    assert ok('Bryant Park and Hippodrome Theater,1905.webm')
    assert not ok('Netanyahu 2026 UN visit Manhattan pro-Palestine protest.webm')
    assert not ok('SunRail Grand Opening at LYNX Central Station.webm')
    assert not ok('Film "Bela" (1913).webm')
    assert not ok('Times Square Becomes Football Street Fair.webm')
    assert ok('anything at all', src='own')                          # our own clips are always New York
    assert F.fits(dict(theme='city', source='commons', title='Film "Bela" (1913).webm'))   # the rule is nyc's only
    assert F.sources_for('nyc_now', 'manhattan skyline') == [('pexels', 'manhattan skyline')]


def test_nyc_places_are_library_clips_and_labels_fit_the_safe_area():
    import json, os
    here = os.path.join(os.path.dirname(__file__), '..', 'studio')
    clips = json.loads(__import__('pathlib').Path(os.path.join(here, 'nyc', 'places.json')).read_text())['clips']
    lib = {e['asset']: e for e in json.loads(__import__('pathlib').Path(os.path.join(here, 'footage', 'index.json')).read_text())['clips']}
    for asset, p in clips.items():
        assert asset in lib, asset
        assert lib[asset]['theme'] in ('nyc', 'nyc_now')
        if p.get('skip'): continue
        assert p.get('mood', 'day') in ('day', 'sunset', 'night', 'snow')
        assert len(p.get('place', '')) <= 26                            # one row at 58 px inside x 96-930
    pairs = {p['pair'] for p in clips.values() if p.get('pair') and not p.get('skip')}
    for pr in pairs:                                                    # a then-and-now pair has both halves
        assert any(lib[a]['theme'] == 'nyc' and p.get('pair') == pr for a, p in clips.items())
        assert any(lib[a]['theme'] == 'nyc_now' and p.get('pair') == pr and not p.get('skip') for a, p in clips.items())


def test_toons_keep_out_live_trademarks_and_films_past_1930():
    ok = lambda title, key='silent:x', **kw: F.fits(dict(theme='toons', source='silent', title=title, key=key, **kw))
    assert ok("Koko's Earth Control", year=1928) and ok('Gertie The Dinosaur (1914)', year=1914)
    assert not ok('Steamboat Willie', 'silent:steamboat-willie_1928', year=1928)       # PD, but Mickey is Disney's live trademark
    assert not ok('Barnacle Bill 1930 Talkartoon', year=1930)                          # the proto-Betty Boop is in it
    assert not ok('Aristocrats of Fashion', 'silent:Aristocr1940', year=1940)           # a 1940 film, indexed as 1930 until 11-26
    assert ok('Aristocrats of Fashion', 'silent:Aristocr1940')                         # fetch checks a title before it knows the year
    assert not ok('Cartoon Collection 1929-1938', year=1929)
    lib = json.loads(__import__('pathlib').Path(F.INDEX).read_text())['clips']
    toons = [e for e in lib if e['theme'] == 'toons' and F.fits(e)]
    assert toons and all(e.get('year', 0) <= 1930 for e in toons)
    assert not any(F.TRADEMARK.search(e['title']) for e in toons)
    assert not any(e['key'] in ('silent:steamboat-willie_1928', 'silent:Aristocr1940', 'silent:BarnacleBill1930Talkartoon') for e in toons)
