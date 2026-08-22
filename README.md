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

## Per-network publishing levers

Buffer's `PostInputMetaData` carries a different input per network, and
several useful fields were going unused. Found by introspecting the schema
rather than assuming — the same move that settled the per-post metrics
question.

| field | network | what it does |
|---|---|---|
| `firstComment` | Instagram | posts a pinned first comment |
| `shouldShareToFeed` | Instagram | Reel also appears in the main feed |
| `notifySubscribers` | YouTube | pushes the Short to subscribers |
| `title` | YouTube | the search surface for a Short |

`buffer.first_comment` is where a link belongs on Instagram. One in the
caption is not clickable, and it displaces the opening words that both search
and the scroll-stop read. Empty means no comment is posted — an empty string
would post an empty comment rather than none.

`buffer.notify_subscribers` is off by default. Notifying a subscriber list a
dozen times a day is a good way to lose it; it is worth turning on for a
channel posting a few times a day.

Both are editable from the dashboard's Settings panel.

---

## Video limits per platform

Text limits were always per-platform; video was not. Every campaign carried
its own `video.max_duration_sec` and the renderer enforced only that, while
calling every limit "the Reels ceiling" regardless of where the video was
going.

| | duration | file | note |
|---|---|---|---|
| Instagram | 3–90s | 100 MB | |
| TikTok | 3–180s | 500 MB | permits far longer; nothing here wants it |
| YouTube | 3–**60s** | 100 MB | the one that bites |

YouTube is the dangerous one, because a Short is a Short *because of its
length*. A video over the boundary is not rejected — it is published as an
ordinary video, losing the whole Shorts surface, with no error anywhere to
explain why that post did nothing.

The 60s figure is deliberately the old boundary rather than the extended one.
The asymmetry decides it: capping short costs a length nothing here wants,
while capping long risks silent reclassification. Verify before relying on
headroom above 60s.

Renders are validated against **the tighter of config and platform**, so a
generous config cannot produce a file the platform will reject or reclassify,
and a deliberately strict config is still honoured.

Duration is decided by which clips get picked, and the selector never probes
the video parts — so `preflight` does the arithmetic instead, comparing the
longest possible cut (longest hook + longest N bodies) against the ceiling. On
the live library that is 15.2s at one body per video and 49.6s at four, so the
whole range fits every platform.

---

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

The live `clubs` library is 6 hooks / 4 bodies / 3 music tracks (33 beds, since
each track is cut into segments) / 25 captions, at **12 posts/day**:

| | have | 12/day needs |
|---|---|---|
| captions (2-day cooldown) | 25 | 24 |
| hooks (cooldown disabled) | 6 | — |
| combinations | 19,800 | — |
| runway | 1,650 days | 90 (`min_runway_days`) |

Those figures come from `./ugc preflight`, which probes every track to count
beds rather than assuming a number.

The dashboard's Library panel leads with the repeat rate for this reason, and
keeps runway as a quiet footnote. The runway number is not the useful one. 1,650 days of unique tuples says
nothing about whether a viewer can tell two of them apart: with 4 body clips at
12 posts/day, each one goes out three times a day whatever the combinatorics
say. **Body clips are the binding constraint, and no amount of unique hashes
fixes it.**

### Varying the shape, not just the look

`composition.bodies_per_video_max` lets a video use a *range* of body clips
rather than always the same number. It is the one structural lever available
without new footage, and on the live library it is worth more than any grade:

| bodies per video | body shapes | combinations |
|---|---|---|
| 1 | 4 | 21,600 |
| 1–2 | 10 | 54,000 |
| 1–3 | 14 | 75,600 |

Four clips, 2.5× the shapes. A two-body cut is also a different *length* from
a one-body cut — roughly 23s against 13s — and length is itself worth testing
rather than holding constant.

The count is drawn once per video, before the relaxation ladder, so a pick
that needs relaxing keeps the shape it started with instead of quietly
becoming a different structure.

Reordering is deliberately **not** a new combination. `tuple_hash` sorts the
body list, so `A→B` and `B→A` collide. The same two clips in a different order
is very nearly the same video to a viewer, and counting it as new would let
visibly similar cuts through — which is the thing the whole dedupe ladder
exists to prevent.

### How evenly clips are actually used

Selection is LRU-weighted so a night does not cluster on one clip. Two details
make that work, both of which were once wrong:

