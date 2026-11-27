# Bio links

`worker.js` runs on Cloudflare as **cq-listen** (Dylan's account), with a KV namespace
`cq-listen-clicks` bound as `CLICKS`. Every Instagram account's bio links to its own path on
`https://cq-listen.cantor-dylan.workers.dev/`; all of them send the visitor to the same place
(`TARGET`, a plain-text variable on the worker; the band site until the song-first listen page exists)
with `?ref=<path>`, and each path counts its own taps. Robots and link previews are not counted.

| path | account | | path | account |
|---|---|---|---|---|
| `/cq` | close__quarters | | `/petri` | digital.petri.dish |
| `/dc` | dylancantor23 | | `/illusions` | rotation.illusions |
| `/psy` | psychedelic.station | | `/races` | algorithm.races |
| `/nostalgia` | nostalgia.hub.vhs | | `/8bit` | 8bit.tests |
| `/math` | math.explainers | | `/notes` | moth.ate.my.notes |
| `/glitch` | glitch.archive.exe | | `/toon` | rubberhose.radio |
| `/ascii` | ascii.terminal.dreams | | `/zoom` | zoom.into.art |
| `/physics` | physics.bounce.lab | | `/date` | situationship.notes |
| `/earth` | earth.data.live | | `/lowpoly` | what.if.town |
| `/retro` | retro.vibes.arcade | | `/college` | dining.hall.philosopher |
| `/rocket` | rocket.league.lit | | `/eyetrick` | eye.trick.lab |
| `/loose` | the.loose.change | | `/fourier` | fourier.reveal |
| `/vintage` | vintage.media.archive | | `/her` | crying.in.trader.joes |
| `/nyc` | nyc.daily.aesthetic | | `/him` | grip.tape.thoughts |
| `/tinycode` | tiny.code.loops | | `/cinema` | ascii.cinema.tty |

The same table lives in `scripts/dash_data.py` (`LINKS`) and `studio/learn.py` (`LINK_NAMES`); a new account
gets a line in all three and its path pasted into the account's bio (Edit profile → Links).

`/stats` returns the last 7 days (`?days=14` at most): one object per day with taps per path (an empty object
is a day nobody tapped), `week` with the window's total per path, and `last` with the time of the latest tap
per path and whether it came from the Instagram app or a browser. `studio/learn.py` copies it into
`studio/clicks.json` and the "Bio link taps" table in `studio/LEARNED.md` every night; `scripts/dash_data.py`
puts the 7-day taps on each account's card on the dashboard. No secret is needed to read it.

**Is it counting?** Open the account's link from a phone, then `/stats`: that path's `last.at` is the time
you tapped. If it is not, the worker is not reaching KV (Settings → Bindings must show `CLICKS` →
`cq-listen-clicks`). `studio/clicks.json` held one day (2026-11-22, the day the links went into the bios)
for a week; the nightly fetch worked each night and the worker simply had no newer tap to report, which
`last` now shows directly.

To change the code: edit `worker.js` here, then either paste it into the worker's editor in the Cloudflare
dashboard and press Deploy, or `cd link && npx wrangler deploy` after putting the KV namespace id into
`wrangler.toml` (`npx wrangler kv namespace list` prints it). Counts are kept in KV for 120 days.
