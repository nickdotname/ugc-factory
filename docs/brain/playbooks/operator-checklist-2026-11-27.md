# Operator checklist after the 2026-11-26 review (things only a human can do)

Back to [[README]] · the plan: `docs/brain/reviews/2026-11-26/README.md` · the code is in PR #199.
Everything below is a step the code cannot take: a token, a Meta or Google dashboard, a distributor, a deploy.
In order of impact. Nothing here needs a secret in chat: tokens go straight into GitHub secrets.

## 1. Give the ten blind accounts their numbers (10 minutes, unblocks the learner)
1. Actions → `ig-check` → run. It now prints each token's permissions and each Page's tasks and flags
   `MISSING instagram_business_manage_insights` / `instagram_manage_insights` and `no ANALYZE`.
2. **IG_TOKEN_2..6** (algorithm.races, 8bit.tests, moth.ate.my.notes, grip.tape.thoughts, crying.in.trader.joes): in the
   Meta app dashboard confirm `instagram_business_manage_insights` is in the Instagram API use case, then **generate
   each tester token again** (a refresh keeps the old scopes) and paste it into the same secret name.
3. **IG_TOKEN_7..11** (rubberhose.radio, zoom.into.art, situationship.notes, dining.hall.philosopher, what.if.town): add
   `instagram_manage_insights` (and `pages_read_engagement`) to the Facebook-Login-for-Business configuration that
   `cqconnect/worker.js` uses, then each account reopens `connect.closequarters.vip/connect?u=<handle>`.
4. **eye.trick.lab / fourier.reveal**: Adrianne grants Dylan Insights (ANALYZE) on both Pages; re-run `tokens.yml`.
5. Until done, `metrics` is red for those campaigns by design (`insights_denied`), and their dashboard cards carry a red
   "insights denied" line.

## 2. Put EDUCATION's audio pages on every reel (the biggest lever)
1. Confirm with the distributor that Facebook/Instagram is in the album's store list (delivery takes 1–4 weeks after
   release; the album came out 2026-11-13).
2. Actions → `audio-search` → run with query "close quarters", tick `songs` (one search per title). Fifteen rows with
   artist Close Quarters means the album is in Meta's library: copy each `audio_id` into
   `studio/songs/<slug>/song.json` as `"ig_audio_id"` (the run prints the exact line per song) and open a PR.
3. No rows yet: retry in a few days. Meanwhile the band's own named sounds work the same way (`type: original_sound`).
4. Once attached, watch the song's audio page on Instagram: every niche reel should list under it.

## 3. The band account's grid
- Trial reels are off from the next top-up. Posts already booked in `outbox/` keep `trial: true` and drain.
- Pin the three best cutout reels on @close__quarters once they have posted as normal reels.

## 4. Bio links (the one conversion number)
1. Deploy the link worker: paste `link/worker.js` into the cq-listen editor in the Cloudflare dashboard and Deploy, or
   `cd link && npx wrangler login && npx wrangler kv namespace list` → put the `cq-listen-clicks` id into
   `link/wrangler.toml` → `npx wrangler deploy`. Settings → Bindings must show `CLICKS` → `cq-listen-clicks`.
2. Prove it counts: open `<link_base>/math` on a phone, then `<link_base>/stats`: `last.math.at` must be that tap.
3. Put each account's path (table in `link/README.md`: `/math`, `/ascii`, `/8bit`, `/loose`, ...) into Edit profile →
   Links on the 26 accounts that have none yet.
4. When a song-first listen page exists, set the worker variable `TARGET` to it; all 30 paths follow.

## 5. YouTube Shorts (weeks of lead time: start the Google side now)
1. Google Cloud: a project with YouTube Data API v3 enabled; a Desktop-app OAuth client → secrets `YT_CLIENT_ID`,
   `YT_CLIENT_SECRET`. Publish the OAuth consent screen (a "Testing" screen expires refresh tokens after 7 days).
2. Submit the **YouTube API Services Audit and Quota Extension form** now: until the audit clears, every upload from
   the project is locked to private. Read the real quota numbers in Cloud Console → Quotas (sources disagree) and ask
   for more on the same form.
3. Create the pilot channels as Brand Account channels under one Google login (rotation.illusions, math.explainers,
   ascii.terminal.dreams, physics.bounce.lab, close__quarters); phone-verify each (lifts the 10-uploads-a-day cap).
4. Per channel, on the laptop: `YT_CLIENT_ID=… YT_CLIENT_SECRET=… python scripts/yt_connect.py <n>` → the refresh token
   goes straight into `YT_REFRESH_TOKEN_<n>`; add the printed `accounts.yaml` entry (example at the end of the file).
   Playbook: [[add-youtube-channel]].

## 6. what.if.town narration
- First real test once the renderer wiring is merged: Actions → `studio.yml` with `campaign=lowpoly_stories count=1
  set=voice=on`; look for `narrator ready` in the log and listen to the clip in the library release. Playbook:
  [[narration]]. The model is cached by the workflow; nothing to install by hand.

## 7. Watch weekly
- Account Status on vintage (paused), glitch, cinema, toon and zoom for originality notices; psychedelic.station's
  recommendation eligibility; the 30-day originality clock on the.loose.change (clean since 11-24).
- `SECRETS_PAT` expiry: the one untracked single point of failure for token refreshes.
- The dashboard: followers Δ7d per account, bio taps, and any red "insights denied" line.

## 8. Decisions still open (yours)
- the.loose.change: rebuild the meme pool from own footage and move it off Buffer (needs Nick's login on
  connect.closequarters.vip), or retire it.
- retro.vibes.arcade is paused: send the Kaggle budget to ascii's single-subject clips, or rebuild on our own renders.
- The notes pages: two or three voices instead of five (situationship.notes is paused; the others post 2 a day).
- Footage: a 30-minute phone session (two people, plain wall, each song's chorus) would double the cutout library and
  let the band account cover all 15 songs.
