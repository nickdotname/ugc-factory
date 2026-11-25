#!/usr/bin/env python3
"""The text page in a girl's thoughts (style notes_her): the same cards as studio/text_video.py (one thought on a soft
colour gradient that breathes with the kick, at most 11 s, no song label on the card), with its own line bank
(studio/notes/her.txt, ids h001...), its own memory of used lines (campaigns/notes_her/recipes.json) and its own looks.

    python studio/text_her_video.py SONG_DIR SEED OUT.mp4
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import text_video as T

T.BANK = os.path.join(HERE, 'notes', 'her.txt')
T.RECIPES = os.path.join(T.REPO, 'campaigns', 'notes_her', 'recipes.json')
T.PREFIX = 'h'
T.LOOK_W = {'rainbow': 3, 'orchid': 3, 'dusk': 2, 'citrus': 2, 'meadow': 2}
T.INK_W = {'white': 3, 'black': 1}
T.FACE_W = {'strong': 3, 'round': 2}

if __name__ == '__main__':
    T.run()
