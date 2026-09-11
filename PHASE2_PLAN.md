# Phase 2 plan — fan-out to every connected Buffer account

Design only; nothing here is built yet. See `HANDOFF.md` for the original
brief and `PHASE1` (the multi-creative work, shipped) for the pattern this
follows — same shape of change, one more dimension.

Today: **one campaign = one channel.** `clubs`, `clubs_tt`, `clubs_yt` are
three campaigns because Buffer needs three channel bindings, even though
they're one brand posting one clip library. After this phase: **one campaign
= a content source**, and every campaign posts to every connected account.

---

## 1. The real accounts (confirmed, not guessed)

Two Buffer logins exist today. Checked directly: `.env`, GitHub secrets
(`gh secret list`), and a live Buffer API channel listing for the key that
was available locally.

| account | network | key | channel id | org id | source |
|---|---|---|---|---|---|
| nickdotname | instagram | `BUFFER_API_KEY` | `6a7d1f03b2d9d57743694aa7` | `6a1dc863e8cbb15ba8fdb4ab` | committed config (`campaigns/clubs/config.yaml`) |
| nickdotname | tiktok | `BUFFER_API_KEY` | `6a1dc9e4c687a22dd44c7e3d` | `6a1dc863e8cbb15ba8fdb4ab` | committed config (`campaigns/clubs_tt/config.yaml`) |
| nickdotname | youtube | `BUFFER_API_KEY` | `6a1dca06c687a22dd44c7f8a` | `6a1dc863e8cbb15ba8fdb4ab` | committed config (`campaigns/clubs_yt/config.yaml`) |
| knick.creates | instagram | `BUFFER_API_KEY_2` | `6a863bb4ccaf649a67dc5e49` | `6a86335e7667b936ca8e2ca1` | live Buffer API (2026-09-11) |
| knick.creates | tiktok | `BUFFER_API_KEY_2` | `6a863b68ccaf649a67dc590d` | `6a86335e7667b936ca8e2ca1` | live Buffer API (2026-09-11) |
| knick.creates | youtube | `BUFFER_API_KEY_2` | `6a8639cbccaf649a67dc364b` | `6a86335e7667b936ca8e2ca1` | live Buffer API (2026-09-11) |

**"nickdotname" is not a fourth brand — it's the real name behind what this
repo calls `clubs`.** `clubs`/`clubs_tt`/`clubs_yt` were always posting to
nickdotname's own three channels; "clubs" is this project's internal
codename, not a separate Buffer identity. So the practical effect of fan-out
isn't "clubs gains three new targets out of nine" — it's much smaller:
**`clubs` content starts also going to knick.creates' three channels**, and
once revived, `knick_creates`-the-campaign's content starts going to
nickdotname's three channels too. Six real channels, two keys, confirmed.

