# Traps: what broke, why, and the fix

Back to [[README]]. The older Clubs-era traps are in `CONTEXT.md` §7 and `HANDOFF.md` §5.

## Meta / Instagram accounts

- **An account must be Creator (professional) and linked to a Facebook Page before the API can see it.** Signing up
  isn't enough. `business_discovery` finds any professional account (handy for its id); `me/accounts` only shows
  Pages the app was granted.
- **Popups die if you touch their opener.** "Connect Instagram" on a Page, and "Generate Access Token" in the Graph
  API Explorer, open a popup that reports back to the tab that opened it. Reloading or navigating that tab before
  the popup finishes loses the result silently ("No Instagram connected"). Start the flow, then only *look*.
- **The Instagram popup uses whichever Instagram account the browser is logged into.** With several accounts in
  one Chrome, it will offer the wrong one. Log the right account into instagram.com first, or choose
  "Use another profile" / "Switch accounts".
- **Login challenges go to the contact points on the account's own Meta Accounts Center**, which may differ from
  your Facebook account's (vintage's offered a relative's number until Dylan confirmed his own).
- **Linking a Page from the Instagram phone app** ("Edit profile → Facebook Page") failed with "Something went
  wrong"; the web flow from the Page's Settings → Linked accounts worked.
- **Granting the app:** choose "Opt in to all current and future Pages / Instagram accounts" so new accounts need
  no re-grant (done 2026-11-23). After any grant, refresh `IG_TOKEN` (Explorer → Copy token → Debugger → Extend).
- **Pages are created under Dylan's Facebook** even for Nick's account, so one token covers every account.
- **Facebook caps new Pages per profile.** After several in a day, "Create Page" does nothing on screen; the
  response says "You have created too many Pages recently." Wait a day, or have Nick create the Page and give
  Dylan full control (Page settings → Page access), then link it from Dylan's side as usual.
- **"Opt in to future accounts" isn't enough for a brand-new Page:** `me/accounts` didn't list Tiny Code until
  Generate Access Token was run again and the new Page and account were ticked; then refresh `IG_TOKEN`.

## Queue and posting

- **Render before studio = an empty day a day later.** Render is demand-driven; it used to run before the nightly
  studio, so new videos waited a day. Render now runs at 08:30 UTC, after studio (06:45).
- **Double-booked minutes.** A hand-run render plus already-booked posts produced two posts on one minute; topup
  now also avoids minutes the network already holds (`scheduled_slots`).
- **One exhausted creative used to fail the whole campaign**, and one too-short clip failed the render; both are
  now skipped (`creative_exhausted`, `item_rejected`).
- **The same post sent twice.** A run that waits its turn behind another sender (fact reel, carousel, the run
  before it) is checked out at the commit that *started* it, so a post the earlier job just sent still read as
  unsent and went out again; the two then changed the same outbox file, the push failed, and every other post that
  run had sent lost its record and was sent again five minutes later. It happened three times (Nov 21 13:00 and
  22:15, Nov 24 10:55 New York; seven extra posts). `publish-due` now pulls the branch before reading the outbox
  (`vcs.sync`), pushes a `publishing` claim for each post before asking Instagram to publish it, and pushes the
  result straight after with `vcs.record`, which cannot be refused. A failed `publish.yml` run is the sign to look
  for: `gh api '...workflows/publish.yml/runs?status=failure'`.
- **GitHub cron is late and skips.** The 5-minute clock is a Cloudflare Worker; GitHub's cron is only the backup.
  Cloudflare's settings UI needs its "Unsaved changes → Save" bar clicked or nothing changes.
- **"Base branch was modified"** when merging: refresh the PR page and merge again.
- **Overnight looks empty by design:** posting windows are daytime, and the queue only holds about a day ahead
  (`max_backlog_days: 1`), so the dashboard rarely shows more than tomorrow.
- **A lone 502 from the media site failed a whole campaign's topup** (retro_arcade, 04:00 New York, 2026-11-24: `MediaStoreError ... not publicly readable (HTTP 502)`; the same video posted fine that afternoon). `assert_publicly_readable` (src/assets.py) now asks again after 4 s and 12 s on 5xx, 429 or a dropped connection; 401/403/404 still stop at once.

## Studio and media

- Cloud sessions can't download from archive.org / Wikimedia; GitHub Actions can. Get footage via the releases.
- `prep_song.py` writes .flac stems and a symlinked master.wav; the renderers want .ogg. Convert, then run
  `beatmap.py` (it needs `stems/Drums.ogg`).
- Fonts: the serif (Fraunces) has no ♪; credits use DejaVuSans.
- OpenCV `remap` wants float32 maps: numpy float64 maths silently upcasts and crashes it.
- GitHub concurrency groups keep one running and **one** pending run: dispatching the same workflow three times
  drops the middle one.
- **Two campaigns on one Buffer channel starve each other**: the cap (`max_buffer_queue`, Buffer's ten) is the
  channel's, and whichever campaign tops up first fills it. Give each a `posting.buffer_share`.
- Old CI renders occasionally segfault when four run in parallel; nightly retries a failed render alone.
- **Every lyric/cut-out render segfaults in `librosa.util.peak_pick`** (even retried alone): librosa caches its
  compiled helpers on disk, and renders starting at the same moment wrote that cache together and broke it.
  nightly.py now builds it once in a single process (`NUMBA_CACHE_DIR` of the run's own) before any render.
- **A song's stems can be shorter than its master** (four songs stop at 100 s). Anything reading stems past
  their end gets silence: use `beat.stretch`, which falls back to the master.

- **Lyrics late at every line change (fixed 2026-11-24).** lyric_video, type and psy picked the line on screen as
  the *first* line still within 0.25 s of its end (cursor: 0.5 s). Lines are mostly back to back, so the old line
  held the screen and the new line's first word came up ~0.28 s late on 449 of 676 line changes. The latest line
  that has started now wins.
- **Stems cut at 100 s.** Four songs' stems stopped at 1:40 while the master ran on, so their lines.json after that
  was evenly spaced guesses (end 99.99) on silence. Re-separated from the master with the same model (2_HP-UVR;
  the first 100 s match the old stems at correlation 0.97–1.0, lag 0) and re-aligned.
- **audio-separator and Whisper medium each want ~3 GB.** Run them one after another in a cloud session, never
  together, or the memory cgroup kills one silently.

## apt hangs on the hosted runners

`sudo apt-get install ffmpeg` sometimes sits for an hour with no output (seen on four jobs on 2026-11-24). The job
shows "Install ffmpeg: in progress" and nothing else. Cancelling and re-running always worked. Workflows now call
`bash scripts/apt_install.sh <packages>`, which gives each try a few minutes and retries three times. If a job is
stuck on any other step for more than ten minutes, cancel it and dispatch it again; the jobs are safe to re-run.

## The same text-page line twice (2026-11-24)
Videos of one night render in parallel before recipes.json is written, so a renderer that avoids reuse by reading recipes cannot see the other videos of the same night. Choose no-repeat subjects in `nightly.py` (see `fresh_line`), not in the renderer.
