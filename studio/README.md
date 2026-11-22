# studio

Makes the videos the pipeline posts. Separate from `src/` on purpose: it needs
audio libraries and a song's stems, and its output is an ordinary `.mp4` that
goes into a campaign like any other clip (dashboard upload, or `ugc ingest`).

## What it makes

`lyric_video.py` draws two kinds of video from one song's own project data:

| style | for | what it looks like |
|---|---|---|
| `band` | the band account | a retro desktop: each lyric line gets its own window (notepad, paint, error dialogs, the arrangement, pictures that match the line) with the words lighting up in time |
| `producer` | a producer account | clean stem waveforms and the real MIDI notes scrolling past a playhead, lyrics on top |

```bash
pip install -r studio/requirements.txt          # plus ffmpeg on the PATH
python studio/lyric_video.py studio/songs/notta-problem band 3 studio/out/np-band-3.mp4
python studio/lyric_video.py studio/songs/notta-problem producer 8 studio/out/np-prod-8.mp4
```

The number is a seed. The same seed always gives the same video; a different
seed gives a different one (other scenes, overlays, background, palette,
pictures). `--frames 20,300,600` writes a contact sheet of those frames
instead of a video, which is the quick way to check a seed before rendering.

## The recipe

Every render writes `<name>.json` beside the video: the seed and every choice
it made. Keep it with the video. Attribution already ranks clips by file name,
so a clip's recipe is what turns "this video did well" into "videos with
pictures and the tiled background do well".

## How it improves itself

Every choice a renderer makes goes through `knobs.py` (`knobs.pick('wall', WALLS, rng)`),
so each one is recorded with its whole menu in the recipe. Each night `learn.py`
scores every option of every knob from the posts' numbers (completion, sends,
views, saves, not skipped; recent posts count more), and `nightly.py` sets each
new video's knobs by Thompson sampling: winners are chosen most, options with few
posts still get tried, and an option that keeps losing after 8+ posts is retired.
One video in five is left to chance. To add a look, add it to a knob's list in
the renderer: it is tried from the next night on, with nothing else to change.

| style | knobs |
|---|---|
| `band` | window style (Win95 / XP / Mac platinum), wallpaper (plasma, tiles, rings, gradient, stars, clouds, hills, equaliser), colour theme, lyric typeface, glitch amounts |
| `producer` | layout (stem lanes / mixing desk), wallpaper, colours, lyric typeface, glitch amounts |
| `psy` | pattern (14, incl. oil light show, Julia set, spiral, moiré, smoke, cells), palette (11), speed, symmetry, mirror, feedback, strobe, motif, lyrics |
| `liminal` | place (backrooms, pool, mall, hotel, office, car park, school), pace, tint, tape wear, PLAY/REC label, date stamp |

`LEARNED.md` lists every knob's options with their numbers, and what has been retired.

## A song directory

```
studio/songs/<song>/
  song.json          title, track number, key, where the project lines up with the master
  lines.json         the lyrics, word by word, with times in seconds into the master
  arrangement.json   tempo, tracks and MIDI notes from the Ableton project
  queries.json       search terms for pictures, per lyric line
  media_keep.json    which fetched pictures were kept
  master.wav         NOT in git — the released master
  stems/             NOT in git — Vocals.flac, Drums.flac, Bass.flac, Other.flac
  media/<line>/      NOT in git — pictures per lyric line
```

- `arrangement.json` comes from `python studio/als_arrangement.py project.als`.
- `stems/` come from any four-stem separator run on the stretch of the master
  the video uses; `stems_start_sec` in `song.json` says where that stretch begins.
- `offset_sec` is the one number that has to be right: a project beat `b` sounds
  at `b * 60 / tempo + offset_sec` seconds into the master. Find it by lining
  the project's bass or drum notes up against the separated stem, not the full
  mix (the full mix locks onto the wrong repeat of a looping pattern).
- `media/` comes from `python studio/fetch_media.py studio/songs/<song>/queries.json`,
  which keeps only public-domain and CC0 results and logs every source. Search
  results are noisy: look through them and delete what does not fit before
  rendering. `media_credits.json` is that log for the pictures in use.

## Adding a song

Copy a song directory, replace the five data files, and render a contact
sheet. Nothing in `lyric_video.py` names a song.
