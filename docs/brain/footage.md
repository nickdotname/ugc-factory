# Footage libraries

Back to [[README]].

## Public domain: `studio/footage.py` → release `footage-library`

Index: `studio/footage/index.json` (every clip: asset, theme, source, licence, page, start, motion).
Queries per theme: `studio/footage/queries.json`. Weekly `footage.yml` (and on any push changing those files):
`purge` (drops clips the block list or the queries no longer allow; never our own), then `fetch --max N`.
Themes with the fewest clips are fetched first.

| theme | sources | used by |
|---|---|---|
| water, nature, city, space, archive | Wikimedia Commons (PD/CC0 only), Prelinger Archives, NASA | glitch |
| silent | Internet Archive, films dated 1890–1930 (US public domain by date); restorations, colourised copies, trailers and documentaries skipped | vintage |
| nyc | Commons, Prelinger, silent-era New York films, **and our own clips** | nyc |
| nyc_now | New York as it looks today: **Pexels** (Pexels licence: free to use and adapt, no credit; needs the free `PEXELS_API_KEY` secret) | scene (nyc world) |

`nyc_now` pieces are cut differently (`NOW` in footage.py): upright 720×1280, put through our film grade (the
library holds our version, not a copy of the stock file), clips of 5–12 s kept whole, titles about people skipped
(places only). glitch.archive never uses them: it is public-domain film only.

`BLOCK` (in footage.py) rules a film out on its title/subject/description: sex, alcohol/tobacco ads, war and
weapons, racist caricature terms, crime, medical, adverts. Metadata can't catch everything, especially in 1920s
cartoons: watch the first vintage posts and add a frame check if anything slips (see [[backlog]]).

Each film gives up to 3 silent 10 s pieces (≤960 px tall, motion-checked).

## Our own clips

- **NYC** (PR #94): add Google Drive links (shared "anyone with the link"), one per line, to
  `studio/footage/inbox/nyc.txt` and commit; `footage-inbox.yml` cuts each into 10 s pieces under theme `nyc`.
  `python studio/footage.py own THEME LINK...` does the same by hand.
- **Rocket League**: `studio/rocket_lib.py` → release `rocket-library`, index `studio/rocket/index.json`, with
  each clip's "moments" (goal explosions, big hits) found from sound and picture. Clips were added from a shared
  Drive folder by a one-off `rocket-inbox` workflow.
- **Band footage** (lofi style): `studio/lofi/index.json`, from the band's own dance videos. Band only on
  @close__quarters and @dylancantor23.

## Made on Kaggle

**Plates** (`studio/plates_gen.py` → release `plates-library`, index `studio/plates/index.json`): still pictures
of places made by SDXL (Open RAIL++-M, commercial use allowed) on Kaggle's free GPUs, `plates.yml` twice a week.
Prompts in `studio/plates/prompts.json`: a scene × a look per theme. Places only: no people, text, logos or real
landmarks. Themes: `school`, `psych`, `nyc` (the band's three worlds, studio/scene_video.py), `liminal`
(nostalgia.hub.vhs), `psy` (psychedelic.station).

retro.vibes.arcade's PS2-style clips: `studio/retro_gen.py` runs an open video model (Wan, Apache 2.0) on Kaggle's
free GPUs, orchestrated by `retro.yml` twice a week.
