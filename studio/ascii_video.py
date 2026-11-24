#!/usr/bin/env python3
"""The ASCII account: a 3D scene drawn in letters, moving to one song, with the code that draws it underneath.

    python studio/ascii_video.py SONG_DIR SEED OUT.mp4

The nightly job's renderer for the "ascii" style (studio/nightly.py): it plays the stretch nightly picked
(CQ_WINDOW). The scene (a ringed planet, Sisyphus and his boulder, a jellyfish) is a knob, as are the letters, the
colours, the layout and how many sparks the snare throws, so the learner finds out what gets watched. The engine
and the scenes are in studio/asciiviz/.

Two scenes are isometric pixel worlds instead of letters (an old bridge over a river, a clay tennis court): voxels
drawn in code, no sprites or image files, with the same timing (studio/pixelviz/). They were taken off for a few
hours on 2026-11-23 as "not ASCII" and put back the same night: they were two of the account's three most-watched
posts, and the page is creative coding as much as ASCII.
"""
import os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'asciiviz')); sys.path.insert(0, HERE)
import knobs as K
from engine import Video

SCENES = ['planet', 'boulder', 'jelly', 'aurora', 'daisies', 'galaxy', 'fireworks', 'goldfish', 'bridge', 'court']
WEIGHTS = [1, 1, 1, 3, 3, 3, 3, 6, 5, 5]   # the newer scenes get more until the learner has a view; the pixel worlds are about a third
PIXEL = {'bridge': 1, 'court': 2}     # scene -> the world number shown in the frame

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