**Weights are by rank, not elapsed days.** `age_in_days + 1` has no resolution
below a day, and a night's batch is picked in a single instant — so every clip
chosen that evening collapsed to the same weight, and once each had been used
once the rest of the batch was uniform random. Ranking is scale-free and
discriminates identically at any timescale.

**A pick counts as recent for the picks that follow it.** `history` does not
change while a batch is built, so the whole night used to see identical
last-used data.

Those picks feed the *weighting* only — never the cooldown filter or tuple
dedupe. Applying a cooldown inside a batch would mean six hooks cannot fill
thirty videos under a three-day cooldown, which is true but is a statement
about library size. It belongs in `library_health` and preflight, not in
relaxing dedupe mid-render every night.

Measured over 20 seeds, this cuts how often a single body clip repeats within
one night by 10–19%:

| posts/night | even split | before | after |
|---|---|---|---|
| 6 | 1.5 | 2.94 | 2.38 |
| 12 | 3.0 | 4.95 | 4.31 |
| 24 | 6.0 | 8.66 | 7.84 |

Cumulative distribution over a fortnight barely moves — across-night LRU was
already self-correcting. The gain is in what a viewer experiences, which is a
day rather than a fortnight.

Captions are the cheapest dimension to grow — they are text — and 25 is only
just over the 24 the cooldown needs. One caption removed and the selector starts
relaxing.

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

## Creative variation per render

Every render can carry its own treatment: a punch-in with a nudged crop anchor,
a fraction of a degree of rotation, a grade shift, film grain, and a slightly
different pace. `variation.enabled` turns it on, per campaign, and it is off by
default because it changes how every video looks.

The treatment is **seeded on the item id**, so `variant-a` looks the same on
any machine on any day. That is the point: a cut that performs is worth knowing
the recipe for, and the recipe is logged with the render and recorded flat in
`Treatment.as_dict()`. An unseeded `random()` would make the A/B data
worthless. Seeding on Python's `hash()` of the id would too — str hashing is
salted per process, so the same variant would look different on every run.

Two things about the numbers. They are set to the low end of what a viewer
notices as *a different edit*, not the high end of imperceptible: two cuts a
person cannot tell apart are the same cut for every purpose that matters,
including whichever one you hoped would win. And `1080x1920` never jitters —
odd resolutions get downgraded in delivery.

The filter order is load-bearing:

```
scale (overscan) -> rotate -> crop back to frame -> hflip -> grade -> grain -> setpts
```

Rotating a 9:16 frame by 0.6° and cropping back needs about 2% more material
than the frame, or the corners show black wedges — so the zoom is raised to
cover the rotation whenever there is one. Grain goes after the grade, or it is
graded along with the picture and stops reading as grain. Audio is retimed with
`atempo` whenever the picture is retimed; leaving it alone drifts a second
every thirty, and it accumulates across every part of a concatenated video.

Mirroring is available and off: it reverses any on-screen text and flips a
logo, so it is only safe on shots with neither.

The recipe is **written down**, not recomputed. `treatment_for` depends on the
campaign's variation config, so the moment that config changes the treatment
behind an older winner becomes unrecoverable — and the render log is no home
for it either, since Actions logs expire. Every rendered item records its
treatment in `queue.json` and, durably, in append-only `history.json`, which
is what a per-post performance figure will eventually join to. An untreated
render records `null` rather than a row of zeros that would read as a real
recipe. The queue panel shows the short form on each row:
`+2.4% punch · +0.42° · sat 0.92 · 0.997x`.

The music bed gets its own treatment — tempo and a shelf tilt, per variant.
It is deliberately separate from the picture's `speed`: nothing is
synchronised to the bed, so it can move freely, while the clip's own audio
must be retimed in lockstep with the video or it drifts. The tilt is a tilt
rather than a boost — the top lifts by the same dB the bottom trims — so
`music_volume` keeps meaning what it says. Bed filters run *before* the trim,
since `atempo` changes how much material a given number of seconds holds, and
trimming first would leave the bed short of the video.

---

## Brands and channels

A campaign is one channel, because the pipeline needs it to be: YouTube
demands a title and caps a Short at 60s, TikTok uses a different post type,
Instagram is a Reel. Those differences are real and they belong in config.

