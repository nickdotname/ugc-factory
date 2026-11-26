# Log

Back to [[README]]. Newest first; one line per change worth remembering.

- 2026-11-24: quality passes merged for ascii.terminal.dreams (#134: `asciiviz/letters.py` typesetter, footage scene
  `wild`, painted skies and weather for the pixel worlds, `subject-*` clip prompts for Kaggle, fireworks retired) and
  psychedelic.station (#135: kick punch, fewer overlays, readable fact reels, facts corrected, no follow-asks). Its mix
  then changed: visualisers 10 → 8 a day (8 a night made), collage dropped, carousels 4 → 1 a day, fact reels stay 4.

- 2026-11-24: @moth.ate.my.notes posts (campaign `notes_app`, style `notes`, `studio/text_video.py`): text-on-
  gradient reels in the look of Instagram's own text posts, from references Dylan sent. 78 thoughts of our own in
  `studio/notes/lines.txt` (add at the end; five are used a night, so the bank needs topping up about every two
  weeks). No song label on the card. 8bit.tests was paused the same day ("way too basic") pending a rebuild.

- 2026-11-24: @8bit.tests added (campaign `pixel_tests`, style `tests8`): the play-along pixel tests that
  math.explainers never chose, in a fuller room (a boombox whose cones follow the kick, a rug, books, a plant, a
  second creature). @moth.ate.my.notes is registered (`notes_ig`, `IG_TOKEN_4`) with no campaign yet. Both have no
  Facebook Page (Unified login).

- 2026-11-24: @algorithm.races added (campaign `algo_races`, style `race`, `studio/race_video.py`): the sorting and
  maze races move there from math.explainers. First account with **no Facebook Page**: Dylan's profile could not
  create Pages and Nick was away, so the app was connected to the Close Quarters business portfolio and the account
  added as an Instagram tester through Meta's Unified login; it has its own token (`IG_TOKEN_2`). `ig-check.yml`
  (`scripts/ig_check.py`) says which accounts each token reaches. Comment replies use each account's own token.
  See [[playbooks/add-account]], "Without a Facebook Page".

- 2026-11-24: the ASCII colour scenes were "not hi-def enough" next to other ASCII pages: 180 x 108 letters at
  6 x 11 px are specks on a phone, on a mostly black frame. Now 108 x 66 **bold** letters (10 x 18 px), short
  heavy ramps so one brightness is a run of one letter (`CRAMPS`), shaded parts hatched along their slope
  (`//// ||||`, `HATCH`), a dot grid on empty cells (`DOTS`), and a halo behind the letters instead of a blur over
  them. goldfish.py is redrawn for it: three koi (one fills the page) with white patches, a forked tail, eyes,
  and water made of letters; its tail was also on the wrong end (in front of the head) and is now behind. The four
  older colour scenes get a smaller canvas (`ZOOM`) so their subjects cover as many letters as they were drawn for.

- 2026-11-24: a post could be sent twice (tiny.code.loops and psychedelic.station today, three accounts on
  Nov 21). `publish-due` now reads the branch as it is, claims each post on the branch before sending it and
  records each result as soon as it is out. See [[traps]], "The same post sent twice".

- 2026-11-24: rotation.illusions gets two more kinds and a shape, from reels Dylan sent as inspiration: `group`
  (twelve dots that are three turning squares and four turning triangles at once), `stripes` (static diagonal
  stripes under sliding discs that swap black and white) and a tilted donut. Our own versions and wording. The
  other formats he sent are in [[backlog]] with the account each belongs to.

- 2026-11-24: the "Install ffmpeg" step hung for 15-20 minutes on four jobs in one night (a studio run and three
  render legs), which would have stalled a nightly run until its 170-minute limit. Every workflow now installs
  through `scripts/apt_install.sh`: a time limit per try, three tries, no man-page index rebuild. See [[traps]].

- 2026-11-23: more posts, earlier. Niche accounts go from 3 to 5 a day (retro 4), nostalgia 6, close__quarters and
  dylancantor23 8, psychedelic.station 10; every window now opens at 8 or 9 (several opened at 11–13, so mornings
  were empty). The studio makes 5 a night per niche account to match. topup now treats a day as full once the
  account holds posts_per_day posts on it: slots were only checked minute by minute, so a changed grid would have
  stacked new posts on top of the days already booked (hand-timed lineup posts are exempt; a campaign with a
  `buffer_share` is limited by that instead). Nightly studio time will grow; its limit is 170 minutes.

- 2026-11-23: new account @rotation.illusions (campaign `illusions`, style `illusion`), on the Page "Rotation
  Illusions" that Nick made and shared. Three a day from 8:20. Three more Pages are coming from Nick (8-Bit Tests,
  Algorithm Races, Notes App Thoughts): one account each, when their formats are ready.

