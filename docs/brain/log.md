# Log

Back to [[README]]. Newest first; one line per change worth remembering.

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