They do not belong in the interface. The unit worth looking at is the
**brand** — one set of clips going out across its networks — so the dashboard
groups campaigns by the assets Release they share, which is by construction
the same brand posting the same material to different places. Selecting a
brand scopes everything to it: all-time totals, the trend chart, the platform
cards, findings and revenue. A second row appears underneath for moving
between that brand's networks, and is hidden when a brand has only one.

The quota panel is deliberately *not* brand-scoped. The request allowance
belongs to the Buffer account, and several brands can share one key.

Before this, selecting a brand changed the tab and the queue while "all time"
carried on summing every campaign in the repo — so a brand created a minute
ago appeared to have already published 569 videos.

---

## Switching campaigns

The header is a tab per campaign, showing its network underneath and marking
a paused one where you are already looking. A dropdown hid the thing you were
choosing between — on macOS it also drops the popup with the *current* item
under the cursor, so the campaign you were on appeared to be missing from its
own list.

Clicking a tab reloads every panel. An earlier version refreshed six of them
and left findings, keys and charts showing the campaign you had just
navigated away from.

Unticking **share the clip library** when creating a campaign genuinely gives
it its own Release and its own drop folder. It used to send an empty string,
which is falsy, so the server treated it as "not supplied" and shared the
library anyway — silently, and exactly opposite to what was asked.

---

## Changing settings without opening the file

The dashboard's **Settings** panel edits `campaigns/<slug>/config.yaml`
directly — cadence, backlog depth, the body-clip range, creative variation,
mirroring, target keywords, and the pause switch.

It edits **one line** and leaves the rest byte-identical. A campaign config is
roughly a third comments and they carry the reasoning behind the numbers;
`yaml.safe_dump` would discard every one of them and reorder the keys as well.
So the write is surgical, and then it is proved: the file is re-parsed through
the real loader, and if that fails for any reason the original text goes back.
A config the pipeline cannot parse would stop the nightly render, which is far
worse than a setting not sticking.

Only an allowlist is editable. Credentials and channel bindings are not on it.
Pushing is still what makes a change reach the workflows.

---

## Being found in search

Both TikTok and YouTube index text and serve it through search, which is the
traffic that does not decay the way a feed placement does. They index
**different fields**, and getting it backwards means posting something
unsearchable:

| platform | indexed field |
|---|---|
| TikTok | caption |
| Instagram | caption |
| YouTube | **title**, not the description |

Set `seo.keywords` on a campaign and the description bank is linted against
them: whether a target phrase appears in the field that platform actually
searches, and whether it appears in the first few words, since front-loading
is what ranks. Matching is case-insensitive and on word boundaries, so `nyu`
does not match `denyung` and report a keyword as covered when it is absent.

These are notes, never errors. A post with no keyword publishes perfectly
well — it is just invisible to everyone who arrives by searching. Run
`./ugc setup --campaign <slug>` or open the Descriptions panel to see them.

---

## Seeing a video before it exists

The **Render a sample** button in the Randomizer panel builds one video from the
clips currently switched on and plays it in the page. It queues nothing, uploads
nothing and posts nothing.

It writes to neither `queue.json` nor `history.json`, which is the point:
recording a sample would mean looking at your own library cost you a unique
combination of runway, and the dedupe record would claim a video was used that
nobody ever saw. History is still *read*, so a sample never shows a combination
already spent — it is what tonight would actually produce.

Renders take a few seconds and reuse one file at
`work/<slug>/samples/sample.mp4`, since samples are disposable and a pile of
100 MB videos is not.

---

## The weekly digest

The digest is the only thing that reaches a human without them opening
anything, so it carries the findings rather than just queue health — the
rolling request total against the allowance, the share of rendered videos
that actually reached a network, and a warning when the whole caption bank
uses one call to action. Everything in it is derived from files on disk, so
it costs no API calls.

It now omits what it cannot compute. Two lines were previously printed as
hard zeros whatever the truth was: every digest claimed `0 / 3000` requests
and `days until first repeat: 0` — one falsely reassuring, one falsely
alarming, and both undermining the rest of a report whose whole job is to
make silence unambiguous.

---

## Is the variation doing anything?

The variation engine applies a different punch-in, grade, grain and pace to
every video, and until now nothing asked whether any of it helps. The recipe
is recorded per post precisely so it can be.

Each knob is split at its median into a low and a high half and the two are
compared with a rank test — ranks, because views are lognormal and nowhere
near normal.

