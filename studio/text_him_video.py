#!/usr/bin/env python3
"""The text page in a skater guy's thoughts (style notes_him, @grip.tape.thoughts): the same cards as studio/text_video.py
(one thought on a soft colour gradient, two beats when the line has them, 7-9 s, loop-clean, no song label on the card),
with its own line bank (studio/notes/him.txt, ids m001...), its own memory of used lines (campaigns/notes_him/recipes.json)
and its own looks: meadow, lagoon and the dark asphalt, which no other page uses.

    python studio/text_him_video.py SONG_DIR SEED OUT.mp4
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import text_video as T

T.BANK = os.path.join(HERE, 'notes', 'him.txt')
T.RECIPES = os.path.join(T.REPO, 'campaigns', 'notes_him', 'recipes.json')
T.PREFIX = 'm'
T.HANDLE = 'grip.tape.thoughts'
T.LOOK_W = {'asphalt': 3, 'meadow': 2, 'lagoon': 2}
T.INK_W = {'white': 3, 'black': 1}
T.FACE_W = {'strong': 3, 'tall': 2, 'round': 1}

if __name__ == '__main__':
    T.run()
