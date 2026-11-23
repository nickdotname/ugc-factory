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
- **GitHub cron is late and skips.** The 5-minute clock is a Cloudflare Worker; GitHub's cron is only the backup.
  Cloudflare's settings UI needs its "Unsaved changes → Save" bar clicked or nothing changes.
- **"Base branch was modified"** when merging: refresh the PR page and merge again.
- **Overnight looks empty by design:** posting windows are daytime, and the queue only holds about a day ahead
  (`max_backlog_days: 1`), so the dashboard rarely shows more than tomorrow.

## Studio and media

- Cloud sessions can't download from archive.org / Wikimedia; GitHub Actions can. Get footage via the releases.
- `prep_song.py` writes .flac stems and a symlinked master.wav; the renderers want .ogg. Convert, then run
  `beatmap.py` (it needs `stems/Drums.ogg`).
- Fonts: the serif (Fraunces) has no ♪; credits use DejaVuSans.
- OpenCV `remap` wants float32 maps: numpy float64 maths silently upcasts and crashes it.
- GitHub concurrency groups keep one running and **one** pending run: dispatching the same workflow three times
  drops the middle one.
- Old CI renders occasionally segfault when four run in parallel; nightly retries a failed render alone.
