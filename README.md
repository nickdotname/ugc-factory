# ugc-factory

Unattended pipeline that assembles short vertical videos from a library of parts
and publishes them to Instagram Reels on a schedule. See [SPEC.md](SPEC.md).

---

## §0 — Buffer API verification

**Verified 2026-08-12 by GraphQL introspection against the live API** using the
existing personal access token. Read-only: no posts were created.

### Answers

| Question | Answer |
|---|---|
| API surface | `POST https://api.buffer.com`, single GraphQL endpoint, `Authorization: Bearer <personal API key>`. The legacy REST API is not used. |
| Does `createPost` accept video by URL? | **Yes.** `AssetInput.video` → `VideoAssetInput { url: String! }`. URL-only — there is no upload field. |
| Is there a `post_type` enum value for reel? | **Yes.** `PostType.reel` exists (alongside `post`, `story`, `carousel`, `short`, `thread`, …). It is set via `metadata.instagram.type`, **not** a top-level `post_type` field. |
| Can it publish directly rather than in reminder mode? | **Controllable and readable, but not yet provable for Instagram on this account — see the blocker below.** |

### How reminder mode actually works

`CreatePostInput.schedulingType` is a required enum with exactly two values, and
Buffer's own descriptions are unambiguous:

- `automatic` — "Buffer's publishing workers send the post, with nobody having to act"
- `notification` — "Buffer reminds someone to publish the post by hand"

This is a **per-post input**, so the publisher requests `automatic` explicitly.
The channel's default is separately readable at
`Channel.metadata` → `InstagramMetadata.defaultToReminders` (resolved from
`profile.default_to_reminders`).

`src/publishers/buffer.py` requests `automatic` **and verifies what came back**:
if Buffer returns a post whose `schedulingType` is `notification`, that is raised
as a hard `InvalidPostError` rather than reported as success. A silent downgrade
would look like a working pipeline that never actually posts.

### ⚠️ Blocker: no Instagram channel is connected

The Buffer account currently has **two channels, neither of them Instagram**:

| channel | service | type |
|---|---|---|
| nickdotname | tiktok | account |
| Nickdotname | youtube | channel |

So the final end-to-end question — *does a real Instagram Reel publish
automatically on this account* — **cannot be answered until an Instagram channel
is connected.** Everything up to that point is verified.

**To finish §0:**

1. Connect an Instagram channel in Buffer. It must be a **Business or Creator**
   account — Instagram's publishing API does not permit unattended posting to
   personal accounts, which is what forces reminder mode.
2. Read back its default:
   ```bash
   BUFFER_API_KEY=... python scripts/check_channel.py
   ```
3. Run the live publish check against a throwaway account (SPEC §13 M6 — not
   `@clubs.create`):
   ```bash
   UGC_LIVE_BUFFER=1 UGC_LIVE_BUFFER_PUBLISH=1 \
   BUFFER_API_KEY=... BUFFER_TEST_CHANNEL_ID=... BUFFER_TEST_VIDEO_URL=... \
   pytest tests/test_buffer_live.py -v
   ```
   It creates one real post two days out and deletes it again. If it fails with
   "not 'automatic'", the channel is in reminder mode and SPEC §0's fallback
   applies: the Instagram Graph API directly, with Meta app review (2–4 weeks).

### Two corrections to SPEC.md

**§4.2 is wrong.** It states "No edit or delete via the API." The live schema
exposes **`deletePost`** *and* **`editPost`** as mutations:

```
createPost(input: CreatePostInput!): PostActionPayload!
editPost(input: EditPostInput!):     PostActionPayload!
deletePost(input: DeletePostInput!): DeletePostPayload!
movePostInQueue(...)
```

This is implemented as `Publisher.delete_post`. It matters for crash recovery —
a duplicate that reaches Buffer *can* now be pulled by code. It does **not**
soften the validation gate: deletion only helps while the post is still queued.
Once Instagram publishes it, it is out. So §6's hard-fail validation and §11's
claim-before-push both stay exactly as specified.

