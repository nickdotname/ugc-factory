# UGC Factory — Build Spec (v2, Buffer)

> Source of truth for this repo. Two claims in §0 and §4.2 were disproved by the
> verification work — see [README §0](README.md#0--buffer-api-verification) for
> the corrections. The spec text below is preserved as written; the README
> records where reality differs.

---

## 0. Verify before building

Buffer publishing is already proven on this account — a prior Telegram→Buffer integration autoposts successfully. That settles auth, `createPost`, and scheduling. It does **not** settle video or Reels.

Open Buffer's API Explorer (Settings → API → personal key) and confirm, then record the answers at the top of the README:

1. **Does `createPost` accept a video via URL for an Instagram channel, and does it publish as a Reel directly rather than in reminder mode?**
   - Buffer's developer page lists a "Create Video Post" mutation and media upload is documented as URL-only. Confirm the exact mutation shape and field names.
   - Buffer's schema exposes `default_to_reminders` and "Instagram fields for reminder-based publishing." Reminder mode = a push notification you tap manually. That is not automation.
   - Reminder behavior is per-channel **and** per-post-type. A working text or image post proves nothing about Reels. Test a Reel specifically.
   - Confirm the `post_type` enum value for reel while you're in there.

If this fails, stop and reassess — the fallback is the Instagram Graph API directly, which works but requires Meta app review (2–4 weeks). Don't build around a guess.

**API surface:** target the GraphQL API with a personal API key. Buffer stopped accepting new developer app registrations on the legacy REST API; if the existing Telegram integration uses a legacy client_id, leave it alone and do not build against it.

**Write the Buffer publisher from scratch.** Do not port code from the existing Telegram integration. That script was written against a different set of assumptions and importing it would compromise the abstraction in §2.2. Consult it as reference for *what Buffer actually returns* — working mutation shapes, error payloads, quirks — and write clean against the contract in §8.

## 1. Goal

An unattended pipeline that assembles short vertical videos from a library of parts and publishes them to Instagram Reels on a schedule, indefinitely, without human intervention.

**Reusable across campaigns.** A "campaign" is one brand/account with its own asset library, caption bank, Buffer channel, and cadence. Adding a second campaign must require zero code changes — a new config folder and new secrets only. Campaign 1 is `clubs`. Nothing specific to it may be hardcoded.

## 2. Scope & quality bar

### 2.1 Scope

**In:** batch render (hook clip + body clip + music at 10% under the whole video), caption from a per-campaign bank, combination dedupe, push to Buffer's scheduled queue for Instagram Reels, runs free on GitHub Actions cron, failure alerting and health checks.

**Out:** TikTok. Any UI. AI generation of hooks or captions — both are human-authored banks. Analytics ingestion.

### 2.2 Quality bar

This is production infrastructure that must run unattended for years and host campaigns that don't exist yet. These are requirements, not aspirations. A milestone is not done until it meets them.

**Boundaries are interfaces.** Every external dependency sits behind an abstract base class in its own module: `Publisher` (Buffer), `MediaStore` (GitHub Releases), `Renderer` (ffmpeg), plus injected `Clock` and `Rng`. Nothing in `src/` calls `requests`, `subprocess`, `datetime.now()`, or `random` directly outside those modules. This is what makes the thing testable and what makes swapping Buffer for the Graph API — or adding TikTok — a new file rather than a refactor.

**No campaign-specific logic anywhere in `src/`.** Every behavioral difference between campaigns is expressed in `config.yaml`. If a campaign needs something config can't express, extend the schema; never branch on slug. A grep for `clubs` in `src/` must return nothing.

**Typed end to end.** Pydantic models for config, queue items, and every API payload. No dicts passed between modules. No stringly-typed status values — use enums. `mypy --strict` passes.

**Typed errors.** A hierarchy of exceptions (`RenderError`, `ValidationError`, `PublishError`, `QuotaError`, `AuthError`) with retryability as a property of the exception class. Never branch on error message strings — Buffer will change its wording and the retry logic will silently invert.

**Deterministic where it can be.** Given a fixed seed, `selector.py` produces identical picks. Given identical inputs, the renderer produces byte-comparable output. Determinism is what makes the acceptance tests in §14 meaningful rather than flaky.

**Tests that don't hit the network.** Unit tests are pure and fast. Buffer's real responses — success, each error mode, rate limit, reminder-mode fallback — are captured once as fixtures and replayed. One optional integration test hits the live API behind an env flag, and it is never part of CI.

**Structured logging.** JSON to stdout, one correlation ID per queue item carried from render through publish. When a post fails at 3 a.m. six weeks from now, the log has to answer *which item, which stage, which inputs, what came back* without anyone reproducing anything.

**Fail loud, fail early.** Validate at boundaries — config on load, rendered files before upload, API responses on receipt. Never a silent default, never a bare `except`, never a swallowed exception. Per §4.2, Buffer posts can't be deleted by code, so anything that reaches Buffer must already be known-good.

**Documented for a future reader who isn't you.** Every module has a docstring stating its responsibility. Every non-obvious decision carries a comment explaining *why*, especially the ffmpeg flags in §6 — those look arbitrary and are not.

## 3. Cost

Everything is genuinely $0 at this scale. The constraints are quota, not money.

| Component | Tier | Limit that binds | Cost |
|---|---|---|---|
| GitHub Actions | Free, **public repo** | Unlimited minutes on public repos | $0 |
| GitHub Releases | Free | 2 GB per file | $0 |
| Buffer | Free | 1 API key, 3,000 requests / 30 days, 3 channels, 10 queued posts per channel | $0 |
| ffmpeg | — | — | $0 |
| Music | Royalty-free sources (§4.4) | — | $0 |

**Make the repo public.** Private repos get 2,000 Actions minutes/month; public repos are unlimited. Assets live in Releases, credentials live in GitHub Secrets, so the tree has nothing worth hiding. This also makes Releases assets publicly fetchable, which is what Buffer needs.

**The 3,000-requests/30-days figure is the ceiling to design against.** Budget at 24 posts/day: ~2 requests per post + queue-depth checks ≈ 54/day ≈ 1,620/month. Fits with roughly 45% headroom. At the recommended 6/day it's ~400/month. Log cumulative request count and alert at 2,400.

## 4. Platform constraints

Verified August 2026. Re-verify numbers at build time; the shapes are stable.

**4.1 — Buffer free plan queues 10 posts per channel at a time.**
Not a daily cap — a queue-depth cap. A slot frees when a post publishes. So the render job cannot dump 24 posts into Buffer at once.
→ **Requirement:** a **top-up job** on cron that reads current Buffer queue depth and pushes only enough items to reach 10. This replaces the hourly-post job entirely; Buffer's own scheduler handles publish timing.

**4.2 — No edit or delete via the API.**
Once `createPost` succeeds, code cannot fix a typo or pull a bad post. Only the Buffer dashboard can.
→ **Requirement:** validate hard before pushing (§6). Keep the render→push gap as a human review window. Never push a post to Buffer in the same job that rendered it.

> **Correction:** `deletePost` and `editPost` both exist. See README §0. The
> requirement stands anyway — deletion only helps before Instagram publishes.

**4.3 — Instagram Reels format rules still apply downstream.**
Buffer is a pass-through; Instagram's specs govern. Reels-tab eligibility needs 9:16 aspect ratio and **5–90 seconds**. H.264 or HEVC, AAC audio at 48 kHz, 1–2 channels, and the **moov atom at the front of the file**. Outside 5–90s it publishes as a regular video post, not a Reel.
→ **Requirement:** `min_duration_sec: 5`, `max_duration_sec: 90` are hard render-time failures, not warnings. `-movflags +faststart` is mandatory.

**4.4 — Music must be royalty-free.**
Baked-in commercial tracks get fingerprinted, muted, or taken down, and repeat hits damage account standing. Approved: Pixabay Music, Uppbeat free tier, YouTube Audio Library, Epidemic Sound (paid). Keep a `LICENSES.md` in each campaign's music folder recording source and license per track; the renderer warns on any track missing an entry.

**4.5 — 24 posts/day is aggressive regardless of API limits.**
Buffer's quota permits it. Instagram's spam classifier is a separate system that doesn't care what Buffer permits. 24 Reels/day from one account is far outside normal account behavior.
→ **Requirement:** `posts_per_day` is per-campaign config, **default 6**, max 24. The system works identically at any value, so this costs nothing to defer. Run 6/day for two weeks, watch reach-per-post, then raise.

## 5. Architecture

```
NIGHTLY RENDER (1×/day, ~05:00 UTC)      TOP-UP (every 4h)
┌────────────────────────────┐           ┌────────────────────────────┐
│ 1. download assets from    │           │ 1. query Buffer queue depth│
│    the assets Release      │           │ 2. read queue.json         │
│ 2. render N videos         │  queue    │ 3. push (10 − depth) items │
│ 3. upload to a dated       │ ────────► │    as scheduled Buffer     │
│    GitHub Release          │  .json    │    posts                   │
│ 4. write queue.json        │           │ 4. mark pushed, commit     │
│ 5. commit                  │           └────────────────────────────┘
└────────────────────────────┘                        │
                                            Buffer publishes on its
                                            own schedule → Instagram
```

**Why the split:** rendering needs ffmpeg and takes minutes; pushing needs neither, so merging multiplies expensive setup. A render failure at 05:00 doesn't stop already-queued posts. The gap is your review window — and per §4.2 it's the *only* window, since Buffer posts can't be deleted by code.

**Media hosting via GitHub Releases:** one Release per render date, rendered MP4s as assets. Public repo means asset URLs are publicly fetchable, which is what Buffer's URL-only media upload needs. A weekly cleanup job deletes Releases older than 14 days. This avoids Cloudflare R2 entirely — no extra account, no credit card, no custom domain.

## 6. Render pipeline

**Do not use the concat demuxer on raw source clips.** Sources will have mismatched resolution, fps, SAR, codec, and some will have no audio stream. Concat will produce corrupt or desynced output. Two stages:

**Stage 1 — normalize each clip to a temp file (re-encode, unavoidable):**
- `scale=W:H:force_original_aspect_ratio=increase,crop=W:H,setsar=1`
- `fps=FPS`, `format=yuv420p`
- ffprobe first. If a clip has no audio stream, attach silent AAC (`anullsrc`, 48 kHz stereo) so every temp has identical stream layout. This is the single most common cause of concat corruption.
- `libx264`, config crf/preset, `aac -b:a 128k -ar 48000 -ac 2`

**Stage 2 — concat + music (video stream-copied, fast):**
- Concat demuxer over the normalized temps with `-c copy` — safe now that params match.
- Music: `-stream_loop -1` on the track so a short track doesn't leave silence, `atrim` to video duration, `volume=0.10` flat across the whole video, `afade` out over the last 1.5s.
- `amix` the music with the concatenated source audio.
- `-c:v copy -c:a aac -movflags +faststart`

Music volume is a flat 10% for the entire video. No ducking, no per-section levels. `music_volume` stays configurable but defaults to `0.10`.

**Validate before upload — hard-fail, don't warn:** duration outside 5–90s, dimensions ≠ configured, missing audio stream, file > 100 MB. Per §4.2 a bad file that reaches Buffer cannot be recalled by code.

## 7. Music bank

`campaigns/<slug>/` has no music in git. Tracks live in the assets Release under `music/`.

- Drop any `.mp3` / `.m4a` / `.wav` in and the selector picks it up on the next render. No config edits, no registration step.
- Tracks shorter than the video loop seamlessly (§6 `-stream_loop -1`).
- Tracks longer than the video are trimmed to length with a 1.5s fade.
- Add one line per track to `music/LICENSES.md`: filename, source, license. The renderer logs a warning for any track with no entry and includes the list in the weekly digest.

Same pattern for `hooks/` and `bodies/` — drop files in, they're live next render.

## 8. Repo layout

```
ugc-factory/
├── SPEC.md
├── README.md                   # setup checklist + §0 verification answers
├── requirements.txt
├── campaigns/
│   ├── clubs/
│   │   ├── config.yaml
│   │   ├── captions.txt        # one caption per line, blank-line separated
│   │   ├── queue.json          # generated, committed
│   │   └── history.json        # generated, committed
│   └── _template/
├── src/
│   ├── cli.py                  # render | topup | preflight | cleanup
│   ├── config.py               # pydantic schema, fail loud
│   ├── assets.py               # GitHub Release download/upload
│   ├── render.py
│   ├── selector.py             # combination picking + dedupe
│   ├── queue.py                # state machine
│   ├── publishers/
│   │   ├── base.py             # Publisher ABC — TikTok slots in here later
│   │   └── buffer.py
│   └── notify.py
├── tests/
└── .github/workflows/
    ├── render.yml
    ├── topup.yml
    ├── preflight.yml
    └── cleanup.yml
```

## 9. Campaign config

`campaigns/<slug>/config.yaml`:

```yaml
slug: clubs
timezone: America/New_York

posting:
  posts_per_day: 6            # §4.5 — build for 24, run at 6
  start_hour: 9               # local; Buffer schedule times spread evenly
  end_hour: 22
  max_buffer_queue: 10        # §4.1 free-plan cap
  dry_run: false              # render + upload, never push to Buffer

video:
  width: 1080
  height: 1920
  fps: 30
  crf: 23
  preset: veryfast
  min_duration_sec: 5         # §4.3 Reels eligibility
  max_duration_sec: 90

composition:
  bodies_per_video: 1
  music_volume: 0.10          # flat, whole video
  music_fade_out_sec: 1.5

selection:
  dedupe_on: [hook, body, music, caption]
  caption_cooldown_days: 14
  hook_cooldown_days: 3

buffer:
  api_key_secret: BUFFER_API_KEY
  channel_id_secret: BUFFER_CHANNEL_CLUBS
  post_type: reel             # confirm enum in §0.3

notify:
  webhook_secret: DISCORD_WEBHOOK_CLUBS
  on: [failure, queue_empty, quota_high, license_missing]
```

Schema-validated on load. Fail loud with the offending key; never silently default.

## 10. Selection & dedupe

`selector.py` picks `(hook, body, music, caption)`.

- Reject any tuple whose hash is in `history.json`.
- Respect `caption_cooldown_days` and `hook_cooldown_days`.
- Weight toward least-recently-used assets, not uniform random — uniform random clusters repeats visibly.
- If no valid pick exists, relax in this order: hook cooldown → caption cooldown → full-tuple dedupe. **Notify on any relaxation** — it means the library is too small for the cadence.
- Log the combinatorial ceiling each render: `hooks × bodies × music × captions`. At 6/day you want ≥90 days of unique combos before the first repeat.

## 11. State

`queue.json`:

```json
{
  "generated_at": "2026-08-13T05:02:11Z",
  "items": [{
    "id": "0198a3f2-...",
    "scheduled_for": "2026-08-13T13:00:00-04:00",
    "video_url": "https://github.com/<owner>/<repo>/releases/download/render-2026-08-13/0198a3f2.mp4",
    "caption": "...",
    "parts": {"hook": "hook_07.mp4", "body": "body_22.mp4", "music": "lofi_03.mp3"},
    "status": "pending",
    "attempts": 0,
    "buffer_post_id": null,
    "last_error": null
  }]
}
```

**Status machine:** `pending → claimed → pushed`, with `→ failed` from any state and `failed → pending` on retry while `attempts < 3`.

The top-up job writes `claimed` **and commits** before calling Buffer. If a job dies mid-push, the next run sees `claimed` and investigates rather than blindly re-pushing — critical because §4.2 means a duplicate cannot be deleted by code. On resume, query Buffer for existing posts at that scheduled time before re-pushing.

`history.json` is append-only: tuple hash, timestamp, Buffer post ID. Never pruned.

## 12. Workflows, failure handling, monitoring

- `concurrency: group: topup-${{ matrix.campaign }}, cancel-in-progress: false` — two top-up jobs racing the queue would double-push.
- Campaigns run as a workflow matrix. Adding one = one line.
- `workflow_dispatch` on every workflow with a `dry_run` input.
- Cache pip. Only `render.yml` installs ffmpeg.
- Bot commits use `[skip ci]`.
- **Cron drift is real** — scheduled workflows queue behind everything else and routinely fire 5–30 minutes late. Irrelevant here because Buffer controls actual publish timing, but don't build logic that assumes exact fire times.
- **GitHub disables cron after 60 days of no commits.** The nightly `queue.json` commit satisfies this. Don't remove it as an "optimization."
- Retry 5xx and timeouts with exponential backoff, 3 attempts. Do not retry auth failures or validation errors — alert and stop.
- Alert on: any job failure, queue runway under 24h, cumulative Buffer requests over 2,400/30 days, dedupe relaxation, missing music licenses.
- **Weekly digest even on success:** posted count, failures, Buffer quota used, queue depth, days until first repeat. Silence must never be ambiguous between "healthy" and "dead."

## 13. Build order

Each milestone must independently satisfy §2.2 before the next begins. Do not defer typing, tests, or error handling to a cleanup pass at the end — that pass never happens, and retrofitting the interface boundaries after milestone 6 means rewriting milestones 2 through 5.

1. **Config + validation.** Tests only.
2. **Renderer, local.** Local folders, no GitHub. One valid MP4 from fixture clips. Deliberately test mismatched resolutions, missing audio streams, landscape sources, music shorter and longer than the video. Most of the real difficulty is here.
3. **Selector + history.** Pure functions, heavy tests.
4. **GitHub Releases layer.** Upload, then `curl` the public URL unauthenticated from outside CI to prove Buffer can actually fetch it.
5. **Queue + state machine,** including crash-resume.
6. **Buffer publisher.** `dry_run` first, then one real post to a throwaway IG account — not @clubs.create.
7. **Workflows.** `workflow_dispatch` only; add cron last.
8. **Preflight, notify, cleanup.**
9. **Second campaign.** Run §15 against a dummy slug to prove the abstraction, before scaling volume.

## 14. Acceptance tests

- Render 30 videos; all pass §6 validation; zero duplicate tuples; all 5–90s.
- Drop a new MP3 into the music Release; next render picks it up with no config change.
- Kill the top-up job between `claimed` and `pushed`; next run resumes without double-pushing.
- Buffer queue already at 10; top-up pushes nothing and exits clean.
- Add a dummy campaign via §15 with zero edits to `src/`.
- Empty the caption bank below cooldown viability; selector relaxes in documented order and notifies.
- Force an auth failure; system alerts and stops rather than draining the queue to `failed`.

## 15. Adding a campaign

No code changes:

1. `cp -r campaigns/_template campaigns/<slug>`
2. Fill `config.yaml` and `captions.txt`
3. Connect the channel in Buffer, get its channel ID
4. Upload assets to that campaign's assets Release
5. Add secrets: `BUFFER_CHANNEL_<SLUG>`, `DISCORD_WEBHOOK_<SLUG>`
6. Add `<slug>` to the matrix in `render.yml` and `topup.yml`
7. `workflow_dispatch` with `dry_run: true`, confirm output

If any step requires touching `src/`, the abstraction failed.

## 16. v2 — TikTok

Buffer supports TikTok as a channel, so v2 may be as simple as a second channel ID and a config block — **if** Buffer's API publishes TikTok directly rather than in reminder mode. Verify the same way as §0.2 before assuming.

> **Note from verification:** the TikTok channel already connected to this
> account reports `defaultToReminders: false`, and the prior integration
> publishes video to it with `schedulingType: automatic`. That is strong
> evidence the Buffer path works for TikTok. Confirm per-channel before relying
> on it.

The fallback, if Buffer can't do it: TikTok's official API forces unaudited clients to private-only, and its audit requires showing the creator's username and avatar before every post — a UX requirement a cron job structurally cannot satisfy. That path leads to either manual drafts or a paid pre-audited third-party API (~$15–30/mo).

Either way, the `Publisher` ABC in §8 is the seam. Honor it in v1 even though only Buffer exists.
