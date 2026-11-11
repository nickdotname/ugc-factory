# Playbook

How to run a campaign day to day. `CONTEXT.md` is the history, `SPEC.md` the
original contract; this is the part you actually use.

Everything is one of three files per campaign, plus one repo-wide list of accounts:

| file | what it controls |
|---|---|
| `accounts.yaml` | every Buffer channel the repo can post to |
| `campaigns/<slug>/config.yaml` | cadence, the mix, which songs/creatives exist, where they go |
| `campaigns/<slug>/creatives/<name>/captions.txt` | captions and on-screen lines for one creative |
| `campaigns/<slug>/lineup.yaml` | posts spelled out by hand |

Changes reach the workflows when they are committed and pushed.

---

## 1. Connect a Buffer login

```bash
./ugc connect                                        # what is connected now
./ugc connect --slot 3 --name creatives_lets_create  # add a login
```

It asks for the API key (hidden), saves it to `.env` and to GitHub secrets,
asks Buffer which channels that key has, and adds each one to `accounts.yaml`.
Commit and push `accounts.yaml`. Slots 1–8 are already wired into every
workflow, so no workflow edit is ever needed. Run it again later if you connect
another network to the same login — existing channels are left alone.

A campaign posts to every account unless its config says otherwise:

```yaml
accounts:
  mode: allow            # or block
  names: [nickdotname_tt, creatives_lets_create_tt]
```

## 2. Set up a song

A **creative** is one self-contained pool: its own clips, its own track, its own
captions. For music, make one per song.

```yaml
# campaigns/closequarters/config.yaml
creatives:
  - name: sunday_song
    assets_release: assets-closequarters-sunday_song
    weight: 2                         # picked twice as often
    music_cues:
      music_01.mp3: [42.5, 73]        # the song only ever starts here
    accounts: [nickdotname_tt, nickdotname_ig]   # omit = everywhere
```

Then:

1. Drop clips in `inbox/closequarters-sunday_song/hooks/` and the track in
   `.../music/` (or use the dashboard: `./ugc web --campaign closequarters`),
   and run `./ugc ingest --campaign closequarters --creative sunday_song`.
   Files are renamed `hook_01.mp4`, `music_01.mp3`, … on upload.
2. Add the track to `campaigns/closequarters/creatives/sunday_song/LICENSES.md`.
3. Write `campaigns/closequarters/creatives/sunday_song/captions.txt`:

```
overlay: how bro starts moving | when this comes on
title: Sunday Song – Close Quarters
Sunday Song – Close Quarters
out now everywhere

#closequarters #newmusic
---
overlay: this part. every single time.
Sunday Song – Close Quarters, link in bio
```

`overlay:` is drawn on the video (a `|` forces a line break; no emoji).
`title:` is the YouTube title. The rest is the caption. A network-specific
version goes in `creatives/sunday_song/captions/tiktok.txt` (same format).

## 3. What controls what

| you want | set |
|---|---|
| song loud, clip silent | `composition.music_volume: 1.0`, `clip_volume: 0.0` |
| the song to start on an exact second | `creatives[].music_cues` |
| one clip per video | `composition.bodies_per_video: 0` |
| a 3-second clip to be usable | `composition.loop_to_min: true` |
| text on the video | an `overlay:` line on the caption record (size and position: the `overlay:` block in config) |
| a clip out of rotation | `./ugc clips --campaign X --off hook_03.mp4` |
| a song to post more / less | `creatives[].weight` |
| a song on certain accounts only | `creatives[].accounts` |
| how many per day, and when | `posting.posts_per_day`, `start_hour`, `end_hour` |
| a different caption per network | `captions/<network>.txt` |
| stop a campaign without losing anything | `posting.paused: true` |
| nothing random at all | `selection.auto_fill: false` + the lineup |

## 4. The lineup — exact posts

`lineup.yaml` is for "this clip, on this lyric, with this line, Friday at six".

```yaml
posts:
  - id: bro-moving-01
    creative: sunday_song
    hook: hook_03.mp4
    music: music_01.mp3
    music_start: 42.5
    overlay: how bro starts moving | when this comes on
    caption: |
      Sunday Song – Close Quarters
      out now everywhere
    accounts: [nickdotname_tt]       # omit = wherever the song goes
    at: 2026-11-14 18:00             # omit = next free slot
```

Lineup posts render before anything random. Each `id` posts once and is then
remembered, so finished entries can stay in the file. A timed post renders up
to two days ahead; if its time passes before it ever rendered, it is reported
to Discord and **not** posted late.

## 5. See it, and pull it

```bash
./ugc render --campaign closequarters --plan     # what tonight would make
./ugc queue  --campaign closequarters            # every queued video, in full
./ugc queue  --campaign closequarters --discard pushed --id 3eb6087b
./ugc queue  --campaign closequarters --discard pushed --id 3eb6087b --account nickdotname_tt
```

`--discard pushed` also deletes the post from Buffer, through whichever login
holds it. Once a network has published, only the network can take it down.
Buffer's own queue is the last review window: a pushed post sits there, visible
and deletable, until its time.

## 6. Going live

`closequarters` ships with `paused: true` and `dry_run: true`.

1. Set up at least one song (section 2).
2. `paused: false`, keep `dry_run: true`. Run the **render** workflow by hand
   and watch a video from the Release it creates. Or locally: the dashboard's
   Sample button.
3. `./ugc preflight --campaign closequarters`.
4. `dry_run: false`. The next render and top-up post for real.

## 7. Limits worth knowing

- **No official sounds.** Buffer can only post a finished video file, so the
  song is baked into the audio. A post made this way is not attached to the
  track's sound page on TikTok or Instagram. For posts that must carry the
  official sound, post those by hand in the app.
- **Buffer's free plan**: 10 queued posts per channel, 3,000 API requests per
  login per 30 days, 31 days of metrics history.
- **Text**: the bundled font has no emoji; they are dropped from overlays.
- **The dashboard** shows and pulls queued posts and previews samples, but the
  lineup and cue points are edited in their files.
