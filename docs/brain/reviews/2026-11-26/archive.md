# Cluster `archive`: psychedelic.station, nostalgia.hub.vhs, glitch.archive.exe, vintage.media.archive, ascii.cinema.tty, ascii.terminal.dreams

Reviewed 2026-11-26 from `cqdash/data.json` (generated 20:51Z), `campaigns/<c>/{posts,recipes,config}.json|yaml`,
`studio/weights.json`, `studio/LEARNED.md`, `studio/nightly.yaml`, the six renderers, `studio/post_factreel.py`,
`studio/post_carousel.py`, `studio/collabs.py`, and contact sheets rendered into
`/tmp/claude-0/-home-user-ugc-factory/bd16ba37-fa04-5fa1-8c52-0897619fc36c/scratchpad/archive/` (psy, liminal, ascii
at frames 0/15/30/60/150/300 of `talk` 23-38 s; glitch/vintage/cinema: see the note at the end). Nothing in the repo
was changed.

## 0. What the six accounts have in common (read this first)

**Views are not a continuous number here; they are a coin flip.** On every account the view counts split into two
piles: posts Instagram put in front of a test batch of non-followers (roughly 100-300 views, reach ≈ views) and posts
it showed to almost nobody (1-60 views, reach 2-50). The *share of posts that got a batch* is the real health metric
and it tells a cleaner story than medians:

| account | posts/day (actual) | share of posts that got a batch (≥100 views), by day |
|---|---|---|
| psychedelic.station | 17, 18, 12, 18, 15, 10 (Nov 21→26) | 4/17, 5/18, 4/12, **2/18, 2/15, 0/8** |
| nostalgia.hub.vhs | 14, 9, 13, 11, 8 (Nov 22→26) | 6/14, 1/9, 3/13, **2/11, 0/8** |
| glitch.archive.exe | 2, 3, 5, 7 | 2/2, 1/3, 0/5, 1/7 |
| vintage.media.archive | 2, 6, 6, 1 | 1/2, 3/6, 2/6, 0/1 |
| ascii.cinema.tty | 8, 4, 2 | 4/8, 4/4, 1/2 |
| ascii.terminal.dreams | 2, 6, 6, 5, 4 | 2/2, 6/6, 6/6, 5/5, 3/4 |

ascii.terminal.dreams gets a batch for almost every post; cinema for about half; psychedelic.station and nostalgia
have gone from "a third of posts get tested" to "none", and the slide continued after posts/day was cut on Nov 25.

