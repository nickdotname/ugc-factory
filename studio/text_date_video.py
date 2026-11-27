#!/usr/bin/env python3
"""The situationship text page (style notes_date, @situationship.notes): the same cards as studio/text_video.py (one
thought on a soft colour gradient, two beats when the line has them, 7-9 s, loop-clean, no song label on the card), with
its own line bank (studio/notes/date.txt, ids d001...), its own memory of used lines (campaigns/notes_date/recipes.json)
and its own look: sunset, which no other page uses.

    python studio/text_date_video.py SONG_DIR SEED OUT.mp4
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import text_video as T

T.BANK = os.path.join(HERE, 'notes', 'date.txt')
T.RECIPES = os.path.join(T.REPO, 'campaigns', 'notes_date', 'recipes.json')
T.PREFIX = 'd'
T.HANDLE = 'situationship.notes'
T.LOOK_W = {'sunset': 1}
T.INK_W = {'white': 3, 'black': 1}
T.FACE_W = {'round': 2, 'strong': 2}

if __name__ == '__main__':
    T.run()
