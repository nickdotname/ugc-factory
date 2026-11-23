# Playbook: add an Instagram account

Back to [[README]] · see [[accounts]], [[traps]]. One format per account: a new idea gets a new account.

## 1. The account (operator, ~10 min, partly on a phone)
1. Create the Instagram account (operator logs in; codes go to the operator).
2. Profile picture, name, bio linking to the band. Never band photos on a niche account.
3. Settings → **Switch to professional → Creator** (category: Digital creator).

## 2. Its Facebook Page (on the computer, Dylan's Facebook)
1. facebook.com/pages/create → name, category "Digital creator" → Create; skip WhatsApp and friend invites.
2. Switch into the Page → Settings → **Linked accounts → Instagram → Connect**.
3. The popup logs into Instagram: make sure it's the **right** account (log it into instagram.com first, or
   "Use another profile"). Confirm, then "Add" to the business portfolio. **Don't touch the Page tab until the popup
   closes.**
4. Check Settings → Linked accounts shows the account.

## 3. The app and the token
1. The app is opted in to all current and future Pages and Instagram accounts, so normally nothing to grant.
   To check: Graph API Explorer → `me/accounts?fields=name,instagram_business_account{username}&limit=50` → Submit.
   The new account must appear with an `instagram_business_account` id.
2. If it doesn't: Generate Access Token → Edit settings → tick the Page and the Instagram account.
3. Refresh `IG_TOKEN` if anything was granted (operator: Copy token → Access Token Debugger → Extend → GitHub
   secret `IG_TOKEN`).

## 4. The repo (PR)
1. `accounts.yaml`: a new `provider: instagram` entry, `channel_id` = the Instagram user id, `api_key_secret: IG_TOKEN`.
2. `tests/test_accounts.py`: bump the account count.
3. `campaigns/<name>/config.yaml` (copy a sibling, e.g. glitch_archive): slug, creatives (one per song, release
   `assets-<campaign>-<song>`), `accounts: allow [<acct>]`, posting window, `slot_offset_min` not used by another
   campaign, first comments, `captions.txt`. Start `paused: true, dry_run: true` until a sample is approved.
4. A renderer (`studio/<style>_video.py`), `VISUAL[...]` in `studio/nightly.py`, a target in `studio/nightly.yaml`
   (see [[new-format]]).
5. `scripts/dash_data.py`: `HANDLES` and `WHAT`.
6. Update [[accounts]], [[styles]], [[log]].

## 5. First posts
After merge: `studio.yml` with `campaign=<name> count=6`, then `render.yml`, then `topup.yml`. Posts go out in the
account's window the next day. Check the dashboard ([[health-check]]).
