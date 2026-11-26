# Cluster `band`: @close__quarters, @dylancantor23, @the.loose.change

Reviewed 2026-11-26 from `cqdash/data.json` (generated 20:51Z), `campaigns/{cq_band,cq_producer,nick_studio,closequarters}/*`,
`studio/weights.json`, `studio/LEARNED.md`, `studio/nightly.yaml`, the renderers, and contact sheets drawn in this session
(`/tmp/claude-0/-home-user-ugc-factory/bd16ba37-fa04-5fa1-8c52-0897619fc36c/scratchpad/band/*.png`). Review only: nothing in the
repo was changed. GitHub Actions logs were not readable from this session, so one finding below (cutout never posting) is a
diagnosis from the data, not from the render log.

## Cross-cutting findings (read these first)

1. **Every automated post on @close__quarters and @dylancantor23 is a trial reel** (`trial_reels: true`, graduation
   `SS_PERFORMANCE`). A trial reel is shown to non-followers only, does not appear on the profile grid, and is auto-shared
   with followers only if its views in the first 72 h are high. With medians of 99 and 46 views nothing graduates, so in
   practice **the band's own followers never see the band's posts, and a visitor sent to @close__quarters by 25 niche
   accounts lands on a grid that holds only the handful of hand-posted, non-trial reels.** The one non-trial post on
   @close__quarters (2026-11-22, "headphones on. we mean it") is the account's best by a wide margin: 631 views, reach 275,
   18 likes, 14 shares, 5 comments. The 53 trial posts have a 0.7–0.9 % like rate; the five hand/non-trial posts 2.3 %.
   The 0.7 % like rate the operator asked about is mostly this: likes come disproportionately from followers, and trial
   reels exclude them. Trial is the right tool for a *risky* format on a *niche* page; it is the wrong default for the
   destination account.
2. **The cutout style, which nightly.yaml runs at 7 a night "because the account's best posts are this footage", has
   never posted.** 27 cutout videos rendered 2026-11-23..26 and sit in the releases (checked `assets-cq_band-fixation-v2`
   and `-wont_be_the_same_again-v2`: every hook_NN is there); 0 have published; 3 are queued for 2026-11-27, the first ever.
   Meanwhile 44 of the 68 bookings since 11-22 were the desktop `band` style, the one the 11-24 pass decided to cut back.
   With `favour_styles {cutout: 3}` and never-used clips carrying the maximum LRU weight, picking 0 of 7+ unposted cutouts
   on fixation while picking lofi three times and band once (11-25/26) has odds under 1 %, so something is blocking them:
   look in the render run logs for `item_rejected` / `creative_exhausted` on cq_band, and at `selector._blocked` /
   `hook_block`. Until this is fixed the account is not running the plan the brain says it is.
