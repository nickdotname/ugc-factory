# Log

Back to [[README]]. Newest first; one line per change worth remembering.

- 2026-11-23: AI pictures and the band's three worlds. `plates_gen.py` makes background stills with SDXL on Kaggle's
  free GPUs (release `plates-library`; themes school, psych, nyc, liminal, psy). New style `scene` for
  close__quarters sets the cut-out band into an after-hours school, psych landscapes or New York on film; the first
  version copied dev_lemons too closely (letterbox, italic lyrics, laptop, handheld, billboard) and was rewritten.
  Footage theme `nyc_now`: modern New York from Pexels (free licence, needs `PEXELS_API_KEY`; Commons has no
  usable no-credit footage of today's city: tried, 18 news clips, purged), because the 1899 films were the wrong New York for it.

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