`BUFFER_API_KEY_2` was confirmed by a live query, not assumed from secret
creation dates — the dates alone pointed the wrong way (would have suggested
`_2` was nickdotname's, when it's knick.creates').

---

## 2. A global, repo-level accounts registry

`accounts.yaml` at the repo root — not per-campaign, not in `src/`:

```yaml
accounts:
  - name: nickdotname_ig
    network: instagram
    organization_id: 6a1dc863e8cbb15ba8fdb4ab
    api_key_secret: BUFFER_API_KEY
    channel_id: 6a7d1f03b2d9d57743694aa7
  - name: nickdotname_tt
    network: tiktok
    organization_id: 6a1dc863e8cbb15ba8fdb4ab
    api_key_secret: BUFFER_API_KEY
    channel_id: 6a1dc9e4c687a22dd44c7e3d
  - name: nickdotname_yt
    network: youtube
    organization_id: 6a1dc863e8cbb15ba8fdb4ab
    api_key_secret: BUFFER_API_KEY
    channel_id: 6a1dca06c687a22dd44c7f8a

  - name: knick_creates_ig
    network: instagram
    organization_id: 6a86335e7667b936ca8e2ca1
    api_key_secret: BUFFER_API_KEY_2
    channel_id: 6a863bb4ccaf649a67dc5e49
  - name: knick_creates_tt
    network: tiktok
    organization_id: 6a86335e7667b936ca8e2ca1
    api_key_secret: BUFFER_API_KEY_2
    channel_id: 6a863b68ccaf649a67dc590d
  - name: knick_creates_yt
    network: youtube
    organization_id: 6a86335e7667b936ca8e2ca1
    api_key_secret: BUFFER_API_KEY_2
    channel_id: 6a8639cbccaf649a67dc364b
```

Account names are identity-first (`nickdotname_ig`), not campaign-first
(`clubs_ig`) — an account isn't owned by any one campaign once every campaign
can reach it, and a future account (a brand with no campaign yet, or a
campaign-less test channel) shouldn't need a campaign name to hang off of.

This reuses `BUFFER_KEY_SLOTS` (`BUFFER_API_KEY`, `_2` … `_8`) already in
`src/config.py` — built for exactly this, just never exercised past one slot.
Adding a seventh account under an existing key, or an eighth under a brand
new one, is a new block here plus (if it's a new key) `gh secret set
BUFFER_API_KEY_3` — never a workflow or code change.

### Adding an account from the dashboard (new requirement)

Asked for explicitly: the ability to add more Buffer accounts "for the
future" without hand-editing YAML. Mirrors the dashboard's existing
"add a campaign" flow (`src/campaigns.py::create_campaign`, `src/web.py`):
give it a key-slot name and a channel, it calls Buffer to discover the
channel's id/org/network (the same call `ugc setup` already makes per
campaign) and writes the `accounts.yaml` block. The key itself is still a
human step — `gh secret set BUFFER_API_KEY_N` — for the same reason
`BUFFER_KEY_SLOTS` is fixed rather than discovered: GitHub will not let a
workflow enumerate the secrets context, so a dynamic key list is a dead end
regardless of what the dashboard does.

Not building this yet — noted so the accounts.yaml *shape* doesn't have to
change when it is.

---

## 3. Per-campaign opt-out, defaulting to everything

Confirmed: every campaign should reach every account, including `clubs`
reaching knick.creates' channels and vice versa. No opt-out needed today —
but reserved as an escape hatch, so opting one campaign out later is a
one-line config change, not a refactor:

```python
class AccountFilter(StrictModel):
    mode: Literal["allow", "block"] = "block"
    names: tuple[str, ...] = ()

class CampaignConfig(StrictModel):
    ...
    accounts: AccountFilter = AccountFilter()   # block nothing = every account
```

No UI for this filter. Config-file only.

---

## 4. Fan-out lives in the queue, not in render

```python
class AccountPost(Model):
    account: str            # name from accounts.yaml
    network: Service
    status: QueueStatus
    buffer_post_id: str | None = None
    attempts: int = 0
    last_error: str | None = None

class QueueItem(Model):
    ...                      # video_url, caption, creative — rendered once, shared
    posts: list[AccountPost] # one per resolved account — 6 today, for every campaign
```

Render still renders one video per slot, exactly as Phase 1 left it. Topup,
instead of pushing one item to one channel, expands each ready item across
every account the campaign resolves to and tracks each account's
push/publish state independently — a rejected post on one account has no
bearing on the other five.

`BufferPublisher` is keyed by API key today (one instance per campaign run).
With two real keys now in play, topup needs one publisher instance *per
distinct key*, not per account — three accounts sharing `BUFFER_API_KEY`
share one publisher and its request-count tally; that tally is also what
`_report_quota` sums across campaigns sharing a key, so this has to stay
consistent with the existing quota math, not bypass it.

---

## 5. Campaign collapse

`clubs`, `clubs_tt`, `clubs_yt` collapse into one `clubs` campaign whose
resolved accounts are exactly `[nickdotname_ig, nickdotname_tt,
nickdotname_yt]` — plus, once fan-out is live, knick.creates' three as well.

`posts.json`, `metrics.json`, `quota.json` from the three folders merge into
the surviving `clubs` folder. Every historical post record gets backfilled
with which account/network it actually went to — `clubs` → `nickdotname_ig`,
`clubs_tt` → `nickdotname_tt`, `clubs_yt` → `nickdotname_yt`, a mechanical
1:1 mapping since each old campaign only ever posted to one channel. That
backfill is the one irreversible step: its own commit, checked before
anything is deleted, never bundled with a code change.

---

## 6. Keying

Attribution, `distribution_lost`, `schedule_gap`, the digest — everything
downstream keys off **(campaign, creative, account, network)** instead of
just campaign, and every alert evaluates per account. Same shape of change
Phase 1 already made for creatives (see `_load_creative_resources`,
`select_batch_multi`), one dimension deeper.

---

## Open questions to resolve before building (not blocking the plan)

- Does the queue-depth/rate cap (`max_buffer_queue`, `posts_per_day`) live on
  the account, or stay campaign-level and get divided across accounts? Phase
  1's per-creative weighting is the template if it's the latter.
- Confirmed above: one `BufferPublisher` per distinct API key, shared across
  every account (and campaign) using that key — not one per account.
- Whether `first_comment`, `notify_subscribers`, `post_type`,
  `title_strategy` (currently per-campaign `BufferConfig` fields, one per
  network) move onto the account instead, since they're properties of the
  channel, not the content source. Likely yes — needs a pass through
  `BufferConfig` to see what's actually campaign-shaped versus
  channel-shaped.
