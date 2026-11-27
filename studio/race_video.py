#!/usr/bin/env python3
"""Algorithm Races (algorithm.races): algorithms racing each other on the same problem, to one song.

    python studio/race_video.py SONG_DIR SEED OUT.mp4

The nightly job's renderer for the "race" style (studio/nightly.py). Two kinds of race, both drawn by the math
account's kit (studio/mathviz/): sorts (four sorting algorithms on the same shuffled numbers, one step each on the
beat) and paths (breadth-first, depth-first and A* through one maze). Which race, which line-up of algorithms and
which maze are knobs, so the learner finds out what gets watched. They were on math.explainers until 2026-11-24.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import math_video as M

TOPICS = ['sorts', 'paths']
WEIGHTS = [2, 3]   # paths over sorts: 1659 views vs 169 on math.explainers (review 2026-11-26)

if __name__ == '__main__':
    M.main(TOPICS, WEIGHTS)
