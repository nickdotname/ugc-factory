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

## Unified-login accounts had no numbers (2026-11-25)
The five accounts with no Facebook Page (algorithm.races, 8bit.tests, moth.ate.my.notes, grip.tape.thoughts,
crying.in.trader.joes) posted fine but every insights call said "(#10) Application does not have permission".
The app had never been given `instagram_business_manage_insights` (Use cases > Instagram API > Permissions and
features). Added; their tokens had to be generated again to carry it. Those tokens last 60 days:
`.github/workflows/tokens.yml` refreshes them on the 1st and 15th and writes them back (needs `SECRETS_PAT`).

## Back-to-back posts on one account (2026-11-25)
Reels, carousels and fact reels are queued by separate jobs, so one account sometimes posted twice within minutes.
77 posts went out under 45 minutes after the account's previous one; their median was 72 views against 89 for the
rest. `publish_due` now holds a post while its account's last publish is under `MIN_GAP` (60 min) old.

## Tokens without pasting: "Connect Instagram" (2026-11-25)
`connect.closequarters.vip/connect?u=<handle>` (its own subdomain: the apex is served by Vercel, so a route there never reaches the worker) (Cloudflare Worker `cq-connect`, code in `cqconnect/worker.js`) runs the app's
Unified login. The token it gets back is made long-lived, checked against the handle, encrypted to
`cqconnect/public.pem` and held in KV; `connect.yml` (every 15 min) decrypts it with `CONNECT_PRIVATE_KEY` and saves
it as the account's secret (accounts.yaml channel_id, else `cqconnect/slots.json`). Nobody sees a token. Token slots
are IG_TOKEN..IG_TOKEN_16, all passed by every workflow, so a new account never needs a workflow edit.
Also: a YAML plain scalar may not contain ": " — `run: grep -q "style: lowpoly" ...` made studio.yml unreadable and
every studio run failed with zero jobs until it became a block scalar.

- The connect link only fills IG_TOKEN_2 and up. IG_TOKEN is one Facebook token shared by 17 pages; the pickup refuses to overwrite it, and tokens.yml keeps it fresh instead.
- **Tokens without anyone pasting:** `scripts/page_tokens.py` (in tokens.yml, weekly and twice a month) reads
  `me/accounts` with IG_TOKEN and stores never-expiring Page tokens as `IG_PAGE_TOKENS` (JSON, IG id -> token).
  The publisher prefers them. A Page token from a long-lived user token does not expire, and needs no app secret.
  So any account linked to a Facebook Page is covered with no login; Instagram-login (Unified) accounts are not.
- **Connect link "App not active":** `display=page&prompt=login` sends Meta's dialog to business.facebook.com, which shows
  "App not active" for an unpublished app. `display=popup` on www.facebook.com works. New Instagram accounts are not in
  the asset picker until linked: use its "connect a pro account" link and sign in as that account.

## A new campaign's queue.json must carry generated_at (2026-11-25)
The five pages wired on 2026-11-25 were given `{"items": []}` as queue.json. `load_queue` refuses a queue without
`generated_at` (on purpose: it never "recovers" a queue), so render and topup failed for them and nothing posted for
a day. Start a new campaign with `{"generated_at": "1970-01-01T00:00:00Z", "items": []}`, or with no queue.json at all.

## bpy segfaults on the runner without EGL/Mesa (2026-11-25)
The low-poly page's Workbench renderer needs an OpenGL context. GitHub's runner has no libEGL/Mesa, so bpy crashed on
the first frame ("Extension modules: ..." and exit 1). `studio.yml` installs libegl1, libgl1 and libgl1-mesa-dri
before bpy.

## The clock's dispatch can get a 500 (2026-11-25)
At 06:45 UTC GitHub answered the studio dispatch with HTTP 500, so no new videos were made that night and the
accounts with small libraries (illusions, petri, cinema, races, notes) ran dry the next day. `publish.yml` now retries
`gh workflow run` up to five times.

## Originality notice on vintage.media.archive (2026-11-25)
Instagram: "Content you recently shared may go against our originality guidelines and affect your account." The
account cuts famous public-domain films (Nosferatu, Chaplin, Man Ray) with a grade and a frame. Those films are uploaded
everywhere, and a tint and a gate do not stop a match: public domain is not "original" to Instagram. Paused (paused:
true, per_night 0). Loose Change's drop on Nov 17 looked the same. glitch.archive.exe and ascii.cinema.tty use the same
library but change every pixel (datamosh, ASCII), so they are less exposed; watch them.
Fixed the same day: vintage now redraws every frame as ink line art (studio/vintage_video.py, look=ink), into new libraries (assets-vintage_ink-<song>) so no old print-look clip can be posted.

## Two top-ups at once double-booked every video (2026-11-26)
topup.yml had its own cron (47 */4) as well as the clock's 09:00 dispatch: at 08:56 and 09:01 UTC two top-ups ran and
both booked the same rendered videos, 52 duplicate bookings across the network; eye.trick.lab and fourier.reveal
each posted the same video twice an hour apart before it was caught. Fixed three ways: the cron is gone (the clock
alone starts top-ups), the Instagram publisher holds a video only once per account (create_post returns the
existing booking), and publish-due never sends a video the account has already posted. The 52 duplicates were set
to failed, not deleted.
