# Cluster `system`: what every account shares, judged against "the band gets heard"

Reviewed 2026-11-26 against `cqdash/data.json` (788 rows, 611 published, 538 with numbers), every
`campaigns/*/config.yaml`, `outbox/`, `studio/learn.py`, `studio/nightly.py`, `studio/weights.json`,
`src/publishers/instagram.py`, `src/cli.py` (metrics), `scripts/*.py`, `cqconnect/worker.js`, `link/`,
`docs/brain/*`, and the logs of today's `metrics.yml` / `publish.yml` / `studio.yml` runs. Nothing was changed.
Contact sheets rendered for race, notes and psy are in `scratchpad/system/`.

## 1. Verdict (one line per area)

| area | verdict | the single biggest lever |
|---|---|---|
| Funnel | **rethink** | no post anywhere is attached to a song audio page: 543 reels, 0 `audio_id`; the only path from a reel to the song is a first comment and "link in bio" on accounts whose bio taps are not even measured |
| Cadence / health | needs work | the network ran 150 posts/day on Nov 24; new accounts go from 0 to 5/day on day 1; the band account is 98% trial reels so its grid is empty for anyone who follows a credit |
| Learner | needs work | 1,565 option weights all between 0.87 and 1.13, zero automatic retirements, 1–6 posts per option: it is noise shaped like a bandit; learn one knob per account on a per-account z-score, not 12–31 dims |
| Metrics gaps | **broken** (fixable today) | 10 accounts / 82 published posts have no numbers: insights permission missing on IG_TOKEN_2..11, and Dylan's Page token cannot read insights on Adrianne's two Pages |
| Covers / grid | needs work | `cover_at_sec` is set on one live campaign; 7 renderers draw the song credit in the bottom 420 px where Instagram's caption hides it; the band account's grid is blank (trial reels) |
| Cross-posting | on track to try, low priority | no watermark on our files so IG's "other app logo" rule does not bite; TikTok/Shorts via the idle Buffer channels is cheap, but the audio page fix above is worth 10x more |

## 2. What the numbers say (network level)

Baseline table: `scratchpad/baseline.md`. Extra cuts computed here:

**Views by day posted (all accounts, median):** Nov 21 57 · Nov 22 78 · Nov 23 112 · Nov 24 115 · Nov 25 93 · Nov 26 80 (young).
Daily volume: 59 · 76 · 79 · **150** · 140 · 72 posts. The 2026-11-23 doubling of per-account volume (3→5, nostalgia 6,
psy 10) did not raise median views; the 2026-11-25 cut-backs (psy 10→2, nostalgia 6→2, dylancantor 8→3) were right and
the log already says "daily totals did not grow with posts".

**Hour posted (NY), z-score of log views within account, n per hour:** 08:00 +0.15 (19) · 09 −0.03 (44) · 10 −0.25 (21)
· 11 −0.27 (43) · 12 −0.09 (45) · 13 +0.06 (40) · 14 −0.11 (34) · 15 +0.04 (34) · 16 −0.16 (40) · 17 +0.49 (16) · 18 +0.01
(28) · 19 −0.10 (38) · 20 +0.09 (52) · 21 +0.13 (35) · 22 +0.52 (21) · 23 +0.50 (5). Evenings (20–23) look ~0.3 sd
better than late morning (10–11), but no hour has more than 52 posts across 18 accounts; the learner's per-campaign
"hour posted" dimension has 1–4 posts per hour and cannot see this. The windows all open at 8–9 and the day's posts
are spread evenly, so a third of the network's posts land in the weakest hours.

**Completion vs clip length (404 posts with a recipe window):** <10 s: completion 0.46, median 117 views ·
10–20 s: 0.23, 111 views · 20–35 s: 0.17, 112 views · 35 s+: 0.09, 44 views (n=12). Views are flat with length
until 35 s; completion (what Instagram ranks on) halves with each step. `knob:cut` is learned per campaign, but this
is a network-wide fact: short loops should be the default for every picture style and 35 s+ should stop.

**Saves+shares per 1,000 views (the distribution signals):** psychedelic.station 21 · loose.change 14 · ascii 12 ·
close__quarters 12 · rocket 11 · cinema 8 · tinycode 7.5 · glitch 7 · nostalgia 7 · math 5.6 · petri 3.4 · earth 3 ·
vintage 3 · nyc 2.2 · illusions 1.9 · physics 1.8 · dylancantor23 1.6 · retro 0. The accounts with the most views
(illusions 1,376 median, math 174, physics 150) have the lowest keep rates: people watch and leave. The accounts
whose viewers keep the post (psy, ascii, rocket) are the ones where a song credit would convert.

**Bio link taps (`studio/clicks.json`, read from `link/worker.js` `/stats`):** 52 taps, all on 2026-11-22, zero
since; only 4 of 30 accounts have a tracked link at all (cq, dc, psy, nostalgia). Either the bios were changed to
untracked links or the KV counter stopped; either way the one number that says whether videos send people to the
music has been blind for four days. `docs/brain/learning.md` calls this "the one number that says whether the videos
send people to the music".

