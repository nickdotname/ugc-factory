#!/usr/bin/env python3
"""The text page in a broke college kid voice (style notes_college): the same cards as studio/text_video.py (one thought on a soft
colour gradient that breathes with the kick, at most 11 s, no song label on the card), with its own line bank
(studio/notes/college.txt, ids c001...), its own memory of used lines (campaigns/notes_college/recipes.json) and its own looks.

    python studio/text_college_video.py SONG_DIR SEED OUT.mp4
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import text_video as T

T.BANK = os.path.join(HERE, 'notes', 'college.txt')
T.RECIPES = os.path.join(T.REPO, 'campaigns', 'notes_college', 'recipes.json')
T.PREFIX = 'c'
T.LOOK_W = {'citrus': 3, 'meadow': 2, 'lagoon': 2, 'rainbow': 2}
T.INK_W = {'white': 2, 'black': 2}
T.FACE_W = {'strong': 3, 'round': 2, 'tall': 1}

if __name__ == '__main__':
    T.run()
