# Context

What this project is, what the evidence actually says, and where the traps are.
Written 2026-09-11 after roughly four weeks of operating it.

`SPEC.md` is the contract and `README.md` is the setup. This file is the part
neither of those can hold: what was tried, what it did, and which confident
explanations turned out to be wrong.

---

## 1. What it does

A nightly pipeline that assembles short vertical videos from a small clip
library and schedules them to Instagram, TikTok and YouTube through Buffer.

```
render (05:00 UTC)   pick unused (hook, body…, music, caption) → ffmpeg →
                     upload to a GitHub Release → write queue.json
topup  (every 4h)    push queue items into Buffer up to its depth cap
metrics  (daily)     pull per-post figures back into posts.json
analytics (daily)    pull product-side signups from the Clubs admin API
```

State lives in the repo, one directory per campaign, committed by the jobs
themselves. There is no database and no server — GitHub Actions plus a local
read-only dashboard (`ugc web`, port 8765).

**One campaign is one channel.** `clubs`, `clubs_tt`, `clubs_yt` are the same
brand posting the same clips to three networks, grouped by a shared
`assets_release`. That grouping is the unit that matters for anything
product-side, because all three drive one product.

`campaigns/_knick_creates*` is a second brand, scaffolded and never finished.
The `_` prefix removes it from discovery. It is parked, not deleted — rename
back to revive it. It spent weeks failing every workflow daily because nothing
skipped it, which is worth remembering before adding another half-built
campaign.

---

## 2. Where things stand

Lifetime, as of 2026-09-11:

| campaign | network | posts | views | views/post | eng % | follows |
|---|---|---|---|---|---|---|
| clubs | Instagram | 332 | 74,874 | 225.5 | 6.82 | **0** |
| clubs_tt | TikTok | 194 | 12,867 | 66.3 | 3.73 | **0** |
| clubs_yt | YouTube | 193 | 5,700 | 29.5 | 1.11 | **0** |

Product side: 756 users, 312 signups in the last 30 days.

All three campaigns run 4/day as of 2026-09-11, cut from 12/6/6.

### The number that matters most

**Zero follows. Across 719 posts and 93,000 views, on every network, since the
first day.** Not "few" — zero, in every daily snapshot ever recorded.

Shares and saves populate normally (977 and 1,699 on Instagram), so this is
not a reporting gap. Every caption drives off-platform, nothing asks for a
follow, and the accounts have accordingly never built an audience. Reach is
therefore entirely algorithmic non-follower distribution, which is the hardest
kind to sustain and the first to be withdrawn.

This is the most likely cause of Instagram's decline (§4) and the cheapest
thing left to change.

---

## 3. The library is the ceiling

Six hooks, four bodies, three music tracks. That is **24 distinct visuals**
(36 on YouTube, which uses two bodies per video).

Every runway figure the system reports counts *combinations* — hook × body ×
music offset × caption. Instagram shows 19,800, which is 4,950 days. The
number of distinct things a viewer can actually see is 24. At 12/day the
picture repeated every 2 days; at 4/day it repeats every 6.

**Treat the combination count as a dedupe guarantee, not a variety measure.**
Caption and music-offset permutations do not change what anyone watches.

Measured performance of the clips, from 21 Instagram breakouts (≥800 views):

| clip | share of breakouts | share of ordinary posts |
|---|---|---|
| hook_02 | 38.1% | 12.2% |
| hook_06 | 23.8% | 15.4% |
| hook_01 | 4.8% | 17.3% |
| **body_04** | **0.0%** | **25.6%** |

`body_04` has produced zero breakouts while holding a quarter of the posting —
p ≈ 0.002 against that being chance. **It is the clip to replace first.** It is
weighted down rather than muted, because dropping to three bodies would cut
distinct visuals from 24 to 18.

Also suggestive: both sub-1.5s hooks are among the three worst, and neither has
ever broken out in 44 posts. When shooting new hooks, give the premise two full
seconds.

---

## 4. What happened to each network

### Instagram — declining, not banned

Reach fell steadily from ~200 views/post (Aug 30) to ~60 (Sep 10) while the
**engagement rate stayed flat at 7.21% → 6.84%**, and no post has ever landed
at zero views.