**Posting cadence vs account age (published posts/day, NY):**
- Day-1 volumes: glitch/physics/ascii/math/earth 3–7 on 2026-11-22; nyc/vintage/tiny/cinema/petri/illusions 2–3 on
  Nov 23 then 5–7 the next day; races/8bit/moth 1–3 then 4–5; crying/grip 5 on their first day; the 2026-11-26 five
  started at 1–2 (good).
- the.loose.change hit 14/day on Nov 22 (two campaigns on one Buffer channel); psychedelic.station 21 on Nov 24
  (reels + carousels + fact reels from separate jobs; the MIN_GAP guard came a day later).
- Today's queue holds 8 for psy, nostalgia, dylancantor23, grip, crying: the `posts_per_day` cuts in `nightly.yaml`
  (per_night 2–3) did not reach every campaign's `posting.posts_per_day` (still 5–10 in config.yaml), so carousels
  and fact reels top those accounts back up.

## 3. Audit, area by area

### 3.1 The funnel: viewer → song

What a viewer of a niche reel actually sees, in order:

1. **On screen.** 24 of 38 renderers draw "♪ {title} — close quarters". Where it is drawn matters: Instagram's
   caption, username and buttons cover roughly the bottom 420 px and the top 250 px of a 1920-tall reel.
   - **Hidden under the caption (y > 1500):** `mathviz/kit.py` 1885 (every math.explainers video), `race_video.py`
     (bottom edge, see `scratchpad/system/race.png`: the credit sits at ~y 1880), `alife_video.py` H−95, `tinycode_video.py`
     H−95, `fluid_video.py` H−70, `hue_video.py` 1590, `measure_video.py` 1590, `reveal_video.py` / `stare_video.py` 1540.
   - **Under the top bar (y < 250):** `asciiviz/engine.py` label at (24, 40).
   - **Inside the safe area (fine):** cutout H−450, rocket H−447, retro H−440, earth 1455, glitch/lowpoly/toon/vintage/zoom
     SAFE_BOTTOM−24, collage 1313, illusion/physics/stopit H×0.80, cinema under the picture, type at SAFE_B.
   - **No credit at all:** psy, liminal, tests8, lyric/band, cursor, lofi, nyc, and the five text pages (by design;
     `text_video.py` docstring). psychedelic.station is the account with the best keep rate (21/1,000) and the only
     thing naming the song is a caption line under "more".
2. **Caption.** 610/611 published captions carry "🎧 {name} – @close__quarters" (`captions.txt` banks); 482 end with
   a "link in bio" CTA (`funnel.cta`, `cta_every: 1`). Good and uniform. But "link in bio" is a promise 26 accounts
   cannot keep measurably (no tracked link), and the CTA names a song page that does not exist as a link: the bio
   goes to closequarters.vip, not to the song.
3. **First comment.** Every niche campaign: "🎧 the song is {name} by @close__quarters, from their album EDUCATION"
   (3 variants). Band account: 3 own variants. Correct and bait-free. Carousels (`post_carousel.py`) and fact reels
   (`post_factreel.py`) post with `first_comment=None`; the fact reel caption credits the song, the carousel caption
   is the spec's own text (check it credits).
4. **The @mention lands on a profile that is empty.** `accounts.yaml` posts every close__quarters and dylancantor23
   reel as a **trial reel** (`trial_reels: true`, 53 of 54 and 48 of 48 measured posts). Trial reels are hidden from
   the profile grid and from followers until graduated (Instagram graduates on SS_PERFORMANCE after ~72 h, and most
   of ours do not perform). So the funnel's destination — the band's profile — shows a near-empty grid to anyone who
   taps @close__quarters from a first comment or a reply. This is the single worst thing in the funnel after audio.
5. **"what song is this?" replies** (`studio/replies.py`): sound. But `TOKENS` only maps IG_TOKEN_2..6; toon_ig,
   zoom_ig, date_ig, lowpoly_ig, college_ig (IG_TOKEN_7..11) fall through to the shared IG_TOKEN, which cannot read
   those accounts, and eyetrick_ig / fourier_ig use IG_TOKEN directly instead of their Page token (the publisher uses
   `IG_PAGE_TOKENS` for them; replies.py does not). The publish log shows the replies step printing nothing at all,
   so I could not confirm it is reading any account; add a one-line summary print ("read N posts on M accounts").
