#!/usr/bin/env python3
"""The text page in a girl's thoughts (style notes_her, @crying.in.trader.joes): the same cards as studio/text_video.py
(one thought on a soft colour gradient, two beats when the line has them, 7-9 s, loop-clean, no song label on the card),
with its own line bank (studio/notes/her.txt, ids h001...), its own memory of used lines (campaigns/notes_her/recipes.json)
and its own looks: the rainbow and citrus washes, which no other page uses.

    python studio/text_her_video.py SONG_DIR SEED OUT.mp4
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import text_video as T

T.BANK = os.path.join(HERE, 'notes', 'her.txt')
T.RECIPES = os.path.join(T.REPO, 'campaigns', 'notes_her', 'recipes.json')
T.PREFIX = 'h'
T.HANDLE = 'crying.in.trader.joes'
T.LOOK_W = {'rainbow': 3, 'citrus': 2}
T.INK_W = {'white': 3, 'black': 2}
T.FACE_W = {'strong': 3, 'round': 2}

if __name__ == '__main__':
    T.run()
