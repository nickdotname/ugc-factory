# Science cluster review (2026-11-26)

Accounts: @math.explainers (math_time), @algorithm.races (algo_races), @tiny.code.loops (tiny_code),
@fourier.reveal (circle_atlas), @physics.bounce.lab (physics_sims), @earth.data.live (earth_data).
Reviewed: baseline + cqdash/data.json, campaigns/*/{posts,recipes,history}.json joined through studio/learn.py's
own join, studio/weights.json, the renderers, captions.txt banks, the metrics workflow logs, and contact sheets
rendered into /tmp/claude-0/-home-user-ugc-factory/bd16ba37-fa04-5fa1-8c52-0897619fc36c/scratchpad/science/
(math_*.png, race_*.png, tiny_*.png, reveal.png, stopit.png). Nothing in the repo was changed.

## Cluster-wide findings (apply to several accounts)

1. **Short cuts win everywhere the learner is allowed to try them.** physics: `short` (6.5 s) median 196 views,
   65% completion vs `full` (22.5 s) 129 views, 25%. earth: short 167 / 70% vs full 126 / 27%. The two biggest
   posts in the cluster outside math were both short cuts (fluid headphones 6 s: 632; flights 7.7 s: 1112).
   math and race are `WHOLE` styles (44 fixed beats, 17–51 s depending on tempo): the cut knob is never learned
   there, and their sub-20 s stretches already score better (0.54 vs 0.455 for 20–35 s, n=8/11).
2. **The learner cannot learn looks yet.** Each campaign has 14–26 scored posts and 20–30 knob options across
   5–8 dimensions; with PRIOR=5 every weight sits at 0.9–1.1. The only dimensions with a real gap are the
   *subject* ones (topic, scene, program, obstacle) and `cut`. Freeze the cosmetic knobs (theme, font, grid,
   shake, glow, chip, palette) to one default for two weeks so the posts go to subject × cut × hook instead.
   Hour-of-day is a confound the learner already tracks; the 10:00 NY slot is the worst on math (0.30, n=3).
3. **Song credit is invisible on two accounts.** math/race draw `♪ title — Close Quarters` at y=1885 and
   tinycode at y=1825: both inside Instagram's bottom 420 px, under the caption. physics (1536), earth (1455),
   reveal (1540) are fine. Move math/race/tinycode credit to y ≤ 1500 (quick, kit.overlay_fixed / tinycode.frame).
4. **Follow-asks in the math scenes.** fourier ("follow for the next one", k≥40), zeta (same), fold ("FOLLOW FOR
   THE NEXT ONE"), paths ("follow for part 2"). The house rule bans comment/tag/like asks; the repo removed
   save/follow asks on carousels and cutout on 11-24. Replace with the payoff line (the scene's last fact).
5. **Metrics are blind on every Unified-login account**, algorithm.races included (details below), and on
   fourier.reveal for a different reason. Two of my six accounts are posting with no feedback at all.
6. **Captions are chosen blind to style.** `src/cli.py` `_creative_bank_path` picks from the campaign bank
   (or a per-song one), never per style, so on physics_sims the fluid lines land on ball videos and vice versa
   (11-26: "count the bounces" on fluid/airfoil, "air flowing past a shape, gusting on every kick" on a
   pendulum, "the last bounce is the best one" on fluid/title). See physics.

## @math.explainers

**Verdict: on track, needs a menu fix.** The account has three of the cluster's four >1,000-view posts. The lever is
to make every video a *question that visibly resolves* and to stop spending 5 of 14 weight points on sci8.

### What the numbers say (26 posts, median 174, mean 367, max 1659, median watch 6.7 s)
| post | topic | secs | views | watch | completion | saves/shares |
|---|---|---|---|---|---|---|
| 11-25 13:42 | paths bfs-dfs-astar | 17.9 | 1659 | 11.1 | 62% | 1/0 |
| 11-26 01:41 | zeta | 22.5 | 1355 | 9.0 | 40% | 0/2 |
| 11-25 16:42 | fourier | 17.5 | 1302 | 11.1 | 63% | 7/11 |
| 11-24 22:41 | fold | 21.7 | 824 | 9.3 | 43% | 0/0 |
| 11-23 20:01 | fourier | 22.8 | 409 | 7.3 | 32% | 0/0 |
| 11-25 01:43 | sci8 brain | 19.8 | 379 | 6.7 | 34% | 1/0 |
| derivative ×4 | | 16–23 | 150–166 | 3.8–5.1 | 20–31% | 3/2 total |
| integral ×4 | | 18–33 | 147–365 | 5.1–5.5 | 17–31% | |
| sci8 heart / fission | | 38 / 22 | 146 / 156 | 7.2 / 6.5 | 19% / 30% | 0/0 |
| zeta (the other 4) | | 22–35 | 153–218 | 5.7–7.3 | 19–26% | 3/1 |

- The winners share one shape: a stake stated up front and an outcome you watch arrive. paths: "which gets out
  first?" (a race with a 3-2-1-GO). zeta: "this spiral hides a $1,000,000 question" and the zero counter ticking.
  fourier: a wobbling wave that *becomes* a square; it is also the only scene with the picture moving from frame 0,
  and the one that got shared (11 sends, 7 saves: the 'every sound is sine waves' claim is sendable).
  fold: a counter racing to the Moon. The losers are definitions: "What IS an integral / derivative?" show
  numbered steps and a slope read-out (`slope ≈ 1.2735`) nobody was waiting for. Completion says the same:
  0.62/0.63 for paths/fourier vs 0.20–0.31 for derivative/integral.
- sci8 is a different genre (pixel trivia listicle, 5–8 parts, 20–38 s); heart and fission are the two weakest
  posts on the account, brain was middling. Its topic weight is 5 of 14: the menu currently makes a sci8 video
  36% of the time.
- zeta is bimodal (1355 vs 153–218): the format is right, the dependency on the hour and song is large, and the
  1355 post is still "too new" in weights.json (zeta's learned score is 0.37 from the four small ones).
- Learner: `knob:topic` is the only readable dimension (fold 0.69 n=2, paths 0.70 n=1, sci8 0.62 n=1, fourier
  0.51 n=6, derivative 0.46, integral 0.41, zeta 0.37). Themes/fonts/grids/shakes: 20 options over 21 posts, noise.
  `cut` is always `full` (WHOLE), so length is not learned; length bucket "under 20s" 0.54 vs "20-35s" 0.455.
- Captions carry no signal at n ≤ 2 each; hashtags are the same five on every post (`#math #calculus
  #mathematics #learnmath #mathisfun`), so a zeta or maze video is filed under calculus.

### Content audit (sheets: math_zeta/fourier/integral/derivative/sci8heart/paths(=fold).png)
- **Frame 0 is empty** on zeta, integral and derivative: all text eases in from beat 0 (`ease_back(k/0.45)`),
  so at 100–120 BPM the first 0.3–0.5 s is a dark gradient with a faint ∫ or d/dx; zeta's "$1,000,000" lands at
  beat 1.4 (~0.7 s). The cover is `cover_at_sec: 5` so the grid is fine, but in the feed nothing says "look"
  in the first half second. fourier (wave from frame 0) and fold (question in pixel type from frame 0) are the
  exceptions, and they are two of the four winners.
- Text legibility is good: 58–150 px display type, chips readable at phone size. The derivative/integral
  `slope ≈`/`area ≈` read-outs are the least legible and least interesting things on screen.
- Loop: math scenes end on a payoff and a follow-ask, then cut; no seam into frame 0.
- Niche consistency: a follower gets "a math idea moving to a beat"; sci8 (pixel trivia with faces) breaks it.
- Cadence: 5/day on a 5-day-old account, 40-min offset, hours 8–23; the 10:00 slot has been the worst (n=3).
- The sorting race video posted here on 11-23 (169 views) and the paths video on 11-25 (1659) came from the
  library rendered before races moved out on 11-24; `math_video.TOPICS` no longer contains sorts/paths, so the
  account's best format cannot be made again here (forcing `CQ_KNOBS='{"topic":"paths"}'` silently falls back
  to a random topic: that is how the sheet named math_paths.png is a fold render).

### Research (what the niche does now)
- Short-form math that travels is the "watch it resolve" kind: epicycle drawings (TikTok @top_maths_5m,
  @epyanimate, @mathswithmuza Valentine's heart; the GitHub puzzle Fourierle) and sorting/"sound of sorting"
  (knowyourmeme: the 2013 Bingmann video is still the template). Explainer accounts on Instagram are mostly
  teacher-led talking heads (HypeAuditor's math list; Aperiodical's -e^iπ profile of @mathswithkala), not
  Manim-style clips; Manim creators who post to Instagram are listed in ManimCommunity/awesome-manim.
- Instagram 2025–26: Mosseri named watch time, likes per reach and sends per reach as the three signals, sends
  weighing more for non-followers (Social Media Today, t3n, mubert summaries of the Jan 2025 Reel); the first
  three seconds are "the hook" and a Skip Rate insight (share leaving inside 3 s) was added in Aug 2025;
  hashtags capped at five from 19 Dec 2025 (Business Today, Social Media Today); near-identical reposts are
  down-ranked in favour of the original (Planoly, PetaPixel Apr 2026); own logo is fine, other apps' logos are not.
  Sources: https://mubert.com/blog/?p=5460 ; https://www.socialmediatoday.com/news/instagram-chief-shares-insights-into-its-algorithms-creator-monetization/718540/ ;
  https://www.truefuturemedia.com/articles/lower-instagram-reels-skip-rate ; https://www.businesstoday.in/technology/news/story/no-more-hashtag-stuffing-instagram-limits-hashtag-usage-to-just-5-per-reel-and-post-507444-2025-12-19 ;
  https://planoly.com/blog/instagram-updates-its-original-content-policy ; https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/ ;
  https://www.socialmediatoday.com/news/instagram-clarifies-that-including-your-own-logo-on-a-reel-is-ok/730852/ ;
  https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers-first/ ; https://routenote.com/blog/how-often-you-should-post-on-instagram/ ;
  https://knowyourmeme.com/memes/sorting-algorithm-videos ; https://github.com/EmmetSurmeli/fourierle ;
  https://www.tiktok.com/@top_maths_5m/video/7516197291024321814 ; https://github.com/ManimCommunity/awesome-manim

### Recommendations (ranked)
1. **Rebalance the topic menu** (quick, `studio/math_video.py` TOPIC_WEIGHTS): fourier 3, zeta 3, fold 2, sci8 1
   with `subject` weights brain 2 / fission 1 / heart 0 / eyes 1, integral 1, derivative 0 until rebuilt.
   Add `retire: {topic: [derivative]}` on the nightly target so the learner's free draws do not bring it back.
2. **Frame-0 rule for every scene** (medium, mathviz/*.py): the stake is on screen at frame 0 at full alpha and
   the picture is already moving. Lines that state a bet, not a definition: zeta "this spiral is worth
   $1,000,000" (number visible at k=0); integral "8 rectangles are wrong by 0.4. watch the error hit 0" (make the
   error counter the resolve); derivative "zoom into any curve. it turns into a straight line" (the resolve is the
   secant snapping, which the scene already does); fourier keep. Drop the ease-in on the first line only.
3. **Drop the follow-asks** (quick) in fourier, zeta, fold, paths; end on the fact.
4. **Give the account its best format back without copying races** (quick, math_video.py): put `paths` back in
   TOPICS at weight 2 restricted to the `bfs-dfs-astar` lineup ("3 ways to escape the same maze"), and keep
   `dijkstra-greedy-astar` / `dfs-greedy-astar` and all sorts on @algorithm.races, so no video exists on both.
   Measure after 10 paths posts on each account (see races).
5. **Shorter stretches** (medium): a 24-beat variant of zeta/fourier/fold (one question, one resolve, loop to
   frame 0) so `cut` becomes learnable on math; today's 44-beat scenes run 17–51 s and the sub-20 s ones score best.
6. **Credit above y 1500** (quick, mathviz/kit.py overlay_fixed) so the song name is seen in the viewer.
7. **Hashtags per topic** (quick, captions.txt per-creative banks or a `{topic}` placeholder): `#riemann
   #primes` for zeta, `#fourier #signalprocessing` for fourier, `#algorithms` for paths; keep `#math`.
8. **Freeze looks** for two weeks (quick, nightly `--set` or weights): theme synth or chalk, font montserrat,
   grid none, shake 1.0, glow 1.0; the learner then spends its posts on topic × hour.
9. Experiment to run: 10 posts "resolve" line vs 10 posts current line on the same topics, scored by skip rate
   (`held`) and completion; the learner already records `caption`, so record the on-screen line as a knob
   (`K.pick('line', ...)`) so it shows up in weights.json.

### Risks
- Nothing reposted, nothing copyrighted; the sci8 numbers are sourced in code comments. The only rule issue is the
  follow-asks. 5/day is tolerable for a Page-linked account; keep slots ≥ 60 min apart (publisher MIN_GAP does).

## @algorithm.races

**Verdict: needs work, blind.** Nine posts, zero numbers. The lever is a token with the insights scope; nothing
about the content can be judged until then.

### Why posts.json has no `m`
- The 2026-11-26 18:31 UTC metrics run (run 45876580322) logs, for every algo_races media id:
  `instagram_insights_unavailable ... (#10) Application does not have permission for this action`. Same for
  notes_app and the other Unified-login accounts. traps.md (11-25) says `instagram_business_manage_insights` was
  added to the app and the tokens regenerated, but the token in `IG_TOKEN_2` still does not carry it. The
  refresh in `scripts/refresh_tokens.py` (`ig_refresh_token`) keeps a token's original scopes, and
  `connect.yml` only overwrites a slot when a new login arrives, so the fix is a **fresh login through
  connect.closequarters.vip/connect?u=algorithm.races** (and the four other Unified accounts) after confirming the
  permission is listed under Use cases > Instagram API with Instagram login > Permissions, and that the
  connect worker's scope string includes `instagram_business_manage_insights`. Until then learn.py has
  `posts: 0` for algo_races and the dashboard shows "-".
- Posting works (9 published, media_ids present), so the publish scope is fine; the account posts blind.

### What we know without numbers
- The same scenes ran on math.explainers before 11-24: paths bfs-dfs-astar 1659 views / 62% completion;
  sorts 169 views / 7.4 s. `race_video.WEIGHTS` is sorts 3 : paths 2, the opposite of that evidence (n=1 each).
- Sheets (race_sorts.png, race_paths.png): frame 0 shows the four lanes and "0 steps" but the title ("4 sorting
  algorithms. the same 48 numbers.") eases in over the first beat; the 3-2-1-GO at beats 4–7 is the hook that
  worked on math; the lane labels, step counters and 1st/2nd stamps are legible. The 'bogo' lineup's payoff
  ("10^N years") is the most sendable line in the kit.
- Cadence: 5/day on a 2-day-old account with no Page, a 60-day token and a library that ran dry on 11-25
  (traps). The 11-25 policy for new accounts is 2/day for the first week.

### Should races live inside math.explainers? Are they cannibalising?
- No evidence of cannibalisation (no numbers), and the audiences Instagram would build are different (#algorithms
  / CS vs #math). The real cost of the split is that math.explainers lost its best-performing format.
- Keep them separate, but do not let one account own the only proven format: give math the `bfs-dfs-astar`
  maze (its framing "3 ways to escape") and races the other lineups plus sorts, as above. Instagram's 2026
  originality rule hits identical/near-identical *media*, not shared ideas: different mazes, lineups and songs
  are different videos.
- Decision rule: once races has 10 scored paths posts, if its median is under half of math's paths median, fold
  races into "sorts + picture-unscramble" (backlog) only; if it holds, add the CS-only formats there (binary
  search vs linear, hash vs list, BFS on a real street grid).

### Recommendations
1. Re-issue IG_TOKEN_2 (and _3.._6) with the insights scope via the connect link (quick, operator).
2. `WEIGHTS = [2, 3]` paths over sorts until numbers say otherwise (quick, race_video.py).
3. posts_per_day 3 for the first two weeks (quick, config.yaml).
4. Title visible at frame 0 (medium, mathviz/sorts.py, paths.py: alpha 1 at k=0 for the first line).
5. Add `--set lineup=bogo` for two posts to see whether the "10^N years" payoff travels (quick experiment).
6. Credit above y 1500 (shares kit.overlay_fixed with math).

### Risks
- Token expiry every 60 days (tokens.yml refreshes on the 1st/15th; needs SECRETS_PAT alive).
- Five posts a day into an account Instagram has not yet trusted; the library ran dry once already.

## @tiny.code.loops

**Verdict: needs work.** Flat 110–212 views, the lowest watch time in the cluster (median 3.6 s, completion
13–38%). The lever is making the promise ("the code shown is the code run") visible in the first second.

### What the numbers say (15 posts, 14 scored)
- Winners: tunnel 209/201 (tight 13 s / full 23 s), rose 212 (tight 11.8 s), metaballs 192, attractor 160,
  sunflower 159. Losers: lissajous 112 (2.4 s watch, 14% completion), galaxy 114 (2.3 s), tunnel 110 (16.9 s
  tight; the same program at 13 s got 209), ridges 125, orbits 123. Big, fast, filled pictures beat thin lines.
- Saves are the signal that works here: 11 saves on 14 posts (tunnel 4; "pause on the code. it's short enough to
  copy" 192 views + 1 save). Shares 5. People want the code, not the picture.
- Cut: 11 of 14 are `tight` (10–18 s), one short, one full: no contrast to learn from. The only `full` (23 s)
  had 18% completion; completion falls with length here as everywhere.
- Learner: 9 scored posts, 13 programs, 4 palettes, 3 glows, 3 trails: noise except program; neon 0.71 (n=2) vs
  acid 0.43 (n=5) is the only hint.

### Content audit (tiny_tunnel.png, tiny_lissajous.png)
- The promise is **not** visible in the first second. The only words that say it are `181 chars · running` at
  y=95 (24 px, under Instagram's top bar) and the caption's first line. The editor starts at y=170, so its first
  two code lines sit under the username overlay; the code is 28 px DejaVu Mono, about 10 px on a phone:
  unreadable in the feed. The credit at y=1825 is under the caption. Frame 0 is the finished picture, already
  cycling: nothing is *happening* in the first second, which matches the 2–4 s watch times.
- `k` (the kick) is a pink token in the code, but nothing on screen ties a hit to a line of code.
- Loopability: none (no fade to frame 0; the picture is periodic in t, so a cut is a jump).
- Niche: consistent (editor + square). Cadence 5/day on a 3-day-old account.
- Rules: all original; the only on-screen ask is none. Hashtags fine (`#creativecoding #generativeart #python`).

### Research
- The format "tiny program on screen, picture below" is alive on TikTok (p5.js clips tagged #creativecoding,
  e.g. Okazz via @folderstudio June 2025; the "creative coding in 30 seconds" series) but posts show
  hundreds to low thousands of likes: a saves-and-follows niche, not a views niche. Dwitter/tixy-style
  "140 characters draws this" is the closest ancestor; the hook that works there is watching the code type and
  the picture appear, and "change one number" diffs.
  Sources: https://www.tiktok.com/@folderstudio/video/7513395496400997650 ; https://syntax.fm/show/960/reacting-to-the-weird-creative-corners-of-the-web ;
  https://richtabor.com/generative-art

### Recommendations
1. **Type the program in** (medium, tinycode_video.py): frame 0 = empty editor + empty square, the six lines
   type themselves over the first bar (one line a beat), the picture appears on the kick that lands the last
   line. The causality "code → picture" is then seen, and the first second has motion.
2. **Move everything into the safe area and make the code readable** (medium): editor top ≥ y 290, 38–40 px
   mono, reflow programs to ≤ 34 chars a line (most already are), header line in 36 px: "6 lines of python.
   this is all of it." at y 290; credit at y ≤ 1500.
3. **Flash the `k` token on every kick** and `t` each second (quick): the viewer sees the drum push a variable.
4. **Retire thin/slow programs** (quick, nightly `retire: {program: [lissajous, galaxy, ridges, orbits]}`),
   weight tunnel/rose/metaballs/plasma/attractor ×2.
5. **Short cuts** (quick): force `SHORT` for two weeks (6–9 s, with the last 9 frames faded into frame 0 for a
   loop, as reveal does); physics and earth both doubled completion that way.
6. **New sub-format "change one number"** (medium): the same program twice, split top/bottom, one constant
   highlighted and different; matches the caption already in the bank and the save behaviour.
7. Experiment: typed-in opener vs current, 10 posts each, scored on skip rate and saves per reach.

## @fourier.reveal (circle_atlas)

**Verdict: on track, too early.** Two posts (both 11-26 and both from the old fourier_reveal campaign: a sci8
fission duplicate of math_time's). The circle_atlas renders (Mexico, Norway, Great Britain, Germany) are queued.
Lever: get numbers flowing and bias the first weeks to easy countries.

### Metrics
- The 11-26 run logs `Unsupported get request. Object with ID ... does not exist, cannot be loaded due to missing
  permissions` for both media. These post through a Page token minted from IG_TOKEN's grant for Adrianne's Page;
  that grant needs `instagram_manage_insights` for her Page/IG account too (re-run the app's permission dialog
  including her Pages, then `scripts/page_tokens.py`). Different cause from races, same effect: blind.

### Content audit (reveal.png)
- Frame 0: question in the safe area ("how many circles until you know it?", "level: hard"), the first circle
  drawing, counter "2 circles · off by 5%": honest, legible, the stake is clear. The reveal (country name in
  Anton 150 px + "drawn with 150 circles") is a real resolve, and the last 9 frames fade into frame 0 (loops).
- Weak spot: stage one is a 2-circle ellipse for ~3 s (88 frames here). The first three seconds show a blob;
  a skip-rate risk. Nigeria/Somalia/Mongolia at "level: hard" give most viewers no "I got it" moment.
- Captions (6) are explanatory and good; hashtags `#geography #maps #fourier #mathart #countries` right.
- 2/day for the first week: right. The 11-26 duplicate-of-math posting is already fixed in nightly.yaml.

### Research
- The format exists and is live: Fourierle (daily puzzle, outline revealed in 6 steps), the TikTok "guess the
  map, 1-2-4...256 circles" clip (@why_does_this_work), epicycle π / heart clips (June 2025, Feb 2026).
  Differentiators here: real Natural Earth outlines, the measured error %, the song. The "guess the country by
  shape" quiz genre is evergreen (Geographical magazine runs it weekly).
  Sources: https://github.com/EmmetSurmeli/fourierle ; https://www.tiktok.com/discover/fourier-series-drawing ;
  https://geographical.co.uk/quizzes/quiz-country-shapes

### Recommendations
1. Start at 3 circles and make stage one one bar long (quick, reveal_video.py `ladder`/`per`): a hint of shape
   inside two seconds.
2. EASY weight 6 (not 3) for the first three weeks (quick); hard ones once there are followers who play.
3. Fix the Page-token insights scope (operator).
4. A second `ask` line that states the stake with a number: "most people need 17 circles" is not true yet, so
   use the honest one: "named at 17 circles by the circles themselves"? No: keep the current asks; add
   "level: easy" bias only.
5. Loop variant (medium): after the reveal, hold the name 1 beat, then fade into frame 0 (already), and make the
   first frame carry the country's *silhouette* at 5% opacity? No: that spoils the guess. Leave as is.

## @physics.bounce.lab

**Verdict: needs work; fluid should take over most of the slots.** Balls cap at ~130–220 views with zero sends;
fluid's first four posts did 1279 / 632 / 424 / 137. Lever: more fluid, fewer balls, and style-aware captions.

### What the numbers say (21 posts, 20 scored)
| style/scene | n | views (med) | completion | shares+saves |
|---|---|---|---|---|
| fluid (plane, headphones, airfoil, cylinder) | 4 (+1 too new) | 528 | 28–65% | 3 saves, 0 shares |
| physics circle (grow/lines/plain) | 6 | 157 | 23–95% | 1/4 |
| physics rings | 4 | 187 | 39–122% | 0/0 |
| physics square | 2 | 128 | 25–36% | 0/0 |
| physics pendulum | 3 | 129 | 23–51% | 0/0 |
- Fluid wins on views by 3–4×; obstacle `plane`/`headphones` (a recognisable object in a wake) beat
  `cylinder` (the textbook Kármán street, 137) and `airfoil` is mixed (424 full / 87 two hours old).
- Ball shorts loop (completion 0.95–1.22) but nobody sends them: 4 shares on 20 posts. Loops without a payoff.
- `cut`: short 0.61, tight 0.58, full 0.30 (n 7/3/5): the clearest knob in the cluster.
- `stopit` ("can you stop this?") has rendered but no post has numbers yet.

### Content audit
- Fluid frame 0: "Paper Plane Wake Formation / Navier–Stokes Simulation" at y 300/385, equations under it,
  the wake already shedding: a credible science-demo opener, no question. The `gust` hook line ("sound on:
  every gust is a kick") is on half the videos; it is the only thing that ties the picture to the song.
- Ball frame 0: the rule line ("the ball grows every bounce") at y 250, ball already flying: fine, but the
  genre is saturated (see research) and the account's handle promises it.
- **Caption bank is style-blind** (see cluster finding 6): fluid videos went out as "count the bounces" and
  "the last bounce is the best one"; a pendulum went out as "air flowing past a shape". Also `#bouncingball`
  on every fluid post, and "the physics are real" is in the bank (the ball path is a straight line between
  notes; the 11-23 fix removed two such captions but this one stayed).
- Credit at y 1536: visible. No asks. All original.

### Research
- "Will the ball escape / ball bouncing brainrot" peaked 2023–24 and is now made by template tools
  (ballsimulator.com, viralballs.com, satisfyinglabs.com, Ball Chaos app); under Instagram's originality
  ranking a format that thousands of accounts clone is the worst place to be with 200 followers. Fluid
  content on short-form is mostly Blender tutorials; a real LBM wind tunnel around a paper plane is scarce.
  Sources: https://knowyourmeme.com/memes/will-the-ball-escape-ball-bouncing-brainrot ; https://ballsimulator.com/en/blog/how-to-create-viral-bouncing-ball-videos/ ;
  https://www.instagram.com/satisfying_ball5/ (24K followers, daily ball sims)

### Recommendations
1. **Slots** (quick, nightly.yaml): fluid 4, stopit 2, physics 1; `retire: {scene: [square, pendulum]}`;
   fluid obstacle weights title 2, plane 3, headphones 3, guitar 2, cassette 2, note 1, cylinder 1, airfoil 1;
   `view` vorticity 2 : speed 2 : smoke 1 (vorticity made the two biggest posts).
2. **Style-aware captions** (medium): split physics_sims into three campaigns on the same account (physics_sims,
   fluid_sims, stopit_lab) each with its own captions.txt and hashtags (`#fluiddynamics #aerodynamics
   #simulation #physics #windtunnel` for fluid), or add a `captions/<style>.txt` lookup in `_creative_bank_path`.
   Remove "the physics are real" from the ball bank.
3. **Fluid hook as a question** (medium, fluid_video.py): "which way does the air spin behind a paper plane?"
   / "what does a guitar do to the wind?" at frame 0, `gust` line always on; keep the title/equation smaller.
4. **Fluid short cuts** (quick): fluid is in VISUAL so `short` exists; the 6 s headphones post had 65%
   completion. Let the learner keep short/tight; stop `full` for fluid (24.7 s airfoil was 28%).
5. **Watch stopit for a week** before giving it more; its only risk is reading as a game nobody can win.
6. Longer term: rename nothing; "bounce lab" still fits a lab that blows air at things.

### Risks
- Ball sims: originality down-ranking (template genre); captions that claim things the video does not do.
- None of this is reposted or music-rights sensitive.

## @earth.data.live

**Verdict: on track, one winner to industrialise.** Median 144, one 1112. Lever: the flights dive, in short cuts,
pointed at a named place.

### What the numbers say (20 posts, 16 scored)
- flights: 1112 (7.7 s short, 72% completion, question hook, 18:37 NY), 224 (17.5 s), 165 (5.9 s), 124 (22 s full).
  quakes ×9: 125–270 (score 0.475). satellites ×5: 119–192 (0.44).
- `cut`: short 0.53 / tight 0.58 / full 0.32; length under 10 s 0.69 (n=3). Palette paper 0.58, ember 0.59 vs
  night 0.36, blueprint 0.33 (n 4–6; paper already ×2 in the menu). `hook` question 0.51 vs fact 0.47.
- Saves 7, shares 5: the "every dot is real" claim does not get sent on its own.
- Hour: 20:00 1.05, 13:00 0.92 (tiny n).

### Content audit
- Layout (11-24 pass) is correct: opening line at y 290–420 the whole video, counts/clock/credit/source at
  1300–1500 left of the buttons, every number true of the data. Frame 0 says "what the sky looked like at 24 Nov,
  13:36 UTC" (fact) or "who is flying at 18:37 UTC on a Monday?" (question): the question version is the one
  that got 1112.
- The dive onto the busiest sky with planes as arrowheads is the proven part; the quakes 30-day replay and the
  satellites cloud read as screensavers at 20 s.
- Credit visible; sources on screen; no asks; ODbL attribution present.

### Research
- The format's references are Flightradar24's "24 hours in 1 minute" videos (US, transatlantic, busiest day),
  picked up by CBS, BuzzFeed, WEF: the hooks are a *count* ("202,157 flights") and a *place*.
  Sources: https://www.flightradar24.com/blog/flight-tracking-news/special-aircraft-tracking/seeing-a-day-in-a-minute-24-hours-of-flights-in-the-us/ ;
  https://www.cbsnews.com/news/video-shows-24-hours-of-flights-over-the-u-s-in-1-minute ; https://www.buzzfeednews.com/article/peteraldhous/busiest-day-flights

### Sub-formats after the flights dive (ranked)
1. **"N planes over <city> at HH:MM"** (medium, earth_video.py): the dive already picks the busiest sky; name
   it (nearest hub from a 30-city list), count within 200 km, put the city in the opening line. Rotate hubs
   nightly (fresh-subject rule). Short cut only.
2. **ISS over a city** (medium): CelesTrak + SGP4 are already there (`self.iss`); compute the next pass over a
   big city at the data's timestamp, dive to it, draw the ground track with the pass time and whether the ISS
   is sunlit while the ground is dark (visible pass) from `sun_dir`. Honest line: "the ISS crossed over Tokyo at
   18:42 UTC". The look-up moment is the most sendable thing this account can make.
3. **One plane's whole route** (large): ADSB.lol snapshots have position+heading only; a route needs the
   callsign→origin/destination lookup (adsb.lol routeset API, run from Actions) and a great-circle draw with the
   tracked position marked. Wording must say "route" not "track". Worth it only after 1 and 2.
4. **Quakes last 24 h** in a 6–9 s short (quick, earthdata/earth_video window): "live" beats "30 days".
5. Satellites: keep at a low weight; `retire` unless a short cut beats 150.

### Recommendations
1. Scene weights flights 4 : quakes 2 : satellites 1 (quick, earth_video.py); `cut` short/tight only (quick).
2. Hook `question` ×2 (quick); add the place-named lines once 1 above exists.
3. Palette: paper ×2 stays, ember ×2, drop blueprint (quick).
4. Build the city dive and the ISS pass (medium each).

### Risks
- Data licences are on screen (ODbL, USGS, CelesTrak); nothing else.

## Summary of the biggest cross-cluster bugs to fix first
1. Insights scope missing on IG_TOKEN_2..6 (five accounts blind) and on Adrianne's Page token (fourier.reveal).
2. Style-blind captions on physics_sims (wrong claims on screen-adjacent text).
3. Song credit under Instagram's caption on math, race and tinycode.
4. Follow-asks in four math scenes.
5. math menu weights favour the weakest topic (sci8) 5:1 over fourier.