6. **Audio attribution: the biggest lever, currently zero.** All 543 published reels are baked-audio uploads;
   475 carry `audio_name="{name} – Close Quarters"` (original audio, named), 0 carry an `audio_id`. Consequences:
   - Each reel is its *own* "Original audio" page under the niche account. Thirty accounts × 15 songs × every reel =
     hundreds of audio pages, none of which aggregates, none of which points at @close__quarters.
   - The audio sticker a viewer taps shows "{name} – Close Quarters · Original audio · @math.explainers". It does not
     link to the band, cannot be saved as the song, and does not count toward the song.
   - What the API allows now (Meta changelog, Instagram Audio API, Facebook Login apps only): `GET /ig_audio?audio_type=
     music|original_sound[&search_query=]` to search, and an `audio_configuration` object (audio id + volumes) on
     `POST /{ig-user-id}/media` to attach that audio to a Reel at creation. `src/publishers/instagram.py` already
     builds exactly that (`_container_params`: `audio_configuration = {"audio_id", "audio_volume", "video_volume"}`),
     and `scripts/ig_audio_search.py` already queries `/ig_audio`. The plumbing exists; it has never been run (no
     `ig_audio` mention anywhere in `docs/brain/log.md`).
   - Two routes, in order of value:
     a. **Get EDUCATION into Meta's licensed music library** through the distributor (DistroKid/TuneCore/etc. deliver
        to Meta; the help centre says that when licensed audio is detected in a reel, attribution changes from
        "Original audio" to artist + title and the reel joins the song's audio page). Once the album is in the library,
        *every existing baked-audio reel* can be auto-attributed by Meta's audio match, and new reels can be posted
        with the catalogue `audio_id` (search `--type music --query "close quarters"`). This is the mechanism by which
        songs spread on Reels: one audio page, "Use audio", "Save audio", artist link. Check with Dylan whether the
        album was delivered to Meta/Facebook/Instagram in the distributor's store list; if it is, run
        `IG_TOKEN=... python scripts/ig_audio_search.py --account close_quarters_ig --query "close quarters"` from a
        GitHub Action (cloud sessions cannot reach graph.facebook.com) and look for 15 rows.
     b. **Until then, one original sound per song, owned by the band.** Post each song's first reel on
        @close__quarters with `audio_name`, then search `--type original_sound --query "Talk – Close Quarters"` and
        attach that `audio_id` to every niche reel of that song. All niche reels of a song then aggregate on one
        audio page whose creator field is @close__quarters. This needs a test post: the Audio API docs say original
        sounds are searchable; whether another business account may attach one is what the test shows.
   - Both need the publisher to carry `audio_id` from campaign config into `PublishRequest` (`src/cli.py` ~1772:
     today only `audio_name` is filled; add `funnel.audio_id_by_song` or a `studio/songs/<slug>/song.json` field
     `ig_audio_id`), and the audio-attached post must drop the baked audio or set `video_volume: 0`.
   - Caveat the brief asked about: Unified-login / Business-login accounts (IG_TOKEN_2..11) are not "Facebook Login"
     in Meta's sense; `create_post` already refuses `audio_id` when `login != "facebook"`. `accounts.yaml` marks all of
     them `login: facebook`, so the guard will not catch it; the API will. Those 10 accounts may stay on named
     original audio until they are linked to a Page.

### 3.2 Posting cadence and account health

- **What Instagram says in 2025–26:** no hard number. Mosseri (Jan/Mar 2025): watch time, likes per reach and
  sends per reach are the three ranking signals; "more posts = more chances, but no perfect number"; the oldest
  concrete guidance is ~2 feed posts a week plus stories. Practitioner consensus for new/small accounts: 1 reel a day
  is plenty, 5 a day on a week-old account splits a tiny audience and reads as automation. Our own data agrees: the
  heaviest posters have the lowest medians, back-to-back posts did 20% worse (traps.md), repeated subjects did half
  the views.
- **Originality policy (the 2024 Reels rule, extended to photos/carousels 2026-04-30):** an account that *primarily*
  posts content it "didn't create or edit in a material way" over a rolling 30 days is removed from recommendations;
  labels link reposts to the original creator; watermarks, speed changes and screenshots are not material edits;
  recovery after 30 clean days via Account Status. The network's exposure: vintage already got the notice (public
  domain ≠ original to the matcher); glitch, cinema and toon use the same films but change every pixel; the retro
  account's AI clips are ours. The thing nobody has checked: **does Meta's duplicate matcher see the same song audio
  across 30 accounts as reposting?** The rule is about the *content* ("reels you didn't create"), and audio match is
  how licensed music is attributed, not how originality is judged, so the risk is low — and it drops further once
  the song is a catalogue track (then identical audio is expected). Keep the videos visually distinct per account
  (they are) and never post the same file on two accounts (the 2026-11-26 double-booking did exactly that; the
  one-booking-per-video fix covers it).