**The prior integration is not what §0 assumed.** SPEC §0 warns the existing
Telegram integration might use "a legacy client_id" on the REST API. It does
not — [`clubs-engine/src/publisher/BufferAdapter.js`](file:///Users/nickbenak/clubs-engine/src/publisher/BufferAdapter.js)
already uses GraphQL with a Bearer token, and already publishes **video** to
TikTok and YouTube with `schedulingType: 'automatic'`. That is useful evidence
that URL-video + automatic scheduling works on this account — for those two
networks. It says nothing about Instagram Reels, which is a separate channel
type with a separate reminder policy.

Per SPEC §0, the Buffer publisher here was **written from scratch** against the
introspected schema, not ported.

### Error contract

`PostActionPayload` is a union, so every failure mode is a distinct type. The
publisher dispatches on `__typename` and never on message text (SPEC §2.2):

| Buffer type | Mapped to | Retryable |
|---|---|---|
| `PostActionSuccess` | — | — |
| `UnauthorizedError` | `AuthError` | no |
| `InvalidInputError` | `InvalidPostError` | no |
| `NotFoundError` | `InvalidPostError` | no |
| `LimitReachedError` | `QuotaError` | no |
| `UnexpectedError` | `PublishError` | yes |
| `RestProxyError` | by `code`: 4xx → `InvalidPostError`, else `PublishError` | by code |
| *unknown* | `PublishError` naming schema drift | no |

---

## Status

| Milestone | State |
|---|---|
| 1. Config + validation | done |
| 2. Renderer (ffmpeg, local) | done |
| 3. Selector + history | done |
| 4. GitHub Releases media store | done |
| 5. Queue + state machine | done |
| 6. Buffer publisher | code done; **live Reel check blocked on an Instagram channel** |
| 7. Workflows | done — `workflow_dispatch` + cron, all defaulting to dry run |
| 8. Preflight / notify / cleanup | done |
| 9. Second campaign | proven by test; no `src/` change needed |

250 tests, 3 skipped (the live-API ones). `mypy --strict` clean.

```bash
pip install -r requirements-dev.txt
mypy src/ && pytest
```

---

## Start here

```bash
./ugc setup --campaign clubs
```

Use `./ugc` rather than `python -m src.cli`. Your shell's `python` is often
some other environment (Anaconda, a system 3.9) whose pydantic is too old, and
the resulting import error looks like a bug in this project rather than a PATH
problem. The wrapper always uses `.venv`, and creates it if missing.

Checks all four systems this depends on — git repo, GitHub Secrets, the Buffer
channel, the assets Release — and prints the exact command to fix each gap. Run
it any time you are unsure what state things are in.

```
  OK  config                        clubs · instagram · reel · 2/day
  OK  github repo                   nickdotname/ugc-factory
   x  secret BUFFER_API_KEY         not set — Buffer personal API key
  OK  buffer channel                instagram · nickdotname · automatic
   x  assets release                empty
   x  descriptions                  3 records · still template text

Next:
  1. secret BUFFER_API_KEY — gh secret set BUFFER_API_KEY --repo owner/repo
  2. assets release — ./ugc web --campaign clubs
```

It never handles secret values: `gh secret set` prompts you for those, so they
never pass through this tool.

## Setup checklist

1. **Make the repo public** (SPEC §3). Public repos get unlimited Actions
   minutes, and — more importantly — Release assets are publicly fetchable,
   which is what Buffer's URL-only media upload requires. Secrets live in
   GitHub Secrets; nothing sensitive is in the tree.

2. **Drop your videos in, using the local web app** (or `ingest` from a
   terminal — same pipeline either way).

   ```bash
   ./ugc web --campaign clubs
   ```

   Opens `http://127.0.0.1:8765`: three drop zones for hooks / bodies / music,
   an editor for descriptions, a live library-health panel, and an upload
   button. It binds to loopback only — it writes files and borrows your `gh`
   token, so it must never be reachable from the network. It auto-detects the
   repo from your git remote and the token from `gh auth token`, so there is
   nothing to export.

   The terminal equivalent: You never name a file
   yourself and never touch the Release by hand.

   ```
   inbox/clubs/
     hooks/     <- hook clips
     bodies/    <- main videos
     music/     <- tracks
   ```

   Filenames do not matter — spaces, capitals, `FINAL_v3 (copy).mp4`, anything.
   The *folder* is what assigns the role. Then:

   ```bash
   ./ugc ingest --campaign clubs
   ```

   It probes every file, rejects what genuinely cannot work, generates correct
   names (continuing the existing sequence, never overwriting), creates the
   `assets-clubs` Release if needed, uploads, and moves the originals into
   `inbox/clubs/_uploaded/` so re-running is safe. `--dry-run` shows the plan
   without uploading.

   ```
     * My Cool Hook v2 FINAL.mp4  -> hook_03.mp4
     x broken.mp4                 -> skipped
         not a readable video file - moov atom not found
     x wrong place.mp3            -> skipped
         .mp3 is not accepted here (expected .mp4, .mov, .m4v, .webm)
     ! main video LANDSCAPE.mov   -> body_01.mov
         1920x1080 is not vertical - will be centre-cropped to 9:16
         no audio track - silence will be added automatically
     * some song.mp3              -> music_01.mp3

   library: 6 hooks - 3 bodies - 5 music - 5 captions
            450 combinations = 225 days at 2/day (target 90)
     library supports the configured cadence with no relaxation
   ```

   Landscape footage and silent clips are **warnings, not rejections** — the
   renderer centre-crops to 9:16 and adds silence automatically. Only unusable
   files are skipped, and those stay in the inbox for you to fix. Full rules in
   [inbox/README.md](inbox/README.md).

   Also upload `LICENSES.md` listing each track's source and licence (SPEC §4.4).

3. **Add repository secrets:**

   | secret | what |
   |---|---|
   | `BUFFER_API_KEY` | personal API key, Buffer → Settings → API |
   | `BUFFER_CHANNEL_CLUBS` | the Instagram channel id |
   | `DISCORD_WEBHOOK_CLUBS` | alerting webhook |

   `GITHUB_TOKEN` is injected by Actions automatically.

4. **Write the description bank** at `campaigns/clubs/captions.txt` — the text
   each video is posted *with*. One record per block, blank line between
   records. It lives in the repo rather than the Release because it is text.

   This is **never drawn onto the video**. On-screen subtitles are baked into
   your source clips before they reach the pipeline; the renderer has no text
   filters at all.

## Text limits per platform

Verified August 2026 and held in one table in [src/platforms.py](src/platforms.py),
not scattered as magic numbers. Descriptions are validated against the
campaign's `buffer.service` at **preflight**, so an over-long one fails before
it costs API quota at publish time.

| platform | description | separate title |
|---|---|---|
| Instagram | 2,200 | none |
| TikTok | 4,000 | none |
| YouTube | 5,000 | **100, required** |

YouTube is the odd one out: it has a short title *in addition to* its
description, and rejects a post without one. Give a record a title with a
leading `title:` line:

```
title: A Short Punchy Title Under 100 Chars
The long description body goes here, and may
run across as many lines as you like.
```

A `title:` line on an Instagram or TikTok campaign is ignored, so one bank can
serve several campaigns. What you get if you point the same bank at the wrong
platform:

```
 instagram: OK
    tiktok: OK
   youtube: description #1: youtube requires a title; add a 'title:' line

2500 chars on  instagram: description is 2500 characters, over instagram's 2200 limit
2500 chars on     tiktok: OK
```

`buffer.service` also drives which metadata block the publisher builds, and
config rejects a mismatched `post_type` — a YouTube channel set to post `reel`,
or an Instagram channel set to `short`, fails at load rather than as an opaque
Buffer rejection later.

5. **Dry run first:**
   ```bash
   gh workflow run preflight.yml -f campaign=clubs
   gh workflow run render.yml -f campaign=clubs -f dry_run=true
   ```
   Inspect the rendered videos in the dated Release before turning `dry_run`
   off in `campaigns/clubs/config.yaml`.

6. **Leave the cadence where it is** for two weeks (SPEC §4.5). Buffer's quota
   permits 24/day; Instagram's spam classifier is a separate system that does
   not care what Buffer permits. Watch reach-per-post, then raise — see sizing
   below for what raising it costs.

## Sizing your library

The combination count is rarely what limits you — **cooldowns are**. A cooldown
of N days at P posts/day needs N x P distinct assets to never repeat inside the
window. Fall short and the selector relaxes its rules and alerts, every day —
which is indistinguishable from being broken.

`ingest` computes this for you and warns while you are still holding the files.
`preflight` fails if the runway drops under `selection.min_runway_days`.

The shipped `clubs` config is tuned for ~6 hooks / ~3 bodies / 5 music /
5 captions at **2 posts/day**, which clears every cooldown with room to spare:

| | have | 2/day needs | 6/day would need |
|---|---|---|---|
| hooks (2-day cooldown) | 6 | 4 | 12 |
| captions (2-day cooldown) | 5 | 4 | 12 |
| combinations | 450 | — | — |
| runway | 225 days | — | 75 days |

Captions are by far the cheapest dimension to grow — they are just text. At
~25 captions the same clip library comfortably supports 6/day. Body clips are
the most expensive: at 3 bodies and 6 posts/day each main video goes out twice
a day, and unique tuples do not make that look different to a viewer.

### Where credentials live

Two stores, and confusing them is the usual cause of "posting works but the
dashboard cannot see my channels", or its mirror image:

| | read by | holds |
|---|---|---|
| `.env` at the repo root | the dashboard only | gitignored, `0600`, this machine |
| GitHub Actions secrets | the workflows only | what actually posts |

The dashboard's **Keys** panel writes both. Paste a value once and it lands in
`.env` and, via `gh secret set`, in the repository's Actions secrets. It shows
which campaigns need each name and which store currently has it; neither store
can be read back, so a value is replaced by pasting a new one, never edited.
The value goes to `gh` on stdin rather than as an argument, since arguments are
visible to every process on the machine.

"Forget locally" drops the `.env` copy only. Deleting the GitHub copy would
silently stop a campaign, so it is not offered here — do that in the
repository's settings, deliberately.

### One library, several campaigns

Campaigns posting the same content to different networks point at one assets
Release via `assets_release`, and the drop folder follows the Release rather
than the slug. `clubs`, `clubs_tt` and `clubs_yt` all read `assets-clubs`, so
they all share `inbox/clubs`: three more hooks go in once, upload once, and are
live in all three on the next render. A campaign with its own Release keeps its
own folder, since `assets-<slug>` reduces to the slug.

The roster below stays per-campaign, which is the useful half of the split — a
clip can run on TikTok and sit out on YouTube.

### Taking a clip out of the mix

A clip that stops working does not have to be deleted. Every campaign has a
roster — `campaigns/<slug>/clips.json` — listing the assets held back from the
randomizer:

```json
{ "disabled": ["hook_04.mov", "body_02.mp4"] }
```

Anything not listed is live, so a freshly uploaded clip needs no switching on.
Muted clips are removed from the library *before* the selector sees it, which
is what keeps the numbers honest: combinations, runway and the cooldown
warnings all describe the clips actually in rotation.

The dashboard (`./ugc web`) has a **Randomizer** panel — one card per clip with
a thumbnail you can play, a switch, and a live combination count that moves as
you flip them. The same thing from a terminal:

```bash
./ugc clips --campaign clubs                      # list, with on/off state
./ugc clips --campaign clubs --off hook_04.mov    # hold it back
./ugc clips --campaign clubs --on  hook_04.mov    # put it back
./ugc clips --campaign clubs --all-on --kind body # whole role at once
```

`clips.json` is campaign state like `history.json`: the change reaches the
render job when it is committed and pushed, not when it is saved.

Deleting a clip for good is a separate, irreversible action — the × on a clip
card removes it from the assets Release, behind a confirmation, and a re-upload
comes back under the next free number. Muting is the reversible one, and is what you usually
want.

---

## Findings

The dashboard's **Findings** panel derives what can honestly be concluded from
files already on disk — no API calls, so it costs nothing against the request
allowance. Three properties of the data shape all of it:

**Metrics are channel aggregates, not per-post.** `aggregatedPostMetrics`
returns window totals. Nothing links a view to a video, so clip-level ranking
cannot be derived at any sample size — the panel says so rather than omitting
the question.

**Six daily snapshots is not a trend.** Correlation over that many points is
noise with a decimal point, so none is computed until there are meaningfully
more.

**The cross-platform comparison is unusually strong.** The three campaigns post
*the same clips with the same captions* to three networks: content is held
constant by design and each side aggregates ~145 posts, so differences are
about the platform rather than the content. Everything is normalised per post
before comparison — raw totals mostly measure how often each channel was posted
to.

A metric a network does not report is shown as `n/r`, never as zero. YouTube
reports no reach; treating that as zero would imply nobody saw it.

---

## Reviewing what goes out

The render-to-push gap is the human review window, and the dashboard's **Queue**
panel is where you use it. Every scheduled item shows its slot time, caption,
the clips it was built from, and the actual rendered video — played straight
from its public Release URL, so what you preview is byte-for-byte what Buffer
fetches.

**Pull** withdraws one item. What that means depends on where it is:

| state | what pulling does |
|---|---|
| `pending` | records the decision; the top-up job skips it. No API call. |
| `pushed` | asks Buffer to delete the post, *then* records it. |
| `claimed` | refused — it may be mid-push right now. Reconcile first. |

Cancelling is deliberately not `failed`: nothing went wrong, somebody decided.
Conflating them would put a normal editorial choice into the failure alerts.

A `pushed` item can only be withdrawn while Buffer is still holding it. Once the
network has published, Buffer's `deletePost` no longer helps and the panel says
so rather than reporting a success it did not achieve. For the same reason a
pushed item is never marked cancelled when the key is missing — a queue file
claiming "stopped" while the post goes out anyway is worse than a refusal.

### The request allowance

Buffer's free plan allows 3,000 requests per 30 days, and that allowance belongs
to the **Buffer account**, not to a campaign — three campaigns on one key spend
one pot. The strip above the queue shows the rolling total across every campaign
sharing the key.

Each campaign writes only its own `quota.json` and the total is summed when
read. A single shared counter would race: campaign workflows have separate
concurrency groups, so two can run at once and a read-modify-write from both
loses one.

---

## Revenue

Buffer reports reach, never money, so revenue enters from outside — typed into
the dashboard's Revenue panel, or eventually through a `RevenueFetcher`. It
lands in `campaigns/<slug>/revenue.json` as a ledger of *periods*, because
money does not arrive daily: a brand deal is one date, an affiliate payout a
week, an app payment a month.

Any query pro-rates an entry across the days it covers, which is what makes
"revenue over this window" well defined. That matters because `metrics.json`
stores **trailing aggregates, not daily increments** — views on 2026-08-19
means the 30 days ending then. Pairing that with one week's revenue would
understate the ratio roughly fourfold, so every ratio pulls revenue from the
snapshot's own window.

| shown | what it means |
|---|---|
| revenue per 1,000 views | that window's money ÷ that window's views |
| revenue over time | payouts spread evenly across the days they cover |
| blended per 1,000 | every campaign's money against every campaign's views |

Two entries from *different* sources overlapping is normal — a brand deal
during an affiliate week is two real payments. The same source twice over one
day is a duplicate, and it is reported rather than merged, because every total
is wrong until it is fixed.

---

## How it runs

```
NIGHTLY RENDER (05:00 UTC)              TOP-UP (every 4h)
┌──────────────────────────┐            ┌──────────────────────────┐
│ download assets Release  │            │ reconcile stranded items │
│ select N combinations    │  queue     │ read Buffer queue depth  │
│ render + validate        │ ────────►  │ push (cap − depth) items │
│ upload to dated Release  │  .json     │ claim→commit→push→commit │
│ write queue + history    │            └──────────────────────────┘
└──────────────────────────┘                        │
                                          Buffer publishes on its
                                          own schedule → Instagram
```

The render→push gap is the human review window. Nothing rendered tonight can
publish before tomorrow.

### Commands

```bash
./ugc render    --campaign clubs [--dry-run] [--count N]
./ugc topup     --campaign clubs [--dry-run] [--no-commit]
./ugc preflight --campaign clubs
./ugc cleanup   --campaign clubs [--digest]
./ugc clips     --campaign clubs [--on NAME…] [--off NAME…] [--all-on|--all-off]
```

### Why the top-up job exists

Buffer's free plan caps **queue depth** at 10 per channel — not posts per day. A
slot frees when a post publishes. So the render job cannot dump 24 posts in at
once; the top-up job tops the queue back up to the cap every four hours, and
Buffer's own scheduler decides when each one actually goes out.

### Crash safety

The top-up job writes `claimed` **and commits it to git** before calling Buffer.
Actions runners are ephemeral, so the commit is the only durable record. A job
that dies between the two leaves `claimed` in the repo, and the next run queries
Buffer for a post at that slot before deciding — rather than blind-pushing a
duplicate.

---

## Adding a campaign

No code changes (SPEC §15). If any step needs a `src/` edit, the abstraction
failed — extend the schema in `src/config.py` instead of branching on slug.
There is a test asserting `src/` contains no campaign slug.

```bash
cp -r campaigns/_template campaigns/<slug>
```

Then fill `config.yaml` and `captions.txt`, connect the channel in Buffer,
upload assets to `assets-<slug>`, add `BUFFER_CHANNEL_<SLUG>` and
`DISCORD_WEBHOOK_<SLUG>`, add `<slug>` to the matrix in `render.yml`,
`topup.yml`, `preflight.yml` and `cleanup.yml`, and dispatch with
`dry_run: true`.

The template ships with `dry_run: true` so a new campaign cannot post before
you have looked at its output.

---

## Layout

```
src/
  cli.py            composition root — the only place real Clock/Rng/HTTP/git are built
  config.py         pydantic schema; the only place campaign differences exist
  errors.py         exception hierarchy; retryability is a class property
  ports.py          Clock and Rng — injected, never called directly elsewhere
  logging.py        structured JSON to stdout, correlation id per item
  models.py         typed shapes crossing module boundaries
  render.py         ffmpeg two-stage pipeline  ← only module using subprocess for media
  selector.py       combination picking, LRU weighting, relaxation ladder
  clips.py          the per-campaign roster: which clips the randomizer may use
  revenue.py        dated money ledger + the ratios against reach
  quota.py          rolling Buffer request tally, summed per API key
  insights.py       cross-campaign findings, and what cannot be concluded
  keys.py           credentials: local .env and GitHub Actions secrets
  assets.py         MediaStore ABC + GitHub Releases
  queue.py          state machine + atomic persistence
  vcs.py            git boundary — the durable claim
  notify.py         alerts + weekly digest
  publishers/
    base.py         Publisher ABC — TikTok/Graph API slot in here
    buffer.py       Buffer GraphQL
```

### Things that look arbitrary and are not

- **Two-stage render.** The concat demuxer stream-copies, so it needs every
  input to already agree on resolution, fps, SAR, codec *and stream layout*.
  Real clips agree on none of those and some have no audio track. Stage 1
  re-encodes each to an identical shape; stage 2 concatenates with `-c copy`.
- **Silent audio via `anullsrc`, not `-an`.** A clip with no audio stream is the
  single most common cause of silent concat corruption.
- **`-movflags +faststart`.** Instagram needs the moov atom at the front. There
  is a test asserting `moov` precedes `mdat`.
- **`amix=normalize=0`.** With the default `normalize=1` ffmpeg divides every
  input by the number of inputs, halving the spoken audio and making
  `music_volume` mean something other than what it says.
- **`-fflags +bitexact` and `-map_metadata -1`.** Strips encoder version and
  timestamps so identical inputs give byte-identical output. There is a test
  asserting two renders are byte-for-byte equal.
- **A custom YAML loader.** PyYAML implements YAML 1.1, where `on`/`off`/`yes`/
  `no` are booleans — which turns SPEC §9's `notify.on:` key into the Python key
  `True`. The loader restricts booleans to `true`/`false`.
- **The nightly commit.** GitHub disables cron after 60 days with no repository
  commits. Removing the commit as an "optimization" stops the pipeline about two
  months later, silently.
