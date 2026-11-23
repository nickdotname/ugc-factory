# Backlog

Back to [[README]]. Ideas and half-built work, with enough detail to pick up. Newest first.

## Open PRs (waiting for a merge)
- #92 the three instrumentals in rotation · #93 fission (math.explainers) · #94 NYC facts + own-clip inbox
- #75 fresh subjects · #77 math sorting/maze races · #79 ASCII goldfish · #80 fluid sims (physics). All merge
  cleanly as of 2026-11-23.

## Next
- **Animated band cutouts (dev_lemons style)** for @close__quarters: the band cut out of their footage and
  moved a lot (camera moves, scale pops, cutout duplicates, stickers), higher quality, keeping the CQ look; now and
  then trippier (melt, glitch, chromatic smear). Start from `lofi_video.py` (cutout + player) and
  `studio/lofi/index.json` (where footage exists).
- **Math "curves in love"**: two curves (y = x and y = x − sin x, etc.) drawn as characters that chase, meet and
  part on the beat; captions as their dialogue. Ref: ilkeveaksiyom.
- **Real modern NYC clips**: Nick's own via the inbox ([[footage]]); a free Pexels API key would add licensed
  stock (needs a `PEXELS_KEY` secret and a `pexels()` source in footage.py).
- **Vintage frame check**: run a small image classifier over a few frames of each silent-film clip at fetch time
  and drop caricature / unsafe frames that metadata can't catch.
- **NYC animated facts from NYC Open Data** (live numbers: 311 calls, subway ridership) instead of the fixed list.

## Account ideas (from the 2026-11 research)
More faceless niches, one format per account: gaming (other games we record), more visualisers, historical events
animated in a distinct style. Don't merge formats into existing accounts; make a new one ([[add-account]]).