- **"Does 30 accounts from one app/token look like a network?"** Meta's inauthentic-sharing rule targets "the same
  content shared at high rates across multiple, seemingly disparate entities" and fake-engagement behaviour. We share
  audio, not content, and the accounts never like/comment on each other (PLAYBOOK §8, keep it that way; replies.py
  skips our own usernames). One app id publishing to 30 accounts is normal for a scheduling tool. What *would* look
  coordinated: 30 first comments with identical wording within minutes, identical hashtags everywhere, and 30 bios
  pointing at one link. Vary the first comment bank per campaign (today every niche campaign has the same 3 lines)
  and stagger `slot_offset_min` (already done).
- **Token-expiry risk** (`scripts/refresh_tokens.py`, `scripts/ig_token_check.py`, `tokens.yml`):
  - IG_TOKEN (shared, 17 Pages): refreshed by `refresh_fb` only if `META_APP_SECRET` is set; page tokens minted from
    it never expire, so publishing survives IG_TOKEN lapsing, but metrics for Unified accounts and `replies.py` do not.
  - IG_TOKEN_2..6 (dashboard tokens): refresh_tokens treats non-"IG"-prefixed tokens as Facebook-format and only
    renews them under 21 days left — fine, but a refresh *keeps the old scopes*, so it will never pick up the insights
    permission (see §3.4).
  - IG_TOKEN_7..11 (connect worker, never expire): no refresh needed.
  - `ig_token_check.py` is wired into `ig-check.yml` and `studio.yml`; it reads `debug_token` with the token as its own
    bearer, which reports `expires_at` but is silent on *scopes*. Add `data.scopes` to its output (names only): that is
    the check that would have caught §3.4 on day one.
  - Single point of failure nobody tracks: `SECRETS_PAT` (fine-grained, expires) — if it lapses, `tokens.yml` goes red
    and nothing else notices until posting stops 60 days later. Add its expiry to the health-check playbook.

### 3.3 The learner (`studio/learn.py`, `studio/nightly.py`, `studio/weights.json`)

What it does: per campaign, ranks each post (0–1) on completion 30%, sends/reach 30%, views 15%, saves/reach 10%,
not-skipped 15%; then for *every* dimension (style, song, section, look, hook, length, hour posted, caption, every
`knob:*`) computes a recency-weighted mean rank per option, shrinks it toward 0.5 with PRIOR=5, writes
`weight = 2^lean` and `stats=[k, keff, mean]`. nightly.py ignores the weights for knobs and runs Thompson sampling on
`Beta(1 + mean·keff, 1 + (1−mean)·keff)` per option, with 20% of videos fully random and the subject knob overridden by
`freshen` (no repeat within 3 nights).

**Is it signal or noise? Noise, at this size.**
- `weights.json` today: 29 campaigns, 1,565 options, every weight in [0.87, 1.13], 0 automatic retirements anywhere
  (MIN_RETIRE=8 posts on one option and mean+2sd < 0.45 never happens with 10–50 posts spread over 50–200 options).
  All four retirements were done by hand in `nightly.yaml`.
- Options have k = 1–6 posts. The sd of a mean of k uniform ranks is 0.29/√k: with k=3 that is ±0.17, so math_time's
  `knob:topic` means (zeta 0.37 … paths 0.70, k=1–6) are indistinguishable from chance. Yet Thompson sampling will
  happily prefer "paths" (k=1, 0.70) tonight.
- **Every post feeds ~15 dimensions at once with the same rank**, so song, topic, palette, hour, caption line and cut
  are perfectly confounded within a post; nothing is held constant. The only randomisation that would make a knob
  identifiable is the 20% EXPLORE, and those 20% are also the posts where *every other* knob is random.
- **Hour posted** is a learned dimension but nightly never chooses the hour (topup assigns slots), so it is purely a
  confounder: a post's rank absorbs its slot's effect (±0.3 sd in the network table above) and attributes it to the
  topic it carried.
- **Age confound:** MIN_AGE_H=20 counts a 21-hour-old post against a 3-day-old one on raw views (views keep rising
  for days; Nov 26's median is 80 against Nov 24's 115 partly for this reason). The rank on `views` is therefore also
  a rank on age.
- **Completion** (`done = watch / secs`): correct in principle (`secs` is the clip's own window after `tighten`, so
  short cuts are compared fairly), but `averageTimeWatched` is capped by loops (>1 means replays) and there is one
  bad value (glitch post, watch 156.9 s on a ~20 s clip) that `ranks()` handles only because it is rank-based. The
  mix gives completion 30% + not-skipped 15% = 45% to retention, 40% to sends+saves, 15% to views: reasonable, but
  `sends` and `saved` are per *reach* with a 30 floor, so on an account whose typical post reaches 40 people, one
  share moves a post from rank 0.3 to rank 0.9. That is why psychedelic.station's and the loose.change's weights are
  as flat as everyone else's despite having the most posts.
- **EXPLORE=0.2:** at these sizes exploration is not the constraint; identifiability is. 20% random on 12 knobs
  mostly re-tests looks already known to lose (e.g. psy `marble`, which had to be retired by hand). 10% is enough
  once retirements are automatic.

