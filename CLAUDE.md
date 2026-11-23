# ugc-factory — start here

This repo is a fully automated short-form video engine for **Close Quarters**, the band behind the album
**EDUCATION** (released 2026-11-13, 15 tracks). Every night it makes new vertical videos set to the album's
songs, queues them, and posts them, about 50 a day, to a network of Instagram accounts (the band's own and
faceless niche pages). Each post's numbers are fed back so the next night's videos lean toward what got watched.

It started as the Clubs app's UGC pipeline. `README.md`, `SPEC.md`, `CONTEXT.md`, `HANDOFF.md` and
`PHASE2_PLAN.md` describe that era (Buffer, `src/`, the queue model) and are still accurate for the posting core.
Everything about the Close Quarters engine (accounts, renderers, the nightly studio, the dashboard) is in
**`docs/brain/`**, an Obsidian-style vault. Open `docs/brain/README.md` first.

## Rules that are not negotiable

- **The operator merges PRs.** Work on a branch, open a PR, give the link. Never push to `main` directly,
  never force-push, never create GitHub releases by hand (the jobs do), never bulk-delete queue or history files.
- **Secrets stay out of chat and out of the repo.** The operator pastes tokens into GitHub secrets
  (`IG_TOKEN`, `BUFFER_API_KEY`, ...). Never print, log, or commit a token. The repo is **public**: no personal
  emails or phone numbers anywhere in it (the dashboard's allow-list lives only in Cloudflare Access).
- **Close Quarters and Clubs stay separate.** The `clubs` campaign is Clubs' own and is blocked from every Close
  Quarters account; the dashboard filters it out (`scripts/dash_data.py`, `NOT_CQ`).
- **Band photos and footage only on @close__quarters and @dylancantor23.** Niche accounts never show the band.
- **No engagement bait** (no "comment X", "tag a friend", like-asks). First comments credit the song only.
- **No copyrighted film/TV edits, no ripped YouTube, no game footage we didn't record.** Footage is public
  domain (pre-1931 films, NASA, Prelinger, CC0 Commons), our own (Rocket League clips, Nick's NYC clips), or, for
  modern New York only, free-licence stock (Pexels licence; places, not people) stored in our own crop and grade.
  Pictures made by our own models (SDXL plates on Kaggle) are ours.
- **Collab invites are off; no band carousels on niche accounts.**
- **Meta/Instagram account work:** never type passwords or payment details; leave verification codes and
  logins to the operator; never pick the wrong account in an OAuth popup. Don't navigate the Facebook tab while an
  Instagram/Facebook popup is mid-flow: it kills the callback (see `docs/brain/traps.md`).

## Where to look

| question | file |
|---|---|
| what runs when, and where the state lives | `docs/brain/pipeline.md` |
| every account, its campaign, renderer and schedule | `docs/brain/accounts.md` |
| what each video style is and its knobs | `docs/brain/styles.md` |
| the 15 songs and how a song is prepared | `docs/brain/songs.md` |
| footage libraries (public domain, Rocket League, own clips) | `docs/brain/footage.md` |
| how videos learn from posts | `docs/brain/learning.md` |
| dashboard.closequarters.vip | `docs/brain/dashboard.md` |
| things that broke and how they were fixed | `docs/brain/traps.md` |
| step-by-step jobs (new account, new song, new format, health check) | `docs/brain/playbooks/` |
| ideas not built yet | `docs/brain/backlog.md` |
| dated log of changes | `docs/brain/log.md` |

## Working here

- Python 3.11+. Posting core: `pip install -r requirements.txt`; studio: `pip install -r studio/requirements.txt`.
- Tests: `python -W ignore -m pytest -q -p no:warnings --ignore=tests/test_acceptance.py` (the full run is slow;
  `-k` a subset). `tests/test_accounts.py` counts the accounts in `accounts.yaml`: update it when adding one.
- Any renderer can draw a contact sheet instead of a video:
  `CQ_WINDOW=23,38 python studio/<style>_video.py studio/songs/talk 5 /tmp/sheet.png --frames 20,140,250`
  and `CQ_KNOBS='{"tint":"sepia"}'` forces knobs. Look at frames before any full render.
- Cloud sessions can't reach archive.org / Wikimedia / most sites; GitHub Actions can. Pull what you need from the
  repo's releases with `gh` (e.g. `python studio/footage.py pull city`).
- Keep `docs/brain/` current: when you add an account, style, song or job, update the matching note and add a
  line to `log.md`.
