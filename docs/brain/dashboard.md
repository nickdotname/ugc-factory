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
- **States:** a post past its slot shows "uploading" for up to 20 minutes (the 5-minute publisher picks it up),
  then "late".

Adding an account: add its handle to `HANDLES` and its style's subject knobs to `WHAT`.
