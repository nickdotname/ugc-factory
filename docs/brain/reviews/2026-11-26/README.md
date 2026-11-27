# Account review, 2026-11-26: every account, what the numbers say, what to change

Back to [[README]]. Eight reviewers (one per cluster plus one for the shared machinery and one for outside research)
read the repo, the posts' numbers (`baseline.md`, `views-by-day.md`), the renderers and contact sheets, and the
2025-2026 guidance Meta has published. Their full reports are beside this file: [[band]], [[science]], [[perception]],
[[archive]], [[worlds]], [[notes]], [[system]], [[research]]. This note is the synthesis and the plan. Nothing in the
repo was changed by the review; every change below is a proposal for its own PR.

## The ten things that matter most (verified against repo data, not only the reviewers' word)

1. **No reel is attached to a song.** 543 published reels, 0 carry an `audio_id`; 475 are "Original audio" under the
   niche account's own name. The audio sticker, the one way music spreads on Reels, points at @math.explainers etc.
   and never at the band or the song. The code path exists (`PublishRequest.audio_id`, `audio_configuration`,
   `scripts/ig_audio_search.py`) and has never been run. EDUCATION should be reaching Meta's music library from the
   distributor about now (1-4 weeks after release). This is the biggest lever in the whole engine.
2. **The band's own account posts only trial reels.** `trial_reels: true` on close_quarters_ig and dylancantor23_ig:
   53 of 54 and 48 of 48 automated posts are hidden from followers and from the grid until Instagram graduates them,
   and at 99 median views none graduate. The one non-trial band post did 631 views and 14 shares. A visitor sent by 25
   niche accounts lands on a near-empty profile.
3. **The cutout style never ships.** `nightly.yaml` renders 7 cutouts a night for cq_band "because the dance footage
   is what works"; 27 are in the libraries, at most 3 have posted, and 44 of 68 bookings since 11-22 were the desktop
   `band` style the 11-24 pass meant to cut. Cause: render only gives cutout a 3x `favour_styles` boost, which the
   performance medians of the older band clips cancel. Render needs a per-style quota, not a boost.
4. **Ten accounts are blind.** 82 published posts on the Unified-login accounts (IG_TOKEN_2..11: algorithm.races,
   8bit.tests, the five notes pages, rubberhose.radio, zoom.into.art, what.if.town, dining.hall.philosopher) and the two
   Page-token accounts have no numbers: every insights call returns `(#10) Application does not have permission`
   (tokens lack `instagram_business_manage_insights`), the metrics job logs a warning and stays green, and the learner
   picks their knobs at random.
5. **Reach is a coin flip and the oldest accounts are losing it.** A post either gets a test batch of 100-300
   non-followers or 0-10 views. Share of posts that get a batch: ascii.terminal.dreams 23/24; psychedelic.station fell
   from 4/17 (11-21) to 0/8 (11-26); nostalgia 6/14 to 0/8; the.loose.change from ~170 to ~20 median on 11-20. The
   network peaked at 150 posts/day on 11-24 with no gain in total views. Volume is dividing a fixed audience.
6. **Skip rates are 71-84 % (benchmark ~65 %).** Viewers leave before the first cut, so the lever is frame 0-30, not
   the edit. vintage and cinema open on abstract Ballet Mécanique shapes because the opener score rewards motion x
   contrast; math scenes open on definitions; petri dish throws its best 4 seconds away in a warm-up.
7. **The learner is noise shaped like a bandit.** 1,565 option weights all between 0.87 and 1.13, 1-6 posts per
   option, zero automatic retirements; hour-posted is learned but never chosen (a pure confounder); cq_band and
   rocket_league score `comments / reach`, and since every post carries exactly one comment (our own credit) that
   rewards the lowest-reach posts. Where it has signal (`cut`, subject), short cuts win everywhere: completion 0.46
   under 10 s vs 0.17 at 20-35 s.
8. **The song credit is hidden on nine renderers.** math, race, alife, tinycode, fluid, hue, measure, reveal, stare
   draw `♪ title — close quarters` below y 1500, under Instagram's caption overlay; ascii draws it under the top bar;
   psy and liminal draw none.
9. **Rights and policy tripwires.** Steamboat Willie (1928, public domain, but Mickey is a live Disney trademark and
   the film is rights-matched everywhere) is in the toons pool three times and passes `footage.TRADEMARK` because the
   title lacks "mickey"; `silent:Aristocr1940` is a 1940 film indexed as 1930; vintage.media.archive already holds an
   originality notice; every psychedelic.station fact reel is about LSD/psilocybin dosing (Recommendation Guidelines:
   regulated products); four math scenes still say "follow for the next one".
