#!/usr/bin/env python3
"""The ASCII account: a 3D scene drawn in letters, moving to one song, with the code that draws it underneath.

    python studio/ascii_video.py SONG_DIR SEED OUT.mp4

The nightly job's renderer for the "ascii" style (studio/nightly.py): it plays the stretch nightly picked
(CQ_WINDOW). The scene (a ringed planet, Sisyphus and his boulder, a jellyfish) is a knob, as are the letters, the
colours, the layout and how many sparks the snare throws, so the learner finds out what gets watched. The engine
and the scenes are in studio/asciiviz/.

Only letters here: the isometric pixel worlds (studio/pixelviz/, an old bridge and a clay court) were taken off on
2026-11-23 because they aren't ASCII. The engine stays for an account of their own.
"""
import os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'asciiviz')); sys.path.insert(0, HERE)
import knobs as K
from engine import Video

SCENES = ['planet', 'boulder', 'jelly', 'aurora', 'daisies', 'galaxy', 'fireworks', 'goldfish']
WEIGHTS = [1, 1, 1, 3, 3, 3, 3, 6]   # the newer scenes (full-colour pictures in fine letters) get more until the learner has a view

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    w = os.environ.get('CQ_WINDOW')
    t0, t1 = (float(x) for x in w.split(',')) if w else (30.0, 48.0)
    scene = K.pick('scene', SCENES, random.Random(seed * 104729), weights=WEIGHTS)
    Video(scene, song_dir, seed, t0, t1, lyrics=os.environ.get('CQ_LYRICS') != 'none').render(out)