**Sharper scoring, concrete:**
1. **One outcome per post, computed at a fixed age.** `score = z(log(views at 48 h))` within the account over the
   trailing 14 days, plus `keep = (shares + saves + 0.5·comments) / views` on a Beta(2, 200)-shrunk estimate. Final
   `score = 0.6·z_views + 0.4·z_keep`. Wait until `fetched_at − sent_at ≥ 48 h` (MIN_AGE_H 20 → 44) and snapshot the
   48 h figures into posts.json (the metrics job overwrites, so keep a `views_48h` field the first time a post passes
   48 h). Per-account z removes the account's size and the day's network-wide drift; it is what "per-account z-scores on
   views after 24 h" buys, and it makes campaigns comparable so cross-campaign facts (cut length, hour) can be learned
   once.
2. **Subtract the slot effect** before attributing: fit `hour_effect[h]` once per week on the whole network (the
   table in §2, with shrinkage), and use `score − hour_effect[hour]`. Same for `cut` length.
3. **Learn three knobs, report the rest.** Per style: the subject knob (`SUBJECT` in nightly.py), `cut`, and hook
   on/off. Everything else (palette, trans, screen, label, pace…) is set per account by hand to the operator's taste
   and listed in LEARNED.md as a table, not sampled. Three knobs × ~8 options × 5 posts/night is learnable in two
   weeks; 12 knobs is not.
4. **Retire by posterior.** For the subject knob: Gaussian posterior on the mean score, prior N(0, 0.5²), retire when
   P(mean < −0.3) > 0.85 after ≥4 posts; un-retire automatically after 21 days. This replaces MIN_RETIRE=8 and the
   hand list in nightly.yaml.
5. **Is "top-3 subjects, rotate" better than Thompson here?** At 15–90 posts per account it is equivalent and more
   legible: with 3 knobs and a per-account z-score, Thompson over the subject knob converges to "mostly the top 2–3,
   occasionally the rest", which is exactly top-3-rotate with 1-in-4 exploration — and `freshen` already forces
   rotation. Recommendation: keep Thompson but on the z-score posterior (Gaussian TS, not Beta on a rank), restrict it
   to the subject knob, and print the top-3 per account in LEARNED.md so Dylan can override by eye. Drop `hour
   posted`, `caption`, `section` and `palette` from the learned dims (keep them in the stats table).
6. **Song weighting.** `wsong`/`wsec` are 0.9–1.1 so song choice is "fewest videos first" in practice. That is fine
   for coverage, but the goal is streams: once the audio page exists, weight songs by *saves+shares per view across
   the network* (the song people keep is the song to push), and let one or two songs take 40% of the night.

### 3.4 Metrics gaps: 10 accounts with no `m`

Facts from today's `metrics.yml` run 45876580322 (every 3 h, `--instagram-only`), all campaigns "success":
- algo_races, pixel_tests, notes_app, notes_her, notes_him (IG_TOKEN_2..6) and toon_edits, museum_zoom, notes_date,
  lowpoly_stories, notes_college (IG_TOKEN_7..11): every `GET /{media_id}/insights` answers
  `(#10) Application does not have permission for this action (HTTP 400, code 10)`. `_media_metrics` catches it, logs
  `instagram_insights_unavailable` and returns `()`, so posts.json gets `metrics: []` and dash_data writes `m: {}`.
- stare_lab, circle_atlas (eye.trick.lab, fourier.reveal, Adrianne's Pages, published with Page tokens from
  `IG_PAGE_TOKENS`): `Unsupported get request. Object with ID '…' does not exist, cannot be loaded due to missing
  permissions`.
- traps.md (2026-11-25) says the insights permission was added to the app and "their tokens had to be generated
  again": the log proves the tokens in use today still do not carry it.

Exact fixes:
1. **IG_TOKEN_2..6 (dashboard "Unified login" tester tokens):** in the app dashboard, Use cases → Instagram API →
   Permissions, confirm `instagram_business_manage_insights` is *added to the use case* (not just listed), then
   **Generate token again for each tester account** and paste as the same secret. `refresh_tokens.py` cannot do this:
   a refresh re-issues the same scopes.
2. **IG_TOKEN_7..11 (connect.closequarters.vip):** the login dialog in `cqconnect/worker.js` line 102 sends only
   `config_id=${CONFIG_ID}`; scopes come from that Facebook Login for Business configuration. Add
   `instagram_manage_insights` (and `pages_read_engagement` if the config lacks it) to the configuration in the
   dashboard, then have each of the five accounts open `connect.closequarters.vip/connect?u=<handle>` again;
   `connect.yml` overwrites the secret.
