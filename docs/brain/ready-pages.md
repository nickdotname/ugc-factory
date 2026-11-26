# Ready pages

Back to [[README]] · see [[accounts]], [[add-account]], [[backlog]]. Pages that are **built, rendered, sampled and
paused**, waiting only for their Instagram account. The every-4-hours growth job keeps at least 6 here. When Dylan
creates the account (one handle, switched to Creator), the page is wired by [[add-account]] and moved off this list.

Each entry: campaign, renderer, what it is, the sample that was looked at, and three handle ideas (Dylan picks one;
any that is taken, try the next).

| page | campaign / style | renderer | what it is | sample | handle ideas |
|---|---|---|---|---|---|
| Circle Atlas | `circle_atlas` / `reveal` | `studio/reveal_video.py` (outlines: `studio/reveal/shapes.json`) | a country's outline drawn by spinning circles (its Fourier series): 2 circles, then more on every few beats up to 150, the circle count and the computed error on screen, then the name. 37 countries (Natural Earth 1:110m, public domain; disputed-border countries left out), easy ones 3x as likely; palettes chalk / blueprint / paper / night | 2026-11-26: Japan on Talk, Italy, Chile, Kenya, USA sheets | @circle.atlas · @drawn.by.circles · @epicycle.maps |
| Stare Lab | `stare_lab` / `stare` | `studio/stare_video.py` (pictures: `studio/stare/scenes.py`) | illusions that happen in your own eyes once you hold still: a landscape in opposite colours that turns grey on a beat and looks coloured for a few seconds (afterimage); a turning spiral, then a still picture that seems to swell or shrink (motion aftereffect); the lilac chaser (12 soft discs, the gap stepping on every 16th note, the discs fade and a disc of the opposite colour runs round). Every picture drawn in code (7 seeded landscapes), countdown ring round the dot, the true line after ("the picture is black and white"). Six steadier songs (Passage, Prologue, Suspended, Silver and Gold, Epilogue, Myth of Sisyphus); cousin of the illusion pages (best median views) but a different effect, pictures and voice | 2026-11-26: tulips colour on Prologue (full render), sunset in all three kinds; all 7 scenes | @stare.lab · @stare.at.the.dot · @afterimage.lab |

## Wiring one (after Dylan creates it)
1. `accounts.yaml`: `<x>_ig` (the name already in the campaign's `accounts.names`), provider instagram, login facebook,
   `api_key_secret: IG_TOKEN`, `channel_id` from the tokens run log; `tests/test_accounts.py` count; `dash_data.py` HANDLES.
2. Campaign `config.yaml`: `paused: false`, `dry_run: false` (posts_per_day is already 1 for the first week).
3. `studio/nightly.yaml`: drop the target's `paused: true`.
4. Merge, then `studio.yml` (campaign=<c>), `render.yml`, `topup.yml`, one at a time.
