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
| `glitch` | footage theme (water, nature, city, space, archive, mixed), treatment (datamosh, blob tracking, pixel sort, slit-scan, point cloud), accent (rgb drift, macroblocks, none), tone (natural, thermal, mono, duotone, xray, night), pace, REC label |
| `physics` | scene (ring, shrinking square, escape rings, pendulum wave), hit source (drums, kick, bass, melody), palette, trail, opening line |
| `ascii` | scene (ringed planet, Sisyphus and the boulder, jellyfish), letters (classic, dense, blocks), palette (the scene's own, sunset, reef, terminal, ember, ice, mono), layout (code panel, clean), sparks on the snare |
| `earth` | scene (every satellite, every airliner, this month's earthquakes), palette (night, blueprint, ember, paper), spin, opening line (fact, question) |
| `math` | topic (integral, Fourier series, derivative), theme (midnight, chalk, synth, mono, paper), typeface, background (grid, dots, none), shake strength, glow, step labels (pill, tag) |

The `ascii` style (`ascii_video.py`) raymarches a scene from `asciiviz/` once per character cell and draws it in letters,
with the scene's code scrolling underneath; add a scene by adding a module there (see `planet.py`) and its name to `SCENES`.
Run one by hand with `CQ_WINDOW=33,51 python studio/ascii_video.py studio/songs/talk 7 out.mp4` (`--frames 30,200` for a sheet).

The `math` style (Math In Time, `math_video.py`) is a short explainer choreographed in beats: eleven bars,
whatever the song's tempo. Each topic is a scene in `mathviz/`; add a topic by adding a scene there and its name to
`TOPICS`. Run one by hand with `python studio/mathviz/integral.py out.mp4 --seed 3` (`--frames 30,200` for a contact sheet).

`LEARNED.md` lists every knob's options with their numbers, and what has been retired.

## A song directory

```
studio/songs/<song>/
  song.json          title, track number, key, where the project lines up with the master
  lines.json         the lyrics, word by word, with times in seconds into the master
  arrangement.json   tempo, tracks and MIDI notes from the Ableton project
  project_hits.json  every hit in the arranged project (MIDI notes and audio-clip attacks), each track's role,
                     and where the project sits in the master; physics videos take every collision from it
  queries.json       search terms for pictures, per lyric line
  media_keep.json    which fetched pictures were kept
  master.wav         NOT in git — the released master
  stems/             NOT in git — Vocals.flac, Drums.flac, Bass.flac, Other.flac
  media/<line>/      NOT in git — pictures per lyric line (optional, hand-picked)
  pictures.json      searches per lyric line; the photos job finds them on Wikimedia Commons
```

- `arrangement.json` comes from `python studio/als_arrangement.py project.als`.
- `project_hits.json`: `python studio/als_hits.py project.als hits.json` on the machine with the project folder
  (it reads the audio files the clips play), then `python studio/project_sync.py <song> hits.json`, which lines the
  project up with the stems (shift and speed, to a few ms) and names untitled tracks ("14-Audio") by which stem's
  kicks, snares or notes their hits land on. Songs with one: Prologue (closelydian), Hair of the Dog
  (closequarterselectronic), Fixation (closeclose), Talk (talktoyobitch), Full Ride (earl), Suspended
  (closesssssssllose). The physics style only renders songs that have it.
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
- `pictures.json` is the way that runs by itself: `{"lines": {"12": ["vintage microphone"]}}`
  names what a line should show (the song's own line numbers, from 0). The photos
  workflow finds each one on Wikimedia Commons, public domain and CC0 only since a
  video has nowhere to put a credit, stores it in `studio/photos/` and records the
  choice in `studio/photos/queries.json`. Band videos show a line's picture in a
  viewer window; producer videos as a card over the stems. How often is a knob
  (`pictures`), so the learner finds out whether pictures help.

## Adding a song

Copy a song directory, replace the five data files, and render a contact
sheet. Nothing in `lyric_video.py` names a song.
