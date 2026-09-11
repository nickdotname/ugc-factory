# Handoff: multi-creative, fan-out, AI captions

Read `CONTEXT.md`, `SPEC.md` and `tests/test_acceptance.py` before touching anything.
**Plan first, write no code until the plan is approved.** Deliver in the three phases
below, each merged and green before the next starts.

---

## The three changes

### Phase 1 — Multiple creatives per campaign

A campaign contains N **creatives**. A creative is a self-contained clip pool:
its own hooks, bodies, and music, with its own licences.

- On each slot: pick a creative (weighted random, uniform by default, optional
  `weight` per creative in config), then run the existing hook/body/music
  randomizer *inside* that creative. Clips never mix across creatives.
- Existing `performance_weight` logic applies within a creative.
- YouTube's two-bodies-per-video rule still holds, drawn from the same creative.
- `license_missing` checks per creative.
- Runway/dedupe reporting per creative **and** a count of distinct visuals
  (hook × body), not just combinations. See CONTEXT §3 for why.
- The current clips become the first creative of `clubs`. Nothing about
  existing output should change in Phase 1.

### Phase 2 — Fan-out: every campaign posts to every connected account

This inverts the core model. Today one campaign = one channel. After this:

- **Campaign** = a content source: brand, creatives, caption voice, product link.
- **Accounts** = a global list of Buffer connections (repo-level config, not per
  campaign). Each connection names the *secret* holding its token; channels are
  discovered from Buffer. Currently: nickdotname, knick.creates, plus the
  existing Clubs channels. More will be added, and adding one should be config only.
- When a slot fires, render **once** and schedule the **same video** to every
  connected channel.
- `clubs`, `clubs_tt`, `clubs_yt` collapse into one `clubs` campaign. Migrate
  `posts.json` history without losing which network/account each post went to.
- Metrics and posts keyed by **(campaign, creative, account, network)** so every
  analysis in CONTEXT §3–§5 stays possible.
- Per-account rate and depth cap (see Assumptions). Keep `max_backlog_days = 1`
  semantics. See CONTEXT §7 for why that one bites.
- Alerts (`distribution_lost`, `schedule_gap`, `queue_*`) evaluate per account.
- `src/` stays campaign- and account-agnostic. No slugs or handles in code.

### Phase 3 — AI captions (Anthropic API)

- Model: `claude-haiku-4-5-20251001`. Call it from a new boundary module only,
  per the acceptance tests.
- Inputs per generation:
  - campaign keywords and caption voice (campaign config)
  - search-volume terms from the existing `demand_unmet` data source
  - top-performing past captions from `posts.json` (by views and engagement,
    last N days, per network)
  - the creative/hook being posted, so the caption matches the video
- Output formatted per network (length limits, hashtag conventions for IG, TT, YT).
- **Every caption includes a follow ask.** Zero follows across 719 posts is the
  worst signal these accounts send (CONTEXT §2).
- `caption_per_account` config toggle, default `false`. When true, generate a
  distinct caption per account on the same network.
- Fallback to the existing caption bank on any API failure; posting never
  blocks on the model.
- Log prompt, response, and which winners and terms were used, per post, so
  caption performance can be traced later.
- API key goes in **both** `.env` and GitHub secrets (CONTEXT §7).
- `demand_unmet` should keep working against AI-written captions.

---

## Constraints (from CONTEXT, do not undo)

- Acceptance tests are load-bearing. `requests` and the Anthropic SDK stay in
  boundary modules, `datetime.now()` only in `ports.py`/`logging.py`, and no
  campaign or account names in `src/`.
- Config models use `extra="forbid"`. Every new field means a dashboard restart;
  make sure `restart_needed` still fingerprints the new config files.
- `_knick_creates*` stays parked unless told otherwise.

---

## Assumptions — confirm or correct before Phase 2

1. Same rate on every account (currently 4/day), configurable per account.
2. Creative selection is uniform random unless weighted in config.
3. Accounts can span multiple Buffer organisations/tokens.
4. Every campaign goes to every account, with no per-account opt-out for v1.
5. Captions are shared across accounts by default (toggle above).
