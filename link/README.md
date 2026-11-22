# Bio links

`worker.js` runs on Cloudflare as **cq-listen** (Dylan's account), with a KV namespace
`cq-listen-clicks` bound as `CLICKS`. Each Instagram account's bio links to its own path:

| account | bio link |
|---|---|
| close__quarters | https://cq-listen.cantor-dylan.workers.dev/cq |
| dylancantor23 | https://cq-listen.cantor-dylan.workers.dev/dc |
| psychedelic.station | https://cq-listen.cantor-dylan.workers.dev/psy |
| nostalgia.hub.vhs | https://cq-listen.cantor-dylan.workers.dev/nostalgia |

A tap is counted (robots and link previews are not) and the visitor is sent to the band site,
closequarters.vip, with `?ref=<account>`. To send people somewhere else, set a `TARGET` variable on
the worker. `/stats` returns the counts per day; `studio/learn.py` copies them into
`studio/clicks.json` and the "Bio link taps" table in `studio/LEARNED.md` every night.

To change the code: edit `worker.js` here, then paste it into the worker's editor in the
Cloudflare dashboard and press Deploy.
