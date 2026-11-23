# Log

Back to [[README]]. Newest first; one line per change worth remembering.

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