3. **The learner's `TALK` mix for cq_band is now mis-scored by our own first comment.** Since 11-24 every post carries
   exactly one comment (the account's own song credit), so `talk = comments / reach` is `1 / reach`, which *rewards the
   least-reached posts* (1/12 for the 16-view lofi beats 1/111 for a 124-view band post). The debate/comment angles the
   mix was added for were removed on 11-24, so `MIX_FOR['cq_band']` should go back to the default `MIX` (or subtract the
   own comment). Same for rocket_league.
4. **Bio-link taps stopped being recorded on 2026-11-22** (`studio/clicks.json` holds one day: cq 9, dc 13, psy 13,
   nostalgia 12). Either the worker's `/stats` fetch has failed since (learn.py only warns) or nobody has tapped in four
   days. It is the only conversion number the system has; it needs to be working before any caption/CTA experiment means
   anything. Also: no account carries a follower count or profile-visit count anywhere in `data.json`/`posts.json`;
   `business_discovery` returns `followers_count` for free and should be logged daily per account.
5. **Shorter wins everywhere in this cluster.** Median completion (avg watch / clip length) on @close__quarters: 0.29 for
   clips under 12 s, 0.19 for 12–20 s, 0.13 for 20–35 s, 0.04 over 35 s; on @dylancantor23 0.34 / 0.20 / 0.15 / 0.07. The
   learner already weights "under 20s" 1.05–1.06, but LYRIC styles are only offered `full`/`tight` (10–20 s); the `short`
   6–9 s loop cut is VISUAL-only (`studio/nightly.py` line 359).

## 1. @close__quarters (close_quarters_ig, campaign cq_band)

### Verdict
**Needs work, bordering on rethink of distribution, not of content.** Single biggest lever: turn trial reels off on this
account (it is the destination, its followers must see it, its grid must fill) and make the cutout footage actually post.
Content-wise the dance cut-outs are the right call; the desktop lyric videos are filler that nobody shares.

### What the numbers say
- 54 published posts with figures, 2026-11-21..26, all but one as trial reels. Median 99 views, mean 102, max 631; median
  watch 2.9 s; median skip rate 73 % (53 posts: min 0, max 88); 45 shares and 20 saves in total, of which 39 shares and 13
  saves belong to the five hand-made posts. Automated posts earn ~2 shares+saves per 1,000 views; the hand posts 39.
- By style (automated): **lofi** n=7, median 115 views, 3.2 s, completion 0.25, 1 share+save/1k; **band** n=31, median 81,
  2.9 s, completion 0.16, skip 72 %, 2/1k; **cursor** n=5, median 52, 2.7 s, completion 0.17, 0/1k. **cutout** n=0 (see
  above). The two hand-made cut-out dance videos from lineup.yaml: 347 views / 21 shares / 5.4 s (Won't Be the Same Again)
  and 170 views / 6.2 s (Fixation): these are still the best automated-looking posts the account has, and they are the
  footage cutout uses full-screen.
- Songs: Fixation (n=9, median 115), Notta Problem (120), Evil Close Quarters (112), Silver and Gold (110), Prologue (106),
  Won't Be the Same Again (100) lead; Hair of the Dog (45), Myth of Sisyphus (43), Suspended (61) trail. Only four songs
  have dance footage (Fixation, Won't Be the Same Again, Full Ride, Notta Problem: 7 clips, two people, 10 fps).
- Daily totals do not grow with posts: 9 posts → 817 views (11-21), 8 → 1,372, 10 → 1,209, 9 → 841, 12 → 1,073. Eight
  posts a day are splitting roughly the same ~1,000 daily views; the 11-26 posts (6 so far) sit at a median of 25.
- Knobs: every knob dimension has 1–9 posts per option (wall 8 options, theme 9, chrome 3, hook 13 lines, 34 sections);
  weights sit at 0.9–1.1, i.e. noise. The learner cannot learn here at this granularity and volume; it can only learn
  style, length and song. "hook angle: share 1.08 / debate 1.05" and the top "hook" lines in weights.json are the bait
  lines removed on 11-23/24: the weights still steer toward them via Thompson sampling on `hook` even though `hook.py` no
  longer offers them (harmless, but it means the hook dimension is unlearnable until the new lines have 5+ posts each).
- Hour posted: 22:00 (n=3, 155 median, 44 shares+saves/1k) is the hand posts; otherwise flat. Confound: the hand posts
  were all posted late evening and are the only non-renderer content, so hour-of-day cannot be read.

### Content audit
- **Cover / first second.** Cutout (sheet `cutout_fixation.png`): the cut-out is centred, big, face readable at phone
  size, "NEW ALBUM. OLD MOVES." in a yellow box at y≈0.155 (inside the safe area). This is the only style on the account
  whose frame 0 says "a person, a band". Band desktop (`band_fixation_sheet.png`): frame 0 is a green equaliser in a
  Win95 window with the flash box "YOUR PC IN 2001:" at mid-screen covering the equaliser; the lyric line sits at the
  bottom of the window stack; "EDUCATION / lesson 5 of 15: Fixation" top-left at y=330. Nothing in the first second says
  "band"; faces arrive later (`faces` 75 %). Lofi (`lofi_fixation.png`): a 480×360 picture blown up 2x inside a Mac
  player, the figure fills maybe a fifth of the screen, the lower half of the frame is an empty desktop: the footage is
  wasted, which the 11-24 note already concluded (now 1 a night). Cursor: a figure made of cursors in a Plexus window on
  black; abstract, no band identity, lowest median: candidates for retirement.
- **Credit.** Cutout: `♪ fixation — close quarters` at 28 px DejaVu, H-450: readable but small; band: "lesson N of 15:
  Fixation" small at top-left; no on-screen "where to listen". Research (below) is consistent that reels using the artist's
  own audio should carry the song name and "link in bio" on screen because viewers do not realise the sound is the
  artist's. The caption and first comment do say it; the picture does not, except in small type.
- **Captions / first comment / hashtags.** Bank is statement-only now (31 lines + per-song files); first comments rotate
  three true lines naming the song, the album and "link in bio"; 5 hashtags (#newmusic #lyricvideo #y2k #indiemusic
  #psychedelichiphop). Two bait captions still went out after the cleanup from the already-booked queue ("which line hit
  hardest? comment it" 11-24, "if you know every word by the end, follow" 11-25); nothing bait-like remains in the banks
  (grep for follow/comment/tag/send/👇 is clean). `funnel.link` is empty, so every "link in bio" depends on the bio being
  right, which this session cannot see.
- **Loopability.** Cutout's frame 0 is a composed cover, so the loop has a visible restart; band/lofi render a clean audio
  loop (`cut()` crossfades into the pre-roll). Fine for 12–20 s; the 6–9 s loop cut is not available to these styles.
- **Niche consistency.** A follower would get: desktop lyric videos (6/night), cut-out dance (7/night, not yet),
  cursor worlds (2), one media-player video. Four looks for one small account reads as four accounts. A band page should
  have one recognisable look per week, with the band in it.
- **Cadence.** 8 a day on a 13-day-old album on the band's own account. Mosseri's position is "no single answer", but
  the daily total here does not scale with count, each extra post splits the same ~1k views, and 8/day of near-identical
  desktop videos is what an account looks like when it is automated.
- **House rules.** No violations found: band footage only here; no ripped footage; no asks in current banks or hooks.

### Research (what works for a band's own page on Reels in 2025–26)
- Ranking: Mosseri (Jan 2025) named watch time, likes per reach and sends per reach as the top three Reels signals, with
  sends mattering more for non-followers and likes more for followers; comments are not on the list.
  https://www.socialmediatoday.com/news/instagram-shares-algorithm-2025/738034/ ·
  https://uppbeat.io/blog/creator-news/whats-working-on-instagram-right-now-carousels-and-sends-says-adam-mosseri
- Trial reels: shown to non-followers, not on the grid, auto-share "if it performs well based on views within the first
  72 hours"; Instagram pitches them for testing content, not as a default.
  https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers-first/ ·
  https://techcrunch.com/2024/12/10/instagram-rolls-out-trial-reels-that-arent-shown-to-a-creators-followers ·
  https://betanews.com/2025/07/14/instagram-opens-up-trial-reels-feature-to-more-creators/ ·
  https://www.planoly.com/blog/trial-reels-auto-share-vs-manual (secondary; says engagement also counts)
- Originality: Instagram recommends only the original of duplicated content, judges an account over a month, and treats
  watermarks/speed changes/credit as not "materially edited"; aggregators lose recommendations until 30 clean days.
  https://www.engadget.com/instagrams-algorithm-overhaul-will-reward-original-content-and-penalize-aggregators-130018977.html ·
  https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/ ·
  https://tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator
- Cadence: Mosseri says there is no one number (creators post monthly or 5 a day); Buffer's 2.1M-post analysis finds more
  posts correlate with more reach (correlational); SocialPilot recommends ~1 reel a day. None of this supports 8/day of
  one format on a band page. https://routenote.com/blog/how-often-you-should-post-on-instagram/ ·
  https://buffer.com/resources/how-often-to-post-on-instagram/ ·
  https://www.socialpilot.co/blog/how-often-to-post-on-instagram
- Band-page formats: guides for independent musicians converge on performance/rehearsal/phone footage of the band for
  discovery, lyric videos for existing fans, naming the song on screen when using original audio, one smart link, Stories
  with a link sticker for the click, a "Musician/Band" category, and a pinned "listen" post.
  https://www.obscuresound.com/2025/05/social-media-growth-tips-for-independent-musicians-in-2025 ·
  https://www.thatericalper.com/2025/04/09/25-short-form-video-music-promotion-ideas-that-work-for-indie-artists/ ·
  https://creatorflow.so/blog/how-to-promote-music-on-instagram/ ·
  https://diymusician.cdbaby.com/video/video-for-musicians-in-2025/
  (Note: most of these are vendor blogs; none gives measured first-month numbers for small bands.)

### What a real indie band's team would do with this account in the first month after an album
- Make the profile the landing page: bio "EDUCATION, out now" + one smart link, category Musician/Band, three pinned
  reels (album trailer, the best dance cut-out, a real rehearsal/performance clip), and a grid that reads as one album
  (a consistent cover: song title + "N/15" + the band). Trial reels off, so posts land on the grid and reach followers.
- Post 1–2 reels a day, 4–5 a week minimum, not 8 a day: one "the band" post (phone footage, rehearsal, the cut-outs) and
  at most one lyric/visual post; daily Stories with the link sticker (the engine does not do Stories; a human should).
- Use the band's own sound on every post, named, so the audio page aggregates everything and fans can use it; answer every
  "what song is this" from @close__quarters itself; reshare fans' reels in Stories.
- Run a 15-week "lesson N of 15" series, one song a week, so each song gets a week of grid presence instead of all 12
  songs cycling 8 times a day.
- Keep trial reels for the experimental formats (cursor, trip effects) and for new hooks, with auto-share on.

### Recommendations (ranked by expected impact)
1. **Turn trial off on close_quarters_ig** (`accounts.yaml trial_reels: false`), keep the sound named and `share_to_feed`
   true. Measure for 7 days against the previous 7: views, likes/reach, sends/reach, and follower count (add it). Expect
   like rate to move from <1 % toward 2–3 % and the grid to fill. If the operator wants to keep testing, run trial on at
   most the `band` style via a per-campaign flag and compare. **quick**
2. **Find out why cutout clips are never selected** (render log `item_rejected`/`hook_block`/`creative_exhausted` for
   cq_band; also check the cutout mp4s' duration and size against `video.min_duration_sec`/`max_file_mb`, and whether the
   render job's checkout had the day's recipes). Until fixed, use `lineup.yaml` to hand-book two cutouts a day. **medium**
3. **Cut posts_per_day from 8 to 3 and rebalance nightly**: cutout 2, band 1, lofi 0, cursor 0 (retire; median 52, no
   shares, no band identity). Daily views have not grown past ~1k with volume; three posts with the band in them will each
   get the reach eight were sharing. **quick**
4. **Put the song and where to hear it in the picture.** Cutout: raise the credit to 40 px bold and add a second line
   "EDUCATION · out now" at the same spot; band: replace "lesson 5 of 15: Fixation" with a bigger "Fixation · EDUCATION
   out now" lockup under the top bar. **medium**
5. **Offer the `short` 6–9 s loop cut to cutout and lofi** (they are FOOTAGE styles, not strictly LYRIC; words can be
   `none` for short cuts) and cap `join` for cq_band at 20 s. Completion is 0.29 under 12 s vs 0.16 at 12–20 s. Learner
   measures it via `knob:cut` and `length`. **medium**
6. **Fix the learner for this campaign**: `MIX_FOR` drop cq_band (first comment pollutes `talk`); add follower count and
   profile views as a daily account-level row so the engine can finally see follows. **quick/medium**
7. **More band footage, more songs.** Only 4 of 15 songs have dance clips; a 30-minute phone session (two people,
   plain wall, each song's chorus) would double the cutout library and let the "song of the week" series cover all 15.
   Backlog's "band in real places" scene style depends on this too. **large (human)**
8. **One look per week.** Pick cutout as the house format for @close__quarters; the band desktop becomes 1 a day
   at most, cursor moves to a trial-only experiment. **quick**
9. **Bio-link stats**: check `cq-listen` `/stats` (clicks.json has not updated since 11-22) and put the tap count on the
   dashboard; an experiment on captions without it is blind. **quick**
10. **Caption experiment once (1) and (3) are in**: half the posts with the first line = the song's own best lyric line
    (true, specific, shareable), half with the bank's generic lines; measure sends/reach over 30 posts. **quick**

### Risks
- Trial-by-default is hiding the band from its own followers and emptying the grid (above).
- Eight automated posts a day on the band's own page looks like automation and dilutes reach; combined with trial reels
  and a 73 % skip rate it is the profile of an account Instagram stops recommending.
- `lineup.yaml` still holds "be honest 👇 skip or replay?" and "who did it better? 👇" entries (already posted; they will
  not repost, but they are engagement-bait text in the repo and will be copied).
- Weights still rank removed bait hooks at the top of `hook`; if `hook.py` ever re-adds a line with the same text it will
  be favoured immediately.

## 2. @dylancantor23 (dylancantor23_ig, campaign cq_producer)

### Verdict
**Needs work.** Biggest lever: fewer, truer, shorter stem videos with a person in them, posted as normal reels, not trials.
3 a day is right; 2 would be fine; 8 was wrong, and the data already proved it.

### What the numbers say
- 48 posts with figures (11-20..26), all trial. Median 46 views, mean 66, max 339; median watch 3.5 s; median skip 67 %;
  **2 saves and 3 shares in 48 posts**: no distribution signal at all. Like rate 0.5 % on renderer posts, 0.8 % on the
  eight hand-made Notta Problem clips (archive, "verse 1, first half": median 117–125 views, 4.7 s).
- 8/day vs 3/day: daily totals were 552 (10 posts), 407 (6), 351 (7), 695 (8), 594 (10), 217 (6, young). ~400–700 views a
  day regardless of count; posts split the audience. The 11-24 rebuild (build/strip stories) has 11 posts so far, median
  ~25 views (ages 0–2 days, so partly too new): no lift yet. Old `mixer` layout median 56 vs `lanes` 23.5.
- Completion by length 0.34 (<12 s) / 0.20 / 0.15 / 0.07: the payoff (FULL MIX / ALL BACK IN) must land inside 10 s.
- Songs: Notta Problem median 125 (n=8) is the best by far and is **weighted 0.001** ("resting: lyrics unchecked");
  Fixation 90, Myth 78, Prologue 75; Talk 6, Full Ride 10, Subway Maintenance 17, Won't Be the Same Again 20.
- Learner: 38 posts, every option 1–7 posts, weights 0.92–1.13 (noise). `hook angle: comment 1.09` and the top hooks
  ("which stem is carrying?", "producers: what would you change?") are the removed comment-asks. Skip rate is available
  here (direct API), so `held` is real; `sends` is 0 for 45 of 48 posts, so the 30 % sends term is ties.

### Content audit
- Frame 0 (`producer_fixation_sheet.png`): "just the vocal. the band comes in one by one" + a VOCAL ONLY pill, four DAW
  lanes, legible, inside the safe area; FULL MIX arrives with coloured lanes. It is a clean, honest explainer. What it
  lacks: a human. Producer content that grows on Reels is a face reacting to the moment the beat drops, then the screen
  (fluxnote; influenceflow). The `faces` sprite (Dylan reacting at the drop) is on only when `faces` is drawn and only at
  the drop; the cover never has him.
- The "stems" are 22 kHz demucs separations (log 2026-11-24: "real stems from the Ableton projects are next"). To a
  producer audience, "VOCAL ONLY" with separation bleed is audibly fake; the single most credibility-building change is
  real stems from the sessions.
- Captions: statement-only bank, good ("i produced this. here's one part of it on its own", "four stems. one song");
  hashtags #producer #musicproducer #beatbreakdown #stems #newmusic; first comment credits @close__quarters + album +
  link in bio: the funnel to the band account is right.
- It is Dylan's personal account posting 3–8 DAW screens a day with the same caption shapes: it reads as a bot feed.
  The eight hand-made clips outperform every renderer post; what they had was a specific moment ("verse 1, first half" of
  the best song), not a knob.
- Cadence: 3/day since 11-25 (nightly `per_night: 3`, config `posts_per_day: 3`); the account still posts every renderer
  output as trial, so Dylan's own followers (the people most likely to share a producer reveal) do not see them.

### Research
- Producer formats: beat built from scratch in 30–60 s as the native format; open on the producer's visible reaction, then
  the cause; hook 0–3 s, process 3–25 s, payoff; one session cut into many posts; Instagram is where A&Rs/managers look,
  TikTok is cold discovery; stem breakdown is a release-week item, not a daily feed.
  https://fluxnote.io/guides/instagram-reels-music-production-strategy ·
  https://influenceflow.io/resources/music-producer-social-media-strategy-complete-guide-to-growing-your-fanbase-in-2026 ·
  https://artistrack.com/?p=304526
- Trial reels and ranking: as above (about.fb.com; socialmediatoday 738034).

### Recommendations
1. **Trial off** on dylancantor23_ig; it is a personal account whose followers are the seed audience. **quick**
2. **2–3 a day, no more**, and make each one a specific moment: the song's best 8 bars, chosen by hand per song in
   `song.json` (like the archive Notta Problem clips) rather than any proven section. **quick**
3. **Un-rest Notta Problem**: fix its lyrics / force-align it (it is the account's best song at 0.001 weight). **medium**
4. **Real stems** from the Ableton projects for the four songs with footage first; until then, prefer `first: Drums`
   builds (drum stems separate cleanly; vocal separation bleed is what gives demucs away). **large**
5. **Shorter stories**: `strip` = 2 bars alone then all back in inside 10–12 s; `build` = drums, +bass, +vocal, FULL MIX
   on four consecutive bars (8–10 s at 120 BPM), window capped at 14 s (`join: 14` for cq_producer). **medium**
6. **A person on the cover**: reuse `faces.py` to put Dylan's reaction sprite on frame 0 (or, better, a 3 s phone clip of
   Dylan at the desk hitting play, which needs one filming session), then cut to the DAW. **medium/large (human)**
7. **Retire the cq_producer-specific learner dimensions that cannot learn** (hook, caption, palette) from Thompson
   sampling for this campaign and let it choose only story/first/length/song until there are 10+ posts per option. **quick**
8. **A weekly "making of" that is actually made by a human**: one 30–45 s reel per week with real session footage; the
   renderer posts become the filler between them, not the feed. **large (human)**

### Risks
- Zero sends/saves across 48 posts and a 67 % skip rate are the profile of content Instagram will stop recommending;
  volume makes it worse, not better.
- "Stems"/"VOCAL ONLY" claims on separated audio could draw "this is AI/fake" comments from producers.
- Trial reels keep the account's own network out; the like rate (0.0 % median) is the symptom.

## 3. @the.loose.change (nickdotname_ig, Buffer; campaigns nick_studio + closequarters [paused])

### Verdict
**Rethink.** The memes were the cluster's best sharing format and died of clip reuse and ripped footage; the kinetic type
replacement is a third lyric format in the cluster with the weakest numbers. Biggest lever: rebuild the meme pool from
Nick's own footage and move the account off Buffer onto the direct publisher.

### What the numbers say
- 67 posts with figures: 61 memes (closequarters) and 6 type videos (nick_studio). Memes: median 35 views but mean 85,
  48 shares and 28 saves (the best share rate in the cluster: 11 shares on single posts on 11-17), watch 4.5 s. Daily median
  fell 201 → 163 → 167 (11-17..19) to 32 → 20 → 18 → 19 → 15 → 10 (11-20..25) as the 15-clip pool repeated (hook_05 11x in
  a week) and Instagram's originality rules bit (all 15 clips were ripped; disabled and paused 11-24).
- Type (nick_studio): n=6, median 32 views, 2.5 s watch, completion 0.17, **0 shares, 0 saves**, 4 % like rate (10 likes
  on 251 views, i.e. Nick's followers). One a day since 11-25 (was 3).
- Buffer metrics carry no skip rate, so the learner's `held` is 0.5 for every post here; with 6 posts nothing is learned.
  Songs: Won't Be the Same Again median 122 over 14 meme posts, Myth of Sisyphus 23.5 over 18 (over-posted).
- Account posts 11–23 with `start_hour 0 / end_hour 0` for memes (all day); fan-out to nickdotname_tt (TikTok) gets 1 view.

### Content audit
- Type (`type_fixation.png`): frame 0 is the word "fixation" in blue Fraunces on paper with "EDUCATION 05/15" and a clock
  in the header, credit at the bottom; everything inside the safe area, highly legible. It is a lyric sheet, still, with
  no face, no motion and no reason to stop; `scroll` layout shows one word. The format is well made and shareable to
  nobody: 0 sends in 6 posts. Kinetic-lyric content is a saturated tool-template genre (search results are all template
  vendors); on an account with a few hundred followers it competes with @close__quarters' own lyric videos for the same
  viewers and loses (32 vs 81 median).
- Captions: statement-only, song credited with album, 5 hashtags; **no first comment (Buffer free plan)** and no trial
  option, no audio naming guarantee. The song credit is in the caption body only.
- Meme pool (`campaigns/closequarters/clips.json`): all 15 hooks and 6 music beds disabled; `captions.txt` overlay lines
  ("how me and bro start moving | when {name} comes on", "me waiting for my friend to get to the good part") were written
  for reaction footage and are only true with footage that shows that.
- House rules: band footage is not allowed here (CLAUDE.md: only @close__quarters and @dylancantor23), so the rebuild must
  be Nick's own clips (NYC inbox, Rocket League, his own phone footage of anything but the band), public-domain plates, or
  text cards.

### Research
- Originality: an account judged mostly unoriginal over a month loses recommendations and gets them back after 30 clean
  days; watermarks/credit do not help. The pause on 11-24 starts that clock; check Account Status in the app.
  https://tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator ·
  https://www.engadget.com/instagrams-algorithm-overhaul-will-reward-original-content-and-penalize-aggregators-130018977.html
- Sends per reach is the signal that reaches non-followers (Mosseri, above); the meme format produced sends, the type
  format produces none.
- Lyric reels: vendor guides recommend them for existing fans, not discovery; the one consistent tip is naming the song on
  screen. https://www.thatericalper.com/2025/04/09/25-short-form-video-music-promotion-ideas-that-work-for-indie-artists/

### Recommendations
1. **Rebuild the meme pool from own footage**, keeping the format that worked: a white caption bar + a relatable line +
   the song at full level. Sources that exist today: `nyc_video.py` `meme` kind (median 116 on nyc.daily, the account's
   best kind), Nick's NYC inbox clips, the 17 Rocket League clips (`rocket_video.py`), public-domain plates. Write new
   overlay lines that are true of city/game footage ("the walk home when {name} comes on", "my aux song this week:
   {name}"), no asks. 21-day clip cooldown and `repeats: false` stay. **medium**
2. **Move the account off Buffer** onto the direct Instagram publisher via connect.closequarters.vip (own token slot):
   gives first comments, insights with skip rate, audio naming, and trial control; drop nickdotname_tt from the campaigns
   (1 view) to stop spending Buffer/TikTok quota. **medium (needs Nick to log in)**
3. **Type style: 1 a day at most, or retire.** If kept, make it earn its place: `slam`/`block` layouts only, the biggest
   word of the hook line on frame 0, a 10–14 s window from the chorus, and measure sends; retire after 20 posts with
   0 sends. **quick**
4. **Make the account Nick's**: a human post a week (his NYC clips, his own voice) so the feed is a person who likes this
   band, not a third renderer; the band's funnel line stays in the caption ("@close__quarters"). **large (human)**
5. **Until the pool is rebuilt keep the account at 1–2 posts a day**; 30 clean days (to ~12-24) before expecting
   recommendations to return. **quick**

### Risks
- Originality penalty is probably already applied (views fell 10x); more unoriginal clips restart the 30-day clock.
- Two campaigns on one Buffer channel starve each other (`buffer_share` 4/6) and TikTok fan-out wastes the cap.
- No first comment means the song is credited only in the caption body on this account.

## Experiments the learner can measure (all three accounts)
- **Trial vs normal (close__quarters, dylancantor23)**: 7 days off vs the previous 7 on; metrics: likes/reach,
  sends/reach, views, follower delta, grid count. (No A/B within a day: trial is per account in `accounts.yaml`; a
  per-campaign override would allow 50/50 by seed if wanted.)
- **Volume**: cq_band 8 → 3 a day; compare daily total views and per-post sends/reach over a week (the daily total should
  not fall; per-post should rise).
- **Length**: `short` loops vs `tight` on cutout, via `knob:cut`/`length` (completion and sends/reach).
- **Caption first line**: lyric line vs bank line, via `caption` dimension once 15+ posts per arm.
- **Cover**: band style with a band photo on frame 0 (`pictures` knob forced high + a `cover_at_sec`) vs equaliser cover,
  via `knob:pictures` and skip rate.
