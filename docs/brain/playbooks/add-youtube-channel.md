# Playbook: add a YouTube channel (direct, no Buffer)

Back to [[README]] · see [[accounts]], [[pipeline]], [[traps]]. The publisher is `src/publishers/youtube.py`; its
posts wait in `outbox/yto-*.json` beside Instagram's and the same `publish.yml` sends them at their slot.

## 0. What Google requires, honestly

Read this before the first channel; several steps take days and the quota numbers disagree between sources.

- **One Cloud project, one OAuth client.** APIs & Services → enable **YouTube Data API v3** → Credentials →
  OAuth client ID, type **Desktop app**. Its client id and secret become the GitHub secrets `YT_CLIENT_ID` and
  `YT_CLIENT_SECRET`, shared by every channel.
- **OAuth consent screen and the API audit.** Until the project passes Google's **API Services Audit**, every
  video uploaded through it is **locked to private** whatever `privacyStatus` says, and a "Testing" consent screen
  revokes refresh tokens after seven days. Publish the consent screen, then submit the *YouTube API Services -
  Audit and Quota Extension Form* (linked from the Data API quota page in the Cloud Console). Expect questions and
  a wait of days to weeks. Submit it on day one; nothing public ships before it clears.
- **Quota.** The cached docs say 10,000 units a day per project, 1,600 per upload (six uploads); later reports say
  uploads got a bucket of their own around 100 a day. **The figures conflict: read them in the Cloud Console
  (APIs & Services → YouTube Data API v3 → Quotas) and ask for more on the same form.** The publisher keeps its own
  ledger (`outbox/youtube_quota.json`, YouTube's Pacific day) and refuses to start an upload past the cap; the cap
  defaults to 100 uploads and 10,000 units and is set with the workflow env `YT_DAILY_UPLOADS`. A refusal logs
  `quota_exhausted`; the post waits for the next run.
- **Brand Account channels under one Google login.** youtube.com → avatar → Switch account → View all channels →
  Create a channel. Each is picked in the consent chooser, so each needs its own refresh token (`YT_REFRESH_TOKEN_n`).
- **Phone-verify every channel** (youtube.com/verify, one phone can verify two channels a year). Unverified channels
  are capped at about 10 uploads a day and cannot upload over 15 minutes; verification lifts both.
- **Shorts are detected, not declared:** vertical (or square) and under three minutes. Our renders are 1080x1920 and
  under 60s. No `#Shorts` needed, but it does no harm.
- **Scopes:** `youtube.upload` (the insert) and `youtube.readonly` (the figures). Watch time needs the YouTube
  Analytics API, a different scope and endpoint: not built, see the TODO in the publisher.
- Everything in `CLAUDE.md` still applies: no band footage on niche channels, no bait, public-domain or own footage.

## 1. The channel (operator, ~10 min)
1. Create the Brand Account channel under the band's Google login; handle, picture, description linking the band.
2. Phone-verify it. Settings → Channel → Feature eligibility must show "Intermediate features" on.
3. In YouTube Studio → Settings → Upload defaults: nothing needed; the publisher sends title, description, tags,
   category 10 (Music), public, not made for kids, on every upload.

## 2. The token (operator's laptop, never CI)
```
export YT_CLIENT_ID=... YT_CLIENT_SECRET=...     # from the Cloud Console; not in chat, not in the repo
python scripts/yt_connect.py 3                   # the next free slot, 1-16
```
A browser opens; **pick the channel, not the login's own channel**, in the chooser. The script stores the refresh
token as the GitHub secret `YT_REFRESH_TOKEN_3` through `gh` (or, with `--no-gh`, into a 0600 file for
`gh secret set ... <` and deletion). It prints only the channel id and title. If Google returns no refresh token,
revoke the app at myaccount.google.com/permissions and run it again (`prompt=consent` is already set).

## 3. The repo (PR)
1. `accounts.yaml`:
   ```yaml
   - name: rotation_yt
     network: youtube
     provider: youtube
     api_key_secret: YT_REFRESH_TOKEN_3
     channel_id: UCxxxxxxxxxxxxxxxxxxxxxx     # the id yt_connect.py printed
     post_type: short
     title_strategy: require                 # Shorts show ~40 characters of a 100-character title
     notify_subscribers: false               # on only for a channel posting once or twice a day
     slot_offset_min: 0
   ```
2. `tests/test_accounts.py`: bump the account count.
3. The campaign: `accounts: allow [rotation_yt]` and a `title:` on every description record (the hook line);
   the song credit goes in the description, the first comment is appended to it (Shorts have no first-comment API).
4. Workflows that build publishers (`publish.yml`, `topup.yml`, `metrics.yml`) need the env lines
   `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN_1` … `YT_REFRESH_TOKEN_16` (and `YT_DAILY_UPLOADS` to change
   the cap). Like the `IG_TOKEN_n` slots, they are named once and never edited per account.
5. Update [[accounts]] and [[log]].

## 4. First posts and checks
- `publish.yml` with `account=rotation_yt`, `dry_run=true` shows what is held. `now=true` sends the earliest.
- The outbox item records `video_id` and `processing` (`processed`, or `uploaded` while YouTube still works).
  `status: failed` with `rejected`/`duplicate` means YouTube refused the file: look at it in Studio.
- Log events: `youtube_post_published`, `quota_exhausted` (the ledger said no), `youtube_quota_refused` (YouTube
  said no: `quotaExceeded` or `uploadLimitExceeded`; the post waits), `youtube_reauth_needed` (names the secret to
  refill with `yt_connect.py`; the channel is skipped until then).
- Private uploads on a public setting mean the audit has not cleared. Nothing in the repo fixes that.
- Figures: `videos.list part=statistics` → views, reactions (likes), comments, into the same `PostMetrics` the
  Instagram posts use. No watch time yet.
