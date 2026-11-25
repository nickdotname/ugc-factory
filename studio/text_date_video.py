#!/usr/bin/env python3
"""The text page in a situationship / dating voice (style notes_date): the same cards as studio/text_video.py (one thought on a soft
colour gradient that breathes with the kick, at most 11 s, no song label on the card), with its own line bank
(studio/notes/date.txt, ids d001...), its own memory of used lines (campaigns/notes_date/recipes.json) and its own looks.

    python studio/text_date_video.py SONG_DIR SEED OUT.mp4
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import text_video as T

T.BANK = os.path.join(HERE, 'notes', 'date.txt')
T.RECIPES = os.path.join(T.REPO, 'campaigns', 'notes_date', 'recipes.json')
T.PREFIX = 'd'
T.LOOK_W = {'orchid': 3, 'sunset': 3, 'dusk': 2, 'rainbow': 1}
T.INK_W = {'white': 3, 'black': 1}
T.FACE_W = {'round': 2, 'strong': 2}

if __name__ == '__main__':
    T.run()