The bar is the interesting part. There are twelve knobs, and testing twelve
things at the usual 5% gives a **46% chance of declaring a winner every
week** whether or not variation does anything at all. That is a machine for
manufacturing findings. So the threshold is divided by the number of
parameters tested, and simulation confirms the result: across twenty runs
where variation genuinely did nothing it reported an effect **zero** times,
and across twenty where zoom genuinely mattered it found it **twenty** times
— naming zoom rather than one of the other eleven.

"No setting is measurably changing results" is a real answer rather than a
missing one: it means the variation is making cuts distinct without any
single knob being worth tuning.

---

## Suggesting a clip be cut

Ranking last is not evidence of anything. With six clips of identical quality
each one comes last about a sixth of the time, because something always is —
simulating that is what ruled out the obvious implementation.

Comparing medians directly does not work either: a median over five posts of
a lognormal quantity is itself extremely noisy.

What survives is a sign test. Count how many of a clip's posts land below the
median of the **other** clips in its field; if the clip is ordinary that is a
coin flip each time, so a long run is unlikely in a way that can be
quantified rather than eyeballed. The leave-one-out part matters — with four
clips, a clip is a quarter of any pooled median, which drags the bar toward
it and hides exactly what this is looking for.

The thresholds were chosen by simulation rather than taste: twelve posts and
80% below fires on about 3% of clips that are fine and catches about 62% of
clips genuinely three times worse. Twelve at 75% roughly triples the false
positives for a little more sensitivity, which is the wrong trade for
something a person will act on.

It is a suggestion and never an action. Muting is reversible from the
Randomizer panel, and roughly one in thirty of these will be a clip that was
doing nothing wrong.

---

## Acting on what wins

Attribution reports; `selection.performance_weight` acts. At 0 — the default
— selection stays blind to results, exactly as it always was. Above 0 it
scales each clip's weight by how it has performed.

Three brakes, because weighting toward winners is a feedback loop by
construction: a clip picked more gathers more evidence, which gets it picked
more.

- **Rank, not magnitude.** Social metrics span orders of magnitude and the
  size of a gap is mostly noise; the order is the durable part. A clip with a
  500,000-view outlier gets the same boost as one merely in first place.
- **A cap.** `performance_max_boost` bounds the best against the worst
  whatever their numbers say, and nothing ever reaches zero — a bad early run
  has to be recoverable, or one unlucky week retires a clip for good.
- **Unmeasured sits in the middle.** A new clip is neither rewarded nor
  punished for being new; punish it and it could never gather the data that
  would clear it.

Performance *multiplies* the recency weighting rather than replacing it, so a
proven clip used an hour ago still yields to one unseen for a week. In
practice even at full weight the best hook takes about 1.6x the worst's
slots, and the worst still takes a share — the point is a nudge that
compounds, not a winner-take-all.

It is off by default on purpose. Weighting costs variety, and variety is most
of what keeps a feed working: with four body clips, favouring two of them
makes the repetition problem worse. It earns its place on a dimension with
many options — captions, hooks — and rarely on one with few.

---

## Which clip actually wins

For most of this project that question was unanswerable. `metrics.json` holds
window totals per channel, and a window total cannot say which hook earned it,
so the library grew on taste alone.

It turns out Buffer exposes `Post.metrics`, and the field takes no arguments —
per-post figures ride along inside the posts query. Thirteen posts came back
in **two requests**, so attribution costs essentially nothing, against an
earlier estimate of ~240 requests a month that talked me out of building it.

`history.json` has always recorded `buffer_post_id` beside the exact hook,
bodies, music offset, caption and now the treatment. The metrics job caches
per-post figures into `posts.json`, and `attribution.py` joins the two.

**Rankings are always per network.** Instagram returns roughly 3.7x TikTok
per post on these accounts, so a pooled median mostly measures which platform
a clip happened to run on: two hooks of identical quality, one weighted to
Instagram and one to TikTok, come out 3.7x apart on merit neither has. Ranking
within a network removes that for free — everything being compared shares a
baseline, so no index or normalisation is needed. It is also the more useful
question. A clip is not good in the abstract; it is good on Shorts or good on
TikTok, and those disagree.

The statistics are the hard part, not the join. Four body clips over a
fortnight is a handful of posts each, and social metrics are wildly
overdispersed — one video catching an algorithm outranks a hundred others. So:

- **Medians, not means.** A mean hands the win to whichever clip was in the
  viral post.
