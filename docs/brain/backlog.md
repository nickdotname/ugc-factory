# Backlog

Back to [[README]]. Ideas and half-built work, with enough detail to pick up. Newest first.

## Open PRs (waiting for a merge)
- #92 the three instrumentals in rotation · #93 fission (math.explainers) · #94 NYC facts + own-clip inbox
- #75 fresh subjects · #77 math sorting/maze races · #79 ASCII goldfish · #80 fluid sims (physics). All merge
  cleanly as of 2026-11-23.

## Next
- **More pixel worlds** for ascii.terminal.dreams (studio/pixelviz/): each is a
  ~140-line voxel scene whose action lands on the song's hits. Built: bridge, court, hoops, subway. Candidates from the album:
  dorm room at night, lecture hall, rooftop, laundromat.
- **Illusions account** (asked for 2026-11-23, after an account of spinning dot-cloud animals): `studio/illusion_video.py`
  is the renderer, not registered anywhere yet. Four kinds (a dot cloud whose direction of turning is undecided and
  that the video flips for you; the same as a flat shadow; flat circles that read as a cone; a wheel that seems to
  reverse at 30 frames a second) over eleven shapes of our own. More turning effects to add: a window that seems to
  swing (Ames), a mask that seems to bulge both ways, a barber pole, a Necker cube with one face lit, counter-turning
  rings of dots that read as a cylinder. Needs: the Instagram account (operator), a Facebook Page (the Page limit
  comes first), then playbooks/add-account. No "comment which way" lines: questions only.
- **Band in real places (scene style)**, inspired by dev_lemons but our own: three worlds — EDUCATION school places
  (AI-made plates: hallway, classroom, gym, bus; lyrics chalked on the board, yearbook portraits), psych-rock
  landscapes (AI plates, marker-scrawl lyrics), NYC film look (our NYC clips, matched light, subtitles). No letterbox,
  italic lyrics, laptops, handhelds, billboards or pixel waves (her signatures). Needs the Kaggle image library.
- **More band footage** for the cut-out and scene styles: only Fixation, Won't Be the Same Again, Full Ride and Notta
  Problem have dance clips in `studio/lofi/index.json`, so those two styles only ever play those songs.
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