10. **The funnel is unmeasured.** Bio-link taps (`studio/clicks.json`) stopped recording on 11-22; no follower count or
    profile-visit count is logged anywhere; the one conversion number the system has is blind.

## Every account

| account | verdict | the lever | cadence |
|---|---|---|---|
| @close__quarters | needs work (distribution, not content) | trial off; make cutout actually post; 3/day: cutout 2, band 1; retire cursor and lofi | 8 → 3 |
| @dylancantor23 | needs work | trial off; hand-chosen 8 bars per song, drums-first builds, a person on the cover | 8 → 2-3 |
| @the.loose.change | rethink | rebuild the meme pool from own footage (nyc meme kind, Nick's clips, Rocket League); type 1/day or retire; move off Buffer | 3 → 1-2 |
| @rotation.illusions | on track (the network's best) | retire cone; cloud 5 / shadow 4 / group 4 / stripes 2 / wheel 1; clean loops; then Ames window, point-light walker, Necker cube as trials | 5 (hold) |
| @math.explainers | on track, menu fix | fourier 3 / zeta 3 / fold 2 / sci8 1, derivative off; stake on frame 0; drop the follow-asks; give it back the bfs-dfs-astar maze | 5 (hold) |
| @ascii.terminal.dreams | on track, double down | retire aurora/daisies/planet; code panel phone-readable; 10-20 s tight cuts (that is where the saves are) | 5 (hold) |
| @physics.bounce.lab | needs work | fluid 4 / stopit 2 / balls 1; retire square, pendulum; style-aware captions (fluid lines land on ball videos today) | 5 (hold) |
| @earth.data.live | on track, one winner | flights 4 / quakes 2 / satellites 1; short cuts only; then "N planes over <city>" and the ISS pass | 5 (hold) |
| @rocket.league.lit | on track | asis 4:1 over montage; goal inside 2 s; typed situation line (score/clock), no slogans | 5 → 3 |
| @tiny.code.loops | needs work | type the program in over the first bar, picture lands on the kick; retire lissajous/galaxy/ridges/orbits; short cuts | 5 → 3 |
| @digital.petri.dish | rethink the arc | warm-up off (start from the seed), a true frame-0 line, then food targets and a pruned ending; later the race and the maze | 5 → 2 |
| @ascii.cinema.tty | on track for reach, weak watch | open on a face (Nosferatu), 2 s title with film + year, caption names the subject | 5 → 3 |
| @glitch.archive.exe | needs work | NASA/space + own footage only; name the thing on screen; mosh as a transition, not a bed | 5 → 2 |
| @vintage.media.archive | rethink | fix the opener or fold into ascii.cinema.tty; it carries the originality notice | 5 → 0-2 |
| @psychedelic.station | rethink | stop carousels; fact reels only on non-drug specs; one format, 2/day, as trial reels, for a week | 10 + jobs → 2 |
| @nostalgia.hub.vhs | needs work → rethink | the 90s-things fact reel is the only reliable format: make it the main one (2/day, ≤12 s); tapes 1/day with something wrong in the room by second 1; purge retired rooms from the library | 6 + jobs → 3 |
| @nyc.daily.aesthetic | needs work | meme + walk 2:2; fact stays retired; write each meme line for the clip it needs; Nick's own clips | 5 → 4 |
| @retro.vibes.arcade | rethink | pause; 48 near-still AI clips are not a PS2 feed; move the Kaggle budget to ascii's subject clips | 4 → 0 |
| @algorithm.races | blind | insights scope on IG_TOKEN_2; paths 3 : sorts 2; title on frame 0 | 5 → 3 |
| @8bit.tests | blind, needs work | insights scope on IG_TOKEN_3; count test distractors; cap at 14-26 s; drop flashes/read from the menu | 5 → 3 |
| @fourier.reveal (circle_atlas) | too early | start at 3 circles, stage one = one bar; easy countries 6:1 for three weeks | 2 (hold) |
| @eye.trick.lab (stare_lab) | too early | make it the one eye-tricks page: stare 2 + hue 2 + measure 1 a night, no new accounts until a style wins | 2 → 3 |
| @what.if.town | sound idea, unproven render | "what if" on frame 0; one visible consequence per story; drop "watch till the end"; **girl's-voice narration with the song ducked under it** (below) | 2 (hold) |
| @rubberhose.radio | rethink before it grows | remove Steamboat Willie and Aristocr1940 today; redraw the frames (ink/riso) before volume | 2 (hold) |
| @zoom.into.art | on track, needs work | dive inside 1.5 s, not after a 6 s push-in; fetch colour paintings (Met/AIC/NGA); skin check at crop level | 2 (hold) |
| @moth.ate.my.notes | needs work | the one text page openly about the sound; two-beat reveal; 7-9 s loops; caption = the line | 5 → 2 |
| @grip.tape.thoughts | needs work, clearest identity | every line skate; drop the four "would you rather" cards | 5 → 2 |
| @crying.in.trader.joes | needs work | one voice; move the raunchy half (h046-h070) out | 5 → 2 |
| @situationship.notes | rethink | merge into trader.joes or make it the clean "mixed signals" page; d032/d050 out today | 5 → pause |
| @dining.hall.philosopher | rethink the bank, keep the handle | rewrite toward deadpan dorm observation; the handle rhymes with EDUCATION | 5 → 2 |

## The plan, in order

### This week (config, captions, one small PR each)
1. **Un-trial the band accounts.** `accounts.yaml` `trial_reels: false` on close_quarters_ig and dylancantor23_ig.
   Measure 7 days against the previous 7: likes/reach, sends/reach, follower delta (start logging it).
2. **Audio pages.** Run `scripts/ig_audio_search.py --account close_quarters_ig --query "close quarters"` from a
   workflow. If the 15 tracks are in the catalogue, add `ig_audio_id` per song in `studio/songs/<slug>/song.json` and
   have topup (`src/cli.py` ~L1772) fill `PublishRequest.audio_id` with `video_volume=0` on Facebook-login accounts.
   If not yet, confirm delivery with the distributor and, meanwhile, name one band-owned original sound per song.
3. **Give the ten blind accounts their numbers.** Add `instagram_business_manage_insights` to the Unified-login
   configuration (`cqconnect/worker.js` config id) and re-connect IG_TOKEN_2..11 through connect.closequarters.vip;
   Adrianne grants Insights on her two Pages and tokens.yml re-runs. Code: print scopes in `scripts/ig_check.py`; an
   alarm in the metrics step when every post of an account comes back empty.
4. **Cadence to match the plan.** `posting.posts_per_day` per the table above (psy 2, nostalgia 3, dylancantor23 3,
   loose.change 1, notes pages 2, new pages 2); carousel job off; fact-reel job nostalgia + non-drug psy specs only;
   no two posts within 60 min on one account across jobs; niche windows start at 12:00 NY (10-11 is the weakest hour,
   17 and 20-23 the best).
5. **Rights.** Add `steamboat.?willie|aristocr` to the toons skip list (or `footage.TRADEMARK`), fix the 1940 year,
   drop the four follow-asks in `mathviz` (fourier, zeta, fold, paths), remove "watch till the end" from
   lowpoly's captions, remove the listed risk lines from the notes banks (d032, d050, the "would you rather" cards,
   the "not a cry for help" caption).
6. **Menus by hand** (`nightly.yaml` retire lists and renderer weights): illusions cone off; math sci8 down, derivative
   off; ascii aurora/daisies/planet off; physics square/pendulum off, fluid 4 slots; earth flights 4; rocket asis 4:1;
   tinycode thin programs off; petri seeds/rain off and `CQ_WARMUP=0`; psy strobe off; retro paused.
7. **Learner hygiene.** `MIX_FOR` drop cq_band and rocket_league (own comment pollutes `talk`); `knob:cut` default
   `short` for VISUAL styles; freeze cosmetic knobs (theme, font, grid, glow, palette) for two weeks so posts go to
   subject x cut x hook; only record a knob the renderer read (`knobs.py`), which also fixes illusions' phantom
   `shape` and pixel_tests' retired `flashes`/`read`.
8. **Bio link.** Check the `cq-listen` worker's `/stats`; tracked path per account; log `followers_count` daily from
   business_discovery into the dashboard.

### Next two weeks (renderer work)
9. **Render by style quota** in `src/cli.py`: cq_band takes cutout 2, band 1 a day from the libraries, not a boost.
10. **Credits into the safe area** (y ≈ 1470) in the nine renderers; add a small credit to psy and liminal.
11. **Frame-0 rule everywhere**: the stake or the subject readable at frame 0 inside y 250-1500, the picture already
    moving. Specific: math stake lines; cinema/vintage exclude the abstract films from the opener and first bar, one or
    two films per video, ≥2 s a shot; tinycode types the program in; petri starts from the seed with a true line;
    zoom dives inside 1.5 s; alife/illusion/reveal loop with the last 9 frames fading into frame 0.
12. **Style-aware captions**: `captions/<style>.txt` lookup in `_creative_bank_path` (physics_sims first).
13. **Short variants** for the WHOLE styles (math/race 24-beat scenes) and the `short` cut offered to cutout/lofi.
14. **Two-beat text cards** on the notes pages (`reveal` knob), 7-9 s, loop-clean, caption = the line, `kind` knob
    (song / friend / self) so the writing can be learned; consolidate to two or three voices.
15. **what.if.town narration** (below) and one visible consequence per story.

### Later (new formats, each its own PR, posted as trial reels first)
16. Illusions: Ames window, point-light walker, Necker cube. Petri: food targets, the two-colony race, the maze.
    Earth: "N planes over <city>", the ISS pass. Rocket: situation line, 30 more clips. Nostalgia: fact reel as main
    format. Glitch/vintage/cinema: fold vintage into cinema, glitch becomes the NASA + own-footage page.
17. **Learner v2**: per-account 48 h z-score of log views plus a shrunk keep rate as the single score; hour and cut
    effects fitted network-wide and subtracted; Gaussian Thompson on the subject knob only; posterior retirement
    after 4 posts; EXPLORE 0.1; LEARNED.md reported as "top 3 per account".
18. **YouTube Shorts** (below).

## YouTube Shorts

Three routes. Buffer (today's `nickdotname_yt` path) is 3 channels per login and ~3,000 requests a month: it does not
scale to 30 channels. A **posting-API vendor** that has already passed Google's audit (Zernio/Late, Upload-Post,
Blotato, Ayrshare; roughly $25-100 a month for the network at 2026 prices) is the fast path: one OAuth per channel on
their page, one REST call per video, posting within days. The **direct YouTube Data API** is free and ours, but public
uploads from an unverified Cloud project are locked to private until Google's audit clears, and the default quota
(1,600 units per upload against 10,000 a day in the cached docs; later reports say uploads got their own ~100/day
bucket) needs the extension form. Plan: submit Google's "API Services Audit and Quota Extension" form now; build
`src/publishers/youtube.py` (or a vendor publisher) behind the existing `Publisher` seam (`PublishRequest` already has
`title` and `notify_subscribers`); pilot five channels as Brand Accounts under one Google login: rotation.illusions,
math.explainers, ascii.terminal.dreams, physics.bounce.lab, close__quarters; 2 a day; phone-verify each channel to lift
the 10-uploads-a-day cap on unverified channels; title = hook line, "<song> — Close Quarters" in the description.
Our files carry no watermark, so neither platform's other-app-logo rule bites.

## what.if.town narration (voice only here; the notes pages stay silent text over the song)

`studio/voice.py`: Kokoro-82M (Apache 2.0, CPU, no key; one fixed girl's voice so the page is recognisable) reads
each story chunk; the voice sets the beat the caption chunks land on; under the speech the song is ducked with an
ffmpeg sidechain compressor and the vocal stem is muted (the stems exist), the full mix returns for the last shots;
the AI-voiceover disclosure goes in the caption as Meta's labelling rule asks. Knob `voice` on/off so the learner
measures it. Kokoro needs Python < 3.13 (the studio job runs 3.11) and a cached model download (huggingface.co is not
reachable from cloud sessions, so test it in Actions).

## Experiments the learner can measure
- Trial vs normal on the band account (7 days each); 8/day vs 3/day (daily total views should hold, per-post
  sends/reach should rise).
- `short` vs `tight` on cutout, fluid, earth, tinycode (`knob:cut`).
- Resolve line vs current line on math (10 posts each; skip rate and completion).
- Typed-in opener vs current on tinycode; warm-up off vs on for petri; opener face vs abstract on cinema.
- Song-line cards vs other cards on the notes pages (sends per reach), once their numbers flow.

## Risks to watch weekly
Account Status on vintage, glitch, cinema, toon, zoom (originality); psychedelic.station recommendation eligibility
(drug content); the 30-day originality clock on the.loose.change (clean since 11-24); identical first-comment text
across 20 campaigns within minutes (vary it); token regeneration for the ten blind accounts (secrets only, never chat);
`SECRETS_PAT` expiry as the single untracked point of failure.
