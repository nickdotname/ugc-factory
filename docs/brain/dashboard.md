# Dashboard: dashboard.closequarters.vip

Back to [[README]].

- **What:** `cqdash/index.html` (one page) reading `cqdash/data.json`. Tabs: Up next (queued posts by day, with
  QUEUED / uploading / late states), Posted (published posts and their numbers), Accounts (per-account totals,
  followers, bio-link taps and winning knobs). Account profile pictures on every row.
- **Data:** `scripts/dash_data.py`, run by `publish.yml` every 5 minutes; it rewrites `data.json` only when
  something changed (so "updated N min ago" can be older than 5 min on a quiet night). It knows each account's
  handle (`HANDLES`), its bio-link path (`LINKS`, the table in `link/README.md`), which knobs say what a video is
  about (`WHAT`), drops Clubs (`NOT_CQ`) and, for @the.loose.change, everything posted before it was a Close
  Quarters account (`OURS_ONLY`). Profile pictures and counts: one Graph call per account once a day (its own
  token, else business_discovery by handle through one of ours), falling back to `campaigns/*/brand/profile.jpg`.
- **Serving:** Cloudflare Worker `cq-dashboard` on the `closequarters.vip` zone serves the page and data from
  `raw.githubusercontent.com` main, and refuses any request without Cloudflare Access's JWT header. It serves
  only `index.html` and `data.json`: anything the page shows has to be in `data.json`.
- **Access:** Cloudflare Zero Trust application "dashboard" with policy "Dylan and Nick only" (email allow-list,
  One-time PIN login). The emails live only in that policy, never in this public repo. The workers.dev URL is off.
- **States:** a booked post past its slot shows "posting now" for up to 30 minutes (the 5-minute publisher, then
  Instagram's processing), then "overdue". Rendered videos with no slot yet ("pending") are listed apart under
  "Ready, waiting for a free slot", with no time: their render-time slot may have gone to another video. Buffer
  posts read "sent to buffer" until Buffer's numbers confirm them. Failed posts show in Posted with their reason.
- **Numbers:** from `campaigns/*/posts.json`, written by `metrics.yml` (every 3 hours for Instagram, daily for
  Buffer). Each post says how old its numbers are ("as of 2 h ago"); totals count only posts that have numbers
  and say how many do. Before 2026-11-23 metrics ran on GitHub's cron, which skipped days: numbers froze.
- **Insights denied** (red line on an account card): every post the account published in the last 24 h is without
  numbers although the oldest went out over 6 h ago, so the 3-hourly metrics run has had its turn and Instagram
  answered nothing. Buffer accounts (read once a day) are left out of the check. Usually a token that cannot read
  that account's insights: see [[traps]].
- **Followers** (`cqdash/followers.json`, one row per account per day, 90 days kept): `followers_count`,
  `follows_count` and `media_count` come free with the daily profile-picture call. `data.json` carries, per
  account, `followers`, `follows`, `media`, `followers_at` (the row's day), `followers_7d` (the change since the
  row 7 days back, else the oldest row within the week) with `followers_since` (that row's day), and
  `followers_log` (the last 14 days). The card shows the count, the delta ("+12 · 7d", "−3 · 2d" while the log is
  young) and the grid size. If `followers.json` is missing on a runner, the log is rebuilt from the old
  `data.json`'s `followers_log`, so a delta survives an uncommitted file. **`publish.yml` must `git add
  cqdash/followers.json` beside `data.json` for the 90 days to accumulate** (until then the 14-day log in
  `data.json` is all there is).
- **Bio-link taps:** `dash_data.py` reads `<link_base>/stats` (site.yaml; `link/worker.js`, no secret) every run
  and gives each account `link` (its path), `taps` (7 daily counts), `taps7` and `tap_last` (the latest tap's
  time). The card shows "N bio taps 7d · last 3 h ago" (or "none yet"). When the worker cannot be read the last
  numbers stand. The same stats feed `studio/clicks.json` nightly (`studio/learn.py`).

`data.json` only ever gains fields: an older page reads a newer file and the other way round.

Adding an account: add its handle to `HANDLES`, its bio-link path to `LINKS` (and `link/worker.js` SOURCES,
`link/README.md`, `studio/learn.py` LINK_NAMES; `tests/test_dash_data.py` checks the first two agree) and its
style's subject knobs to `WHAT`.
