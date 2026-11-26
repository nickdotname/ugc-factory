# Cluster `perception`: rotation.illusions, eye.trick.lab, 8bit.tests, digital.petri.dish

Reviewed 2026-11-26 against `cqdash/data.json` (generated 20:51Z), `campaigns/*/posts.json` (fetched 18:47-19:06Z),
`recipes.json`, `studio/weights.json`, the renderers, and contact sheets rendered into
`/tmp/claude-0/-home-user-ugc-factory/bd16ba37-fa04-5fa1-8c52-0897619fc36c/scratchpad/perception/` (illusion_{cloud,cone,wheel,group,stripes}.png,
stare_{colour,chaser}.png, alife_ring.png, tests8_{count,pause,cups}.png). Nothing in the repo was changed.

Network context (from every campaign's posts.json, posts with >= 30 views, n=552): median skip rate 70%. Only two
campaigns are under 41%: rocket_league (39.7%) and **illusions (40.6%, median watch 9.2 s, median views 1376)**.
petri_dish is 75% (median watch 3.1 s). 8bit.tests and eye.trick.lab have no figures (see each section).

---

## 1. @rotation.illusions (illusions_ig, campaign `illusions`, `studio/illusion_video.py`)

**Verdict: on track; the single biggest lever is to stop spending slots on `cone` and put the freed slots into the
ambiguous-motion kinds (cloud/shadow/group), then add new kinds that follow the same formula.**

### What the numbers say

15 published posts with figures (one more, stripes, failed as a duplicate booking and was re-sent at 19:21Z with no
figures yet). Joined to recipes (posted time is UTC; hour is New York; age is at the 18:47Z fetch):

| kind·shape | song/section | len s | views | reach | v/reach | watch s | watch/len | skip % | likes | sh | sv | NY hour | age h |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cloud·knot | Epilogue s07 (instr.) | 17.5 | 2457 | 1840 | 1.34 | 9.5 | 0.54 | 49 | 33 | 16 | 4 | Mon 22:55 | 63 |
| shadow·planet | Suspended s02 | 21.9 | 2087 | 1573 | 1.33 | 12.0 | 0.55 | 38 | 18 | 1 | 2 | Mon 23:26 | 62 |
| cloud·mug | Recess s08 (instr.) | 16.8 | 1763 | 1256 | 1.40 | 11.5 | 0.69 | 35 | 11 | 8 | 1 | Mon 23:51 | 62 |
| wheel·(chair) | Notta Problem s02 | 9.2 | 2002 | 1286 | 1.56 | 9.2 | 1.01 | 38 | 14 | 0 | 0 | Tue 08:21 | 53 |
| cone·(stair) | Epilogue s05 | 17.4 | 200 | 164 | 1.22 | 6.0 | 0.34 | 56 | 1 | 0 | 0 | Tue 11:21 | 50 |
| cone·(key) | Prologue s02 (quiet) | 8.7 | 621 | 411 | 1.51 | 7.2 | 0.82 | 43 | 11 | 0 | 0 | Tue 13:21 | 48 |
| cone·(knot) | Passage s01 | 19.1 | 207 | 167 | 1.24 | 6.7 | 0.35 | 44 | 2 | 0 | 0 | Tue 14:21 | 47 |
| shadow·guitar | WBTSA s03 | 23.0 | 1376 | 1062 | 1.30 | 11.4 | 0.50 | 35 | 10 | 0 | 2 | Tue 18:22 | 43 |
| wheel·(planet) | Myth s06 | 10.0 | 470 | 323 | 1.46 | 7.3 | 0.73 | 45 | 2 | 0 | 0 | Wed 08:21 | 29 |
| group·(mug) | Talk s07 | 20.2 | 2371 | 1596 | 1.49 | **19.7** | **0.97** | 35 | 8 | 0 | 0 | Wed 11:27 | 26 |
| shadow·hourglass | Prologue s09 | 10.9 | 1751 | 1203 | 1.46 | 8.7 | 0.80 | 41 | 7 | 0 | 0 | Wed 14:22 | 23 |
| wheel·(helix) | Recess s10 | 17.5 | 190 | 155 | 1.23 | 7.5 | 0.43 | 53 | 2 | 0 | 0 | Wed 17:21 | 20 |
| cloud·cube | Notta Problem s06 | 14.3 | 2326 | 1617 | 1.44 | 10.6 | 0.74 | 43 | 8 | 0 | 0 | Wed 20:21 | 17 |
| group·(donut) | Suspended s05 | 6.2 | 302 | 152 | 1.99 | 8.8 | 1.43 | 36 | 1 | 0 | 0 | Thu 08:21 | 5 |
| group·(rocket) | Recess s03 | 17.4 | 237 | 157 | 1.51 | 12.5 | 0.72 | 40 | 1 | 0 | 0 | Thu 11:21 | 2.5 |

(shape in brackets = the shape knob was drawn but the kind does not use it; see "learner" below.)

What this says:

- **Outcomes are bimodal, not a gradient.** A post either stays with the ~150-200 followers-plus-a-little floor, or
  Instagram pushes it to 1,000-1,800 non-followers. Views/reach of 1.3-1.56 on the winners means a third to a half of
  viewers replayed it (the loop is doing work). Every win so far got there within ~17 h (cloud·cube), so the two
  Thursday `group` posts at 2.5-5 h are not yet readable; the Tuesday cones at 47-50 h are a verdict.
- **Kind is the whole story so far.** cloud 3/3 wins (median 2326), shadow 3/3 (1751), group 1/1 readable (2371,
  and the longest watch of the account: 19.7 s on a 20.2 s clip, i.e. people watched the whole thing and looped),
  wheel 1/3 (chair 2002; planet 470; helix 190), cone 0/3 (200, 621, 207; skip 43-56%, watch/len 0.34-0.35 on the two
  long ones). The `kind` weights in `weights.json` (cloud 1.07, cone 0.90) point the same way but are shrunk towards
  1.0 by the PRIOR of 5 posts, so nightly is still drawing cone at its menu weight (2 of 18) and wheel at 2 of 18.
- **Why cloud/shadow/group win and cone loses.** The winners share one shape of experience: a question the viewer
  answers in their own head in the first second ("which way is it turning?" / "three squares or four triangles?"),
  then the video *proves the viewer's answer was a choice* by cueing it the other way ("now it turns right ->", "<- now
  it turns left", "same dots the whole time. you choose"). That is the spinning-dancer formula; the payoff is personal
  and it invites a replay to try to flip it, which is exactly the views/reach > 1.3 and the 9-20 s watch. Cone has
  none of that: the opening line gives the answer away ("this is flat. circles on a disc, turning"), the stereokinetic
  depth is weak at phone size (13 thin rings, see `illusion_cone.png`), and there is nothing for the viewer to decide,
  so nothing to replay. Wheel is in between: a real effect, but the first ~3 s are a wheel slowly starting to spin
  (the aliasing only appears near the top speed), so the hook is late; wheel·chair won on a 9 s clip (the whole clip
  is the interesting part, completion 1.01), the 17.5 s wheel·helix lost (skip 53%).
- **Length.** Winners run 9-22 s; completion is highest on 9-11 s (0.80-1.01) and 14-17 s (0.69-0.74), lowest on
  22-23 s (0.50-0.55, though those still won on views). The phase marks are at 42/62/82% of the clip, so on a 9 s
  clip each cued phase is 1.8 s (barely enough to see the flip) and on a 23 s clip the undecided opening is 9.7 s.
  A fixed 12-14 s clip (5 s undecided, 3 s right, 3 s left, 2 s "you choose") fits the formula better than
  letting the section length decide. The learner's `length` buckets (under 10s 1.02, 20-35s 1.04, under 20s 0.95)
  are noise at n=2-6.
- **Songs/sections.** No song effect is separable from kind yet: Notta Problem is 2/2 (both winners, wheel+cloud),
  Epilogue is 2457 (cloud) and 200 (cone), Suspended 2087 (shadow) and 302 (group, young), Recess 1763/190/237. Vocal
  and instrumental stretches both win (Epilogue s07 and Recess s08 have no vocals; Suspended s02 and Prologue s09 are
  0.82 vocals). Keep every song in rotation; do not read the song weights (0.94-1.05) as signal.
- **Hour.** Wins at 08:21, 11:27, 14:22, 18:22, 20:21 and 22:55-23:51 NY; losses at 08:21, 11:21, 13:21, 14:21,
  17:21. Hour is not the driver; the late-evening lineup posts did best but they were also the first three posts of a
  fresh account and all cloud/shadow.
- **Saves/shares.** 25 shares, 9 saves, 29 comments over 15 posts: the first post (cloud·knot, 16 shares, 11 comments)
  carried most of it; the rest of the winners got 0-8 shares. Sends per reach are ~0.5% on the winners, which is low
  for 1,500 reach. The format earns watch time and replays, not sends. That is the next thing to design for (below).
- **Can the learner learn here?** Partly. (a) n=15 with 6 kinds x 12 shapes x 5 palettes x 3 asks is too thin for
  Thompson sampling to move off the menu weights for weeks; (b) `shape` is recorded on every video but only
  cloud/shadow draw a shape (wheel, cone, group, stripes ignore it), so the learner credits "chair 1.03" for wheel·chair
  and "stair 0.92" for cone·stair, pure noise that also pollutes the fresh-subjects rule (a group video "uses" a
  shape it never showed, so that shape is blocked for 3 nights); (c) kind is the one knob with a clear signal and the
  pipeline already supports `retire:` by hand in nightly.yaml. Hand-retire cone now rather than waiting for MIN_RETIRE=8.

### Content audit

- **Frame 0 / hook**: the question is on screen from frame 0 at y=300 in 70 px Montserrat (safe area, legible at
  phone size: see `illusion_cloud.png`), the shape is already turning. Good. Group's frame 0 is twelve bare dots with
  the question, weaker as a cover but it still won. Cone's frame 0 is the answer, not a question.
- **Loop**: the clip ends on "same dots the whole time. you choose" with the shape in an arbitrary phase and jumps
  back to the question. The number of turns in a clip is fractional for 12 of 16 renders (e.g. 4.95, 6.28, 7.11
  turns; the docstring says "one turn takes a whole number of bars", but the window is not cut to whole turns), so
  the loop seam is visible. stare_video.py already fades its last 9 frames into frame 0; the illusion renderer does
  not. A clean loop is the cheapest watch-time win on an account whose viewers already replay.
- **On-screen `ask` and engagement bait**: `ASKS` are "which way is it turning?", "left or right? now make it
  switch", "it turns one way. are you sure which?". Meta's engagement-bait definition covers asking people to vote,
  react, share, tag or comment ([Meta transparency center](https://transparency.meta.com/features/approach-to-ranking/content-distribution-guidelines/engagement-bait/));
  Instagram's 2024 clarification is that explicit asks for shares/comments/tags/other actions are what gets a post
  excluded from recommendations ([Social Media Today](https://www.socialmediatoday.com/news/instagram-says-using-certain-ctas-can-impact-post-reach/717732/)).
  A perceptual question the viewer answers silently is the *subject* of the video, not a request for a platform
  action: not bait under CLAUDE.md or Meta's rules, and it is the mechanism that makes the format work. Keep it.
  The learner says `ask` which 1.04, flip 1.03, sure 0.92 (n=3-8, not significant), but "it turns one way. are you
  sure which?" is the weakest line on its face (it tells the viewer the answer is "one way"). The caption
  "which did you see first?" (captions.txt) does not ask for a comment, but it is the only line that reads as a
  comment prompt; "pause it and check." (stripes' last line) asks for a pause, which is not a ranked action and is
  honest. Both are fine; I would not add anything closer to the line than these.
- **Captions**: statements, 5 hashtags (the Dec 2025 limit, [Social Media Today](https://www.socialmediatoday.com/news/instagrams-implementing-new-limits-on-hashtag-use/808309/)),
  song credited on line 2 plus the rotating first comment and "link in bio to stream {name}" (funnel `link` is empty in
  config.yaml, so the bio link must carry it). Consistent niche: a follower knows exactly what they will get.
- **Credit line** `♪ talk — close quarters` is 28 px DejaVu at y=1536: inside the safe area but small; it is the
  only on-screen song credit and barely readable on a phone. 36-40 px would still be discreet.
- **Cadence**: posts_per_day 5, posted 8 (Mon, with the 3 lineup posts), 4, 4. Account is 3 days old. The data does
  not show dilution: Wednesday's 4 posts produced 3 winners; each post gets its own cold-start test. What a wasted
  slot costs is a lower account-level average and a cone in a new follower's first impression. So the honest answer
  to "5 a day or 3 better ones" is: **5 a day of the kinds that work beats 3; 5 a day including cone/long wheel is
  worse than 3.** Keep 5, fix the mix, keep the 1 h minimum gap (already in the publisher). Mosseri's own position is
  that cadence has no single answer and that reach follows quality of each post ([RouteNote](https://routenote.com/blog/how-often-you-should-post-on-instagram/));
  Buffer's 2M-post study found reach per post holds up to daily-plus posting ([Buffer](https://buffer.com/resources/how-often-to-post-on-instagram/)).
- **House rules**: everything is drawn from formulas, no footage, no band, no asks. Clean. `polish` is deliberately
  off for illusion pages, good (a grade or bloom would change the dots' brightness, which is the depth cue).

### Research: what the niche does and what Instagram rewards

- Instagram's stated top ranking signals (Mosseri, Jan 2025): watch time, likes per reach, sends per reach; sends
  weigh more for non-followers, likes for followers ([Social Media Today](https://www.socialmediatoday.com/news/instagram-shares-algorithm-insights-2025/738034/),
  [Buffer](https://buffer.com/resources/instagram-algorithms/)). Skip rate (share who swipe away inside 3 s) was
  added to Insights in Aug 2025 as the hook metric ([Metricool](https://metricool.com/instagram-reel-analytics/),
  [exchange4media](https://www.exchange4media.com/influence-zone-news/instagram-introduces-skip-rate-new-metric-to-make-brandcreator-conversations-tougher-146829.html)).
  This account is already the network's best on all three.
- Originality: since Apr 2026 accounts that mostly repost or lightly transform others' content are no longer
  recommended to non-followers; identical content is deduplicated to the original ([TechCrunch](https://techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/),
  [Social Media Today](https://www.socialmediatoday.com/news/instagram-expands-originality-reach-penalties/819016/)).
  Drawn-in-code illusions are the safe end of this; the risk is reproducing a named artist's specific image
  (e.g. Kitaoka's "Rotating Snakes" figures are his copyrighted artwork even though the peripheral-drift principle is
  not; [Kitaoka's pages](https://www.ritsumei.ac.jp/~akitaoka/index-e.html)).
- Trial reels (Dec 2024): a reel shown only to non-followers first, with 24 h metrics and optional auto-promotion to
  followers after 72 h ([Instagram creators blog](https://creators.instagram.com/blog/instagram-trial-reels)).
  `accounts.yaml` has `trial_reels: false` for illusions_ig; trials are the right tool for new kinds (below).
- Motion illusions are the best-performing illusion content on short video (rotating snakes, spirals, the spinning
  dancer family); the recurring viral lines are "which way is it spinning", "your brain decides", "watch it flip"
  ([Creative Bloq](https://creativebloq.com/news/rotating-horse), [Filmora, vendor claim](https://filmora.wondershare.com/ai-prompt/optical-illusion-video.html)).
  The account is on the right formula; what the big illusion pages add is (a) a flip you can *cause* ("look at the
  foot / look at the top") and (b) a reason to send it ("send this to someone and ask which way").

### The next 10 kinds (all drawable in `illusion_video.py` from formulas, all true on screen, ranked by fit to the
winning formula: a question, the viewer's brain picks, the video flips it, "you choose")

1. **Ames window** (backlog has it): a trapezoid "window" of dots turning a full circle seems to oscillate back
   and forth. Ask "is it turning or swinging?"; cue by drawing the true far edge dimmer, then take the cue away.
2. **Necker cube** as a dot wireframe, slowly turning: the viewer's front face flips; cue with occlusion of the far
   edges one way, then the other. Reuses the `cube` points.
3. **Point-light walker** (Johansson): 13-15 dots walking in place, seen from the front/back: "walking towards you
   or away?" It is the most famous ambiguous-motion figure after the dancer and nobody on the network does it.
4. **Two shells** (backlog "level hard"): two dot clouds of the same shape, one inside the other, turning opposite
   ways; "which one is turning left?" Then each is cued in turn. Harder, longer watch.
5. **Hollow mask / hollow shape**: a dot-shell of a face-like bowl (or any of the 12 shapes) rendered concave; the
   brain sees it convex and the turning direction reverses. Cue with lighting from one side, then the other.
6. **Pinna rotation**: two rings of tilted squares; as the camera zooms in and out on the beat they seem to
   counter-rotate. "nothing here is rotating" / zoom stops / "still not rotating".
7. **Stepping feet**: two bars (one light, one dark) sliding at the same speed over black/white stripes seem to
   step alternately; cue by removing the stripes (they glide together), then putting them back.
8. **Barber pole**: stripes on a cylinder moving sideways read as moving up; cue by showing the cylinder's ends.
9. **Four-stroke / reverse-phi motion**: a pattern that only ever oscillates two frames but seems to drift forever
   in one direction; "it never moves right" / show the two frames side by side.
10. **Ouchi**: a disc of orthogonal stripes in a field of stripes that seems to float and slide when the frame
    jitters on the kick; "the disc never moves" / jitter stops / "it never did".

Keep: cloud, shadow, group, stripes (untested: its one post was a duplicate booking; the sheet looks right). Demote
wheel to a 9-10 s only kind (it works when the clip is the top-speed part). Retire cone, or rebuild it with a question
and a stronger cue (the rings bigger and thicker, fewer of them, a wobble on the beat) and trial it.

Motion-induced blindness and the Troxler fade belong on eye.trick.lab (they need a fixation), not here.

### Recommendations (ranked by expected impact)

1. **Fix the kind mix now** (quick, `studio/nightly.yaml` illusions target): `retire: {kind: [cone]}` and change the
   menu weights in `illusion_video.py` from `[5,3,2,2,3,3]` to cloud 5, shadow 4, group 4, stripes 2, wheel 1, cone 0.
   Expected: the per-post win rate goes from ~8/15 to ~11/15 at the same cadence.
2. **Loop cleanly** (medium, renderer): cut the clip to a whole number of turns (round `n` down to a multiple of
   `self.turn`, or pick `t1` so it is) and fade the last 9 frames into frame 0 the way `stare_video.py` does. Measure:
   views/reach and watch/len on the next 10 posts vs the 15 here (1.40 and 0.69 medians).
3. **Fix the three-phase timing to the clip, not the section** (medium): target 12-14 s and set the marks in seconds
   (undecided 5 s, right 3 s, left 3 s, "you choose" to the end) instead of 42/62/82%. Keep a 9 s wheel variant.
   Learner: a new knob `phase` (pct vs seconds) so it is measured.
4. **Stop recording `shape` for kinds that do not draw it** (quick, renderer: only `K.pick('shape', ...)` inside
   `cloud`/`shadow`). Removes learner noise and the false fresh-subject blocks.
5. **Design for sends** (medium, captions + one on-screen line): the one thing this account does not earn. Replace
   the weakest caption lines ("look away, look back" 0.97, "this is your brain filling in what is not there" 0.92)
   with lines that give a reason to send without asking ("most couples disagree on this one", "argue about this one
   with someone", "show this to the person who thinks they can't be fooled"). None of these asks for a share, tag or
   comment. Measure: shares per reach (0.5% now).
6. **New kinds as trial reels** (large, one kind per PR): add Ames window, point-light walker and Necker cube first
   (they are the closest to the winners), each posted as a trial reel (`trial_reels: true` for those renders only, or
   a `trial` flag on the recipe) so a dud never reaches followers. The learner measures them as `knob:kind` like
   everything else; promote a kind to the menu after 3 posts with views above the account median.
7. **Bigger credit line** (quick): `f_small` 28 -> 36 px, and put the song title in the first caption line of one
   post in five ("the song is Talk by Close Quarters: that is why it turns on the beat") to see whether a visible
   credit lifts bio taps (`studio/clicks.json`).
8. **Harder second act for the group kind** (medium): group·mug held viewers for 19.7 s; a `group` variant with the
   lines fading in and out on the bar, twice, would turn one win into a repeatable one.

### Risks

- Nothing here breaks the house rules. The `ask` questions and "pause it and check." are not engagement bait.
- Loop seams and the cone posts are the only quality risks. No music-rights risk (own songs, `audio_name` set).
- Do not add band content, carousels or other styles to this account; its niche consistency is why cold starts win.
- Duplicate-booking failure on 2026-11-26 (stripes·key) is already fixed network-wide; the stripes kind is still unmeasured.

---

## 2. @eye.trick.lab (eyetrick_ig, campaign `stare_lab`, `studio/stare_video.py`) and the paused ruler_says_no / colour_lies pages

**Verdict: too early to judge (1 post, and it was the old illusion format); the biggest lever is to make this the
one "eye tricks" page that tests stare, colour and measure as kinds of one account before any new account is created.**

### What the numbers say

Nothing yet. The only published post (2026-11-26 13:31Z, "cone·donut", Evil Close Quarters) was the old `eye_tricks`
campaign's near-copy of rotation.illusions, and a cone at that; it has no figures (Page-token account, 5 h old at the
fetch). Its twin at 21:01Z was cancelled as a near copy. The first real stare post (colour·beach, Prologue) is queued
for 16:07 NY. Four stare renders exist (3 colour, 1 of them "beach" twice; 0 spiral, 0 chaser): the kind weights
`['colour','colour','spiral','chaser']` make colour half the output, fine for a first week, but the chaser is the most
famous of the three (the "lilac chaser") and should get an early slot.

### Content audit (from the sheets)

- `stare_colour.png`: frame 0 is a flat negative-colour beach with a dot, a countdown (14) and "stare at the dot until
  it turns grey" in 64 px. The instruction is clear and the picture is bold and flat (good for an afterimage). Two
  issues: (1) the countdown is the only thing that moves for 13 s; in the reel feed, a still picture with a number
  reads as a slideshow and will be skipped by the people who don't read, so expect a high skip rate even if the people
  who stay get a strong effect. A slow drift of the kick-driven ring (already there, but 3 px wide) is not enough.
  (2) the payoff line "the picture is black and white. the colour is in your eyes" appears 1.4 s after the switch,
  which is the right moment, but the grey picture stays for the remaining ~4.5 s with no further event, and the fade
  back to frame 0 restarts the stare: the loop works against the format (a viewer who looped would see the colour
  version again, which kills the afterimage they were enjoying). Consider a different end: hold the grey, then
  "blink. now look again" and show it once more in negative as a second, shorter stare.
- `stare_chaser.png`: correct lilac-chaser geometry, instruction "stare at the cross. don't follow the gap", payoff
  "every disc is gold. there was never a blue one" (true). Phone risk: Instagram's chroma subsampling blurs soft
  blobs, which actually helps the chaser.
- Lengths 15-18 s (cut to 24 max). The format inherently needs 8-14 s of nothing, which is the opposite of what the
  skip-rate metric rewards; the account should be judged on watch time and shares of the people who stay, and the
  caption bank already frames it honestly ("a slow one. it's worth holding still for").
- Captions are statements, 5 hashtags, song credited, first comment set, 1/day for the first week. Good.
- Niche: "eye tricks" is broad enough to hold afterimages, colour illusions and measured illusions; "stare lab" would
  be narrow. The handle is the broad one, which is an advantage (below).

### Which of ruler_says_no (`measure`) and colour_lies (`hue`) deserves an account first?

Evidence from the one account with data: the illusion formula that wins is *question -> the viewer commits ->
proof that their eyes chose -> loop*. Both ready pages have that shape (question held ~4.6 s with a filling bar, then
a measurement/eyedropper on the beat, then "measured. still looks wrong." / "same colour. still looks different.").
Differences:

- **colour_lies first.** Colour illusions are the illusion sub-genre with the strongest recent share history
  (Munker-White "the spheres are all the same colour", the confetti illusion) because the proof is a thing people
  argue about and send to each other; the hex-code eyedropper is a stronger proof than a ruler, and it reads at phone
  size (two big swatches). It also covers songs no other page uses (Myth, Prologue, Passage, Epilogue). Risk to check
  before launch: Instagram re-encodes at 4:2:0 chroma, so thin coloured stripes (Munker, Bezold) smear. Render a test,
  upload as a trial reel, and look at it on a phone; stripes should be at least ~8 px wide at 1080 and the swatches
  solid. The hex codes are read before encoding, so they stay true; the stripes' *look* is what is at risk.
- **ruler_says_no second.** Its seven illusions are the textbook ones everyone has seen (Muller-Lyer, Ebbinghaus,
  Ponzo, cafe wall); the ruler payoff is satisfying but less sendable, and the surprise is smaller for most adults.
  Its best kinds for Reels are the ones that look like a scene (cafe wall, Hering) rather than two lines.
- **Better than either as a first step:** eye.trick.lab has no identity yet (1 post, an old-format cone). Run it as the
  general eye-tricks page for two weeks: `stare` 50%, `hue` 30%, `measure` 20%, at 2-3 posts a day. The campaign
  machinery supports several styles per campaign (physics_sims runs physics+fluid+stopit), so this is three
  nightly.yaml targets on `stare_lab` (or one campaign renamed `eye_tricks`) with no new account, no new Page, no new
  token. The learner then ranks `style` with real numbers, and the winner gets spun out to its own handle (the ready
  page's config is already written) when the operator has time for Meta's account dance. That protects the
  operator's scarcest resource (account creation and OAuth sessions, see traps.md) and avoids three 1-post pages.

### Research

- The stare formats are the ones Instagram's own hook metric punishes (nothing moves for 10 s). Everything in this
  genre that travels does so on sends ("do this, then tell me what you saw"), so the caption and first comment matter
  more here than on rotation.illusions. Sends per reach is the signal Mosseri names for non-follower reach
  ([Social Media Today, 2024](https://www.socialmediatoday.com/news/instagram-chief-post-share-rates-key-driver-reach/716540/)).
- The chaser and afterimage effects depend on the phone being held still and the dot being looked at; the countdown
  is the right device (every viral version has one).

### Recommendations

1. **Make eye.trick.lab the eye-tricks page with three styles** (quick: nightly.yaml + config): add `hue` and `measure`
   targets to campaign `stare_lab` at per_night 2/1 alongside stare 2; `posts_per_day` 2 for week one, then 3. Learner
   measures `style` (quick) and `knob:kind` per style.
2. **Give every stare post one moving thing from frame 0** (medium, `stare_video.py`): a slow 2-3% breathing zoom on
   the picture or the dot pulsing on the kick, so frame 0-3 s is not a still. Measure skip rate against the first 10.
3. **End differently** (medium): after the payoff line, hold grey for 2 s, then show the negative again for 3 s as a
   second stare ("again. shorter this time."), and loop from there. The loop then helps instead of hurting.
4. **Put the chaser first** (quick): `--set kind=chaser` for two of the first week's posts; it is the kind people
   already know by name.
5. **Trial-reel the hue stripes on a phone before the first hue post** (quick): confirm the Munker stripes survive
   Instagram's re-encode; widen stripes if not.
6. **Captions for sends**: "do this with someone and compare what you saw" is a statement of what to do with the
   video, not a share-ask; keep the bank honest and add two lines like it.

### Risks

- The one published post is a near-copy of a sibling account's format (already cancelled from the queue; the live
  one stays up). Instagram's duplicate-content rule applies to identical media, not to a style, so no action needed.
- A still picture with a countdown will post high skip rates; do not let the network-wide skip-rate comparison
  retire the style before watch time and sends of those who stay are read.
- The afterimage and chaser claims on screen are true of the picture; keep `polish` off here (it is).

---

## 3. @8bit.tests (tests8_ig, campaign `pixel_tests`, `studio/tests8_video.py` + `studio/mathviz/tests8.py`)

**Verdict: needs work, and it is flying blind: the single biggest lever is getting the insights permission onto
IG_TOKEN_3 so the 8 published posts (and the learner) get numbers.**

### Why posts.json has no `m`

`campaigns/pixel_tests/posts.json` has all 8 posts with `"metrics": []` and `fetched_at 2026-11-26T19:00Z`. The
metrics run that produced it (workflow `metrics`, run 45876580322, 18:31Z today) logs, for every pixel_tests post:

    instagram_insights_unavailable ... "(#10) Application does not have permission for this action (HTTP 400, code 10)"

`src/publishers/instagram.py::_media_metrics` catches that as an `InvalidPostError` and returns `()` with only a
warning, so the dashboard shows an empty `m` and nothing flags it. traps.md ("Unified-login accounts had no numbers,
2026-11-25") says `instagram_business_manage_insights` was added to the app and the tokens regenerated; the run log
shows the token in use for tests8_ig still lacks it, and so do every other Unified-login account's tokens in the same
run: algo_races (9 posts), notes_app (9), notes_him (7), notes_her (7), toon_edits, notes_date, notes_college,
museum_zoom, lowpoly_stories (1 each), plus `clubs` (45, not ours). Either the regenerated tokens were not written to
the secrets, or the accounts need to go through the connect flow again so the grant includes the new scope (a token
only carries the permissions granted at login; adding a permission to the app does not upgrade existing tokens, and
`tokens.yml`'s refresh keeps the old scope). Concrete fix: for each of those accounts, re-run
`connect.closequarters.vip/connect?u=<handle>` signed in as that account, confirm the scope list in the dialog includes
insights, then `gh workflow run metrics.yml -f instagram_only=true` and grep the log for `(#10)`. Also worth a small
change: when every post of an account comes back empty with code 10, the dashboard account card should say
"no insights permission" instead of "-". That is a cross-cluster finding; it affects nine accounts.

Also found in the dashboard data: 4 pixel_tests posts are `cancelled` with due dates of 2026-12-08/09 (12 days out),
and the 2026-11-26 duplicate-booking failures are the known network-wide incident.

### What the numbers say

Nothing can be said about performance. What can be said about the pipeline: 8 posts in 3 days (Mon 1, Tue 4, Wed 3),
5/night rendering, tests chosen so far: flashes 4 and read 2 (the retired pre-rebuild tests, still in `recipes.json`
and on the menu `["flashes","read","pause",...]`; the first two published posts were old-format renders), then
pause 1, memory 3, count 2, cups 1, beat 1. One render is 51.1 s long (suspended s06, memory): BEATS=28 at that
stretch's tempo; check it before it posts, 51 s is twice the format's natural length. Lengths otherwise 17-27 s.

### Content audit (from `tests8_count.png`, `tests8_pause.png`, `tests8_cups.png`)

- **Is the instruction readable on frame 0?** Yes. "COUNT THE / FIREWORKS", "PAUSE WHEN / IT FITS", "FOLLOW / THE GEM"
  are on frame 0 in the 5x7 pixel font at scale 3 (84 px glyphs at 1080 wide), gold on the night sky, centred at
  x=520 (clear of the right-hand buttons), y 264-372: inside the safe area. The sub-lines ("SOUND ON", "NO PAUSING",
  "ROUND 1 OF 3", "FRAME 0000") are scale 1-2 (28-56 px); the 28 px ones are at the limit of phone legibility but they
  are secondary. The countdown "2" at scale 4 with the draining bar is clear.
- **Solvable at phone size?** pause: yes (big shapes, big hole; the 4/2/1-frame ladder means round 1 is winnable,
  round 3 is not, and the on-screen frame counter lets a paused viewer verify; honest). cups: yes, three large pots,
  but 14 swaps in ~17 s with the late ones on every hit is at the edge; the reveal "POT 3, 14 SWAPS, ALL ON THE BEAT"
  is a good true line. count: the hardest to read, because the city world's lit windows, ground sparkles and the
  small coloured bursts at the skyline bottom (see frame 2 of the sheet) look like small fireworks; a viewer counting
  on a phone cannot be sure what counts. The reveal numbers 1-8 over the bursts make it fair after the fact, but the
  distractors are a design flaw for a counting test (the sky should be the only place things burst, and the
  bottom-row sparkles should be off during the count). memory and beat: not rendered here; the code puts the six
  crystals on two rows at scale with badges, fine.
- **Hook**: the instruction is the hook, as in the genre. What the genre adds and this does not: a stake in the first
  second ("round 1 of 3" is there; a visible success/fail state at the end of each round is not). After round 1 of
  pause, a 1-word "FIT" / "MISSED" stamp on the tablet would give the viewer a score to beat and a reason to replay.
- **Loop**: the reveal holds to the end, then cuts to the instruction; acceptable for a test (a loop seam does not
  hurt a format you play once), but the reveal frames are 3-4 s of a static card.
- **Comparison with the "only 1% can pass" genre, without the bait.** That genre runs on three devices: an
  unverifiable claim ("only 1%", "99% fail"), a pause/screenshot ask, and comment prompts ("comment your score").
  The first is dishonest and the other two are asks. tests8 keeps the honest parts (a test with a true answer, a
  countdown, a reveal) and drops the asks: "PAUSE WHEN IT FITS" asks the viewer to pause the video, which is not a
  ranked engagement action and is the game itself, not bait. What it loses without the claim is the self-assessment
  hook; a true version of it is available: the answer's own difficulty ("it fit for 1 frame", "14 swaps") and a
  "you can check: frame 0275" line. That is already there for pause; add the equivalent for cups ("the gem moved 14
  times") and count ("8 bursts, all on snares").
- **Captions**: statements, 5 hashtags, song credited. "try it before you read the comments" is close to a comment
  prompt; replace it. The bank is otherwise fine.
- **Cadence**: 5/day on an account 3 days old with no feedback. Until metrics flow, 5/day is a guess multiplied by
  five. 3/day until the learner can see.
- **House rules**: own pixel art, own font, no game characters, no footage. Clean.

### Research

- Pause-challenge and "stop it on" formats are a steady TikTok/Reels genre; the posts that travel pair a precise
  target ("pause when the car fits the box") with a reflex framing; the bait versions add screenshot/comment asks
  ([TikTok tag pages](https://www.tiktok.com/discover/pause-the-video-trend)). Memory and quiz reels work because they
  demand a decision from the viewer, which resets attention ([Typito, vendor](https://typito.com/blog/quiz-reels-trend-report-boost-engagement/)).
- Instagram's 3-second skip rate is the opening metric; a test whose instruction is readable on frame 0 is well
  placed for it ([Metricool](https://metricool.com/instagram-reel-analytics/)).
- Hashtags: 5 max since Dec 2025 (bank complies).

### Recommendations

1. **Get insights on IG_TOKEN_3 (and the other eight Unified-login tokens)** (quick, operator): re-connect each
   account through the connect link with the insights scope; verify with one metrics run. Until then the account
   cannot be judged or learned from.
2. **Drop to 3/day until numbers flow** (quick, `posts_per_day: 3`).
3. **Fix the count test's distractors** (medium, `pix8.py`/`tests8.py`): no ground sparkles and dimmer skyline
   windows while counting; bursts only in the top 40% of the sky.
4. **Score stamps per round** (medium): "FIT" / "MISSED BY 4 PX" after each pause round, "SWAP 14" ticking in cups
   (already there), a running "7..." for count only at the reveal (never during, that would solve it for the viewer).
5. **Remove the pre-rebuild tests from the menu** (quick): `flashes` and `read` are still in `recipes.json`'s menu
   and may be drawn by `EXPLORE`; make sure the renderer's `K.pick('test', ...)` list is the source of truth (it is:
   five tests) and that nightly's free draws cannot pick menu entries the renderer no longer accepts.
6. **Cap length** (quick): render only stretches where 28 beats is 14-26 s; the 51 s memory render should not post.
7. **Caption line**: replace "try it before you read the comments" with "one try. the reveal is exact".

### Risks

- Zero-feedback posting at 5/day on a 3-day-old account; nothing rule-breaking.
- "PAUSE WHEN IT FITS" is a pause ask, not an engagement ask; keep it out of captions anyway (the on-screen
  instruction is the game; the caption should not add asks).
- The 4 cancelled posts dated 12-08/09 suggest the queue once reached 12 days out; `max_backlog_days: 1` is set, so
  that is past, but check that the cancelled ones did not consume clips (`repeats: false`).

---

## 4. @digital.petri.dish (petri_ig, campaign `petri_dish`, `studio/alife_video.py`)

**Verdict: rethink the format; the single biggest lever is giving every video an arc with a promise on frame 0 and
a resolution at the end, because right now nothing happens that a viewer could wait for.**

### What the numbers say

13 posts with figures, views 41-238 (median 164), reach 38-202: never once pushed past followers. Skip rate 58-95%
(median 75%, fourth-worst campaign on the network), watch 1.6-5.0 s on 6-18 s clips (watch/len 0.14-0.58, median
0.22). One share, six saves, zero comments beyond the first comment. By start knob:

| start | posts | views | skip % | watch s | watch/len |
|---|---|---|---|---|---|
| ring | 3 | 164, 190, 146 | 71, 58, 77 | 3.0, 5.0, 3.8 | 0.39, 0.33, 0.58 |
| rain | 4 | 229, 172, 167, 184 | 72, 71, 73, 79 | 4.1, 3.2, 2.9, 3.0 | 0.26, 0.20, 0.16, 0.19 |
| seeds | 6 | 238, 149, 148, 150, 53, 41 | 81, 80, 73, 80, 90, 95 | 2.5, 4.7, 3.7, 2.4, 1.6, 1.6 | 0.31, 0.27, 0.22, 0.14, 0.19, 0.15 |

`ring` is the only start that holds anyone (the weights agree: ring 1.07, seeds 0.94) and the sheet shows why: a ring
is the only start with a visible *event* (a bright ring collapsing inward into veins over the first 4 s,
`alife_ring.png` frames 1-2). `seeds` and `rain` are a finished network from frame 0. The two newest posts (seeds·bio
53 views, seeds·ember 41 views, skip 90-95%) are the account's worst and both are seeds. Palette, sense and steps show
nothing (all within 0.96-1.06 at n=2-5). Song: nothing separable. Hour: evening slightly better, n too small.

Why watch time is so low, specifically:
1. **Frame 0 makes no promise.** The only text is `physarum · 1,200,000 agents` and `each one smells left, ahead,
   right · turns · steps · leaves a trail` in 22-26 px mono at the top left: unreadable on a phone and meaningless to
   anyone who does not know the word physarum. Every other drawn style on the network puts a 64-70 px line in the
   safe area from frame 0; this one does not. The viewer sees glowing veins and no reason to stay.
2. **The becoming happens before the viewer arrives.** `CQ_WARMUP=90` runs 90 steps before frame 0, so the network
   has already formed; what is left is slow drift, kicks that brighten it and snares that fling 50,000 agents from a
   random point. There is no state the video is moving towards, so there is nothing to resolve and no reason to reach
   the end. The 'ring' start is the exception precisely because its first seconds are a transformation.
3. **No end.** The clip stops wherever the section stops. No "it found it", no shape, no count, nothing to screenshot
   or send.
4. The caption bank is good copy ("nobody drew this. it grew") but it is in the caption, which the reel feed hides
   behind "more"; the one line that could hook is not on the picture.

Can the learner learn here? Only `start` has a signal, and it is the one knob that is really "is there an event".
Everything else is cosmetic. The learner cannot fix a format with no arc; it can only pick the least bad knob.

### Content audit

- Hook: none on screen (see above). Loop: none (no fade to frame 0; frame 0 is a formed network anyway). Legibility:
  the only text is too small. Song credit: 26 px mono at the bottom left, inside the safe area, barely readable.
- Captions: statements, honest, 5 hashtags, first comment. "it finds the shortest path on its own" (0.94) is a claim
  the video does not show; it should only be used on a video that shows a path being found.
- Niche: consistent, and the pictures are genuinely good (the full-resolution physarum of 2026-11-26 is the best-looking
  thing on the network). The problem is purely dramaturgy.
- Cadence: 5/day of a format with 75% skip is the one case in this cluster where volume is clearly hurting: every post
  trains Instagram that this account's reels get swiped. 2/day until the arc exists.
- House rules: own simulation, no footage, no asks. Clean.

### Research

- Every slime-mould clip that has ever travelled is a *task being solved*: the oats-in-a-maze shortest-path timelapse
  (Will Stevens, 2011, re-shared for a decade as a GIF) and the Tokyo-rail-map experiment (Tero et al. 2010), both
  framed as "a brainless blob solves X" ([Live Science](https://www.livescience.com/64218-slime-mold-hunts-prey-gif.html),
  [Tokyo subway recreation](https://kody-w.github.io/learnwithkody/examples/slime-mold/), [SwarmLab](https://swarm-lab.github.io/blog/slimelapsegallery/2015/01/02/slimelapsegallery-1)).
  The simulation community's demos (fogleman/physarum, Sage Jenson) are watched as "it forms into X" sequences, not as
  steady states. In other words: the niche's native format is a race/maze/map with a result, which is what the brief
  suggests and what the data here independently says.
- Instagram's ranking signals (watch time, sends; skip rate as the hook metric) all punish a still-ish picture with no
  promise ([Social Media Today](https://www.socialmediatoday.com/news/instagram-shares-algorithm-insights-2025/738034/)).

### What would make it a watch-to-the-end format (in order of build cost)

1. **Start from the seed, every time** (quick): `CQ_WARMUP=0` (or 10) for `ring` and `seeds`, so the first 4 s are
   the colony exploding into a network. The sheet shows this is the best-looking 4 s the renderer makes, and it is
   currently thrown away. Measure: skip rate on the next 10 vs 75%.
2. **A frame-0 line in the house font** (quick): 64 px Montserrat in the safe area, true of the video, e.g. "no
   brain. watch it find the food." / "1,200,000 cells, three rules". Keep the mono HUD as a secondary line at 36 px.
3. **Food, so there is a goal** (medium, `alife_video.py`): drop 2-5 "food" sources (a strong trail deposit at fixed
   points, drawn as bright dots); the colony floods, then prunes to the connections. End on the pruned network with
   "connected: 5 of 5" and a 9-frame fade to frame 0. This is the Tokyo-map format and it needs only a deposit term.
4. **The race** (medium): two colonies (the `species` knob already exists, three colours that avoid each other's
   trails) start in opposite corners with one food blob in the middle; the line is "two slimes, one meal"; the end is
   the one that reached it first, named by colour ("gold got there on beat 14"). True, scored, sendable.
5. **The maze** (large): a maze of our own (recursive-backtracker, drawn as walls the agents cannot cross by zeroing
   the trail and reflecting heading on wall cells), food at the exit, colony at the entrance; the colony fills it and
   withdraws to the shortest path ("shortest path: found. no brain."). This is the genre's single most famous clip,
   and nobody on Instagram is doing it as a clean simulation set to music.
6. **Time-lapse to a shape** (large): food placed along a mask (the song's title in the 5x7 pixel font, a heart, the
   album's title) so the network *is* the word by the end. Reveal: "it spelled TALK. nobody told it to." True because
   the food did the telling; say so in the caption.

### Recommendations (ranked)

1. **Warm-up off, headline on, 2/day** (quick, today): the three cheapest changes, together: `CQ_WARMUP` 0-10, a
   64 px true line from frame 0, `posts_per_day: 2`, `per_night: 2`. Expected: skip rate from 75% towards 55-60%,
   watch from 3 to 5+ s. The learner measures `knob:start` as now.
2. **Retire `seeds` and `rain` as starts until (3) exists** (quick, nightly.yaml `retire: {start: [seeds, rain]}`):
   ring is the only one with an event.
3. **Food targets + pruned ending + fade to frame 0** (medium): the smallest change that gives the video an end.
   New knobs `goal` (none/food/race) and `ending` (open/connected) so the learner can see it.
4. **The race** (medium): same code path as (3) with two species; the line and the end are true by construction.
5. **The maze** (large, one PR): the format the niche is known for; worth a trial reel first.
6. **Caption honesty**: use "it finds the shortest path on its own" only on (3)/(5) videos.
7. **Credit line bigger** (quick, 26 -> 36 px).

### Risks

- 5/day at 75% skip is the one cadence risk in this cluster; reduce now.
- No rule or rights risk: own simulation, no asks. The claims on screen must stay true: "connected 5 of 5" and
  "gold got there first" must be computed from the trail map, not asserted.

---

## Cross-cluster notes

- Nine Unified-login accounts (not just 8bit.tests) have had no insights since launch because their tokens lack
  `instagram_business_manage_insights`; the metrics job swallows the error. Fix once, verify with one run.
- The learner's `shape` knob on illusions and the retired `flashes`/`read` tests on pixel_tests are both cases of
  recipes recording knobs the renderer did not use; a one-line rule in `knobs.py` (only record a pick that was read)
  would stop both.
- Network-wide, the only two campaigns under 41% skip are the two where the viewer is asked a question they can
  answer in their head in the first second (illusions) or shown a clip with an obvious thing about to happen
  (rocket). That is the lesson to carry to petri_dish and the stare page.