**The watch-time question has a simple answer: nobody is leaving at the second cut, they are leaving before the first
one.** Median skip rate (swiped away inside 3 s, Instagram's own metric) is psy 79%, nostalgia 77%, glitch 84%,
vintage 83%, cinema 79%, ascii 71%. Socialinsider's 2025 benchmark for 1-5K accounts is ~65% ([socialinsider](https://socialinsider.io/blog/instagram-reels-statistics/)).
With 80% gone in under 3 s, a 2.6 s *average* watch time means the 20% who stay watch most of the clip (completion
on the ≤10 s loops is 0.3-0.5; on 10-20 s clips 0.15-0.23). So the lever is frame 0 to frame 30, not the edit.
The best posts on every account have skip rates of 41-64%, the worst 85-100%.

**The learner cannot learn on five of the six.** `learn.py` ranks posts within a campaign and then splits them across
every knob (psy has ~20 knobs with 2-12 options each: 2-9 posts per option; glitch 17 posts over 7 knobs; vintage
15 posts over 10 knobs). Every weight in `weights.json` for these campaigns sits between 0.90 and 1.13, i.e. noise, and
Thompson sampling on that is a random draw. Worse, the dominant variable in this week's data is *the day the post went
out* (reach decayed day by day on psy/nostalgia/glitch/vintage), and `HALF_LIFE=21` with recency weighting means any
knob that happened to be tried on Nov 25-26 looks bad. The hand-retire lines in `nightly.yaml` (marble/spiral/warp/oil,
school/pool, water/nature) are the right tool at this sample size; the knob menus should be cut to 3-4 knobs per
style until an account has ~100 tested posts.

**Instagram's current ranking guidance, as it applies here** (secondary sources; the official pages are outside this
session's network): Mosseri (Jan 2025) named average watch time, likes per reach and sends per reach as the signals that
carry the most weight, with sends mattering more for reaching non-followers and likes more for followers
([socialmediatoday](https://www.socialmediatoday.com/news/instagram-shares-algorithm-insights-2025/738034/),
[socialmediatoday 2](https://www.socialmediatoday.com/news/instagram-chief-post-share-rates-key-driver-reach/716540/)).
Instagram replaced "view rate" with **skip rate** and a retention chart in Reels Insights in August 2025
([socialmediatoday](https://www.socialmediatoday.com/news/instagram-adds-retention-insights-reels/758464/),
[metricool](https://metricool.com/instagram-reel-analytics/)). **Trial reels** (Dec 2024) go to non-followers first and
"shouldn't impact the performance of your regular reels" ([about.fb.com](https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers/),
[sproutsocial](https://sproutsocial.com/insights/instagram-trial-reels/)); all six accounts have `trial_reels: false`.
The **April 2026 originality crackdown** removed recommendation eligibility from accounts that mostly repost, extended
it to photos/carousels, and says low-effort edits (watermark, speed change, credit) do not count while "material edits
such as new narration, graphics or commentary" do; eligibility returns ~30 days after the last unoriginal post
([techcrunch](https://techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/),
[petapixel](https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/),
[tubefilter](https://tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator)).
vintage.media.archive already got that notice on Nov 25. On cadence Mosseri says there is no golden number ("five
reels a day works for some, once a month for others") ([routenote](https://routenote.com/blog/how-often-you-should-post-on-instagram/)),
but Metricool's panel doubled posting volume in 2025 and reach fell anyway ([socialpilot](https://www.socialpilot.co/blog/how-often-to-post-on-instagram)),
and the data above shows the same thing per account: daily totals did not grow with posts. Instagram's Recommendations
Guidelines also say it tries not to recommend content that "promotes the use of certain regulated products ... or
pharmaceutical drugs" ([help.instagram.com](https://help.instagram.com/313829416281232)); this matters for
psychedelic.station's fact reels (see §1).

Niche research caveat: WebSearch returned no reliable 2025-26 rankings of glitch/liminal/ASCII/vintage/psychedelic
*accounts*; what it did return is format evidence, cited per account below.

---

## 1. @psychedelic.station (psy_station; psy + collage, carousels, fact reels)

**Verdict: rethink.** The biggest lever is stopping the three jobs that post into it and giving the account one format,
posted twice a day, for a week, to see whether Instagram will test it again at all.

### What the numbers say
- 90 posts in six days: 45 psy visualisers, 12 collages, 18 carousels, 15 fact reels. Views by day: median 55, 55, 38,
  29, 22, 17. The cut from 8→4→2 psy/day on Nov 25 did not stop the slide: Nov 26's ten posts got 0 test batches.
- **Carousels have never worked**: 18 posted, views 13-65, **reach 3-18** (views > reach = the same few people, mostly
  from the profile). They exist "so fact reels have something to point to", but the fact reels' end card points
  to a carousel nobody will open. They are a quarter of the account's output and contribute nothing but volume.
- **Fact reels were the best format and then died**: 153, 151, 204, 113 (Nov 21-23) → 139, 65, 16, 14, 9, 1 (Nov 24-26).
  nostalgia's fact reels on the same nights still got batches (227, 224 on Nov 25), so this is not the fact-reel job.
  Two things differ: psy's are ~18-22 s of text cards (watch 3-9 s, so completion 0.2-0.4) and **every psy headline is
  about LSD, psilocybin or the CIA dosing people** (bicycle-day, good-friday, midnight-climax, mkultra, leary-escape,
  concord-prison, huxley). That is squarely the "promotes the use of ... drugs" classifier territory of Instagram's
  Recommendations Guidelines, even when the content is history. The cleanest test: post only the non-drug specs for a
  week (petrov, tunguska, voynich, bloop, kryptos, numbers-stations, ghost-army, habakkuk) and compare.
- psy knobs (n=45, views / s watched / shares+saves): field tunnel 109/4.3 (n=3), moire 68/3.9 (8), kaleido 52/3.2 (9,
  19 shares+saves, the most), bryce 41, voronoi 41, oil 29, spiral 26, warp 22, marble 12 (retired Nov 25: right).
  **strobe=true: 28 views, 4 shares+saves over 18 posts vs 53 views and 46 shares+saves without** (not retired; should
  be). contour=true: 41 shares+saves vs 9. word_y 0.72: 55 views/38 shares+saves vs 0.5: 28/12 (the lyric higher up
  the frame fights the picture). sym 3: 63 views and 5.0 s watched (n=4) vs sym 4: 25 views/2.9 s. Palette lava:
  22 shares+saves (n=8), the rest ≤9.
- collage: ice palette got 103-114 views but 1.7-2.3 s watched and 0 saves: it gets tested and fails the test. Dropping
  it on Nov 24 was right (it kept posting from the library until Nov 25: 6 that day).
- Length: ≤10 s loops complete at 0.50 (watch 3.75 s), 10-20 s at 0.23, 20-35 s at 0.16, 35 s+ at 0.08. Only the
  ≤10 s and 10-20 s cuts should be rendered (`join: 40` lets 35 s+ through).
- Hour of day: flat (9:00 and 22:00 slots lowest at 30 and 15 median; everything else 34-65).
- **The kaleido post (144 views, 16 likes, 9 shares, 5 saves, 4.2 s): what it did right.** Recipe: Fixation s01
  (12.4-30.8 s), `kaleido`, `sym 8`, `pal lava`, `contour`, `speed 0.6`, `feedback false`, `strobe false`, `mirror
  false`, no motif, no ring, lyrics as lines at `word_y 0.72`, second field `marble`, `hook ''`. Posted Sunday
  6:16 pm NY. Caption: "what do you see in this? wrong answers only" (comment bait: since removed, and rightly, but it
  is why there were 9 shares: people sent it to a friend to answer). The *picture* side is reproducible without the
  bait: 8-fold symmetry + slow speed + contour lines = a mandala that resolves into faces (pareidolia; the contact
  sheet below shows a 2-eyed "face" in the oil/marble field too). The lesson is "symmetry that the brain reads as a
  face or an object, moving slowly enough to be looked at", not "kaleido".

### Content audit
- Contact sheet (`archive/psy_small.jpg`, oil field, neon, speed 1.6, hook ''): frame 0 is a handsome symmetric blob;
  frames 0 and 15 are near-identical; no text, no motion cue, no reason to keep watching, no song name on screen until
  the credit line. It is a good *cover* and a weak *hook*. Half of psy videos get no opening line at all
  (`hook.NONE_SHARE['psy'] = 0.5`), and the lines on offer ("the bass is moving the picture") describe, they don't promise.
- Captions (`captions.txt`, 15 lines): clean, no asks, and they all say the same thing ("made from the song's own
  stems"). The hashtags (#psychedelic #trippy #psychedelicart #visualizer #audioreactive) put the account in the same
  pool as the AI-video psychedelic generators that dominate that niche's search results
  ([neuralframes](https://www.neuralframes.com/styles/progressive-psychedelic), [freebeat](https://freebeat.ai/visual-art/psychedelic-music-visualizer),
  [opus.pro](https://www.opus.pro/blog/audio-reactive-video)); "no AI" is a real differentiator but it is only claimed
  in the caption, never shown.
- Song credit: first comment "🎧 the song is {name} by @close__quarters, from their album EDUCATION" + "link in bio"
  CTA in the caption + `audio_name "{name} – Close Quarters"`. Fine, but nothing on screen before the credit line
  at the bottom. The audio is uploaded as original audio per post, so Instagram cannot pool "use this sound" across
  posts (CD Baby: claim attribution with ISRC/start time so reels show artist + title, [cdbaby](https://diymusician.cdbaby.com/releasing-music/instagram-reels-music/)).
- Niche consistency: a follower sees visualisers, mirrored temple collages, CIA/LSD history carousels, and 20 s
  text-card reels. There is no single thing this page is.
- Cadence vs age: 17-18 posts/day on Nov 21-22 is the highest in the network and the account's reach slid from
  that day on. Even now it is ~6/day across three jobs, often within minutes of each other (62 of 88 posts had another
  post within 45 minutes).
- House rules: old captions in the data include "tag someone who needs 20 seconds of this", "send this to the friend
  who would stare at it for an hour", "what do you see in this? wrong answers only", "how far did you make it before
  you looked away?" (11 posts). Bank is clean now. Collab invites: `collabs.PLAN = {}`, off.

### Research (what works in this niche)
- The psychedelic-visuals search results are dominated by AI generators and painters (Alex Grey ~1.3M,
  [doubleblindmag](https://doubleblindmag.com/psychedelic-artists-on-instagram/)); "audio-reactive" is sold as a
  tool category ([opus.pro](https://www.opus.pro/blog/audio-reactive-video)). The reels that spread in this space are
  (a) short perfect loops (replays count: [techbullion](https://techbullion.com/loop-your-way-to-growth-a-smarter-instagram-strategy-for-2025/),
  [getimg](https://getimg.ai/blog/guide-to-making-ai-art-go-viral-on-social-media)) and (b) things that *do* something
  (an illusion, a reveal). rotation.illusions in this same network (median 1,376 views, 9.2 s watch) is the proof.
- Saves come from reference/utility, not pure aesthetics ([getimg](https://getimg.ai/blog/guide-to-making-ai-art-go-viral-on-social-media)).

### Recommendations (ranked)
1. **Pause carousels for psy_station** (`publish.yml` line 170 runs `carousel.yml` once a day; filter it to nostalgia or
   set the psy specs aside). quick. Measure: nothing to measure; they have never reached >18 people.
2. **Pause the drug-topic fact reels; keep the non-drug ones; make the reel ≤12 s.** In `post_factreel.py` the reel is
   headline + 3 slides + pointer ≈ 18-22 s with 3-9 s watched. Cut to headline + 2 slides, no "all 6 slides are in the
   carousel" end card (there will be no carousel), and run only specs whose headline has no LSD/psilocybin/dosing in it
   for one week. quick (spec list + `OPEN_S/END_S` + slides[:2]). Measure: share of fact reels getting a batch vs the
   Nov 24-26 baseline of 2/8.
3. **One format, 2/day, 1 week, as trial reels.** Set `trial_reels: true` for `psychedelic_station_ig` so the posts are
   judged by non-followers and don't pile on the (possibly fatigued) follower graph. quick (`accounts.yaml`). Measure:
   batch share and skip rate week over week.
4. **Retire `strobe` and lock the winning look.** `nightly.yaml` psy `retire: {field: [...], strobe: [true]}` (strobe is a
   `K.pick` knob, so retire works) and `--set`-style defaults: sym ≥ 6, contour on, speed 0.6, word_y 0.72, palettes
   lava/acid/ice. medium (knob defaults in `psy_video.py`). Measure: shares+saves per 1,000 views (currently 23 for psy).
5. **Give frame 0-30 a reason**: a 2 s line that is true and promises something, e.g. "a face appears when the drums
   come in" (only when the field is symmetric), or render the first beat as a reveal: start on a plain dark frame with
   the song title in the field's palette and let the first kick blow it into the pattern (the "punch" already exists).
   Set `NONE_SHARE['psy']` to 0.2. medium (`hook.py`, `psy_video.py`). Measure: skip rate.
6. **Put the song on screen for the first 2 s** ("Fixation — Close Quarters", top, inside the safe area) so the
   credit is seen by the 80% who leave. quick/medium.
7. **Cut `join` to 20 for psy** so no 20 s+ visualiser is rendered. quick (`nightly.yaml`).
8. Large, if 1-7 don't move the batch share in a week: retire the visualiser and move the account to a reveal format
   (e.g. the `stare` or `hue` ready pages in a psychedelic palette), which is what the network's own data says people
   watch.

### Risks
- Drug-history content on an account tagged #psychedelic is a recommendation-eligibility risk (see guidelines above);
  one strike there and the whole account stops being recommended, which matches what the numbers look like.
- Three jobs posting into one account within minutes (traps.md already notes the double-post problem).
- `hook_cooldown_days: 4` next to `repeats: false` in config is contradictory; `repeats: false` wins, fine, but the
  comment misleads.

---

## 2. @nostalgia.hub.vhs (nostalgia; liminal tapes, carousels, fact reels)

**Verdict: needs work, close to rethink.** The lever is to stop posting liminal tapes as they are and make the fact
reel (90s/2000s things explained in 12 s) the account's main format, with the liminal rooms as its background.

### What the numbers say
- 55 posts: 29 liminal, 15 carousels, 11 fact reels. Median views by day 60, 35, 21, 10, 5.
- **Fact reels about childhood things are the account's only reliable format**: Oregon Trail 292, Blockbuster 255,
  Tamagotchi 223 (Nov 22), Furby 227, Windows hill 224 (Nov 25). The misses were off-topic or part-2s (LimeWire 60,
  AIM 7, Y2K 25, Beanie 6).
- Liminal tapes are bimodal: 276, 243, 230, 154, 228, 207, 234 got batches; 22 of 29 got 3-72 views. Every batch
  winner was backrooms/mall/parking or the early (pre-knob) renders; **pool, school, office, hotel never got one**
  (pool 5 posts median 4 views, school 3 posts median 4, office 2 posts 4.5). The Nov 25 retire of school/pool was
  right, but the library kept draining old renders: pool and school tapes were still posted on Nov 25 and 26, and
  the new rooms (playplace, rink, lab, added Nov 24) had not been posted at all by Nov 26 (recipes: Nov 25 rendered
  1 hotel; Nov 26 1 lab + 1 rink). `retire:` in nightly.yaml stops rendering, not posting.
- Tape knobs with any signal: `tape worn` 50 views (n=6) vs clean/chewed 4; `tint cold/green` 35-47 vs neutral/warm
  3-8; `label PLAY` 35 vs REC 4; `pace`: both dead (6-9). These are confounded with date like everything else.
- Length: ≤10 s loops 55 views, completion 0.41; 10-20 s 6.5 views, 0.18; 20-35 s 25 views, 0.07.
- No post got the "isolated" benefit: posts with another post within 45 min had median 47 views, isolated ones 7
  (the isolated ones are the late-week ones, so again date).
- Hour: 13:00-15:00 NY slots hold the five best posts; 11:00 and 21:00 the worst. Weak, n small.

### Content audit
- Contact sheet (`archive/liminal_small.jpg`, pool, walk, neutral, clean, PLAY, date stamp, line "swim lessons at 8am
  in january"): frames 0, 15, 30, 60, 150 and 300 are the same picture. The walk is so slow that nothing changes in
  10 s; the room is clean CG (no people, no objects, no stains visible at this size), the line is a memory, not a
  promise, and the timecode is the only thing moving. A viewer has nothing to wait for. The loop is seamless, but a
  loop of nothing is nothing twice.
- The memory lines are good copy and within the rules; they just do not make anyone stay. The captions that got
  batches were found-footage framings ("no one else is here. turn it up.", "found this tape in my parents'
  basement", "recorded over a birthday tape"); the current bank keeps that voice. Hashtags fine.
- Carousel specs: sourced, on-niche, no asks; the "slide 4 is how they said it" hook sentence is stripped for reels.
  Still 0 reach as carousels (views 8-48, reach 3-18).
- Song credit: as psy. The fact reels' music is a random song stretch; the caption credits it. OK.
- Niche: liminal CG rooms + 90s trivia + carousels: two niches ("liminal spaces" and "90s kid nostalgia") that only
  overlap in mood. The fact reels show which one the audience wants.
- Cadence: 14 posts on its first day (the account was knick.creates before: its followers are not nostalgia
  followers, which is one more reason to go trial-reels).
- House rules: old captions "if you remember this hallway you had a good childhood", "drop your old screen name",
  "how many did you let die? be honest" (6 posts) were asks; gone now. No band footage, no logos (lab's CRTs draw
  their own desktops).

### Research
- Liminal/dreamcore content spreads as *POV second-person* hooks ("POV: you fell asleep in the play area", "POV: you
  found the exit") paired with a song, on TikTok as compilations with six-figure likes
  ([alici.ai breakdowns](https://alici.ai/formulas/media/other-realm/b470b849-1629-5a31-a1d5-375856503857-liminal-space-dreamcore-ai-video),
  [tiktok @backroomsliminalspace](https://www.tiktok.com/@backroomsliminalspace/video/7425333936722595102)); the canon
  images are empty malls, hallways, pools and parking lots ([Wikipedia](https://en.wikipedia.org/wiki/Liminal_space_(aesthetic)),
  [Dazed](https://www.dazeddigital.com/science-tech/article/52477/1/inside-the-uncanny-world-of-liminal-spaces-tiktok-reddit-nostalgia)).
  The genre is explicitly "a glitch in reality": something is *wrong* in the room. Ours are pleasant and empty.
- Nostalgia on social right now is retro *things* (the 2016 photo aesthetic, old UI, products) more than places
  ([adobe](https://www.adobe.com/express/learn/blog/nostalgia-on-social), [petapixel](https://petapixel.com/2026/01/25/gen-z-is-nostalgic-for-the-photo-aesthetic-of-2016/)).
  That is exactly the fact-reel format.

### Recommendations
1. **Make the fact reel the main format, 2/day, 10-12 s, one slide of payoff** (headline on frame 0, one "did you know"
   card, the answer card, loop). Pause carousels (they are only there as a pointer). Keep `place` matched to the topic
   (`CQ_PLACE`). quick/medium (`post_factreel.py`: slides[:2], OPEN_S 2.0, END card off; `publish.yml` factreel
   times). Measure: batch share of fact reels (baseline 5/11) and watch/length.
2. **Liminal tapes: 1/day at most, only backrooms/mall/parking/playplace/rink/lab, ≤10 s, and purge the already-rendered
   pool/school/office/hotel clips from the library** so `retire:` actually takes effect (`render.yml` picks from the
   library, not from recipes). quick (library prune + `nightly.yaml` retire list adds office, hotel).
3. **Put something wrong in the room by second 1** (medium, `liminal_video.py`): the lights flicker off on the first
   kick and come back on the snare; a door at the end of the hallway is open on frame 0 and closes on the bar; the
   tracking tear hits in the first second instead of waiting for a big drum. The genre's hook is unease, and the
   skip rate (77%) says the rooms are read as screensavers. Measure: skip rate on tapes vs 77%.
4. **Hook line in second person, present tense**, e.g. "you're 8. it's 10pm. the hotel pool is still open" rather than
   "the hotel pool at 10pm on the family road trip". Statements, no asks, same `LINES` dict. quick. Measure: skip.
5. **Trial reels on** for `nostalgia_ig` (its follower graph is inherited from knick.creates). quick.
6. Large: a "then / now" or "things that disappeared" fact format on the liminal rooms (the mall that closed, the
   Blockbuster wall) is the merge of the two niches that the data points at.

### Risks
- Posting retired places from the library makes the account look worse than its new renders.
- Reused follower base from knick.creates (not Close Quarters' audience) drags follower-side signals.

---

## 3. @glitch.archive.exe (glitch_archive; datamosh on public-domain footage)

**Verdict: needs work.** The lever is the footage, not the mosh: use footage people recognise (NASA/space did best)
and lead with what it is.

### What the numbers say
- 17 posts, median 51, skip 84% (worst with vintage), watch 2.7 s. (The 156.9 s "watch" on the 182-view post is an
  API artifact.) Batches: Nov 22 2/2, Nov 23 1/3, Nov 24 0/5, Nov 25 1/7: raised to 5/day the reach went away.
- source: space 83 median (n=4), mixed 83, archive 72, city 61, nature 50, water 39 (water/nature retired Nov 25:
  right). main: mosh 100 (n=4), slit 50, sort 51, points 48, track 38 (5). tone: night 182 (n=1), mono 116 (1),
  thermal 71 (5), xray 51 (5). pace 2 (two-beat melts) 76/2.8 s vs pace 1 49/2.3 s. accent rgb gets views (62) but
  0 shares+saves; blocks 49 views, 7 shares+saves. label rec vs none: no difference.
- The Nov 25 change (opener clean 3:1 instead of mid-melt) is in 5-6 posts so far: 129, 51, 46, 41, 38, 15. Not
  visibly better; too early.
- Length: ≤10 s 76 views/0.35 completion; 10-20 s 51/0.17; 20-35 s 48/0.13.
- Learner: 17 posts, 7 knobs, 2-6 options each. Nothing learnable yet; every weight 0.90-1.10.

### Content audit
- The renderer is strong (surveyed clips, real bar lines, macroblock melt, seamless loop, clean opener). The problem
  is what is in the frame: soft 1950s Prelinger copies and silent-era shots of people nobody knows, in a `rec`
  timecode frame. At phone size, a melting grey crowd reads as "corrupted file", which is what the captions say
  ("tape found in a creek", "this file should not play"), and viewers treat it as one.
- Caption bank: good voice, no asks, but no caption names the film or the subject. The one caption that did ("a
  hundred-year-old film, taken apart on the snare") sat on a water clip at 38 views.
- Song credit as elsewhere; on screen only the credit line.
- Niche: consistent (every post is a mosh); a follower knows what they'll get, which is the same thing.
- Cadence: 5/day for an account 4 days old. Nov 25's 7 posts: one batch.
- Rules: the renderer re-checks `footage.BLOCK` and skips talking heads, sponsors, logos (Nov 24 pass). OK.

### Research
- Mainstream datamosh in 2025 is a **transition**, not a look: CapCut/Premiere "datamosh transition" templates, phonk
  edits, "eye transition" trends ([capcut](https://www.capcut.com/explore/datamosh-transition/7497635808041322497),
  [epidemicsound](https://www.epidemicsound.com/blog/how-to-datamosh/), [tiktok #datamosh](https://www.tiktok.com/tag/datamosh?lang=en)).
  The melt is the half-second between two shots people *want* to see; 15 s of melt is the thing nobody asked for.
- The glitch-art community (#glitchartistscollective, @datamosh) is small and tool-centred
  ([wikipedia list](https://en.wikipedia.org/wiki/List_of_glitch_artists)); no 2025-26 account rankings surfaced.
- Originality: a mosh of PD footage is a material transformation, so the April 2026 rules are satisfied; watch it anyway
  (traps.md already says so).

### Recommendations
1. **Footage first: space/NASA and our own clips only, for two weeks.** `nightly.yaml` glitch `retire: {source:
   [water, nature, archive, city]}` and add a theme for Nick's NYC clips (`studio/footage/inbox/nyc.txt`, our own
   footage, allowed on niche accounts) and the Rocket League library (also ours). A rocket launch or a goal melting on
   the snare is a recognisable thing breaking. quick (yaml) / medium (new source themes in `glitch_video.py`).
   Measure: batch share vs 4/17.
1b. **Let the first shot happen before it melts**: with `pace 1` the rocket in the contact sheet is cut before
   lift-off. First cut no earlier than the second bar; `pace 2` by default; `tone` natural/night (duotone and
   thermal turn a launch into mud). quick (knob defaults / retire).
2. **Name the thing on screen in the first second**: the `rec` label already knows the film title; promote it to a
   one-line top title for 2 s ("Apollo 11 launch, 1969" / "Coney Island, 1905") and lead captions with it. The
   "did you know this film exists" framing you asked about is the right instinct, and it is cheaper than a pivot:
   the index already carries title, year and source. quick/medium. Measure: skip rate vs 84%.
3. **Mosh as a transition, not a bed**: pace 2 (two-beat melts) already beats pace 1; go further with a `main` option
   "clean" where the picture plays clean and only the cut melts (16-24 frames), so the clip reads as footage with
   glitch transitions. medium. Measure: watch time and completion.
4. **2/day, ≤12 s.** `posts_per_day: 2`, `join: 20`. quick.
5. Retire `accent rgb` (views without any keep) and `main track` (38 median, 5 posts) by hand. quick.
6. Trial reels on. quick.
7. Merge question: see §7 at the end.

### Risks
- Same PD library as vintage (which got an originality notice) and cinema: three accounts on one token posting
  transformations of the same films within hours of each other is a pattern a classifier can see.
- `mixed` includes `archive` (Prelinger sponsor/educational films) where a stray logo or caption can slip through
  the SKIP lists.

---

## 4. @vintage.media.archive (vintage_archive; pre-1931 film as an old print, now ink line art)

**Verdict: rethink.** The lowest watch time in the network (2.27 s, 83% skip) on footage Instagram has already
flagged as unoriginal. The lever is a reason to watch (a fact about the film) or merging into ascii.cinema.tty.

### What the numbers say
- 15 posts, median 72, 11 of 15 under 3 s watched. Batches: Nov 23 1/2, Nov 24 3/6, Nov 25 2/6, Nov 26 0/1.
- Paused Nov 25 after the originality notice; back the same day as ink line art (`look=ink`, `pen brush`), 2/day.
  Since: 114 (night·none, 19:41), 7, 17. Three posts: unknowable yet.
- Knobs (n=15, all confounded with date): tint night 114 / sepia 115 / rose 95 vs amber 17; crank 2: 105 vs crank 1:
  28; gate iris 105 vs rounded 12; trip double 104 (n=6); pace 2: 112 vs pace 1: 19; cards lower 114 vs none 45 vs
  full 28 (but full cards watched 4.85 s). The weights file points the other way on several (rounded 1.06, pace
  beat2 1.06): that is the learner reading noise.
- Length: 20-35 s cuts got the most views (84) and the least completion (0.11); ≤10 s 69 views, 0.32.
- Saves 1, shares 2 in 15 posts: nobody keeps or sends these.

### Content audit
- Frame 0 is the clip with "most movement × contrast in its first half-second"; on 1900s footage at phone size that
  is a grey crowd. The strip layout (three small frames) was already found to skip at 82% and demoted; `fill` is
  better but still "old film, no idea what". A slate with title and year exists as a knob (`slate on`, learned
  1.06) and should be always on and bigger.
- Captions are the best-written bank in the cluster ("these films were made to be played with a live band. here is
  ours", "the pianist called in sick") but none names the film; the data shows the plain "{song} – Close Quarters"
  captions did as well as the clever ones.
- Song credit: as elsewhere. The "played with a live band" line is a genuine angle for crediting the band.
- Cadence: 6/day on days 2-3 of the account's life, then the notice.
- Rules: 1906 Veil Dance blocked, trademark cartoons blocked; the library is 7 films (Nov 24), so repetition is
  the next problem.

### Research
- Old footage goes viral when it is **recognisable and framed as a comparison**: Shiryaev's 1911 New York (upscaled,
  colourised, "this is what it looked like") ([nvidia](https://blogs.nvidia.com/blog/2020/10/23/ai-startup-enhances-video),
  [boredpanda](https://boredpanda.com/1911-footage-new-york-city-colorized-ai-high-resolution-denis-shiryaev)). The
  Library of Congress itself frames kinetoscope clips as "the Reels of the 1890s" ([loc.gov](https://blogs.loc.gov/families/2022/03/were-kinetoscopes-the-instagram-reels-of-the-1890s/)).
  Nobody found a 2025 account winning with *unframed* silent film cut to music.
- Originality rules (April 2026): a filter or line-art pass is a "low-effort edit" risk; added narration/graphics/
  commentary is what Meta names as material ([techcrunch](https://techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/)).
  A fact card is both the hook and the originality fix.

### Recommendations
0. **Fix the opener and the cut rate first** (medium, `vintage_video.py` `Plan`): never open on an abstract film
   (Ballet Mécanique / Emak-Bakia / Rhythmus / Lichtspiel), ≥2 s a shot in the first bar, at most two films per
   video. The contact sheet shows six films in ten seconds opening on an abstract shape; no fact card can save that.
1. **"Did you know this film exists" format** (medium, `vintage_video.py` + a small facts file per film in the footage
   index): frame 0 = ink still + one line ("the first film shot in New York at night, 1905" / "Méliès blew this up by
   hand, 1902"), 2 s, then the cut. Facts only from the index/source page; no invented years. Measure: skip vs 83%,
   saves.
2. **Slate always on, in the top safe area, for the first 2 s, title + year** (quick: force `slate on`, move it up).
3. **≤10 s only, 2/day, trial reels on** (quick). `join: 12`.
4. **Retire tint amber, pace 1, gate rounded, strip layout by hand** until n > 50 (quick, `nightly.yaml`).
5. **Or merge** (see §7): fold vintage's films into ascii.cinema.tty's dream/comedy reels and stop posting here. The
   library is the same, the audience is the same, cinema already gets batches on half its posts.

### Risks
- Already one originality notice. The ink pass may or may not satisfy "material edit"; a second notice likely ends
  recommendation for 30 days. Facts/graphics on screen is the defensible path.
- Seven films: repetition across vintage, cinema and glitch (same copies, same shots) within days.

---

## 5. @ascii.cinema.tty (ascii_cinema; public-domain film as type in a terminal)

**Verdict: on track for reach, needs work for watch.** Half its posts get tested (median 109, flat day to day), but
2.6 s watch/79% skip. The lever is naming the subject on screen and in the caption, which its own numbers already show.

### What the numbers say
- 14 posts, median 109, batches 4/8, 4/4, 1/2 (the steadiest in the cluster after ascii.terminal.dreams). Saves 10
  (rocket launch 3, phosphor Fixation 2).
- **Captions that name the subject win**: "a rocket launch, played back as letters in a terminal" 206 views/4.4 s/3
  saves; "the earth from orbit, in green terminal dots" 127; vs "cinema, typed out" 9, "no pixels. only characters"
  39, "an escalator ride, redrawn as 5,850 coloured letters a frame" 71 (named, but an escalator). Weights agree:
  rocket launch 1.08, earth 1.07, escalator 0.93.
- crt on: 118 views/3.07 s vs off 107/2.33 s. cell 14: 3.43 s vs 12: 2.28 s (bigger letters read better at phone
  size). look: phosphor/amber 112-115 vs colour 83; reel: dream (Nosferatu) 125 vs comedy (Speedy) 97, n=1 each.
- Length: ≤10 s completion 0.31, 10-20 s 0.15; views equal. 
- Hour: 20:00-22:00 NY slots 99-206; 13:00 and 18:00 slots 9-39 (n tiny).

### Content audit
- Frame 0 is mid-action (good), typed in (good), seamless loop (good). Text is `$ play nosferatu_1922.mp4` and the
  credit *under* the picture, small, green on black. Nothing above the fold says what you are looking at; the
  terminal conceit is clear only to people who already like terminals.
- Caption bank (15): all about the technique ("every outline is a slash"), none about the film. The two winners were
  hand-written subject captions that are not in the bank.
- Song credit: standard; the `$ play` line could just as well read the song.
- Niche: consistent (ASCII cinema). Cadence 5/day from day one; the Nov 24 8-post day still got 4 batches, so
  this audience tolerates it better than psy's did.
- Rules: SKIP list + `footage.blocked()`; films alternate; no logos. OK.

### Research
- The ASCII/terminal audience is the creative-coding audience (play.ertdfgcvb.xyz live-coding ASCII,
  [holo.mg](https://www.holo.mg/stream/andreas-gysin-ascii-live-coding-playground/), [korben](https://korben.info/en/ertdfgcvb-live-coding-ascii.html));
  the "code scrolls under the scene" format is recognised as a reels style
  ([github terminal-art](https://github.com/topics/terminal-art)). ascii.terminal.dreams' 86 saves come from exactly
  that audience; cinema shows none of the code.
- Reels with a named subject + a "played back as X" claim are the format that got batches here; generic "it's all text"
  is not (same finding as glitch and vintage: the footage must be *about* something).

### Recommendations
0. **Open on a face or a figure, never on an abstract film** (medium, `cinema_video.py` opener scoring: a per-film
   `subject` flag in the SKIP/film table, abstract films allowed only after the first bar). The dream reel's
   contact sheet opens on Ballet Mécanique shapes and shows Nosferatu's face only at 5 s.
1. **Top title for 2 s on frame 0**: "Nosferatu (1922) as text" / "Apollo launch, in 5,850 letters a frame", inside the
   safe area at y≈300, then it fades; and rewrite the caption bank so line 1 is `{film} ({year}), {what it is}, played
   back as letters`. The title and year are already in the footage index. quick/medium (`cinema_video.py` draw +
   `captions.txt` with a `{film}` field). Measure: skip vs 79%.
2. **Lock crt on and cell 14** (quick, `CQ_KNOBS` defaults or retire `cell 12/18`, `crt off`).
3. **Show the code**: a 6-line panel of the real letter ramp / DoG-stroke code under the picture (the terminal is
   already there) is what earns saves on the sister account. medium.
4. **Prefer launch/dream reels** (rockets, Earth, Méliès, Nosferatu) over comedy until comedy proves itself; the launch
   reel "needs clearer rocket footage" (styles.md): NASA's library (space theme) is PD and sharp. quick.
5. **≤10 s loops**, 3/day. quick.
6. Trial reels on. quick.

### Risks
- Shares the PD library with vintage (one notice already) and glitch. The ASCII transform is clearly material; keep
  it that way (no "clean" look).

---

## 6. @ascii.terminal.dreams (ascii_art; scenes and pixel worlds in letters, with their code)

**Verdict: on track; double down.** 23 of 24 posts got a batch; three went to 1,300-1,800 views; 86 saves is the most
in the network. The lever is more of the thing that gets saved (a finished, named world + visible code) and less of
the screensavers.

### What the numbers say
- Median 185, mean 383, max 1,825. Saves 86, shares 23, likes 271 (3.7% of views, best engagement rate in the cluster).
- **Saves per 1,000 views**: court 12-9, galaxy 10-29, bridge 10; subway 4; planet/jelly 5-10 on small numbers;
  aurora, daisies, boulder 0. For comparison the cluster's other accounts run 0-5 per 1,000.
- scene (views / s watched / shares+saves): court 1,047 / 5.0 / 31 (n=2); bridge 766 / 3.9 / 15; galaxy 311 / 3.9 /
  39 (3); subway 281 / 5.0 / 1; fireworks 215 / 4.5 / 3 (retired); jelly 188 / 3.4 / 6; boulder 175 / 3.7 / 1;
  planet 166 / 2.8 / 6; goldfish 197 / 2.6 / 2; daisies 154 / 3.1 / 0; aurora 151 / 2.7 / 5.
- **layout code: 184 views / 3.7 s / 59 shares+saves (n=12) vs clean: 166 / 2.9 s / 26 (n=7).** The code panel is
  worth ~0.8 s of watch and twice the saves. palette ember: 247 / 4.6 s / 52 (n=5); sunset 277 / 18; ice 182 / 8;
  scene 157 / 2. ramp blocks/classic ≈ equal; dense/texture worse. pixel_cuts bars: 1,057 vs none 225 (n=2 each:
  the bar cuts are the "it moves with the kick" moment). pixel_bg ink 1,363 vs plum 168 (n=1 each).
- **Length: the 10-20 s tight cut is where the saves are (69 saves, 13 posts, 242 median)**; the ≤10 s loops got 1 save
  in 4 posts; 20-35 s 16 saves/6 posts. This is the one account where shorter is *not* better: people save a finished
  scene they watched build.
- Hour: the three big ones went out 20:46-22:41 NY on Nov 23 (also the night everything was fresh); 20:00-22:00
  slots median 751-1,825 vs 145-213 the rest of the day. Worth a real test, not a conclusion.
- Captions: the three 1,300+ posts had the three most specific captions in the bank ("a clay tennis court built from
  voxels, all of it code. every shot lands on the beat. sound on."); generic ("3D, but it's only text") 145-311;
  "send this to someone who writes code" (an ask, since removed) 183-213.
- Learner: with 24 posts it has found the right thing (court/bridge/galaxy 1.06-1.07, daisies 0.93) but the
  `WEIGHTS` in `ascii_video.py` still give aurora/daisies 2 each and planet/boulder/jelly 1 each (7 of 32 draws on
  scenes that never got a save).

### Content audit
- Contact sheet (`archive/ascii_small.jpg`, subway world, night sky, clear): frame 0 is a dark isometric platform
  under a moon, the train already entering; by frame 60 (2 s) it is in the station; by 300 the doors are open and
  "riders" print lines. That is a reveal with a question answered by watching (what arrives?). The code panel
  (`subway.py`, `def world()`, `def train(song)`) is real but **unreadable at phone size** (I could not read it at
  1800 px wide; on a phone it is texture). The status line "voxels 11,980 · train: arriving · off 0 on 0" is
  readable and true.
- The losers (aurora, daisies, planet) have no object and nothing arrives; galaxy is the exception because it
  resolves into a spiral.
- Captions: the bank is clean and on-voice; make line 1 always name the scene (it is a knob, so `{scene}` is known).
- Song credit: `♪ talk — close quarters` top-left in the terminal chrome from frame 0 (readable). Good; the only
  account in the cluster where the song is on screen in the first second.
- Niche: "creative coding / ASCII / pixel worlds" is coherent as long as the code panel stays. 5/day is working
  here; do not raise it.
- Rules: no footage, no asks (one old "send this to someone who writes code" caption in the data, now gone).

### Research
- Saves are a reference/utility signal ("educational, how-to and reference content drives saves far more than purely
  aesthetic content", [getimg](https://getimg.ai/blog/guide-to-making-ai-art-go-viral-on-social-media)); people save
  what they might want to make or come back to. The creative-coding audience (ertdfgcvb's ASCII playground,
  [holo.mg](https://www.holo.mg/stream/andreas-gysin-ascii-live-coding-playground/); #creativecoding/#generativeart as
  the leading hashtags, [best-hashtags](https://best-hashtags.com/hashtag/creativecoding/)) saves code. That is why a
  readable code panel, "pause it", and "the numbers at the top are real: counted from this frame" work here, and why
  the wallpaper-like scenes (aurora, daisies) do not: they are pretty, but there is nothing to take away.
- Loops/replays count ([techbullion](https://techbullion.com/loop-your-way-to-growth-a-smarter-instagram-strategy-for-2025/)),
  but this account's data says a 10-20 s build beats a 7 s loop; keep the build.

### Recommendations
1. **Retire aurora, daisies, planet in `nightly.yaml`** (`retire: {scene: [aurora, daisies, planet]}`) and reweight
   `WEIGHTS` toward wild/court/bridge/galaxy/subway/hoops. quick. Measure: saves per 1,000 views (now ~9 overall).
2. **Make the code panel readable on a phone**: 6-8 lines at 2x the current size, the function that is running right
   now highlighted (the engine knows: `train()` while the train arrives), the status line kept. The code shown must
   stay the code run. medium (`pixelviz/engine.py`, `asciiviz/engine.py`). Measure: saves and watch (code layout is
   already +0.8 s).
3. **Caption line 1 names the scene and one true number**: "{scene}: {voxels} voxels, every one placed by code. the
   train arrives on the first kick." quick (`captions.txt` with knob fields).
4. **Keep 10-20 s tight cuts; stop rendering ≤10 s for ascii** (`cut` knob: retire `short`). quick.
5. **Test the evening slot**: `start_hour: 15`, `end_hour: 23` for two weeks (or weight 20:00-22:00 in topup). quick.
   Measure: median views per slot.
6. **More pixel worlds with an arrival** (backlog already lists this): a drive-in where the film starts, a lighthouse
   that lights on the chorus, a bridge that raises on the bar: every world needs the one event the viewer waits for.
   large.
7. **Trial reels on** here too; the account's follower base is new and matches the content, so the risk is low and the
   non-follower test is what the big three got anyway. quick.
8. Ember palette, bars cuts, ink background as defaults for pixel worlds. quick.

### Risks
- Nothing rule-related. The one risk is volume: 5/day works because almost every post gets tested; raising it is the
  psy mistake.

---

## 7. Should glitch, vintage and cinema merge?

Yes, two of them. All three draw on the same 7-film + Prelinger + NASA library on one token, and the data says the
library's films are not the draw: the batches went to **rockets, Earth from orbit, NASA, and whatever was named**.
Proposed:
- **ascii.cinema.tty** keeps the silent films (dream/comedy reels) *and* takes vintage's "did you know this film
  exists" cards; vintage.media.archive stops posting (set `paused: true`) or becomes the carousel/fact page for film
  history if carousels ever reach anyone (they don't now).
- **glitch.archive.exe** drops the silent/archive film sources entirely and becomes the NASA + our-own-footage mosh
  page (space, Rocket League goals, Nick's NYC), with mosh as a transition.
- Both at 2-3/day, ≤12 s, trial reels on, a 2 s title on frame 0.
This halves the PD-film exposure on the token, removes the account with the originality notice from the feed, and
concentrates the films on the renderer that transforms them most (ASCII) and gets tested most.

## 8. Cross-cluster quick wins (one PR)
- `accounts.yaml`: `trial_reels: true` on all six (the brief's "new accounts spammed at 5/day" is exactly what trial
  reels were built for: [about.fb.com](https://about.fb.com/news/2024/12/trial-reels-try-content-non-followers/)).
- `nightly.yaml`: psy `join 20`, glitch/vintage/cinema `join 12-20`, ascii keep 30; retire lists above.
- `publish.yml`: carousel job → nostalgia only (or off); factreel job → nostalgia + non-drug psy specs only.
- Every renderer: a 2 s top line on frame 0 that names the thing (film+year, scene, "a face appears on the drums")
  inside y 250-420; the song title on screen in the first 2 s (ascii already does it in the chrome).
- Per-account post spacing: no two posts within 60 minutes on one account across all jobs (traps.md notes the
  double-post; psy had 62/88 posts within 45 min of another).
- `learn.py`: until n≥50 per campaign, publish only the hand-retire lists and treat weights as display, not as
  Thompson input (set `EXPLORE` high or freeze knobs to the defaults named above).

## Contact-sheet note (all six rendered and looked at; `scratchpad/archive/*_small.jpg`)
- **vintage** (`talk` 23-38 s, seed 5: ink, amber, fill, cards full, slate on, pace beat2): frame 0 is *Ballet
  Mécanique*, an abstract "0" shape in woodcut black-and-cream with the slate "Ballet Mécanique 1924" readable at the
  top. Then Le Monstre at 1 s, The Haunted Castle at 2 s, Nosferatu at 5 s, Highway 101 at 10 s: **six films in ten
  seconds, one shot each**; nothing stays long enough to be seen, and the opener is the one film in the library with
  no recognisable subject at all. The opener score (motion × contrast) rewards abstract avant-garde films, which is
  the opposite of what a viewer needs. Fix: exclude the abstract films (Ballet Mécanique, Rhythmus 21, Lichtspiel
  Opus, Emak-Bakia) from the opener slot and from the first bar, one or two films per video, ≥2 s per shot.
- **cinema** (seed 5: dream reel, phosphor, cell 14, crt off): the same thing. Frames 0-1 s are Ballet Mécanique as
  green letters (abstract shapes nobody can name), The Lost World at 2 s, Nosferatu's face only at 5-10 s. Its
  opener score (motion × contrast × outline) has the same bias. Nosferatu's face should be frame 0; a face in the
  first second is the single most-cited retention factor ([metricool](https://metricool.com/instagram-reel-analytics/)).
  The `$ play ballet_mecanique_1924.mp4` line is tiny under the picture; nothing names the film where the eye starts.
- **glitch** (seed 11, forced `source space, main mosh, opener clean`; duotone, pace 1, label rec): frame 0 is an
  Antares rocket on the pad, recognisable; by 1 s it has melted into a Titan II; Earth at 5 s, aurora at 10 s. The
  `SRC Launch Replays of Antares Rocket...` line is unreadable mono text under the top bar. Duotone turns the launch
  to mud. With pace 1 the rocket is gone before it lifts off; the thing worth watching (ignition, lift-off) never
  happens because the cut comes first. The unforced render (seed 5, default sources) **crashed** in `melt_step` →
  `cv2.remap` with an empty source (OpenCV 5.1.0 here; `glitch2.log`/`glitch.log` have the trace): one clip's
  cached frames came back empty. Worth a guard in `Footage.frames()` (skip a clip whose read is empty) since the
  nightly job's OpenCV may differ.
- **psy / liminal / ascii**: described in their sections.