- 2026-11-23: two more pixel worlds for ascii.terminal.dreams. `hoops`: a pickup game on a blacktop court, one
  bounce per kick or snare, the shot leaves on one hit and drops on the next. `subway`: a platform cut open (the
  wall reads 8 ST - NYU); the train stops on a bar line, one rider off or on per beat, it leaves on another bar
  line, then a rat moves on the hi-hats. Checked on all 15 songs at 7 s and 17 s. A new world is one file in
  `studio/pixelviz/` (build, setup, dynamic, stats, CODE) plus its name in `ascii_video.py`.

- 2026-11-23: the pixel worlds (bridge, court) are back on ascii.terminal.dreams, about a third of its videos.
  They were removed that morning as "not ASCII", but they were two of the account's three most-watched posts
  (1,261 and 1,130 views, longest watch time, most shares), so they stay there; no separate pixel account for now.
  Next: more worlds, so the same two don't come round too often.

- 2026-11-23: fact reels stopped (20:45 run): the newer carousel specs give each slide a third field (its
  pictures) and `post_factreel.py` unpacked exactly two. It now ignores anything after the heading and the text.
- 2026-11-23: ascii.cinema.tty and digital.petri.dish go live: three hand-timed first posts each tonight
  (`lineup.yaml`), then the usual three a day. Two captions corrected to match the videos (the petri sim has
  140,000 agents, not 200,000; ascii cinema's footage is not always a century old: NASA and CC0 clips too).

- 2026-11-23: two new accounts, @ascii.cinema.tty (campaign `ascii_cinema`, style `cinema`) and @digital.petri.dish
  (`petri_dish`, style `alife`). Dylan's profile had hit Facebook's Page limit, so Nick made the two Pages on his
  own profile and gave Dylan full control. They start at 8 and 9 in the morning, earlier than the other niche pages.

- 2026-11-23: the.loose.change's memes keep running, with less repetition: 4 a day (was 6), a clip rests 3 days
  (was 0; 15 clips had made 60 posts, one of them 11 times in a week, while median views fell from 500-870 to
  11-32), and the "tag the friend who needs..." overlay line is gone (bait). Still open: the clips themselves are
  not our footage (see the band review); rebuild them on footage we may use. Also: files left open in
  dash_data.py and replies.py failed the tests at random under CI (`filterwarnings = error`); closed properly.

- 2026-11-23: the.loose.change's schedule. Buffer holds ten posts for a channel; `closequarters` (memes, 6 a day)
  was topped up first and filled all ten, so `nick_studio` (type videos) read "full" on every run and almost never
  posted. Each campaign now has a share of its own (`posting.buffer_share`: 6 and 4). The dashboard was missing
  half of what Buffer held, because queue.json forgets a pushed item at the next render: topup now records the
  campaign's own posts waiting in Buffer (`campaigns/<c>/backend_queue.json`) and the page shows them, and videos
  rendered but not yet offered to Buffer show as waiting.
- 2026-11-23: from the account review. psychedelic.station's `star` motif drew a six-pointed star when the symmetry
  was 3, 6 or 12; it now has eight points in those cases. "Rate this 1-10" lines removed from the hook menus and two
  caption banks (a comment-ask is bait; open questions and the hot takes stay).
- 2026-11-23: physics.bounce.lab reworked after "the recent physics bounce is really bad": the box shrank to a
  third of the screen and nothing built up. Circle and square now fill the screen and follow a `rule` (grow, lines,
  multiply) stated in frame 0, the ball flies in from the first frame, the credit and counter sit above Instagram's
  buttons, and two captions that claimed "real physics / gravity, friction" (it is a straight path between notes)
  were reworded. retro.vibes.arcade gets a `hook` line over the picture (spot / smoke / memory), places numbered for
  the questions. Footage styles on close__quarters now give the song with the fewest videos its turn first.

- 2026-11-23: two things stopped Notta Problem's footage videos after #107. (1) Its dance clip sits at 99–150 s
  and the song's stems stop at 100 s (as do Evil, Silver and Gold, Subway Maintenance: only their first half was
  prepared), so every window read as silent and was skipped; now footage past the stems is accepted and
  `beat.stretch` lets the master stand in for a stem that does not reach. (2) A studio run that began with four
  lyric renders broke librosa's compiled cache (segfault in `peak_pick` for every render after); nightly now
  builds that cache once, alone, before rendering. See [[traps]].