That combination rules out suppression. People who see it respond exactly as
they always did; fewer are shown it. The working hypothesis is account quality,
driven by the zero-follows signal in §2, compounded by 24 visuals running
thirteen times each into an audience with no follower base.

The 4/day cut on 2026-09-11 is the first test of this. If reach recovers at
lower volume, saturation was the mechanism. If it does not, the follow signal
is, and the captions need to start asking for follows.

### TikTok — broke, diagnosed, fixed

Went to literal zero on 2026-08-18: 32 of 59 posts at exactly zero views,
median 0. A served post always gets *some* seed audience, so zero means the
video never entered distribution.

Cause was almost certainly the music. All three tracks were downloaded from
YouTube — they are the copyrighted originals, which TikTok mutes and YouTube
Content ID matches. Muting music on TikTok and YouTube (2026-08-23) brought
TikTok back within a day: median 137 views on 08-24 against 0 before.

### YouTube — live, correctly formatted, and ignored

Got the same fix and did not recover. `ugc diagnose` settles what it is:

```
totals: {'scheduled': 2, 'sent': 18}
16 posts live at youtube.com/shorts/…
```

Everything publishes, and YouTube's own URL classifies them as Shorts. There is
no block, no claim in the publishing path, no format bug. It is a cold channel
with no subscribers, and Shorts gives that almost nothing. Unlike TikTok there
is no fixable fault — which also means the distribution alert (§6) deliberately
will not page about it, because it never had a healthy stretch to fall from.

### The music question

`campaigns/clubs/LICENSES.md` records this in full. Short version: the three
tracks are copyrighted, they stay muted on TikTok and YouTube, and they stay
live on Instagram because Meta licenses far more broadly and has not touched
them across 300+ posts. That is a weighed decision, not an oversight. Swapping
in royalty-free tracks would remove the residual risk without changing anything
a viewer notices — the bed sits at 10% under voiceover, and TikTok recovered
with no music at all.

---

## 5. Does any of this drive signups?

**No measurable effect, on four independent readings.**

- Daily views and signups correlate at r ≈ 0.1 (p ≈ 0.28) at every lag 0–7 days.
- Mean signups: 10.0 on days with posts, 9.2 on days without.
- The week of Aug 3 took **79 signups with zero posting**; the heaviest posting
  week took 84.
- 2026-09-01 had the week's lowest views and its highest signups.

The product also loses roughly 60% of weekly actives, retains ~12% at week 1
across all 17 cohorts back to May, and records **zero applications against
13,528 swipes** — which looks like a tracking bug on the Clubs side and has
been flagged but not fixed.

**Attribution is day-level only and cannot be made finer here.** The signup
series is product-wide: no referrer, no campaign tag, no per-post id
(`acquisition.by_source` is 100% `mobile`). Ranking a *hook* by signups needs a
per-post link that Clubs resolves — instrumentation on the product side, not
arithmetic on this one. `correlate()` is named and documented to keep anyone
from reading more into it than that.

---

## 6. What monitors what

Alerts go to Discord. Each was built after the failure it describes.

| event | fires when | catches |
|---|---|---|
| `distribution_lost` | ≥70% of a day's posts reach ≤2 views, 3 days running, preceded by a healthy day | TikTok's shutdown |
| `schedule_gap` | queue full by count but next slot > 6h away | the 18-hour silence of 2026-08-29 |
| `demand_unmet` | captions speak to <75% of search volume | copy drifting from what people search |
| `queue_stale`, `queue_empty`, `quota_high`, `license_missing`, `dedupe_relaxed`, `failure`, `digest` | pre-existing | |

Two design notes that are easy to undo by accident:

**`distribution_lost` measures the share of posts reaching nobody, not a drop in
views.** Magnitude is useless as a signal — healthy Instagram swings 0.23x then
3.15x day to day, healthy YouTube by two orders of magnitude. Any
percentage-drop rule tuned to catch a real outage fires constantly on channels
that are fine.

**It requires a healthy day before the run.** A channel that never worked would
otherwise alert every morning forever. The cost is that a channel already dead
when alerting is switched on stays silent. That is deliberate.

---

## 7. Traps

### The dashboard is a long-running process reading files that move

