# Accounts

Back to [[README]]. Source of truth: `accounts.yaml` (channels) and `campaigns/*/config.yaml` (what posts where).

| account | `accounts.yaml` name | campaign | style(s) / renderer | posts/day | window (NY) |
|---|---|---|---|---|---|
| @close__quarters | close_quarters_ig | cq_band | band, lofi, cursor (lyric styles: the band's own footage) | 3 (cutout 2, band 1; style quota) | 9–23 |
| @dylancantor23 | dylancantor23_ig | cq_producer | producer (stems build / strip in a DAW) | 3 | 9–23 |
| @the.loose.change (was nickdotname) | nickdotname_ig (Buffer) | nick_studio, closequarters (**paused** 2026-11-24: every meme clip in its pool was ripped film/TV/game footage) | type (kinetic lyrics) + memes | 1 + 0 | 12–23 / all day |
| @psychedelic.station | psychedelic_station_ig | psy_station | psy, collage (+ carousels, fact reels) | 1 + 2 fact reels | 12–23 |
| @nostalgia.hub.vhs | nostalgia_ig | nostalgia | liminal (+ carousels, fact reels) | 1 + 2 fact reels | 12–23 |
| @math.explainers (**deleted 2026-11-27**: linked to the wrong profile; a new account will replace it) | math_ig | math_time | math (integrals, Fourier, zeta, fold, sci8) | **paused** | — |
| @glitch.archive.exe | glitch_ig | glitch_archive | glitch | 2 | 12–23 |
| @ascii.terminal.dreams | ascii_ig | ascii_art | ascii | 5 | 12–23 |
| @physics.bounce.lab | physics_ig | physics_sims | physics (needs the song's Ableton hits) | 5 (fluid 3, stopit 1, physics 1) | 12–23 |
| @earth.data.live | earth_ig | earth_data | earth | 5 | 12–23 |
| @retro.vibes.arcade | retro_ig | retro_arcade | retro (Kaggle-made PS2 clips) | **paused** 2026-11-27 (review) | — |
| @rocket.league.lit | rocket_ig | rocket_league | rocket (our own clips) | 3 | 12–23 |
| @vintage.media.archive | vintage_ig | vintage_archive | vintage (pre-1931 films as old prints) | **paused** 2026-11-27 (review; originality notice) | — |
| @nyc.daily.aesthetic ("Daily NYC Memes & Culture") | nyc_ig | nyc_daily | nyc (city walk, memes, then/now, facts) | 4 | 12–23 |
| @tiny.code.loops ("Tiny Code & Generative Art") | tinycode_ig | tiny_code | tinycode (a short numpy program and what it draws) | 3 | 12–23 |
| @ascii.cinema.tty ("ASCII Cinema & Film") | cinema_ig | ascii_cinema | cinema (public-domain films set in type in a terminal, cut on the bar: comedy, dream or launch reels) | 3 | 12–23 |
| @digital.petri.dish ("Digital Petri Dish & Artificial Life") | petri_ig | petri_dish | alife (a slime-mould simulation of thousands of simple agents, moving to the song) | 2 | 12–23 |
| @rotation.illusions ("Rotation Illusions") | illusions_ig | illusions | illusion (dot shapes whose turning direction is up to your eyes; a disc that reads as a cone; a wheel that runs backwards) | 5 | 12–23 |
| @algorithm.races ("Algorithm Races", no Page: Unified login, token `IG_TOKEN_2`) | races_ig | algo_races | race (sorting algorithms on the same shuffled numbers; search algorithms through one maze) | 3 | 12–23 |
| @8bit.tests ("8-Bit Tests", no Page, token `IG_TOKEN_3`) | tests8_ig | pixel_tests | tests8 (play-along pixel tests: pause when it fits, follow the gem, watch the order, count the fireworks, early or late) | 3 | 12–23 |
| @moth.ate.my.notes (no Page, token `IG_TOKEN_4`) | notes_ig | notes_app | notes (one thought on a gradient, like an Instagram text post; no song label on the card) | 2 | 12–23 |
| @crying.in.trader.joes (no Page, token `IG_TOKEN_6`) | her_ig | notes_her | notes_her (one thought on a gradient in a girl's voice; bank studio/notes/her.txt) | 2 | 12–23 |
| @grip.tape.thoughts (no Page, token `IG_TOKEN_5`) | him_ig | notes_him | notes_him (one thought on a gradient in a skater guy's voice; bank studio/notes/him.txt) | 2 | 12–23 |

**closequarters memes** (when un-paused): the six songs share one clip pool, so a clip's 21-day cooldown is kept across every song and every account version (`Selector.select_batch_multi(visual_pools=...)`); Instagram and TikTok each get their own clip (`variation.per_account`), and with `repeats: false` an empty slot beats a repeat.

`clubs` is the Clubs app's own campaign: blocked from every Close Quarters account. `knick_creates_*` are
Nick's older Buffer channels (not Close Quarters).

## How an Instagram account is connected

Every direct-posting account is an Instagram **professional (Creator)** account linked to a **Facebook Page**
that Dylan's Facebook manages. The app **"Close Quarters Clip Engine"** has been granted those Pages and
Instagram accounts (opted in to *all current and future* Pages and Instagram accounts since 2026-11-23, so new
ones need no re-grant). One user token, `IG_TOKEN` (a long-lived token from the Graph API Explorer, extended in
the Access Token Debugger), posts for all of them. `channel_id` in `accounts.yaml` is the Instagram user id
(`me/accounts?fields=name,instagram_business_account{username}` in the Explorer lists them).

Nick's @nyc.daily.aesthetic lives in Nick's own Meta account; its Page sits under Dylan's Facebook so it rides the
same token. Full steps: [[add-account]].

## Profiles

Each campaign's `brand/profile.jpg` is the account picture; the dashboard shows each account's live picture
(fetched daily with business_discovery). Bios link to the band.

## Added 2026-11-25 (own tokens from connect.closequarters.vip, Business login; never expire)
- @rubberhose.radio: toon_edits (toon), IG_TOKEN_7
- @zoom.into.art: museum_zoom (zoom), IG_TOKEN_8
- @situationship.notes: notes_date (notes_date), IG_TOKEN_9
- @what.if.town: lowpoly_stories (lowpoly), IG_TOKEN_11
- @dining.hall.philosopher: notes_college (notes_college), IG_TOKEN_10
New accounts post 2 a day for their first week. situationship.notes is **paused** since 2026-11-27 (its bank overlapped
crying.in.trader.joes and carried the recommendation-guideline risk; the clean lines moved to the other banks).

**Cadence since 2026-11-27** (docs/brain/reviews/2026-11-26): posts/day above is the whole day including fact reels; the
carousel job is off; fact reels run twice a day on nostalgia and on psychedelic.station with non-drug specs only; niche
windows open at noon New York (10–11 was the weakest hour, 17 and 20–23 the best); no two posts within 60 minutes on one
account across jobs. The band accounts post **normal reels, not trials** (`trial_reels: false`). Each campaign has its own
three first-comment wordings. cq_band picks by `selection.style_quota` (cutout 2, band 1).

### Adrianne's pages (2026-11-25)
- **@eye.trick.lab** (`eyetrick_ig`, campaign `eye_tricks`): the illusion style, its own renders. Page "Eye Tricks".
- **@fourier.reveal** (`fourier_ig`, campaign `fourier_reveal`): the math style. Page "Fournir".
Both post through their Page tokens (IG_PAGE_TOKENS, from IG_TOKEN's grant; Dylan manages the Pages by invite), 2 a day.
satisfying.sims.physics, creature.sim and code.makes.art have no Page yet (creation errored); they can come in
through connect.closequarters.vip (tester invite + "Continue with Instagram"), IG_TOKEN_13/14/16 reserved.
- 2026-11-26: eye.trick.lab and fourier.reveal were rendering rotation.illusions' and math_time's style with the same
  subjects (fourier.reveal even posted the same science explainer as math_time the same night). They now run their own
  formats: **eye.trick.lab → campaign stare_lab** (stare-at-the-dot illusions, studio/stare_video.py) and
  **fourier.reveal → campaign circle_atlas** (countries drawn by Fourier circles, studio/reveal_video.py). eye_tricks
  and fourier_reveal are paused.
