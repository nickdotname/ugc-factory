#!/usr/bin/env python3
"""8-Bit Tests (8bit.tests): pixel-art tests you take along with the song.

    python studio/tests8_video.py SONG_DIR SEED OUT.mp4

The nightly job's renderer for the "tests8" style (studio/nightly.py). The scenes are in studio/mathviz/tests8.py:
five play-along tests built from the song's own hits (pause when it fits, follow the gem, watch the order, count the
fireworks, early or late), drawn as detailed pixel worlds (studio/mathviz/pix8.py: city rooftop, moonlit forest,
crystal cave). Which test, which world and the scanlines are knobs.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import math_video as M

if __name__ == '__main__':
    M.main(['tests8'], [1])
