#!/usr/bin/env python3
"""The text page in a broke college kid's voice (style notes_college, @dining.hall.philosopher): the same cards as
studio/text_video.py (two beats when the line has them, 7-9 s, loop-clean, no song label on the card), with its own
line bank (studio/notes/college.txt, ids c001...), its own memory of used lines (campaigns/notes_college/recipes.json)
and its own look: paper, a cream card with black type that reads like a note, which no other page uses.

    python studio/text_college_video.py SONG_DIR SEED OUT.mp4
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import text_video as T

T.BANK = os.path.join(HERE, 'notes', 'college.txt')
T.RECIPES = os.path.join(T.REPO, 'campaigns', 'notes_college', 'recipes.json')
T.PREFIX = 'c'
T.HANDLE = 'dining.hall.philosopher'
T.LOOK_W = {'paper': 1}
T.INK_W = {'black': 1}
T.FACE_W = {'round': 3, 'strong': 2, 'tall': 1}

if __name__ == '__main__':
    T.run()
