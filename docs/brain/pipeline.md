# Pipeline: the daily clock

All times New York (UTC−5 in winter). Back to [[README]].

| when (NY) | UTC | job | what it does |
|---|---|---|---|
| every 5 min | */5 | `publish.yml` | sends due Instagram posts from `outbox/`, posts first comments, refreshes `cqdash/data.json`, starts the jobs below on the minutes listed |
| 00:52 | 05:52 | `earthdata.yml` | satellites, flights, earthquakes for [[styles#earth]] |
| 01:45 | 06:45 | `studio.yml` | `studio/nightly.py`: new videos for every target in `studio/nightly.yaml` → each song's clip library (GitHub release `assets-<campaign>-<song>`) |
| 03:30 | 08:30 | `render.yml` | `ugc render`: picks unused library videos per campaign up to `posts_per_day × max_backlog_days` (1), writes `campaigns/<c>/queue.json` |
| 04:00, 10:00, 16:00 | 09:00, 15:00, 21:00 | `topup.yml` | books queued posts into the next free slots of each account (Instagram → `outbox/igo-*.json`; Buffer → Buffer's queue) |
| 09:15 12:15 16:15 20:15 | | `carousel.yml` | info carousels (psychedelic.station, nostalgia) |
| 10:45 13:45 17:45 20:45 | | `factreel.yml` | fact reels |
| Mon 04:41 | 09:41 Mon | `footage.yml` | grows the public-domain footage library ([[footage]]) |
| Mon/Thu | | `retro.yml` | PS2-style clips made on Kaggle GPUs for retro.vibes.arcade |

GitHub's own cron in `publish.yml` (8,23,38,53) is only a backup; the Worker is the clock. The daily jobs fire only in the
first 5 minutes of their quarter hour (`m % 15 < 5`), so the 5-minute cadence doesn't start them three times.

The order matters: **studio before render before topup.** Render is demand-driven: it fills tomorrow and stops.
So if studio ran late, render that night finds nothing new, and the gap shows up a day later (fixed 2026-11-23 by
moving render to 08:30 UTC, after studio).

## Where state lives (all in the repo, committed by the jobs)

- `campaigns/<c>/config.yaml`: creatives (one per song), accounts, posting window (`start_hour`/`end_hour`,
  `posts_per_day`, `slot_offset_min`), funnel (first comments, CTA), selection rules.
- `campaigns/<c>/queue.json`: rendered posts waiting for a slot. `history.json`: what was used (dedupe).
  `posts.json`: published posts and their numbers. `recipes.json`: what each library video was made of (knobs).
- `outbox/igo-*.json`: Instagram posts booked for a slot (status QUEUED → PUBLISHING → PUBLISHED).
- `cqdash/data.json`: the dashboard's numbers.
- `studio/weights.json`: what [[learning]] concluded.
- `studio/songs/<slug>/`: each song's master, stems, lyrics timing, beat grid ([[songs]]).

## Posting

- Instagram accounts post **directly** through the Graph API (`src/publishers/instagram.py`, token `IG_TOKEN`).
  A post is made as a container, then published at its slot; then the first comment is added (failure of the
  comment never fails the post).
- @the.loose.change (`nickdotname_ig`) still posts through **Buffer** (`BUFFER_API_KEY_2`).
- Slots: `upcoming_slots` per campaign; `topup` refuses minutes another campaign or the network already holds
  on the same account (`publisher.scheduled_slots`), so two posts never land on one minute.
- Posting windows are daytime (9–23 NY, per campaign). Nothing posts overnight by design.

## Failure handling worth knowing

- A creative whose library is exhausted is skipped, not fatal (`select_batch_multi`).
- A render that fails validation (clip too short) frees its slot for another (`cli.py`, `freed_slots`).
- `repeats: false` + `dedupe_on: [hook]`: a library video is posted once, ever. Libraries refill nightly.
