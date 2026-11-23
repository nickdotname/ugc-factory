# Dashboard: dashboard.closequarters.vip

Back to [[README]].

- **What:** `cqdash/index.html` (one page) reading `cqdash/data.json`. Tabs: Up next (queued posts by day, with
  QUEUED / uploading / late states), Posted (published posts and their numbers), Accounts (per-account totals and
  winning knobs). Account profile pictures on every row.
- **Data:** `scripts/dash_data.py`, run by `publish.yml` every 5 minutes; it rewrites `data.json` only when
  something changed (so "updated N min ago" can be older than 5 min on a quiet night). It knows each account's
  handle (`HANDLES`), which knobs say what a video is about (`WHAT`), drops Clubs (`NOT_CQ`) and, for
  @the.loose.change, everything posted before it was a Close Quarters account (`OURS_ONLY`). Profile pictures:
  business_discovery once a day, falling back to `campaigns/*/brand/profile.jpg`.
- **Serving:** Cloudflare Worker `cq-dashboard` on the `closequarters.vip` zone serves the page and data from
  `raw.githubusercontent.com` main, and refuses any request without Cloudflare Access's JWT header.
- **Access:** Cloudflare Zero Trust application "dashboard" with policy "Dylan and Nick only" (email allow-list,
  One-time PIN login). The emails live only in that policy, never in this public repo. The workers.dev URL is off.
- **States:** a booked post past its slot shows "posting now" for up to 30 minutes (the 5-minute publisher, then
  Instagram's processing), then "overdue". Rendered videos with no slot yet ("pending") are listed apart under
  "Ready, waiting for a free slot", with no time: their render-time slot may have gone to another video. Buffer
  posts read "sent to buffer" until Buffer's numbers confirm them. Failed posts show in Posted with their reason.
- **Numbers:** from `campaigns/*/posts.json`, written by `metrics.yml` (every 3 hours for Instagram, daily for
  Buffer). Each post says how old its numbers are ("as of 2 h ago"); totals count only posts that have numbers
  and say how many do. Before 2026-11-23 metrics ran on GitHub's cron, which skipped days: numbers froze.

Adding an account: add its handle to `HANDLES` and its style's subject knobs to `WHAT`.