3. **eye.trick.lab / fourier.reveal:** `scripts/page_tokens.py` mints Page tokens from Dylan's `me/accounts`; a Page
   token can only read Instagram insights if Dylan's role on the Page includes the *Insights* task (ANALYZE). Adrianne
   gave content/publish access; ask her for **Full control** (or at least Insights) on both Pages, then re-run
   `tokens.yml` so `IG_PAGE_TOKENS` is re-minted. Add `tasks` to the `me/accounts` fields in `ig_check.py` so this is
   visible (`fields=name,tasks,instagram_business_account{username}`).
4. **Make the failure loud and the check cheap:** `src/publishers/instagram.py::_media_metrics` logs a warning per
   post; `cli.py` logs `post_metrics_cached fetched=9` as if it worked. Count empty results and emit one
   `::error::` + Discord line per account when *all* its posts came back empty ("no insights permission on <slot>").
   And print `debug_token` scopes in `scripts/ig_check.py` (names only), run by `ig-check.yml`.
5. While the permission is missing, `studio/learn.py` reports "No posts with numbers yet" for those 10 campaigns and
   nightly runs blind on them; `freshen` still rotates subjects, so nothing breaks, but ten accounts' worth of signal
   (82 posts and 51 queued) is lost until this is done.

### 3.5 Cover frames and the grid

- `posting.cover_at_sec` exists in `src/config.py` and reaches Instagram as `thumb_offset`; it is set only on
  `math_time` (5 s; fourier_reveal is paused). Every other campaign posts frame 0 as the cover.
- Renderers that deliberately design frame 0 (per `docs/brain/styles.md`): psy (no text, field already moving — the
  psy sheet shows a full kaleidoscope at frame 0), liminal (memory line held from frame 0), physics (rule stated,
  ball in flight), retro (opens on the most-moving clip), glitch (`opener` clean shot since 11-25), vintage, nyc (loop
  closes into frame 0), earth, cutout (cut-out centred), type (readable lyric), tests8 (instruction from frame 0),
  fact reels (headline card on frame 0). These grids are coherent *per account*: one look, one text position.
- Not designed, or wrong for a grid:
  - **race** (`scratchpad/system/race.png`): frame 0 is four rows of unsorted dots with "0 steps" and no question;
    the "which one finishes first?" line appears at frame 90 (3 s). Cover should be frame ~90 (`cover_at_sec: 3`) or
    the question should be on frame 0.
  - **notes / her / him / date / college** (`notes.png`): frame 0 = the whole card, which is right for a text page
    (the grid reads as a notes app), but the gradient and type are identical across the five accounts, so the five
    grids are indistinguishable from each other — fine for viewers, bad if Instagram's matcher compares them.
  - **math**: the 5 s cover is right (the reveal has started); keep.
  - **reveal / stare / measure / hue / ebru**: the ask holds the first ~4.6 s with a filling bar, so frame 0 is the
    question: good covers.
  - **close__quarters and dylancantor23**: the grid is empty because every reel is a trial reel (3.1 §4). The cover
    discussion is moot until that changes. The band account should carry its best 9 (one per style, band footage) as
    regular reels, then trial the rest.
- Rule to write into `docs/brain/playbooks/new-format.md`: frame 0 must contain the format's "look at this" (the
  question, the line, the subject) inside y 250–1500; if the renderer cannot, set `cover_at_sec` in config.yaml to the
  first frame that does. Dash: show the cover frame thumbnail per queued post (`dash_data.py` already has the video
  URL; a `thumb_offset` field would let the page say which frame is the cover).

### 3.6 Cross-posting

- **Instagram side:** the 2021 rule (still Mosseri's stated position, re-confirmed 2024) demotes reels carrying
  *another app's* logo/watermark or low resolution; your own logo is fine. Our files are watermark-free 1080×1920
  H.264 from our own renderers, so posting the same file to TikTok and Shorts costs nothing on Instagram as long as
  nothing comes *back* with a TikTok watermark. Never pull a clip back from TikTok.
- **Band account reposting niche winners:** allowed (same owner, same app), but the originality rule is
  account-level over 30 days: if @close__quarters "primarily" posts videos that already exist elsewhere, Instagram
  labels them as reposts (label links to the niche account, not the band) and can drop the band from recommendations.
  The useful inversion: post a format's best new video on **@close__quarters first** (as a regular, not trial, reel),
  then on the niche account a day later. If the matcher labels the later copy as a repost, the label links *to the
  band*. Cap at 1 of the band's 8 a day, and only for formats whose visuals do not clash with the house rule (no band
  footage on niche accounts is a niche-side rule; the band account may carry anything). Collab tags would do this
  more cleanly but are off by house rule.
- **TikTok / YouTube Shorts via Buffer:** `knick_creates_tt` / `knick_creates_yt` exist (dry_run, campaign
  `_knick_creates*`). HANDOFF §4's music problem was about *other people's* songs; ours are ours. On TikTok a
  baked-in song that is in TikTok's library (via the distributor) gets auto-attributed to the official sound, which is
  the same funnel as Instagram's; on YouTube, Content ID on your own channel is a claim you own. Worth a 1/day feed of
  the previous day's top-decile niche reel (by the z-score above) to both, from `_knick_creates` renamed to a Close
  Quarters campaign, with the YouTube title "{song} – Close Quarters" and the first line crediting the song. Medium
  effort; measure with the per-platform `insights.py` finding, which already exists for exactly this comparison.

