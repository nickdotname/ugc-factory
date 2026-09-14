# Handoff — 2026-09-14

What was built, what it cost, what is still in the way. Written at the end of
the session that shipped phases 1 and 2 of the brief now kept as an appendix
at the bottom of this file.

`SPEC.md` is the contract. `README.md` is the setup. `CONTEXT.md` is what the
evidence actually says and where the traps are — **read it before touching
anything**, particularly §4 (music), §7 (traps) and §8 (things I got wrong).
`PHASE2_PLAN.md` is the fan-out design, now mostly built.

---

## 0. Where this stands, in one screen

| | state |
|---|---|
| **Phase 1 — multiple creatives** | shipped, live |
| **Phase 2 — fan-out to every account** | built and verified, **switched off** |
| **Phase 3 — AI captions** | not started |
| Test suite | 1,306 tests, green |
| `mypy --strict` | clean across 34 modules |
| Posting | **broken since 2026-09-12 ~20:00 UTC** |

**The one thing blocking everything: the Buffer API key for `BUFFER_API_KEY`
is dead.** Every `topup` run since Sep 12 has failed with `AuthError: Buffer
rejected the API key (HTTP 401)` — six consecutive as of Sep 14 04:31. Nothing
has published to any channel since. `render` and `analytics` still pass,
because neither touches Buffer.

Fix: Buffer → Settings → API → new personal token → paste into the **Keys**
panel in the dashboard's Operations tab, which writes `.env` *and* GitHub
secrets together. Writing only one is CONTEXT §7's documented trap: every
local run works and every scheduled one fails.

Nobody but the operator can do this. GitHub secrets cannot be read back, so
the value is not recoverable from the repo or from a session.

---

## 1. What the system is now

### One brand, many places

Before: **one campaign was one channel.** `clubs`, `clubs_tt` and `clubs_yt`
were the same clips, the same cadence and three different caption banks,
split three ways purely because the Buffer binding lived inside the campaign.

Now: **one campaign is a content source**, and channels live in a repo-level
registry.

```
accounts.yaml              six Buffer channels, two logins
  nickdotname_ig/_tt/_yt     BUFFER_API_KEY    org 6a1dc863e8cbb15ba8fdb4ab
  knick_creates_ig/_tt/_yt   BUFFER_API_KEY_2  org 6a86335e7667b936ca8e2ca1

campaigns/clubs/           the one surviving campaign
  config.yaml                cadence, creatives, accounts filter, fan_out
  captions.txt               Instagram copy (the shared/default bank)
  captions/tiktok.txt        TikTok copy      — 25 records
  captions/youtube.txt       YouTube copy     — 25 records, 25 written titles
  creatives/default/LICENSES.md
  queue.json  history.json  posts.json  metrics.json  quota.json  clips.json
```

**"nickdotname" and "clubs" are the same three channels.** `clubs` was this
project's internal codename for the content; nickdotname is the Buffer login
it posts through. This confused a whole round of work — it is not a fourth
brand to go find.

### The vocabulary (settled, and load-bearing)

| word | means | where it appears |
|---|---|---|
| **brand** | a content source, one `campaigns/<slug>/` folder | UI |
| **creative** | a self-contained hook/body/music pool inside a brand | UI + code |
| **network** | instagram / tiktok / youtube | UI + code |
| **account** | one connected Buffer channel in `accounts.yaml` | UI + code |
| **campaign** | the folder/config name for a brand | **code only, never UI** |

`campaign` stays in code, config and folder names because it is load-bearing
in SPEC, the acceptance tests and every workflow matrix. It was removed from
every visible string, because a folder name leaking into the interface is
what made "creative" and "campaign" look like two names for one idea.

### The data model

```
brand (campaign)
 └── creatives[]            each its own Release tag, licences, weight
      └── one picked at random per slot, weighted
           └── QueueItem    one rendered video
                ├── caption + captions{network}   text per network
                └── posts[] → AccountPost         one per account
                                 status, attempts, buffer_post_id, scheduled_for
```

A video is rendered **once** and pushed **per account**. Each account tracks
its own attempts and its own failure, so one channel rejecting a post leaves
the other five untouched. The item's own `status` is a rollup of its account
records (`queue.recompute_status`) so everything that reads a queue — the
dashboard panel, `carry_forward`, the digest — keeps working unchanged.

---

## 2. How to go live

Fan-out is built, dry-run verified, and **off**. Turning it on:

1. **Replace the Buffer key** (§0). Confirm `topup` goes green on the
   existing single-channel path first — do not debug a dead key and a new
   posting topology at the same time.
2. `posting.fan_out: true` in `campaigns/clubs/config.yaml`.
3. `ugc preflight --campaign clubs` — it will refuse if any music track is
   still in rotation (§4 below explains why).
4. **Restart the dashboard.** Config gained fields; a process started before
   them cannot parse the config at all (CONTEXT §7).
5. Watch the first `topup`. Expect ~6 pushes per queued video, staggered 20
   minutes apart within a network.

**Only ever switch `fan_out` on for a brand that is the sole source of its
content.** Two brands carrying the same clips would each fan the same video
to every channel, and each channel would publish it once per brand.

