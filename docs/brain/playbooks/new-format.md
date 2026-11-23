# Playbook: a new video format (style)

Back to [[README]] · see [[styles]], [[learning]].

1. **Decide where it posts.** A different format usually means a different account ([[add-account]]). On an
   existing account it competes with that account's styles and the learner sorts it out.
2. **Write `studio/<style>_video.py`** with the standard interface: `python studio/<style>_video.py SONG_DIR SEED
   OUT.mp4`, window from `CQ_WINDOW`, `--frames a,b,c` draws a contact sheet. Copy the skeleton (render(),
   `__main__`) from `vintage_video.py` or `glitch_video.py`.
   - Read the music with `beat.load(slug, t0, t1)`: per-frame stem levels, kicks, snares, beat grid. Move on
     those.
   - Every choice through `K.pick('name', options, rng[, weights])`, so it is recorded and learnable.
   - Write `OUT.json` with `K.record()` (+ any footage keys).
   - Respect the rules in `CLAUDE.md` (no band on niche accounts, no bait, public-domain or own footage only).
3. **Look before rendering:** contact sheets at the busiest moments, forcing knobs with `CQ_KNOBS`, on two songs.
   Then one full render to send for approval.
4. **Wire it in:** `VISUAL['<style>'] = '<style>_video.py'` (or `LYRIC` if it shows lyrics) in `studio/nightly.py`;
   a target in `studio/nightly.yaml` (`campaign`, `style`, `per_night`, `join`); its subject knob in
   `scripts/dash_data.py` `WHAT` (and `SUBJECT` once #75 is in).
5. **Try it now** after merge: `studio.yml` with `campaign=<c>` and `set=knob=value` to force a look, or
   `try.yml` to make and post one immediately.
6. Update [[styles]] and [[log]].