- **A floor before ranking.** Below four posts an option is not ranked at all;
  a confident order drawn from two posts is worse than none, because it gets
  acted on.
- **The range is shown beside every median.** When an option's own posts vary
  more than the gap between options, the panel says so — something other than
  the clip is driving the number.
- **Coverage is stated.** A ranking drawn from a fifth of the output is a
  ranking of that fifth.

A post with no figures yet contributes nothing rather than a zero, since a
zero would punish whichever clip was in a video published an hour ago.

---

## Findings

The dashboard's **Findings** panel derives what can honestly be concluded from
files already on disk — no API calls, so it costs nothing against the request
allowance. Three properties of the data shape all of it:

**Metrics are channel aggregates, not per-post.** `aggregatedPostMetrics`
returns window totals. Nothing links a view to a video, so clip-level ranking
cannot be derived at any sample size — the panel says so rather than omitting
the question.

**A caption count is not a variety count.** The bank is measured on what it
actually varies — distinct openings, distinct *asks*, length spread — because
twenty-five captions ending in the same call to action are one call to action
tested twenty-five times. The ask is the part a viewer is meant to act on,
which makes it the highest-leverage thing in the bank to vary and the easiest
to forget. On the live bank: 25 distinct openings, and one ask.

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

## Rendering only what can actually publish

Render is **demand-driven**: it tops the local backlog up to
`posting.posts_per_day x posting.max_backlog_days` (default 2 days) and stops.
If the backlog is already full it renders nothing.

This replaced a fixed nightly batch that rebuilt `queue.json` from scratch. At a
render rate above what the channel really publishes — which is where these
campaigns were — the surplus was discarded unseen every night, having already
been rendered, uploaded, and charged against the library's unique combinations.
78% of all output was being thrown away.

Carrying items forward has two exclusions:

| dropped | why |
|---|---|
| finished (pushed, cancelled, failed past retries) | done, not lost |
| rendered longer ago than `RENDER_RETENTION_DAYS` | its media Release is deleted, so `video_url` points at nothing |

The second is reported rather than silent — an aged-out video is the signal that
the channel cannot drain the queue as fast as it is filled, and the fix is a
lower `posts_per_day`.

New items are allocated slots that exclude the ones carried items already hold,
since two videos in one slot publish minutes apart.

`./ugc render --campaign <slug> --plan` prints the decision — carried, expired,
target, and how many it would render — and exits without rendering, uploading
or writing anything.

Expect one larger batch the first time: an empty backlog fills to the full
target, then settles at whatever the channel actually publishes. On the live
campaigns that is roughly 6/day (Instagram), 3/day (TikTok) and 5/day
(YouTube) against a configured 12, so over ten days it renders about 78, 52 and
66 videos instead of 120 each — and all of them publish rather than 22% of
them.

---

## Staggering campaigns

Slot times are derived from `posts_per_day`, `start_hour` and `end_hour`, so
campaigns sharing those produce **identical** slots. Three campaigns posting
one library to three networks therefore fire on the same minute, all day.

Nothing collides — they are separate channels, and no channel is ever
double-posted — but the day's coverage collapses into a few instants and
anyone following two of them sees a double. It is easy to miss while most
renders are being discarded, and obvious once they are not.

`posting.slot_offset_min` shifts a campaign's whole grid. The live campaigns
run 0 / 40 / 80 minutes, which spreads three networks evenly across a
two-hour gap:

```
clubs     15:00  17:00  19:00  21:00
clubs_tt  15:40  17:40  19:40  21:40
clubs_yt  16:20  18:20  20:20  22:20
```

The re-slotting path uses the same offset, or an item moved off a stale slot
would land between its campaign's own slots and drift out of the stagger.

New campaigns pick their own offset rather than defaulting to zero and
recreating the problem: `free_slot_offset` takes the midpoint of the widest
unclaimed gap among siblings on the same cadence and start hour, so two end up
half an interval apart, three at thirds, without anyone choosing numbers. A
campaign on a different cadence has a different grid, so it has nothing to
avoid and stays on the hour.

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

Each campaign writes only its own `quota.json`, **commits it**, and the total
is summed when read. The commit is not incidental: runners are ephemeral, so a
ledger written and left behind is gone before the next run reads it — which is
how the counter sat at zero through a full day of posting while the file was
being written correctly every time. A single shared counter would race: campaign workflows have separate
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
./ugc render    --campaign clubs --plan          # what tonight would do, changing nothing
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

