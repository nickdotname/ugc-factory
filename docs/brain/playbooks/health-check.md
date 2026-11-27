# Playbook: health check: is everything posting?

Back to [[README]] · see [[pipeline]], [[traps]]. In order, stop at the first problem.

1. **Publisher alive?** `gh run list --workflow publish.yml --limit 5`: a run every 5 minutes, green. Silent ⇒
   check the Cloudflare Worker `ugc-publish-timer` (cron `*/5 * * * *`).
2. **Last night's chain:** `studio.yml` (~06:45 UTC) → `render.yml` (~08:30) → `topup.yml` (09:00) all green?
   A red studio usually means one renderer crashed; the run log says which (`retrying ... on its own`).
3. **Tomorrow full?** Count queued posts per account in `cqdash/data.json` (`posts` with status
   queued/scheduled, `due` tomorrow in New York) against each campaign's `posts_per_day`. Short ⇒ is that
   creative's library exhausted (render log: `creative_exhausted` / `libraries_exhausted`)? Then studio needs to make
   more for that campaign: `studio.yml` with `campaign=<c> count=N`, then render, then topup.
4. **Posts actually went out?** Dashboard → Posted, or `outbox/igo-*.json` stuck in PUBLISHING. A failure alert
   in the publisher log usually means a dead token (refresh `IG_TOKEN`) or a refused container (video spec).
5. **Numbers flowing?** A red `metrics` run with `insights_denied`, or a red "insights denied" line on an account card,
   means that account's token lacks the insights permission: run `ig-check` (prints each token's permissions and each
   Page's tasks) and re-mint the token with `instagram_business_manage_insights` ([[traps]]).
6. **The band account's grid:** posts must be normal reels (`trial_reels: false`); cutouts must be posting (`style_quota`
   log events `style_quota_filled` / `style_quota_short` in the render run).
7. **Token expiry:** studio's last step warns before an Instagram token runs out; `scripts/ig_token_check.py`.
8. **Footage / libraries:** `footage.yml` weekly; rocket, retro, lofi libraries have their own indexes ([[footage]]).

9. **Bio-link taps and followers:** the dashboard's account cards show 7-day taps and the follower delta; a tap count
   stuck at zero for days means the link worker or its KV binding, not the audience (`link/README.md`).

Fixes are PRs; the operator merges. Re-runs of workflows are fine; cancelling runs or deleting state needs the
operator's go.
