#!/usr/bin/env python3
"""The text page in a guy's thoughts (style notes_him): the same cards as studio/text_video.py (one thought on a soft
colour gradient that breathes with the kick, at most 11 s, no song label on the card), with its own line bank
(studio/notes/him.txt, ids m001...), its own memory of used lines (campaigns/notes_him/recipes.json) and its own looks.

    python studio/text_him_video.py SONG_DIR SEED OUT.mp4
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import text_video as T

T.BANK = os.path.join(HERE, 'notes', 'him.txt')
T.RECIPES = os.path.join(T.REPO, 'campaigns', 'notes_him', 'recipes.json')
T.PREFIX = 'm'
T.LOOK_W = {'citrus': 3, 'rainbow': 2, 'dusk': 2, 'meadow': 3, 'sunset': 2}
T.INK_W = {'white': 3, 'black': 1}
T.FACE_W = {'strong': 3, 'round': 2}

if __name__ == '__main__':
    T.run()
