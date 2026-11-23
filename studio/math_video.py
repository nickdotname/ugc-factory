#!/usr/bin/env python3
"""Math In Time: one math explainer, moving to one song.

    python studio/math_video.py SONG_DIR SEED OUT.mp4

The nightly job's renderer for the "math" style (studio/nightly.py). The topic is a knob, so the learner finds out
which explainers people watch; the look (theme, typeface, background, shake, glow, step labels) is a set of knobs
inside studio/mathviz/kit.py. Every scene is choreographed in beats (44 of them, eleven bars), so it fits any song at
its own tempo: it starts on the first bar line at or after the stretch nightly picked (CQ_WINDOW), and if the song
ends too soon it moves back. The scenes themselves are in studio/mathviz/: integral, fourier, derivative, zeta (the Riemann hypothesis), fold
(how many folds of paper reach the Moon, in pixel art), sorts (four sorting algorithms race on the same numbers), paths (breadth-first, depth-first and A* race
through one maze), sci8 (pixel-art science explainers in escalating parts: the brain, the
heart, the eyes). tests8 (play-along tests) is kept but not chosen.
"""
import importlib, json, math, os, random, sys
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'mathviz')); sys.path.insert(0, HERE)
import knobs as K
import beat as audio

TOPICS = ['integral', 'fourier', 'derivative', 'zeta', 'fold', 'sci8', 'sorts', 'paths']
TOPIC_WEIGHTS = [1, 1, 1, 3, 3, 5, 5, 4]  # sorts / paths: algorithm races (comp sci);  the Riemann hypothesis is in the news (AI results on it, Aug-Oct 2026); fold (paper to the Moon, in pixel art) is new
BEATS = 44

def start_beat(song_dir, t0):
    """The first bar line (a multiple of four beats from the first downbeat) at or after t0 at which the whole scene
    still fits before the song ends."""
    s = json.load(open(os.path.join(song_dir, 'song.json')))
    master = next(os.path.join(song_dir, 'master' + e) for e in ('.ogg', '.flac', '.wav') if os.path.exists(os.path.join(song_dir, 'master' + e)))
    last = math.floor((audio.beat_of_time(s, sf.info(master).duration) - BEATS - 1) / 4) * 4
    return max(0, min(math.ceil(audio.beat_of_time(s, t0) / 4) * 4, last))

if __name__ == '__main__':
    song_dir, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    topic = K.pick('topic', TOPICS, random.Random(seed * 7919), weights=TOPIC_WEIGHTS)
    t0 = float(os.environ.get('CQ_WINDOW', '0,0').split(',')[0])
    os.environ.update(CQ_MATH_SONG=os.path.basename(os.path.normpath(song_dir)), CQ_MATH_B0=str(start_beat(song_dir, t0)), CQ_MATH_SEED=str(seed))
    scene = importlib.import_module(topic)
    scene.render(scene.frame, scene.CL, out)
