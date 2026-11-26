# Backlog

Back to [[README]]. Ideas and half-built work, with enough detail to pick up. Newest first.

## Open PRs (waiting for a merge)
- #92 the three instrumentals in rotation · #93 fission (math.explainers) · #94 NYC facts + own-clip inbox
- #75 fresh subjects · #79 ASCII goldfish · #80 fluid sims (physics). All merge
  cleanly as of 2026-11-23.

## Next
- **Account ideas from the same day** (each needs an Instagram account made on the phone and a tester invite; four
  token slots are free, `IG_TOKEN_5`…`8`):
  - *Reveal* ("can you guess it?"): **built 2026-11-26 for countries** as circle_atlas ([[ready-pages]]). Still open: animals, instruments, everyday objects (need our own outlines).
    Original note:: a closed outline drawn by Fourier epicycles with N = 3, 5, 8, 20… circles, the
    error falling as N grows, the answer at the end. Our subjects only: animals, instruments, countries, everyday
    objects (the reference used Pokémon, which we cannot draw). `studio/mathviz/fourier.py` already draws
    epicycles. Difficulty tags are fine; "only true fans" / "you're a genius" lines are not.
  - *What if* (a question, then a small 3D scene that plays it out with one live number): "what if the ocean froze
    for 5 seconds", "what if a 1 km asteroid hit 50 km away". Voxel scenes like `studio/pixelviz/`. Every number
    shown must be computed (a shockwave's arrival time from the distance and the speed of sound), not made up. No
    real people (the reference used a pop-star figure).
  - *Choose a world* ("choose a planet, you must survive one year"): four numbered worlds, a countdown, then a
    walk through each with a pixel caption. Fits retro.vibes.arcade today, from clips already in `retro-library`.
  - *Stare illusions* (afterimage, motion aftereffect, lilac chaser): **built 2026-11-26** as stare_lab ([[ready-pages]]). Still open: a Troxler-fading page, an Ames window.
  - *Marbling* (ink drops, combs, stirs by exact equations): **built 2026-11-26** as ink_marbling ([[ready-pages]]). Still open: a slow 'make the pattern' series (one stroke per beat for 40 s), drops placed by the melody's pitch.
  - *Measured illusions* (size, straightness, grey; asked then measured): **built 2026-11-26** as ruler_says_no ([[ready-pages]]). Still open: Zollner, Delboeuf, Adelson's checker shadow, a 'level 2' with two illusions stacked.
  - *Harder levels* for rotation.illusions ("level: hard ++++": more dots, two shells turning against each other).
  - *Same prompt, four models* (a drawing made by code from each of several AI models, side by side): only if each
    panel is really that model's output. Not from our renderers with model names on them.
- **Formats from Dylan's inspiration reels (2026-11-24).** Each must be our own version: our pictures, our wording, no
  "comment if you got it", no "follow for part 2", no invented statistics ("only 1% can").
  - *Sorting race that unscrambles a picture* (quick sort vs merge sort on the same shuffled image, side by side):
    the Algorithm Races account, on top of #77. Pictures: public-domain paintings or our own renders.
  - *Pause at the right time* (a moving thing and an outline it fits for a few frames): the 8-Bit Tests account, in
    our own pixel scenes. Not Minecraft or any other game's footage.
  - *Every triangle splits into four, how small can they get* (a shape that subdivides on the beat, with a counter):
    math.explainers.
  - *How close can X get* (a distance halved again and again, the scale named at each step, down to atoms; the
    picture at each scale is drawn procedurally): math.explainers. The biggest build; facts need sources.
  - *10 cuts vs 1,000 cuts* (a solid sliced into more and more pieces that spill out, with a piece counter):
    physics.bounce.lab.
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