## Switching between campaigns

The header control lists every campaign with its network, cadence and whether
it is live, and marks the one you are on. It replaced a native `<select>`,
which was the wrong control for the job: macOS opens the popup with the
*current* item under the cursor, so the campaign you were already on sat
hidden behind the button and only the others looked selectable.

Switching reloads every panel. The previous handler refreshed six of them and
left findings, keys and charts showing the campaign you had just navigated
away from.

Creating a campaign now lands on it. Before, the form told you it had worked
and nothing on the page changed.

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
  platforms.py      per-network limits — caption length, title rules
  render.py         ffmpeg two-stage pipeline  ← only module using subprocess for media
  selector.py       combination picking, LRU weighting, relaxation ladder
  descriptions.py   the caption bank: parsing, validation, title strategy
  ingest.py         the drop folder — probe, name, reject, upload
  campaigns.py      creating and listing campaigns from disk
  clips.py          the per-campaign roster: which clips the randomizer may use
  revenue.py        dated money ledger + the ratios against reach
  quota.py          rolling Buffer request tally, summed per API key
  insights.py       cross-campaign findings, and what cannot be concluded
  attribution.py    per-post metrics joined back to the clips that earned them
  variation.py      per-variant treatment, seeded so a winner is reproducible
  settings.py       one-line config edits that keep the comments
  keys.py           credentials: local .env and GitHub Actions secrets
  assets.py         MediaStore ABC + GitHub Releases
  queue.py          state machine + atomic persistence
  vcs.py            git boundary — the durable claim
  notify.py         alerts + weekly digest
  metrics.py        cached performance snapshots, rolling and lifetime
  doctor.py         readiness checks behind `ugc setup`
  web.py            the local dashboard — every panel, one stdlib HTTP server
  publishers/
    base.py         Publisher ABC — TikTok/Graph API slot in here
    buffer.py       Buffer GraphQL
```

### Is per-post performance even possible?

`scripts/check_post_metrics.py` answers it in one request. Clip- and
caption-level ranking needs a metric attached to an individual post, and
nothing in the codebase establishes whether Buffer exposes one:
`aggregatedPostMetrics` is channel-level, and the `posts` query asks for no
metrics at all. The script introspects the schema — reading types, touching no
posts — and prints either the candidate fields or a definitive no.

### Colour, and why it is a test

The dashboard's accent sits at **exactly 4.50:1** against white — the AA floor
for the 13px semibold text on its buttons. That is not a coincidence; it was
solved for. It also means the accent has no headroom: any colour lighter than
it fails.

Adding gradients walked straight into that. Brightening the button fill 14%
toward peach looked like nothing and took it to 4.00:1. So `--grad-accent` may
only ever darken, and `tests/test_contrast.py` enforces it — parsing the
palette out of the served stylesheet, checking every stop against white in
both themes, and rejecting any `color-mix` of the accent toward anything but
black.

Motion gets the same treatment. The transitions are decoration — a card
lifting, the toggle knob sliding, the quota bar easing to width — so they
yield to `prefers-reduced-motion`, and the transform lifts are cancelled
outright rather than merely shortened, since a zero-duration transform still
jumps. Twelve transitions had accumulated before any guard existed.

The campaign switcher declares `role="listbox"`, which is a promise that arrow
keys work: up and down move, Home and End jump, opening lands on the campaign
you are already on, and Escape closes and returns focus to the trigger rather
than stranding it on a hidden button.

The other gradients are derived from the palette with `color-mix` rather than
hand-picked per theme, so light and dark cannot drift apart. They carry depth
and never meaning: no surface holding text varies by more than a few percent
of luminance.

### Checking the dashboard's JavaScript

`scripts/check_page_js.sh` syntax-checks the page as a browser receives it,
by fetching from a running dashboard rather than extracting from `src/web.py`.
Two reasons it is worth a script:

- A duplicate `const` kills the entire `<script>` with **no console output** —
  the page renders as an empty shell and every panel silently disappears.
- Reading the source text is misleading: a backslash is still Python-escaped
  there, so `\\s` in the file is the `\s` the browser gets.

That second point has its own trap. `PAGE` is a plain triple-quoted string, so
an unescaped `\s` inside it is an invalid Python escape sequence. Bytecode
caching hides it — the warning fires at compile time, so an already-cached
module stays quiet and only a fresh checkout fails.

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
