# dashboard.closequarters.vip

Every account's schedule and numbers on one page, for Dylan and Nick: what is lined up and when (New York time),
what went out, and how each post did (views, likes, comments, sends, saves, average watch time). Tap a post to watch it.

- `index.html`: the page (no build step). Tabs: **Up next**, **Posted** (sortable by views, sends, comments, saves, watch
  time), **Accounts** (posts and views over the last 7 days, median views, followers with the change over 7 days, taps on
  the account's bio link over 7 days, a 14-day views line, next and best post; a red "insights denied" line when a day's
  posts came back without numbers).
- `data.json`: what it shows, rewritten by `scripts/dash_data.py` at the end of every publish run (15 minutes).
- `followers.json`: one row per account per day (followers, following, posts), 90 days, appended by the same script.
- `worker.js`: the Cloudflare Worker on the domain. It serves both files from `main`, so merging a change here is all
  it takes to update the page.

Sign-in is **Cloudflare Access** on the domain, with a policy that allows only the two of us by email (a one-time code
is mailed at each sign-in). The emails live in that policy, not in this public repository. To add or remove someone:
Cloudflare → Zero Trust → Access controls → Applications → dashboard → Policies (policy "Dylan and Nick only"). Login method: One-time PIN.

Everything shown is already in this repository (it is public): the page puts it in one place, it does not reveal more.
