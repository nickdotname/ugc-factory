# Close Quarters engine — the brain

An Obsidian vault (open `docs/brain/` as a vault, or just read it on GitHub). Every note links to the others with
`[[name]]`. Start with the one you need:

- [[pipeline]]: the daily clock: what runs when, what each job reads and writes, where the state lives
- [[accounts]]: every account, its campaign, renderer, schedule and how it is connected
- [[styles]]: every video style (renderer) and the knobs it offers
- [[songs]]: the 15 EDUCATION songs and how a song is prepared
- [[footage]]: the footage libraries: public domain, Rocket League, our own clips
- [[learning]]: how the posts' numbers steer the next night's videos
- [[dashboard]]: dashboard.closequarters.vip
- [[traps]]: what broke, why, and the fix: read before touching Meta accounts or the queue
- [[ready-pages]]: pages built and paused, waiting for their Instagram account (with handle ideas)
- [[backlog]]: ideas and half-built things, with enough detail to pick up
- [[log]]: dated changes
- `reviews/`: dated whole-network reviews; start with `reviews/2026-11-26/README.md` (every account's verdict and the ranked plan)

Playbooks (step by step):
- [[add-account]]: a new Instagram account, from signup to its first post
- [[add-song]]: a new song (with or without vocals)
- [[new-format]]: a new video style
- [[health-check]]: is everything posting? what to look at, in order

## The system in one paragraph

A Cloudflare Worker (`ugc-publish-timer`) starts `publish.yml` every 5 minutes. `publish.yml` sends every
Instagram post whose slot has come (posts wait in `outbox/`), posts a first comment crediting the song, refreshes
the dashboard, and at fixed times starts the daily jobs: **studio** (01:45 New York: render new videos into each
song's clip library), **render** (03:30: turn library videos into queued posts for the next day), **topup**
(04:00, 10:00, 16:00: book queued posts into free slots on each account), plus carousels and fact reels.
`studio/learn.py` scores every published post, and **studio** uses those scores to choose the next night's songs,
sections and looks.

## People

- **Dylan Cantor**: in the band; built and runs this. Owns the Facebook account that manages every Page.
- **Nick**: in the band; runs @the.loose.change and @nyc.daily.aesthetic.
Both can open the dashboard. Personal contact details are deliberately not in this repo.
