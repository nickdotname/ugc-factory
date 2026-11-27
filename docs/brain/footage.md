# Footage libraries

Back to [[README]].

## Public domain: `studio/footage.py` → release `footage-library`

Index: `studio/footage/index.json` (every clip: asset, theme, source, licence, page, start, motion).
Queries per theme: `studio/footage/queries.json`. Weekly `footage.yml` (and on any push changing those files):
`purge` (drops clips the block list or the queries no longer allow; never our own), then `fetch --max N`.
Themes with the fewest clips are fetched first.

| theme | sources | used by |
|---|---|---|
| water, nature, city, archive | Wikimedia Commons (PD/CC0 only), Prelinger Archives (PD only), NASA; `svs>` queries: NASA SVS | glitch, cinema, cutout bgs |
| space | NASA Image and Video Library, NASA Scientific Visualization Studio (SVS), Commons | glitch, cinema, cutout bgs |
| silent | Internet Archive and **Library of Congress** films dated 1890–1930 (US public domain by date); `commons>incategory:Videos_of_films_from_YYYY` queries; restorations, colourised copies, trailers and documentaries skipped | vintage, cinema |
| nyc | Commons, Prelinger, silent-era New York films (IA and LoC), **and our own clips** | nyc, cinema, cutout bgs |
| nyc_now | New York as it looks today: **Pexels** (Pexels licence: free to use and adapt, no credit; `PEXELS_API_KEY`). Pieces cut upright 720x1280 in our own grade (`NOW`, `GRADE`), titles about people or logos skipped (`PEOPLE`, `LOGO`) | nyc |

**nyc must be New York and not news** (`fits`, 2026-11-24): Commons' "Times Square" / "Grand Central" / "Empire State Building" queries had brought in a 2026 political protest, a Florida rail opening, steam engines and Russian films of 1909-1913. A non-own nyc clip now needs a New York place in its title (`NYC_WORDS`) and none of `NYC_NOT` (protest, parade, fair, football ...); `pull` never serves one that fails, and `purge` removes them.

A query goes to every source its theme lists (`BY_THEME`), unless it starts with `source>` (`loc>Edison`,
`svs>ocean currents`, `commons>incategory:...`, `silent>collection:silent_films AND year:[1895 TO 1899]`), when only
that source gets it. Words in an Internet Archive query must all appear, in any field; a query with `:` is IA syntax.
Every clip records `source`, `key`, `title`, `licence`, `page` (and `year` for pre-1931 films).

**Why silent and Prelinger found so little (fixed 2026-11-24):** (1) `fetch --max 40` was used up by the first
two or three queries (a query gave every film it found, 3 pieces each), so Keaton, Chaplin, Lloyd and Lumière
were never asked; now every query gets one film per turn before any gets a second (`PER_QUERY`). (2) Prelinger
searched only titles/subjects and needed both words there ("skyline", "subway train" are in shot lists, not titles);
now all fields, with `licenseurl:*publicdomain*` in the search itself, 60 hits instead of 6. (3) BLOCK matched
inside harmless words (s*kill*, be*gun*, Es*sex*, pat*riot*ic, *smok*estack, *Indian*a): `SAFE` blanks those first.
For silent films and LoC the long description only has to pass `HARD` (caricature, nudity), so a comedy whose
summary mentions a policeman is no longer lost; titles and subjects still pass the whole BLOCK. (4) The smallest
mp4 was picked, so old films came as 320x240 copies; now the tallest h.264 copy up to 1080 lines, and a copy under
360 lines (`MIN_H`) is skipped.

Each film gives up to 3 silent 10 s pieces (≤960 px tall, motion-checked); black bars (a 4:3 film pillarboxed in a
16:9 scan) are cropped off first (`bars`), and a piece that is more than a third intertitles / black leader is dropped
(`looks`).

`BLOCK` (in footage.py) rules a film out on its title/subject/description: sex, alcohol/tobacco ads, war and
weapons, racist caricature terms, crime, medical, adverts. Metadata can't catch everything, especially in 1920s
cartoons: watch the first vintage posts and add a frame check if anything slips (see [[backlog]]).


The silent theme is small (Nov 2026: 7 films, 21 usable clips; 6 of them are 320x240 copies of Nosferatu), so vintage posts repeat films often. The Veil Dance (Schleiertanz, 1906) is blocked: its dancers wear body stockings that read as nude at phone size. More silent films (Keaton, Chaplin, Lloyd, Lumière and city films are in `queries.json` but nothing from them is in the library yet) would help vintage more than any look change.

`footage.TRADEMARK` keeps live characters out of the toons pull (Mickey, Betty Boop, Felix, ... and, since 2026-11-27, Steamboat
Willie and Barnacle Bill by title); a toons entry dated after 1930 is out whatever its title (Aristocrats of Fashion is 1940).

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

retro.vibes.arcade's PS2-style clips: `studio/retro_gen.py` runs an open video model (Wan, Apache 2.0) on Kaggle's
free GPUs, orchestrated by `retro.yml` twice a week.

## More sources (researched 2026-11-24, not built yet)

Ranked; see the more-sources PR for the reasoning. Built: Library of Congress (`loc`), NASA SVS (`svs`), Commons
year categories, and the IA/Prelinger fixes above. Pexels for modern New York is on the `cq-worlds` branch
(`PEXELS_API_KEY` secret already exists).

- **Pixabay video API** (Pixabay Content Licence, no credit): a second modern-places source next to Pexels;
  needs a free key as secret `PIXABAY_API_KEY`. Same "places, not people" filter.
- **Europeana** (filter `reusability=open`, `type=VIDEO`; free key `EUROPEANA_API_KEY`): European newsreels and
  early film; many records point at a player, not a file, so the yield is lower than it looks.
- **National Archives (NARA) catalog API v2**: US government films, all PD (Universal Newsreels too), but a key
  is needed (`NARA_API_KEY`, by email) and the content is heavy on war and news; low fit.
- **Stills** (for carousels / still-based styles, `photos.py` today reads Commons only): Smithsonian Open Access
  (CC0, api.data.gov key), the Met and Art Institute of Chicago open-access APIs (CC0, no key), and on Hugging Face
  `madebyollin/soa-full` (Smithsonian CC0) and Spawning's PD12M (12 M public-domain/CC0 images).
- Rejected: IA `classic_tv` and `feature_films` after 1930 (rights by lapse are unproven), IA `stock_footage`
  (uploader-chosen licences), ESA (CC BY-SA, needs credit), Open Images / Polygoon (mostly CC BY-SA), any
  YouTube-sourced dataset (OpenVid etc.).
