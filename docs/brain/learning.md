# Learning: how posts steer the next videos

Back to [[README]].

1. **Knobs.** Renderers make every choice through `studio/knobs.py`; each video's knobs are saved in its
   campaign's `recipes.json`, and `menu` there grows as renderers offer new options.
2. **Numbers.** `metrics.yml` / the publisher pull each published post's figures into `campaigns/*/posts.json`
   (views, reach, watch time, skip rate, shares, saves, follows...).
3. **Scores.** `studio/learn.py` ranks each post within its campaign on the signals Instagram ranks Reels by
   (completion carries the most weight), joins it to its recipe, and writes per-option statistics and per-song /
   per-section weights to `studio/weights.json`, retiring options that keep losing.
4. **Choosing.** `studio/nightly.py` picks songs and sections (fewest videos first, weighted by what gets watched),
   then knobs by Thompson sampling over those statistics; 20% of videos (`EXPLORE`) are left entirely to chance so
   new looks keep getting tried. `--set k=v` forces a look for a run (try a new format now).
5. **Cut length.** Videos are the whole stretch, a 10–20 s tight cut from the strongest line, or (picture styles)
   a 6–9 s loop; that choice is learned too (`knob:cut`).

`studio/tried.json` / `clicks.json` hold side experiments (hooks, link clicks). The dashboard's account cards show
which knob values are winning ([[dashboard]]).

Open PR #75 adds **fresh subjects**: a video's subject knob (math topic, psy field, vintage tint, nyc kind...)
never repeats the account's most recent ones, so a winner can't be posted four times running.
