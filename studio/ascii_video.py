#!/usr/bin/env python3
"""The ASCII account: a 3D scene drawn in letters, moving to one song, with the code that draws it underneath.

    python studio/ascii_video.py SONG_DIR SEED OUT.mp4

The nightly job's renderer for the "ascii" style (studio/nightly.py): it plays the stretch nightly picked
(CQ_WINDOW). The scene (a ringed planet, Sisyphus and his boulder, a jellyfish) is a knob, as are the letters, the
colours, the layout and how many sparks the snare throws, so the learner finds out what gets watched. The engine
and the scenes are in studio/asciiviz/. The scene "wild" is a real picture (public-domain footage, or our own
single-subject clips) set in type by studio/asciiviz/letters.py; its code panel shows letters.py, which is what draws it.

Four scenes are isometric pixel worlds instead of letters (an old bridge over a river, a clay tennis court, a pickup
basketball game, a subway platform): voxels
drawn in code, no sprites or image files, with the same timing (studio/pixelviz/). They were taken off for a few
hours on 2026-11-23 as "not ASCII" and put back the same night: they were two of the account's three most-watched
posts, and the page is creative coding as much as ASCII.
"""
import os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'asciiviz')); sys.path.insert(0, HERE)
import knobs as K
from engine import Video

SCENES = ['planet', 'boulder', 'jelly', 'aurora', 'daisies', 'galaxy', 'goldfish', 'wild', 'bridge', 'court', 'hoops', 'subway']
# wild (a real picture set in type) and the pixel worlds (their best posts) lead; fireworks was retired on 2026-11-24
# (a sparse frame, 180 views); the raymarched trio (planet, boulder, jelly: ~190 views each) are kept for variety
WEIGHTS = [1, 1, 1, 2, 2, 4, 4, 7, 3, 3, 3, 3]
PIXEL = {'bridge': 1, 'court': 2, 'hoops': 3, 'subway': 4}     # scene -> its world number

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW')
    t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 48.0)
    scene = K.pick('scene', SCENES, random.Random(seed * 104729), weights=WEIGHTS)
    if scene in PIXEL:
        sys.path.insert(0, os.path.join(HERE, 'pixelviz'))
        import importlib.util
        spec = importlib.util.spec_from_file_location('pixel_engine', os.path.join(HERE, 'pixelviz', 'engine.py'))
        PE = importlib.util.module_from_spec(spec); spec.loader.exec_module(PE)
        PE.Video(scene, song_dir, seed, t0, t1, world_no=PIXEL[scene]).render(out)
    else:
        Video(scene, song_dir, seed, t0, t1, lyrics=os.environ.get('CQ_LYRICS') != 'none').render(out)
