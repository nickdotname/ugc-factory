#!/usr/bin/env python3
"""8-Bit Tests (8bit.tests): pixel-art tests you take along with the song.

    python studio/tests8_video.py SONG_DIR SEED OUT.mp4

The nightly job's renderer for the "tests8" style (studio/nightly.py). The scenes are in studio/mathviz/tests8.py
(count the flashes: one firefly flash per snare; read as fast as he raps: the verse a word at a time with a
words-per-minute gauge), drawn with the math account's kit. Which test and which sky are knobs.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import math_video as M

if __name__ == '__main__':
    M.main(['tests8'], [1])