- 2026-11-23: band footage. Notta Problem's dance clip starts where song.json's sections end, so the studio never
  offered it: footage styles (lofi, cutout) now also use stretches inside the footage itself. close__quarters favours
  those clips 3x within a song (`selection.favour_styles`), and a song with unposted footage clips comes up 3x as
  often. `cutout` can stand the band in front of library footage graded to its palette, and moves on springs.

- 2026-11-23: dashboard accuracy. Metrics were on GitHub's cron, which skipped 2026-11-23 entirely, and the
  newer accounts had never been measured: now publish.yml starts metrics daily (06:30 UTC) and Instagram-only
  every 3 hours; IG-only campaigns no longer spend Buffer requests on it. The page lists unbooked renders apart,
  says how old each post's numbers are, shows failures and carousel pictures, treats "publishing" as booked, and
  names the song from the outbox when history doesn't. Found while checking: before the held-slot guard (#97
  era, 22:39 ET 2026-11-22) accounts were often booked twice into one minute; none booked since.

- 2026-11-23: the "share" hook angle is gone from studio/hook.py ("send this to your duo", "save this for your next
  session"...): those are tag-a-friend asks. "your sign to start a band" moved to relatable.

- 2026-11-23: caption banks. Songs without a bank of their own (the 7 added later, and every song on nyc and
  vintage) fell back to one line per campaign, so those posts read the same every day; each campaign's
  `captions.txt` now holds 22-40 song-agnostic lines. Every niche account has 25+ distinct openings, so the 7-day
  opening-line cooldown can hold. "send this to…", "save this for…" and "wrong answers only" lines removed.
  cq_producer's fallback named Notta Problem on every song: fixed, plus 3 queued dylancantor23 posts and 6 queue items.

- 2026-11-23: @tiny.code.loops live (Page "Tiny Code & Generative Art", campaign tiny_code, style tinycode, 4 a
  night). ASCII Cinema & Film and Digital Petri Dish wait on new Facebook Pages: Facebook refused more Pages from
  Dylan's profile that day ("created too many Pages recently"). The pixel bridge and court are off @ascii.terminal.dreams.

- 2026-11-23: fresher posts. Within a night's batch an account plays each song once before any repeats, and
  songs it posted in the last day are picked a quarter as often. A caption's opening line isn't reused on the
  same account for 7 days while unused lines remain (`LINE_COOLDOWN_DAYS` in `src/selector.py`). Bait lines
  ("tag a...", "comment it", "drop a 🎧") removed from the banks and hooks; ~70 new opening lines added for
  psy_station, cq_band, cq_producer and nostalgia. Dashboard: a rendered video whose minute went to another
  post shows "waiting for a slot", not OVERDUE.

- 2026-11-23: `studio/replies.py` answers "what song is this?" under our Instagram posts with the song and
  @close__quarters (once a quarter hour from `publish.yml`; 3 a run, 6 an hour, 30 a day per account; nothing
  else is answered). Needs `instagram_manage_comments` on IG_TOKEN. Loose Change (Buffer) is not covered.
- 2026-11-23: repo brain (`CLAUDE.md`, `docs/brain/`). The three instrumentals get `prep_instrumental.py` (#92).
  NYC facts checked; own-clip inbox (#94). Fission for math.explainers (#93).
- 2026-11-23: @vintage.media.archive and @nyc.daily.aesthetic created, made Creator, linked to new Pages under
  Dylan's Facebook, granted to the app (opt-in to all current and future Pages / IG accounts); IG_TOKEN refreshed.
  Renderers `vintage_video.py`, `nyc_video.py`; footage themes `silent`, `nyc` (#90, #91).
- 2026-11-23: render moved after studio (08:30 UTC); topups at 09/15/21 UTC (#89). Four songs added:
  Notta Problem, Subway Maintenance, Silver and Gold, Evil Close Quarters (#88).
- 2026-11-22: publishing every 5 minutes via the Cloudflare Worker (#82); first comments credit the song (#84);
  topup avoids minutes already booked (#85); exhausted creatives and too-short clips no longer fail a run
  (#86, #87); dashboard: profile pictures, Clubs filtered, "uploading" state (#81, #83); dashboard locked to
  Dylan and Nick with Cloudflare Access.
- 2026-11-22: Rocket League library at 17 clips.
- 2026-11-13: EDUCATION released.
- 2026-11-24: @8bit.tests rebuilt (PR #137) after Dylan's "way too basic and weird". The flashes and read tests in the empty room are replaced by five play-along tests built from the song's hits: pause when it fits (4/2/1-frame windows with a frame counter), follow the gem, watch the order, count the fireworks, and early or late (the last landing moved 3-4 frames, revealed in ms). Drawn in new 2D parallax pixel worlds (`studio/mathviz/pix8.py`: city rooftop, moonlit forest, crystal cave) with reactive lights, particles, bloom and optional scanlines. Hits come from the Ableton project where a song has one, else the drum stem. New knobs `test`/`world`/`crt`, new caption bank. Frames and a full render reviewed; the campaign and nightly target are back on.
- 2026-11-24: nostalgia.hub.vhs quality pass (PR #138). Liminal reels had median 55 views, 76% skip and 0 shares; the fact reels and carousels were what people watched and sent. `liminal_video.py` now weights childhood places drawn in code: playplace (ball pit), rink (cosmic carpet, mirror ball on the drums) and lab (CRTs after hours); office and parking dropped. Every place gets corner shading, reflections, stains, a camcorder bob and tilt, tracking tears on drum hits and exact loops, plus a memory line held from frame 0 inside the safe area. Fact-reel cards now show on frame 0 (the cover used to be blank). Carousel specs name their reel's room (`place` -> `CQ_PLACE`). Engagement asks removed from the carousel end slide and captions; caption bank rewritten.
- 2026-11-24: @dylancantor23 producer style rebuilt (PR #139) after a median 22 views, 3.5 s watch and 68% skip. The scrolling-waveform view (`scroll`, off the menu) is replaced by two stem stories with audio rebuilt from the stems: **build** (one part alone, the rest unmuting on the bar, then FULL MIX) and **strip** (full mix, one part alone, all back in), drawn as a clean DAW with M/S buttons, entry flashes, a label, a master spectrum and meter. New settings `story` (build/strip) and `first` (Vocals/Drums). Caption bank rewritten to statements only (question captions had the lowest views). Stems are still 22 kHz demucs splits; real stems from the Ableton projects are next.
- 2026-11-24: the.loose.change type style rebuilt (PR #140). `studio/type_video.py` is now a two-ink print: each line sits on the page as outlines and every word is inked as it is sung, so frame 0 is always a lyric. Layouts are block (justified poster rows), scroll and slam (the giant word is the line's last strong word, never 'and'/'you'). A cropped echo of the line's biggest word behind, a typeset header and credit, riso/photocopy texture, the spot ink jumping out of register on the snare, the page leaning in on the kick. All text inside the safe area. Stack, split and the title card retired. Lines under line_conf 0.5 ink at once; placeholder words past the vocal stem are dropped. nick_studio captions rewritten (no y2k lines or share-asks). Found: the account's meme reach collapsed after 11-20 (median 171 -> 18), likely clip reuse plus engagement-bait captions in the shared `closequarters` campaign; that is fixed in the close__quarters pass.
- 2026-11-24: vintage.media.archive quality pass (PR #141). `vintage_video.py` defaults to a new `strip` layout: a 35 mm strip on a light box showing the whole 4:3 frame, the next shot rolling into the gate on alternate cuts (`fill` kept as a knob). Clips are read once and cached: the films' own intertitles, black frames and baked-in bars are skipped, each cut uses the clip's liveliest stretch, the opening shot is picked for motion in its first half-second, films alternate and the last cut loops into the first. At most 2.2 s per cut, a `slate` knob shows the film's title and year, the iris no longer opens from black, all text inside the safe zones. The 1906 Veil Dance is in `footage.BLOCK` (reads as nude at phone size); the `dance` and `Felix the Cat` silent queries are removed. Library size (7 films) is now the limit.
- 2026-11-24: retro.vibes.arcade quality pass (PR #142). The transition knob is now `trans` (as `cut` it was overwritten by nightly's length knob and never learned). Frame 0 opens on a moving clip, short clips are slowed instead of reversed, the last 9 frames fade into frame 0 so the reel loops, bloom eases off bright pictures, OSD and hook stay inside the safe area. The media-player frame and the `smoke` hook are retired; `spot` runs one bar per place. `studio/retro/rejects.json` lists clips never to use. prompts.json leads every scene with the camera move, drops the degraded-look words from `ps2`, adds `impossible` and `aero` themes, drops `menu`. `assert_publicly_readable` retries 5xx/429/connection errors (one 502 had failed the 04:00 topup). The library (24 nearly-still Wan 1.3B clips at 480x832) is the ceiling.
- 2026-11-24: retro.vibes.arcade hooks now fit the picture (Dylan: nobody "lives" on a race track). A `spot` video stays inside one theme that has 3+ places and uses that theme's line (racing: "pick your track", town: "pick the town you'd move to", ...); if no theme has 3 places yet, or the video mixes themes, the line is a neutral one ("pick a level", "pick your save file"). The "pick one to live in" line is gone from mixed videos.
- 2026-11-24: footage sources (PR #143). The silent and Prelinger queries had returned nothing: `--max` was used up by the first two or three queries, Prelinger searched only titles, the block list matched inside words like "skill" and "Essex", and archive.org gave its smallest copies. All fixed: every query gets a turn, Prelinger searches all fields with the public-domain licence in the query, `SAFE`/`HARD` sit in front of BLOCK, and the tallest copy (at least 360 lines) is picked; black bars are cropped and mostly-intertitle pieces dropped. New sources: Library of Congress pre-1931 films (`loc`, 1080p) and the NASA Scientific Visualization Studio (`svs`); Commons year categories and `source>` query routing. About 80 new queries; every clip keeps its source page, licence and year.
- 2026-11-24: glitch.archive.exe quality pass (PR #146). Every cut in `glitch_video.py` is now a macroblock datamosh melt (the old picture dragged along the new clip's motion, snapping back clean on the next beat), on the song's real bar lines. The last beat melts into the opener, so frame 0 is already mid-melt and the loop is seamless. Clips are surveyed once (`<asset>.glitch.json`): each shot plays its liveliest clean stretch, the opener is the liveliest, most colourful clip. `mixed` is only the five glitch themes (no silent films, no nyc). The renderer re-checks `footage.BLOCK` and skips talking heads, explainer captions, sponsor films, a slaughterhouse film and logo clips (`SKIP_TITLE`/`SKIP_ASSET`). track, sort and slit reworked; text out of Instagram's interface zones; four untrue captions rewritten. Soft 1950s Prelinger copies are the remaining limit (PR #143's sharper sources should help).
- 2026-11-24: close__quarters pass and the.loose.change meme fix (PR #145). the.loose.change views fell from a median 171 to 18 after Nov 20: the closequarters meme pool (15 clips shared by six songs) kept each clip's cooldown per song, so hook_05 went out 11 times in a week, and every caption was an ask. On inspection all 15 clips were ripped film/TV/game/broadcast footage or other creators' memes (Family Guy, Naruto, Star Wars, a college football broadcast...), which the house rules forbid and Instagram's 2026 originality rules punish. The clips are disabled and `closequarters` is paused until it has a library of our own clips. The clip cooldown is now kept across every song and account version (`select_batch_multi(visual_pools=...)`, 21 days, `repeats: false`); captions are statements. On close__quarters: the debate/comment opening lines are replaced by statement hot takes; band lines are flashed, never held; titles below the top 250 px; cutout opens with the cut-out centred and a no-ask hook; nightly runs band 6, lofi 1, cutout 7 (was 8/3/3) because the dance footage is what worked.
- 2026-11-24: nyc.daily.aesthetic rebuilt (PR #147). The `nyc` footage library had picked up a 2026 Manhattan political protest, a Florida rail opening, steam engines and Russian 1909-1913 films through Commons queries; `footage.fits()` now keeps theme nyc to New York and not news (in fetch, pull and purge). Modern New York comes from Pexels (`nyc_now`, ported from cq-worlds onto `sources_for`), and every clip is looked at and labelled in `studio/nyc/places.json` (place from the picture, mood, hero score, then/now pair, 13 skipped with reasons). `nyc_video.py`: walk (hero opener, mood line, place names, cinematic grade, beat cuts, seamless loop), meme on the modern city, then/now (Brooklyn Bridge 1899, East River 1903), facts readable from frame 0. Captions rewritten. Still needed: Nick's own clips in `studio/footage/inbox/nyc.txt`.
- 2026-11-24: lyric sync (PR #148). `studio/sync_check.py` measures every lyric word against the vocal stem (distance to the nearest onset, on singing or silence, against chance, whole-song lag, stem/master offset) and is the gate every lyric stretch must pass (median <= 45 ms, >= 1.4x better than chance, <= 10% on silence) in nightly, render_all and post_now. Every lyric renderer reads lines through `sync_check.load_lines`: an untrusted line appears whole, never word by word. Fixed the line picker in lyric_video, psy and cursor, which held the next line's first word back ~0.28 s on two line changes in three. Subway Maintenance, Silver and Gold, Evil Close Quarters and Notta Problem had stems cut at 100 s: re-separated from the master and the three unaligned songs force-aligned. Lyric styles now use 36 sections, all in sync (was 32, 25 in sync). Subway Maintenance's lyric text stops at ~1:57: Dylan has the rest.
- 2026-11-24: ascii.cinema.tty renderer rebuilt (PR #149). Clips pass footage.blocked()/BLOCK plus a SKIP list (they were never checked). One reel per video (comedy: Keaton/Chaplin/Lloyd; dream: Méliès, Nosferatu, Ballet Mécanique and other avant-garde films; launch: rockets, Coney Island, trains). Clips surveyed once (`.cinema.json`); opener picked for motion x contrast x outline; films alternate, cuts on the bar, crop follows the action, last cut loops into frame 0. Letters through an S-curve and an ink-sorted ramp, difference-of-Gaussians outlines as `| / - \` strokes, a dim picture wash behind, new shots type themselves in. Text inside the safe area; captions rewritten. Knobs: reel, cell (12/14), look (paper/phosphor/amber), crt. The launch reel needs clearer rocket footage.
- 2026-11-24: earth.data.live quality pass (PR #150). Count, clock and credit moved out of Instagram's bottom 420 px (now y 1300-1500); the opening line stays at y 290-420 for the whole video. Hooks and counters are built from each video's own data, so no "right now": flights say "AIRLINERS TRACKED", quakes "M2.5+". Globe bigger (radius 455); flights draw planes as arrowheads on their heading when zoomed in, no smearing while the camera moves; quakes open on the busiest side of the planet. Paper weighted x2 (most-watched so far, small sample). earthdata.py fetches NASA Blue Marble and Black Marble once into the earth-data release, enabling a "marble" palette (real day side, city lights at night): check its first post. Caption bank rewritten to lines true for every scene.
- 2026-11-24: two more text pages prepared (accounts not created yet): a girl's voice (`studio/text_her_video.py`, bank `studio/notes/her.txt`, ids h001...) and a guy's voice (`studio/text_him_video.py`, `studio/notes/him.txt`, m001...), both the moth.ate.my.notes card with their own banks, memory and looks. `text_video.py` gained looks rainbow/citrus/meadow (the light washes text pages use), a `strong` face (Montserrat ExtraBold), and per-voice weights (LOOK_W, INK_W, FACE_W, PREFIX). Campaigns and accounts get wired once the Instagram accounts exist.
- 2026-11-24: girl's and guy's text banks got 22 spicier lines each (Dylan: "a little raunchier"): flirting, late-night texts, dating, nights out. Suggestive, never explicit: Instagram stops recommending sexually explicit posts.
- 2026-11-24: the guy's text page leans skate (Dylan: "the boy should be something about skateboarding"): 24 skate lines added to `studio/notes/him.txt` (no real skaters or brands). The girl's page is planned as @crying.in.trader.joes.
- 2026-11-24: 14 more lines for the guy's skate page in the style Dylan pointed to (would-you-rather cards, dumb setups with a fake-math punchline). Skate-footage backgrounds come once we have our own skate clips.
- 2026-11-24: moth.ate.my.notes posted the same line twice (n044 on two songs): the night's videos render side by side before any is in recipes.json, so text_video's own 'unused' check could not see its siblings. nightly.py now picks text-page lines itself (`BANKED`, `fresh_line`) off everything already posted and everything chosen tonight; the same goes for the girl's and guy's pages.
- 2026-11-24: @crying.in.trader.joes (her_ig, IG_TOKEN_6, campaign notes_her) and @grip.tape.thoughts (him_ig, IG_TOKEN_5, campaign notes_him) created through iPhone Mirroring inside the existing Meta account, switched to Creator, added as Instagram testers of the app (no Facebook Page). Campaigns start paused until their tokens pass ig-check; 5 a night each in studio/nightly.yaml.
- 2026-11-25: insights permission added for the Unified-login accounts; tokens.yml refreshes IG tokens twice a month.
- 2026-11-25: psychedelic.station 8→4 and nostalgia.hub.vhs 6→4 reels a day (heaviest posters had the lowest medians; their fact reels beat the main format). Cancelled one queued dylancantor23 post asking for saves.
- 2026-11-25: new page styles toon (1930 cartoons), zoom (museum zoom), notes_date, notes_college, lowpoly (Blender story page; CC0 kits via lowpoly.yml). Accounts still to be created.
- 2026-11-25: publisher waits until an account's last post is an hour old (MIN_GAP); back-to-back posts did ~20% worse.
- 2026-11-25: Connect Instagram (cqconnect/, connect.yml); token slots to 16; studio.yml parse fix.
- 2026-11-25: connect link moved to connect.closequarters.vip; pickup never overwrites the shared IG_TOKEN.
- 2026-11-25: IG_PAGE_TOKENS: never-expiring Page tokens minted from IG_TOKEN, preferred by the publisher.
- 2026-11-25: top-up keeps an account's slots an hour apart across campaigns (no more 'overdue' from MIN_GAP holds).
- 2026-11-25: connect: Business-login tokens never expire but cannot name their account; worker trusts the link's handle when the token can publish; scripts/ig_lookup.py finds the id.
- 2026-11-25: nightly never repeats an account's subject within 3 nights (repeats did median 61 views vs 119 fresh); with nothing fresh, the account posts fewer that night.
- 2026-11-25: wired rubberhose.radio, zoom.into.art, situationship.notes, what.if.town (own tokens IG_TOKEN_7/8/9/11).
- 2026-11-25: wired dining.hall.philosopher (notes_college, IG_TOKEN_10).
- 2026-11-25: volume fitted to the data: dylancantor23 8->3, psych 4->2 and nostalgia 4->2 (fact reels carry them), Loose Change type 3->1. Daily totals did not grow with posts.
- 2026-11-25: retire weak subjects by hand (nightly.yaml `retire:`): liminal school/pool, psy marble/spiral/warp/oil, glitch water/nature, nyc fact. Each did a fifth or less of the account's best subject.
- 2026-11-25: new pages were not posting: their queue.json lacked generated_at (render/topup failed), and bpy crashed on the runner with no EGL. Both fixed; see traps.md.
- 2026-11-26: ready page circle_atlas (style `reveal`, studio/reveal_video.py): countries drawn by Fourier circles, the name at the end; outlines from Natural Earth (public domain). Paused until its Instagram account exists. New `docs/brain/ready-pages.md` lists pages waiting for accounts; nightly.yaml targets can be `paused: true` (skipped unless run with campaign=<c>).
- 2026-11-25: openings: glitch opens on a clean readable shot (knob opener, clean 3:1; frame 0 was mid-melt, skip 85%); vintage favours the filled frame over the three-frame strip (layout 2:3); retro 4->2 a day (median 16 views).
- 2026-11-25: wired Adrianne's eye.trick.lab (illusion) and fourier.reveal (math); 2 a day, Page tokens.
- 2026-11-25: vintage.media.archive paused after an Instagram originality notice.
- 2026-11-25: vintage.media.archive back, every frame redrawn as ink line art (look=ink, warm papers), 2 a day.
- 2026-11-25: new format stopit ("can you stop this?") on physics.bounce.lab, 2 a night; physics 4->3.
- 2026-11-26: ready page stare_lab (style `stare`, studio/stare_video.py): afterimage, motion-aftereffect and lilac-chaser illusions on landscapes drawn in code; six steadier songs. Paused until its Instagram account exists ([[ready-pages]]).
- 2026-11-26: duplicate bookings from two concurrent top-ups cancelled (52); topup cron removed; one booking per video per account.
- 2026-11-26: eye.trick.lab -> stare_lab, fourier.reveal -> circle_atlas (own formats; were near copies of siblings).
- 2026-11-26: ready page ink_marbling (style `ebru`, studio/ebru_video.py): paper marbling by the exact drop/comb/wave/stir maps, drops on the beat; six patterns. Paused until its Instagram account exists ([[ready-pages]]).
- 2026-11-26: ready-pages.md: circle_atlas and stare_lab taken off (they went live on @fourier.reveal and @eye.trick.lab).
- 2026-11-26: ready page ruler_says_no (style `measure`, studio/measure_video.py): seven classic size/straightness/grey illusions asked, then measured on the beat (numbers read off the drawing). Paused until its Instagram account exists ([[ready-pages]]).
- 2026-11-26: studio/gl.py (headless GLSL on CPU) + psy fields as full-size shaders (shaders/psy.glsl, new `relief` knob); studio/polish.py finishing pass on 15 renderers; psy CRF 27->20.
- 2026-11-26: alife (digital.petri.dish): physarum at full resolution, 1.2M agents (numba), new `species` knob (three colonies). tinycode fields drawn at 1000 px, points splatted bilinearly.
- 2026-11-26: retro: FastWan 2.2 (Wan 2.2 5B, 3 DMD steps, 704x1280) added as a test option (`model: fastwan` on retro.yml); default unchanged until the test clips are reviewed.
