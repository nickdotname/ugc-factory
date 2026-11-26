# Ready pages

Back to [[README]] · see [[accounts]], [[add-account]], [[backlog]]. Pages that are **built, rendered, sampled and
paused**, waiting only for their Instagram account. The every-4-hours growth job keeps at least 6 here. When Dylan
creates the account (one handle, switched to Creator), the page is wired by [[add-account]] and moved off this list.

Each entry: campaign, renderer, what it is, the sample that was looked at, and three handle ideas (Dylan picks one;
any that is taken, try the next).

| page | campaign / style | renderer | what it is | sample | handle ideas |
|---|---|---|---|---|---|
| Marbled by Math | `ink_marbling` / `ebru` | `studio/ebru_video.py` | paper marbling (ebru) done with the exact equations of mathematical marbling: drops of ink land on the beat and push each other into rings, then a comb, a wavy comb or a stir pulls them into a pattern (stone, gelgit, nonpareil, tulip hearts, stir, wave); six palettes, three baths; drop and stroke counter; the last line is true (no move changes a drop's area). Sub-niche of the fluid format (physics.bounce.lab's fluid videos: median 632 views, second only to illusions) but its own look, voice and songs (Talk, Full Ride, Fixation, Subway Maintenance, Recess, Won't Be the Same Again) | 2026-11-26: tulip on Full Ride (full render); sheets of all six patterns on Talk | @marbled.by.math · @ink.on.water.lab · @ebru.equations |
| Ruler Says No | `ruler_says_no` / `measure` | `studio/measure_video.py` | the classic size, straightness and brightness illusions (Muller-Lyer, Ebbinghaus, Ponzo, Jastrow, cafe wall, Hering, same grey) asked as a question ('which line is longer?'), then measured on the beat: the surroundings fade, the pieces slide together, a ruler shows the numbers read off the drawing ('the same length.'), then it all comes back ('measured. still looks wrong.'). Drawn in code, three palettes. Sub-niche of the illusion pages (best median views) but a different effect from rotation.illusions (motion) and eye.trick.lab (afterimages): a quiz with a proof. Songs: Hair of the Dog, Notta Problem, Evil Close Quarters (no other page's), Suspended, Silver and Gold, Full Ride | 2026-11-26: Ebbinghaus on Hair of the Dog (full render, 11 s); sheets of all 7 kinds on Talk, 8 seeds on Notta Problem, timing on Evil Close Quarters and Suspended | @ruler.says.no · @measured.illusions · @same.length.lab |
| Colour Lies | `colour_lies` / `hue` | `studio/hue_video.py` | classic colour illusions (Munker-White bars, confetti dots, Bezold spreading, simultaneous contrast) asked as a question ('same colour, or not?', 'what colour are the dots?', 'which red is brighter?'), then proven on the beat: an eyedropper takes one pixel from each piece, the two swatches slide together until they touch and show the hex code read off the frame ('#A8A096 #A8A096'), the stripes fade to grey ('the same colour.'), then it all comes back ('same colour. still looks different.'). Drawn in code, three colour sets per kind, dark or light page, no finishing pass so the codes are exact. Sub-niche of the illusion pages (best median views) but colour, which no page does (rotation.illusions: motion; eye.trick.lab: afterimages; ruler.says.no: size and lines). Songs: Myth of Sisyphus, Prologue, Passage (Waiting), Epilogue (no other ready page's), Talk, Evil Close Quarters | 2026-11-26: Munker (lime) on Myth of Sisyphus (full render, 11.7 s); sheets of all kinds and sets on Myth of Sisyphus and Talk, timing on all six songs | @colour.lies · @same.hex.code · @one.colour.two |

## Wiring one (after Dylan creates it)
1. `accounts.yaml`: `<x>_ig` (the name already in the campaign's `accounts.names`), provider instagram, login facebook,
   `api_key_secret: IG_TOKEN`, `channel_id` from the tokens run log; `tests/test_accounts.py` count; `dash_data.py` HANDLES.
2. Campaign `config.yaml`: `paused: false`, `dry_run: false` (posts_per_day is already 1 for the first week).
3. `studio/nightly.yaml`: drop the target's `paused: true`.
4. Merge, then `studio.yml` (campaign=<c>), `render.yml`, `topup.yml`, one at a time.