---

## 3. Decisions made, and why

**Creatives keep the per-slot random pick.** A creative is picked per slot,
weighted, and the hook/body/music randomiser then runs *inside* it. Clips
never mix across creatives: each has its own history slice, cooldowns and
dedupe. This layer is what makes "a random creative every set of posts"
possible; collapsing it away would remove that.

**Caption banks are per network, not one shared bank.** Checked before
assuming: the three banks are **not** one caption rewritten three ways, they
are three independent sets of 25. Record 0 is a different caption in each.
So each network picks its own, at render time, against its own recency and
cooldown, and push time only looks it up. Merging them into one bank would
have thrown two thirds of the copy away.

**History post ids: first success wins.** A history entry carries one
`buffer_post_id` and fan-out produces six. The first account to succeed gets
it, which keeps attribution joining exactly as it did when the brand had one
channel. Per-account ids live on the queue records. Keying attribution fully
per account is still open (§6).

**The three histories were merged.** Dedupe now treats a combination already
used on one network as spent everywhere — correct, since one video now
reaches every channel. It retires 1,163 combinations instead of 486, against
19,800 available, so it costs nothing real.

**Music is muted.** See §4 — this one is not a preference.

**`demand_ignore`.** "azure" was 21 of 86 searches, a quarter of all volume,
and the only proper noun in a log otherwise made of topics and places.
Counting it meant the only way to clear the 75% floor was to write "azure"
into Clubs captions: the metric goes green by making the writing worse.
Ignored, coverage is 96.9% rather than 73.3%.

---

## 4. The music problem — read this before re-enabling anything

CONTEXT §4 records a TikTok outage that took weeks to diagnose: all three
music tracks are copyrighted originals downloaded from YouTube, which TikTok
mutes and YouTube Content ID matches. Muting them on those two networks
brought TikTok back within a day.

That fix was implemented as **three campaigns with three mute lists** — music
on for Instagram, off for TikTok and YouTube.

**Fan-out renders one file and sends it everywhere, so that split is now
physically impossible.** The tracks are either in the video for every network
or none.

They are now muted for everyone. The cost is small — the bed sat at 10% under
voiceover and TikTok recovered with no music at all. The real fix is
royalty-free replacements, which CONTEXT §9's shoot brief already requires
for any new music.

`ugc preflight` fails while `fan_out` is on and any music track is in
rotation, naming the fix. That guard exists so this lesson cannot be quietly
lost by someone unmuting a track months from now.

---

## 5. Traps found the hard way this session

**The dashboard is a long-running process reading files that move.** This bit
twice in one session. The process had been running for six days; the moment
`clubs/config.yaml` gained a `creatives:` key, the old in-memory schema
rejected it (`extra="forbid"`) and the dashboard reported the brand as
broken — with a `?` where its details should be. This is exactly CONTEXT §7,
and it is now the single most likely explanation for any "the dashboard is
broken" report. **Restart it after every config change.**

**Metrics were keyed by campaign, and a campaign used to be a channel.** The
collapse broke four analytics panels in the same silent way: asking for "the
latest snapshot" of a brand that posts to three networks returns whichever
sorts last, so the dashboard showed YouTube's figures under the brand's name.
`upsert` now keys on (date, scope, **service**), and `latest`/`lifetime`/
`series`/`change` all take an optional service. Anything that asks a
multi-network brand a single-network question is probably still wrong.

**Title rules differ per network, and one render now feeds all of them.**
Dry-running fan-out for the first time raised `youtube requires a title` —
items rendered for a network with no title field carry none, and YouTube
refuses a Short without one. Titles are resolved per account at push time.

**Stale slots collapsed onto one minute.** The first fan-out implementation
reassigned every past-due item to "now plus a bit", which handed one channel
three videos on the same minute. They now walk successive free slots, the way
the single-channel path always did.

**A campaign slug in a `src/` docstring fails the build.** `src/accounts.py`
mentioned the three campaigns by name in its module docstring and the
acceptance tests rejected it, correctly. The rule is absolute and it applies
to comments.

**`status` is a read-only shell variable.** A monitor script using it as a
local exited 1 with `read-only variable: status`.

---

## 6. What is still open

**Phase 3 — AI captions.** Not started. The original brief (appendix) still
describes it accurately, with one addition: captions are now per network
already, so generation should produce per-network text rather than one string
formatted three ways.

**Attribution keyed fully per account.** `PostMetrics.account` exists and the
838 migrated posts are backfilled with it, but `attribute()` still ranks by
dimension across the whole brand. Ranking a hook *per account* is the
follow-up that makes "which creative works on which network" answerable.

**The dashboard shows the first creative only.** Its clip panel, sample
button and plan preview all operate on whichever creative is selected, but
there is no creative picker outside the Assets panel, and `ugc clips` (the
mute roster) is still campaign-wide — a clip muted in one creative is muted
in all of them. Fine while there is one creative; revisit when there are two.

**Duplicate content across two Instagram accounts.** Fan-out will put the
same video on nickdotname and knick.creates twenty minutes apart. Given
CONTEXT §4's open question about account quality driving the Instagram
decline, watch reach on both after go-live. `distribution_lost` will catch a
real collapse; a slow decline it will not.