## 4. Research (sources)

- Instagram Audio API (search `/ig_audio?audio_type=music|original_sound`, attach via `audio_configuration` at
  `POST /{ig-user-id}/media`, Facebook Login apps only): Meta changelog
  https://developers.facebook.com/documentation/instagram-platform/changelog.md ; API page
  https://developers.facebook.com/docs/instagram-platform/content-publishing/audio-api/ ; wrapper confirmations
  https://www.ayrshare.com/docs/apis/post/social-networks/instagram , https://info.bundle.social/api-reference/platforms/instagram-music ,
  https://docs.zernio.com/platforms/instagram/posts
- Licensed audio detected in a reel is re-attributed to artist + title and joins the song's audio page:
  https://help.instagram.com/iphone-app/329208821595430 ; how songs get into Meta's library (distributor delivery):
  https://soundcloud.com/topic/category/how-to-distribute-music-to-instagram , https://www.soundstripe.com/blogs/instagram-music-library
- Media insights permissions (`instagram_business_manage_insights` for Instagram Login, Mar 2025; Advanced Access
  only for accounts you don't manage): https://developers.facebook.com/blog/post/2025/03/24/user-and-media-insights-on-instagram-api-with-instagram-login/ ,
  https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights/ ; the (#10) error guide
  https://support.dataslayer.ai/instagram-insights-how-to-solve-the-error-10-application-does-not-have-permission-for-this-action
- Ranking signals 2025 (watch time, likes/reach, sends/reach; no precise multipliers):
  https://www.socialmediatoday.com/news/instagram-shares-algorithm-insights-2025/738034/ , https://buffer.com/resources//instagram-algorithms/
- Posting frequency (Mosseri: "no perfect number", more posts = more chances; ~2 feed posts/week + stories as the
  only concrete figure): https://www.socialmediaexaminer.com/how-to-determine-your-ideal-instagram-posting-frequency/ ,
  https://routenote.com/blog/how-often-you-should-post-on-instagram/ , https://www.inman.com/2025/03/07/head-of-instagram-reveals-secrets-to-social-media-success/
- Originality / aggregator rules (Reels 2024, photos+carousels 2026-04-30, 30-day rolling, labels, Account Status):
  https://creators.instagram.com/recommendations-and-originality , https://creators.instagram.com/original-content-guidelines/ ,
  https://tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator ,
  https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/ , https://techcrunch.com/2025/07/14/following-youtube-meta-announces-crackdown-on-unoriginal-facebook-content
- Inauthentic sharing (same content across multiple entities at high rates): https://transparency.meta.com/features/approach-to-ranking/content-distribution-guidelines/inauthentic-sharing
- Watermarks / recycled content (2021 rule; own logo OK): https://tubefilter.com/2021/02/10/instagram-reels-with-tiktok-watermark-less-discoverable/ ,
  https://www.socialmediatoday.com/news/instagram-clarifies-including-your-own-logo-on-a-reel-is-ok/730852
- Trial reels hidden from grid and followers until graduated: https://buffer.com/resources/instagram-trial-reels/ ,
  https://metricool.com/instagram-trial-reels/
- Hashtag cap of 5 (Dec 2025; `MAX_HASHTAGS` already matches): https://www.socialmediatoday.com/news/instagrams-implementing-new-limits-on-hashtag-use/808309/
- Shadowban/volume: no official threshold; spam signals, not a daily count: https://later.com/blog/instagram-shadowban/

(developers.facebook.com, creators.instagram.com, transparency.meta.com, routenote.com and info.bundle.social could
not be opened from this session; the claims above come from search summaries and should be re-read on the page
before coding against field names.)

## 5. Recommendations, ranked by expected impact

1. **Song audio pages (large, the lever).** (a) Confirm EDUCATION is delivered to Meta via the distributor; if not,
   deliver it (days). (b) Run `scripts/ig_audio_search.py --account close_quarters_ig --query "close quarters"` from a
   workflow; if the 15 tracks appear, add `ig_audio_id` per song (in `studio/songs/<slug>/song.json`) and have
   `src/cli.py` (topup, ~line 1772) fill `PublishRequest.audio_id` + `video_volume=0` on Facebook-login accounts.
   (c) If not yet in the catalogue, test route 3.1 §6b (band-owned original sound per song attached to one niche post).
   (d) Once attributed, change the CTA bank from "link in bio to stream {name}" to "tap the audio / save the sound"
   wording without an ask (e.g. "the sound is {name}, saved under @close__quarters"). Measure: the audio page's reel
   count and Spotify/streams by week.
2. **Un-trial the band account (quick).** `accounts.yaml`: `trial_reels: false` for close_quarters_ig (keep trials on
   dylancantor23 if wanted). Post the best band-footage reels as regular so the profile the funnel points to has a
   grid. Measure: profile visits in account insights, follower delta per week.
3. **Fix the ten blind accounts (quick, operator + 2 code lines).** §3.4 steps 1–3 for the operator; code: scopes in
   `ig_check.py`, Page `tasks` in `ig_check.py`, per-account "all empty" alarm in `cli.py` metrics, fallback to the user
   token in `_media_metrics` when a Page token gets "does not exist".
4. **Move every on-screen credit into y 250–1500 (medium, 9 files).** `mathviz/kit.py` 1885 → 1470; `race_video.py`
   bottom → 1470; `alife_video.py`, `tinycode_video.py` H−95 → 1470; `fluid_video.py` H−70 → 1470; `hue`/`measure`
   1590 → 1470; `reveal`/`stare` 1540 → 1470; `asciiviz/engine.py` label (24, 40) → (24, 270). Add a credit to psy and
   liminal (small, muted, y≈1450) — those two accounts have the keep rates that convert. Text pages stay bare by
   design; their caption already credits.
5. **Cadence (quick, config).** Set `posting.posts_per_day` to match `nightly.yaml` per_night everywhere (psy 2+fact
   reels, nostalgia 2+fact, dylancantor23 3, loose.change 1); new accounts 1/day for days 1–7, 2/day for days 8–21,
   then 3–5 only if median views beat 100; cap any account at 5/day *including* carousels and fact reels (`topup`
   counts them, the carousel/factreel jobs do not check `posts_per_day` the same way). Shift windows: `start_hour`
   12, `end_hour` 23 for niche accounts (the 10–11 slots are the weakest; 17 and 20–23 the best).
6. **Fix bio-link measurement (quick).** Check `cq-listen` KV / `/stats` (zero taps since 11-22 is not plausible
   with 150 posts a day); give every account a tracked path (`/math`, `/ascii`, … in `link/worker.js` + `LINK_NAMES`
   in learn.py); point `TARGET` at a song-first landing (closequarters.vip/listen with the 15 tracks + smart links),
   not the home page. Add the 7-day taps per account to the dashboard account cards.
7. **Learner v2 (medium, `studio/learn.py` + `nightly.py`).** Per-account 48-h z-score + shrunk keep-rate as the
   single score; hour/cut effects fitted network-wide and subtracted; learn only subject/cut/hook; Gaussian Thompson
   on the subject knob; posterior retirement; EXPLORE 0.2 → 0.1; `knob:cut` default `short` for VISUAL styles
   network-wide (completion 0.46 vs 0.17 at equal views). Write LEARNED.md as "top-3 per account" tables.
8. **replies.py coverage (quick).** Extend `TOKENS` with toon_ig/zoom_ig/date_ig/lowpoly_ig/college_ig (IG_TOKEN_7..11)
   and read `IG_PAGE_TOKENS` for eyetrick_ig/fourier_ig; print a per-run summary line so the publish log shows it ran.
   Vary the three niche first-comment lines per campaign (today identical across 20 campaigns).
9. **Covers (quick).** `cover_at_sec: 3` on algo_races; document the frame-0 rule in `playbooks/new-format.md`;
   dashboard shows the cover frame per queued post.
10. **Cross-posting (medium).** 1/day top-decile niche reel to TikTok + Shorts via the Buffer channels; band-first
    posting of each format's best new video (regular reel) then niche a day later; never bring a file back from TikTok.
11. **Health-check additions (quick, docs).** `SECRETS_PAT` expiry; `ig-check` scopes; "accounts with 0 posts
    carrying `m` for 24 h" as a red line on the dashboard (today it silently shows `—`).

## 6. Risks

- **Originality notices:** vintage already got one; glitch, cinema, toon and zoom use famous public-domain films/
  paintings. zoom.into.art shows an unaltered painting for the first beats — the closest to a "repost" of the lot;
  keep the crop/motion from frame 0. Watch Account Status weekly on those four.
- **Trial reels on the band account** are also a reach risk: SS_PERFORMANCE graduates few, so most band posts never
  reach followers at all.
- **Same first-comment text on 20 accounts within minutes** is the one pattern in our control that resembles
  coordination; vary it.
- **AI-generated clips (retro, lowpoly plates)** should carry Instagram's AI label where they show realistic scenes
  (PLAYBOOK §8); the API cannot set it.
- **Token hygiene:** the fix in §3.4 means the operator regenerates five tokens; keep them out of chat, into
  secrets only; the connect link is the safer path for IG_TOKEN_7..11.
- No engagement bait found in captions, first comments or hooks (bait lines were removed 2026-11-23); the suggested
  audio CTA must stay a statement, not an ask.
