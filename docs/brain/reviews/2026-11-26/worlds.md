# Cluster `worlds`: retro.vibes.arcade, rocket.league.lit, nyc.daily.aesthetic, what.if.town, rubberhose.radio, zoom.into.art

Reviewed 2026-11-26 from `cqdash/data.json` (generated 20:51Z), `campaigns/*/posts.json`, `studio/weights.json`, `studio/LEARNED.md`,
the renderers, and contact sheets rendered here from the real libraries (release assets pulled without `gh`):
`/tmp/claude-0/-home-user-ugc-factory/bd16ba37-fa04-5fa1-8c52-0897619fc36c/scratchpad/worlds/sheets/*.png`
(retro x2, rocket x2, toon x2, zoom x2, nyc x4). what.if.town could not be rendered here (no `bpy`) and the published videos
sit on a host this session cannot reach, so that account is judged from `studio/lowpoly_video.py` + `studio/lowpoly/scene.py`.

Nothing in the repo was changed. The wrapper used for the sheets is
`/tmp/claude-0/-home-user-ugc-factory/bd16ba37-fa04-5fa1-8c52-0897619fc36c/scratchpad/worlds/sheet.py`
(it only patches each library's `pull()` to use what is already cached; `CQ_KNOBS` works as usual).

## What Instagram's own guidance says right now (applies to all six)

- Ranking signals Mosseri named (Jan 2025): **watch time** (relative and absolute), **likes per reach**, **sends per reach**;
  sends matter most for reaching non-followers ([Buffer summary](https://buffer.com/resources//instagram-algorithms/),
  [Social Media Today](https://www.socialmediatoday.com/news/instagram-shares-algorithm-2025/738034/),
  [Uppbeat on sends](https://uppbeat.io/blog/creator-news/whats-working-on-instagram-right-now-carousels-and-sends-says-adam-mosseri)).
  The learner's mix (completion 30 / sends 30 / views 15 / saves 10 / not-skipped 15) already matches this.
- **Originality, April 30 2026 update**: accounts that *mostly* post unoriginal photos/carousels/reels are taken out of
  recommendations (Explore, Reels tab, suggested); followers still see them. "Original" = made by you, or third-party
  material **materially edited** so the additions "meaningfully enhance" it; a caption, a crop, a filter, speed change or
  a watermark does not count. Status is rolling, visible in Account Status, recoverable 30 days after the last unoriginal post
  ([TechCrunch](https://techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/),
  [Instagram original content guidelines](https://creators.instagram.com/original-content-guidelines/),
  [Instagram: recommendations and originality](https://creators.instagram.com/recommendations-and-originality),
  [PetaPixel](https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/)). vintage.media.archive already
  got this notice (traps.md); the toons library is the same exposure.
- **AI labels, Aug 2026**: the reach limit is for *profiles that present an AI-generated person* without the
  "AI-generated profile" label; "creators who use AI tools as part of their creative process do not need to add the label"
  ([Instagram creators blog](https://creators.instagram.com/blog/ai-generated-profile-label),
  [TechCrunch](https://techcrunch.com/2026/08/31/instagram-puts-new-limits-on-undisclosed-ai-profiles/)). The per-post
  "AI info" tag is a separate system driven by C2PA/IPTC markers and classifiers ([Meta 2024](https://about.fb.com/news/2024/02/labeling-ai-generated-images-on-facebook-instagram-and-threads/));
  nobody has published a measured reach penalty for it. So the retro account's problem is not an AI penalty (see below).
- **Trial reels** go to non-followers first, don't show on the grid unless promoted; toggle at share time
  ([Meta newsroom](https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers-first/),
  [Instagram creators](https://creators.instagram.com/blog/instagram-trial-reels)). The pipeline posts through the Graph API,
  and `trial=False` on every post here; worth checking whether the API exposes the toggle, because every new-account
  experiment below would be cheaper as a trial.
- **Hook**: Mosseri, March 2025: "the first three seconds of a reel are super important... have text on your video"
  ([Inman](https://www.inman.com/2025/03/07/head-of-instagram-reveals-secrets-to-social-media-success/)).
- **Cadence**: no official number; Instagram's FAQ ties growth to posting reels regularly, third parties converge on 3-5
  reels a week for a new account and warn multi-daily from a brand-new account reads as spam
  ([Buffer, 2M posts](https://buffer.com/resources/how-often-to-post-on-instagram/), [Later](https://later.com/blog/instagram-reels-algorithm/),
  [Instagram FAQ](https://creators.instagram.com:443/faq)). The repo's own data agrees: back-to-back posts did ~20% worse
  (log 2026-11-25), subject repeats 61 vs 119 views, and in this cluster rocket's one 7-post day produced its four worst posts.

---

## 1. @retro.vibes.arcade (retro_arcade, `studio/retro_video.py`, Kaggle Wan 2.1 clips)

**Verdict: rethink.** The biggest lever is the footage itself: 48 near-still AI renders of empty places are not a PS2
nostalgia feed, and no knob on top of them will fix that. Stop spending Kaggle hours on this library.

### What the numbers say
- n=14, median 30 views, mean 44, max 112, median watch 3.4 s, **skip rate 71-89% on 13 of 14 posts**, 0 saves, 0 shares.
  Every post shows exactly 1 comment: that is our own first comment, so real engagement is zero.
- The two 100+ posts (space 112, racing+memory 111) were posted at 19:00 and 13:00 NY; the 9 posts at 09:00/12:00/16:00/20:00
  all sit at 7-62. With n=1 per theme the "space wins" reading is noise.
- `studio/weights.json`: every option 0.95-1.04, every song/section/theme has 1-2 posts. The learner cannot learn here:
  13 themes x 4 screens x 2 frames x 4 trans x 2 paces x 3 hooks over 2 posts a day. The retro `trans` knob was only
  made learnable on 11-24, so it has 4 posts of data.
- Library (`studio/retro/index.json`): 50 clips, 48 live, 13 themes with 3-4 clips each, all Wan 2.1 1.3B at 480x832, 3 s.
  Motion score quartiles 0.49 / 1.14 / 2.22; **21 of 48 clips move less than 1.0** (near-stills; the sheet's second
  "place" is a blank aqua wall). `impossible` and `aero`, the two themes written on 11-24 as the liminal/dreamcore hook,
  have **0 clips**; `menu` (dropped from prompts.json because "nobody picks a menu to live in") still has 4 clips that
  `theme=mixed` happily uses, because `lib.pull(())` returns every non-subject theme.
- Watch time 3.4 s on 6-20 s videos with 80% skipping in the first 3 s: the cover and first second are the whole problem.

### Content audit
- Frame 0 (sheet `retro_spot_ps2.png`): a chrome pipe close-up with "which level are you loading first? 1" over it. Nothing
  reads as a game, a level or a place in the first second; "pick one" asks the viewer to choose between four stills.
- The PS2/CRT/VHS screens are convincing (dither, combing, bloom all fine), text sits inside the safe area, the loop fade
  works, the OSD is tasteful. The craft is not the issue.
- The 480x832 upscale to 1080x1920 is soft; with bloom on top the pictures look like AI stills with a filter, which is
  what the Y2K/PS2 audience is primed to reject (the 2024 "AI PS2 filter" trend was mocked as "artificial nostalgia":
  [Sabukaru](https://sabukaru.online/articles/artificial-nostalgia-behind-the-trending-ps2-filter),
  [Know Your Meme](https://knowyourmeme.com/memes/ai-ps2-filter)).
- Captions: good, on-niche lines ("the demo disc had one more level"), 7 hashtags, song credit, link-in-bio CTA, first
  comment credits the song. "found this level on a memory card from 2003. sound on." is a small untruth (the level is
  not from 2003) and "sound on" is a soft ask; the rest are fine.
- Cadence: 2/day since 11-25 (was 4). Fine for the account's age. No house-rule breaches.

### Research: what real PS2/Y2K pages do
- The pages that work are real-game-footage pages: @play2.nostalgia (53K, Brazilian PS2 nostalgia, real screenshots and
  footage), @meu_ps2_nostalgia; the PS1 aesthetic community (Haunted PS1, "PS1 aesthetics") is built on **indie games made
  in the style**, not AI ([Instagram @play2.nostalgia](https://www.instagram.com/play2.nostalgia/),
  [Haunted PS1](https://en.wikipedia.org/wiki/Haunted_PS1)). Their posts are recognisable games, menus, memory-card
  screens and boot sounds: a shared memory, which a made-up level cannot be.
- Legal paths that keep the look without ripping games:
  1. **Our own real-time renders** of low-poly scenes in the engine look (vertex jitter, affine texture warp, 15-bit colour,
     fog): `studio/pixelviz/` and `studio/lowpoly/` already render voxel/low-poly worlds in code; Kenney's kits are CC0
     ([Kenney licence](https://kenney.nl/support)). A Godot/Blender-side PS1-style render is ours outright; no model, no label,
     no originality question, and it can be made to *move* (a camera that actually drives through the level) which Wan 1.3B
     cannot.
  2. **Open-source / CC-licensed games recorded by us**: only with a licence that allows it per game; itch.io terms vary and
     "free" is not a licence ([itch.io threads](https://itch.io/post/15882506)). Workable but a per-title legal check each time.
  3. Demoscene productions are copyrighted by their groups; not a path.
- Kaggle is ~30 GPU hours/week on two T4s, sessions capped at 12 h; P100s reportedly retired Sept 2026
  ([gpuperhour](https://gpuperhour.com/blog/free-cloud-gpus-and-credits), [Spheron](https://www.spheron.network/blog/free-gpu-cloud-credits-2026/)).
  FastWan 2.2 at 704x1280 (added 11-26) would sharpen the pictures but not the premise.

### Recommendations
1. **Retire the Wan library as the account's picture; put the Kaggle budget on `subject-*` clips for ascii.terminal.dreams**
   (median 185, 86 saves: the only account whose format turns a Kaggle clip into something clearly ours). Quick:
   `studio/nightly.yaml` retro `per_night: 0`, `campaigns/retro_arcade/config.yaml` `paused: true`; `retro.yml` plan
   weighted to `subjects`. [quick]
2. **Rebuild the account on our own engine-style renders** (large): a `ps1`/`ps2` look on `studio/lowpoly/scene.py` or
   `studio/pixelviz/` (vertex snapping, affine warp, 256x224 render upscaled nearest, fog, a HUD that is ours), with the
   camera *driving* through the level on the bar and a real game-like beat: a lap, a jump, a door opening on the downbeat.
   Keep the retro screens and OSD; they are good. First 20 posts: one world per post, "level 1-20", each opening on motion.
   Measure: skip rate under 60% and any shares in the first 20. [large]
3. If the Wan library stays on for now: `theme=mixed` must exclude `menu` (filter `e['theme'] in THEMES` in
   `retro_video.py` `Video.__init__`), `rejects.json` should list every clip with motion < 0.6 (21 clips), the hook
   `spot` should be off (a question over four stills has 0 sends in 14 posts) and the window should be `short` only
   (under-10s posts scored 0.61 vs 0.47). [quick]
4. Fix the caption "found this level on a memory card from 2003. sound on." (untrue + ask). [quick]

### Risks
- No AI-profile label needed: no person is shown. The "AI info" post tag may appear; not a known reach penalty.
- The real risk is the originality rule in reverse: a feed of generic AI stills is exactly what the April 2026 update's
  "low effort" language targets, and 80% skips train the account into a hole from which later formats start.

---

## 2. @rocket.league.lit (rocket_league, `studio/rocket_video.py`, our own clips)

**Verdict: on track, needs work.** Biggest lever: post the clip straight (asis), fewer per day, with the goal landing
inside the first 2 s; every share the account has came from that.

### What the numbers say
- n=19, median 141, mean 149, max 380, median watch 5.9 s, 19 shares, 11 saves (the best share rate in the cluster).
- **asis vs montage** (n=10 vs 9): median views 154 vs 136, watch 6.6 vs 3.8 s, skip 37% vs 69%, shares **19 vs 0**,
  saves 7 vs 4. Montage is a different (worse) product: a flash cut every bar on 17 clips the viewer has not learned
  to care about. The learner already weights asis 1.06 / montage 0.93, slowmo 1.07, short cut 1.10.
- Both 300+ posts and both shared posts were asis with "replay worthy"/"nobody saw this coming": one clip, one moment,
  caption that promises a payoff without asking for anything.
- **Cadence confound**: the four worst posts (11, 12, 15, 15 views) all went out on 11-25, the one day the account posted 7
  (its config says 5). Nothing else about them is unusual. Hour 17:00 NY is best (median 246, n=2), 08:00/11:00 worst.
- Library: 17 clips (`studio/rocket/index.json`), 5 posts a night, so each clip comes back about every 3 nights; the
  caption "ceiling shot, but make it Hair of the Dog" was posted twice (213 then 15 views). The 6 "cancelled" rows are the
  11-26 double-booking, not a content problem.
- Learner: `MIX_FOR['rocket_league'] = TALK` counts comments per reach, but every post's 1 comment is our own first
  comment, so that 15% of the score is constant noise. Format is the only knob with a real signal; `frame` and `ramp`
  are confounded with it.

### Content audit
- Sheet `rocket_asis_blur.png`: the 16:9 clip sits in the middle third with a blurred copy above and below; the goal
  explosion is small, the "SOUND ON" box is in the safe area, the HUD shows "NICKDOTNAME SCORED!" (fine: it is Nick's
  own handle) and other players' gamertags/clan tags (minor; they are public in-game names).
- Sheet `rocket_montage_crop.png`: `crop` fills the frame but loses the ball; the first frame is a scoreboard + hook, the
  goal flash reads well. "rocket league players will get it" is the weakest line (10 views, 3.4 s).
- The hook line now comes from statements only (`studio/hook.py` 'rocket'); the bait line "tag your duo" that posted on
  11-24 (134 views, 3.7 s, 0 shares) is gone from the bank. Good.
- Credit pill at y 1450-1496: inside the safe area. Song credit and first comment fine. Game audio muted, song only: right
  call (Psyonix reserves all IP rights in the EULA and has no clip policy; gameplay clips with our own music are the
  community norm: [Epic/Psyonix EULA via search](https://legal.epicgames.com/nl/psyonix/eula/rocket-league-sideswipe),
  [YouTube game content policy](https://support.google.com/youtube/answer/138161?hl=en-GB)).

### Research: what the RL clips community watches
- Psyonix's own community-clips brief: "epic saves, elite team plays, demolition highlights, and hilarious whiffs and
  fails" ([Psyonix community clips](https://devtrackers.gg/rocket-league/p/88659a08-community-clips)); the official
  clips site sorts by goals / saves / aerials / flip resets ([rocket-league.com/clips](https://rocket-league.com/clips));
  the esports subreddit's top monthly post was an open-net miss ([r/RocketLeagueEsports roundup](https://reddit.sudovanilla.org/r/RocketLeagueEsports)).
  Flip resets are the ceiling of "clip culture" since 2019 ([Dignitas](https://dignitas.gg/articles/flip-reset-shots-and-how-important-they-are-a-guide-with-yukeo)).
- Clip-to-Reels tooling (Eklipse) cuts "flip-reset plays, zero-second equalizers, whiff fails" into 9:16 with the
  moment first ([Eklipse](https://eklipse.gg/use-case/rocket-league-highlights/)). Fan pages like @itsrlclips are small
  (3.4K) ([Instagram](https://www.instagram.com/itsrlclips/)): there is no giant incumbent, the niche is open.
- What makes an RL clip sendable without bait: the *situation* stated as a fact before the payoff: the score and clock
  ("1-2, 0:04 left"), the rank, "double touch", "zero second", "own goal", "whiff". The viewer sends it to the duo
  because the caption names the thing they argue about.

### Recommendations
1. **asis 4:1 over montage and 3 posts a day, none before 11:00 NY** (`nightly.yaml` rocket `per_night: 3`;
   `rocket_video.py` `K.pick('format', ..., weights=[4, 1])`; `config.yaml` `posts_per_day: 3`, `start_hour: 11`). [quick]
2. **Move the moment to 1.5-2.5 s**: in `asis`, `start = m - dur*0.55` puts the goal past the middle of an 8-14 s clip,
   so the first 3 s are build-up. Make `m - start` land at ~2 s (one bar of run-in), then let the clip play out to the
   replay. The two best posts are the ones where the hit came early. [medium]
3. **Vertical crop that follows the ball**: `frame=crop` fills the frame but crops the centre; a ball-tracker (brightest
   moving blob, or the HUD-free centre of motion from `rocket_lib.moments`) would keep the play in frame. Until then
   `blur` is the safer default (weight it 3:1). [medium]
4. **Situation overlay instead of a slogan** (new `hook` kind `situ`): a one-line fact read off the clip and typed by us
   when the clip is added (`rocket_lib.py add` can take `--line "0:04 left, down one"`), held for the whole clip in the
   top safe band; statements only. Learner compares `situ` vs `none` vs the current lines. [medium]
5. **Library is the ceiling**: 17 clips cannot feed 3/day for long without repeats, and repeats did 61 vs 119 network-wide.
   Ask Dylan and Nick for 30 more clips with the whiffs/own goals/saves kept (the fails are what the community sends);
   the `rocket-inbox` workflow already exists (footage.md). [quick for us, work for them]
6. Drop `talk` from `MIX_FOR['rocket_league']` or subtract the first comment from the comment count in
   `learn.numbers()`. [quick]

### Risks
- Nick's gamertag and other players' names are on screen; public in-game names, no house-rule issue, but keep the
  Rocket League footage off any account that shows the band (it does not).
- Clip repeats across 17 clips are the main originality exposure: Instagram's near-duplicate matching is on our own
  earlier posts too.

---

## 3. @nyc.daily.aesthetic (nyc_daily, `studio/nyc_video.py`, Pexels + Nick's clips)

**Verdict: needs work.** Biggest lever: retire `fact` (already done 11-25) and make `meme` the account, with the line
written for the picture rather than dropped on a random clip.

### What the numbers say
- n=18 with numbers: **meme median 112 (n=11, 93-178 on 9 of 11), fact median 16 (n=7, 5-44)**; watch 3.7 vs 2.6 s, skip 53%
  vs 79%. `walk` and `thennow` (built 11-24) have **no published post yet** in the dashboard; every post so far is meme
  or fact. The learner's kind weights (meme 1.06, fact 0.94) are the first real signal in the cluster.
- Saves 2, shares 1 (both on a 16-view fact post): memes get watched but not sent. 2.6% likes/views.
- Hours 09:00 and 15:00 NY best (median 111/112), 10:00 and 18:00-20:00 worst; 6 posts a day on 11-24 and 11-25.
- Two meme posts at 7 and 39 views were lines 10/"the city, on the beat" and a 19:00 post; nothing structural.

### Content audit
- Sheet `nyc_meme.png`: the white bar + Poppins text at the top is the classic meme-page look and reads at phone size; the
  line "when it's sunny and the whole city is in the same park" plays over the Chrysler Building, then a bridge, then the
  East River. **The picture never pays off the line.** The 30 lines in `MEMES` are generic NYC jokes, each cut goes to
  any clip of the mood; so the joke has no second beat. Real meme pages match the text to one shot (the empty train car,
  the scaffolding, the dollar slice).
- Sheet `nyc_walk.png`: strong. Hero night opener, "new york after dark" in Fraunces, place name + coordinates low in the
  safe area, loop to the opener. This is the account's best-looking format and nobody has seen it yet.
- Sheet `nyc_fact.png`: "700+ LANGUAGES SPOKEN IN NEW YORK" readable from frame 0, then nothing changes for 15 s.
  Retiring it was right.
- Sheet `nyc_thennow.png`: the 1899 film is mud (dark, blurred, a dark band), the "now" half is a static cable shot; it
  reads as two unrelated clips. With two pairs (bridge 11 / river 8) it cannot vary. Not ready.
- Captions: 58 lines, 5 hashtags, no asks, song credit + first comment fine. `funnel.link` is empty and every caption says
  "link in bio": make sure the bio has the album link (not checkable from here).
- Library: 73 labelled clips, 13 skipped, hero>=2 on 29; 0 of Nick's own clips yet (`studio/footage/inbox/nyc.txt` is empty).
  Pexels licence allows this use; still, Pexels city stock is on hundreds of pages, so the format must add something.

### Research: NYC pages
- The pages that define the niche are hyper-local and *specific*: Nolita Dirtbag (reality-TV-style captions on specific
  NYC types), Subway Creatures (real subway footage), Overheard New York, Starter Packs of NYC
  ([Vice](https://www.vice.com/en/article/hyper-local-instagram-meme-accounts/), [New York Dearest](https://newyorkdearest.com/best-nyc-instagram-accounts/),
  [Influencer Marketing Hub](https://influencermarketinghub.com/instagram-meme-accounts/)). Big generic city pages
  (@newyorkcity 1.5M) are photo aggregators ([HypeAuditor](https://hypeauditor.com/instagram/newyorkcity/)): exactly
  what the April 2026 originality rule now demotes.
- What travels: a line that names a very specific New York experience over footage of *that* thing; POV walks with
  one line held at the top; "then/now" works when both halves are sharp.

### Recommendations
1. **Keep fact retired; run meme and walk, 2:2, 4 a day at 09/12/15/19 NY** (`nightly.yaml` nyc kind weights via `retire`
   stays; `nyc_video.py` `K.pick('kind', ..., weights=[5, 5, 0, 0])` until thennow has sharper pairs; `config.yaml`
   `posts_per_day: 4`). The walk kind has zero posts: that is the first thing to learn. [quick]
2. **Tag each meme line with the clip label it needs** (medium): extend `MEMES` to `(line, wants)` with `wants` a
   places.json label or mood ("subway", "scaffolding", "bodega", "rain", "crowd"), and have `plan()` open on a clip with
   that label (fall back to mood). Nine of the 30 lines already name a thing in places.json's vocabulary. [medium]
3. **Nick's own clips are the originality moat**: the inbox workflow is built; 20 clips of subway platforms, scaffolding,
   bodegas, the walk home would let the memes land and make the account "own footage" under the new rule. [quick for
   us; ask Nick]
4. thennow: keep off until the old film is cleaned (level + sharpen + crop the dark band, as `vintage_video` does with
   its survey) and there are 5+ pairs. [medium]
5. Posting hours: avoid 18-20 NY where this account's posts die (n small; let the learner's `hour posted` carry it). [quick]

### Risks
- None of the house rules are broken (no band footage, no bait, Pexels licence). The originality rule is the risk:
  stock city clips with a caption bar is the definition of "lightly edited third-party content" unless the caption bar and
  cut make it ours. Own clips fix that outright.

---

## 4. @what.if.town (lowpoly_stories, `studio/lowpoly_video.py` + `studio/lowpoly/scene.py`, Blender)

**Verdict: on track as an idea, unproven as a render.** 1 post, no numbers. Biggest lever: make the picture pay off the
words (the "what if" lands on a visible consequence) and open on the question in frame 0.

### What the code produces
- 20 stories in `stories.txt`, 3-5 shots each; captions in Montserrat ExtraBold 118 px with a 12 px stroke at 58% height,
  one chunk per beat (or half beat on slow songs), each word popping in; a credit at the bottom of the safe area; knobs
  story / caption (yellow vs white-pink) / pace. Blender Workbench at 720x1280, box people from CC0 Kenney kits, effects
  grow / shrink / float / shake / spin / blast / many / night / old; camera per shot type.
- Strengths: the words keep time with the song (this is the format's hook: the premise unfolds on the beat), the stories
  are ours and funny in the right register ("you now owe the bank a kidney"), no asks, no real people, kits CC0
  ([Kenney](https://kenney.nl/support)). The house rules are met.
- Weaknesses to expect from the code: (a) frame 0 is a walk shot with no words yet: the first chunk appears on the first
  beat (`beats = [0] + beats` puts chunk 0 at frame 0 only if the story's first shot starts there; it does, so "what if"
  should be on frame 0: check one published cover). (b) Workbench flat shading + 720p upscaled + `polish` will look like a
  2012 mobile game; the low-poly pages that work now lean into "cursed/bad 3D" on purpose
  ([hooked.so low-poly trend](https://hooked.so/tools/low-poly-video-generator), [KYM low-poly gimmick accounts](https://knowyourmeme.com/memes/low-poly-gimmick-accounts)):
  either commit to that (hard outlines, chunky, deliberately stiff walk) or it reads as unfinished. (c) The consequence is
  mostly *told* ("the neighbors moved out") while the picture only has grow/shrink/float/blast to show it: 3 of 20 stories
  have a shot whose effect is the joke. (d) "watch till the end" is in the caption bank: a soft ask, drop it.
- The "what if" + 3D scenario format is a recognised Reels format ([Anijam ideas list](https://www.anijam.ai/blog/ai-animation-ideas/)),
  and the repo's own note says the reference used a pop-star figure (not allowed here). The strongest versions put **one
  live number** on screen (backlog: "every number shown must be computed").

### First week and first 20 posts
- 2/day is right for a brand-new account; keep it for 7-10 days, then 3. All 20 stories once, best songs only (the
  stories want a tempo under ~110 bpm so a chunk per beat is readable: check `spb` and prefer `half` pace only on slow songs).
- First 20: open every one on the "what if" card already on screen; vary the opening shot type so the grid is not 20
  identical streets; put the three "shown not told" stories (gravity, giant, double) first.

### Recommendations
1. Verify the cover (frame 0) has the words on it; if not, hold chunk 0 from frame 0. [quick]
2. Remove "watch till the end" from `captions.txt`. [quick]
3. One visible consequence per story: add effects that *are* the punchline (rain of plates for "broke a plate", the
   town shrinking to a shoe for "gym", a clock for "snooze") rather than text alone; `scene.py` effects are cheap transforms,
   two or three new ones cover most stories. [medium]
4. Pick a look and commit: either "cursed low-poly" (Workbench outline on, 2x pixel size, 15 fps hold) or a clean toy-town
   (Eevee is not available on the runner; Workbench with cavity + stronger shadows is the ceiling). [medium]
5. Add a `number` kind later (one computed figure per shot) to reach the "what if" audience that the backlog describes. [large]

### Risks
- None legal (own stories, CC0 kits). Watch the first metrics for watch time under 3 s, which would mean the words are
  too fast; `pace=beat` on a fast song puts a chunk every 0.4 s.

---

## 5. @rubberhose.radio (toon_edits, `studio/toon_video.py`, pre-1931 cartoons)

**Verdict: rethink before it grows.** The format is good; the library has two films that must come out today and the
whole idea sits on the same originality tripwire that paused vintage.media.archive.

### Rights, film by film (`studio/footage/index.json`, theme `toons`, 22 films)
- US rule: anything published 1930 or earlier is public domain as of 2026-01-01 ([Duke, Public Domain Day 2026](https://web.law.duke.edu/cspd/publicdomainday/2026/)).
  Copyright is fine for 20 of 22. Trademark and platform rights-matching are the problems.
- **Steamboat Willie (1928): remove.** The 1928 film is PD, but Mickey is a live Disney trademark, Disney has not
  disclaimed enforcement (the Morgan & Morgan v. Disney suit, Sept 2025, is about exactly this), and YouTube's Content ID
  kept claiming the footage for creators in 2024 ([Duke CSPD](https://web.law.duke.edu/cspd/mickey/),
  [Gizmodo on the 2025 suit](https://gizmodo.com/disney-steamboat-willie-lawsuit-public-domain-mickey-mouse-2000663467),
  [Tubefilter on Content ID claims](https://www.tubefilter.com/2024/01/04/disney-copyright-claim-steamboat-willie/)).
  `footage.TRADEMARK` matches `mickey|disney|...` but the title is "Steamboat Willie", so it **passes `fits()`** and the
  renderer used it in both test sheets (`toon_hook_cream_tv.png` plan shows it three times). The house rule "no
  copyrighted film/TV edits" is meant to keep exactly this off a niche account.
- **"Aristocrats of Fashion": remove.** Indexed as 1930, but the archive.org id is `Aristocr1940` and Commons/Prelinger
  list it as a Reed Productions rayon fashion film, ca. late 1930s-early 1940s, live action
  ([Commons file](https://commons.wikipedia.com/wiki/File:0396_Aristocrats_of_Fashion_10_22_40_00.webm),
  [A/V Geeks](https://avgeeks.com/?p=40511)). Not a cartoon, and not provably PD by date.
- **Fiddlesticks (1930)**: Flip the Frog in his Mickey-lookalike design; PD since 2026 (the one Flip short whose copyright was
  renewed) but already in the renderer's `SKIP` for the look-alike ([Wikipedia](https://en.wikipedia.org/wiki/Flip_the_Frog),
  [Cartoon Brew](https://www.cartoonbrew.com/classic/public-domain-betty-boop-flip-the-frog-rover-257808.html)). Keep skipped.
  Puddle Pranks / Little Orphan Willie (1930, unrenewed): fine.
- **Fleischer 1930 Talkartoons** (Hot Dog, Barnacle Bill, Swing You Sinners, Accordion Joe): PD by date
  ([Wikipedia, Swing You Sinners](https://en.wikipedia.org/wiki/Swing_You_Sinners!)). Fleischer Studios disputes that
  *Betty Boop* is PD and polices the trademark; Barnacle Bill (Aug 1930) has the proto-Betty "Nancy Lee" in it
  ([Fleischer Studios statement](https://www.fleischerstudios.com/publicdomain.html), [Plagiarism Today](https://www.plagiarismtoday.com/2025/12/09/the-upcoming-war-over-betty-boop/),
  [Slashdot](https://tech.slashdot.org/story/26/01/04/2234236/)). Low risk for Bimbo/Koko scenes; keep Betty-shaped
  frames out (a `SKIP` on Barnacle Bill is the simple answer).
- Koko's Earth Control (1928, National Film Registry, PD: [Commons](https://commons.wikipedia.com/wiki/File:Dave_Fleischer_-_Inkwell_Imps,_The_-_Koko%27s_Earth_Control_(1928).webm)),
  Gertie (1914), McCay's Mosquito (1912), Bobby Bumps (1917/18), Col. Heeza Liar (1923), Dinky Doodle (1925), Prinzen
  Achmed (1926, Reiniger; US PD by date), Aesop's Fables (1929), Toby the Pup (1930), Finding His Voice (1929): all fine.
- Platform matching is the bigger exposure: these are the most-uploaded cartoons on the internet. vintage.media.archive got
  the originality notice with a tint and a gate; `toon_video` adds a wash, an edge trim, a zoom punch and a TV frame, which
  is the same class of edit. The fix that worked there (every frame redrawn as ink line art) is the model.

### Content audit (sheets `toon_words_pop_fit.png`, `toon_hook_cream_tv.png`)
- `fit` frame: 4:3 picture in the middle 930 px with a blurred copy behind: a third of the screen is blur. The `tv` frame
  (cream cabinet) looks the most deliberate and reads as a format. `pop` wash (a colour per cut) is the right instinct: it
  is what makes it an *edit* rather than a print.
- Sung words (Anton 150 px, one word per sung word, colour per word) are big and legible; the first word appears when the
  vocal does, so **frame 0 can be an abstract lightning frame with no text** (`words` has nothing to show until the first
  sung word; `hook` holds the line from frame 0). The film credit at 40 px over cream is faint at phone size.
- Hooks bank: fine, statements only. Captions: "they drew every frame of this by hand" is true; "public domain and still
  going hard" is fine; no asks. 5 hashtags, good.
- Cadence 2/day, right for week one.

### Research
- The 1930s "rubber hose" look is a live aesthetic (Cuphead, TikTok's rubber-hose tags, AI "rubber hose" portrait prompts);
  the pages are mostly artists drawing in the style, not edits of the originals
  ([TikTok rubber hose tag](https://www.tiktok.com/discover/rubber-hose?lang=en), [Wikipedia](https://en.wikipedia.org/wiki/Rubber_hose_animation)).
  Phonk/brainrot edits over old cartoons exist as a CapCut template genre ([Tubefilter on phonk edits](https://www.tubefilter.com/2026/02/24/gen-alpha-brainrot-shorts-phonk-music-brazil/)).
  The sync of a 1930 walk cycle to a 2026 drum hit is the thing people send; that is what `stutter` and `punch` do.

### Recommendations
1. **Today**: add `steamboat|aristocr` to `toon_video.SKIP` (or `footage.TRADEMARK` for Steamboat Willie; the index
   title has no "Mickey" in it) and `barnacle` for the proto-Betty frames. Re-check the two posts already out; if either
   used Steamboat Willie, delete it. [quick]
2. **Material transformation before volume**: redraw frames (ink line art as vintage does, or a two-tone riso/screenprint
   with the pop colour as the second ink, halftone dots on the greys) so no frame is the original print. Keep `tv` + `pop`
   + sung words as the house look. Then first 20 posts: one film per post, `words` on singing sections and `hook` on
   instrumentals, frame 0 always with text (hold the first word, or the hook, from frame 0). [medium]
3. First week at 2/day is right; go to 3 only after the originality notice risk is handled. [quick]
4. Drop the blurred-fill `fit` frame in favour of `tv` or `full`-with-trim; raise the film credit to 48 px with a stroke. [quick]

### Risks
- Steamboat Willie on a niche account is both a trademark exposure and a CLAUDE.md breach (copyrighted-character edit).
- Originality notice on the account within weeks if frames stay as-is (precedent: vintage.media.archive, 11-25).

---

## 6. @zoom.into.art (museum_zoom, `studio/zoom_video.py`, Cleveland CC0)

**Verdict: on track, needs work before scaling.** Biggest lever: the dive must happen inside the first 2-3 s, not after a
6-second push-in on a static print; and the library needs colour paintings.

### Sources: clean
- 120 works, all Cleveland Museum of Art Open Access, CC0, 2400-3400 px, museum page recorded
  (`studio/art/index.json`). The release also holds `aic_*.jpg` assets not in the index (159 vs 120): the AIC fetch ran but
  the index was replaced; nothing wrong, just unused. No Met works yet despite the docstring. Rights are the best in the
  cluster: CC0 images are "original" once the camera work and text are ours, and nobody else's upload matches a 20x
  crop of an etching.
- 7 works carry `art.BLOCK` words in their titles ("The Dirty Bride", "Peasants Smoking in an Inn", "Prisoners on a
  Projecting Platform", "The Sacrifice of Isaac", "Fight Between a Tiger and a Buffalo", "New Yoshiwara", "Rural
  Tenderness"); `art.pull()` filters them at render time, so they do not post, but `zoom_video.SKIP` and the recipes `menu`
  still list them. Harmless, but the block regex is over-broad ("tender", "smok", "fight") and under-broad for what
  matters on Reels (a 20x zoom can land on a figure the title does not warn about: the face detector + "brushwork" picker
  has no nudity check at the detail level).

### Content audit (sheets `zoom_gallery_ring.png`, `zoom_blur_age.png`)
- Frames 0-170 (the first **5.9 s of a 15 s** clip): the whole print small on a grey wall with a slow push; the ring appears
  at 5.3 s; the dive at 5.9 s (`drop = first bar after 0.3 * n`). That is three "first three seconds" of nothing moving.
  The research on art-detail accounts is unambiguous: the cut to the detail *is* the hook.
- The hook lines are true and good ("keep your eye on the bottom right corner.", "this picture is 358 years old. look at
  the middle."). Montserrat 58 px in the safe area, fine. The title card (Fraunces 50) over the detail at the end is nice.
- The detail finder picks faces first; on the van Doetechum landscape it chose a patch of hatching (the "busiest brushwork"
  fallback), which is not a reveal. On a monochrome print the payoff is weak however good the camera is.
- Library mix: of the 6 cached works, mean saturation 19-27 (monochrome) for 4, 34-52 for the two Hiroshige prints. By
  artist: ~30 colour works (Hiroshige, Hokusai, Kuniyoshi, Bosschaert, the Boucicaut manuscript), ~90 etchings/engravings.
- Captions: "someone painted this by hand" was posted over an engraving (not painted). 5 hashtags, two weak (#details,
  #zoomin). No asks. Cadence 2/day, right.

### Research: the art-detail niche
- Working accounts: @paintingsanalyzed (zooms on hidden details with a one-line explanation), @greatartexplained (300K+),
  @smarthistory (150K+), @_theiconoclass (fast video essays on hidden details)
  ([SCMP, 15 art accounts](https://www.scmp.com/magazines/style/lifestyle/leisure/article/3303799/15-art-accounts-follow-instagram-those-run-artists-or-art-historians-others-sharing-quirky-facts-or),
  [Austin Gallery list](https://www.austingallery.org/blog/instagram-art-collectors-follow), [TMM India](https://www.tmmindia.in/articles/decoding-the-canvas-5-instagram-accounts-bringing-art-history-to-your-feed)).
  Museum TikToks run super-zoom details of Van Gogh, Goya's painted-over face, Vermeer ([Bijutsu Techo on museum TikTok](https://bijutsutecho.com/magazine/series/s41/24185/pictures/7));
  Google Arts & Culture's "zoom into" is the reference for the camera move ([Google Arts & Culture](https://artsandculture.google.com/theme/12-artworks-you-ll-love-to-zoom-in-on/WwLiy-4s3wl8KA)).
  The "reveal" is the dominant painting format online ([Artnet](https://news.artnet.com/art-world/painting-performance-era-art-reveals-2763962)).
- What they share: colour paintings with a *story* in the detail (a tiny figure doing something odd, a face in a crowd, a
  signature, a hidden animal), one true sentence of context, 7-15 s, the cut to the detail in the first 2 s.

### Recommendations
1. **Dive early**: `drop = first bar >= 1.5 s` (not 0.3*n), hold the detail, then a second detail or a pull-out; keep the
   ring only when it precedes the dive by one beat. The whole-picture view is the *end* of the video, not the start. [quick]
2. **Fetch colour paintings**: run `art.py fetch` with Met + AIC + NGA queries for Bruegel, Bosch, Avercamp, Steen, the
   Limbourgs, Canaletto *paintings*, Hiroshige/Hokusai (already), Winslow Homer watercolours, Audubon; require
   `kind: painting|woodblock|watercolor` for the `work` pick until the library is 50%+ colour. [medium]
3. **Detail picker v2**: prefer small faces/figures far from the centre (already), then animals and text (an OCR-free
   proxy: high-contrast small blobs), never plain hatching; add a skin-tone check on the chosen crop so an unlabelled
   nude never becomes the reveal. [medium]
4. Captions: make the opening line true for any work ("drawn by hand" not "painted"); hashtags #arthistory #museum
   #oldmasters #artdetails #printmaking #ukiyoe. [quick]
5. First 20 posts: 20 different works, colour first (the Hiroshige/Hokusai set), `hook=who` (artist + year) on
   famous names and `where` on the rest; 2/day for week one, then 3. Measure: watch time over 6 s and saves (this niche saves). [quick]

### Risks
- Lowest in the cluster. The one thing that can hurt it is a reveal that lands on something a museum tag did not flag.

---

## Cross-cluster notes
- **The learner has no data in this cluster except rocket's format and nyc's kind.** With 2-5 posts a day and 10-300
  options per style, Thompson sampling is a coin toss for months. Where a decision is obvious from n=10 (asis, meme,
  fact), set it by hand in `nightly.yaml` and leave the learner the small knobs.
- **Hour posted and posts-per-day are the strongest confounds in every table above** (rocket's 7-post day, nyc's 18-20
  NY slots, retro's 13:00/19:00 wins). `learn.py` records `hour posted` but the publisher does not choose hours from it;
  that would be a cheap global win.
- **Trial reels**: if the Graph API exposes the trial flag, run every new-format experiment as a trial first.
- Caches left in the gitignored dirs (`studio/retro/cache`, `studio/rocket/cache`, `studio/art/cache`,
  `studio/footage/cache`, ~420 MB): delete if space matters; nothing else was touched.