Config models use `extra="forbid"`. A process started before a config gained a
field cannot parse that config at all, shows every campaign as broken, and is
itself the only thing available to report why. **Four separate "the dashboard is
broken" reports were this.**

`restart_needed` in `/api/pending` now detects it by fingerprinting `src/` and
the campaign configs at boot. **Restart the dashboard after any config change.**

### Pull before you judge anything

The jobs commit their results to the repo; the dashboard reads local disk. A
checkout that has not pulled shows figures frozen at whenever it last did, very
convincingly. This has caused false alarms at 86, 227 and 372 commits behind —
"no data since Aug 27", "huge Buffer backlog", "nothing has posted". All three
were a stale checkout. `behind_commits` now reports it, but it cannot help if
the dashboard process predates that feature.

### `max_backlog_days` was a hidden rate multiplier

Render produces `posts_per_day × max_backlog_days` *every day* and topup pushes
it within about a day. At `2`, every campaign published at double its configured
rate — `clubs` read 12/day and published 13–17. All three are now `1`, and the
number in the config means what it says.

### Red workflows were mostly one dead campaign

Before `knick_creates` was parked, render, metrics, analytics and preflight were
all red simultaneously, every day, on a campaign that had never posted. Red
every day is the same as no signal. Check *which job* failed before believing a
banner.

### The acceptance tests are load-bearing

`tests/test_acceptance.py` enforces the architecture and it is right to. It will
reject, among others:

- `requests` imported outside a boundary module
- `datetime.now()` anywhere but `ports.py`/`logging.py`
- the string `clubs` (any campaign slug) appearing anywhere in `src/`

The first draft of the analytics client broke all three and deserved to. `src/`
is campaign-agnostic: the admin API's endpoint and the *name* of its secret are
campaign config, so a second brand pointing at a different panel is
configuration rather than a code change.

### Secrets live in two stores

`.env` is local, GitHub secrets are for the workflows. The dashboard writes both
when asked; saving to only one produces a state where every local run succeeds
and every scheduled one fails. `CLUBS_API_KEY` was local-only for six days, and
because local runs kept working the daily failures read as noise.

---

## 8. Things I got wrong

Recorded because the wrong answers were each confident and plausible.

- **"A stuck errored post is eating the queue cap."** It is not; `queue_depth`
  filters to `scheduled`/`sending` and excludes `error`.
- **"Past-dated queue items are dead weight."** `_reslot_stale` reassigns them
  at push time.
- **"`carry_forward` keeps stale times."** True, and handled downstream.
- **"Topup's commits are not reaching the repo."** Could not be substantiated;
  the evidence was two greps of one log returning different counts. The code is
  fine.
- **"TikTok and YouTube are running 6/day now."** That was render volume, not
  publishes. See `max_backlog_days` above.
- **"The analytics failures are `knick_creates` noise."** Four of them came
  after that campaign was parked. It was a missing GitHub secret.
- **"The `performance_weight` change starved variety."** Hook distribution
  before and after is 25% vs 24% on the top clip. It did not.

The pattern: the codebase already handled most of what looked broken, and the
real faults were in configuration, staleness, and things outside the repo.
Check what the code actually does before theorising about it.

---

## 9. What to do next

**Ranked by expected value, not by effort.**

1. **Shoot more clips.** Six hooks and four bodies caps everything — how hard
   the weighting can favour winners, how fast any channel can scale, how long
   before fatigue. Replace `body_04` first; shoot hooks at 2+ seconds. This is
   the only item that raises the ceiling rather than tuning under it.

2. **Ask for follows.** Zero across 719 posts is the worst signal these accounts
   emit, and it costs one caption rewrite to stop emitting it.

3. **Watch the 4/day cut.** Reach recovering means saturation; reach flat means
   the follow signal. Either answer directs everything after it.

4. **Per-post attribution**, if Clubs can resolve a `?ref=` on the bio link.
   `attribution.py` would then rank hooks by conversions instead of views, and
   those are unlikely to be the same order.

5. **The `apply: 0` bug** on the product side — 13,528 swipes, zero recorded
   applications, while 330 connections plainly happened.

What is *not* worth doing: tuning YouTube (§4), cross-campaign dedupe (networks
do not share fingerprint databases), or trusting any single coverage or runway
percentage without looking at what it counts.
