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
5. **Token expiry:** studio's last step warns before an Instagram token runs out; `scripts/ig_token_check.py`.
6. **Footage / libraries:** `footage.yml` weekly; rocket, retro, lofi libraries have their own indexes ([[footage]]).

Fixes are PRs; the operator merges. Re-runs of workflows are fine; cancelling runs or deleting state needs the
operator's go.
