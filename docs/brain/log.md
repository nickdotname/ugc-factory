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