**`_knick_creates*` is still parked.** Three scaffolded campaign folders with
a `_` prefix keeping them out of discovery. Its *accounts* are live in
`accounts.yaml`; the *campaign* is not. Reviving it means renaming the
folders, and CONTEXT §1 explains what happened last time something half-built
was left in discovery.

**"dallas"** is the only search term still unmet, at 2 searches. Not worth
acting on; noted so nobody re-derives it.

---

## 7. Verification done, so it need not be repeated

- Fan-out dry-run against the real queue: 4 videos × 6 accounts = 24 records,
  slots six hours apart, no two accounts on a network sharing a minute,
  nothing sent to Buffer, queue and history restored afterwards.
- Migration verified through the real models, not the JSON: per-network
  lifetimes came back **332 / 194 / 193 posts** and **74,874 / 12,867 / 5,700
  views**, which is exactly CONTEXT §2's table reconstructed from merged data.
- Dashboard clicked through in a browser for every change: three tabs, the
  creative picker, creating a creative and uploading into it, and the
  per-network analytics panels. Light and dark.
- `--plan` diff before and after the Phase 1 change: identical combination
  counts (19,800 / 478 used), proving the creatives layer changed no output.

---

## Appendix: the original brief

Kept verbatim. Phases 1 and 2 are done; its Phase 3 section is still current.
Its "Assumptions" were resolved as: same rate everywhere (posts_per_day stays
on the brand, queue depth moved to the account), creative selection weighted
with a uniform default, accounts do span two Buffer logins, every brand
reaches every account with an `AccountFilter` escape hatch that defaults to
all, and captions are per network rather than per account.

> # Handoff: multi-creative, fan-out, AI captions
>
> Read `CONTEXT.md`, `SPEC.md` and `tests/test_acceptance.py` before touching
> anything. **Plan first, write no code until the plan is approved.** Deliver
> in the three phases below, each merged and green before the next starts.
>
> ## Phase 1 — Multiple creatives per campaign
>
> A campaign contains N **creatives**. A creative is a self-contained clip
> pool: its own hooks, bodies, and music, with its own licences.
>
> - On each slot: pick a creative (weighted random, uniform by default,
>   optional `weight` per creative in config), then run the existing
>   hook/body/music randomizer *inside* that creative. Clips never mix across
>   creatives.
> - Existing `performance_weight` logic applies within a creative.
> - YouTube's two-bodies-per-video rule still holds, drawn from the same
>   creative.
> - `license_missing` checks per creative.
> - Runway/dedupe reporting per creative **and** a count of distinct visuals
>   (hook × body), not just combinations.
> - The current clips become the first creative of `clubs`. Nothing about
>   existing output should change in Phase 1.
>
> ## Phase 2 — Fan-out: every campaign posts to every connected account
>
> - **Campaign** = a content source: brand, creatives, caption voice, product
>   link.
> - **Accounts** = a global list of Buffer connections (repo-level config).
>   Each connection names the *secret* holding its token.
> - When a slot fires, render **once** and schedule the **same video** to
>   every connected channel.
> - `clubs`, `clubs_tt`, `clubs_yt` collapse into one `clubs` campaign.
>   Migrate `posts.json` history without losing which network/account each
>   post went to.
> - Metrics and posts keyed by **(campaign, creative, account, network)**.
> - Per-account rate and depth cap. Keep `max_backlog_days = 1` semantics.
> - Alerts (`distribution_lost`, `schedule_gap`, `queue_*`) evaluate per
>   account.
> - `src/` stays campaign- and account-agnostic. No slugs or handles in code.
>
> ## Phase 3 — AI captions (Anthropic API)
>
> - Model: `claude-haiku-4-5-20251001`. Call it from a new boundary module
>   only, per the acceptance tests.
> - Inputs per generation: campaign keywords and caption voice; search-volume
>   terms from the existing `demand_unmet` data source; top-performing past
>   captions from `posts.json` (by views and engagement, last N days, per
>   network); the creative/hook being posted, so the caption matches the video.
> - Output formatted per network (length limits, hashtag conventions).
> - **Every caption includes a follow ask.** Zero follows across 719 posts is
>   the worst signal these accounts send (CONTEXT §2).
> - `caption_per_account` config toggle, default `false`.
> - Fallback to the existing caption bank on any API failure; posting never
>   blocks on the model.
> - Log prompt, response, and which winners and terms were used, per post.
> - API key goes in **both** `.env` and GitHub secrets (CONTEXT §7).
> - `demand_unmet` should keep working against AI-written captions.
>
> ## Constraints (from CONTEXT, do not undo)
>
> - Acceptance tests are load-bearing. `requests` and the Anthropic SDK stay
>   in boundary modules, `datetime.now()` only in `ports.py`/`logging.py`, and
>   no campaign or account names in `src/`.
> - Config models use `extra="forbid"`. Every new field means a dashboard
>   restart; make sure `restart_needed` still fingerprints the new config
>   files.
> - `_knick_creates*` stays parked unless told otherwise.
