# Ready pages

Back to [[README]] · see [[accounts]], [[add-account]], [[backlog]]. Pages that are **built, rendered, sampled and
paused**, waiting only for their Instagram account. The every-4-hours growth job keeps at least 6 here. When Dylan
creates the account (one handle, switched to Creator), the page is wired by [[add-account]] and moved off this list.

Each entry: campaign, renderer, what it is, the sample that was looked at, and three handle ideas (Dylan picks one;
any that is taken, try the next).

| page | campaign / style | renderer | what it is | sample | handle ideas |
|---|---|---|---|---|---|
| Marbled by Math | `ink_marbling` / `ebru` | `studio/ebru_video.py` | paper marbling (ebru) done with the exact equations of mathematical marbling: drops of ink land on the beat and push each other into rings, then a comb, a wavy comb or a stir pulls them into a pattern (stone, gelgit, nonpareil, tulip hearts, stir, wave); six palettes, three baths; drop and stroke counter; the last line is true (no move changes a drop's area). Sub-niche of the fluid format (physics.bounce.lab's fluid videos: median 632 views, second only to illusions) but its own look, voice and songs (Talk, Full Ride, Fixation, Subway Maintenance, Recess, Won't Be the Same Again) | 2026-11-26: tulip on Full Ride (full render); sheets of all six patterns on Talk | @marbled.by.math · @ink.on.water.lab · @ebru.equations |

## Wiring one (after Dylan creates it)
1. `accounts.yaml`: `<x>_ig` (the name already in the campaign's `accounts.names`), provider instagram, login facebook,
   `api_key_secret: IG_TOKEN`, `channel_id` from the tokens run log; `tests/test_accounts.py` count; `dash_data.py` HANDLES.
2. Campaign `config.yaml`: `paused: false`, `dry_run: false` (posts_per_day is already 1 for the first week).
3. `studio/nightly.yaml`: drop the target's `paused: true`.
4. Merge, then `studio.yml` (campaign=<c>), `render.yml`, `topup.yml`, one at a time.
